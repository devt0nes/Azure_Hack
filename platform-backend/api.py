# api.py
import asyncio
import uuid
from fastapi import FastAPI, HTTPException
from models import (
    TaskLedger, AEG, AgentNode, AEGEdge,
    ClarifyRequest, AEGRequest, ApproveRequest, DeltaRequest, ExecuteRequest
)
import cosmos_client as db
import director
import validator
import delta_aeg
import guardrails
import service_bus_listener

app = FastAPI()


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    asyncio.create_task(service_bus_listener.listen_for_commands())


# ── Dev 1 endpoints (unchanged) ────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "Director service running"}


@app.post("/clarify")
async def clarify(req: ClarifyRequest):
    try:
        project_id = req.project_id or str(uuid.uuid4())
        history = db.get_conversation(project_id)
        history.append({"role": "user", "content": req.message})
        result = await director.run_clarification(history)
        if result["action"] == "TASK_LEDGER_COMPLETE":
            ledger = TaskLedger(project_id=project_id, id=project_id, **result["task_ledger"])
            db.save_task_ledger(ledger)
            db.save_conversation(project_id, history)
            return {"status": "complete", "project_id": project_id,
                    "message": "Task Ledger saved! Now call POST /aeg"}
        elif result["action"] == "GUARDRAIL":
            history.append({"role": "assistant", "content": result["question"]})
            db.save_conversation(project_id, history)
            return {"status": "guardrail", "project_id": project_id,
                    "risk": result["risk"], "recommendation": result["recommendation"],
                    "question": result["question"]}
        else:
            history.append({"role": "assistant", "content": result["question"]})
            db.save_conversation(project_id, history)
            return {"status": "asking", "project_id": project_id, "question": result["question"]}
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


@app.post("/aeg")
async def generate_aeg_route(req: AEGRequest):
    try:
        ledger = db.get_task_ledger(req.project_id)
        val = await validator.validate(ledger)
        blockers = [i for i in val["issues"] if i["severity"] == "blocker"]
        if blockers:
            return {"status": "blocked", "issues": blockers,
                    "message": "Resolve blockers before AEG can be generated"}
        raw = await director.generate_aeg(ledger)
        if director.has_cycle(raw["nodes"], raw["edges"]):
            raw = await director.generate_aeg(ledger)
            if director.has_cycle(raw["nodes"], raw["edges"]):
                raise HTTPException(500, "AEG generation produced circular dependency twice")
        aeg = AEG(
            id=req.project_id, project_id=req.project_id,
            nodes=[AgentNode(**n) for n in raw["nodes"]],
            edges=[AEGEdge(**e) for e in raw["edges"]],
            status="PENDING_APPROVAL"
        )
        db.save_aeg(aeg)
        return {"status": "awaiting_approval", "project_id": req.project_id,
                "aeg": aeg.model_dump(), "message": "AEG generated! Now call POST /approve"}
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


@app.post("/approve")
async def approve_aeg(req: ApproveRequest):
    try:
        aeg_data = db.get_aeg(req.project_id)
        if req.approved:
            aeg_data["status"] = "APPROVED"
            db.save_aeg(AEG(**aeg_data))
            from azure.servicebus.aio import ServiceBusClient
            from azure.servicebus import ServiceBusMessage
            from config import SB_CONN, SB_QUEUE
            import json
            async with ServiceBusClient.from_connection_string(SB_CONN) as sb:
                sender = sb.get_queue_sender(SB_QUEUE)
                async with sender:
                    msg = ServiceBusMessage(json.dumps({
                        "command": "EXECUTE_AEG",
                        "project_id": req.project_id
                    }))
                    await sender.send_messages(msg)
            return {"status": "approved", "project_id": req.project_id,
                    "message": "AEG approved! Service Bus notified. Dev 2 will start execution."}
        else:
            aeg_data["status"] = "REVISION_REQUESTED"
            aeg_data["revision_notes"] = req.notes or ""
            db.save_aeg(AEG(**aeg_data))
            return {"status": "revision_needed", "project_id": req.project_id,
                    "message": "AEG sent back for revision"}
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


@app.post("/delta")
async def delta(req: DeltaRequest):
    try:
        risk = guardrails.screen_message(req.change_description)
        if risk:
            return {"status": "guardrail", "project_id": req.project_id,
                    "risk": risk["risk"], "recommendation": risk["recommendation"],
                    "message": "Risky pattern detected in change request"}
        result = await delta_aeg.apply_delta(req.project_id, req.change_description)
        if result["conflict"]:
            return {"status": "conflict_detected", "project_id": req.project_id,
                    "change_type": result["change_type"], "conflict": result["conflict"],
                    "message": "This change conflicts with a previous structural decision"}
        return {"status": "accepted", "project_id": req.project_id,
                "change_type": result["change_type"],
                "message": f"{result['change_type']} change logged successfully"}
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


# ── Dev 2 endpoints ────────────────────────────────────────────────────────────

@app.post("/execute")
async def execute(req: ExecuteRequest):
    """Manually trigger scheduler for an already-APPROVED AEG."""
    try:
        import scheduler
        aeg = db.get_aeg(req.project_id)
        if aeg["status"] != "APPROVED":
            raise HTTPException(
                status_code=400,
                detail=f"AEG status is '{aeg['status']}' — must be APPROVED before executing"
            )
        asyncio.create_task(scheduler.start(aeg))
        return {"status": "started", "project_id": req.project_id}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


@app.get("/status/{project_id}")
async def get_status(project_id: str):
    """Return the AEG-level status and per-node status for a project."""
    try:
        aeg = db.get_aeg(project_id)
        return {
            "project_id": project_id,
            "aeg_status": aeg["status"],
            "nodes": [
                {
                    "agent_id": n["agent_id"],
                    "role":     n["role"],
                    "status":   n["status"],
                    "priority": n.get("priority", "NORMAL")
                }
                for n in aeg["nodes"]
            ]
        }
    except Exception:
        raise HTTPException(status_code=404, detail=f"No AEG found for project {project_id}")


@app.get("/costs/{project_id}")
async def get_costs(project_id: str):
    """Return per-model cost breakdown and savings vs an all-GPT-4o baseline."""
    try:
        records = db.get_cost_records(project_id)
        if not records:
            return {"project_id": project_id, "total_cost_usd": 0, "message": "No cost records yet"}

        total_cost   = sum(r["cost_usd"] for r in records)
        total_tokens = sum(r["tokens"]   for r in records)

        by_model: dict = {}
        for r in records:
            m = r["model"]
            by_model.setdefault(m, {"calls": 0, "tokens": 0, "cost_usd": 0.0})
            by_model[m]["calls"]    += 1
            by_model[m]["tokens"]   += r["tokens"]
            by_model[m]["cost_usd"] += r["cost_usd"]

        # Round per-model costs for display
        for m in by_model:
            by_model[m]["cost_usd"] = round(by_model[m]["cost_usd"], 4)

        # Savings vs hypothetical all-GPT-4o run
        GPT4O_RATE_PER_1K = 0.005
        baseline_cost = (total_tokens / 1000) * GPT4O_RATE_PER_1K

        return {
            "project_id":                      project_id,
            "total_cost_usd":                  round(total_cost, 4),
            "total_tokens":                    total_tokens,
            "by_model":                        by_model,
            "savings_vs_gpt4o_baseline_usd":   round(baseline_cost - total_cost, 4)
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}

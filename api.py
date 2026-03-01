# api.py
from fastapi import FastAPI, HTTPException
from models import TaskLedger, AEG, AgentNode, AEGEdge, ClarifyRequest, AEGRequest, ApproveRequest, DeltaRequest
import cosmos_client as db
import director
import validator
import delta_aeg
import guardrails
import uuid

app = FastAPI()

@app.get("/")
def root():
    return {"status": "Director service running"}


# ── POST /clarify ──────────────────────────────────────────
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


# ── POST /aeg ──────────────────────────────────────────────
@app.post("/aeg")
async def generate_aeg_route(req: AEGRequest):
    try:
        ledger = db.get_task_ledger(req.project_id)

        # 1. Validate — block on blocker severity issues
        val = await validator.validate(ledger)
        blockers = [i for i in val["issues"] if i["severity"] == "blocker"]
        if blockers:
            return {"status": "blocked", "issues": blockers,
                    "message": "Resolve blockers before AEG can be generated"}

        # 2. Generate AEG
        raw = await director.generate_aeg(ledger)

        # 3. Cycle check — regenerate once if cycle detected
        if director.has_cycle(raw["nodes"], raw["edges"]):
            raw = await director.generate_aeg(ledger)
            if director.has_cycle(raw["nodes"], raw["edges"]):
                raise HTTPException(500, "AEG generation produced circular dependency twice")

        # 4. Save AEG
        aeg = AEG(
            id=req.project_id,
            project_id=req.project_id,
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


# ── POST /approve ──────────────────────────────────────────
@app.post("/approve")
async def approve_aeg(req: ApproveRequest):
    try:
        aeg_data = db.get_aeg(req.project_id)

        if req.approved:
            aeg_data["status"] = "APPROVED"
            db.save_aeg(AEG(**aeg_data))

            # Notify Dev 2 via Service Bus
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


# ── POST /delta ────────────────────────────────────────────
@app.post("/delta")
async def delta(req: DeltaRequest):
    try:
        # 1. Screen for risky patterns first
        risk = guardrails.screen_message(req.change_description)
        if risk:
            return {
                "status":         "guardrail",
                "project_id":     req.project_id,
                "risk":           risk["risk"],
                "recommendation": risk["recommendation"],
                "message":        "Risky pattern detected in change request"
            }

        # 2. Classify and check for conflicts
        result = await delta_aeg.apply_delta(req.project_id, req.change_description)

        if result["conflict"]:
            return {
                "status":      "conflict_detected",
                "project_id":  req.project_id,
                "change_type": result["change_type"],
                "conflict":    result["conflict"],
                "message":     "This change conflicts with a previous structural decision"
            }

        return {
            "status":      "accepted",
            "project_id":  req.project_id,
            "change_type": result["change_type"],
            "message":     f"{result['change_type']} change logged successfully"
        }

    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}
# scheduler.py
from collections import deque
from datetime import datetime
from models import AEG
import cosmos_client as db
import asyncio

MAX_CONCURRENT          = 8    # Max agents running at the same time across all batches
STARVATION_TIMEOUT_SECS = 600  # 10 minutes before a PENDING agent gets ELEVATED priority
BATCH_POLL_INTERVAL     = 3    # Seconds between batch-completion checks
CAPACITY_POLL_INTERVAL  = 5    # Seconds between concurrency-limit checks


# ── Topological sort ──────────────────────────────────────────────────────────

def get_execution_batches(aeg: dict) -> list[list[str]]:
    """
    Kahn's algorithm over the AEG DAG.
    Returns a list of batches — agents within the same batch have no
    inter-dependencies and can safely run in parallel.
    """
    nodes     = {n["agent_id"] for n in aeg["nodes"]}
    graph     = {n: [] for n in nodes}
    in_degree = {n: 0 for n in nodes}

    for edge in aeg["edges"]:
        graph[edge["from_agent"]].append(edge["to_agent"])
        in_degree[edge["to_agent"]] += 1

    queue   = deque(n for n in in_degree if in_degree[n] == 0)
    batches = []
    while queue:
        batch = list(queue)
        batches.append(batch)
        queue.clear()
        for node in batch:
            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

    return batches


# ── Node helper ───────────────────────────────────────────────────────────────

def get_node(aeg: dict, agent_id: str) -> dict:
    return next(n for n in aeg["nodes"] if n["agent_id"] == agent_id)


# ── State machine writer ──────────────────────────────────────────────────────

async def update_status(project_id: str, agent_id: str, status: str):
    """
    Valid transitions:
      PENDING      → RUNNING
      RUNNING      → COMPLETED | FAILED | SLEEPING | RATE_LIMITED
      RATE_LIMITED → RUNNING   (after Retry-After window)
      SLEEPING     → RUNNING   (when a dormant dependency completes)
    """
    aeg = db.get_aeg(project_id)
    for node in aeg["nodes"]:
        if node["agent_id"] == agent_id:
            node["status"]     = status
            node["updated_at"] = datetime.utcnow().isoformat()
            if status == "RUNNING":
                node["started_at"] = datetime.utcnow().isoformat()
            # Stamp pending_since on the first PENDING write so starvation monitor works
            if status == "PENDING" and not node.get("pending_since"):
                node["pending_since"] = datetime.utcnow().isoformat()
            break
    db.save_aeg(AEG(**aeg))


# ── Starvation monitor ────────────────────────────────────────────────────────

async def starvation_monitor(project_id: str):
    """
    Background task — runs for the lifetime of an execution.
    Any agent stuck in PENDING for > 10 minutes gets priority = ELEVATED,
    which causes the scheduler to front-run it in the next available slot.
    """
    while True:
        await asyncio.sleep(60)
        aeg = db.get_aeg(project_id)

        if aeg["status"] in ("COMPLETED", "FAILED"):
            break  # Execution finished — stop monitoring

        now     = datetime.utcnow()
        changed = False
        for node in aeg["nodes"]:
            if node["status"] == "PENDING" and node.get("pending_since"):
                since   = datetime.fromisoformat(node["pending_since"])
                elapsed = (now - since).total_seconds()
                if elapsed > STARVATION_TIMEOUT_SECS and node.get("priority") != "ELEVATED":
                    node["priority"] = "ELEVATED"
                    changed = True
                    print(f"[STARVATION] Agent {node['agent_id']} elevated after "
                          f"{int(elapsed)}s wait")

        if changed:
            db.save_aeg(AEG(**aeg))


# ── Main execution loop ───────────────────────────────────────────────────────

async def start(aeg: dict):
    project_id = aeg["project_id"]
    print(f"[Scheduler] Starting execution for project {project_id}")

    # Mark AEG as executing
    aeg["status"] = "EXECUTING"
    db.save_aeg(AEG(**aeg))

    asyncio.create_task(starvation_monitor(project_id))

    batches = get_execution_batches(aeg)
    print(f"[Scheduler] {len(batches)} batch(es) planned: {batches}")

    for batch_idx, batch in enumerate(batches):
        print(f"[Scheduler] Batch {batch_idx + 1}/{len(batches)}: {batch}")

        # Re-fetch AEG so priority flags from starvation monitor are current
        aeg = db.get_aeg(project_id)

        # ELEVATED agents go first within the batch
        sorted_batch = sorted(
            batch,
            key=lambda aid: 0 if get_node(aeg, aid).get("priority") == "ELEVATED" else 1
        )

        running_count = sum(1 for n in aeg["nodes"] if n["status"] == "RUNNING")

        for agent_id in sorted_batch:
            # Block until a slot opens if we're at the concurrency limit
            while running_count >= MAX_CONCURRENT:
                await asyncio.sleep(CAPACITY_POLL_INTERVAL)
                aeg          = db.get_aeg(project_id)
                running_count = sum(1 for n in aeg["nodes"] if n["status"] == "RUNNING")

            await update_status(project_id, agent_id, "RUNNING")
            running_count += 1
            print(f"[Scheduler] Agent {agent_id} → RUNNING")

        # Wait for every agent in this batch to reach a terminal state
        # before unlocking the next batch
        while True:
            await asyncio.sleep(BATCH_POLL_INTERVAL)
            aeg            = db.get_aeg(project_id)
            batch_statuses = [get_node(aeg, a)["status"] for a in batch]
            if all(s in ("COMPLETED", "FAILED", "SLEEPING") for s in batch_statuses):
                failed = [a for a in batch if get_node(aeg, a)["status"] == "FAILED"]
                if failed:
                    print(f"[Scheduler] Batch {batch_idx + 1} finished with failures: {failed}")
                break

    # Final AEG status — COMPLETED only if every node succeeded
    aeg          = db.get_aeg(project_id)
    all_statuses = [n["status"] for n in aeg["nodes"]]
    aeg["status"] = "COMPLETED" if all(s == "COMPLETED" for s in all_statuses) else "FAILED"
    db.save_aeg(AEG(**aeg))
    print(f"[Scheduler] Project {project_id} → {aeg['status']}")

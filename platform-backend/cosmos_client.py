# cosmos_client.py
from config import cosmos_db
from models import TaskLedger, AEG

task_ledgers  = cosmos_db.get_container_client("task_ledgers")
aeg_store     = cosmos_db.get_container_client("aeg_state")
conversations = cosmos_db.get_container_client("conversations")
costs         = cosmos_db.get_container_client("cost_records")   # Dev 2 owns this


# ── Task Ledger ───────────────────────────────────────────────────────────────

def save_task_ledger(ledger: TaskLedger):
    task_ledgers.upsert_item(body=ledger.model_dump())

def get_task_ledger(project_id: str) -> dict:
    return task_ledgers.read_item(item=project_id, partition_key=project_id)


# ── AEG ───────────────────────────────────────────────────────────────────────

def save_aeg(aeg: AEG):
    aeg_store.upsert_item(body=aeg.model_dump())

def get_aeg(project_id: str) -> dict:
    return aeg_store.read_item(item=project_id, partition_key=project_id)


# ── Conversations ─────────────────────────────────────────────────────────────

def save_conversation(project_id: str, history: list):
    conversations.upsert_item({
        "id":         project_id,
        "project_id": project_id,
        "history":    history
    })

def get_conversation(project_id: str) -> list:
    try:
        doc = conversations.read_item(item=project_id, partition_key=project_id)
        return doc.get("history", [])
    except:
        return []


# ── Cost Records (Dev 2) ──────────────────────────────────────────────────────

def save_cost_record(record: dict):
    costs.upsert_item(body=record)

def get_cost_records(project_id: str) -> list:
    return list(costs.query_items(
        query="SELECT * FROM c WHERE c.project_id = @pid",
        parameters=[{"name": "@pid", "value": project_id}],
        enable_cross_partition_query=True
    ))

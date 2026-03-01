# delta_aeg.py
from config import openai_client, GPT4O, MINI
import cosmos_client as db
import json

COSMETIC_KEYWORDS = [
    "rename", "restyle", "color", "font", "wording",
    "typo", "reorder", "comment", "rewrite description"
]

STRUCTURAL_KEYWORDS = [
    "add module", "new service", "change database", "add api",
    "new auth", "remove module", "switch to", "replace with",
    "add microservice", "new endpoint", "add feature"
]


async def classify_change(description: str) -> str:
    """
    Classifies a change request as COSMETIC or STRUCTURAL.
    First tries keyword matching, then falls back to GPT-4o-mini.
    """
    desc = description.lower()

    if any(k in desc for k in COSMETIC_KEYWORDS):
        return "COSMETIC"

    if any(k in desc for k in STRUCTURAL_KEYWORDS):
        return "STRUCTURAL"

    # Ambiguous — ask the model
    response = await openai_client.chat.completions.create(
        model=MINI,
        messages=[{
            "role": "user",
            "content": (
                f"Is this change request COSMETIC (rename/style/wording) "
                f"or STRUCTURAL (new module/service/database/feature)?\n"
                f"Change: {description}\n"
                f"Reply with ONE word only: COSMETIC or STRUCTURAL"
            )
        }]
    )
    return response.choices[0].message.content.strip().upper()


async def detect_conflict(new_request: str, project_id: str) -> dict | None:
    """
    Checks if the new change conflicts with previous structural decisions.
    Returns a conflict dict if conflict found, None if compatible.
    """
    ledger = db.get_task_ledger(project_id)
    prev_deltas = [
        r for r in ledger.get("revision_history", [])
        if r.get("type") == "STRUCTURAL"
    ]

    if not prev_deltas:
        return None  # No previous structural changes to conflict with

    prev_summary = json.dumps([d["description"] for d in prev_deltas[-3:]])

    response = await openai_client.chat.completions.create(
        model=GPT4O,
        messages=[{
            "role": "user",
            "content": (
                f"Are these structural changes to a software project compatible?\n"
                f"Previous decisions: {prev_summary}\n"
                f"New request: {new_request}\n"
                f"Reply ONLY with valid JSON: "
                f"{{\"conflict\": true/false, \"reason\": \"...\"}}"
            )
        }],
        response_format={"type": "json_object"}
    )

    result = json.loads(response.choices[0].message.content)
    return result if result["conflict"] else None


async def apply_delta(project_id: str, change_description: str) -> dict:
    """
    Main function called by POST /delta endpoint.
    Classifies the change, checks for conflicts, updates the ledger.
    """
    change_type = await classify_change(change_description)
    conflict = None

    if change_type == "STRUCTURAL":
        conflict = await detect_conflict(change_description, project_id)

    # Log the change into revision_history
    ledger = db.get_task_ledger(project_id)
    from datetime import datetime
    ledger["revision_history"].append({
        "type":        change_type,
        "description": change_description,
        "timestamp":   datetime.utcnow().isoformat()
    })
    from models import TaskLedger
    db.save_task_ledger(TaskLedger(**ledger))

    return {
        "change_type": change_type,
        "conflict":    conflict
    }
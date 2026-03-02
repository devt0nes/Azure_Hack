# validator.py
from config import openai_client, MINI
import json

VALIDATOR_PROMPT = """
You are a software architecture validator. Review the Task Ledger for anti-patterns.

Check for ALL of these specifically:
  missing_auth       — app handles user data or accounts but no auth strategy defined
  circular_dependency — agent A needs output from B, and B needs output from A
  undefined_contracts — agents reference data shapes not described anywhere
  no_db_strategy     — app stores persistent data but no database choice/schema mentioned
  no_error_handling  — no mention of failure scenarios, retries, or fallback behaviour
  missing_env_secrets — credentials or API keys mentioned inline rather than as env vars

Return ONLY valid JSON — no markdown, no preamble:
{"passed": true/false, "issues": [
  {"type": "missing_auth", "description": "...", "severity": "blocker|warning"}
]}
"""

async def validate(task_ledger: dict) -> dict:
    response = await openai_client.chat.completions.create(
        model=MINI,
        messages=[
            {"role": "system", "content": VALIDATOR_PROMPT},
            {"role": "user", "content": json.dumps(task_ledger)}
        ],
        temperature=0.1,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)
# guardrails.py

RISK_PATTERNS = {
    "no_auth":         ["no auth", "no authentication", "public access", "skip login", "without login"],
    "plaintext_creds": ["hardcode", "store password", "plaintext", "no encryption", "hardcoded key"],
    "wrong_db":        ["mongodb for financial", "nosql for transactions", "mongo for payments"],
    "no_tests":        ["no tests", "skip testing", "dont need tests", "no unit tests"],
    "no_error":        ["no error handling", "ignore errors", "no retries", "skip error"],
}

RISK_MESSAGES = {
    "no_auth":         "App handles user data but has no authentication strategy.",
    "plaintext_creds": "Credentials or secrets are being stored insecurely.",
    "wrong_db":        "NoSQL database chosen for financial/transactional data.",
    "no_tests":        "No testing strategy defined — bugs may go undetected.",
    "no_error":        "No error handling strategy — failures may crash the system.",
}

RECOMMENDATIONS = {
    "no_auth":         "Use JWT or OAuth2 for authentication.",
    "plaintext_creds": "Store all secrets in environment variables, never in code.",
    "wrong_db":        "Use PostgreSQL or another relational DB for financial data.",
    "no_tests":        "Add at least unit tests and integration tests.",
    "no_error":        "Add try/except blocks, retries, and fallback behaviour.",
}

def screen_message(user_message: str) -> dict | None:
    """
    Screens a user message for risky patterns.
    Returns a risk dict if found, None if clean.
    """
    msg = user_message.lower()
    for risk_type, patterns in RISK_PATTERNS.items():
        if any(p in msg for p in patterns):
            return {
                "risk_type":      risk_type,
                "risk":           RISK_MESSAGES[risk_type],
                "recommendation": RECOMMENDATIONS[risk_type]
            }
    return None  # No risk detected — message is clean


def log_override(task_ledger: dict, risk_type: str, recommendation: str, user_decision: str):
    """
    Logs a guardrail override into the task ledger's guardrail_overrides list.
    user_decision = "override" or "accepted_recommendation"
    """
    from datetime import datetime
    task_ledger["guardrail_overrides"].append({
        "risk_type":      risk_type,
        "recommendation": recommendation,
        "user_decision":  user_decision,
        "timestamp":      datetime.utcnow().isoformat()
    })
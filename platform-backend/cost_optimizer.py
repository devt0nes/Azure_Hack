# cost_optimizer.py
import asyncio
from datetime import datetime
from config import openai_client, GPT4O, MINI, O1
import cosmos_client as db


# ── Token bucket (shared TPM rate limiter per project) ────────────────────────

class TokenBucket:
    """
    One instance lives per project_id in _buckets.
    All agents in that project share it, so we never blow the Azure TPM limit.
    Blocks when usage reaches 85% of the window limit, then waits out the window.
    """
    def __init__(self, tpm_limit: int = 90000):
        self.limit        = tpm_limit
        self.used         = 0
        self.window_start = datetime.utcnow()
        self._lock        = asyncio.Lock()

    async def acquire(self, tokens_needed: int):
        async with self._lock:
            now     = datetime.utcnow()
            elapsed = (now - self.window_start).total_seconds()

            if elapsed >= 60:               # New 1-minute window
                self.used         = 0
                self.window_start = now
                elapsed           = 0

            if self.used + tokens_needed > self.limit * 0.85:
                wait = 60 - elapsed
                print(f"[RATE] TPM at {self.used}/{self.limit} — waiting {wait:.1f}s")
                await asyncio.sleep(wait)
                self.used         = 0
                self.window_start = datetime.utcnow()

            self.used += tokens_needed


_buckets: dict[str, TokenBucket] = {}

def get_bucket(project_id: str) -> TokenBucket:
    if project_id not in _buckets:
        _buckets[project_id] = TokenBucket()
    return _buckets[project_id]


# ── Model cost table ──────────────────────────────────────────────────────────

MODEL_COSTS_PER_1K = {
    MINI:  0.00015,   # gpt-4o-mini
    GPT4O: 0.005,     # gpt-4o
    O1:    0.003,     # o1-mini
}

# Cheapest → most capable; never skip backwards
ESCALATION_LADDER = [MINI, GPT4O, O1]


# ── Task classifier ───────────────────────────────────────────────────────────

COMPLEX_KEYWORDS = [
    "auth", "oauth", "security", "owasp", "architecture",
    "encryption", "jwt", "payment", "compliance", "gdpr", "algorithm"
]
MEDIUM_KEYWORDS = [
    "function", "component", "endpoint", "route", "schema",
    "migration", "test", "integration", "api", "service", "controller"
]

def classify_task(task_description: str) -> str:
    desc = task_description.lower()
    if any(k in desc for k in COMPLEX_KEYWORDS): return GPT4O
    if any(k in desc for k in MEDIUM_KEYWORDS):  return MINI
    return MINI   # Safe default — phi-4 not provisioned in this deployment


# ── Output self-validation heuristic ─────────────────────────────────────────

def passes_self_validation(output: str, task: str) -> bool:
    """Lightweight check before deciding whether to escalate to a larger model."""
    if not output or len(output) < 20:   return False
    if "i cannot" in output.lower():     return False
    if "as an ai"  in output.lower():    return False
    # Code tasks must contain at least one structural Python/JSON marker
    if any(k in task.lower() for k in ["function", "component", "schema", "endpoint", "class"]):
        return "def " in output or "class " in output or "{" in output
    return True


# ── Safe model call — treats 429 as RATE_LIMITED, not FAILED ─────────────────

async def safe_model_call(
    model: str,
    messages: list,
    project_id: str,
    agent_id: str,
    estimated_tokens: int = 2000,
) -> tuple[str, int]:
    """
    Acquires token-bucket capacity, calls the model, handles 429s gracefully.
    A 429 sets status → RATE_LIMITED (not FAILED), sleeps Retry-After,
    then retries ONCE on the SAME model without consuming an escalation step.
    """
    import scheduler  # Local import — avoids circular dependency at module load

    bucket = get_bucket(project_id)
    await bucket.acquire(estimated_tokens)

    try:
        response = await openai_client.chat.completions.create(
            model=model, messages=messages, temperature=0.2
        )
        return response.choices[0].message.content, response.usage.total_tokens

    except Exception as e:
        if "429" in str(e) or "rate_limit" in str(e).lower():
            retry_after = 30
            if hasattr(e, "response") and e.response:
                retry_after = int(e.response.headers.get("Retry-After", 30))

            await scheduler.update_status(project_id, agent_id, "RATE_LIMITED")
            print(f"[429] Agent {agent_id} rate-limited — retrying in {retry_after}s")
            await asyncio.sleep(retry_after)
            await scheduler.update_status(project_id, agent_id, "RUNNING")

            # Single retry on same model — does NOT count as escalation
            response = await openai_client.chat.completions.create(
                model=model, messages=messages, temperature=0.2
            )
            return response.choices[0].message.content, response.usage.total_tokens

        raise   # Re-raise everything else so escalation policy can handle it


# ── Cost logging ──────────────────────────────────────────────────────────────

async def log_cost(
    project_id: str, agent_id: str, task: str, model: str, tokens: int
):
    cost = (tokens / 1000) * MODEL_COSTS_PER_1K.get(model, 0.005)
    db.save_cost_record({
        "id":         f"{project_id}_{agent_id}_{datetime.utcnow().timestamp()}",
        "project_id": project_id,
        "agent_id":   agent_id,
        "task":       task,
        "model":      model,
        "tokens":     tokens,
        "cost_usd":   round(cost, 6),
        "timestamp":  datetime.utcnow().isoformat()
    })


async def log_escalation(
    project_id: str, task: str, tried: list[str], final_model: str
):
    print(
        f"[ESCALATION] project={project_id} | task='{task}' "
        f"| tried={tried} | final={final_model}"
    )


# ── Escalation policy ─────────────────────────────────────────────────────────

async def call_with_escalation(
    task: str,
    messages: list,
    start_model: str,
    project_id: str,
    agent_id: str,
) -> str:
    start_idx      = ESCALATION_LADDER.index(start_model) if start_model in ESCALATION_LADDER else 0
    escalation_log = []

    for model in ESCALATION_LADDER[start_idx:]:
        output, tokens = await safe_model_call(model, messages, project_id, agent_id)
        await log_cost(project_id, agent_id, task, model, tokens)

        if passes_self_validation(output, task):
            if escalation_log:
                await log_escalation(project_id, task, escalation_log, model)
            return output

        escalation_log.append(model)
        print(f"[ESCALATION] {model} failed validation for '{task}' — escalating")

    # All ladder tiers failed — last resort: O1 unconditionally
    output, tokens = await safe_model_call(O1, messages, project_id, agent_id)
    await log_cost(project_id, agent_id, task, O1, tokens)
    return output


# ── Public entry points ───────────────────────────────────────────────────────

async def route_call(
    task: str,
    messages: list,
    project_id: str,
    agent_id: str,
    force_model: str = None,
) -> str:
    """
    The ONLY function agents should ever call to talk to a model.
    Never call openai_client directly from anywhere else in the codebase.
    """
    model = force_model or classify_task(task)
    return await call_with_escalation(task, messages, model, project_id, agent_id)


async def healer_call(
    task: str,
    messages: list,
    project_id: str,
    agent_id: str,
) -> str:
    """
    For healer/recovery tasks — always starts at GPT-4o minimum,
    never inherits the model tier that originally failed.
    """
    return await route_call(task, messages, project_id, agent_id, force_model=GPT4O)

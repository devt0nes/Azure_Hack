# ══════════════════════════════════════════════════════════════════════════════
# CONSOLIDATED MULTI-AGENT SOFTWARE BUILD PLATFORM
# All modules merged into a single file for deployment simplicity
# ══════════════════════════════════════════════════════════════════════════════

import asyncio
import json
import uuid
from datetime import datetime
from collections import deque
from typing import Optional, Tuple
import os

# ── THIRD-PARTY IMPORTS ────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from openai import AsyncAzureOpenAI
from azure.cosmos import CosmosClient
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus import ServiceBusMessage

# ── ENVIRONMENT CONFIGURATION ────────────────────��─────────────────────────────

# Create .env file if it doesn't exist
# ==========================================
AZURE_OPENAI_ENDPOINT = "https://llama-70b-nexus-resource.openai.azure.com/"
AZURE_OPENAI_KEY = "37agtjrY9nhEVhzYxLbcCdqHq4IdU34BKJ3kpQpO1zA6z2dVYbYYJQQJ99CBACNns7RXJ3w3AAAAACOGVmhK"
AZURE_OPENAI_DEPLOYMENT = "gpt-4o"  # Must be GPT-4o as per design [cite: 328]

COSMOS_CONNECTION_STR = "AccountEndpoint=https://agentic-nexus-db.documents.azure.com:443/;AccountKey=Dzm7yoohYOsG8Ls6vUl85yPJvrLdwwvoCvmJfnxQ5ZDVe4lCfk9oattAMI0n93CfzMGoPIYHbzvwACDbtE9u0w==;"
DATABASE_NAME = "agentic-nexus-db"
LEDGER_CONTAINER = "TaskLedgers"

SERVICE_BUS_STR = "Endpoint=sb://agentic-nexus-bus.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=zc/D4I6SL4vb4KlTp7AnT97po4w8NTEXa+ASbFFsUOo="
GHOST_HANDSHAKE_QUEUE = "agent-handshake-stubs"
ENV_FILE_CONTENT = """# ══════════════════════════════════════════════════════════════════════════════
# MULTI-AGENT SOFTWARE BUILD PLATFORM - ENVIRONMENT CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

# ── AZURE OPENAI CONFIGURATION ─────────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_KEY=your-azure-openai-api-key
AZURE_OPENAI_API_VERSION=2024-02-15-preview

# ── AZURE OPENAI MODEL DEPLOYMENTS ─────────────────────────────────────────────
OPENAI_GPT4O_DEPLOYMENT=gpt-4o
OPENAI_MINI_DEPLOYMENT=gpt-4o-mini
OPENAI_O1_DEPLOYMENT=o1-mini

# ── AZURE COSMOS DB CONFIGURATION ──────────────────────────────────────────────
COSMOS_ENDPOINT=https://your-cosmos-account.documents.azure.com:443/
COSMOS_KEY=your-cosmos-db-key
COSMOS_DB_NAME=multi_agent_db

# ── AZURE SERVICE BUS CONFIGURATION ────────────────────────────────────────────
SERVICE_BUS_CONN_STR=Endpoint=sb://your-namespace.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=your-key
SERVICE_BUS_QUEUE=aeg-execution-queue

# ── SCHEDULER CONFIGURATION ────────────────────────────────────────────────────
MAX_CONCURRENT_AGENTS=8
STARVATION_TIMEOUT_SECS=600
BATCH_POLL_INTERVAL=3
CAPACITY_POLL_INTERVAL=5

# ── TOKEN BUCKET CONFIGURATION ─────────────────────────────────────────────────
TPM_LIMIT=90000
TPM_THRESHOLD=0.85

# ── MODEL PRICING (cost per 1K tokens) ─────────────────────────────────────────
MINI_COST_PER_1K=0.00015
GPT4O_COST_PER_1K=0.005
O1_COST_PER_1K=0.003

# ── BASELINE COST CALCULATION (for comparison) ─────────────────────────────────
GPT4O_BASELINE_RATE_PER_1K=0.005

# ── LOGGING CONFIGURATION ─────────────────────────────────────────────────────
LOG_LEVEL=INFO
LOG_FORMAT=json

# ── API CONFIGURATION ─────────────────────────────────────────────────────────
API_HOST=0.0.0.0
API_PORT=8000
API_RELOAD=false
API_WORKERS=4

# ── DEVELOPMENT FLAGS (set to true for dev, false for prod) ────────────────────
DEBUG_MODE=false
ENABLE_TRACE_LOGS=false
"""

def create_env_file(filepath: str = ".env"):
    """Create .env file with default values if it doesn't exist."""
    if not os.path.exists(filepath):
        with open(filepath, "w") as f:
            f.write(ENV_FILE_CONTENT)
        print(f"[INIT] Created {filepath} with default configuration")

# Create .env if missing
create_env_file()

# Load environment variables
from dotenv import load_dotenv
load_dotenv()
print("ENV GPT4O =", os.getenv("OPENAI_GPT4O_DEPLOYMENT"))
print("ENV MINI  =", os.getenv("OPENAI_MINI_DEPLOYMENT"))
print("ENV API VERSION =", os.getenv("AZURE_OPENAI_API_VERSION"))

# ── ENVIRONMENT VARIABLES ──────────────────────────────────────────────────────

# Azure OpenAI
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")

# Model Deployments
GPT4O = os.getenv("OPENAI_GPT4O_DEPLOYMENT")
MINI  = os.getenv("OPENAI_MINI_DEPLOYMENT")
O1    = os.getenv("OPENAI_O1_DEPLOYMENT")

# Cosmos DB
COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT")
COSMOS_KEY = os.getenv("COSMOS_KEY")
COSMOS_DB_NAME = os.getenv("COSMOS_DB_NAME")

# Service Bus
SB_CONN  = os.getenv("SERVICE_BUS_CONN_STR")
SB_QUEUE = os.getenv("SERVICE_BUS_QUEUE")

# Scheduler Config
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_AGENTS", "8"))
STARVATION_TIMEOUT_SECS = int(os.getenv("STARVATION_TIMEOUT_SECS", "600"))
BATCH_POLL_INTERVAL = int(os.getenv("BATCH_POLL_INTERVAL", "3"))
CAPACITY_POLL_INTERVAL = int(os.getenv("CAPACITY_POLL_INTERVAL", "5"))

# Token Bucket
TPM_LIMIT = int(os.getenv("TPM_LIMIT", "90000"))
TPM_THRESHOLD = float(os.getenv("TPM_THRESHOLD", "0.85"))

# API Config
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
API_RELOAD = os.getenv("API_RELOAD", "false").lower() == "true"
API_WORKERS = int(os.getenv("API_WORKERS", "4"))

# Debug Flags
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
ENABLE_TRACE_LOGS = os.getenv("ENABLE_TRACE_LOGS", "false").lower() == "true"

# ── CLIENT INITIALIZATION ──────────────────────────────────────────────────────

openai_client = AsyncAzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_KEY,
    api_version=AZURE_OPENAI_API_VERSION
)

cosmos_client = CosmosClient(
    COSMOS_ENDPOINT, credential=COSMOS_KEY
)
cosmos_db = cosmos_client.get_database_client(COSMOS_DB_NAME)

# ── COSMOS DB CLIENTS ──────────────────────────────────────────────────────────

task_ledgers  = cosmos_db.get_container_client("task_ledgers")
aeg_store     = cosmos_db.get_container_client("aeg_state")
conversations = cosmos_db.get_container_client("conversations")
costs         = cosmos_db.get_container_client("cost_records")

# ── PYDANTIC MODELS ────────────────────────────────────────────────────────────

AGENT_STATUSES = ["PENDING", "RUNNING", "COMPLETED", "FAILED", "SLEEPING", "RATE_LIMITED"]

class GuardrailEntry(BaseModel):
    risk_type: str
    recommendation: str
    user_decision: str
    timestamp: str

class TaskLedger(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_id: str = "default_user"
    user_intent: str = ""
    functional_requirements: list[str] = []
    non_functional_requirements: dict = {}
    tech_constraints: dict = {}
    integration_targets: list[str] = []
    guardrail_overrides: list[GuardrailEntry] = []
    revision_history: list[dict] = []
    status: str = "DRAFT"
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class AgentNode(BaseModel):
    agent_id: str
    role: str
    inputs: list[str] = []
    outputs: list[str] = []
    token_budget: int = 30000
    model_preference: str = "gpt-4o-mini"
    status: str = "PENDING"
    pending_since: Optional[str] = None
    priority: str = "NORMAL"

class AEGEdge(BaseModel):
    from_agent: str
    to_agent: str

class AEG(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    nodes: list[AgentNode]
    edges: list[AEGEdge]
    status: str = "PENDING_APPROVAL"
    revision_notes: str = ""
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class ClarifyRequest(BaseModel):
    project_id: Optional[str] = None
    message: str

class AEGRequest(BaseModel):
    project_id: str

class ApproveRequest(BaseModel):
    project_id: str
    approved: bool
    notes: Optional[str] = None

class DeltaRequest(BaseModel):
    project_id: str
    change_description: str

class ExecuteRequest(BaseModel):
    project_id: str

# ── COSMOS DB OPERATIONS ───────────────────────────────────────────────────────

def save_task_ledger(ledger: TaskLedger):
    task_ledgers.upsert_item(body=ledger.model_dump())

def get_task_ledger(project_id: str) -> dict:
    return task_ledgers.read_item(item=project_id, partition_key=project_id)

def save_aeg(aeg: AEG):
    aeg_store.upsert_item(body=aeg.model_dump())

def get_aeg(project_id: str) -> dict:
    return aeg_store.read_item(item=project_id, partition_key=project_id)

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

def save_cost_record(record: dict):
    costs.upsert_item(body=record)

def get_cost_records(project_id: str) -> list:
    return list(costs.query_items(
        query="SELECT * FROM c WHERE c.project_id = @pid",
        parameters=[{"name": "@pid", "value": project_id}],
        enable_cross_partition_query=True
    ))

# ── GUARDRAILS ─────────────────────────────────────────────────────────────────

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
    msg = user_message.lower()
    for risk_type, patterns in RISK_PATTERNS.items():
        if any(p in msg for p in patterns):
            return {
                "risk_type":      risk_type,
                "risk":           RISK_MESSAGES[risk_type],
                "recommendation": RECOMMENDATIONS[risk_type]
            }
    return None

def log_override(task_ledger: dict, risk_type: str, recommendation: str, user_decision: str):
    task_ledger["guardrail_overrides"].append({
        "risk_type":      risk_type,
        "recommendation": recommendation,
        "user_decision":  user_decision,
        "timestamp":      datetime.utcnow().isoformat()
    })

# ── DIRECTOR LOGIC ─────────────────────────────────────────────────────────────

DIRECTOR_SYSTEM_PROMPT = """
You are the Director of a multi-agent software build platform.
Clarify the user's app idea in EXACTLY 2-3 focused questions — no more, no less.

Cover these 5 axes across your questions:
  1. Functional scope — what does the app actually do
  2. Target users — who uses it, what scale
  3. Tech constraints — preferred stack, anything forbidden
  4. Integrations — third-party APIs, databases
  5. Quality/compliance — performance, budget, security

If the user mentions a risky tech choice (no auth, plaintext passwords,
NoSQL for financial data), output a GUARDRAIL before your next question.

Respond ONLY with valid JSON — no markdown, no extra text.

If you need more info:
  {"action": "ASK", "question": "your question here"}

If a tech choice is risky:
  {"action": "GUARDRAIL", "risk": "one line risk summary",
   "recommendation": "what you suggest instead",
   "question": "challenge + your next question"}

Once you have enough info (after 2-3 exchanges):
  {"action": "TASK_LEDGER_COMPLETE", "task_ledger": {
     "user_intent": "...",
     "functional_requirements": ["...", "..."],
     "non_functional_requirements": {"performance": "...", "budget": "..."},
     "tech_constraints": {"preferred": "...", "forbidden": "..."},
     "integration_targets": ["..."]
  }}
"""

AEG_PROMPT = """
Decompose this Task Ledger into an Agent Execution Graph (AEG).

STRICT RULES:
  - Produce exactly 5 to 7 agent nodes
  - NO circular dependencies — if agent A depends on B, B cannot depend on A
  - Each node must specify: agent_id, role, inputs[], outputs[], token_budget, model_preference
  - Edges must only flow from the producer of a value to its consumer
  - model_preference must be one of: gpt-4o-mini, gpt-4o
    Use gpt-4o only for auth, security, and architecture-level tasks
    Use gpt-4o-mini for API, schema, component, and test tasks

Available agent roles:
  Backend Engineer, Frontend Engineer, Database Architect,
  Security Reviewer, QA Engineer, DevOps Engineer, Documentation Writer

Return ONLY valid JSON:
{"nodes": [...], "edges": [{"from_agent": "...", "to_agent": "..."}]}
"""

async def run_clarification(conversation_history: list) -> dict:
    response = await openai_client.chat.completions.create(
        model=GPT4O,
        messages=[{"role": "system", "content": DIRECTOR_SYSTEM_PROMPT}]
                 + conversation_history,
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

def has_cycle(nodes: list, edges: list) -> bool:
    graph = {n["agent_id"]: [] for n in nodes}
    for e in edges:
        graph[e["from_agent"]].append(e["to_agent"])
    visited, rec = set(), set()
    def dfs(node):
        visited.add(node); rec.add(node)
        for nb in graph.get(node, []):
            if nb not in visited and dfs(nb): return True
            elif nb in rec: return True
        rec.discard(node)
        return False
    return any(dfs(n) for n in graph if n not in visited)

async def generate_aeg(task_ledger: dict) -> dict:
    response = await openai_client.chat.completions.create(
        model=GPT4O,
        messages=[
            {"role": "system", "content": AEG_PROMPT},
            {"role": "user", "content": json.dumps(task_ledger)}
        ],
        temperature=0.2,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# ── VALIDATOR ──────────────────────────────────────────────────────────────────

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

# ── DELTA AEG ─────────────────────────────────────────────────────���────────────

COSMETIC_KEYWORDS = ["rename", "restyle", "color", "font", "wording", "typo", "reorder", "comment"]
STRUCTURAL_KEYWORDS = ["add module", "new service", "change database", "add api", "new auth",
                       "remove module", "switch to", "replace with", "add microservice", "new endpoint", "add feature"]

async def classify_change(description: str) -> str:
    desc = description.lower()
    if any(k in desc for k in COSMETIC_KEYWORDS): return "COSMETIC"
    if any(k in desc for k in STRUCTURAL_KEYWORDS): return "STRUCTURAL"
    response = await openai_client.chat.completions.create(
        model=MINI,
        messages=[{"role": "user", "content":
            f"Is this change COSMETIC (rename/style) or STRUCTURAL (new module/service/db)?\n{description}\nReply ONE word: COSMETIC or STRUCTURAL"}]
    )
    return response.choices[0].message.content.strip().upper()

async def detect_conflict(new_request: str, project_id: str) -> dict | None:
    ledger = get_task_ledger(project_id)
    prev_deltas = [r for r in ledger.get("revision_history", []) if r.get("type") == "STRUCTURAL"]
    if not prev_deltas: return None
    prev_summary = json.dumps([d["description"] for d in prev_deltas[-3:]])
    response = await openai_client.chat.completions.create(
        model=GPT4O,
        messages=[{"role": "user", "content":
            f"Are these structural changes compatible?\nPrevious: {prev_summary}\nNew: {new_request}\nReply ONLY JSON: {{\"conflict\": true/false, \"reason\": \"...\"}}"}],
        response_format={"type": "json_object"}
    )
    result = json.loads(response.choices[0].message.content)
    return result if result["conflict"] else None

async def apply_delta(project_id: str, change_description: str) -> dict:
    change_type = await classify_change(change_description)
    conflict = None
    if change_type == "STRUCTURAL":
        conflict = await detect_conflict(change_description, project_id)
    ledger = get_task_ledger(project_id)
    ledger["revision_history"].append({
        "type": change_type,
        "description": change_description,
        "timestamp": datetime.utcnow().isoformat()
    })
    save_task_ledger(TaskLedger(**ledger))
    return {"change_type": change_type, "conflict": conflict}

# ── COST OPTIMIZER ─────────────────────────────────────────────────────────────

class TokenBucket:
    """
    One instance lives per project_id in _buckets.
    All agents in that project share it, so we never blow the Azure TPM limit.
    Blocks when usage reaches 85% of the window limit, then waits out the window.
    """
    def __init__(self, tpm_limit: int = TPM_LIMIT):
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

            if self.used + tokens_needed > self.limit * TPM_THRESHOLD:
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

MODEL_COSTS_PER_1K = {
    MINI:  float(os.getenv("MINI_COST_PER_1K", "0.00015")),
    GPT4O: float(os.getenv("GPT4O_COST_PER_1K", "0.005")),
    O1:    float(os.getenv("O1_COST_PER_1K", "0.003")),
}

ESCALATION_LADDER = [MINI, GPT4O, O1]

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
    return MINI

def passes_self_validation(output: str, task: str) -> bool:
    """Lightweight check before deciding whether to escalate to a larger model."""
    if not output or len(output) < 20:   return False
    if "i cannot" in output.lower():     return False
    if "as an ai"  in output.lower():    return False
    if any(k in task.lower() for k in ["function", "component", "schema", "endpoint", "class"]):
        return "def " in output or "class " in output or "{" in output
    return True

async def safe_model_call(
    model: str,
    messages: list,
    project_id: str,
    agent_id: str,
    estimated_tokens: int = 2000,
) -> Tuple[str, int]:
    """
    Acquires token-bucket capacity, calls the model, handles 429s gracefully.
    A 429 sets status → RATE_LIMITED (not FAILED), sleeps Retry-After,
    then retries ONCE on the SAME model without consuming an escalation step.
    """
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

            await update_status(project_id, agent_id, "RATE_LIMITED")
            print(f"[429] Agent {agent_id} rate-limited — retrying in {retry_after}s")
            await asyncio.sleep(retry_after)
            await update_status(project_id, agent_id, "RUNNING")

            response = await openai_client.chat.completions.create(
                model=model, messages=messages, temperature=0.2
            )
            return response.choices[0].message.content, response.usage.total_tokens

        raise

async def log_cost(
    project_id: str, agent_id: str, task: str, model: str, tokens: int
):
    cost = (tokens / 1000) * MODEL_COSTS_PER_1K.get(model, 0.005)
    save_cost_record({
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

    output, tokens = await safe_model_call(O1, messages, project_id, agent_id)
    await log_cost(project_id, agent_id, task, O1, tokens)
    return output

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

# ── SCHEDULER ──────────────────────────────────────────────────────────────────

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

def get_node(aeg: dict, agent_id: str) -> dict:
    return next(n for n in aeg["nodes"] if n["agent_id"] == agent_id)

async def update_status(project_id: str, agent_id: str, status: str):
    """
    Valid transitions:
      PENDING      → RUNNING
      RUNNING      → COMPLETED | FAILED | SLEEPING | RATE_LIMITED
      RATE_LIMITED → RUNNING   (after Retry-After window)
      SLEEPING     → RUNNING   (when a dormant dependency completes)
    """
    aeg = get_aeg(project_id)
    for node in aeg["nodes"]:
        if node["agent_id"] == agent_id:
            node["status"]     = status
            node["updated_at"] = datetime.utcnow().isoformat()
            if status == "RUNNING":
                node["started_at"] = datetime.utcnow().isoformat()
            if status == "PENDING" and not node.get("pending_since"):
                node["pending_since"] = datetime.utcnow().isoformat()
            break
    save_aeg(AEG(**aeg))

async def starvation_monitor(project_id: str):
    """
    Background task — runs for the lifetime of an execution.
    Any agent stuck in PENDING for > 10 minutes gets priority = ELEVATED,
    which causes the scheduler to front-run it in the next available slot.
    """
    while True:
        await asyncio.sleep(60)
        aeg = get_aeg(project_id)

        if aeg["status"] in ("COMPLETED", "FAILED"):
            break

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
            save_aeg(AEG(**aeg))

async def start(aeg: dict):
    project_id = aeg["project_id"]
    print(f"[Scheduler] Starting execution for project {project_id}")

    aeg["status"] = "EXECUTING"
    save_aeg(AEG(**aeg))

    asyncio.create_task(starvation_monitor(project_id))

    batches = get_execution_batches(aeg)
    print(f"[Scheduler] {len(batches)} batch(es) planned: {batches}")

    for batch_idx, batch in enumerate(batches):
        print(f"[Scheduler] Batch {batch_idx + 1}/{len(batches)}: {batch}")

        aeg = get_aeg(project_id)

        sorted_batch = sorted(
            batch,
            key=lambda aid: 0 if get_node(aeg, aid).get("priority") == "ELEVATED" else 1
        )

        running_count = sum(1 for n in aeg["nodes"] if n["status"] == "RUNNING")

        for agent_id in sorted_batch:
            while running_count >= MAX_CONCURRENT:
                await asyncio.sleep(CAPACITY_POLL_INTERVAL)
                aeg          = get_aeg(project_id)
                running_count = sum(1 for n in aeg["nodes"] if n["status"] == "RUNNING")

            await update_status(project_id, agent_id, "RUNNING")
            running_count += 1
            print(f"[Scheduler] Agent {agent_id} → RUNNING")

        while True:
            await asyncio.sleep(BATCH_POLL_INTERVAL)
            aeg            = get_aeg(project_id)
            batch_statuses = [get_node(aeg, a)["status"] for a in batch]
            if all(s in ("COMPLETED", "FAILED", "SLEEPING") for s in batch_statuses):
                failed = [a for a in batch if get_node(aeg, a)["status"] == "FAILED"]
                if failed:
                    print(f"[Scheduler] Batch {batch_idx + 1} finished with failures: {failed}")
                break

    aeg          = get_aeg(project_id)
    all_statuses = [n["status"] for n in aeg["nodes"]]
    aeg["status"] = "COMPLETED" if all(s == "COMPLETED" for s in all_statuses) else "FAILED"
    save_aeg(AEG(**aeg))
    print(f"[Scheduler] Project {project_id} → {aeg['status']}")

# ── SERVICE BUS LISTENER ───────────────────────────────────────────────────────

async def listen_for_commands():
    """
    Runs as a background task from app startup.
    Polls the Service Bus queue every 5 seconds for EXECUTE_AEG commands.
    On receiving one, fetches the AEG from Cosmos and kicks off the scheduler.
    """
    async with ServiceBusClient.from_connection_string(SB_CONN) as client:
        receiver = client.get_queue_receiver(
            queue_name=SB_QUEUE,
            max_wait_time=5
        )
        async with receiver:
            while True:
                try:
                    msgs = await receiver.receive_messages(
                        max_message_count=10,
                        max_wait_time=5
                    )
                    for msg in msgs:
                        try:
                            payload = json.loads(str(msg))
                            command = payload.get("command")
                            project_id = payload.get("project_id")

                            if not command or not project_id:
                                print(f"[Listener] Malformed message, skipping: {payload}")
                                await receiver.dead_letter_message(msg, reason="Missing command or project_id")
                                continue

                            if command == "EXECUTE_AEG":
                                print(f"[Listener] Received EXECUTE_AEG for project {project_id}")
                                aeg = get_aeg(project_id)
                                asyncio.create_task(start(aeg))
                                print(f"[Listener] Scheduler started for project {project_id}")
                            else:
                                print(f"[Listener] Unknown command '{command}', skipping")

                            await receiver.complete_message(msg)

                        except json.JSONDecodeError as e:
                            print(f"[Listener] JSON parse error: {e}")
                            await receiver.dead_letter_message(msg, reason="Invalid JSON")

                        except Exception as e:
                            print(f"[Listener] Error processing message: {e}")
                            await receiver.abandon_message(msg)

                except Exception as e:
                    print(f"[Listener] Receiver error, retrying in 10s: {e}")
                    await asyncio.sleep(10)

# ── FASTAPI APPLICATION ───────────────────────────────────────────────────────

app = FastAPI()

@app.on_event("startup")
async def startup():
    asyncio.create_task(listen_for_commands())

# ── Dev 1 endpoints ────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "Director service running"}

@app.post("/clarify")
async def clarify(req: ClarifyRequest):
    try:
        project_id = req.project_id or str(uuid.uuid4())
        history = get_conversation(project_id)
        history.append({"role": "user", "content": req.message})
        result = await run_clarification(history)
        if result["action"] == "TASK_LEDGER_COMPLETE":
            ledger = TaskLedger(project_id=project_id, id=project_id, **result["task_ledger"])
            save_task_ledger(ledger)
            save_conversation(project_id, history)
            return {"status": "complete", "project_id": project_id,
                    "message": "Task Ledger saved! Now call POST /aeg"}
        elif result["action"] == "GUARDRAIL":
            history.append({"role": "assistant", "content": result["question"]})
            save_conversation(project_id, history)
            return {"status": "guardrail", "project_id": project_id,
                    "risk": result["risk"], "recommendation": result["recommendation"],
                    "question": result["question"]}
        else:
            history.append({"role": "assistant", "content": result["question"]})
            save_conversation(project_id, history)
            return {"status": "asking", "project_id": project_id, "question": result["question"]}
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}

@app.post("/aeg")
async def generate_aeg_route(req: AEGRequest):
    try:
        ledger = get_task_ledger(req.project_id)
        val = await validate(ledger)
        blockers = [i for i in val["issues"] if i["severity"] == "blocker"]
        if blockers:
            return {"status": "blocked", "issues": blockers,
                    "message": "Resolve blockers before AEG can be generated"}
        raw = await generate_aeg(ledger)
        if has_cycle(raw["nodes"], raw["edges"]):
            raw = await generate_aeg(ledger)
            if has_cycle(raw["nodes"], raw["edges"]):
                raise HTTPException(500, "AEG generation produced circular dependency twice")
        aeg = AEG(
            id=req.project_id, project_id=req.project_id,
            nodes=[AgentNode(**n) for n in raw["nodes"]],
            edges=[AEGEdge(**e) for e in raw["edges"]],
            status="PENDING_APPROVAL"
        )
        save_aeg(aeg)
        return {"status": "awaiting_approval", "project_id": req.project_id,
                "aeg": aeg.model_dump(), "message": "AEG generated! Now call POST /approve"}
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}

@app.post("/approve")
async def approve_aeg(req: ApproveRequest):
    try:
        aeg_data = get_aeg(req.project_id)
        if req.approved:
            aeg_data["status"] = "APPROVED"
            save_aeg(AEG(**aeg_data))
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
            save_aeg(AEG(**aeg_data))
            return {"status": "revision_needed", "project_id": req.project_id,
                    "message": "AEG sent back for revision"}
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}

@app.post("/delta")
async def delta(req: DeltaRequest):
    try:
        risk = screen_message(req.change_description)
        if risk:
            return {"status": "guardrail", "project_id": req.project_id,
                    "risk": risk["risk"], "recommendation": risk["recommendation"],
                    "message": "Risky pattern detected in change request"}
        result = await apply_delta(req.project_id, req.change_description)
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
        aeg = get_aeg(req.project_id)
        if aeg["status"] != "APPROVED":
            raise HTTPException(
                status_code=400,
                detail=f"AEG status is '{aeg['status']}' — must be APPROVED before executing"
            )
        asyncio.create_task(start(aeg))
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
        aeg = get_aeg(project_id)
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
        records = get_cost_records(project_id)
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

        for m in by_model:
            by_model[m]["cost_usd"] = round(by_model[m]["cost_usd"], 4)

        GPT4O_BASELINE_RATE = float(os.getenv("GPT4O_BASELINE_RATE_PER_1K", "0.005"))
        baseline_cost = (total_tokens / 1000) * GPT4O_BASELINE_RATE

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

# ── ENTRY POINT ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=API_HOST,
        port=API_PORT,
        reload=API_RELOAD,
        workers=API_WORKERS if not API_RELOAD else 1
    )
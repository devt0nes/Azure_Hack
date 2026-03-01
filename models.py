# models.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid

# ── STATUS ENUM ──────────────────────────────────────────
# These are the exact strings both devs use — agree on these now
# Dev 2 will write/read these into Cosmos DB
AGENT_STATUSES = ["PENDING", "RUNNING", "COMPLETED", "FAILED", "SLEEPING", "RATE_LIMITED"]

# ── TASK LEDGER ──────────────────────────────────────────
class GuardrailEntry(BaseModel):
    risk_type: str
    recommendation: str
    user_decision: str       # "override" or "accepted_recommendation"
    timestamp: str

class TaskLedger(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Cosmos needs "id"
    project_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_id: str = "default_user"
    user_intent: str = ""
    functional_requirements: list[str] = []
    non_functional_requirements: dict = {}   # e.g. {"performance": "< 2s", "budget": "$500/mo"}
    tech_constraints: dict = {}              # e.g. {"preferred": "FastAPI", "forbidden": "PHP"}
    integration_targets: list[str] = []     # e.g. ["Stripe", "SendGrid"]
    guardrail_overrides: list[GuardrailEntry] = []
    revision_history: list[dict] = []
    status: str = "DRAFT"                   # DRAFT → VALIDATED → AEG_APPROVED
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

# ── AEG (Agent Execution Graph) ───────────────────────────
class AgentNode(BaseModel):
    agent_id: str                            # e.g. "backend_engineer_1"
    role: str                                # e.g. "Backend Engineer"
    inputs: list[str] = []                  # e.g. ["db_schema"]
    outputs: list[str] = []                 # e.g. ["rest_api_spec"]
    token_budget: int = 30000
    model_preference: str = "gpt-4o-mini"  # "phi-4" | "gpt-4o-mini" | "gpt-4o"
    status: str = "PENDING"                 # Use strings from AGENT_STATUSES above
    pending_since: Optional[str] = None
    priority: str = "NORMAL"               # "NORMAL" | "ELEVATED"

class AEGEdge(BaseModel):
    from_agent: str    # NOTE: can't use "from" — that's a Python reserved word
    to_agent: str

class AEG(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Cosmos needs "id"
    project_id: str
    nodes: list[AgentNode]
    edges: list[AEGEdge]
    status: str = "PENDING_APPROVAL"       # PENDING_APPROVAL → APPROVED → EXECUTING → COMPLETED
    revision_notes: str = ""
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

# ── API REQUEST SHAPES ────────────────────────────────────
# These are what YOUR endpoints receive — share these with Dev 2

class ClarifyRequest(BaseModel):
    project_id: Optional[str] = None   # None on first call — you generate it
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

# ── EXECUTE REQUEST (what Dev 2's /execute expects from you) ──
# When you call POST /execute after approval, send this shape:
class ExecuteRequest(BaseModel):
    project_id: str     # That's it — Dev 2 reads the AEG from Cosmos themselves
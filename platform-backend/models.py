# models.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid

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
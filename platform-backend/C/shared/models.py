from pydantic import BaseModel
from typing import Optional

# ─────────────────────────────────────────────
# SHARED MODELS
# ─────────────────────────────────────────────

class TestResult(BaseModel):
    run_id: str
    project_id: str
    module_id: str
    pass_count: int
    fail_count: int
    coverage_pct: float
    timestamp: str

class FailureContext(BaseModel):
    project_id: str
    test_id: str
    failing_test_body: str
    stack_trace: str
    module_code: str

class PatchAttempt(BaseModel):
    patch_id: str
    project_id: str
    failure_id: str
    diff: str
    model_tier: str
    security_verdict: str
    applied: bool
    timestamp: str

class EscalationEvent(BaseModel):
    escalation_id: str
    project_id: str
    tier_reached: int
    director_notified: bool
    cascade_chain_json: Optional[str] = None

# ─────────────────────────────────────────────
# DATA INGESTION MODELS
# ─────────────────────────────────────────────

class SchemaResult(BaseModel):
    project_id: str
    file_type: str
    columns: Optional[list[str]] = None
    types: Optional[dict[str, str]] = None
    domain: Optional[str] = None
    proposed_db_schema: Optional[str] = None
    suggested_endpoints: Optional[list[str]] = None
    suggested_ui_components: Optional[list[str]] = None

class VisionResult(BaseModel):
    project_id: str
    page_name: str
    components: list[str]
    layout: str
    navigation_flow: list[str]
    frontend_task_list: list[str]

class DocumentResult(BaseModel):
    project_id: str
    extracted_text: str
    tables: Optional[list[dict]] = None
    key_value_pairs: Optional[dict] = None
    user_stories: Optional[list[str]] = None
    technical_constraints: Optional[list[str]] = None

class UnifiedContext(BaseModel):
    project_id: str
    csv_schema: Optional[SchemaResult] = None
    vision_result: Optional[VisionResult] = None
    document_result: Optional[DocumentResult] = None
    combined_summary: Optional[str] = None
    task_ledger_seeds: Optional[list[str]] = None
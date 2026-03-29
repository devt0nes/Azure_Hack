"""
Platform-compatible backend for nexus-new.
Implements the same route surface as Azure_Hack tentative-backend/app.py,
but with local, simplified orchestration logic.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from ingestion_service import build_ingestion_context
from blob_workspace import build_blob_workspace_from_env
from azure_runtime_sync import download_blob_to_local_path, write_text_azure_first
from cosmos_client import (
    get_cosmos_client,
    get_starter_template,
    init_cosmos_db,
    resolve_starter_template_for_stack,
    seed_default_templates,
    seed_starter_templates,
)


load_dotenv()
AZURE_MODEL_DEPLOYMENT = os.getenv("AZURE_MODEL_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT") or "gpt-4o"


def _detect_repo_root() -> Path:
    env_root = (os.getenv("NEXUS_ROOT_DIR") or "").strip()
    if env_root:
        return Path(env_root).resolve()

    here = Path(__file__).resolve()
    # If running from .../Azure_Hack-*/platform-backend, root is three levels up.
    if here.parent.name == "platform-backend" and here.parent.parent.name.startswith("Azure_Hack-"):
        return here.parent.parent.parent

    return here.parent


REPO_ROOT = _detect_repo_root()

class ReferenceFileItem(BaseModel):
	filename: str
	url: str


class IngestionContextRequest(BaseModel):
	reference_files: List[ReferenceFileItem] = []
	include_canvas: bool = False

# ------------------------------
# App + logging
# ------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("nexus-platform-backend")
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.servicebus").setLevel(logging.WARNING)
logging.getLogger("azure.core").setLevel(logging.WARNING)

app = FastAPI(
    title="Nexus Platform Backend",
    description="Platform-compatible API surface for frontend integration",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------
# Models
# ------------------------------

class ProjectStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    GENERATING_CODE = "generating_code"
    GENERATING_DEPLOYMENT = "generating_deployment"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class CreateProjectRequest(BaseModel):
    project_name: str
    user_intent: str
    description: Optional[str] = None
    azure_resources: Optional[List[str]] = ["cosmos_db", "blob_storage", "key_vault"]


class ProjectResponse(BaseModel):
    project_id: str
    project_name: str
    status: ProjectStatus
    created_at: str
    updated_at: str
    user_intent: str
    progress: int
    error: Optional[str] = None


class DeploymentRequest(BaseModel):
    project_id: str
    enable_docker_build: bool = True
    enable_infrastructure: bool = True
    enable_cicd: bool = True
    mock_success: bool = False
    resource_group: str = "agentic_brocode"
    location: str = "southeastasia"


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str
    cosmos: Optional[Dict[str, Any]] = None


class ClarifyRequest(BaseModel):
    project_id: str
    user_input: str
    answers: Optional[Dict[str, str]] = None


class ExecuteRequest(BaseModel):
    project_id: str
    user_intent: Optional[str] = None
    service_api_keys: Optional[Dict[str, str]] = None


class TutorRequest(BaseModel):
    project_id: str
    question: str
    context: Optional[Dict[str, Any]] = {}


class AgentSelectionRequest(BaseModel):
    aeg_node_id: str
    agent_id: str
    project_id: Optional[str] = None

class CreateAgentRequest(BaseModel):
    role: str                          # human name, will be slugified to id
    description: str
    tier: int = 2                       # 1 = Core (GPT-4o), 2 = Specialist (GPT-4o-mini)
    model_label: Optional[str] = None  # auto-derived from tier if omitted
    tags: List[str] = []
    system_prompt: Optional[str] = None  # full system prompt / instructions for the agent

class BudgetRequest(BaseModel):
    budget_usd: float


class ClarifyAnswersRequest(BaseModel):
    project_id: str
    answers: Dict[str, str]

class QuestionRequest(BaseModel):
    project_id: str
    user_message: str
    conversation_history: Optional[List[Dict[str, str]]] = None
    question_count: Optional[int] = 0


class QuestionReadinessRequest(BaseModel):
    project_id: str


# ------------------------------
# Project storage
# ------------------------------

class ProjectStore:
    def __init__(self, storage_file: str = str(REPO_ROOT / "projects_db.json")):
        self.storage_file = Path(storage_file)
        self.generated_root = REPO_ROOT / "generated_code"
        self.logs_root = REPO_ROOT / "agent_logs"
        self.projects: Dict[str, Dict[str, Any]] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self._load()

    def _load(self) -> None:
        if not self.storage_file.exists():
            self.projects = {}
            return
        try:
            self.projects = json.loads(self.storage_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load projects DB: %s", exc)
            self.projects = {}

    def _save(self) -> None:
        self.storage_file.write_text(json.dumps(self.projects, indent=2), encoding="utf-8")

    def create(self, project_name: str, user_intent: str, description: Optional[str]) -> Dict[str, Any]:
        project_id = str(uuid.uuid4())
        return self.create_with_id(project_id, project_name, user_intent, description)

    def create_with_id(self, project_id: str, project_name: str, user_intent: str, description: Optional[str]) -> Dict[str, Any]:
        now = datetime.utcnow().isoformat()
        payload = {
            "project_id": project_id,
            "project_name": project_name,
            "user_intent": user_intent,
            "description": description,
            "status": ProjectStatus.CREATED.value,
            "created_at": now,
            "updated_at": now,
            "progress": 0,
            "error": None,
            "artifacts": [],
            "ledger_data": None,
            "clarification_questions": [],
            "clarification_answers": {},
            "clarification_state": "none",
            "question_count": 0
        }
        self.projects[project_id] = payload
        self._save()
        return payload

    def get(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self.projects.get(project_id)

    def update(self, project_id: str, *, status: Optional[ProjectStatus] = None, progress: Optional[int] = None, error: Optional[str] = None) -> None:
        project = self.projects.get(project_id)
        if not project:
            return
        if status is not None:
            project["status"] = status.value
        if progress is not None:
            project["progress"] = progress
        if error is not None:
            project["error"] = error
        project["updated_at"] = datetime.utcnow().isoformat()
        self._save()


store = ProjectStore()
BLOB_WORKSPACE = None
try:
    BLOB_WORKSPACE = build_blob_workspace_from_env()
except Exception as exc:
    logger.exception("Blob workspace disabled: %s", exc)
    print(f"[AzureBlob][init] Blob workspace disabled: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)

# ─── Azure Storage Configuration ─────────────────────────────────────────────
_ENABLE_LOCAL_FILE_GENERATION = str(os.getenv("ENABLE_LOCAL_FILE_GENERATION", "false")).strip().lower() in {"1", "true", "yes", "on"}
_AZURE_STORAGE_CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
_AZURE_STORAGE_CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER", "project-workspace")
_BLOB_SYNC_MIN_INTERVAL_SECONDS = int(os.getenv("BLOB_SYNC_MIN_INTERVAL_SECONDS", "20"))
_BLOB_SYNC_VERBOSE_DOWNLOAD_LOGS = str(os.getenv("BLOB_SYNC_VERBOSE_DOWNLOAD_LOGS", "false")).strip().lower() in {"1", "true", "yes", "on"}
_ENABLE_LEGACY_BLOB_PROJECT_SYNC = str(os.getenv("ENABLE_LEGACY_BLOB_PROJECT_SYNC", "false")).strip().lower() in {"1", "true", "yes", "on"}
_BLOB_AUTOSYNC_ENABLED = str(os.getenv("BLOB_AUTOSYNC_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
_BLOB_AUTOSYNC_INTERVAL_SECONDS = max(1, int(os.getenv("BLOB_AUTOSYNC_INTERVAL_SECONDS", "1")))
_ACTIVE_PROJECT_STATES_FOR_AUTOSYNC = {
    ProjectStatus.QUEUED.value,
    ProjectStatus.GENERATING_CODE.value,
    ProjectStatus.GENERATING_DEPLOYMENT.value,
    ProjectStatus.PAUSED.value,
}

_azure_blob_client = None
_PROJECT_BLOB_AUTOSYNC_TASKS: Dict[str, asyncio.Task] = {}


def _report_blob_error(prefix: str, exc: Exception, project_id: Optional[str] = None) -> None:
    details = f"{type(exc).__name__}: {exc}"
    if project_id:
        logger.exception("%s (project=%s): %s", prefix, project_id, details)
        _append_project_log(project_id, "blob_error", stage=prefix, error=details)
        print(f"[AzureBlob][{project_id}] {prefix}: {details}", file=sys.stderr, flush=True)
    else:
        logger.exception("%s: %s", prefix, details)
        print(f"[AzureBlob] {prefix}: {details}", file=sys.stderr, flush=True)


def _get_azure_blob_container_client():
    """Get Azure Blob Storage container client for project files.
    
    Returns None if not configured. Lazy initialization on first use.
    """
    global _azure_blob_client
    if _azure_blob_client is not None:
        return _azure_blob_client
    
    if not _AZURE_STORAGE_CONN_STR:
        logger.warning("Azure Storage not configured: AZURE_STORAGE_CONNECTION_STRING is empty")
        return None
    
    try:
        from azure.storage.blob import BlobServiceClient
        service_client = BlobServiceClient.from_connection_string(_AZURE_STORAGE_CONN_STR)
        _azure_blob_client = service_client.get_container_client(_AZURE_STORAGE_CONTAINER)
        try:
            _azure_blob_client.create_container()
        except Exception:
            # Container already exists
            pass
        return _azure_blob_client
    except Exception as exc:
        _report_blob_error("Failed to initialize Azure Blob Storage", exc)
        return None


async def _upload_file_to_azure(project_id: str, local_file_path: Path) -> bool:
    """Upload a single file to Azure Storage.
    
    Returns True if successful, False otherwise.
    """
    if _ENABLE_LOCAL_FILE_GENERATION:
        # Kept for backward compatibility with existing env behavior.
        logger.warning(
            "Direct Azure upload skipped because ENABLE_LOCAL_FILE_GENERATION=true (project=%s, file=%s)",
            project_id,
            local_file_path,
        )
        return True
    
    container = _get_azure_blob_container_client()
    if not container:
        logger.warning("Azure Storage not available, file %s not uploaded", local_file_path)
        return False
    
    try:
        local_file = Path(local_file_path)
        if not local_file.exists():
            logger.warning("Local file does not exist: %s", local_file_path)
            return False
        
        # Construct blob name as project_id/relative_path
        rel_path = local_file.relative_to(_project_generated_dir(project_id)).as_posix()
        blob_name = f"{project_id}/{rel_path}"
        
        # Upload to Azure asynchronously
        loop = asyncio.get_event_loop()
        with open(local_file, "rb") as data:
            await loop.run_in_executor(
                None,
                lambda: container.upload_blob(blob_name, data, overwrite=True)
            )
        
        logger.debug("Uploaded file to Azure: %s", blob_name)
        return True
    except Exception as exc:
        _report_blob_error(f"Failed to upload file to Azure ({local_file_path})", exc, project_id=project_id)
        return False


async def _upload_project_to_azure(project_id: str) -> int:
    """Upload all project files to Azure Storage.
    
    Returns the count of files uploaded.
    """
    if _ENABLE_LOCAL_FILE_GENERATION:
        # Kept for backward compatibility with existing env behavior.
        logger.warning(
            "Direct Azure project upload skipped because ENABLE_LOCAL_FILE_GENERATION=true (project=%s)",
            project_id,
        )
        return 0
    
    container = _get_azure_blob_container_client()
    if not container:
        logger.warning("Azure Storage not available, project %s not uploaded", project_id)
        return 0
    
    try:
        project_root = _project_generated_dir(project_id)
        if not project_root.exists():
            logger.warning("Project directory does not exist: %s", project_root)
            return 0
        
        count = 0
        for root, _, files in os.walk(project_root):
            for name in files:
                full_path = Path(root) / name
                rel_path = full_path.relative_to(project_root).as_posix()
                blob_name = f"{project_id}/{rel_path}"
                
                try:
                    with open(full_path, "rb") as data:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            None,
                            lambda f=data, bn=blob_name: container.upload_blob(bn, f, overwrite=True)
                        )
                    count += 1
                except Exception as exc:
                    _report_blob_error(f"Failed to upload file during project sync ({full_path})", exc, project_id=project_id)
                    continue
        
        logger.info("Uploaded %d files for project %s to Azure Storage", count, project_id)
        return count
    except Exception as exc:
        _report_blob_error("Failed to upload project to Azure", exc, project_id=project_id)
        return 0


SELECTED_AGENTS_BY_PROJECT: Dict[str, Dict[str, Dict[str, Any]]] = {}
_BLOB_SYNC_LAST_DOWNLOAD_TS: Dict[str, float] = {}

AGENT_CATALOG: List[Dict[str, Any]] = [
    # ── Tier 1 — Module Agents (GPT-4o, core execution) ──────────────────────
    {
        "id": "backend_engineer",
        "role": "backend_engineer",
        "tier": 1,
        "model_label": "GPT-4o",
        "description": "Builds backend APIs, microservices, and orchestration logic on Azure.",
        "reputation_score": 0.93,
        "tags": ["backend", "api", "python", "azure"],
    },
    {
        "id": "frontend_engineer",
        "role": "frontend_engineer",
        "tier": 1,
        "model_label": "GPT-4o",
        "description": "Builds React UIs and integrates frontend with backend APIs.",
        "reputation_score": 0.91,
        "tags": ["frontend", "react", "ui", "tailwind"],
    },
    {
        "id": "database_architect",
        "role": "database_architect",
        "tier": 1,
        "model_label": "GPT-4o",
        "description": "Designs SQL/NoSQL schemas, indexing strategies, and data pipelines.",
        "reputation_score": 0.88,
        "tags": ["database", "sql", "cosmos", "schema"],
    },
    # ── Tier 2 — Specialist Agents (all others, GPT-4o-mini) ─────────────────
    {
        "id": "solution_architect",
        "role": "solution_architect",
        "tier": 2,
        "model_label": "GPT-4o-mini",
        "description": "Designs overall system architecture, selects tech stack, and coordinates agents.",
        "reputation_score": 0.95,
        "tags": ["architecture", "azure", "design", "microservices"],
    },
    {
        "id": "api_designer",
        "role": "api_designer",
        "tier": 2,
        "model_label": "GPT-4o-mini",
        "description": "Designs OpenAPI contracts, versioning strategy, and SDK interfaces.",
        "reputation_score": 0.86,
        "tags": ["api", "openapi", "design", "rest"],
    },
    {
        "id": "security_engineer",
        "role": "security_engineer",
        "tier": 2,
        "model_label": "GPT-4o-mini",
        "description": "Hardens systems against OWASP Top-10, manages secrets, and enforces compliance.",
        "reputation_score": 0.90,
        "tags": ["security", "compliance", "azure", "owasp"],
    },
    {
        "id": "devops_engineer",
        "role": "devops_engineer",
        "tier": 2,
        "model_label": "GPT-4o-mini",
        "description": "Builds CI/CD pipelines, IaC templates, and Azure deployment automation.",
        "reputation_score": 0.87,
        "tags": ["devops", "cicd", "azure", "iac"],
    },
    {
        "id": "qa_engineer",
        "role": "qa_engineer",
        "tier": 2,
        "model_label": "GPT-4o-mini",
        "description": "Writes test suites, runs load tests, and enforces coverage targets.",
        "reputation_score": 0.89,
        "tags": ["qa", "testing", "automation"],
    },
]

# ─── Cosmos DB – AgentLibrary ────────────────────────────────────────────────
# Reads agents from the AgentRegistry container in the agentic-nexus-db database.
# Falls back to AGENT_CATALOG above if the DB is unreachable or the container is empty.
_COSMOS_DB_NAME          = os.getenv("COSMOS_DB_NAME",           "agentic-nexus-db")
_AGENT_REGISTRY_CONTAINER = os.getenv("AGENT_CONTAINER",         "AgentRegistry")
_COSMOS_CONN_STR         = os.getenv("COSMOS_CONNECTION_STR",    "")
_AGENT_CACHE_TTL         = int(os.getenv("AGENT_CACHE_TTL_SECONDS", "300"))

_agent_catalog_cache: Optional[List[Dict[str, Any]]] = None
_agent_cache_ts: float = 0.0
_agent_cache_source: str = "local"


def _get_agent_library_cosmos_container():
    """Return a Cosmos DB ContainerClient for AgentRegistry, or raise."""
    from azure.cosmos import CosmosClient  # lazy import – already in requirements
    if not _COSMOS_CONN_STR:
        raise RuntimeError("COSMOS_CONNECTION_STR is not set")
    client = CosmosClient.from_connection_string(_COSMOS_CONN_STR)
    db = client.get_database_client(_COSMOS_DB_NAME)
    return db.get_container_client(_AGENT_REGISTRY_CONTAINER)


def _query_cosmos_agents() -> List[Dict[str, Any]]:
    """Blocking helper; call via run_in_executor.
    Uses read_all_items() to enumerate documents without any SQL query,
    bypassing the SDK's internal query rewriter that generates the
    SC2001 'Identifier c could not be resolved' error.
    """
    container = _get_agent_library_cosmos_container()
    items = list(container.read_all_items())
    for item in items:
        # Cosmos uses 'id' as partition key, so this should exist,
        # but ensure the frontend field is consistent
        if "id" not in item and "agent_id" in item:
            item["id"] = item["agent_id"]
        # Strip Cosmos system properties to keep payload clean
        for key in ["_rid", "_self", "_etag", "_attachments", "_ts"]:
            item.pop(key, None)
    return items


async def _get_agent_catalog() -> List[Dict[str, Any]]:
    """Return agents from Cosmos DB AgentLibrary with a timed in-memory cache.

    Falls back to the hardcoded AGENT_CATALOG if Cosmos DB is unreachable or
    returns no documents.
    """
    global _agent_catalog_cache, _agent_cache_ts, _agent_cache_source
    now = time.monotonic()
    if _agent_catalog_cache is not None and (now - _agent_cache_ts) < _AGENT_CACHE_TTL:
        return _agent_catalog_cache

    try:
        loop = asyncio.get_event_loop()
        agents = await loop.run_in_executor(None, _query_cosmos_agents)
        if agents:
            _agent_catalog_cache = agents
            _agent_cache_ts = now
            _agent_cache_source = "cosmos"
            return agents
        logger.warning("AgentLibrary: Cosmos DB container returned 0 documents; using local fallback.")
    except Exception as exc:
        logger.warning("AgentLibrary: Cosmos DB unavailable (%s); using local fallback.", exc)

    _agent_cache_source = "local"
    return AGENT_CATALOG

COSMOS_STARTUP_STATUS: Dict[str, Any] = {
    "enabled": False,
    "required": False,
    "initialized": False,
    "containers": [],
    "template_seed": None,
    "starter_template_seed": None,
    "error": None,
}

_ORCHESTRATOR_MODULE = None
DISABLED_AGENT_ROLES = {"security_engineer"}


def _load_firebase_metadata() -> Dict[str, Any]:
    """Load non-sensitive Firebase metadata from service account path in env."""
    configured = False
    project_id = None
    client_email = None
    path_raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "").strip()
    if not path_raw:
        return {"configured": configured, "project_id": project_id, "client_email": client_email}

    candidate = Path(path_raw)
    if not candidate.is_absolute():
        candidate = Path(__file__).resolve().parent / candidate

    try:
        if candidate.exists() and candidate.is_file():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            configured = True
            project_id = payload.get("project_id")
            client_email = payload.get("client_email")
    except Exception:
        configured = False

    return {"configured": configured, "project_id": project_id, "client_email": client_email}


firebase_meta = _load_firebase_metadata()


def _project_generated_dir(project_id: str) -> Path:
    return store.generated_root / project_id


def _project_log_file(project_id: str) -> Path:
    store.logs_root.mkdir(parents=True, exist_ok=True)
    return store.logs_root / f"{project_id}.log"


def _frontend_preview_bases(project_id: str) -> List[Path]:
    """Candidate frontend output roots for preview serving."""
    project_root = _project_generated_dir(project_id)
    candidates = [
        project_root / "frontend_engineer",
        project_root / "frontend",
    ]
    return [p for p in candidates if p.exists() and p.is_dir()]


def _discover_frontend_preview_target(project_id: str) -> Optional[Tuple[Path, str]]:
    """Return (base_dir, relative_entry_path) for preview entry when available."""
    bases = _frontend_preview_bases(project_id)
    if not bases:
        return None

    preferred = [
        "index.html",
        "dist/index.html",
        "public/index.html",
        "build/index.html",
    ]
    for base in bases:
        for rel in preferred:
            p = base / rel
            if p.exists() and p.is_file():
                return base, rel

        for p in sorted(base.rglob("index.html")):
            if p.is_file():
                try:
                    return base, str(p.relative_to(base)).replace("\\", "/")
                except Exception:
                    continue
    return None


def _discover_frontend_preview_entry(project_id: str) -> Optional[str]:
    """Return relative preview entry path when available."""
    target = _discover_frontend_preview_target(project_id)
    if not target:
        return None
    _base, rel = target
    return rel


def _inject_preview_console_bridge(html: str, project_id: str) -> str:
        """Inject script that forwards generated-frontend console output to preview parent window."""
        if not isinstance(html, str) or not html:
                return html

        marker = "data-nexus-preview-bridge=\"1\""
        if marker in html:
                return html

        bridge = f"""
<script {marker}>
(function() {{
    if (window.__NEXUS_PREVIEW_BRIDGE__) return;
    window.__NEXUS_PREVIEW_BRIDGE__ = true;

    var PROJECT_ID = {json.dumps(project_id)};
    function send(level, msg) {{
        try {{
            var text = (typeof msg === 'string') ? msg : (msg && msg.message ? String(msg.message) : String(msg));
            window.parent && window.parent.postMessage({{
                type: 'nexus_generated_frontend_output',
                project_id: PROJECT_ID,
                level: String(level || 'log'),
                message: text,
                ts: Date.now()
            }}, '*');
        }} catch (_e) {{}}
    }}

    ['log', 'info', 'warn', 'error', 'debug'].forEach(function(level) {{
        var orig = console[level];
        console[level] = function() {{
            try {{
                var args = Array.prototype.slice.call(arguments || []);
                var msg = args.map(function(a) {{
                    if (typeof a === 'string') return a;
                    try {{ return JSON.stringify(a); }} catch (_err) {{ return String(a); }}
                }}).join(' ');
                send(level, msg);
            }} catch (_err) {{}}
            if (typeof orig === 'function') return orig.apply(console, arguments);
        }};
    }});

    window.addEventListener('error', function(evt) {{
        var msg = (evt && (evt.message || (evt.error && evt.error.message))) || 'window error';
        send('error', msg);
    }});

    window.addEventListener('unhandledrejection', function(evt) {{
        var reason = evt && evt.reason;
        var msg = (reason && reason.message) ? reason.message : String(reason || 'unhandled rejection');
        send('error', msg);
    }});
}})();
</script>
"""

        if "</body>" in html:
                return html.replace("</body>", bridge + "</body>")
        return html + bridge


def _append_project_log(project_id: str, event: str, **data: Any) -> None:
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": event,
        **data,
    }
    line = json.dumps(payload, ensure_ascii=False)
    try:
        with _project_log_file(project_id).open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as exc:
        logger.warning("Could not append project log for %s: %s", project_id, exc)


def _service_api_keys_file(project_id: str) -> Path:
    workspace_dir = REPO_ROOT / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir / f"service_api_keys_{project_id}.json"


def _load_service_api_keys(project_id: str) -> Dict[str, str]:
    path = _service_api_keys_file(project_id)
    download_blob_to_local_path(str(path))
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        result: Dict[str, str] = {}
        for service, key in data.items():
            service_name = str(service or "").strip()
            key_value = str(key or "").strip()
            if service_name and key_value:
                result[service_name] = key_value
        return result
    except Exception:
        return {}


def _save_service_api_keys(project_id: str, keys: Dict[str, str]) -> Dict[str, str]:
    sanitized: Dict[str, str] = {}
    for service, key in (keys or {}).items():
        service_name = str(service or "").strip()
        key_value = str(key or "").strip()
        if service_name and key_value:
            sanitized[service_name] = key_value

    path = _service_api_keys_file(project_id)
    payload = json.dumps(sanitized, indent=2, ensure_ascii=False)
    ok, detail = write_text_azure_first(str(path), payload)
    if not ok:
        raise RuntimeError(f"Failed to save service API keys (azure-first): {detail}")
    return sanitized


def _canonicalize_service_name(service_name: str) -> str:
    value = str(service_name or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def _service_name_to_env_var(service_name: str) -> str:
    canonical = _canonicalize_service_name(service_name)
    env_map: Dict[str, str] = {
        "openai": "OPENAI_API_KEY",
        "azure_openai": "AZURE_OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google_gemini": "GEMINI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "stripe": "STRIPE_API_KEY",
        "twilio": "TWILIO_API_KEY",
        "sendgrid": "SENDGRID_API_KEY",
        "github": "GITHUB_TOKEN",
        "google_maps": "GOOGLE_MAPS_API_KEY",
        "weather": "WEATHER_API_KEY",
        "serpapi": "SERPAPI_API_KEY",
        "supabase": "SUPABASE_API_KEY",
        "pinecone": "PINECONE_API_KEY",
        "mongodb": "MONGODB_URI",
        "mongodb_atlas": "MONGODB_URI",
        "atlas": "MONGODB_URI",
        "postgres": "POSTGRES_URL",
        "postgresql": "POSTGRES_URL",
        "neon": "POSTGRES_URL",
        "planetscale": "DATABASE_URL",
        "redis": "REDIS_URL",
        "upstash": "UPSTASH_REDIS_REST_TOKEN",
    }
    if canonical in env_map:
        return env_map[canonical]
    if not canonical:
        return "SERVICE_API_KEY"
    return f"{canonical.upper()}_API_KEY"


def _write_project_env_file(project_id: str, service_api_keys: Dict[str, str]) -> Optional[str]:
    if not service_api_keys:
        return None

    lines = [
        "# Auto-generated by Nexus from provided service API keys",
        "# Do not commit this file to source control.",
        "",
    ]
    written_vars: set[str] = set()
    for service_name, api_key in sorted(service_api_keys.items(), key=lambda item: str(item[0]).lower()):
        key_value = str(api_key or "").strip()
        if not key_value:
            continue
        env_name = _service_name_to_env_var(service_name)
        if env_name in written_vars:
            continue
        escaped = key_value.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f"{env_name}=\"{escaped}\"")
        written_vars.add(env_name)

    if len(lines) <= 3:
        return None

    env_content = "\n".join(lines) + "\n"
    project_dir = _project_generated_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    env_path = project_dir / ".env"
    ok, detail = write_text_azure_first(str(env_path), env_content)
    if not ok:
        raise RuntimeError(f"Failed to write generated .env file: {detail}")
    return str(env_path)


def _set_runtime_api_key_envs(service_api_keys: Dict[str, str]) -> Dict[str, Optional[str]]:
    """Temporarily set runtime env vars from saved service keys and return previous values."""
    previous: Dict[str, Optional[str]] = {}
    clean_keys: Dict[str, str] = {}
    for service, key in (service_api_keys or {}).items():
        service_name = str(service or "").strip()
        key_value = str(key or "").strip()
        if not service_name or not key_value:
            continue
        clean_keys[service_name] = key_value
        env_var = _service_name_to_env_var(service_name)
        previous[env_var] = os.environ.get(env_var)
        os.environ[env_var] = key_value

    if clean_keys:
        previous["NEXUS_SERVICE_API_KEYS_JSON"] = os.environ.get("NEXUS_SERVICE_API_KEYS_JSON")
        os.environ["NEXUS_SERVICE_API_KEYS_JSON"] = json.dumps(clean_keys, ensure_ascii=False)

    return previous


def _restore_runtime_api_key_envs(previous_env: Dict[str, Optional[str]]) -> None:
    for env_var, old_value in (previous_env or {}).items():
        if old_value is None:
            os.environ.pop(env_var, None)
        else:
            os.environ[env_var] = old_value


def _sync_project_from_blob(project_id: str) -> None:
    if not BLOB_WORKSPACE:
        return

    now = time.time()
    last_sync = _BLOB_SYNC_LAST_DOWNLOAD_TS.get(project_id)
    if (
        _BLOB_SYNC_MIN_INTERVAL_SECONDS > 0
        and last_sync is not None
        and (now - last_sync) < _BLOB_SYNC_MIN_INTERVAL_SECONDS
    ):
        return

    local_dir = _project_generated_dir(project_id)
    local_dir.mkdir(parents=True, exist_ok=True)
    for stale in [local_dir / "runtime", local_dir / "generated_code"]:
        try:
            if stale.exists() and stale.is_dir():
                shutil.rmtree(stale)
        except Exception as exc:
            logger.warning("Could not remove stale recursive folder %s: %s", stale, exc)
    workspace_dir = REPO_ROOT / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    try:
        count = 0
        # Preferred runtime source-of-truth layout.
        count += BLOB_WORKSPACE.download_project(
            project_id,
            str(workspace_dir),
            remote_prefix="runtime/workspace",
        )

        # Optional legacy path support (disabled by default to avoid recursive nesting).
        if _ENABLE_LEGACY_BLOB_PROJECT_SYNC:
            count += BLOB_WORKSPACE.download_project(project_id, str(local_dir))
        _BLOB_SYNC_LAST_DOWNLOAD_TS[project_id] = now
        if _BLOB_SYNC_VERBOSE_DOWNLOAD_LOGS:
            logger.info("Blob sync download complete for %s: %s files -> %s", project_id, count, local_dir.resolve())
            _append_project_log(
                project_id,
                "blob_download",
                file_count=count,
                local_path=str(local_dir.resolve()),
            )
        elif count > 0:
            logger.info("Blob sync download updated %s: %s files -> %s", project_id, count, local_dir.resolve())
    except Exception as exc:
        _report_blob_error("Blob download failed", exc, project_id=project_id)
        _append_project_log(project_id, "blob_download_failed", error=f"{type(exc).__name__}: {exc}")


def _sync_project_to_blob(project_id: str) -> None:
    if not BLOB_WORKSPACE:
        return
    local_dir = _project_generated_dir(project_id)
    workspace_dir = REPO_ROOT / "workspace"
    try:
        count = 0
        # Source-of-truth runtime layout in Azure.
        if workspace_dir.exists():
            count += BLOB_WORKSPACE.upload_project(
                project_id,
                str(workspace_dir),
                remote_prefix="runtime/workspace",
            )

        # Optional legacy mirror path (disabled by default to avoid recursive nesting).
        if _ENABLE_LEGACY_BLOB_PROJECT_SYNC and _ENABLE_LOCAL_FILE_GENERATION and local_dir.exists():
            count += BLOB_WORKSPACE.upload_project(project_id, str(local_dir))

        logger.info("Blob sync upload complete for %s: %s files <- %s", project_id, count, local_dir.resolve())
        _append_project_log(
            project_id,
            "blob_upload",
            file_count=count,
            local_path=str(local_dir.resolve()),
            source_of_truth_prefixes=["runtime/workspace"],
        )
    except Exception as exc:
        _report_blob_error("Blob upload failed", exc, project_id=project_id)
        _append_project_log(project_id, "blob_upload_failed", error=f"{type(exc).__name__}: {exc}")


def _resolve_orchestrator_main_path() -> Path:
    env_path = (os.getenv("ORCHESTRATOR_MAIN_PATH") or "").strip()
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent / p
        return p
    return Path(__file__).resolve().parent / "Azure_Hack-hritxjujjhar" / "platform-backend" / "main.py"


def _load_orchestrator_module():
    global _ORCHESTRATOR_MODULE
    if _ORCHESTRATOR_MODULE is not None:
        return _ORCHESTRATOR_MODULE

    main_path = _resolve_orchestrator_main_path()
    if not main_path.exists():
        raise RuntimeError(f"Orchestrator main.py not found at: {main_path}")

    module_dir = str(main_path.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)

    spec = importlib.util.spec_from_file_location("platform_backend_main", str(main_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load orchestrator module spec")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _ORCHESTRATOR_MODULE = module
    return module


def _snapshot_generated_output_for_project(project_id: str) -> None:
    """Copy generated outputs into project-scoped local reference folder."""
    if not _ENABLE_LOCAL_FILE_GENERATION:
        return

    project_root = _project_generated_dir(project_id)
    project_root.mkdir(parents=True, exist_ok=True)

    # Cleanup stale recursive folders created by older sync logic.
    # We only remove known problematic roots under the project folder.
    for stale in [project_root / "runtime", project_root / "generated_code"]:
        try:
            if stale.exists() and stale.is_dir():
                shutil.rmtree(stale)
        except Exception as exc:
            logger.warning("Could not remove stale recursive folder %s: %s", stale, exc)

    # Upload is intentionally performed via _sync_project_to_blob() so the
    # configured BlobWorkspace path remains the single write mechanism.


def _blob_autosync_enabled() -> bool:
    return bool(BLOB_WORKSPACE) and bool(_BLOB_AUTOSYNC_ENABLED)


async def _project_blob_autosync_worker(project_id: str) -> None:
    _append_project_log(
        project_id,
        "blob_autosync_started",
        interval_seconds=_BLOB_AUTOSYNC_INTERVAL_SECONDS,
    )
    try:
        while True:
            project = store.get(project_id)
            if not project:
                break

            status = str(project.get("status") or "")
            if status not in _ACTIVE_PROJECT_STATES_FOR_AUTOSYNC:
                break

            try:
                _snapshot_generated_output_for_project(project_id)
                _sync_project_to_blob(project_id)
            except Exception as exc:
                _report_blob_error("Blob autosync iteration failed", exc, project_id=project_id)

            await asyncio.sleep(_BLOB_AUTOSYNC_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        _append_project_log(project_id, "blob_autosync_cancelled")
        raise
    except Exception as exc:
        _report_blob_error("Blob autosync worker failed", exc, project_id=project_id)
    finally:
        _PROJECT_BLOB_AUTOSYNC_TASKS.pop(project_id, None)
        _append_project_log(project_id, "blob_autosync_stopped")


def _start_project_blob_autosync(project_id: str) -> None:
    if not _blob_autosync_enabled():
        return
    existing = _PROJECT_BLOB_AUTOSYNC_TASKS.get(project_id)
    if existing and not existing.done():
        return
    _PROJECT_BLOB_AUTOSYNC_TASKS[project_id] = asyncio.create_task(_project_blob_autosync_worker(project_id))


def _stop_project_blob_autosync(project_id: str) -> None:
    task = _PROJECT_BLOB_AUTOSYNC_TASKS.get(project_id)
    if not task or task.done():
        return
    task.cancel()


def _deep_merge_dict(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge dict updates into base."""
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge_dict(base[k], v)
        else:
            base[k] = v
    return base


def _ensure_minimum_agent_spec(ledger_data: Dict[str, Any]) -> None:
    """Guarantee orchestrator-required agent specs exist."""
    spec = ledger_data.setdefault("agent_specifications", {})
    required = spec.get("required_agents")
    layers = spec.get("layers")

    has_required = isinstance(required, list) and len(required) > 0
    has_layers = isinstance(layers, list) and len(layers) > 0
    if has_required and has_layers:
        return

    default_roles = [
        "system_architect",
        "database_architect",
        "backend_engineer",
        "frontend_engineer",
        "qa_engineer",
    ]
    spec["required_agents"] = [
        {
            "role": role,
            "description": f"{role.replace('_', ' ').title()} for project implementation",
            "instructions": "Implement role deliverables based on task ledger and upstream artifacts.",
        }
        for role in default_roles
    ]
    spec["layers"] = [
        ["system_architect"],
        ["database_architect"],
        ["backend_engineer"],
        ["frontend_engineer"],
        ["qa_engineer"],
    ]


def _remove_disabled_roles_from_ledger(ledger_data: Dict[str, Any]) -> None:
    """Remove disabled roles from required_agents/layers/dependencies/layout.

    This guards against older prompts producing deprecated roles.
    """
    if not isinstance(ledger_data, dict):
        return

    spec = ledger_data.get("agent_specifications")
    if not isinstance(spec, dict):
        return

    required = spec.get("required_agents")
    if isinstance(required, list):
        cleaned_required = []
        for entry in required:
            if isinstance(entry, str):
                role = entry.strip().lower().replace(" ", "_")
            elif isinstance(entry, dict):
                role = str(entry.get("role") or entry.get("agent_name") or "").strip().lower().replace(" ", "_")
            else:
                continue
            if role in DISABLED_AGENT_ROLES:
                continue
            cleaned_required.append(entry)
        spec["required_agents"] = cleaned_required

    layers = spec.get("layers")
    if isinstance(layers, list):
        cleaned_layers = []
        for layer in layers:
            if isinstance(layer, list):
                normalized = [
                    r for r in layer
                    if isinstance(r, str)
                    and str(r).strip().lower().replace(" ", "_") not in DISABLED_AGENT_ROLES
                ]
                if normalized:
                    cleaned_layers.append(normalized)
            elif isinstance(layer, dict):
                layer_agents = layer.get("agents", [])
                if not isinstance(layer_agents, list):
                    continue
                filtered_agents = []
                for a in layer_agents:
                    if isinstance(a, str):
                        role = a.strip().lower().replace(" ", "_")
                    elif isinstance(a, dict):
                        role = str(a.get("role") or a.get("agent_name") or "").strip().lower().replace(" ", "_")
                    else:
                        continue
                    if role in DISABLED_AGENT_ROLES:
                        continue
                    filtered_agents.append(a)
                if filtered_agents:
                    layer_copy = dict(layer)
                    layer_copy["agents"] = filtered_agents
                    cleaned_layers.append(layer_copy)
        spec["layers"] = cleaned_layers

    deps = spec.get("agent_dependencies")
    if isinstance(deps, dict):
        cleaned_deps: Dict[str, Any] = {}
        for role, dep_list in deps.items():
            role_norm = str(role or "").strip().lower().replace(" ", "_")
            if role_norm in DISABLED_AGENT_ROLES:
                continue
            if isinstance(dep_list, list):
                filtered = [
                    d for d in dep_list
                    if str(d or "").strip().lower().replace(" ", "_") not in DISABLED_AGENT_ROLES
                ]
            else:
                filtered = []
            cleaned_deps[role] = filtered
        spec["agent_dependencies"] = cleaned_deps

    layout = ledger_data.get("workspace_layout")
    if isinstance(layout, dict):
        role_map = layout.get("role_output_roots")
        if isinstance(role_map, dict):
            for disabled in DISABLED_AGENT_ROLES:
                role_map.pop(disabled, None)


def _normalize_workspace_layout_paths(ledger_data: Dict[str, Any]) -> None:
    """Keep generated files rooted under workspace/ without project-name subfolders."""
    layout = ledger_data.get("workspace_layout")
    if not isinstance(layout, dict):
        return

    project_id = str(ledger_data.get("project_id") or "").strip().lower()
    project_name = str(ledger_data.get("project_name") or "").strip().lower().replace(" ", "_")
    strip_candidates = {x for x in [project_id, project_name] if x}

    root_keys = ["root", "roles"]
    for k in root_keys:
        layout.pop(k, None)

    def _clean_path(path: str) -> str:
        p = str(path or "").replace("\\", "/").strip()
        for prefix in ["./workspace/", "workspace/", "./"]:
            if p.startswith(prefix):
                p = p[len(prefix):]
        p = p.strip("/")
        parts = [x for x in p.split("/") if x]
        if parts and parts[0].lower() in strip_candidates:
            parts = parts[1:]
        return "/".join(parts)

    dirs = layout.get("directories", [])
    if isinstance(dirs, list):
        cleaned_dirs = []
        for d in dirs:
            c = _clean_path(str(d))
            if c and c not in cleaned_dirs:
                cleaned_dirs.append(c)
        layout["directories"] = cleaned_dirs

    role_map = layout.get("role_output_roots", {})
    if isinstance(role_map, dict):
        cleaned_role_map: Dict[str, Any] = {}
        for role, roots in role_map.items():
            if isinstance(roots, str):
                roots = [roots]
            if not isinstance(roots, list):
                continue
            clean_roots = []
            for r in roots:
                c = _clean_path(str(r))
                if c and c not in clean_roots:
                    clean_roots.append(c)
            if len(clean_roots) == 1:
                cleaned_role_map[role] = clean_roots[0]
            elif clean_roots:
                cleaned_role_map[role] = clean_roots
        layout["role_output_roots"] = cleaned_role_map


def _ledger_has_agent_plan(ledger_data: Any) -> bool:
    """Return True when the ledger has a usable Director-generated plan."""
    if not isinstance(ledger_data, dict):
        return False
    spec = ledger_data.get("agent_specifications")
    if not isinstance(spec, dict):
        return False
    required = spec.get("required_agents")
    layers = spec.get("layers")
    return (
        isinstance(required, list)
        and len(required) > 0
        and isinstance(layers, list)
        and len(layers) > 0
    )


def _normalize_required_api_key_services(ledger_data: Dict[str, Any]) -> List[str]:
    """Return a cleaned, de-duplicated list of service names requiring API keys."""
    if not isinstance(ledger_data, dict):
        return []

    raw = ledger_data.get("required_api_key_services", [])
    if not isinstance(raw, list):
        raw = []

    cleaned: List[str] = []
    seen = set()
    for item in raw:
        name = str(item or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(name)
    return cleaned


def _infer_required_api_key_services(ledger_data: Dict[str, Any]) -> List[str]:
    """Infer likely API-key services from ledger stack/integration hints."""
    text_chunks: List[str] = []

    def _collect(value: Any) -> None:
        if isinstance(value, str):
            text_chunks.append(value)
        elif isinstance(value, list):
            for item in value:
                _collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                _collect(item)

    _collect(ledger_data.get("technology_stack", {}))
    _collect(ledger_data.get("integration_targets", []))
    _collect(ledger_data.get("tech_constraints", {}))
    _collect(ledger_data.get("functional_requirements", []))
    _collect(ledger_data.get("feature_catalog", []))

    haystack = " ".join(text_chunks).lower()
    service_rules = [
        ("openai", "OpenAI"),
        ("anthropic", "Anthropic"),
        ("claude", "Anthropic"),
        ("gemini", "Google Gemini"),
        ("google ai studio", "Google Gemini"),
        ("stripe", "Stripe"),
        ("twilio", "Twilio"),
        ("sendgrid", "SendGrid"),
        ("mailgun", "Mailgun"),
        ("resend", "Resend"),
        ("supabase", "Supabase"),
        ("firebase", "Firebase"),
        ("pinecone", "Pinecone"),
        ("serpapi", "SerpAPI"),
        ("hugging face", "Hugging Face"),
        ("mongodb atlas", "MongoDB Atlas"),
        ("postgres", "Postgres"),
        ("postgresql", "Postgres"),
        ("redis", "Redis"),
    ]

    inferred: List[str] = []
    for needle, service_name in service_rules:
        if needle in haystack and service_name not in inferred:
            inferred.append(service_name)

    # Nuanced MongoDB Atlas inference: include only when managed/cloud cues are present.
    mongodb_present = "mongodb" in haystack
    atlas_cues = [
        "mongodb atlas",
        "atlas",
        "mongodb+srv",
        "connection string",
        "managed mongodb",
        "hosted mongodb",
        "cloud mongodb",
        "mongo uri",
        "mongodb uri",
    ]
    if mongodb_present and any(cue in haystack for cue in atlas_cues):
        if "MongoDB Atlas" not in inferred:
            inferred.append("MongoDB Atlas")

    return inferred


def _infer_required_api_key_services_from_text(spec_text: str) -> List[str]:
    """Infer likely API-key services from plain specification text."""
    haystack = str(spec_text or "").lower()
    if not haystack.strip():
        return []

    service_rules = [
        ("openai", "OpenAI"),
        ("anthropic", "Anthropic"),
        ("claude", "Anthropic"),
        ("gemini", "Google Gemini"),
        ("google ai studio", "Google Gemini"),
        ("stripe", "Stripe"),
        ("twilio", "Twilio"),
        ("sendgrid", "SendGrid"),
        ("mailgun", "Mailgun"),
        ("resend", "Resend"),
        ("supabase", "Supabase"),
        ("firebase", "Firebase"),
        ("pinecone", "Pinecone"),
        ("serpapi", "SerpAPI"),
        ("hugging face", "Hugging Face"),
        ("google cloud vision", "Google Cloud Vision API"),
        ("mongodb atlas", "MongoDB Atlas"),
        ("postgres", "Postgres"),
        ("postgresql", "Postgres"),
        ("redis", "Redis"),
    ]

    inferred: List[str] = []
    for needle, service_name in service_rules:
        if needle in haystack and service_name not in inferred:
            inferred.append(service_name)

    # Nuanced MongoDB Atlas inference: do not assume Atlas for generic MongoDB usage.
    mongodb_present = "mongodb" in haystack
    atlas_cues = [
        "mongodb atlas",
        "atlas",
        "mongodb+srv",
        "connection string",
        "managed mongodb",
        "hosted mongodb",
        "cloud mongodb",
        "mongo uri",
        "mongodb uri",
    ]
    if mongodb_present and any(cue in haystack for cue in atlas_cues):
        if "MongoDB Atlas" not in inferred:
            inferred.append("MongoDB Atlas")

    return inferred


async def _generate_task_ledger_only(project_id: str, user_input: str, owner_id: str) -> Dict[str, Any]:
    """Run Director-only flow to produce a finalized ledger without running the orchestrator."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from director_agent import DirectorAI, TaskLedger, normalize_layers_common_sense, default_workspace_layout

    director = DirectorAI()
    ledger = TaskLedger(user_input, owner_id)
    ledger.data["project_id"] = project_id

    workspace_dir = REPO_ROOT / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    ledger_file = workspace_dir / f"ledger_{project_id}.json"

    # Seed initial ledger so director tooling can always read from disk.
    seed_payload = json.dumps(ledger.data, indent=2)
    ok, detail = write_text_azure_first(str(ledger_file), seed_payload)
    if not ok:
        raise RuntimeError(f"Failed to seed task ledger: {detail}")

    previous_ledger: Optional[Dict[str, Any]] = None
    max_director_iterations = int(os.getenv("DIRECTOR_MAX_ITERATIONS", "3"))
    director_iteration_timeout_env = int(os.getenv("DIRECTOR_ITERATION_TIMEOUT_SECONDS", "0"))
    director_iteration_timeout: Optional[int] = (
        director_iteration_timeout_env if director_iteration_timeout_env > 0 else None
    )

    thought: str = ""
    loop = asyncio.get_event_loop()
    for iteration in range(1, max_director_iterations + 1):
        director_future = loop.run_in_executor(
            None,
            lambda: director.clarify_intent_with_thought(
                ledger,
                iteration,
                previous_ledger,
                {},
            ),
        )
        if director_iteration_timeout:
            ledger_data, thought, _follow_ups = await asyncio.wait_for(
                director_future,
                timeout=director_iteration_timeout,
            )
        else:
            ledger_data, thought, _follow_ups = await director_future

        if not isinstance(ledger_data, dict):
            raise RuntimeError("Director Agent returned invalid ledger payload")

        _deep_merge_dict(ledger.data, ledger_data)
        previous_ledger = ledger_data

        spec = ledger.data.get("agent_specifications", {}) if isinstance(ledger.data, dict) else {}
        required = spec.get("required_agents") if isinstance(spec, dict) else None
        layers = spec.get("layers") if isinstance(spec, dict) else None
        done = str(ledger.data.get("status", "")).upper() == "DONE"
        has_required = isinstance(required, list) and len(required) > 0
        has_layers = isinstance(layers, list) and len(layers) > 0
        if has_required and has_layers and done:
            break

    normalize_layers_common_sense(ledger.data)
    _remove_disabled_roles_from_ledger(ledger.data)

    if not isinstance(ledger.data.get("workspace_layout"), dict):
        ledger.data["workspace_layout"] = default_workspace_layout()
    _ensure_minimum_agent_spec(ledger.data)
    _normalize_workspace_layout_paths(ledger.data)

    explicit_services = _normalize_required_api_key_services(ledger.data)
    if explicit_services:
        required_services = explicit_services
    else:
        required_services = _infer_required_api_key_services(ledger.data)
    if not required_services:
        required_services = _infer_required_api_key_services_from_text(user_input)
    ledger.data["required_api_key_services"] = required_services
    ledger.data.setdefault("service_api_keys", {service: "" for service in required_services})
    ledger.data["status"] = "DONE"

    ledger_json = json.dumps(ledger.data, indent=2)
    ok, detail = write_text_azure_first(str(ledger_file), ledger_json)
    if not ok:
        raise RuntimeError(f"Failed to persist generated task ledger: {detail}")

    _append_project_log(
        project_id,
        "director_task_ledger_generated",
        required_api_key_services=required_services,
        path=str(ledger_file.resolve()),
        thought=(thought[:200] if thought else ""),
    )
    return ledger.data


def _generate_director_questions(user_intent: str) -> List[str]:
    """Generate 3 concise clarification questions from Director context."""
    try:
        from director_agent import DirectorAI
        director = DirectorAI()
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the Director Agent. Ask exactly 3 concise clarification questions. "
                    "Return only JSON with key 'questions' as an array of 3 strings."
                ),
            },
            {
                "role": "user",
                "content": f"User intent: {user_intent}",
            },
        ]
        response = director.client.chat.completions.create(
            model=AZURE_MODEL_DEPLOYMENT,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        payload = json.loads(response.choices[0].message.content)
        questions = payload.get("questions", [])
        if isinstance(questions, list):
            cleaned = [str(q).strip() for q in questions if str(q).strip()]
            if len(cleaned) >= 3:
                return cleaned[:3]
    except Exception as exc:
        logger.warning("Question generation fallback used: %s", exc)

    return [
        "What are the top 3 features you want in version 1?",
        "Do you have a preferred tech stack or constraints?",
        "What should be prioritized first: speed, design polish, or scalability?",
    ]


async def _invoke_real_orchestrator(project_id: str, project_data: Dict[str, Any]) -> Dict[str, Any]:
    user_input = project_data.get("user_intent", "Create a web application")
    project_name = project_data.get("project_name", f"Project-{project_id[:8]}")
    owner_id = project_data.get("owner_id", project_id)
    timeout_env = int(os.getenv("AGENT_TIMEOUT_SECONDS", "0"))
    timeout_s: Optional[int] = timeout_env if timeout_env > 0 else None
    director_iteration_timeout_env = int(os.getenv("DIRECTOR_ITERATION_TIMEOUT_SECONDS", "0"))
    director_iteration_timeout: Optional[int] = (
        director_iteration_timeout_env if director_iteration_timeout_env > 0 else None
    )
    previous_service_env: Dict[str, Optional[str]] = {}

    try:
        prev_active_project_id = os.getenv("NEXUS_ACTIVE_PROJECT_ID")
        prev_workspace_root = os.getenv("NEXUS_WORKSPACE_ROOT")
        os.environ["NEXUS_ACTIVE_PROJECT_ID"] = str(project_id)
        os.environ["NEXUS_WORKSPACE_ROOT"] = str((REPO_ROOT / "workspace").resolve())

        saved_service_keys = _load_service_api_keys(project_id)
        if saved_service_keys:
            previous_service_env = _set_runtime_api_key_envs(saved_service_keys)

        # Step 0: Read project specifications file if it exists
        project_specs = _read_project_specs_file(project_id)
        if project_specs:
            # Prepend specs to user input so director has full context
            user_input = f"PROJECT SPECIFICATIONS:\n\n{project_specs}\n\nADDITIONAL CONTEXT:\n{user_input}"
            logger.info("Director agent will use gathered specifications for project %s", project_id)
            _append_project_log(project_id, "director_agent_using_specs", specs_length=len(project_specs))
        
        # Step 1: Import director and orchestrator modules
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from director_agent import DirectorAI, TaskLedger, normalize_layers_common_sense, default_workspace_layout
        from agent_orchestrator_v3 import EnhancedAgentOrchestrator
        
        logger.info("Step 1: Director Agent - Generating task ledger for %s", project_id)
        _append_project_log(project_id, "director_agent_start", user_intent=user_input[:200])
        
        # Step 2: Create task ledger via Director Agent (iterative refinement)
        director = DirectorAI()
        ledger = TaskLedger(user_input, owner_id)
        # Keep ledger id aligned with API project id so tool-based reads/writes resolve consistently.
        ledger.data["project_id"] = project_id
        previous_ledger: Optional[Dict[str, Any]] = None
        max_director_iterations = int(os.getenv("DIRECTOR_MAX_ITERATIONS", "3"))
        thought = ""

        workspace_dir = REPO_ROOT / "workspace"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        initial_ledger_file = workspace_dir / f"ledger_{project_id}.json"
        if initial_ledger_file.exists() and initial_ledger_file.is_file():
            try:
                existing_ledger_data = json.loads(initial_ledger_file.read_text(encoding="utf-8"))
                if _ledger_has_agent_plan(existing_ledger_data):
                    _deep_merge_dict(ledger.data, existing_ledger_data)
                    max_director_iterations = 0
                    _append_project_log(
                        project_id,
                        "director_existing_ledger_reused",
                        path=str(initial_ledger_file.resolve()),
                    )
            except Exception as exc:
                logger.warning("Could not parse existing ledger for %s: %s", project_id, exc)

        # Seed ledger file BEFORE first director tool call.
        # Director prompts mandate read_task_ledger() first; without this file, the model can loop on read errors.
        if max_director_iterations > 0:
            initial_ledger_file.write_text(json.dumps(ledger.data, indent=2), encoding="utf-8")
            _append_project_log(
                project_id,
                "ledger_seeded",
                ledger_id=project_id,
                path=str(initial_ledger_file.resolve()),
            )
        
        # Call director multiple times to converge on a complete ledger.
        loop = asyncio.get_event_loop()
        for iteration in range(1, max_director_iterations + 1):
            director_future = loop.run_in_executor(
                None,
                lambda: director.clarify_intent_with_thought(
                    ledger,
                    iteration,
                    previous_ledger,
                    {},
                ),
            )
            if director_iteration_timeout:
                ledger_data, thought, _follow_ups = await asyncio.wait_for(
                    director_future,
                    timeout=director_iteration_timeout,
                )
            else:
                ledger_data, thought, _follow_ups = await director_future

            if not isinstance(ledger_data, dict):
                raise RuntimeError("Director Agent returned invalid ledger payload")

            _deep_merge_dict(ledger.data, ledger_data)
            previous_ledger = ledger_data

            spec = ledger.data.get("agent_specifications", {}) if isinstance(ledger.data, dict) else {}
            required = spec.get("required_agents") if isinstance(spec, dict) else None
            layers = spec.get("layers") if isinstance(spec, dict) else None
            done = str(ledger.data.get("status", "")).upper() == "DONE"
            has_required = isinstance(required, list) and len(required) > 0
            has_layers = isinstance(layers, list) and len(layers) > 0
            _append_project_log(
                project_id,
                "director_iteration",
                iteration=iteration,
                has_required_agents=has_required,
                has_layers=has_layers,
                status=str(ledger.data.get("status", "")),
            )

            if has_required and has_layers and done:
                break

        normalize_layers_common_sense(ledger.data)
        _remove_disabled_roles_from_ledger(ledger.data)
        # Auto-inject chatbot_engineer when project intent/description mentions LLM/chat features
        _chatbot_keywords = [
            "chatbot", "llm", "ai assistant", "ai chat", "conversational",
            "openai", "chat feature", "chat api", "language model", "gpt",
        ]
        _intent_text = " ".join([
            str(ledger.data.get("user_intent", "")),
            str(ledger.data.get("project_description", "")),
            str(ledger.data.get("project_name", "")),
        ]).lower()
        _cb_spec = ledger.data.get("agent_specifications") or {}
        _cb_roles = {
            (a.get("role") if isinstance(a, dict) else a)
            for a in (_cb_spec.get("required_agents") or [])
        }
        if any(kw in _intent_text for kw in _chatbot_keywords) and "chatbot_engineer" not in _cb_roles:
            _cb_agent = {
                "role": "chatbot_engineer",
                "description": (
                    "Integrate an LLM-powered chatbot API into the backend. "
                    "Retrieve the FastAPI chatbot template, write backend/chatbot_api.py, "
                    "and wire the router into the app entry-point."
                ),
                "instructions": "",
            }
            if not isinstance(_cb_spec.get("required_agents"), list):
                _cb_spec["required_agents"] = []
            _cb_spec["required_agents"].append(_cb_agent)
            _cb_layers = _cb_spec.get("layers") or []
            _cb_inserted = False
            for _ci, _cl in enumerate(_cb_layers):
                if isinstance(_cl, list) and any(
                    (r.get("role") if isinstance(r, dict) else r) == "backend_engineer"
                    for r in _cl
                ):
                    _cb_layers.insert(_ci + 1, ["chatbot_engineer"])
                    _cb_inserted = True
                    break
            if not _cb_inserted:
                _cb_layers.append(["chatbot_engineer"])
            _cb_spec["layers"] = _cb_layers
            ledger.data["agent_specifications"] = _cb_spec
            logger.info("Auto-injected chatbot_engineer (LLM/chat intent detected) for %s", project_id)
        if not isinstance(ledger.data.get("workspace_layout"), dict):
            ledger.data["workspace_layout"] = default_workspace_layout()
        _ensure_minimum_agent_spec(ledger.data)
        _normalize_workspace_layout_paths(ledger.data)
        explicit_services = _normalize_required_api_key_services(ledger.data)
        if explicit_services:
            ledger.data["required_api_key_services"] = explicit_services
        else:
            ledger.data["required_api_key_services"] = _infer_required_api_key_services(ledger.data)
        if not ledger.data.get("required_api_key_services"):
            ledger.data["required_api_key_services"] = _infer_required_api_key_services_from_text(user_input)
        if not isinstance(ledger.data.get("service_api_keys"), dict):
            ledger.data["service_api_keys"] = {
                service: "" for service in (ledger.data.get("required_api_key_services") or [])
            }
        ledger.data["status"] = "DONE"

        ledger_id = str(ledger.data.get("project_id") or project_id)
        logger.info("Director Agent complete. Task ledger generated: %s", ledger_id)
        _append_project_log(project_id, "director_agent_complete", ledger_id=ledger_id, thought=thought[:200] if thought else "")
        
        # Step 3: Persist ledger to disk (director may not have written it)
        workspace_dir = REPO_ROOT / "workspace"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        ledger_file = workspace_dir / f"ledger_{ledger_id}.json"
        
        ledger_json = json.dumps(ledger.data, indent=2)
        ledger_file.write_text(ledger_json, encoding="utf-8")
        logger.info("Ledger persisted to: %s", ledger_file.resolve())
        _append_project_log(project_id, "ledger_persisted", ledger_id=ledger_id, path=str(ledger_file.resolve()), size=len(ledger_json))
        
        # Step 4: Run orchestrator with the ledger
        logger.info("Step 2: Orchestrator - Executing agents for ledger %s", ledger_id)
        _append_project_log(project_id, "orchestrator_start", ledger_id=ledger_id)
        
        orchestrator = EnhancedAgentOrchestrator(ledger_id)
        
        # Run orchestrator in executor (it's synchronous).
        # IMPORTANT: use a soft timeout so a long run does not get marked as failed
        # while worker threads continue producing output.
        orchestrator_future = loop.run_in_executor(None, orchestrator.execute_all_layers)
        if timeout_s:
            try:
                result = await asyncio.wait_for(asyncio.shield(orchestrator_future), timeout=timeout_s)
            except asyncio.TimeoutError:
                warn_msg = (
                    f"Orchestration exceeded soft timeout ({timeout_s}s); "
                    "continuing to wait for completion."
                )
                logger.warning("%s project=%s", warn_msg, project_id)
                _append_project_log(
                    project_id,
                    "orchestration_timeout_soft",
                    timeout_seconds=timeout_s,
                    message=warn_msg,
                )
                # Keep waiting (without timeout) for final completion result.
                result = await orchestrator_future
        else:
            result = await orchestrator_future
        
        logger.info("Orchestrator execution complete for ledger %s", ledger_id)
        _append_project_log(project_id, "orchestrator_complete", ledger_id=ledger_id)
        
        return {
            "status": "success",
            "project_id": project_id,
            "ledger_id": ledger_id,
            "mode": "director-orchestrator-pipeline",
            "message": "Generated via Director Agent → Orchestrator pipeline",
        }
        
    except Exception as exc:
        logger.exception("Orchestration failed for %s: %s", project_id, exc)
        _append_project_log(project_id, "orchestration_failed", error=str(exc)[:500])
        raise RuntimeError(f"Orchestration pipeline failed: {exc}")
    finally:
        if prev_active_project_id is None:
            os.environ.pop("NEXUS_ACTIVE_PROJECT_ID", None)
        else:
            os.environ["NEXUS_ACTIVE_PROJECT_ID"] = prev_active_project_id

        if prev_workspace_root is None:
            os.environ.pop("NEXUS_WORKSPACE_ROOT", None)
        else:
            os.environ["NEXUS_WORKSPACE_ROOT"] = prev_workspace_root
        _restore_runtime_api_key_envs(previous_service_env)


# ------------------------------
# Internal workers
# ------------------------------

async def _simulate_generation(project_id: str) -> None:
    """Background worker to run real orchestrator generation."""
    try:
        store.update(project_id, status=ProjectStatus.GENERATING_CODE, progress=10)
        _start_project_blob_autosync(project_id)
        project_dir = _project_generated_dir(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        _sync_project_from_blob(project_id)
        logger.info("Generation started for %s; local output dir: %s", project_id, project_dir.resolve())
        _append_project_log(
            project_id,
            "generation_started",
            local_output_dir=str(project_dir.resolve()),
            blob_enabled=bool(BLOB_WORKSPACE),
        )

        project = store.get(project_id)
        if not project:
            return

        result = await _invoke_real_orchestrator(project_id, project)

        def _looks_like_aeg_payload(payload: Any) -> bool:
            if not isinstance(payload, dict):
                return False
            has_legacy = isinstance(payload.get("nodes"), list) and isinstance(payload.get("edges"), list)
            has_specs = isinstance(payload.get("agent_specifications"), dict)
            return has_legacy or has_specs

        persisted_ledger = None
        ledger_file = REPO_ROOT / "workspace" / f"ledger_{project_id}.json"
        if ledger_file.exists() and ledger_file.is_file():
            try:
                persisted_ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Could not parse persisted ledger for %s: %s", project_id, exc)

        if _looks_like_aeg_payload(persisted_ledger):
            project["ledger_data"] = persisted_ledger
        elif _looks_like_aeg_payload(result):
            project["ledger_data"] = result
        project["updated_at"] = datetime.utcnow().isoformat()
        store._save()

        manifest = {
            "project_id": project_id,
            "generated_at": datetime.utcnow().isoformat(),
            "status": "completed",
            "result": result if isinstance(result, dict) else {"raw": str(result)},
        }
        (project_dir / "_nexus_execution.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        _snapshot_generated_output_for_project(project_id)

        _sync_project_to_blob(project_id)

        store.update(project_id, status=ProjectStatus.COMPLETED, progress=100)
        _append_project_log(project_id, "generation_completed", progress=100)
    except Exception as exc:
        logger.exception("Generation failed for %s", project_id)
        store.update(project_id, status=ProjectStatus.FAILED, progress=0, error=str(exc))
        _append_project_log(project_id, "generation_failed", error=str(exc))
    finally:
        _stop_project_blob_autosync(project_id)


async def _simulate_deployment(project_id: str, request: DeploymentRequest) -> None:
    prev_active_project_id = os.getenv("NEXUS_ACTIVE_PROJECT_ID")
    prev_workspace_root = os.getenv("NEXUS_WORKSPACE_ROOT")
    try:
        os.environ["NEXUS_ACTIVE_PROJECT_ID"] = str(project_id)
        os.environ["NEXUS_WORKSPACE_ROOT"] = str((REPO_ROOT / "workspace").resolve())

        store.update(project_id, status=ProjectStatus.GENERATING_DEPLOYMENT, progress=60)
        _start_project_blob_autosync(project_id)
        _sync_project_from_blob(project_id)
        _append_project_log(
            project_id,
            "deployment_started",
            resource_group=request.resource_group,
            location=request.location,
            mock_success=bool(request.mock_success),
        )

        project_dir = _project_generated_dir(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)

        backend_rel = "backend_engineer" if (project_dir / "backend_engineer").exists() else "backend"
        frontend_rel = "frontend_engineer" if (project_dir / "frontend_engineer").exists() else "frontend"

        loop = asyncio.get_event_loop()

        def _run_deploy_agent() -> Dict[str, Any]:
            from deployment_agent_azure import AzureDeploymentAgent

            agent = AzureDeploymentAgent(
                project_root=project_dir,
                project_name=(store.get(project_id) or {}).get("project_name", project_id),
                backend_rel=backend_rel,
                frontend_rel=frontend_rel,
            )

            checklist_path = agent.run()
            result = agent.run_tool(
                "deploy_to_azure",
                mock_success=bool(request.mock_success),
                resource_group=request.resource_group,
                location=request.location,
            )

            return {
                "checklist_path": str(checklist_path),
                "result_path": str(agent.deploy_result),
                "result": {
                    "status": result.status,
                    "mode": result.mode,
                    "message": result.message,
                    "details": result.details,
                },
                "backend_rel": backend_rel,
                "frontend_rel": frontend_rel,
            }

        deploy_payload = await loop.run_in_executor(None, _run_deploy_agent)

        # Mirror summary under project deployment folder for easy artifact discovery.
        deploy_dir = project_dir / "deployment"
        deploy_dir.mkdir(parents=True, exist_ok=True)
        (deploy_dir / "deployment_summary.json").write_text(
            json.dumps(
                {
                    "project_id": project_id,
                    "generated_at": datetime.utcnow().isoformat(),
                    **deploy_payload,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        _sync_project_to_blob(project_id)

        result_obj = (deploy_payload or {}).get("result", {}) if isinstance(deploy_payload, dict) else {}
        result_status = str(result_obj.get("status", "")).lower()
        if result_status == "succeeded":
            store.update(project_id, status=ProjectStatus.COMPLETED, progress=100, error=None)
            _append_project_log(project_id, "deployment_completed", **result_obj)
        else:
            # Keep project usable; deployment failure is reported via deployment status/details.
            store.update(project_id, status=ProjectStatus.COMPLETED, progress=100, error=result_obj.get("message") or "Deployment failed")
            _append_project_log(project_id, "deployment_failed", **result_obj)
    except Exception as exc:
        logger.exception("Deployment failed for %s", project_id)
        store.update(project_id, status=ProjectStatus.COMPLETED, error=str(exc))
        _append_project_log(project_id, "deployment_failed_exception", error=str(exc))
    finally:
        _stop_project_blob_autosync(project_id)
        if prev_active_project_id is None:
            os.environ.pop("NEXUS_ACTIVE_PROJECT_ID", None)
        else:
            os.environ["NEXUS_ACTIVE_PROJECT_ID"] = prev_active_project_id

        if prev_workspace_root is None:
            os.environ.pop("NEXUS_WORKSPACE_ROOT", None)
        else:
            os.environ["NEXUS_WORKSPACE_ROOT"] = prev_workspace_root

def _read_project_specs_file(project_id: str) -> Optional[str]:
    """Read the project specifications file if it exists."""
    try:
        workspace_dir = REPO_ROOT / "workspace"
        spec_file = workspace_dir / f"project_specs_{project_id}.md"
        if spec_file.exists() and spec_file.is_file():
            content = spec_file.read_text(encoding="utf-8")
            logger.info("Read project specifications from: %s", spec_file.resolve())
            _append_project_log(project_id, "specs_file_read", spec_file=str(spec_file.resolve()))
            return content
    except Exception as exc:
        logger.warning("Could not read project specs file for %s: %s", project_id, exc)
    return None

def _check_input_safety(text: str) -> Dict[str, Any]:
    lowered = (text or "").lower()
    blocked_tokens = ["malware", "exploit", "ransomware"]
    for token in blocked_tokens:
        if token in lowered:
            return {
                "is_safe": False,
                "blocked_reason": f"Contains blocked content: {token}",
                "scores": {"violence": 0.0, "self_harm": 0.0, "sexual": 0.0, "hate": 0.0},
            }
    return {
        "is_safe": True,
        "blocked_reason": None,
        "scores": {"violence": 0.0, "self_harm": 0.0, "sexual": 0.0, "hate": 0.0},
    }


# ------------------------------
# Routes (parity with tentative-backend)
# ------------------------------

@app.get("/api/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    cosmos_payload = {
        "enabled": COSMOS_STARTUP_STATUS.get("enabled", False),
        "required": COSMOS_STARTUP_STATUS.get("required", False),
        "initialized": COSMOS_STARTUP_STATUS.get("initialized", False),
        "containers": COSMOS_STARTUP_STATUS.get("containers", []),
        "template_seed": COSMOS_STARTUP_STATUS.get("template_seed"),
        "starter_template_seed": COSMOS_STARTUP_STATUS.get("starter_template_seed"),
        "error": COSMOS_STARTUP_STATUS.get("error"),
    }
    return {
        "status": "healthy" if (not cosmos_payload["required"] or cosmos_payload["initialized"]) else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "cosmos": cosmos_payload,
    }


@app.get("/api/cosmos/health", tags=["Health", "Cosmos"])
async def cosmos_health_check():
    if not COSMOS_STARTUP_STATUS.get("enabled", False):
        return {
            "status": "disabled",
            "startup": COSMOS_STARTUP_STATUS,
            "health": None,
            "timestamp": datetime.utcnow().isoformat(),
        }

    try:
        health = await asyncio.to_thread(get_cosmos_client().health_check)
        status = "healthy" if health.get("connected") and not health.get("error") else "degraded"
        return {
            "status": status,
            "startup": COSMOS_STARTUP_STATUS,
            "health": health,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        return {
            "status": "error",
            "startup": COSMOS_STARTUP_STATUS,
            "health": None,
            "error": str(exc),
            "timestamp": datetime.utcnow().isoformat(),
        }


@app.post("/api/cosmos/templates/seed", tags=["Cosmos"])
async def seed_cosmos_templates():
    result = await asyncio.to_thread(seed_default_templates)
    status = "seeded" if result.get("ok") else "failed"
    return {
        "status": status,
        "result": result,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/api/cosmos/starter-templates/seed", tags=["Cosmos"])
async def seed_cosmos_starter_templates():
    result = await asyncio.to_thread(seed_starter_templates)
    status = "seeded" if result.get("ok") else "failed"
    return {
        "status": status,
        "result": result,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/cosmos/starter-templates/resolve/by-stack", tags=["Cosmos"])
async def resolve_cosmos_starter_template(stack: str = Query(..., description="Comma-separated stack tokens")):
    tokens = [token.strip().lower() for token in str(stack or "").split(",") if token.strip()]
    if not tokens:
        raise HTTPException(status_code=400, detail="stack query parameter is required")
    doc = await asyncio.to_thread(resolve_starter_template_for_stack, tokens)
    if not isinstance(doc, dict):
        raise HTTPException(status_code=404, detail=f"No starter template matched stack tokens: {tokens}")
    return {"template": doc, "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/cosmos/starter-templates/{template_id}", tags=["Cosmos"])
async def get_cosmos_starter_template(template_id: str):
    doc = await asyncio.to_thread(get_starter_template, template_id)
    if not isinstance(doc, dict):
        raise HTTPException(status_code=404, detail=f"Starter template not found: {template_id}")
    return {"template": doc, "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/status", tags=["Health"])
async def status():
    active = [
        p for p in store.projects.values()
        if p["status"] not in {ProjectStatus.COMPLETED.value, ProjectStatus.FAILED.value}
    ]
    return {
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat(),
        "active_projects": len(active),
        "total_projects": len(store.projects),
        "firebase_configured": firebase_meta.get("configured", False),
        "cosmos": {
            "enabled": COSMOS_STARTUP_STATUS.get("enabled", False),
            "required": COSMOS_STARTUP_STATUS.get("required", False),
            "initialized": COSMOS_STARTUP_STATUS.get("initialized", False),
            "containers": COSMOS_STARTUP_STATUS.get("containers", []),
            "template_seed": COSMOS_STARTUP_STATUS.get("template_seed"),
            "starter_template_seed": COSMOS_STARTUP_STATUS.get("starter_template_seed"),
            "error": COSMOS_STARTUP_STATUS.get("error"),
        },
    }


@app.post("/api/projects", response_model=ProjectResponse, tags=["Projects"])
async def create_project(request: CreateProjectRequest, background_tasks: BackgroundTasks):
    project = store.create(request.project_name, request.user_intent, request.description)
    project["azure_resources"] = request.azure_resources
    store.update(project["project_id"], status=ProjectStatus.QUEUED, progress=5)
    _append_project_log(
        project["project_id"],
        "project_created",
        project_name=project["project_name"],
        local_output_dir=str(_project_generated_dir(project["project_id"]).resolve()),
    )
    background_tasks.add_task(_simulate_generation, project["project_id"])
    project = store.get(project["project_id"]) or project
    return ProjectResponse(
        project_id=project["project_id"],
        project_name=project["project_name"],
        status=ProjectStatus(project["status"]),
        created_at=project["created_at"],
        updated_at=project["updated_at"],
        user_intent=project["user_intent"],
        progress=project["progress"],
        error=project.get("error"),
    )


@app.get("/api/projects/{project_id}", response_model=ProjectResponse, tags=["Projects"])
async def get_project(project_id: str):
    project = store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    generated_dir = _project_generated_dir(project_id)
    local_file_count = 0
    if generated_dir.exists():
        local_file_count = sum(1 for p in generated_dir.rglob("*") if p.is_file())
    return ProjectResponse(
        project_id=project["project_id"],
        project_name=project["project_name"],
        status=ProjectStatus(project["status"]),
        created_at=project["created_at"],
        updated_at=project["updated_at"],
        user_intent=project["user_intent"],
        progress=project["progress"],
        error=project.get("error"),
    )


@app.get("/api/projects/{project_id}/service-api-keys/status", tags=["Projects"])
async def get_project_service_api_key_status(project_id: str):
    project = store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    saved_keys = _load_service_api_keys(project_id)
    saved_services = sorted(saved_keys.keys())
    last_saved_at = project.get("service_api_keys_last_saved_at")

    return {
        "project_id": project_id,
        "saved_services": saved_services,
        "saved_count": len(saved_services),
        "last_saved_at": last_saved_at,
    }


@app.get("/api/projects/{project_id}/ledger", tags=["Projects"])
async def get_project_ledger_compat(project_id: str):
    """Compatibility route for frontend ledger reads."""
    workspace_dir = REPO_ROOT / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    ledger_file = workspace_dir / f"ledger_{project_id}.json"
    download_blob_to_local_path(str(ledger_file))

    project = store.get(project_id)
    project_status = project.get("status", "unknown") if project else "unknown"
    project_progress = project.get("progress", 0) if project else 0

    if not ledger_file.exists():
        return {
            "project_id": project_id,
            "file_path": str(ledger_file.resolve()),
            "exists": False,
            "project_status": project_status,
            "project_progress": project_progress,
            "message": "Ledger not generated yet.",
            "ledger_data": None,
        }

    try:
        ledger_data = json.loads(ledger_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to parse ledger: {exc}")

    return {
        "project_id": project_id,
        "file_path": str(ledger_file.resolve()),
        "exists": True,
        "project_status": project_status,
        "project_progress": project_progress,
        "file_size": ledger_file.stat().st_size,
        "modified_at": datetime.fromtimestamp(ledger_file.stat().st_mtime).isoformat(),
        "ledger_data": ledger_data,
    }


@app.get("/api/projects/{project_id}/storage", tags=["Projects"])
async def get_project_storage(project_id: str):
    project = store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    local_dir = _project_generated_dir(project_id)
    local_dir.mkdir(parents=True, exist_ok=True)

    files: List[Dict[str, Any]] = []
    for p in local_dir.rglob("*"):
        if not p.is_file():
            continue
        files.append(
            {
                "path": str(p.relative_to(local_dir)),
                "size": p.stat().st_size,
                "modified_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
            }
        )
    files.sort(key=lambda x: x["modified_at"], reverse=True)

    return {
        "project_id": project_id,
        "local_storage": {
            "path": str(local_dir.resolve()),
            "exists": local_dir.exists(),
            "file_count": len(files),
            "recent_files": files[:25],
        },
        "blob_storage": {
            "enabled": bool(BLOB_WORKSPACE),
            "container": _AZURE_STORAGE_CONTAINER,
            "prefix": f"{project_id}/",
            "source_of_truth_prefixes": [
                f"{project_id}/runtime/workspace/",
            ],
        },
        "project_log": str(_project_log_file(project_id).resolve()),
    }


@app.get("/api/projects/{project_id}/artifacts", tags=["Artifacts"])
async def list_artifacts(project_id: str):
    project = store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    _sync_project_from_blob(project_id)
    artifacts = []
    project_dir = _project_generated_dir(project_id)
    if project_dir.exists():
        for file_path in project_dir.rglob("*"):
            if not file_path.is_file():
                continue
            artifacts.append(
                {
                    "name": file_path.name,
                    "type": "code" if file_path.suffix in {".py", ".js", ".jsx", ".ts", ".tsx"} else "config",
                    "size": file_path.stat().st_size,
                    "created_at": datetime.fromtimestamp(file_path.stat().st_ctime).isoformat(),
                    "path": str(file_path.relative_to(project_dir)),
                }
            )

    return {
        "project_id": project_id,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


@app.get("/api/projects/{project_id}/artifacts/{artifact_name}", tags=["Artifacts"])
async def download_artifact(project_id: str, artifact_name: str):
    project = store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    _sync_project_from_blob(project_id)
    artifact_path = _project_generated_dir(project_id) / artifact_name
    if not artifact_path.exists() or not artifact_path.is_file():
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_name} not found")

    return FileResponse(path=artifact_path, filename=artifact_name, media_type="application/octet-stream")


@app.get("/api/projects/{project_id}/logs", tags=["Logs"])
async def get_project_logs(project_id: str):
    project = store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    logs: Dict[str, str] = {}
    if store.logs_root.exists():
        for log_file in store.logs_root.glob("*.log"):
            try:
                logs[log_file.name] = log_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass

    return {"project_id": project_id, "logs": logs}


@app.get("/api/projects/{project_id}/agent-events", tags=["Logs"])
async def get_project_agent_events(project_id: str):
    project = store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    log_file = _project_log_file(project_id)
    events: List[Dict[str, Any]] = []
    if log_file.exists():
        for line in log_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                events.append(json.loads(text))
            except Exception:
                pass

    ledger_files = []
    ws = REPO_ROOT / "workspace"
    if ws.exists():
        ledger_files = [str(p.name) for p in ws.glob("ledger_*.json")]

    return {
        "project_id": project_id,
        "event_count": len(events),
        "events": events[-200:],
        "agent_log_file": str(log_file.resolve()),
        "workspace_ledgers": sorted(ledger_files),
        "blob_sync_note": "Blob upload happens after generation completes successfully.",
    }


@app.post("/api/projects/{project_id}/deploy", tags=["Deployment"])
async def deploy_project(project_id: str, request: DeploymentRequest, background_tasks: BackgroundTasks):
    project = store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    if project["status"] != ProjectStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Project must be in COMPLETED state, current state: {project['status']}",
        )

    store.update(project_id, status=ProjectStatus.GENERATING_DEPLOYMENT, progress=50)
    background_tasks.add_task(_simulate_deployment, project_id, request)
    return {
        "status": "deployment_queued",
        "project_id": project_id,
        "message": "Deployment agent queued",
    }


@app.get("/api/projects/{project_id}/deployment-status", tags=["Deployment"])
async def get_deployment_status(project_id: str):
    project = store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    _sync_project_from_blob(project_id)
    deployment_dir = _project_generated_dir(project_id) / "deployment"
    artifacts = []
    if deployment_dir.exists():
        for file_path in deployment_dir.glob("*"):
            if file_path.is_file():
                artifacts.append(
                    {
                        "name": file_path.name,
                        "size": file_path.stat().st_size,
                        "created_at": datetime.fromtimestamp(file_path.stat().st_ctime).isoformat(),
                    }
                )

    deployment_result = None
    deployment_result_file = _project_generated_dir(project_id) / "deployment" / "azure" / "deployment_result.json"
    if deployment_result_file.exists():
        try:
            deployment_result = json.loads(deployment_result_file.read_text(encoding="utf-8"))
        except Exception:
            deployment_result = None

    return {
        "project_id": project_id,
        "deployment_status": project["status"],
        "artifacts": artifacts,
        "cost_estimate_available": (_project_generated_dir(project_id) / "cost_estimate.json").exists(),
        "deployment_result": deployment_result,
        "blob_sync_note": "Deployment artifacts are uploaded to blob immediately after deployment agent run.",
    }


@app.get("/api/projects/{project_id}/cost-estimate", tags=["Deployment"])
async def get_cost_estimate(project_id: str):
    project = store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    _sync_project_from_blob(project_id)
    estimate_file = _project_generated_dir(project_id) / "cost_estimate.json"
    if not estimate_file.exists():
        raise HTTPException(status_code=404, detail="Cost estimate not available yet")
    return json.loads(estimate_file.read_text(encoding="utf-8"))


@app.get("/api/projects", tags=["Projects"])
async def list_projects():
    return {
        "total_projects": len(store.projects),
        "projects": [
            {
                "project_id": p["project_id"],
                "project_name": p["project_name"],
                "status": p["status"],
                "created_at": p["created_at"],
                "progress": p["progress"],
            }
            for p in store.projects.values()
        ],
    }

@app.post("/api/projects/{project_id}/ingestion/context", tags=["Ingestion"])
async def generate_project_ingestion_context(
    project_id: str,
    request: IngestionContextRequest,
):
    project = store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    context = build_ingestion_context(
        repo_root=REPO_ROOT,
        project_id=project_id,
        reference_files=[item.model_dump() for item in request.reference_files],
        include_canvas=bool(request.include_canvas),
        canvas_data=project.get("canvas_data") if request.include_canvas else None,
    )

    project["ingestion_context"] = {
        "generated_at": context.get("generated_at"),
        "combined_summary": context.get("combined_summary"),
        "task_ledger_seeds": context.get("task_ledger_seeds") or [],
        "file_count": len(context.get("file_results") or []),
        "has_canvas": bool(context.get("canvas_result")),
        "persisted_files": context.get("persisted_files") or {},
    }
    project["updated_at"] = datetime.utcnow().isoformat()
    store._save()
    _append_project_log(
        project_id,
        "ingestion_context_generated",
        file_count=len(context.get("file_results") or []),
        has_canvas=bool(context.get("canvas_result")),
        persisted_files=context.get("persisted_files") or {},
    )

    # Ensure ingestion outputs are pushed to blob storage immediately.
    _sync_project_to_blob(project_id)

    return context


@app.get("/api/preview/{project_id}/{path:path}", tags=["Compatibility"])
async def preview(project_id: str, path: str = ""):
    _sync_project_from_blob(project_id)
    raw_path = path.strip("/") if path and path.strip() != "/" else ""
    requested_filename = raw_path or "index.html"

    bases = _frontend_preview_bases(project_id)
    if not bases:
        return HTMLResponse(
            content=(
                "<!doctype html><html><body><h1>⏳ Preview Not Available</h1>"
                "<p>The generated code for this project hasn't been created yet.</p></body></html>"
            ),
            status_code=200,
        )

    target: Optional[Path] = None
    for base in bases:
        candidate = base / requested_filename
        try:
            candidate.resolve().relative_to(base.resolve())
        except Exception:
            continue
        if candidate.exists() and candidate.is_file():
            target = candidate
            break

    if target is None and requested_filename in {"", "index.html"}:
        discovered = _discover_frontend_preview_target(project_id)
        if discovered:
            base, rel = discovered
            candidate = base / rel
            try:
                candidate.resolve().relative_to(base.resolve())
                if candidate.exists() and candidate.is_file():
                    target = candidate
            except Exception:
                target = None

    if target is None:
        if ".." in requested_filename.split("/"):
            raise HTTPException(status_code=403, detail="Access denied")
        return HTMLResponse(
            content=(
                "<!doctype html><html><body><h1>⏳ Preview Not Available</h1>"
                "<p>The generated code for this project hasn't been created yet.</p></body></html>"
            ),
            status_code=200,
        )

    suffix = target.suffix.lower()
    content_types = {
        ".html": "text/html",
        ".css": "text/css",
        ".js": "application/javascript",
        ".json": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
    }
    if suffix == ".html":
        try:
            raw = target.read_text(encoding="utf-8", errors="ignore")
            patched = _inject_preview_console_bridge(raw, project_id=project_id)
            return HTMLResponse(content=patched, status_code=200)
        except Exception:
            # Fall back to regular file response if injection fails.
            pass
    return FileResponse(target, media_type=content_types.get(suffix, "application/octet-stream"))


@app.get("/api/projects/{project_id}/preview-status", tags=["Compatibility"])
async def get_project_preview_status(project_id: str):
    project = store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    _sync_project_from_blob(project_id)
    entry = _discover_frontend_preview_entry(project_id)
    preview_ready = bool(entry)

    return {
        "project_id": project_id,
        "project_status": project.get("status"),
        "preview_ready": preview_ready,
        "entry": entry,
        "preview_url": f"/api/preview/{project_id}/{entry}" if preview_ready and entry else None,
        "message": "Frontend preview is ready" if preview_ready else "Frontend preview is not ready yet",
    }


@app.get("/context/{project_id}", tags=["Compatibility"])
async def get_context(project_id: str):
    return {
        "project_id": project_id,
        "task_ledger": {
            "app_type": "Agentic Nexus",
            "auth": "Firebase JWT",
            "database": "CosmosDB/JSON",
            "framework": "FastAPI",
        },
        "aeg": {
            "nodes": [
                {"id": "backend", "agent_type": "BackendEngineer", "state": "COMPLETED"},
                {"id": "frontend", "agent_type": "FrontendEngineer", "state": "COMPLETED"},
                {"id": "qa", "agent_type": "QAEngineer", "state": "PENDING"},
            ],
            "edges": [
                {"from": "backend", "to": "frontend"},
                {"from": "frontend", "to": "qa"},
            ],
        },
        "agents": [
            {"id": "backend", "tokens_used": 1200, "cost": 0.03, "state": "COMPLETED"},
            {"id": "frontend", "tokens_used": 900, "cost": 0.02, "state": "COMPLETED"},
            {"id": "qa", "tokens_used": 0, "cost": 0.0, "state": "PENDING"},
        ],
    }


@app.get("/api/agents", tags=["Compatibility"])
async def get_agents(tier: Optional[int] = Query(default=None), role: Optional[str] = Query(default=None), tag: Optional[str] = Query(default=None)):
    agents = await _get_agent_catalog()
    if tier is not None:
        agents = [a for a in agents if int(a.get("tier", 0)) == int(tier)]
    if role:
        role_l = role.lower()
        agents = [a for a in agents if role_l in str(a.get("role", "")).lower()]
    if tag:
        tag_l = tag.lower()
        agents = [a for a in agents if any(tag_l == str(t).lower() for t in a.get("tags", []))]
    return {"agents": agents, "count": len(agents), "source": _agent_cache_source}

@app.post("/api/agents", tags=["Compatibility"])
async def create_custom_agent(payload: CreateAgentRequest):
    """Create a custom agent and persist it to CosmosDB."""
    import re as _re

    # Slugify role → id (lowercase, underscores, no special chars)
    agent_id = _re.sub(r"[^a-z0-9]+", "_", payload.role.lower().strip()).strip("_")
    if not agent_id:
        raise HTTPException(status_code=422, detail="role must contain at least one alphanumeric character")
    if len(payload.description.strip()) < 10:
        raise HTTPException(status_code=422, detail="description must be at least 10 characters")
    if payload.tier not in (1, 2):
        raise HTTPException(status_code=422, detail="tier must be 1 or 2")

    model_label = payload.model_label or ("GPT-4o" if payload.tier == 1 else "GPT-4o-mini")
    doc = {
        "id": agent_id,
        "agent_id": agent_id,
        "role": agent_id,
        "display_name": payload.role.strip(),
        "tier": payload.tier,
        "model_label": model_label,
        "description": payload.description.strip(),
        "reputation_score": 0.0,
        "tags": [t.strip().lower() for t in payload.tags if t.strip()],
        "is_custom": True,
        "system_prompt": payload.system_prompt.strip() if payload.system_prompt else "",
    }

    try:
        container = _get_agent_library_cosmos_container()
        await asyncio.get_event_loop().run_in_executor(None, lambda: container.upsert_item(doc))
        logger.info("Custom agent '%s' upserted to CosmosDB.", agent_id)
    except Exception as exc:
        logger.warning("CosmosDB upsert failed for custom agent '%s': %s", agent_id, exc)
        raise HTTPException(status_code=503, detail=f"Failed to persist agent: {exc}")

    # Bust in-memory cache so next GET returns fresh data (includes new agent)
    global _agent_catalog_cache, _agent_cache_ts
    _agent_catalog_cache = None
    _agent_cache_ts = 0.0

    return {"ok": True, "agent": doc}


@app.get("/api/agents/{agent_id}", tags=["Compatibility"])
async def get_agent(agent_id: str):
    agents = await _get_agent_catalog()
    for agent in agents:
        if agent.get("id") == agent_id:
            return agent
    raise HTTPException(status_code=404, detail="Agent not found")


@app.post("/api/agents/select", tags=["Compatibility"])
async def select_agent(payload: AgentSelectionRequest):
    project_id = payload.project_id or "default"
    project_map = SELECTED_AGENTS_BY_PROJECT.setdefault(project_id, {})
    agents = await _get_agent_catalog()
    selected = next((a for a in agents if a["id"] == payload.agent_id), None)
    if not selected:
        raise HTTPException(status_code=404, detail="Agent not found")
    project_map[payload.agent_id] = {
        "agent_id": payload.agent_id,
        "id": payload.agent_id,
        "aeg_node_id": payload.aeg_node_id,
        "selected_at": datetime.utcnow().isoformat(),
    }
    return {"ok": True, "project_id": project_id, "selected_agent": project_map[payload.agent_id]}


@app.delete("/api/agents/select/{project_id}/{agent_id}", tags=["Compatibility"])
async def deselect_agent(project_id: str, agent_id: str):
    project_map = SELECTED_AGENTS_BY_PROJECT.setdefault(project_id, {})
    project_map.pop(agent_id, None)
    return {"ok": True, "project_id": project_id, "agent_id": agent_id}


@app.get("/api/agents/selected/{project_id}", tags=["Compatibility"])
async def get_selected_agents(project_id: str):
    project_map = SELECTED_AGENTS_BY_PROJECT.get(project_id, {})
    return {"project_id": project_id, "selected_agents": list(project_map.values()), "count": len(project_map)}


@app.get("/api/cost/ticker", tags=["Compatibility"])
async def cost_ticker(project_id: str):
    return {
        "project_id": project_id,
        "estimated_usd": 0.0,
        "budget_usd": 100.0,
        "updated_at": datetime.utcnow().isoformat(),
    }


@app.post("/api/cost/budget", tags=["Compatibility"])
async def set_cost_budget(project_id: str, request: BudgetRequest):
    return {
        "project_id": project_id,
        "budget_usd": float(request.budget_usd),
        "updated_at": datetime.utcnow().isoformat(),
    }


@app.get("/api/cost/summary", tags=["Compatibility"])
async def cost_summary(project_id: str):
    return {
        "project_id": project_id,
        "total_usd": 0.0,
        "by_agent": [],
        "updated_at": datetime.utcnow().isoformat(),
    }


@app.get("/api/cost/usage", tags=["Compatibility"])
async def cost_usage(project_id: str, limit: int = 20):
    return {
        "project_id": project_id,
        "limit": int(limit),
        "entries": [],
    }


@app.get("/api/cost/escalations", tags=["Compatibility"])
async def cost_escalations(project_id: str):
    return {
        "project_id": project_id,
        "items": [],
        "count": 0,
    }


@app.post("/clarify", tags=["Compatibility"])
async def clarify_intent(request: ClarifyRequest, background_tasks: BackgroundTasks):
    """Compatibility route aligned with platform-backend branch behavior."""
    try:
        project = store.get(request.project_id)
        active_project_id = request.project_id

        if not project:
            created = store.create_with_id(request.project_id, f"Project {request.project_id[:8]}", request.user_input, None)
            active_project_id = created["project_id"]
            project = created
        else:
            project["user_intent"] = request.user_input
            project["updated_at"] = datetime.utcnow().isoformat()
            store._save()

        answers = request.answers or {}
        if answers:
            existing_questions = project.get("clarification_questions", []) if isinstance(project, dict) else []
            qa_lines = []
            if isinstance(existing_questions, list) and existing_questions:
                for idx, q in enumerate(existing_questions, start=1):
                    a = answers.get(str(idx), "") or answers.get(q, "")
                    qa_lines.append(f"Q{idx}: {q}\nA{idx}: {a}")
            else:
                for k, v in answers.items():
                    qa_lines.append(f"{k}: {v}")

            project["clarification_answers"] = answers
            project["clarification_state"] = "answered"
            project["user_intent"] = f"{request.user_input}\n\nClarifications:\n" + "\n".join(qa_lines)
            project["updated_at"] = datetime.utcnow().isoformat()
            project["error"] = None
            store._save()

            # Always (re)start generation when clarification answers are submitted.
            # This avoids stale states (e.g., stuck generating_code) after server restarts.
            store.update(active_project_id, status=ProjectStatus.QUEUED, progress=5)
            background_tasks.add_task(_simulate_generation, active_project_id)
            _append_project_log(
                active_project_id,
                "clarify_auto_execute_started",
                local_output_dir=str(_project_generated_dir(active_project_id).resolve()),
                blob_enabled=bool(BLOB_WORKSPACE),
            )

            _append_project_log(active_project_id, "clarify_answers_received", answer_count=len(answers))
            return {
                "director_reply": "Great, thanks. I have enough detail. I have started execution now.",
                "project_id": active_project_id,
                "status": "execution_started",
                "questions": [],
            }

        questions = _generate_director_questions(request.user_input)
        project["clarification_questions"] = questions
        project["clarification_state"] = "awaiting_answers"
        project["updated_at"] = datetime.utcnow().isoformat()
        store._save()

        _append_project_log(
            active_project_id,
            "clarify_received",
            user_input=request.user_input,
        )

        return {
            "director_reply": f"I understand you want to: {request.user_input}. I'll create a task breakdown and coordinate the agents.",
            "project_id": active_project_id,
            "status": "clarified",
            "questions": questions,
        }
    except Exception:
        return {
            "director_reply": "I'm processing your request. The orchestration will begin shortly.",
            "project_id": request.project_id,
            "status": "processing",
        }

@app.post("/question", tags=["QuestioningAgent"])
async def question_endpoint(request: QuestionRequest):
    """Interactive questioning agent endpoint.
    
    Conducts natural conversation to gather project specifications.
    Updates project specification file iteratively.
    """
    prev_active_project_id = os.getenv("NEXUS_ACTIVE_PROJECT_ID")
    prev_workspace_root = os.getenv("NEXUS_WORKSPACE_ROOT")
    try:
        from questioning_agent import QuestioningAgent
        os.environ["NEXUS_ACTIVE_PROJECT_ID"] = str(request.project_id)
        os.environ["NEXUS_WORKSPACE_ROOT"] = str((REPO_ROOT / "workspace").resolve())
        
        project = store.get(request.project_id)
        requested_question_count = int(request.question_count or 0)
        history_count = len(request.conversation_history or [])

        current_question_count = requested_question_count
        
        if not project:
            created = store.create_with_id(
                request.project_id, 
                f"Project {request.project_id[:8]}", 
                request.user_message, 
                None
            )
            project = created
            current_question_count = int(project.get("question_count", 0) or 0)
        else:
            stored_question_count = int(project.get("question_count", 0) or 0)

            # If the client starts a fresh questioning session on an existing
            # project, allow question flow to restart from zero.
            if requested_question_count == 0 and history_count <= 1 and stored_question_count >= 10:
                stored_question_count = 0
                project["question_count"] = 0
                project["updated_at"] = datetime.utcnow().isoformat()
                store._save()

            current_question_count = max(stored_question_count, requested_question_count)
        
        agent = QuestioningAgent()
        conversation_history = request.conversation_history or []
        
        response = agent.get_response(
            request.project_id,
            request.user_message,
            conversation_history,
            question_count=current_question_count
        )
        
        # Always persist the latest question count, including terminal 10/10 state.
        response_question_count = response.get("question_count", current_question_count)
        try:
            persisted_question_count = int(response_question_count)
        except (TypeError, ValueError):
            persisted_question_count = current_question_count

        project["question_count"] = max(0, min(10, persisted_question_count))
        project["updated_at"] = datetime.utcnow().isoformat()
        store._save()
        
        _append_project_log(
            request.project_id,
            "questioning_agent_response",
            user_message=request.user_message[:100],
            question_count=response["question_count"]
        )
        
        return {
            "response": response["response"],
            "agent_thinking": response["agent_thinking"],
            "next_topics": response["next_topics"],
            "project_id": request.project_id,
            "spec_updated": response["spec_updated"],
            "spec_preview": response["spec_preview"],
            "full_spec_path": response["full_spec_path"],
            "question_count": response["question_count"],
            "questions_remaining": response["questions_remaining"],
            "must_execute": response["must_execute"],
            "web_context_used": bool(response.get("web_context_used", False)),
        }
    except Exception as exc:
        logger.error("Question endpoint error: %s", exc)
        return {
            "response": "I encountered an issue processing your input. Please try again.",
            "project_id": request.project_id,
            "error": str(exc)
        }
    finally:
        if prev_active_project_id is None:
            os.environ.pop("NEXUS_ACTIVE_PROJECT_ID", None)
        else:
            os.environ["NEXUS_ACTIVE_PROJECT_ID"] = prev_active_project_id

        if prev_workspace_root is None:
            os.environ.pop("NEXUS_WORKSPACE_ROOT", None)
        else:
            os.environ["NEXUS_WORKSPACE_ROOT"] = prev_workspace_root


@app.post("/question-readiness", tags=["QuestioningAgent"])
async def question_readiness_endpoint(request: QuestionReadinessRequest):
    """Check if project specifications are complete and ready for execution."""
    prev_active_project_id = os.getenv("NEXUS_ACTIVE_PROJECT_ID")
    prev_workspace_root = os.getenv("NEXUS_WORKSPACE_ROOT")
    try:
        from questioning_agent import QuestioningAgent
        os.environ["NEXUS_ACTIVE_PROJECT_ID"] = str(request.project_id)
        os.environ["NEXUS_WORKSPACE_ROOT"] = str((REPO_ROOT / "workspace").resolve())
        
        project = store.get(request.project_id)
        if not project:
            return {
                "is_ready": False,
                "completeness": 0,
                "message": "No project found. Start a conversation first.",
                "missing_areas": ["Project specifications"],
                "project_id": request.project_id
            }
        
        agent = QuestioningAgent()
        readiness = agent.suggest_execution(request.project_id, [])
        is_ready = bool(readiness.get("is_ready", False))
        completeness = int(readiness.get("completeness", 0) or 0)
        message = readiness.get("message", "Readiness check completed.")
        missing_areas = readiness.get("missing_areas", []) or []
        full_spec_path = readiness.get("full_spec_path")
        required_services: List[str] = []

        try:
            workspace_dir = REPO_ROOT / "workspace"
            ledger_file = workspace_dir / f"ledger_{request.project_id}.json"
            download_blob_to_local_path(str(ledger_file))
            if ledger_file.exists():
                ledger_data = json.loads(ledger_file.read_text(encoding="utf-8"))
                required_services = _normalize_required_api_key_services(ledger_data)
                if not required_services:
                    required_services = _infer_required_api_key_services(ledger_data)
            elif full_spec_path:
                download_blob_to_local_path(str(full_spec_path))
                if os.path.exists(full_spec_path):
                    spec_text = Path(full_spec_path).read_text(encoding="utf-8")
                    required_services = _infer_required_api_key_services_from_text(spec_text)
        except Exception:
            required_services = []
        
        return {
            "is_ready": is_ready,
            "completeness": completeness,
            "message": message,
            "missing_areas": missing_areas,
            "full_spec_path": full_spec_path,
            "required_api_key_services": required_services,
            "project_id": request.project_id
        }
    except Exception as exc:
        logger.error("Question readiness error: %s", exc)
        return {
            "is_ready": False,
            "completeness": 0,
            "message": "Error assessing specification readiness.",
            "project_id": request.project_id,
            "error": str(exc)
        }
    finally:
        if prev_active_project_id is None:
            os.environ.pop("NEXUS_ACTIVE_PROJECT_ID", None)
        else:
            os.environ["NEXUS_ACTIVE_PROJECT_ID"] = prev_active_project_id

        if prev_workspace_root is None:
            os.environ.pop("NEXUS_WORKSPACE_ROOT", None)
        else:
            os.environ["NEXUS_WORKSPACE_ROOT"] = prev_workspace_root


@app.post("/execute-from-specs", tags=["QuestioningAgent"])
async def execute_from_specs(request: ExecuteRequest, background_tasks: BackgroundTasks):
    """Execute project generation using specifications gathered by questioning agent."""
    prev_active_project_id = os.getenv("NEXUS_ACTIVE_PROJECT_ID")
    prev_workspace_root = os.getenv("NEXUS_WORKSPACE_ROOT")
    try:
        from questioning_agent import QuestioningAgent
        os.environ["NEXUS_ACTIVE_PROJECT_ID"] = str(request.project_id)
        os.environ["NEXUS_WORKSPACE_ROOT"] = str((REPO_ROOT / "workspace").resolve())
        
        project = store.get(request.project_id)
        active_project_id = request.project_id
        
        if not project:
            return {
                "message": "Project not found",
                "project_id": request.project_id,
                "status": "failed",
                "error": "No project with this ID"
            }
        
        # Load the specification file
        agent = QuestioningAgent()
        spec_path = agent._get_spec_file_path(request.project_id)
        download_blob_to_local_path(spec_path)
        
        if not os.path.exists(spec_path):
            return {
                "message": "No specifications found. Please complete the questioning process first.",
                "project_id": request.project_id,
                "status": "failed"
            }

        # Ensure task ledger exists (Director-only pass) before orchestration.
        workspace_dir = REPO_ROOT / "workspace"
        ledger_file = workspace_dir / f"ledger_{active_project_id}.json"
        ledger_data: Dict[str, Any] = {}
        required_services: List[str] = []
        download_blob_to_local_path(str(ledger_file))
        if ledger_file.exists():
            try:
                ledger_data = json.loads(ledger_file.read_text(encoding="utf-8"))
                required_services = _normalize_required_api_key_services(ledger_data)
                if not required_services:
                    required_services = _infer_required_api_key_services(ledger_data)
            except Exception:
                ledger_data = {}
                required_services = []
        
        with open(spec_path, 'r', encoding='utf-8') as f:
            project_specs = f.read()

        if not _ledger_has_agent_plan(ledger_data):
            director_input = (
                f"PROJECT SPECIFICATIONS:\n\n{project_specs}\n\n"
                f"ADDITIONAL CONTEXT:\n{project.get('user_intent', '')}"
            )
            ledger_data = await _generate_task_ledger_only(
                project_id=active_project_id,
                user_input=director_input,
                owner_id=str(project.get("owner_id") or active_project_id),
            )
            required_services = _normalize_required_api_key_services(ledger_data)
            if not required_services:
                required_services = _infer_required_api_key_services(ledger_data)

        if not required_services:
            required_services = _infer_required_api_key_services_from_text(project_specs)

        ledger_data["required_api_key_services"] = required_services

        provided_keys = request.service_api_keys or {}
        saved_keys = _load_service_api_keys(active_project_id)
        submitted_non_empty_keys = {
            str(service or "").strip(): str(key or "").strip()
            for service, key in provided_keys.items()
            if str(service or "").strip() and str(key or "").strip()
        }
        merged_keys = {**saved_keys, **submitted_non_empty_keys}

        if submitted_non_empty_keys:
            merged_keys = _save_service_api_keys(active_project_id, merged_keys)
            _append_project_log(
                active_project_id,
                "service_api_keys_saved",
                saved_services=sorted(merged_keys.keys()),
            )

        existing_ledger_keys = ledger_data.get("service_api_keys")
        if not isinstance(existing_ledger_keys, dict):
            existing_ledger_keys = {}

        ledger_service_keys = dict(existing_ledger_keys)
        for service in required_services:
            ledger_service_keys.setdefault(service, "")
        for service_name, api_key in merged_keys.items():
            ledger_service_keys[service_name] = api_key
        ledger_data["service_api_keys"] = ledger_service_keys
        ledger_payload = json.dumps(ledger_data, indent=2, ensure_ascii=False)
        ok, detail = write_text_azure_first(str(ledger_file), ledger_payload)
        if not ok:
            raise RuntimeError(f"Failed to persist task ledger with API keys: {detail}")

        missing_services = [
            service for service in required_services
            if not str(merged_keys.get(service, "")).strip()
        ]

        if missing_services:
            store.update(active_project_id, status=ProjectStatus.PAUSED, progress=5)
            _append_project_log(
                active_project_id,
                "execution_paused_missing_api_keys",
                missing_services=missing_services,
            )
            return {
                "message": "Missing API keys for required services. Save the keys and retry execution.",
                "project_id": request.project_id,
                "status": "awaiting_api_keys",
                "orchestration_started": False,
                "missing_services": missing_services,
                "required_api_key_services": required_services,
                "ledger_generated": True,
            }

        env_path = _write_project_env_file(active_project_id, merged_keys)
        if env_path:
            _append_project_log(
                active_project_id,
                "project_env_generated",
                env_path=env_path,
                service_count=len(merged_keys),
            )
        
        # Update project with specifications as the intent
        project["user_intent"] = f"Based on these specifications:\n\n{project_specs}"
        project["provided_api_key_services"] = sorted(merged_keys.keys())
        project["service_api_keys_last_saved_at"] = datetime.utcnow().isoformat()
        project["updated_at"] = datetime.utcnow().isoformat()
        store._save()
        
        # Start execution
        store.update(active_project_id, status=ProjectStatus.QUEUED, progress=5)
        background_tasks.add_task(_simulate_generation, active_project_id)
        
        _append_project_log(
            active_project_id,
            "execute_from_specs_started",
            local_output_dir=str(_project_generated_dir(active_project_id).resolve()),
            blob_enabled=bool(BLOB_WORKSPACE),
            spec_file=spec_path
        )
        
        return {
            "message": "Execution started using gathered specifications",
            "project_id": active_project_id,
            "status": "running",
            "spec_file": spec_path,
            "ledger_generated": True,
            "orchestration_started": True,
        }
    except Exception as exc:
        logger.error("Execute from specs error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to start execution from specifications")
    finally:
        if prev_active_project_id is None:
            os.environ.pop("NEXUS_ACTIVE_PROJECT_ID", None)
        else:
            os.environ["NEXUS_ACTIVE_PROJECT_ID"] = prev_active_project_id

        if prev_workspace_root is None:
            os.environ.pop("NEXUS_WORKSPACE_ROOT", None)
        else:
            os.environ["NEXUS_WORKSPACE_ROOT"] = prev_workspace_root


@app.get("/api/workspace/files", tags=["Workspace"])
async def get_workspace_files():
    """List all files in the workspace directory (specs, ledgers, etc.)."""
    try:
        workspace_dir = REPO_ROOT / "workspace"
        if not workspace_dir.exists():
            return {"files": [], "workspace_path": str(workspace_dir.resolve())}
        
        files = []
        for file_path in sorted(workspace_dir.glob("*")):
            if file_path.is_file():
                files.append({
                    "name": file_path.name,
                    "type": "spec" if "project_specs" in file_path.name else "ledger" if "ledger" in file_path.name else "other",
                    "size": file_path.stat().st_size,
                    "modified_at": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                    "path": str(file_path.relative_to(REPO_ROOT))
                })
        
        return {
            "workspace_path": str(workspace_dir.resolve()),
            "file_count": len(files),
            "files": files
        }
    except Exception as exc:
        logger.error("Workspace files error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list workspace files")


@app.get("/api/workspace/specs/{project_id}", tags=["Workspace"])
async def get_project_specs_file(project_id: str):
    """Retrieve the project specifications markdown file content."""
    try:
        workspace_dir = REPO_ROOT / "workspace"
        spec_file = workspace_dir / f"project_specs_{project_id}.md"
        
        if not spec_file.exists():
            raise HTTPException(status_code=404, detail=f"Specifications file not found for project {project_id}")
        
        content = spec_file.read_text(encoding="utf-8")
        return {
            "project_id": project_id,
            "file_path": str(spec_file.resolve()),
            "file_size": spec_file.stat().st_size,
            "modified_at": datetime.fromtimestamp(spec_file.stat().st_mtime).isoformat(),
            "content": content
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Get specs file error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve specifications file")


@app.get("/api/workspace/ledger/{project_id}", tags=["Workspace"])
async def get_project_ledger(project_id: str):
    """Retrieve the task ledger JSON file for a project."""
    try:
        workspace_dir = REPO_ROOT / "workspace"
        ledger_file = workspace_dir / f"ledger_{project_id}.json"
        
        # Also get project status and logs
        project = store.get(project_id)
        project_status = "unknown"
        project_progress = 0
        if project:
            project_status = project.get("status", "unknown")
            project_progress = project.get("progress", 0)
        
        if not ledger_file.exists():
            return {
                "project_id": project_id,
                "file_path": str(ledger_file.resolve()),
                "exists": False,
                "project_status": project_status,
                "project_progress": project_progress,
                "message": f"Ledger file not found. Project status: {project_status} (progress: {project_progress}%). The director agent may still be running. Check logs for details.",
                "ledger_data": None
            }
        
        content = ledger_file.read_text(encoding="utf-8")
        ledger_data = json.loads(content)
        
        return {
            "project_id": project_id,
            "file_path": str(ledger_file.resolve()),
            "exists": True,
            "project_status": project_status,
            "project_progress": project_progress,
            "file_size": ledger_file.stat().st_size,
            "modified_at": datetime.fromtimestamp(ledger_file.stat().st_mtime).isoformat(),
            "ledger_data": ledger_data
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Get ledger error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve ledger file")


@app.get("/aeg", tags=["Compatibility"])
async def get_aeg(project_id: str = "default"):
    try:
        project = store.get(project_id)

        def _looks_like_aeg_payload(payload: Any) -> bool:
            if not isinstance(payload, dict):
                return False
            has_legacy = isinstance(payload.get("nodes"), list) and isinstance(payload.get("edges"), list)
            has_specs = isinstance(payload.get("agent_specifications"), dict)
            return has_legacy or has_specs

        def _with_project_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
            enriched = dict(payload)
            enriched.setdefault("project_id", project_id)
            if project and project.get("project_name"):
                enriched.setdefault("project_name", project.get("project_name"))
            return enriched

        ledger_file = REPO_ROOT / "workspace" / f"ledger_{project_id}.json"
        if ledger_file.exists() and ledger_file.is_file():
            try:
                ledger_payload = json.loads(ledger_file.read_text(encoding="utf-8"))
                if _looks_like_aeg_payload(ledger_payload):
                    if project:
                        project["ledger_data"] = ledger_payload
                        project["updated_at"] = datetime.utcnow().isoformat()
                        store._save()
                    return _with_project_meta(ledger_payload)
            except Exception as exc:
                logger.warning("Failed loading ledger file for AEG (%s): %s", project_id, exc)

        if project and _looks_like_aeg_payload(project.get("ledger_data")):
            return _with_project_meta(project["ledger_data"])

        if project and isinstance(project.get("ledger_data"), dict):
            nested_ledger = project["ledger_data"].get("ledger_data") or project["ledger_data"].get("result")
            if _looks_like_aeg_payload(nested_ledger):
                return _with_project_meta(nested_ledger)

        return {
            "project_id": project_id,
            "project_name": (project or {}).get("project_name", "Demo Project"),
            "status": "DRAFT",
            "task_ledger": {
                "layers": [
                    {
                        "name": "Layer 1 · Foundation",
                        "agents": ["backend_engineer", "database_architect"],
                        "coordination_expectations": [
                            "Define API contracts and data schema.",
                            "Align on auth model and migration plan.",
                        ],
                    },
                    {
                        "name": "Layer 2 · Experience",
                        "agents": ["frontend_engineer"],
                        "coordination_expectations": [
                            "Implement UI against finalized API contracts.",
                            "Surface integration assumptions for QA handoff.",
                        ],
                    },
                    {
                        "name": "Layer 3 · Validation",
                        "agents": ["qa_engineer"],
                        "coordination_expectations": [
                            "Run end-to-end checks and report blockers.",
                            "Publish verification summary and release readiness.",
                        ],
                    },
                ],
                "layer_blackboards": {
                    "layer-1": [
                        "Backend and database are running in parallel with shared API/schema checkpoints.",
                        "Auth and persistence decisions must be finalized before Layer 2 starts.",
                    ],
                    "layer-2": [
                        "Frontend starts once Layer 1 contracts are stable.",
                        "UI integration notes and assumptions should be posted for QA.",
                    ],
                    "layer-3": [
                        "QA verifies cross-layer integration and reports final readiness.",
                        "Any defects should be fed back to the owning layer with repro steps.",
                    ],
                },
            },
            "agent_specifications": {
                "required_agents": [
                    "backend_engineer",
                    "frontend_engineer",
                    "database_architect",
                    "qa_engineer",
                ],
                "layers": [
                    ["backend_engineer", "database_architect"],
                    ["frontend_engineer"],
                    ["qa_engineer"],
                ],
                "agent_dependencies": {
                    "backend_engineer": [],
                    "frontend_engineer": ["backend_engineer"],
                    "database_architect": [],
                    "qa_engineer": ["backend_engineer", "frontend_engineer"],
                },
                "parallel_execution_groups": [
                    ["backend_engineer", "database_architect"],
                    ["frontend_engineer"],
                    ["qa_engineer"],
                ],
            },
        }
    except Exception as exc:
        logger.error("AEG error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch AEG")


@app.post("/execute", tags=["Compatibility"])
async def execute_project_compat(request: ExecuteRequest, background_tasks: BackgroundTasks):
    try:
        project = store.get(request.project_id)
        active_project_id = request.project_id
        requested_intent = (request.user_intent or "").strip()
        fallback_intent = os.getenv("DEFAULT_USER_INTENT", "Generate a simple bakery website").strip()
        effective_intent = requested_intent or fallback_intent

        if not project:
            created = store.create_with_id(request.project_id, f"Project {request.project_id[:8]}", effective_intent, None)
            active_project_id = created["project_id"]
            project = created
        elif requested_intent:
            project["user_intent"] = requested_intent
            project["updated_at"] = datetime.utcnow().isoformat()
            store._save()

        if project.get("clarification_state") == "awaiting_answers":
            return {
                "message": "Clarification answers required before execution",
                "project_id": active_project_id,
                "status": "clarification_required",
                "questions": project.get("clarification_questions", []),
            }

        if project["status"] in {ProjectStatus.CREATED.value, ProjectStatus.FAILED.value}:
            store.update(active_project_id, status=ProjectStatus.QUEUED, progress=5)
            background_tasks.add_task(_simulate_generation, active_project_id)
            _append_project_log(
                active_project_id,
                "execute_started",
                local_output_dir=str(_project_generated_dir(active_project_id).resolve()),
                blob_enabled=bool(BLOB_WORKSPACE),
            )

        return {
            "message": "Execution started",
            "project_id": active_project_id,
            "status": "running",
        }
    except Exception as exc:
        logger.error("Execute error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to start execution")


@app.post("/tutor/ask", tags=["Compatibility"])
async def tutor_ask(request: TutorRequest):
    q = (request.question or "").lower()
    response_text = "I'm the Nexus learning assistant. "
    if "explain" in q or "what is" in q:
        response_text += "This platform uses specialized agents to build full-stack applications collaboratively."
    elif "aeg" in q or "graph" in q:
        response_text += "The AEG shows dependencies between agents and execution order."
    elif "cost" in q:
        response_text += "Cost tracking reports token usage and estimated spend."
    else:
        response_text += "Ask me about agent execution, AEG, cost tracking, or orchestration flow."

    return {
        "response": response_text,
        "level": "overview",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/tunnel-status", tags=["Compatibility"])
async def tunnel_status():
    return {
        "status": "local",
        "tunnel_url": "http://localhost:5173",
        "port": 5173,
        "message": "Running on localhost (no tunnel configured)",
    }


@app.get("/", tags=["Compatibility"])
async def root():
    return {
        "message": "Agentic Nexus Backend API",
        "documentation": "/api/docs",
        "health": "/api/health",
    }


# ------------------------------
# Error handlers
# ------------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(_request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "timestamp": datetime.utcnow().isoformat()},
    )


@app.exception_handler(Exception)
async def general_exception_handler(_request, _exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "timestamp": datetime.utcnow().isoformat()},
    )


@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Nexus platform-compatible backend starting")
    logger.info(
        "Azure Blob config | conn_configured=%s container=%s blob_workspace_enabled=%s enable_local_file_generation=%s legacy_project_sync=%s autosync_enabled=%s autosync_interval_seconds=%s",
        bool(_AZURE_STORAGE_CONN_STR),
        _AZURE_STORAGE_CONTAINER,
        bool(BLOB_WORKSPACE),
        _ENABLE_LOCAL_FILE_GENERATION,
        _ENABLE_LEGACY_BLOB_PROJECT_SYNC,
        _BLOB_AUTOSYNC_ENABLED,
        _BLOB_AUTOSYNC_INTERVAL_SECONDS,
    )
    if _ENABLE_LOCAL_FILE_GENERATION:
        logger.warning(
            "ENABLE_LOCAL_FILE_GENERATION=true. Direct upload helpers (_upload_*_to_azure) are skipped by design. "
            "Blob sync via BLOB_WORKSPACE is still used where wired."
        )

    cosmos_connection = (os.getenv("COSMOS_CONNECTION_STR") or "").strip()
    persist_code_to_db = str(os.getenv("PERSIST_CODE_TO_DB", "false")).strip().lower() in {"1", "true", "yes", "on"}
    require_cosmos = str(os.getenv("REQUIRE_COSMOS_ON_STARTUP", "true")).strip().lower() in {"1", "true", "yes", "on"}

    COSMOS_STARTUP_STATUS["required"] = require_cosmos and (persist_code_to_db or bool(cosmos_connection))
    COSMOS_STARTUP_STATUS["enabled"] = bool(cosmos_connection)

    if not cosmos_connection:
        msg = "COSMOS_CONNECTION_STR not configured"
        COSMOS_STARTUP_STATUS["error"] = msg
        if COSMOS_STARTUP_STATUS["required"]:
            logger.error("❌ %s (required by startup policy)", msg)
            raise RuntimeError(msg)
        logger.warning("⚠️ %s; continuing startup", msg)
        return

    ok = await asyncio.to_thread(init_cosmos_db)
    if not ok:
        COSMOS_STARTUP_STATUS["initialized"] = False
        COSMOS_STARTUP_STATUS["error"] = "Failed to initialize Cosmos DB containers"
        logger.error("❌ Cosmos DB initialization failed")
        if COSMOS_STARTUP_STATUS["required"]:
            raise RuntimeError(COSMOS_STARTUP_STATUS["error"])
        return

    health = get_cosmos_client().health_check()
    COSMOS_STARTUP_STATUS["initialized"] = True
    COSMOS_STARTUP_STATUS["containers"] = health.get("containers", [])
    COSMOS_STARTUP_STATUS["error"] = health.get("error")

    try:
        seed_result = await asyncio.to_thread(seed_default_templates)
        COSMOS_STARTUP_STATUS["template_seed"] = seed_result
        if seed_result.get("ok"):
            logger.info("✅ Cosmos TemplateLibrary seeded: %s", seed_result.get("upserted", []))
        else:
            logger.warning("⚠️ Cosmos template seeding incomplete: %s", seed_result)
    except Exception as exc:
        COSMOS_STARTUP_STATUS["template_seed"] = {"ok": False, "error": str(exc)}
        logger.warning("⚠️ Cosmos template seeding failed: %s", exc)

    try:
        starter_seed_result = await asyncio.to_thread(seed_starter_templates)
        COSMOS_STARTUP_STATUS["starter_template_seed"] = starter_seed_result
        if starter_seed_result.get("ok"):
            logger.info("✅ Cosmos starter_templates seeded: %s", starter_seed_result.get("upserted", []))
        else:
            logger.warning("⚠️ Cosmos starter template seeding incomplete: %s", starter_seed_result)
    except Exception as exc:
        COSMOS_STARTUP_STATUS["starter_template_seed"] = {"ok": False, "error": str(exc)}
        logger.warning("⚠️ Cosmos starter template seeding failed: %s", exc)

    logger.info("✅ Cosmos DB initialized with containers: %s", COSMOS_STARTUP_STATUS["containers"])


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Nexus platform-compatible backend shutting down")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    reload_enabled = str(os.getenv("BACKEND_RELOAD", "false")).lower() in {"1", "true", "yes"}
    uvicorn.run("backend_platform:app", host="0.0.0.0", port=port, reload=reload_enabled)

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
import shutil
import sys
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from blob_workspace import build_blob_workspace_from_env


load_dotenv()
AZURE_MODEL_DEPLOYMENT = os.getenv("AZURE_MODEL_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT") or "gpt-4o"


# ------------------------------
# App + logging
# ------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("nexus-platform-backend")
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

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


class ClarifyRequest(BaseModel):
    project_id: str
    user_input: str
    answers: Optional[Dict[str, str]] = None


class ExecuteRequest(BaseModel):
    project_id: str
    user_intent: Optional[str] = None


class TutorRequest(BaseModel):
    project_id: str
    question: str
    context: Optional[Dict[str, Any]] = {}


class AgentSelectionRequest(BaseModel):
    aeg_node_id: str
    agent_id: str
    project_id: Optional[str] = None


class BudgetRequest(BaseModel):
    budget_usd: float


class ClarifyAnswersRequest(BaseModel):
    project_id: str
    answers: Dict[str, str]


# ------------------------------
# Project storage
# ------------------------------

class ProjectStore:
    def __init__(self, storage_file: str = "./projects_db.json"):
        self.storage_file = Path(storage_file)
        self.generated_root = Path("./generated_code")
        self.logs_root = Path("./agent_logs")
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
    logger.warning("Blob workspace disabled: %s", exc)

SELECTED_AGENTS_BY_PROJECT: Dict[str, Dict[str, Dict[str, Any]]] = {}

AGENT_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "backend_engineer",
        "role": "backend_engineer",
        "tier": 1,
        "model_label": "GPT-4o",
        "description": "Builds backend APIs and orchestration logic.",
        "reputation_score": 0.93,
        "tags": ["backend", "api", "python"],
    },
    {
        "id": "frontend_engineer",
        "role": "frontend_engineer",
        "tier": 1,
        "model_label": "GPT-4o",
        "description": "Builds React UI and frontend integrations.",
        "reputation_score": 0.91,
        "tags": ["frontend", "react", "ui"],
    },
    {
        "id": "database_architect",
        "role": "database_architect",
        "tier": 2,
        "model_label": "GPT-4o-mini",
        "description": "Designs schema and data layer conventions.",
        "reputation_score": 0.88,
        "tags": ["database", "sql", "schema"],
    },
    {
        "id": "qa_engineer",
        "role": "qa_engineer",
        "tier": 2,
        "model_label": "GPT-4o-mini",
        "description": "Creates tests and quality checks.",
        "reputation_score": 0.89,
        "tags": ["qa", "testing"],
    },
]

_ORCHESTRATOR_MODULE = None


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


def _discover_frontend_preview_entry(project_id: str) -> Optional[str]:
    """Return relative preview entry path under frontend_engineer/ when available."""
    base = _project_generated_dir(project_id) / "frontend_engineer"
    if not base.exists() or not base.is_dir():
        return None

    preferred = [
        "index.html",
        "dist/index.html",
        "public/index.html",
        "build/index.html",
    ]
    for rel in preferred:
        p = base / rel
        if p.exists() and p.is_file():
            return rel

    for p in sorted(base.rglob("index.html")):
        if p.is_file():
            try:
                return str(p.relative_to(base)).replace("\\", "/")
            except Exception:
                continue
    return None


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


def _sync_project_from_blob(project_id: str) -> None:
    if not BLOB_WORKSPACE:
        return
    local_dir = _project_generated_dir(project_id)
    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        count = BLOB_WORKSPACE.download_project(project_id, str(local_dir))
        logger.info("Blob sync download complete for %s: %s files -> %s", project_id, count, local_dir.resolve())
        _append_project_log(
            project_id,
            "blob_download",
            file_count=count,
            local_path=str(local_dir.resolve()),
        )
    except Exception as exc:
        logger.warning("Blob download failed for %s: %s", project_id, exc)
        _append_project_log(project_id, "blob_download_failed", error=str(exc))


def _sync_project_to_blob(project_id: str) -> None:
    if not BLOB_WORKSPACE:
        return
    local_dir = _project_generated_dir(project_id)
    try:
        count = BLOB_WORKSPACE.upload_project(project_id, str(local_dir))
        logger.info("Blob sync upload complete for %s: %s files <- %s", project_id, count, local_dir.resolve())
        _append_project_log(
            project_id,
            "blob_upload",
            file_count=count,
            local_path=str(local_dir.resolve()),
        )
    except Exception as exc:
        logger.warning("Blob upload failed for %s: %s", project_id, exc)
        _append_project_log(project_id, "blob_upload_failed", error=str(exc))


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
    """Copy generated_code outputs into project-scoped folder for preview/blob sync."""
    source_root = Path(__file__).resolve().parent / "generated_code"
    project_root = _project_generated_dir(project_id)
    project_root.mkdir(parents=True, exist_ok=True)

    if not source_root.exists():
        return

    for child in source_root.iterdir():
        # avoid recursive nesting of project snapshots
        if child.name == project_id:
            continue
        target = project_root / child.name
        if child.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(child, target)
        elif child.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


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
        "api_designer",
        "database_architect",
        "security_engineer",
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
        ["api_designer"],
        ["database_architect", "security_engineer"],
        ["backend_engineer"],
        ["frontend_engineer"],
        ["qa_engineer"],
    ]


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
    timeout_s = int(os.getenv("AGENT_TIMEOUT_SECONDS", "3600"))

    try:
        # Step 1: Import director and orchestrator modules
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from director_agent import DirectorAI, TaskLedger, normalize_layers_common_sense, default_workspace_layout
        from agent_orchestrator_v3 import EnhancedAgentOrchestrator
        
        logger.info("Step 1: Director Agent - Generating task ledger for %s", project_id)
        _append_project_log(project_id, "director_agent_start", user_intent=user_input)
        
        # Step 2: Create task ledger via Director Agent (iterative refinement)
        director = DirectorAI()
        ledger = TaskLedger(user_input, owner_id)
        previous_ledger: Optional[Dict[str, Any]] = None
        max_director_iterations = int(os.getenv("DIRECTOR_MAX_ITERATIONS", "3"))
        
        # Call director multiple times to converge on a complete ledger.
        loop = asyncio.get_event_loop()
        for iteration in range(1, max_director_iterations + 1):
            ledger_data, thought, _follow_ups = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: director.clarify_intent_with_thought(
                        ledger,
                        iteration,
                        previous_ledger,
                        {},
                    ),
                ),
                timeout=180,
            )

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
        if not isinstance(ledger.data.get("workspace_layout"), dict):
            ledger.data["workspace_layout"] = default_workspace_layout()
        _ensure_minimum_agent_spec(ledger.data)
        _normalize_workspace_layout_paths(ledger.data)
        ledger.data["status"] = "DONE"

        ledger_id = str(ledger.data.get("project_id") or project_id)
        logger.info("Director Agent complete. Task ledger generated: %s", ledger_id)
        _append_project_log(project_id, "director_agent_complete", ledger_id=ledger_id, thought=thought[:200] if thought else "")
        
        # Step 3: Persist ledger to disk (director may not have written it)
        workspace_dir = Path("./workspace")
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
        
        # Run orchestrator in executor (it's synchronous)
        result = await asyncio.wait_for(
            loop.run_in_executor(None, orchestrator.execute_all_layers),
            timeout=timeout_s,
        )
        
        logger.info("Orchestrator execution complete for ledger %s", ledger_id)
        _append_project_log(project_id, "orchestrator_complete", ledger_id=ledger_id)
        
        return {
            "status": "success",
            "project_id": project_id,
            "ledger_id": ledger_id,
            "mode": "director-orchestrator-pipeline",
            "message": "Generated via Director Agent → Orchestrator pipeline",
        }
        
    except asyncio.TimeoutError:
        msg = (
            f"Orchestration timed out after {timeout_s}s. "
            "Execution may still be running in background threads; increase AGENT_TIMEOUT_SECONDS."
        )
        logger.error("Orchestration timeout for %s: %s", project_id, msg)
        _append_project_log(project_id, "orchestration_timeout", timeout_seconds=timeout_s, error=msg)
        raise RuntimeError(msg)
    except Exception as exc:
        logger.exception("Orchestration failed for %s: %s", project_id, exc)
        _append_project_log(project_id, "orchestration_failed", error=str(exc)[:500])
        raise RuntimeError(f"Orchestration pipeline failed: {exc}")


# ------------------------------
# Internal workers
# ------------------------------

async def _simulate_generation(project_id: str) -> None:
    """Background worker to run real orchestrator generation."""
    try:
        store.update(project_id, status=ProjectStatus.GENERATING_CODE, progress=10)
        project_dir = _project_generated_dir(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
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
        if isinstance(result, dict):
            project["ledger_data"] = result

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


async def _simulate_deployment(project_id: str, request: DeploymentRequest) -> None:
    try:
        store.update(project_id, status=ProjectStatus.GENERATING_DEPLOYMENT, progress=60)
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
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
    }


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
            "container": (os.getenv("AZURE_STORAGE_CONTAINER") or "workspace"),
            "prefix": f"{project_id}/",
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
    ws = Path("./workspace")
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


@app.get("/api/preview/{project_id}/{path:path}", tags=["Compatibility"])
async def preview(project_id: str, path: str = ""):
    _sync_project_from_blob(project_id)
    filename = path.strip("/") if path and path.strip() != "/" else "index.html"
    base = _project_generated_dir(project_id) / "frontend_engineer"
    target = base / filename

    try:
        target.resolve().relative_to(base.resolve())
    except Exception:
        raise HTTPException(status_code=403, detail="Access denied")

    if not target.exists():
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
    agents = AGENT_CATALOG
    if tier is not None:
        agents = [a for a in agents if int(a.get("tier", 0)) == int(tier)]
    if role:
        role_l = role.lower()
        agents = [a for a in agents if role_l in str(a.get("role", "")).lower()]
    if tag:
        tag_l = tag.lower()
        agents = [a for a in agents if any(tag_l == str(t).lower() for t in a.get("tags", []))]
    return {"agents": agents, "count": len(agents), "source": "local"}


@app.get("/api/agents/{agent_id}", tags=["Compatibility"])
async def get_agent(agent_id: str):
    for agent in AGENT_CATALOG:
        if agent.get("id") == agent_id:
            return agent
    raise HTTPException(status_code=404, detail="Agent not found")


@app.post("/api/agents/select", tags=["Compatibility"])
async def select_agent(payload: AgentSelectionRequest):
    project_id = payload.project_id or "default"
    project_map = SELECTED_AGENTS_BY_PROJECT.setdefault(project_id, {})
    selected = next((a for a in AGENT_CATALOG if a["id"] == payload.agent_id), None)
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
            store._save()

            if project.get("status") in {ProjectStatus.CREATED.value, ProjectStatus.FAILED.value}:
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


@app.get("/aeg", tags=["Compatibility"])
async def get_aeg(project_id: str = "default"):
    try:
        project = store.get(project_id)

        if project and project.get("ledger_data"):
            return project["ledger_data"]

        return {
            "project_id": project_id,
            "project_name": "Demo Project",
            "status": "DRAFT",
            "agent_specifications": {
                "required_agents": [
                    "backend_engineer",
                    "frontend_engineer",
                    "database_architect",
                    "qa_engineer",
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


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Nexus platform-compatible backend shutting down")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    reload_enabled = str(os.getenv("BACKEND_RELOAD", "false")).lower() in {"1", "true", "yes"}
    uvicorn.run("backend_platform:app", host="0.0.0.0", port=port, reload=reload_enabled)

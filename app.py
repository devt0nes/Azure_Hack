"""
Agentic Nexus - FastAPI Backend
Orchestrates AI agents for code generation and deployment.
Designed for Azure Container Apps + Azure Static Web Apps.

Merged: Reputation Scoring Service is now embedded directly.
  - ReputationService initialised at startup and injected into agents_router.
  - POST /api/agents/{agent_id}/engagement  — orchestrator records scores
  - GET  /api/agents/{agent_id}/score       — Director reads selection score
  - POST /api/agents/{agent_id}/report      — Command Center community reports
  - POST /api/agents/{agent_id}/audit       — Human reviewer resolution
"""

import asyncio
import json
import uuid
import logging
import os
from datetime import datetime
from typing import Optional, Dict, List, Any
from pathlib import Path
from enum import Enum

from fastapi import FastAPI, HTTPException, BackgroundTasks, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from agents_router import (
    router as agents_router,
    seed_agent_catalog,
    get_selected_agents,
    init_reputation_service,
)

import main as orchestrator_module

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ORCHESTRATION_TIMEOUT_SECONDS = int(os.getenv("ORCHESTRATION_TIMEOUT_SECONDS", "600"))

# ==========================================
# FASTAPI APP INITIALIZATION
# ==========================================

app = FastAPI(
    title="Agentic Nexus Backend API",
    description="AI-powered code generation and deployment orchestration with live reputation scoring",
    version="2.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents_router)

# ==========================================
# DATA MODELS
# ==========================================

class ProjectStatus(str, Enum):
    CREATED            = "created"
    QUEUED             = "queued"
    GENERATING_CODE    = "generating_code"
    GENERATING_DEPLOYMENT = "generating_deployment"
    COMPLETED          = "completed"
    FAILED             = "failed"
    PAUSED             = "paused"


class CreateProjectRequest(BaseModel):
    project_name:    str
    user_intent:     str
    description:     Optional[str] = None
    azure_resources: Optional[List[str]] = ["cosmos_db", "blob_storage", "key_vault"]


class ProjectResponse(BaseModel):
    project_id:   str
    project_name: str
    status:       ProjectStatus
    created_at:   str
    updated_at:   str
    user_intent:  str
    progress:     int
    error:        Optional[str] = None


class ArtifactInfo(BaseModel):
    name:       str
    type:       str
    size:       int
    created_at: str
    path:       str


class DeploymentRequest(BaseModel):
    project_id:           str
    enable_docker_build:  bool = True
    enable_infrastructure: bool = True
    enable_cicd:          bool = True


class HealthResponse(BaseModel):
    status:    str
    timestamp: str
    version:   str


# ==========================================
# IN-MEMORY PROJECT TRACKING
# ==========================================

class ProjectManager:
    def __init__(self, storage_file: str = "./projects_db.json"):
        self.projects:    Dict[str, Dict[str, Any]] = {}
        self.tasks:       Dict[str, asyncio.Task]   = {}
        self.storage_file = Path(storage_file)
        self._load_projects()

    def _load_projects(self):
        try:
            if self.storage_file.exists():
                with open(self.storage_file, 'r') as f:
                    self.projects = json.load(f)
                logger.info(f"Loaded {len(self.projects)} projects from {self.storage_file}")
        except Exception as e:
            logger.error(f"Failed to load projects: {e}")
            self.projects = {}

    def _save_projects(self):
        try:
            with open(self.storage_file, 'w') as f:
                json.dump(self.projects, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save projects: {e}")

    def create_project(self, name: str, intent: str, description: str = None) -> str:
        project_id = str(uuid.uuid4())
        self.projects[project_id] = {
            "project_id":   project_id,
            "project_name": name,
            "user_intent":  intent,
            "description":  description,
            "status":       ProjectStatus.CREATED,
            "created_at":   datetime.utcnow().isoformat(),
            "updated_at":   datetime.utcnow().isoformat(),
            "progress":     0,
            "error":        None,
            "artifacts":    [],
            "ledger_data":  None,
        }
        self._save_projects()
        return project_id

    def get_project(self, project_id: str) -> Optional[Dict]:
        return self.projects.get(project_id)

    def update_project_status(self, project_id: str, status: ProjectStatus,
                               progress: int = None, error: str = None):
        if project_id in self.projects:
            self.projects[project_id]["status"]     = status
            self.projects[project_id]["updated_at"] = datetime.utcnow().isoformat()
            if progress is not None:
                self.projects[project_id]["progress"] = progress
            if error:
                self.projects[project_id]["error"] = error
            self._save_projects()

    def register_task(self, project_id: str, task: asyncio.Task):
        self.tasks[project_id] = task

    def add_artifact(self, project_id: str, artifact: ArtifactInfo):
        if project_id in self.projects:
            self.projects[project_id]["artifacts"].append(artifact.dict())
            self._save_projects()


project_manager = ProjectManager()


# ==========================================
# ORCHESTRATION SERVICE
# ==========================================

class OrchestrationService:

    @staticmethod
    async def generate_code(project_id: str, project_data: Dict) -> Dict:
        try:
            project_manager.update_project_status(project_id, ProjectStatus.GENERATING_CODE, progress=10)
            logger.info(f"Starting code generation for project {project_id}")

            user_input   = project_data.get("user_intent", "Create a web application")
            project_name = project_data.get("project_name", f"Project-{project_id[:8]}")
            owner_id     = project_data.get("owner_id", project_id)

            try:
                orchestration_task = orchestrator_module.main(
                    user_input=          user_input,
                    project_name=        project_name,
                    owner_id=            owner_id,
                    project_id_override= project_id,
                )
                result = await asyncio.wait_for(
                    orchestration_task,
                    timeout=float(ORCHESTRATION_TIMEOUT_SECONDS),
                )
                logger.info(f"Orchestration completed for project {project_id}. Result: {result}")
                project_manager.update_project_status(project_id, ProjectStatus.GENERATING_CODE, progress=90)
                project_manager.update_project_status(project_id, ProjectStatus.COMPLETED, progress=100)
                return {"status": "success", "project_id": project_id, "message": "Code generation completed"}

            except asyncio.TimeoutError:
                error_msg = f"Code generation timed out after {ORCHESTRATION_TIMEOUT_SECONDS}s"
                logger.error(f"{error_msg} for project {project_id}")
                project_manager.update_project_status(project_id, ProjectStatus.FAILED,
                                                       error=error_msg, progress=10)
                raise
            except Exception as e:
                logger.error(f"Orchestration failed for {project_id}: {e}", exc_info=True)
                project_manager.update_project_status(project_id, ProjectStatus.FAILED,
                                                       error=f"Orchestration failed: {e}", progress=10)
                raise

        except Exception as e:
            logger.error(f"Code generation error for {project_id}: {e}", exc_info=True)
            project_manager.update_project_status(project_id, ProjectStatus.FAILED, error=str(e))
            raise

    @staticmethod
    async def deploy_project(project_id: str, enable_docker: bool = True) -> Dict:
        # deployment_integration module not available — stub response
        logger.warning("deploy_project called but deployment_integration is not available.")
        project_manager.update_project_status(project_id, ProjectStatus.COMPLETED, progress=100)
        return {"status": "skipped", "reason": "deployment_integration module not available"}


# ==========================================
# API ENDPOINTS  (unchanged from original)
# ==========================================

@app.get("/api/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat(), "version": "2.0.0"}


@app.get("/api/status", tags=["Health"])
async def status():
    svc_status = "reputation_service_available"
    try:
        from agents_router import _get_rep_svc
        svc_status = "reputation_service_ok" if _get_rep_svc() else "reputation_service_unavailable"
    except Exception:
        svc_status = "reputation_service_error"

    return {
        "status":          "operational",
        "timestamp":       datetime.utcnow().isoformat(),
        "active_projects": len([p for p in project_manager.projects.values()
                                if p["status"] not in [ProjectStatus.COMPLETED, ProjectStatus.FAILED]]),
        "total_projects":  len(project_manager.projects),
        "reputation":      svc_status,
    }


@app.post("/api/projects", response_model=ProjectResponse, tags=["Projects"])
async def create_project(request: CreateProjectRequest, background_tasks: BackgroundTasks):
    try:
        project_id = project_manager.create_project(
            name=        request.project_name,
            intent=      request.user_intent,
            description= request.description,
        )
        project = project_manager.get_project(project_id)
        project["azure_resources"] = request.azure_resources
        project_manager.update_project_status(project_id, ProjectStatus.QUEUED, progress=5)
        background_tasks.add_task(OrchestrationService.generate_code, project_id, project)

        return ProjectResponse(
            project_id=   project_id,
            project_name= request.project_name,
            status=       ProjectStatus.QUEUED,
            created_at=   project["created_at"],
            updated_at=   project["updated_at"],
            user_intent=  request.user_intent,
            progress=     5,
        )
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}", response_model=ProjectResponse, tags=["Projects"])
async def get_project(project_id: str):
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return ProjectResponse(**{k: project[k] for k in ProjectResponse.model_fields if k in project})


# ==========================================
# STARTUP / SHUTDOWN
# ==========================================

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Agentic Nexus Backend API starting up (v2 — with Reputation Scoring)")

    # ── 1. Init ReputationService ───────────────────────────────────────────
    try:
        from src.reputation_service import ReputationService
        rep_svc = ReputationService.from_env()
        init_reputation_service(rep_svc)
        logger.info("✅ ReputationService initialised")
    except KeyError as e:
        logger.warning(f"⚠️  ReputationService skipped — missing env var {e} "
                       f"(set COSMOS_ENDPOINT + COSMOS_KEY to enable)")
    except Exception as e:
        logger.warning(f"⚠️  ReputationService startup failed (non-fatal): {e}")

    # ── 2. Seed catalogs (also seeds reputation docs for builtins) ──────────
    seed_agent_catalog()

    logger.info("API docs: /api/docs")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Agentic Nexus Backend API shutting down")
    for task in project_manager.tasks.values():
        if not task.done():
            task.cancel()


# ==========================================
# LEGACY COMPATIBILITY ENDPOINTS
# ==========================================

class ExecuteRequest(BaseModel):
    project_id: str


@app.post("/execute", tags=["Compatibility"])
async def execute_project_compat(request: ExecuteRequest, background_tasks: BackgroundTasks):
    try:
        project = project_manager.get_project(request.project_id)
        if not project:
            project_id = project_manager.create_project(
                name=f"Project {request.project_id[:8]}",
                intent="User initiated execution",
            )
            project = project_manager.get_project(project_id)

        if project["status"] in [ProjectStatus.CREATED, ProjectStatus.FAILED]:
            project_manager.update_project_status(request.project_id, ProjectStatus.QUEUED, progress=5)
            background_tasks.add_task(OrchestrationService.generate_code, request.project_id, project)

        return {"message": "Execution started", "project_id": request.project_id, "status": "running"}
    except Exception as e:
        logger.error(f"Execute error: {e}")
        raise HTTPException(status_code=500, detail="Failed to start execution")


@app.get("/api/tunnel-status", tags=["Compatibility"])
async def tunnel_status():
    return {"status": "local", "tunnel_url": "http://localhost:5173",
            "port": 5173, "message": "Running on localhost"}


# ==========================================
# ERROR HANDLERS
# ==========================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    logger.error(f"HTTP Exception: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "timestamp": datetime.utcnow().isoformat()},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "timestamp": datetime.utcnow().isoformat()},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
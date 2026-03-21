"""
Agentic Nexus - FastAPI Backend
Orchestrates AI agents for code generation and deployment
Designed for Azure Container Apps + Azure Static Web Apps
"""
from auth import get_current_user
import asyncio
import json
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any
from pathlib import Path
from enum import Enum

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

import main as orchestrator_module
from agents_router import router as agents_router, seed_agent_catalog
from cost_router import router as cost_router
from templates_router import router as templates_router, seed_template_catalog

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agentic Nexus Backend API",
    description="AI-powered code generation and deployment orchestration",
    version="1.0.0",
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

# ==========================================
# DATA MODELS
# ==========================================

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
    deploy_url: Optional[str] = None


class ArtifactInfo(BaseModel):
    name: str
    type: str
    size: int
    created_at: str
    path: str


class DeploymentRequest(BaseModel):
    project_id: str
    enable_docker_build: bool = True
    enable_infrastructure: bool = True
    enable_cicd: bool = True


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str


# ==========================================
# IN-MEMORY PROJECT TRACKING
# ==========================================

class ProjectManager:
    def __init__(self, storage_file: str = "./projects_db.json"):
        self.projects: Dict[str, Dict[str, Any]] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
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

    def create_project(self, name: str, intent: str, description: str = None, owner_id: str = None) -> str:
        project_id = str(uuid.uuid4())
        self.projects[project_id] = {
            "project_id": project_id,
            "project_name": name,
            "user_intent": intent,
            "description": description,
            "owner_id": owner_id,  # ← scoped to user
            "status": ProjectStatus.CREATED,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "progress": 0,
            "error": None,
            "artifacts": [],
            "ledger_data": None,
        }
        self._save_projects()
        return project_id

    def get_project(self, project_id: str) -> Optional[Dict]:
        return self.projects.get(project_id)

    def get_projects_for_user(self, owner_id: str) -> List[Dict]:
        """Return only projects belonging to this user"""
        return [p for p in self.projects.values() if p.get("owner_id") == owner_id]

    def update_project_status(self, project_id: str, status: ProjectStatus, progress: int = None, error: str = None):
        if project_id in self.projects:
            self.projects[project_id]["status"] = status
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
# OWNERSHIP HELPER
# ==========================================

def assert_project_owner(project: Dict, user_id: str):
    """Raise 403 if the project doesn't belong to this user"""
    if project.get("owner_id") and project["owner_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")


# ==========================================
# ORCHESTRATION SERVICE
# ==========================================

class OrchestrationService:
    @staticmethod
    async def generate_code(project_id: str, project_data: Dict) -> Dict:
        try:
            project_manager.update_project_status(project_id, ProjectStatus.GENERATING_CODE, progress=10)
            user_input = project_data.get("user_intent", "Create a web application")
            project_name = project_data.get("project_name", f"Project-{project_id[:8]}")
            owner_id = project_data.get("owner_id", project_id)
            try:
                orchestration_task = orchestrator_module.main(
                    user_input=user_input,
                    project_name=project_name,
                    owner_id=owner_id
                )
                result = await asyncio.wait_for(orchestration_task, timeout=300.0)
                project_manager.update_project_status(project_id, ProjectStatus.GENERATING_CODE, progress=90)
                project_manager.update_project_status(project_id, ProjectStatus.COMPLETED, progress=100)
                return {"status": "success", "project_id": project_id, "message": "Code generation completed"}
            except asyncio.TimeoutError:
                error_msg = "Code generation timed out after 5 minutes"
                project_manager.update_project_status(project_id, ProjectStatus.FAILED, error=error_msg, progress=10)
                raise
            except Exception as e:
                project_manager.update_project_status(project_id, ProjectStatus.FAILED, error=f"Orchestration failed: {str(e)}", progress=10)
                raise
        except Exception as e:
            project_manager.update_project_status(project_id, ProjectStatus.FAILED, error=str(e))
            raise

    @staticmethod
    async def deploy_project(project_id: str, enable_docker: bool = True) -> Dict:
        try:
            project_manager.update_project_status(project_id, ProjectStatus.GENERATING_DEPLOYMENT, progress=50)
            project_data = project_manager.get_project(project_id)
            if not project_data:
                raise ValueError(f"Project {project_id} not found")
            from deployment_integration import run_post_generation_deployment
            result = await run_post_generation_deployment(
                project_id=project_id,
                app_name=project_data["project_name"],
                ledger_data=project_data.get("ledger_data", {}),
                enable_bundle=enable_docker,
                enable_blueprint=True,
                enable_cost_estimate=True,
                enable_cloud_deploy=True
            )
            deploy_url = (
                result.get("deployment_tasks", {})
                      .get("cloud_deploy", {})
                      .get("deploy_url")
            )
            if deploy_url:
                project_manager.projects[project_id]["deploy_url"] = deploy_url
                project_manager._save_projects()
            project_manager.update_project_status(project_id, ProjectStatus.COMPLETED, progress=100)
            return result
        except Exception as e:
            project_manager.update_project_status(project_id, ProjectStatus.FAILED, error=str(e))
            raise


# ==========================================
# API ENDPOINTS
# ==========================================

# --- Public endpoints (no auth) ---

@app.get("/api/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat(), "version": "1.0.0"}


@app.get("/api/status", tags=["Health"])
async def status():
    return {
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat(),
        "active_projects": len([p for p in project_manager.projects.values() if p["status"] not in [ProjectStatus.COMPLETED, ProjectStatus.FAILED]]),
        "total_projects": len(project_manager.projects)
    }


@app.get("/")
async def root():
    return {"message": "Agentic Nexus Backend API", "documentation": "/api/docs", "health": "/api/health"}


# --- Protected endpoints ---

@app.post("/api/projects", response_model=ProjectResponse, tags=["Projects"])
async def create_project(
    request: CreateProjectRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user)   # ← auth
):
    try:
        project_id = project_manager.create_project(
            name=request.project_name,
            intent=request.user_intent,
            description=request.description,
            owner_id=user["id"]          # ← scoped to user
        )
        project = project_manager.get_project(project_id)
        project["azure_resources"] = request.azure_resources
        project_manager.update_project_status(project_id, ProjectStatus.QUEUED, progress=5)
        background_tasks.add_task(OrchestrationService.generate_code, project_id, project)
        return ProjectResponse(
            project_id=project_id,
            project_name=request.project_name,
            status=ProjectStatus.QUEUED,
            created_at=project["created_at"],
            updated_at=project["updated_at"],
            user_intent=request.user_intent,
            progress=5
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects", tags=["Projects"])
async def list_projects(user=Depends(get_current_user)):   # ← auth
    projects = project_manager.get_projects_for_user(user["id"])  # ← only their projects
    return {
        "total_projects": len(projects),
        "projects": [
            {
                "project_id": p["project_id"],
                "project_name": p["project_name"],
                "status": p["status"],
                "created_at": p["created_at"],
                "progress": p["progress"]
            }
            for p in projects
        ]
    }


@app.get("/api/projects/{project_id}", response_model=ProjectResponse, tags=["Projects"])
async def get_project(project_id: str, user=Depends(get_current_user)):   # ← auth
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    assert_project_owner(project, user["id"])   # ← ownership check
    return ProjectResponse(
        project_id=project["project_id"],
        project_name=project["project_name"],
        status=project["status"],
        created_at=project["created_at"],
        updated_at=project["updated_at"],
        user_intent=project["user_intent"],
        progress=project["progress"],
        error=project.get("error"),
        deploy_url=project.get("deploy_url")
    )


@app.get("/api/projects/{project_id}/artifacts", tags=["Artifacts"])
async def list_artifacts(project_id: str, user=Depends(get_current_user)):   # ← auth
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    assert_project_owner(project, user["id"])
    artifacts = []
    generated_dir = Path("./generated_code")
    if generated_dir.exists():
        for file_path in generated_dir.rglob("*"):
            if file_path.is_file():
                relative_path = file_path.relative_to(generated_dir)
                artifacts.append({
                    "name": file_path.name,
                    "type": "code" if file_path.suffix in [".py", ".ts", ".tsx", ".js", ".jsx"] else "config",
                    "size": file_path.stat().st_size,
                    "created_at": datetime.fromtimestamp(file_path.stat().st_ctime).isoformat(),
                    "path": str(relative_path)
                })
    return {"project_id": project_id, "artifact_count": len(artifacts), "artifacts": artifacts}


@app.get("/api/projects/{project_id}/artifacts/{artifact_name}", tags=["Artifacts"])
async def download_artifact(project_id: str, artifact_name: str, user=Depends(get_current_user)):   # ← auth
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    assert_project_owner(project, user["id"])
    artifact_path = Path("./generated_code") / artifact_name
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_name} not found")
    return FileResponse(path=artifact_path, filename=artifact_name, media_type="application/octet-stream")


@app.get("/api/projects/{project_id}/logs", tags=["Logs"])
async def get_project_logs(project_id: str, user=Depends(get_current_user)):   # ← auth
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    assert_project_owner(project, user["id"])
    logs_dir = Path(f"./agent_logs")
    logs = {}
    if logs_dir.exists():
        for log_file in logs_dir.glob("*.log"):
            try:
                with open(log_file, 'r') as f:
                    logs[log_file.name] = f.read()
            except Exception as e:
                logger.warning(f"Could not read log file {log_file.name}: {e}")
    return {"project_id": project_id, "logs": logs}


@app.post("/api/projects/{project_id}/deploy", tags=["Deployment"])
async def deploy_project(
    project_id: str,
    request: DeploymentRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user)   # ← auth
):
    try:
        project_manager._load_projects()
        project = project_manager.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        assert_project_owner(project, user["id"])
        current_status = str(project.get("status", "")).strip().lower()
        if current_status != ProjectStatus.COMPLETED.value:
            raise HTTPException(status_code=400, detail=f"Project must be in COMPLETED state, current state: {project.get('status')}")
        project_manager.update_project_status(project_id, ProjectStatus.GENERATING_DEPLOYMENT, progress=50)
        background_tasks.add_task(OrchestrationService.deploy_project, project_id, request.enable_docker_build)
        return {"status": "deployment_queued", "project_id": project_id, "message": "Deployment integration started"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}/deployment-status", tags=["Deployment"])
async def get_deployment_status(project_id: str, user=Depends(get_current_user)):   # ← auth
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    assert_project_owner(project, user["id"])
    deployment_dir = Path("./generated_code/deployment")
    artifacts = []
    if deployment_dir.exists():
        for file_path in deployment_dir.iterdir():
            if file_path.is_file():
                artifacts.append({
                    "name": file_path.name,
                    "size": file_path.stat().st_size,
                    "created_at": datetime.fromtimestamp(file_path.stat().st_ctime).isoformat()
                })
    return {
        "project_id": project_id,
        "deployment_status": project["status"],
        "artifacts": artifacts,
        "cost_estimate_available": (deployment_dir / "cost_estimate.json").exists() if deployment_dir.exists() else False
    }


@app.get("/api/projects/{project_id}/cost-estimate", tags=["Deployment"])
async def get_cost_estimate(project_id: str, user=Depends(get_current_user)):   # ← auth
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    assert_project_owner(project, user["id"])
    estimate_file = Path("./generated_code/cost_estimate.json")
    if not estimate_file.exists():
        raise HTTPException(status_code=404, detail="Cost estimate not available yet")
    try:
        with open(estimate_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to read cost estimate")


# ==========================================
# COMPATIBILITY ENDPOINTS
# ==========================================

class ClarifyRequest(BaseModel):
    project_id: str
    user_input: str


@app.post("/clarify", tags=["Compatibility"])
async def clarify_intent(
    request: ClarifyRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user)   # ← auth
):
    try:
        project_id = project_manager.create_project(
            name=f"Project from clarification",
            intent=request.user_input,
            description=None,
            owner_id=user["id"]          # ← scoped to user
        )
        project = project_manager.get_project(project_id)
        project_manager.update_project_status(project_id, ProjectStatus.QUEUED, progress=5)
        background_tasks.add_task(OrchestrationService.generate_code, project_id, project)
        return {
            "director_reply": f"I understand you want to: {request.user_input}. I'll create a task breakdown and coordinate the agents.",
            "project_id": project_id,
            "status": "clarified"
        }
    except Exception as e:
        logger.error(f"Clarify error: {str(e)}")
        error_project_id = str(uuid.uuid4())
        return {
            "director_reply": "I'm processing your request. The orchestration will begin shortly.",
            "project_id": error_project_id,
            "status": "processing"
        }


@app.get("/aeg", tags=["Compatibility"])
async def get_aeg(project_id: str = "default", user=Depends(get_current_user)):   # ← auth
    try:
        project = project_manager.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        assert_project_owner(project, user["id"])

        user_intent = project.get("user_intent", "Create a web application")
        status = project.get("status", "created")

        if project.get("ledger_data"):
            ledger_data = project["ledger_data"]
            return {
                **ledger_data,
                "project_id": project_id,
                "status": "COMPLETED" if status == "completed" else "IN_PROGRESS",
                "progress": project.get("progress", 0)
            }

        agents = ["frontend_engineer"]
        if "backend" in user_intent.lower() or "api" in user_intent.lower():
            agents.insert(0, "backend_engineer")
        if "database" in user_intent.lower() or "db" in user_intent.lower():
            agents.append("database_architect")
        if "test" in user_intent.lower() or "qa" in user_intent.lower():
            agents.append("qa_engineer")
        if "deploy" in user_intent.lower() or "devops" in user_intent.lower():
            agents.append("devops_engineer")

        dependencies = {
            "backend_engineer": [],
            "frontend_engineer": [d for d in ["backend_engineer"] if d in agents],
            "database_architect": [],
            "qa_engineer": ["backend_engineer", "frontend_engineer"],
            "devops_engineer": ["backend_engineer", "frontend_engineer"],
        }
        filtered_deps = {agent: [d for d in dependencies.get(agent, []) if d in agents] for agent in agents}
        level_0 = [a for a in agents if not filtered_deps[a]]
        level_1 = [a for a in agents if filtered_deps[a]]
        parallel_groups = [level_0] + ([level_1] if level_1 else [])

        task_ledger = []
        task_names = ["Frontend Development", "Backend Development", "Database Setup", "QA Testing", "Deployment"]
        task_id = 1
        for group_idx, group in enumerate(parallel_groups):
            for agent in group:
                task_name = f"{agent.replace('_', ' ').title()}: {task_names[min(task_id-1, len(task_names)-1)]}"
                task_ledger.append({
                    "id": task_id,
                    "name": task_name,
                    "agent": agent,
                    "status": "IN_PROGRESS" if status == "generating_code" else "PENDING",
                    "progress": project.get("progress", 0) if status == "generating_code" else 0,
                    "estimated_duration": "5-10 minutes",
                    "dependencies": filtered_deps.get(agent, [])
                })
                task_id += 1

        return {
            "project_id": project_id,
            "project_name": project.get("project_name", f"Project {project_id[:8]}"),
            "status": "IN_PROGRESS" if status == "generating_code" else "DRAFT",
            "progress": project.get("progress", 0),
            "user_intent": user_intent,
            "task_ledger": task_ledger,
            "agent_specifications": {
                "required_agents": agents,
                "agent_dependencies": filtered_deps,
                "parallel_execution_groups": parallel_groups
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch AEG")


# Preview is intentionally left PUBLIC — iframe embeds can't send auth headers
@app.get("/api/preview/{project_id}/{path:path}", tags=["Preview"])
async def serve_preview(project_id: str, path: str = ""):
    try:
        from fastapi.responses import StreamingResponse
        filename = path.strip("/") if path and path.strip() != "/" else "index.html"
        try:
            cosmos_manager = orchestrator_module.CosmosManager()
            query = """
                SELECT c.content, c.filename FROM c 
                WHERE c.project_id = @project_id 
                AND c.type = 'artifact.code' 
                AND c.filename = @filename
            """
            items = list(cosmos_manager.exchange_log_container.query_items(
                query=query,
                parameters=[
                    {"name": "@project_id", "value": project_id},
                    {"name": "@filename", "value": filename}
                ]
            ))
            if items:
                content = items[0].get('content')
                if content:
                    suffix = filename.lower()
                    content_types = {'.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg', '.gif': 'image/gif', '.svg': 'image/svg+xml'}
                    content_type = next((ct for ext, ct in content_types.items() if suffix.endswith(ext)), 'application/octet-stream')
                    return StreamingResponse(iter([content.encode('utf-8') if isinstance(content, str) else content]), media_type=content_type)
        except Exception as cosmos_error:
            logger.warning(f"Cosmos fallback: {cosmos_error}")

        generated_path = Path("./generated_code") / "frontend_engineer" / filename
        base_path = Path("./generated_code") / "frontend_engineer"
        try:
            generated_path.resolve().relative_to(base_path.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if not generated_path.exists():
            error_html = f"""<!DOCTYPE html><html><head><title>Preview Not Available</title></head>
            <body style="font-family:sans-serif;text-align:center;padding:50px">
            <h1>⏳ Preview Not Available</h1>
            <p>Code generation is still in progress or hasn't started yet.</p></body></html>"""
            return HTMLResponse(content=error_html, status_code=200)

        suffix = generated_path.suffix.lower()
        content_types = {'.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg', '.gif': 'image/gif', '.svg': 'image/svg+xml'}
        content_type = content_types.get(suffix, 'application/octet-stream')
        return FileResponse(generated_path, media_type=content_type)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to serve preview")


class ExecuteRequest(BaseModel):
    project_id: str


@app.post("/execute", tags=["Compatibility"])
async def execute_project_compat(
    request: ExecuteRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user)   # ← auth
):
    try:
        project = project_manager.get_project(request.project_id)
        if not project:
            project_id = project_manager.create_project(
                name=f"Project {request.project_id[:8]}",
                intent="User initiated execution",
                description=None,
                owner_id=user["id"]
            )
            project = project_manager.get_project(project_id)
        else:
            assert_project_owner(project, user["id"])

        if project["status"] in [ProjectStatus.CREATED, ProjectStatus.FAILED]:
            project_manager.update_project_status(request.project_id, ProjectStatus.QUEUED, progress=5)
            background_tasks.add_task(OrchestrationService.generate_code, request.project_id, project)

        return {"message": "Execution started", "project_id": request.project_id, "status": "running"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to start execution")


class TutorRequest(BaseModel):
    project_id: str
    question: str
    context: Optional[Dict] = {}


@app.post("/tutor/ask", tags=["Compatibility"])
async def tutor_ask(request: TutorRequest, user=Depends(get_current_user)):   # ← auth
    question_lower = request.question.lower()
    response_text = "I'm the Agentic Nexus learning assistant. "
    if "explain" in question_lower or "what is" in question_lower:
        response_text += "The Agentic Nexus uses specialized AI agents to collaboratively build full-stack applications."
    elif "aeg" in question_lower or "graph" in question_lower:
        response_text += "The Agent Execution Graph (AEG) shows dependencies between agents."
    elif "cost" in question_lower:
        response_text += "Cost tracking monitors token usage from AI calls."
    else:
        response_text += "Ask me about: agent execution, the AEG, cost tracking, or how orchestration works."
    return {"response": response_text, "level": "overview", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/tunnel-status", tags=["Compatibility"])
async def tunnel_status():  # intentionally public — just returns config info
    return {"status": "local", "tunnel_url": "http://localhost:5173", "port": 5173, "message": "Running on localhost"}


# ==========================================
# ==========================================
# INCLUDE ROUTERS
# ==========================================

app.include_router(agents_router, dependencies=[Depends(get_current_user)])
app.include_router(cost_router, dependencies=[Depends(get_current_user)])
app.include_router(templates_router, dependencies=[Depends(get_current_user)])


# ERROR HANDLERS
# ==========================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail, "timestamp": datetime.utcnow().isoformat()})


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error", "timestamp": datetime.utcnow().isoformat()})


# ==========================================
# STARTUP / SHUTDOWN
# ==========================================

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Agentic Nexus Backend API starting up")
    seed_agent_catalog()
    seed_template_catalog()

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Agentic Nexus Backend API shutting down")
    for task in project_manager.tasks.values():
        if not task.done():
            task.cancel()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
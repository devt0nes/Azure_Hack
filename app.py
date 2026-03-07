"""
Agentic Nexus - FastAPI Backend
Orchestrates AI agents for code generation and deployment
Designed for Azure Container Apps + Azure Static Web Apps
"""

import asyncio
import json
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any
from pathlib import Path
from enum import Enum

from fastapi import FastAPI, HTTPException, BackgroundTasks, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Import main orchestration
import main as orchestrator_module

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==========================================
# FASTAPI APP INITIALIZATION
# ==========================================

app = FastAPI(
    title="Agentic Nexus Backend API",
    description="AI-powered code generation and deployment orchestration",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json"
)

# Enable CORS for Azure Static Web App frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure with specific domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# DATA MODELS
# ==========================================

class ProjectStatus(str, Enum):
    """Project execution status"""
    CREATED = "created"
    QUEUED = "queued"
    GENERATING_CODE = "generating_code"
    GENERATING_DEPLOYMENT = "generating_deployment"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class CreateProjectRequest(BaseModel):
    """Request to create and start a new project"""
    project_name: str
    user_intent: str
    description: Optional[str] = None
    azure_resources: Optional[List[str]] = ["cosmos_db", "blob_storage", "key_vault"]


class ProjectResponse(BaseModel):
    """Project metadata and status"""
    project_id: str
    project_name: str
    status: ProjectStatus
    created_at: str
    updated_at: str
    user_intent: str
    progress: int  # 0-100
    error: Optional[str] = None


class ArtifactInfo(BaseModel):
    """Information about a generated artifact"""
    name: str
    type: str  # "code", "documentation", "deployment", "config"
    size: int
    created_at: str
    path: str


class DeploymentRequest(BaseModel):
    """Request to deploy a project"""
    project_id: str
    enable_docker_build: bool = True
    enable_infrastructure: bool = True
    enable_cicd: bool = True


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: str
    version: str


# ==========================================
# IN-MEMORY PROJECT TRACKING
# ==========================================

class ProjectManager:
    """
    Manages project state and execution tracking.
    In production, this should use Cosmos DB.
    """
    def __init__(self):
        self.projects: Dict[str, Dict[str, Any]] = {}
        self.tasks: Dict[str, asyncio.Task] = {}

    def create_project(self, name: str, intent: str, description: str = None) -> str:
        """Create a new project and return its ID"""
        project_id = str(uuid.uuid4())
        self.projects[project_id] = {
            "project_id": project_id,
            "project_name": name,
            "user_intent": intent,
            "description": description,
            "status": ProjectStatus.CREATED,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "progress": 0,
            "error": None,
            "artifacts": [],
            "ledger_data": None,
        }
        return project_id

    def get_project(self, project_id: str) -> Optional[Dict]:
        """Get project by ID"""
        return self.projects.get(project_id)

    def update_project_status(self, project_id: str, status: ProjectStatus, progress: int = None, error: str = None):
        """Update project status"""
        if project_id in self.projects:
            self.projects[project_id]["status"] = status
            self.projects[project_id]["updated_at"] = datetime.utcnow().isoformat()
            if progress is not None:
                self.projects[project_id]["progress"] = progress
            if error:
                self.projects[project_id]["error"] = error

    def register_task(self, project_id: str, task: asyncio.Task):
        """Register a background task"""
        self.tasks[project_id] = task

    def add_artifact(self, project_id: str, artifact: ArtifactInfo):
        """Add artifact to project"""
        if project_id in self.projects:
            self.projects[project_id]["artifacts"].append(artifact.dict())


# Global project manager
project_manager = ProjectManager()

# ==========================================
# ORCHESTRATION SERVICE
# ==========================================

class OrchestrationService:
    """
    Wraps the main orchestrator to work with FastAPI
    """

    @staticmethod
    async def generate_code(project_id: str, project_data: Dict) -> Dict:
        """
        Run the code generation pipeline asynchronously
        """
        try:
            project_manager.update_project_status(project_id, ProjectStatus.GENERATING_CODE, progress=10)
            
            logger.info(f"Starting code generation for project {project_id}")
            
            # Run the main orchestration in a thread to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: asyncio.run(
                    orchestrator_module.main()
                )
            )
            
            project_manager.update_project_status(project_id, ProjectStatus.COMPLETED, progress=100)
            logger.info(f"Code generation completed for project {project_id}")
            
            return {
                "status": "success",
                "project_id": project_id,
                "message": "Code generation completed"
            }
        
        except Exception as e:
            logger.error(f"Code generation failed for project {project_id}: {str(e)}")
            project_manager.update_project_status(
                project_id,
                ProjectStatus.FAILED,
                error=str(e)
            )
            raise

    @staticmethod
    async def deploy_project(project_id: str, enable_docker: bool = True) -> Dict:
        """
        Run deployment integration
        """
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
                enable_cost_estimate=True
            )
            
            project_manager.update_project_status(project_id, ProjectStatus.COMPLETED, progress=100)
            
            return result
        
        except Exception as e:
            logger.error(f"Deployment failed for project {project_id}: {str(e)}")
            project_manager.update_project_status(project_id, ProjectStatus.FAILED, error=str(e))
            raise


# ==========================================
# API ENDPOINTS
# ==========================================

@app.get("/api/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint for Azure load balancer
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0"
    }


@app.get("/api/status", tags=["Health"])
async def status():
    """
    System status endpoint
    """
    return {
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat(),
        "active_projects": len([p for p in project_manager.projects.values() if p["status"] not in [ProjectStatus.COMPLETED, ProjectStatus.FAILED]]),
        "total_projects": len(project_manager.projects)
    }


@app.post("/api/projects", response_model=ProjectResponse, tags=["Projects"])
async def create_project(request: CreateProjectRequest, background_tasks: BackgroundTasks):
    """
    Create and start a new code generation project
    
    This endpoint:
    1. Creates a new project
    2. Queues code generation in background
    3. Returns project ID for status tracking
    """
    try:
        # Create project
        project_id = project_manager.create_project(
            name=request.project_name,
            intent=request.user_intent,
            description=request.description
        )
        
        logger.info(f"Created project {project_id}: {request.project_name}")
        
        # Update project with azure resources
        project = project_manager.get_project(project_id)
        project["azure_resources"] = request.azure_resources
        project_manager.update_project_status(project_id, ProjectStatus.QUEUED, progress=5)
        
        # Queue code generation as background task
        background_tasks.add_task(
            OrchestrationService.generate_code,
            project_id,
            project
        )
        
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
        logger.error(f"Failed to create project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}", response_model=ProjectResponse, tags=["Projects"])
async def get_project(project_id: str):
    """
    Get project status and metadata
    """
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    return ProjectResponse(
        project_id=project["project_id"],
        project_name=project["project_name"],
        status=project["status"],
        created_at=project["created_at"],
        updated_at=project["updated_at"],
        user_intent=project["user_intent"],
        progress=project["progress"],
        error=project.get("error")
    )


@app.get("/api/projects/{project_id}/artifacts", tags=["Artifacts"])
async def list_artifacts(project_id: str):
    """
    List all generated artifacts for a project
    """
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    artifacts = []
    generated_dir = Path("./generated_code")
    
    if generated_dir.exists():
        # Scan for artifacts
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
    
    return {
        "project_id": project_id,
        "artifact_count": len(artifacts),
        "artifacts": artifacts
    }


@app.get("/api/projects/{project_id}/artifacts/{artifact_name}", tags=["Artifacts"])
async def download_artifact(project_id: str, artifact_name: str):
    """
    Download a specific artifact
    """
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    artifact_path = Path("./generated_code") / artifact_name
    
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_name} not found")
    
    return FileResponse(
        path=artifact_path,
        filename=artifact_name,
        media_type="application/octet-stream"
    )


@app.get("/api/projects/{project_id}/logs", tags=["Logs"])
async def get_project_logs(project_id: str):
    """
    Get audit logs for a project
    """
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    logs_dir = Path(f"./agent_logs")
    logs = {}
    
    if logs_dir.exists():
        for log_file in logs_dir.glob("*.log"):
            try:
                with open(log_file, 'r') as f:
                    logs[log_file.name] = f.read()
            except Exception as e:
                logger.warning(f"Could not read log file {log_file.name}: {e}")
    
    return {
        "project_id": project_id,
        "logs": logs
    }


@app.post("/api/projects/{project_id}/deploy", tags=["Deployment"])
async def deploy_project(project_id: str, request: DeploymentRequest, background_tasks: BackgroundTasks):
    """
    Trigger deployment integration for a project
    
    Generates:
    - Dockerfile
    - Bicep infrastructure file
    - GitHub Actions CI/CD pipeline
    - README deployment guide
    - Cost estimates
    """
    try:
        project = project_manager.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        
        if project["status"] not in [ProjectStatus.COMPLETED]:
            raise HTTPException(
                status_code=400,
                detail=f"Project must be in COMPLETED state, current state: {project['status']}"
            )
        
        project_manager.update_project_status(project_id, ProjectStatus.GENERATING_DEPLOYMENT, progress=50)
        
        # Queue deployment as background task
        background_tasks.add_task(
            OrchestrationService.deploy_project,
            project_id,
            request.enable_docker_build
        )
        
        return {
            "status": "deployment_queued",
            "project_id": project_id,
            "message": "Deployment integration started"
        }
    
    except Exception as e:
        logger.error(f"Failed to start deployment: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}/deployment-status", tags=["Deployment"])
async def get_deployment_status(project_id: str):
    """
    Get deployment status for a project
    """
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
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
async def get_cost_estimate(project_id: str):
    """
    Get monthly Azure cost estimate for a project
    """
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    estimate_file = Path("./generated_code/cost_estimate.json")
    
    if not estimate_file.exists():
        raise HTTPException(status_code=404, detail="Cost estimate not available yet")
    
    try:
        with open(estimate_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read cost estimate: {e}")
        raise HTTPException(status_code=500, detail="Failed to read cost estimate")


@app.get("/api/projects", tags=["Projects"])
async def list_projects():
    """
    List all projects
    """
    return {
        "total_projects": len(project_manager.projects),
        "projects": [
            {
                "project_id": p["project_id"],
                "project_name": p["project_name"],
                "status": p["status"],
                "created_at": p["created_at"],
                "progress": p["progress"]
            }
            for p in project_manager.projects.values()
        ]
    }


# ==========================================
# ERROR HANDLERS
# ==========================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    logger.error(f"HTTP Exception: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """General exception handler"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "timestamp": datetime.utcnow().isoformat()
        }
    )


# ==========================================
# STARTUP/SHUTDOWN EVENTS
# ==========================================

@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    logger.info("🚀 Agentic Nexus Backend API starting up")
    logger.info(f"API Documentation: /api/docs")
    logger.info(f"OpenAPI Schema: /api/openapi.json")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("🛑 Agentic Nexus Backend API shutting down")
    # Cancel any running tasks
    for task in project_manager.tasks.values():
        if not task.done():
            task.cancel()


# ==========================================
# ROOT REDIRECT
# ==========================================

@app.get("/")
async def root():
    """Root endpoint - redirects to API docs"""
    return {
        "message": "Agentic Nexus Backend API",
        "documentation": "/api/docs",
        "health": "/api/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )

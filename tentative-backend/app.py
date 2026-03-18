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
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from agents_router import router as agents_router
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
app.include_router(agents_router)

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
    Persists projects to disk for recovery across restarts.
    """
    def __init__(self, storage_file: str = "./projects_db.json"):
        self.projects: Dict[str, Dict[str, Any]] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.storage_file = Path(storage_file)
        self._load_projects()

    def _load_projects(self):
        """Load projects from storage file"""
        try:
            if self.storage_file.exists():
                with open(self.storage_file, 'r') as f:
                    self.projects = json.load(f)
                logger.info(f"Loaded {len(self.projects)} projects from {self.storage_file}")
        except Exception as e:
            logger.error(f"Failed to load projects: {e}")
            self.projects = {}

    def _save_projects(self):
        """Save projects to storage file"""
        try:
            with open(self.storage_file, 'w') as f:
                json.dump(self.projects, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save projects: {e}")

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
        self._save_projects()
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
            self._save_projects()

    def register_task(self, project_id: str, task: asyncio.Task):
        """Register a background task"""
        self.tasks[project_id] = task

    def add_artifact(self, project_id: str, artifact: ArtifactInfo):
        """Add artifact to project"""
        if project_id in self.projects:
            self.projects[project_id]["artifacts"].append(artifact.dict())
            self._save_projects()


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
        Run the code generation pipeline asynchronously with timeout protection
        """
        try:
            project_manager.update_project_status(project_id, ProjectStatus.GENERATING_CODE, progress=10)
            
            logger.info(f"Starting code generation for project {project_id}")
            
            # Extract user intent and project name from project data
            user_input = project_data.get("user_intent", "Create a web application")
            project_name = project_data.get("project_name", f"Project-{project_id[:8]}")
            owner_id = project_data.get("owner_id", project_id)
            
            logger.info(f"Project Intent: {user_input}")
            logger.info(f"Project Name: {project_name}")
            
            # Run the main orchestration with a timeout (300 seconds = 5 minutes max per request)
            try:
                # Set timeout for orchestration
                orchestration_task = orchestrator_module.main(
                    user_input=user_input,
                    project_name=project_name,
                    owner_id=owner_id
                )
                
                # Execute with timeout
                result = await asyncio.wait_for(orchestration_task, timeout=300.0)
                
                logger.info(f"Orchestration completed. Result: {result}")
                
                # Update progress to 90% after orchestration completes
                project_manager.update_project_status(project_id, ProjectStatus.GENERATING_CODE, progress=90)
                
                # Mark as completed
                project_manager.update_project_status(project_id, ProjectStatus.COMPLETED, progress=100)
                logger.info(f"Code generation completed for project {project_id}")
                
                return {
                    "status": "success",
                    "project_id": project_id,
                    "message": "Code generation completed"
                }
            except asyncio.TimeoutError:
                error_msg = "Code generation timed out after 5 minutes"
                logger.error(f"{error_msg} for project {project_id}")
                project_manager.update_project_status(
                    project_id,
                    ProjectStatus.FAILED,
                    error=error_msg,
                    progress=10
                )
                raise
            except Exception as e:
                logger.error(f"Orchestration failed for project {project_id}: {str(e)}", exc_info=True)
                project_manager.update_project_status(
                    project_id,
                    ProjectStatus.FAILED,
                    error=f"Orchestration failed: {str(e)}",
                    progress=10
                )
                raise
        
        except Exception as e:
            logger.error(f"Code generation error for project {project_id}: {str(e)}", exc_info=True)
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
# COMPATIBILITY ENDPOINTS (Legacy Frontend Support)
# ==========================================

class ClarifyRequest(BaseModel):
    """Legacy clarify request"""
    project_id: str
    user_input: str


@app.post("/clarify", tags=["Compatibility"])
async def clarify_intent(request: ClarifyRequest, background_tasks: BackgroundTasks):
    """
    Legacy Director clarification endpoint (compatibility layer)
    Always creates a NEW project for each clarification request and triggers code generation
    """
    try:
        # Always create a new project for new clarification requests
        # This ensures each request gets fresh generation, not reuse of completed projects
        project_id = project_manager.create_project(
            name=f"Project from clarification",
            intent=request.user_input,
            description=None
        )
        project = project_manager.get_project(project_id)
        
        # Update status to queued and trigger code generation
        project_manager.update_project_status(project_id, ProjectStatus.QUEUED, progress=5)
        
        # Queue code generation as background task
        background_tasks.add_task(
            OrchestrationService.generate_code,
            project_id,
            project
        )
        
        logger.info(f"Clarify: Created NEW project {project_id} and queued code generation")
        
        # Return director-style response with the new project ID
        return {
            "director_reply": f"I understand you want to: {request.user_input}. I'll create a task breakdown and coordinate the agents.",
            "project_id": project_id,
            "status": "clarified"
        }
    except Exception as e:
        logger.error(f"Clarify error: {str(e)}")
        # Generate a new project ID for error response
        error_project_id = str(uuid.uuid4())
        return {
            "director_reply": "I'm processing your request. The orchestration will begin shortly.",
            "project_id": error_project_id,
            "status": "processing"
        }


@app.get("/aeg", tags=["Compatibility"])
async def get_aeg(project_id: str = "default"):
    """
    Legacy AEG endpoint (compatibility layer)
    Returns agent execution graph structure with real-time updates
    """
    try:
        project = project_manager.get_project(project_id)
        
        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        
        user_intent = project.get("user_intent", "Create a web application")
        status = project.get("status", "created")
        
        # If ledger_data exists (from actual generation), return it with real task info
        if project.get("ledger_data"):
            ledger_data = project["ledger_data"]
            # Enhance with current status and progress
            return {
                **ledger_data,
                "project_id": project_id,
                "status": "COMPLETED" if status == "completed" else "IN_PROGRESS",
                "progress": project.get("progress", 0)
            }
        
        # For projects in progress, generate task structure based on intent
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
        
        # Group agents by dependency level
        level_0 = [a for a in agents if not filtered_deps[a]]
        level_1 = [a for a in agents if filtered_deps[a]]
        parallel_groups = [level_0] + ([level_1] if level_1 else [])
        
        # Build task ledger with real task structure
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
        logger.error(f"AEG error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch AEG")


@app.get("/api/preview/{project_id}/{path:path}", tags=["Preview"])
async def serve_preview(project_id: str, path: str = ""):
    """
    Serve generated frontend code for preview
    Fetches from Cosmos DB (preferred) or falls back to disk
    """
    try:
        from fastapi.responses import StreamingResponse
        import io
        
        # Determine filename - if path is empty or ends with /, try index.html
        filename = path.strip("/") if path and path.strip() != "/" else "index.html"
        
        # Try Cosmos DB first
        try:
            cosmos_manager = orchestrator_module.CosmosManager()
            
            # Query for the artifact in Cosmos DB
            query = f"""
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
                    # Determine content type
                    suffix = filename.lower()
                    content_types = {
                        '.html': 'text/html',
                        '.css': 'text/css',
                        '.js': 'application/javascript',
                        '.json': 'application/json',
                        '.png': 'image/png',
                        '.jpg': 'image/jpeg',
                        '.gif': 'image/gif',
                        '.svg': 'image/svg+xml',
                    }
                    
                    # Match by extension
                    content_type = 'application/octet-stream'
                    for ext, ctype in content_types.items():
                        if suffix.endswith(ext):
                            content_type = ctype
                            break
                    
                    # Return content as stream
                    return StreamingResponse(
                        iter([content.encode('utf-8') if isinstance(content, str) else content]),
                        media_type=content_type
                    )
        except Exception as cosmos_error:
            logger.warning(f"Could not fetch from Cosmos DB: {cosmos_error}, falling back to disk")
        
        # Fallback to disk
        generated_path = Path("./generated_code") / "frontend_engineer" / filename
        
        # Security check: ensure path doesn't escape the frontend_engineer directory
        base_path = Path("./generated_code") / "frontend_engineer"
        try:
            generated_path.resolve().relative_to(base_path.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")
        
        if not generated_path.exists():
            # Return a helpful HTML error message instead of 404
            logger.warning(f"Preview file not found: {filename} for project {project_id}")
            error_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Preview Not Available</title>
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }}
                    .container {{ max-width: 600px; margin: 50px auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); text-align: center; }}
                    h1 {{ color: #333; margin: 0 0 10px 0; }}
                    p {{ color: #666; margin: 10px 0; line-height: 1.6; }}
                    .code {{ background: #f0f0f0; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 12px; overflow-x: auto; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>⏳ Preview Not Available</h1>
                    <p>The generated code for this project hasn't been created yet.</p>
                    <p style="color: #999; font-size: 14px;">
                        This happens when:<br>
                        • Code generation is still in progress<br>
                        • The generation was cancelled<br>
                        • Files were deleted after generation
                    </p>
                    <p>Try generating a new project or refreshing the page.</p>
                </div>
            </body>
            </html>
            """
            return HTMLResponse(content=error_html, status_code=200)
        
        # Determine content type
        suffix = generated_path.suffix.lower()
        content_types = {
            '.html': 'text/html',
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.json': 'application/json',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.gif': 'image/gif',
            '.svg': 'image/svg+xml',
        }
        content_type = content_types.get(suffix, 'application/octet-stream')
        
        return FileResponse(generated_path, media_type=content_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Preview error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to serve preview")


class ExecuteRequest(BaseModel):
    """Legacy execute request"""
    project_id: str


@app.post("/execute", tags=["Compatibility"])
async def execute_project_compat(request: ExecuteRequest, background_tasks: BackgroundTasks):
    """
    Legacy execution endpoint (compatibility layer)
    Triggers code generation for existing or new project
    """
    try:
        project = project_manager.get_project(request.project_id)
        
        if not project:
            # Create placeholder project
            project_id = project_manager.create_project(
                name=f"Project {request.project_id[:8]}",
                intent="User initiated execution",
                description=None
            )
            project = project_manager.get_project(project_id)
        
        # Queue generation if not already running
        if project["status"] in [ProjectStatus.CREATED, ProjectStatus.FAILED]:
            project_manager.update_project_status(request.project_id, ProjectStatus.QUEUED, progress=5)
            background_tasks.add_task(
                OrchestrationService.generate_code,
                request.project_id,
                project
            )
        
        return {
            "message": "Execution started",
            "project_id": request.project_id,
            "status": "running"
        }
    except Exception as e:
        logger.error(f"Execute error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to start execution")


class TutorRequest(BaseModel):
    """Legacy tutor request"""
    project_id: str
    question: str
    context: Optional[Dict] = {}


@app.post("/tutor/ask", tags=["Compatibility"])
async def tutor_ask(request: TutorRequest):
    """
    Legacy Learning Mode tutor endpoint (compatibility layer)
    """
    # For now, return helpful explanations about the system
    question_lower = request.question.lower()
    
    response_text = "I'm the Agentic Nexus learning assistant. "
    
    if "explain" in question_lower or "what is" in question_lower:
        response_text += "The Agentic Nexus uses specialized AI agents to collaboratively build full-stack applications. Each agent has a specific role (Backend, Frontend, DevOps, QA) and they coordinate through a shared task ledger."
    elif "aeg" in question_lower or "graph" in question_lower:
        response_text += "The Agent Execution Graph (AEG) shows dependencies between agents. Agents with no dependencies run first, while dependent agents wait for their prerequisites to complete."
    elif "cost" in question_lower:
        response_text += "Cost tracking monitors token usage from AI calls. Each agent reports tokens consumed, which is converted to estimated cost based on the model pricing."
    else:
        response_text += "Ask me about: agent execution, the AEG (graph), cost tracking, or how the orchestration works."
    
    return {
        "response": response_text,
        "level": "overview",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/api/tunnel-status", tags=["Compatibility"])
async def tunnel_status():
    """
    Legacy tunnel status endpoint (compatibility layer)
    Returns localhost info for preview functionality
    """
    return {
        "status": "local",
        "tunnel_url": "http://localhost:5173",
        "port": 5173,
        "message": "Running on localhost (no tunnel configured)"
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

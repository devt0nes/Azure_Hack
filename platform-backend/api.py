"""
Day 4: FastAPI entrypoint with hot-reload support
Includes tunnel status endpoint for local preview
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import os

app = FastAPI(title="Platform A Backend", version="0.1.0")

# CORS configuration for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://frontend:5173",  # Docker network
        "*",  # Allow all for dev tunnels (restrict in production)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "Platform A Backend",
        "status": "running",
        "version": "0.1.0",
        "endpoints": ["/tunnel-status", "/clarify", "/aeg", "/execute", "/tutor/ask"],
    }


@app.get("/api/tunnel-status")
async def tunnel_status():
    """
    Day 4: Return tunnel status for preview iframe
    Checks for .tunnel-url file created by start-devtunnel.ps1
    """
    tunnel_file = Path(__file__).parent.parent / ".tunnel-url"

    if tunnel_file.exists():
        tunnel_url = tunnel_file.read_text().strip()
        return {
            "status": "active",
            "tunnel_url": tunnel_url,
            "port": 5173,
            "message": "Dev tunnel is active",
        }

    return {
        "status": "local",
        "tunnel_url": "http://localhost:5173",
        "port": 5173,
        "message": "Running on localhost (no tunnel)",
    }


# Placeholder endpoints for Days 1-3 integration
@app.post("/clarify")
async def clarify_intent(request: dict):
    """Director clarification endpoint (to be implemented)"""
    return {"message": "Clarify endpoint - implementation pending", "data": request}


@app.get("/aeg")
async def get_aeg(project_id: str = "default"):
    """Agent Execution Graph endpoint (to be implemented)"""
    return {
        "message": "AEG endpoint - implementation pending",
        "project_id": project_id,
    }


@app.post("/execute")
async def execute_project(request: dict):
    """Project execution endpoint (to be implemented)"""
    return {"message": "Execute endpoint - implementation pending", "data": request}


@app.post("/tutor/ask")
async def tutor_ask(request: dict):
    """Learning Mode tutor endpoint (to be implemented)"""
    return {
        "message": "Tutor endpoint - implementation pending",
        "question": request.get("question"),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api:app", host="0.0.0.0", port=8000, reload=True, log_level="info"
    )



import os
import json
import uuid
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys

sys.path.append(r"C:\Users\hritp\OneDrive\Desktop\Microsoft Hackathon\C(men)")
from shared.clients import call_gpt4o
from shared.cosmos_client import client

load_dotenv_path = os.path.join(os.path.dirname(__file__), "../../../.env")
from dotenv import load_dotenv
load_dotenv(load_dotenv_path)

app = FastAPI(title="Learning Mode Agent")

# ─────────────────────────────────────────────
# COSMOS DB
# ─────────────────────────────────────────────

learning_db = client.get_database_client("nexus_learning")
sessions_container = learning_db.get_container_client("sessions")

# ─────────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────────

class ProjectContext(BaseModel):
    project_id: str
    app_name: str
    description: str
    files: Optional[dict[str, str]] = {}      # filename -> file content
    task_ledger: Optional[dict] = {}           # task ledger JSON
    aeg: Optional[dict] = {}                   # agent execution graph JSON
    qa_results: Optional[dict] = {}            # QA results JSON

class ExplainProjectRequest(BaseModel):
    project_id: str
    context: ProjectContext
    depth: str  # "surface", "intermediate", "deep"

class ExplainFileRequest(BaseModel):
    project_id: str
    context: ProjectContext
    filename: str
    file_content: str
    depth: str  # "surface", "intermediate", "deep"

class QuestionRequest(BaseModel):
    project_id: str
    context: ProjectContext
    question: str
    conversation_history: Optional[list[dict]] = []  # previous Q&A pairs

# ─────────────────────────────────────────────
# DEPTH INSTRUCTIONS
# ─────────────────────────────────────────────

DEPTH_INSTRUCTIONS = {
    "surface": """
    Explain in plain English as if talking to a non-technical person.
    Use simple analogies. No code. No jargon.
    Focus on WHAT was built and WHY, not HOW.
    Keep it to 3-5 sentences.
    """,

    "intermediate": """
    Explain to someone with basic programming knowledge.
    Describe HOW each component works and the key design decisions made.
    You can reference code concepts but don't do line-by-line analysis.
    Use bullet points where helpful.
    Keep it to 1-2 paragraphs.
    """,

    "deep": """
    Explain to an experienced developer.
    Do a thorough technical walkthrough.
    Reference specific functions, classes, and architectural patterns.
    Discuss trade-offs, potential improvements, and edge cases.
    Be as detailed as needed.
    """
}

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def build_context_prompt(context: ProjectContext) -> str:
    parts = []
    parts.append(f"Project: {context.app_name}")
    parts.append(f"Description: {context.description}")

    if context.task_ledger:
        parts.append(f"Task Ledger: {json.dumps(context.task_ledger, indent=2)[:1000]}")

    if context.aeg:
        parts.append(f"Agent Execution Graph: {json.dumps(context.aeg, indent=2)[:1000]}")

    if context.qa_results:
        parts.append(f"QA Results: {json.dumps(context.qa_results, indent=2)[:500]}")

    if context.files:
        parts.append("Generated Files:")
        for filename, content in list(context.files.items())[:5]:
            parts.append(f"\n--- {filename} ---\n{content[:500]}")

    return "\n\n".join(parts)

def save_session(project_id: str, session_type: str, input_data: dict, response: str):
    doc = {
        "id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "project_id": project_id,
        "session_type": session_type,
        "input": input_data,
        "response": response,
        "timestamp": datetime.utcnow().isoformat()
    }
    sessions_container.create_item(body=doc)
    return doc["id"]

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "agent": "learning-mode"}

@app.post("/explain-project")
def explain_project(request: ExplainProjectRequest):
    try:
        depth_instruction = DEPTH_INSTRUCTIONS.get(request.depth, DEPTH_INSTRUCTIONS["surface"])
        context_prompt = build_context_prompt(request.context)

        prompt = f"""
        You are an expert code tutor for the Agentic Nexus platform.
        You have full context of a software project that was built by AI agents.

        PROJECT CONTEXT:
        {context_prompt}

        DEPTH LEVEL: {request.depth.upper()}
        {depth_instruction}

        Explain this project to the user.
        """

        response = call_gpt4o(prompt)
        save_session(request.project_id, "explain_project", {"depth": request.depth}, response)

        return {
            "status": "success",
            "project_id": request.project_id,
            "depth": request.depth,
            "explanation": response
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/explain-file")
def explain_file(request: ExplainFileRequest):
    try:
        depth_instruction = DEPTH_INSTRUCTIONS.get(request.depth, DEPTH_INSTRUCTIONS["surface"])
        context_prompt = build_context_prompt(request.context)

        prompt = f"""
        You are an expert code tutor for the Agentic Nexus platform.
        You have full context of a software project that was built by AI agents.

        PROJECT CONTEXT:
        {context_prompt}

        FILE TO EXPLAIN: {request.filename}
        FILE CONTENT:
        {request.file_content}

        DEPTH LEVEL: {request.depth.upper()}
        {depth_instruction}

        Explain this specific file to the user.
        Focus on what this file does, why it exists, and how it fits into the overall project.
        """

        response = call_gpt4o(prompt)
        save_session(
            request.project_id,
            "explain_file",
            {"filename": request.filename, "depth": request.depth},
            response
        )

        return {
            "status": "success",
            "project_id": request.project_id,
            "filename": request.filename,
            "depth": request.depth,
            "explanation": response
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ask")
def ask_question(request: QuestionRequest):
    try:
        context_prompt = build_context_prompt(request.context)

        # Build conversation history string
        history = ""
        if request.conversation_history:
            history = "\n\nPREVIOUS CONVERSATION:\n"
            for turn in request.conversation_history[-5:]:  # last 5 turns only
                history += f"User: {turn.get('question', '')}\n"
                history += f"Tutor: {turn.get('answer', '')}\n"

        prompt = f"""
        You are an expert code tutor for the Agentic Nexus platform.
        You have full context of a software project that was built by AI agents.
        Answer the user's question with direct reference to the project's actual code and decisions.
        Do not give generic answers — always tie your answer back to this specific project.

        PROJECT CONTEXT:
        {context_prompt}
        {history}

        USER QUESTION: {request.question}

        Answer clearly and helpfully.
        """

        response = call_gpt4o(prompt)
        save_session(
            request.project_id,
            "freeform_question",
            {"question": request.question},
            response
        )

        return {
            "status": "success",
            "project_id": request.project_id,
            "question": request.question,
            "answer": response
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{project_id}")
def get_sessions(project_id: str):
    try:
        query = f"SELECT * FROM c WHERE c.project_id = '{project_id}' ORDER BY c.timestamp DESC"
        sessions = list(sessions_container.query_items(query=query, enable_cross_partition_query=True))
        return {
            "status": "success",
            "project_id": project_id,
            "sessions": sessions
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
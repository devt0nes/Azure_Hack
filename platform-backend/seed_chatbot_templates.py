"""
seed_chatbot_templates.py  —  Seed the ChatbotTemplates Cosmos DB container
============================================================================

Pushes the chatbot backend template into the ChatbotTemplates container.
The container is created automatically if it does not already exist.

Usage:
    python seed_chatbot_templates.py

ENV VARS (same as the rest of the project):
    COSMOS_CONNECTION_STR   full Cosmos DB connection string
    COSMOS_DB_NAME          database name  (default: agentic-nexus-db)
    COSMOS_CHATBOT_CONTAINER container name (default: ChatbotTemplates)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=False)

try:
    from azure.cosmos import CosmosClient, PartitionKey, exceptions as cosmos_exceptions
except ImportError:
    print("ERROR: azure-cosmos SDK not installed. Run: pip install azure-cosmos")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Template document — chatbot backend
# ---------------------------------------------------------------------------

CHATBOT_BACKEND_TEMPLATE = {
    "id": "chatbot-backend-v1",
    "name": "Chatbot Backend API",
    "description": (
        "Full FastAPI chatbot backend with Azure OpenAI integration. "
        "Provides /chat and /chat/stream endpoints with conversation history, "
        "system prompt configuration, and error handling. "
        "Drop-in ready for any project that needs an AI chat feature."
    ),
    "category": "chatbot",
    "framework": "fastapi",
    "tags": ["chatbot", "azure-openai", "streaming", "fastapi", "backend", "api"],
    "file_extension": ".py",
    "usage_count": 0,
    "code": '''\
"""
chatbot_api.py  —  Chatbot Backend API
=======================================
FastAPI router providing two endpoints:

    POST /chat          — single-turn chat (full response)
    POST /chat/stream   — streaming chat (SSE, token-by-token)

Requires env vars:
    AZURE_OPENAI_ENDPOINT
    AZURE_OPENAI_KEY
    AZURE_OPENAI_API_VERSION
    AZURE_MODEL_DEPLOYMENT
"""

from __future__ import annotations

import os
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai import AzureOpenAI
from pydantic import BaseModel

load_dotenv()

router = APIRouter(prefix="/chat", tags=["chatbot"])

# ---------------------------------------------------------------------------
# Azure OpenAI client
# ---------------------------------------------------------------------------

def _build_openai_client() -> AzureOpenAI:
    endpoint   = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    api_key    = os.getenv("AZURE_OPENAI_KEY", "").strip()
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview").strip()
    if not endpoint or not api_key:
        raise ValueError(
            "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY must be set."
        )
    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
    )


_client: Optional[AzureOpenAI] = None


def get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = _build_openai_client()
    return _client


DEPLOYMENT = os.getenv("AZURE_MODEL_DEPLOYMENT", "gpt-4.1")

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful AI assistant. "
    "Answer questions clearly and concisely."
)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str           # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    system_prompt: Optional[str] = None
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1024


class ChatResponse(BaseModel):
    reply: str
    total_tokens: int


# ---------------------------------------------------------------------------
# POST /chat  —  single-turn, full response
# ---------------------------------------------------------------------------

@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Send a list of messages and receive a full AI reply.

    The first entry in `messages` should have role="user".
    Include previous turns to maintain conversation context.
    """
    system_prompt = request.system_prompt or DEFAULT_SYSTEM_PROMPT

    openai_messages = [{"role": "system", "content": system_prompt}]
    for msg in request.messages:
        if msg.role not in ("user", "assistant", "system"):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid role '{msg.role}'. Must be user, assistant, or system.",
            )
        openai_messages.append({"role": msg.role, "content": msg.content})

    try:
        response = get_client().chat.completions.create(
            model=DEPLOYMENT,
            messages=openai_messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Azure OpenAI error: {exc}") from exc

    reply = response.choices[0].message.content or ""
    total_tokens = response.usage.total_tokens if response.usage else 0

    return ChatResponse(reply=reply, total_tokens=total_tokens)


# ---------------------------------------------------------------------------
# POST /chat/stream  —  streaming response (Server-Sent Events)
# ---------------------------------------------------------------------------

@router.post("/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """
    Stream the AI reply token-by-token using Server-Sent Events.

    Each chunk is delivered as:
        data: <token>\\n\\n

    The stream ends with:
        data: [DONE]\\n\\n
    """
    system_prompt = request.system_prompt or DEFAULT_SYSTEM_PROMPT

    openai_messages = [{"role": "system", "content": system_prompt}]
    for msg in request.messages:
        openai_messages.append({"role": msg.role, "content": msg.content})

    async def token_generator():
        try:
            stream = get_client().chat.completions.create(
                model=DEPLOYMENT,
                messages=openai_messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield f"data: {delta.content}\\n\\n"
            yield "data: [DONE]\\n\\n"
        except Exception as exc:
            yield f"data: ERROR: {exc}\\n\\n"

    return StreamingResponse(token_generator(), media_type="text/event-stream")
''',
}

# ---------------------------------------------------------------------------
# Cosmos helpers
# ---------------------------------------------------------------------------

def _get_container():
    conn_str   = os.getenv("COSMOS_CONNECTION_STR", "").strip()
    db_name    = os.getenv("COSMOS_DB_NAME", "agentic-nexus-db").strip() or "agentic-nexus-db"
    ctr_name   = os.getenv("COSMOS_CHATBOT_CONTAINER", "ChatbotTemplates").strip() or "ChatbotTemplates"

    if not conn_str:
        raise ValueError("COSMOS_CONNECTION_STR is not set.")

    client   = CosmosClient.from_connection_string(conn_str)
    database = client.create_database_if_not_exists(id=db_name)

    container = database.create_container_if_not_exists(
        id=ctr_name,
        partition_key=PartitionKey(path="/id"),
        offer_throughput=400,
    )
    return container, ctr_name


def upsert_template(container, doc: dict) -> None:
    container.upsert_item(body=doc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Chatbot Template Seeder")
    print("=" * 60)

    try:
        container, ctr_name = _get_container()
        print(f"✓ Connected — container: {ctr_name}")
    except Exception as exc:
        print(f"✗ Could not connect to Cosmos DB: {exc}")
        sys.exit(1)

    templates = [CHATBOT_BACKEND_TEMPLATE]

    for tmpl in templates:
        try:
            existing = None
            try:
                existing = container.read_item(
                    item=tmpl["id"], partition_key=tmpl["id"]
                )
            except cosmos_exceptions.CosmosResourceNotFoundError:
                pass

            if existing:
                # Preserve the existing usage_count
                tmpl["usage_count"] = existing.get("usage_count", 0)
                container.replace_item(item=tmpl["id"], body=tmpl)
                action = "updated"
            else:
                container.create_item(body=tmpl)
                action = "created"

            print(f"  ✓ [{action}] {tmpl['id']} — {tmpl['name']}")
        except Exception as exc:
            print(f"  ✗ Failed to upsert '{tmpl['id']}': {exc}")

    print()
    print(f"Done. {len(templates)} template(s) seeded into '{ctr_name}'.")


if __name__ == "__main__":
    main()

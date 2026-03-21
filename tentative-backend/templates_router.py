"""
templates_router.py
--------------------
FastAPI router — Template Library for reusable frontend code snippets.

Routes:
  GET  /api/templates                    → full catalog (filters: ?category=, ?framework=, ?tag=)
  GET  /api/templates/{template_id}      → single template with full code
  POST /api/templates                    → save a user/agent-created template
  DELETE /api/templates/{template_id}    → delete a custom template (built-ins protected)

Public helpers (imported by app.py and main.py):
  seed_template_catalog()                — call once on startup
  get_templates_for_agent(role, tags)    — returns relevant templates for injection into agent prompt
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from dotenv import load_dotenv

# ── path setup ────────────────────────────────────────────────────────────────
_BACKEND_DIR  = Path(__file__).resolve().parent
_REPO_ROOT    = _BACKEND_DIR.parent
_SHARED_DIR   = _REPO_ROOT / "shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
_LOCAL_SHARED = _BACKEND_DIR / "shared"
if str(_LOCAL_SHARED) not in sys.path:
    sys.path.insert(0, str(_LOCAL_SHARED))

from template_catalog import TEMPLATE_CATALOG

load_dotenv(dotenv_path=_BACKEND_DIR / ".env")

logger = logging.getLogger(__name__)

# ── Cosmos setup ─────────────────────────────────────────────────────────────
from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos import exceptions as CosmosExceptions

COSMOS_CONNECTION_STR       = os.getenv("COSMOS_CONNECTION_STR")
DATABASE_NAME               = os.getenv("DATABASE_NAME", "agentic-nexus-db")
TEMPLATE_LIBRARY_CONTAINER  = "TemplateLibrary"

BUILTIN_TEMPLATE_IDS = {t["template_id"] for t in TEMPLATE_CATALOG}


def _get_container():
    """Return the TemplateLibrary Cosmos container, creating it if needed."""
    if not COSMOS_CONNECTION_STR:
        return None
    try:
        client = CosmosClient.from_connection_string(COSMOS_CONNECTION_STR)
        db     = client.create_database_if_not_exists(id=DATABASE_NAME)
        return db.create_container_if_not_exists(
            id=TEMPLATE_LIBRARY_CONTAINER,
            partition_key=PartitionKey(path="/template_id"),
        )
    except Exception as e:
        logger.warning(f"⚠️  TemplateLibrary container unavailable: {e}")
        return None


# ── Seed ─────────────────────────────────────────────────────────────────────
def seed_template_catalog():
    """
    Upserts all TEMPLATE_CATALOG entries into Cosmos DB TemplateLibrary container.
    Safe to call multiple times (idempotent). Called from app.py startup_event().
    """
    container = _get_container()
    if container is None:
        logger.warning("⚠️  Skipping TemplateLibrary seed — Cosmos DB unavailable.")
        return
    seeded = 0
    for template in TEMPLATE_CATALOG:
        try:
            container.upsert_item(template)
            seeded += 1
        except Exception as e:
            logger.warning(f"⚠️  Could not seed template {template['template_id']}: {e}")
    logger.info(f"✅ TemplateLibrary seeded: {seeded}/{len(TEMPLATE_CATALOG)} templates")


# ── Public helper used by main.py (agent context injection) ──────────────────
def get_templates_for_agent(role: str, tags: List[str] = None) -> List[dict]:
    """
    Returns templates relevant to a given agent role and optional tag list.
    Used by main.py to inject template context into the frontend agent's prompt.

    Logic:
    - frontend_engineer gets all templates
    - other roles get nothing (templates are frontend-only)
    - further filtered by tags if provided
    """
    if "frontend" not in role.lower():
        return []

    templates = _read_catalog()
    if not templates:
        templates = TEMPLATE_CATALOG

    if tags:
        tags_lower = [t.lower() for t in tags]
        templates = [
            t for t in templates
            if any(tag in [x.lower() for x in t.get("tags", [])] for tag in tags_lower)
        ]

    # Return without full code for context injection — code fetched separately
    return [
        {
            "template_id": t["template_id"],
            "name":        t["name"],
            "category":    t["category"],
            "description": t["description"],
            "tags":        t.get("tags", []),
        }
        for t in templates
    ]


def get_template_code(template_id: str) -> Optional[str]:
    """Fetch the full code for a single template. Used by agent at generation time."""
    container = _get_container()
    if container:
        try:
            item = container.read_item(item=template_id, partition_key=template_id)
            return item.get("code")
        except Exception:
            pass
    # Static fallback
    for t in TEMPLATE_CATALOG:
        if t["template_id"] == template_id:
            return t.get("code")
    return None


# ── Internal helpers ─────────────────────────────────────────────────────────
def _read_catalog() -> List[dict]:
    """Read all templates from Cosmos, filtering to real template entries only."""
    container = _get_container()
    if container is None:
        return []
    try:
        items = list(container.read_all_items())
        return [i for i in items if i.get("type") == "template_catalog_entry"]
    except Exception as e:
        logger.warning(f"⚠️  Could not read TemplateLibrary: {e}")
        return []


def _find_static_template(template_id: str) -> Optional[dict]:
    for t in TEMPLATE_CATALOG:
        if t["template_id"] == template_id:
            return t
    return None


def _get_template_by_id(template_id: str) -> Optional[dict]:
    container = _get_container()
    if container:
        try:
            return container.read_item(item=template_id, partition_key=template_id)
        except Exception:
            pass
    return _find_static_template(template_id)


def _enrich(template: dict) -> dict:
    """Add display fields without exposing the full code in list views."""
    return {
        **template,
        "has_code": bool(template.get("code")),
    }


def _enrich_with_code(template: dict) -> dict:
    """Full template including code — for single-item endpoints only."""
    return _enrich(template)


# ── Router ───────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/templates", tags=["Template Library"])


# ── Pydantic models ───────────────────────────────────────────────────────────
class CreateTemplateRequest(BaseModel):
    name:        str
    category:    str
    framework:   str = "react"
    tags:        List[str] = []
    description: str
    code:        str
    dependencies: List[str] = []


class CreateTemplateResponse(BaseModel):
    status:      str
    template_id: str
    template:    dict


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", summary="List all templates (no code in list view)")
def list_templates(
    category:  Optional[str] = Query(None, description="Filter by category e.g. navigation, layout, auth"),
    framework: Optional[str] = Query(None, description="Filter by framework e.g. react, vue"),
    tag:       Optional[str] = Query(None, description="Filter by tag (case-insensitive)"),
):
    """
    Returns all templates from Cosmos DB (falls back to static catalog).
    Code field is excluded from list view — fetch a single template to get code.
    """
    cosmos_results = _read_catalog()
    if cosmos_results:
        seen, unique = set(), []
        for t in cosmos_results:
            key = t.get("template_id")
            if key and key not in seen:
                seen.add(key)
                unique.append(t)
        results = unique
        source  = "cosmos"
    else:
        results = TEMPLATE_CATALOG
        source  = "static"

    if category:
        results = [t for t in results if t.get("category", "").lower() == category.lower()]
    if framework:
        results = [t for t in results if t.get("framework", "").lower() == framework.lower()]
    if tag:
        results = [t for t in results if tag.lower() in [x.lower() for x in t.get("tags", [])]]

    # Strip code from list responses to keep payloads small
    stripped = [{k: v for k, v in _enrich(t).items() if k != "code"} for t in results]

    return {
        "templates": stripped,
        "count":     len(stripped),
        "source":    source,
    }


@router.get("/categories", summary="List all available categories")
def list_categories():
    """Returns all unique categories and frameworks in the catalog."""
    results    = _read_catalog() or TEMPLATE_CATALOG
    categories = sorted({t.get("category", "") for t in results if t.get("category")})
    frameworks = sorted({t.get("framework", "") for t in results if t.get("framework")})
    all_tags   = sorted({tag for t in results for tag in t.get("tags", [])})
    return {"categories": categories, "frameworks": frameworks, "tags": all_tags}


@router.get("/{template_id}", summary="Get a single template with full code")
def get_template(template_id: str):
    """Returns the full template including the code field."""
    template = _get_template_by_id(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    # Increment usage count in Cosmos (best-effort, non-blocking)
    container = _get_container()
    if container:
        try:
            doc = container.read_item(item=template_id, partition_key=template_id)
            doc["usage_count"] = doc.get("usage_count", 0) + 1
            container.upsert_item(doc)
            template = doc
        except Exception:
            pass
    return _enrich_with_code(template)


@router.post("", response_model=CreateTemplateResponse, summary="Create a custom template")
def create_template(body: CreateTemplateRequest):
    """
    Saves a user or agent-created template to Cosmos DB.
    Immediately available to all agents and visible in the UI.
    """
    if not body.name or not body.code:
        raise HTTPException(status_code=400, detail="name and code are required.")

    now  = datetime.now(timezone.utc).isoformat()
    slug = body.name.lower().strip().replace(" ", "-")
    # Make ID unique with timestamp suffix
    template_id = f"custom-{slug}-{int(datetime.now(timezone.utc).timestamp())}"

    doc = {
        "id":           template_id,
        "template_id":  template_id,
        "type":         "template_catalog_entry",
        "name":         body.name,
        "category":     body.category,
        "framework":    body.framework,
        "tags":         body.tags,
        "description":  body.description,
        "code":         body.code,
        "dependencies": body.dependencies,
        "usage_count":  0,
        "created_by":   "user",
        "custom":       True,
        "created_at":   now,
        "updated_at":   now,
    }

    container = _get_container()
    if container is None:
        raise HTTPException(status_code=503, detail="Cosmos DB unavailable — cannot save template.")

    try:
        container.upsert_item(doc)
        logger.info(f"✅ Custom template created: {template_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save template: {str(e)}")

    return CreateTemplateResponse(
        status="created",
        template_id=template_id,
        template=_enrich_with_code(doc),
    )


@router.delete("/{template_id}", summary="Delete a custom template")
def delete_template(template_id: str):
    """
    Deletes a custom template. Built-in templates cannot be deleted.
    """
    if template_id in BUILTIN_TEMPLATE_IDS:
        raise HTTPException(status_code=403, detail="Built-in templates cannot be deleted.")

    container = _get_container()
    if container is None:
        raise HTTPException(status_code=503, detail="Cosmos DB unavailable.")

    try:
        container.read_item(item=template_id, partition_key=template_id)
    except CosmosExceptions.CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")

    try:
        container.delete_item(item=template_id, partition_key=template_id)
        logger.info(f"🗑️  Template deleted: {template_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete template: {str(e)}")

    return {"status": "deleted", "template_id": template_id}

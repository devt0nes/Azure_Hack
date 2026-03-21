"""
Canonical Template Catalog for Cosmos DB.

This module is the single source of truth for the template catalog schema used by:
- backend seeding into the TemplateLibrary container
- frontend template browser rendering
- agent code injection for consistent UI patterns
"""

from datetime import datetime, timezone
from typing import List, Dict, Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_builtin_template_catalog() -> List[Dict[str, Any]]:
    """Build the catalog of built-in code templates."""
    now = _utc_now_iso()
    builtins = [
        {
            "template_id": "react-form-v1",
            "name": "React Form Component",
            "category": "frontend",
            "framework": "react",
            "description": "Reusable React form component with validation",
            "tags": ["react", "form", "component"],
            "code": "// React form component\nexport default function FormComponent() { return <form></form>; }",
            "custom": False,
            "source": "builtin",
            "created_at": now,
            "updated_at": now,
        },
        {
            "template_id": "fastapi-endpoint-v1",
            "name": "FastAPI Endpoint",
            "category": "backend",
            "framework": "fastapi",
            "description": "Basic FastAPI endpoint with dependency injection",
            "tags": ["fastapi", "api", "endpoint"],
            "code": "@app.get('/api/endpoint')\nasync def get_endpoint(db: Depends(get_db)):\n    return {'status': 'ok'}",
            "custom": False,
            "source": "builtin",
            "created_at": now,
            "updated_at": now,
        },
    ]
    return builtins


TEMPLATE_CATALOG = build_builtin_template_catalog()

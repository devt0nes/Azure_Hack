"""
Canonical Agent Catalog documents for Cosmos DB.

This module is the single source of truth for the catalog schema used by:
- backend seeding into the AgentCatalog container
- frontend marketplace rendering
- future custom agent creation

The key design goal is that built-in and future user-created agents share the
same storage contract. Built-ins are simply catalog entries with `custom=False`
and `source="builtin"`.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List
import re


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify_role_key(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", (value or "").strip().lower())
    return cleaned.strip("_")


def normalize_agent_document(agent: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a catalog document so it is safe to persist in Cosmos DB and ready
    for future custom-agent support.

    Important compatibility choices:
    - `id` and `agent_id` are kept identical so Cosmos item lookup is simple.
    - legacy top-level fields (`tags`, `mcp_tools`, `specialties`, etc.) are
      preserved for existing frontend/backend consumers.
    - richer nested metadata is added for future expansion.
    """

    raw = deepcopy(agent)
    now = raw.get("updated_at") or raw.get("created_at") or _utc_now_iso()

    role = raw.get("role", "").strip()
    role_key = raw.get("role_key") or _slugify_role_key(role)
    agent_id = raw.get("agent_id") or raw.get("id") or f"{role_key}-v1"
    custom = bool(raw.get("custom", False))
    source = raw.get("source") or ("custom" if custom else "builtin")
    creator_name = raw.get("creator_name") or raw.get("creator") or ("Marketplace User" if custom else "Agentic Nexus")
    system_prompt = raw.get("system_prompt")

    specialties = list(raw.get("specialties", []))
    dependencies = list(raw.get("dependencies", []))
    tags = list(raw.get("tags", []))
    mcp_tools = list(raw.get("mcp_tools", []))
    added_to_projects = list(raw.get("added_to_projects", []))

    normalized = {
        "id": agent_id,
        "type": "agent_catalog_entry",
        "agent_id": agent_id,
        "role": role,
        "display_name": raw.get("display_name") or role,
        "role_key": role_key,
        "tier": raw.get("tier", 2),
        "description": raw.get("description", ""),
        "system_prompt": system_prompt,
        "custom": custom,
        "source": source,
        "status": raw.get("status", "available"),
        "visibility": raw.get("visibility", "workspace"),
        "creator": creator_name,
        "creator_id": raw.get("creator_id") or ("system" if not custom else None),
        "version": int(raw.get("version", 1)),
        "model_tier": raw.get("model_tier", "intermediate"),
        "model_config": {
            "tier": raw.get("model_tier", "intermediate"),
            "deployment": raw.get("model_deployment"),
        },
        "specialties": specialties,
        "dependencies": dependencies,
        "mcp_tools": mcp_tools,
        "tags": tags,
        "reputation_score": float(raw.get("reputation_score", 0.0)),
        "added_to_projects": added_to_projects,
        "last_used": raw.get("last_used"),
        "created_at": raw.get("created_at") or now,
        "updated_at": raw.get("updated_at") or now,
        "capabilities": {
            "specialties": specialties,
            "dependencies": dependencies,
            "mcp_tools": mcp_tools,
            "tags": tags,
        },
        "provenance": {
            "seeded_from": raw.get("seeded_from") or ("shared.agent_catalog" if not custom else "marketplace"),
            "seed_version": raw.get("seed_version") or "2026-03-20",
        },
    }

    return normalized


def build_builtin_agent_catalog() -> List[Dict[str, Any]]:
    now = _utc_now_iso()
    builtins = [
        {
            "agent_id": "backend-engineer-v1",
            "role": "Backend Engineer",
            "role_key": "backend_engineer",
            "tier": 1,
            "description": "Builds REST APIs, microservices, and authentication flows. Outputs OpenAPI contracts consumed by the frontend.",
            "model_tier": "intermediate",
            "specialties": ["azure_infrastructure", "microservices", "api_development"],
            "dependencies": ["database_architect", "api_designer", "security_engineer"],
            "mcp_tools": ["github-file-write", "code-sandbox", "azure-sql"],
            "tags": ["api", "auth", "microservices"],
            "reputation_score": 0.87,
            "custom": False,
            "source": "builtin",
            "creator": "Agentic Nexus",
            "created_at": now,
            "updated_at": now,
        },
        {
            "agent_id": "frontend-engineer-v1",
            "role": "Frontend Engineer",
            "role_key": "frontend_engineer",
            "tier": 1,
            "description": "Builds React/Next.js components with accessibility compliance and integrates backend contracts into polished UI flows.",
            "model_tier": "intermediate",
            "specialties": ["react_frontend", "angular_frontend"],
            "dependencies": ["backend_engineer", "api_designer"],
            "mcp_tools": ["github-file-write", "code-sandbox"],
            "tags": ["react", "ui", "nextjs"],
            "reputation_score": 0.91,
            "custom": False,
            "source": "builtin",
            "creator": "Agentic Nexus",
            "created_at": now,
            "updated_at": now,
        },
        {
            "agent_id": "database-architect-v1",
            "role": "Database Architect",
            "role_key": "database_architect",
            "tier": 1,
            "description": "Designs schemas, indexing strategy, and migration scripts for relational and document databases.",
            "model_tier": "complex",
            "specialties": ["database_design", "azure_infrastructure"],
            "dependencies": ["solution_architect"],
            "mcp_tools": ["azure-sql", "cosmos-db", "github-file-write"],
            "tags": ["schema", "migrations", "indexing"],
            "reputation_score": 0.83,
            "custom": False,
            "source": "builtin",
            "creator": "Agentic Nexus",
            "created_at": now,
            "updated_at": now,
        },
        {
            "agent_id": "security-engineer-v1",
            "role": "Security Engineer",
            "role_key": "security_engineer",
            "tier": 2,
            "description": "Performs security review, threat modeling, auth design, and compliance checks across generated systems.",
            "model_tier": "complex",
            "specialties": ["security_compliance", "azure_infrastructure"],
            "dependencies": ["solution_architect"],
            "mcp_tools": ["github-read", "code-sandbox"],
            "tags": ["owasp", "security", "iam"],
            "reputation_score": 0.95,
            "custom": False,
            "source": "builtin",
            "creator": "Agentic Nexus",
            "created_at": now,
            "updated_at": now,
        },
        {
            "agent_id": "qa-engineer-v1",
            "role": "QA Engineer",
            "role_key": "qa_engineer",
            "tier": 2,
            "description": "Generates unit, integration, and end-to-end tests and helps validate production readiness.",
            "model_tier": "intermediate",
            "specialties": ["testing_automation"],
            "dependencies": ["backend_engineer", "frontend_engineer"],
            "mcp_tools": ["code-sandbox", "github-file-write"],
            "tags": ["testing", "coverage", "e2e"],
            "reputation_score": 0.89,
            "custom": False,
            "source": "builtin",
            "creator": "Agentic Nexus",
            "created_at": now,
            "updated_at": now,
        },
        {
            "agent_id": "devops-engineer-v1",
            "role": "DevOps Engineer",
            "role_key": "devops_engineer",
            "tier": 2,
            "description": "Generates Dockerfiles, IaC, deployment pipelines, and operational workflows for Azure environments.",
            "model_tier": "intermediate",
            "specialties": ["devops_ci_cd", "azure_infrastructure"],
            "dependencies": ["backend_engineer", "database_architect", "security_engineer"],
            "mcp_tools": ["github-file-write", "azure-devops", "acr"],
            "tags": ["docker", "bicep", "ci-cd"],
            "reputation_score": 0.86,
            "custom": False,
            "source": "builtin",
            "creator": "Agentic Nexus",
            "created_at": now,
            "updated_at": now,
        },
        {
            "agent_id": "solution-architect-v1",
            "role": "Solution Architect",
            "role_key": "solution_architect",
            "tier": 2,
            "description": "Designs the overall system architecture, selects stack boundaries, and defines the execution plan other agents follow.",
            "model_tier": "complex",
            "specialties": ["azure_infrastructure", "microservices"],
            "dependencies": [],
            "mcp_tools": ["file_write", "diagram_gen"],
            "tags": ["architecture", "planning", "system-design"],
            "reputation_score": 0.94,
            "custom": False,
            "source": "builtin",
            "creator": "Agentic Nexus",
            "created_at": now,
            "updated_at": now,
        },
        {
            "agent_id": "api-designer-v1",
            "role": "API Designer",
            "role_key": "api_designer",
            "tier": 2,
            "description": "Produces OpenAPI and interface contracts, versioning strategy, and endpoint design before implementation starts.",
            "model_tier": "intermediate",
            "specialties": ["api_development"],
            "dependencies": ["solution_architect"],
            "mcp_tools": ["file_write", "code_exec"],
            "tags": ["api", "openapi", "swagger", "rest"],
            "reputation_score": 0.80,
            "custom": False,
            "source": "builtin",
            "creator": "Agentic Nexus",
            "created_at": now,
            "updated_at": now,
        },
    ]
    return [normalize_agent_document(agent) for agent in builtins]


AGENT_CATALOG = build_builtin_agent_catalog()

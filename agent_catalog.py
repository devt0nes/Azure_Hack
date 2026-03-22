"""
agent_catalog.py
----------------
Standalone agent catalog — no shared/ dependency.

AGENT_CATALOG: Add your agents here. Each entry is a dict with at minimum:
  agent_id, role, role_key, tier, model_tier, tags, description,
  mcp_tools, reputation_score, source, custom

normalize_agent_document: ensures every agent doc has all expected fields.
build_builtin_agent_catalog: returns the catalog list (used by seeding logic).
"""

from __future__ import annotations
from typing import List


# ── Add your agents here ──────────────────────────────────────────────────────
AGENT_CATALOG: List[dict] = [
    # Example shape — fill in your real agents:
    # {
    #     "id":               "backend_engineer",
    #     "agent_id":         "backend_engineer",
    #     "type":             "agent_catalog_entry",
    #     "role":             "Backend Engineer",
    #     "role_key":         "backend_engineer",
    #     "tier":             1,
    #     "model_tier":       "complex",
    #     "tags":             ["backend", "api", "python"],
    #     "description":      "Builds FastAPI/Node services and REST APIs.",
    #     "mcp_tools":        ["code_executor", "file_writer"],
    #     "reputation_score": 0.5,
    #     "source":           "builtin",
    #     "custom":           False,
    #     "status":           "available",
    #     "added_to_projects": [],
    # },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

_DEFAULTS = {
    "id":                "",
    "agent_id":          "",
    "type":              "agent_catalog_entry",
    "role":              "",
    "role_key":          "",
    "tier":              1,
    "model_tier":        "complex",
    "tags":              [],
    "description":       "",
    "mcp_tools":         [],
    "reputation_score":  0.5,
    "source":            "builtin",
    "custom":            False,
    "status":            "available",
    "added_to_projects": [],
}


def normalize_agent_document(agent: dict) -> dict:
    """
    Ensures every agent document has all expected fields.
    Missing fields are filled from _DEFAULTS.
    Also guarantees agent_id == id for consistency.
    """
    normalized = {**_DEFAULTS, **agent}
    if not normalized["agent_id"] and normalized["id"]:
        normalized["agent_id"] = normalized["id"]
    if not normalized["id"] and normalized["agent_id"]:
        normalized["id"] = normalized["agent_id"]
    return normalized


def build_builtin_agent_catalog() -> List[dict]:
    """Returns the full builtin catalog (used by seeding logic at startup)."""
    return [normalize_agent_document(a) for a in AGENT_CATALOG]
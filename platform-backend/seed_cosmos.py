"""
seed_cosmos.py
──────────────
Inserts (or upserts) the 8 canonical agents into the CosmosDB AgentLibrary
container.

Usage:
    python seed_cosmos.py

Reads credentials from the .env file (or environment). Requires:
    COSMOS_CONNECTION_STR   – the primary connection string from the Azure portal
    AGENT_LIBRARY_DB_NAME   – default: agent-nexus
    AGENT_LIBRARY_CONTAINER – default: AgentLibrary

The container must already exist with partition key  /agent_id
(which you set when creating the CosmosDB account).
"""

import os
from dotenv import load_dotenv
from azure.cosmos import CosmosClient, PartitionKey, exceptions

load_dotenv()

CONN_STR   = os.getenv("COSMOS_CONNECTION_STR", "")
DB_NAME    = os.getenv("AGENT_LIBRARY_DB_NAME",   "agent-nexus")
CONTAINER  = os.getenv("AGENT_LIBRARY_CONTAINER", "AgentLibrary")
PARTITION  = "/agent_id"          # must match what you configured in the portal

if not CONN_STR:
    raise SystemExit(
        "ERROR: COSMOS_CONNECTION_STR is not set.\n"
        "Copy .env.example → .env and fill in your connection string."
    )

# ─── 8 Agent documents ────────────────────────────────────────────────────────
# Schema matches AGENT_CATALOG in backend_platform.py.
# "id" = CosmosDB document id (unique per container).
# "agent_id" = partition key field (must match /agent_id set in portal).

AGENTS = [
    # ── Tier 1 — Core Agents (frontend, backend, database) ───────────────────
    {
        "id": "backend_engineer",
        "agent_id": "backend_engineer",
        "role": "backend_engineer",
        "tier": 1,
        "model_label": "GPT-4o",
        "description": "Builds backend APIs, microservices, and orchestration logic on Azure.",
        "reputation_score": 0.93,
        "tags": ["backend", "api", "python", "azure"],
    },
    {
        "id": "frontend_engineer",
        "agent_id": "frontend_engineer",
        "role": "frontend_engineer",
        "tier": 1,
        "model_label": "GPT-4o",
        "description": "Builds React UIs and integrates frontend with backend APIs.",
        "reputation_score": 0.91,
        "tags": ["frontend", "react", "ui", "tailwind"],
    },
    {
        "id": "database_architect",
        "agent_id": "database_architect",
        "role": "database_architect",
        "tier": 1,
        "model_label": "GPT-4o",
        "description": "Designs SQL/NoSQL schemas, indexing strategies, and data pipelines.",
        "reputation_score": 0.88,
        "tags": ["database", "sql", "cosmos", "schema"],
    },
    # ── Tier 2 — Specialist Agents (all others) ──────────────────────────────
    {
        "id": "solution_architect",
        "agent_id": "solution_architect",
        "role": "solution_architect",
        "tier": 2,
        "model_label": "GPT-4o-mini",
        "description": "Designs overall system architecture, selects tech stack, and coordinates agents.",
        "reputation_score": 0.95,
        "tags": ["architecture", "azure", "design", "microservices"],
    },
    {
        "id": "api_designer",
        "agent_id": "api_designer",
        "role": "api_designer",
        "tier": 2,
        "model_label": "GPT-4o-mini",
        "description": "Designs OpenAPI contracts, versioning strategy, and SDK interfaces.",
        "reputation_score": 0.86,
        "tags": ["api", "openapi", "design", "rest"],
    },
    {
        "id": "security_engineer",
        "agent_id": "security_engineer",
        "role": "security_engineer",
        "tier": 2,
        "model_label": "GPT-4o-mini",
        "description": "Hardens systems against OWASP Top-10, manages secrets, and enforces compliance.",
        "reputation_score": 0.90,
        "tags": ["security", "compliance", "azure", "owasp"],
    },
    {
        "id": "devops_engineer",
        "agent_id": "devops_engineer",
        "role": "devops_engineer",
        "tier": 2,
        "model_label": "GPT-4o-mini",
        "description": "Builds CI/CD pipelines, IaC templates, and Azure deployment automation.",
        "reputation_score": 0.87,
        "tags": ["devops", "cicd", "azure", "iac"],
    },
    {
        "id": "qa_engineer",
        "agent_id": "qa_engineer",
        "role": "qa_engineer",
        "tier": 2,
        "model_label": "GPT-4o-mini",
        "description": "Writes test suites, runs load tests, and enforces coverage targets.",
        "reputation_score": 0.89,
        "tags": ["qa", "testing", "automation"],
    },
]


# ─── REMOVE OLD PLACEHOLDER BLOCK (replaced above) ───────────────────────────
# The block below this comment is intentionally absent; the
# old specialties/responsibilities/dependencies/output_types form has been
# replaced with the compact AGENT_CATALOG-compatible schema above.
# ─── Upsert ────────────────────────────────────────────────────────────────────

def main():
    print("Connecting to CosmosDB …")
    client = CosmosClient.from_connection_string(CONN_STR)

    # Create DB if it doesn't exist yet
    db = client.create_database_if_not_exists(id=DB_NAME)
    print(f"  Database  : {DB_NAME}  ✓")

    # Create container if it doesn't exist yet (partition key = /agent_id)
    container = db.create_container_if_not_exists(
        id=CONTAINER,
        partition_key=PartitionKey(path=PARTITION),
    )
    print(f"  Container : {CONTAINER}  ✓\n")

    inserted = 0
    for agent in AGENTS:
        try:
            container.upsert_item(agent)
            print(f"  ✓  Upserted  {agent['id']}")
            inserted += 1
        except exceptions.CosmosHttpResponseError as e:
            print(f"  ✗  Failed   {agent['id']}  →  {e.message}")

    print(f"\nDone – {inserted}/{len(AGENTS)} agents seeded into {DB_NAME}/{CONTAINER}")


if __name__ == "__main__":
    main()

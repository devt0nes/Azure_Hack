import os
from azure.cosmos import CosmosClient, PartitionKey, exceptions
from dotenv import load_dotenv
import uuid
from datetime import datetime

load_dotenv()

# ─────────────────────────────────────────────
# COSMOS DB CLIENT
# ─────────────────────────────────────────────

client = CosmosClient.from_connection_string(os.getenv("COSMOS_DB_CONNECTION_STRING"))

# Databases
ingest_db = client.get_database_client("nexus_ingest")

# Containers
schemas_container = ingest_db.get_container_client("schemas")

# ─────────────────────────────────────────────
# WRITE FUNCTIONS
# ─────────────────────────────────────────────

def write_schema_result(result: dict) -> str:
    """Write a SchemaResult or VisionResult or DocumentResult to Cosmos DB."""
    doc = {
        "id": str(uuid.uuid4()),
        "schema_id": str(uuid.uuid4()),
        "project_id": result.get("project_id"),
        "file_type": result.get("file_type"),
        "schema_result_json": result,
        "timestamp": datetime.utcnow().isoformat()
    }
    schemas_container.create_item(body=doc)
    return doc["id"]

def write_unified_context(unified: dict) -> str:
    """Write a UnifiedContext to Cosmos DB."""
    doc = {
        "id": str(uuid.uuid4()),
        "unified_context_id": str(uuid.uuid4()),
        "project_id": unified.get("project_id"),
        "file_type": "unified",
        "schema_result_json": unified,
        "timestamp": datetime.utcnow().isoformat()
    }
    schemas_container.create_item(body=doc)
    return doc["id"]

def read_schemas_for_project(project_id: str) -> list:
    """Read all schema results for a project."""
    query = f"SELECT * FROM c WHERE c.project_id = '{project_id}'"
    return list(schemas_container.query_items(query=query, enable_cross_partition_query=True))
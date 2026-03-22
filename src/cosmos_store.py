"""
cosmos_store.py
Azure Cosmos DB adapter for reputation documents.
Container : agent_catalog  |  Partition key : /agent_id

Document types:
  agent_reputation   — one per agent, mutable
  engagement_record  — one per build engagement, immutable
  community_report   — one per filed report, immutable
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import List, Optional

from azure.cosmos import CosmosClient

from .schemas import AgentReputationDocument, RawEngagementMetrics


class CosmosReputationStore:

    CONTAINER = "agent_catalog"

    def __init__(self, endpoint: str, key: str, database: str = "agentic_nexus"):
        client  = CosmosClient(endpoint, credential=key)
        db      = client.get_database_client(database)
        self._c = db.get_container_client(self.CONTAINER)

    @classmethod
    def from_env(cls) -> "CosmosReputationStore":
        return cls(
            endpoint=os.environ["COSMOS_ENDPOINT"],
            key=     os.environ["COSMOS_KEY"],
            database=os.getenv("COSMOS_DATABASE", "agentic_nexus"),
        )

    # ── Reputation document ──────────────────────

    def get_reputation(self, agent_id: str) -> Optional[AgentReputationDocument]:
        query  = "SELECT * FROM c WHERE c.agent_id=@id AND c.document_type='agent_reputation'"
        params = [{"name": "@id", "value": agent_id}]
        items  = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        return AgentReputationDocument(**items[0]) if items else None

    def save_reputation(self, doc: AgentReputationDocument) -> None:
        self._c.upsert_item(doc.to_cosmos_dict())

    # ── Engagement records ───────────────────────

    def save_engagement_record(self, metrics: RawEngagementMetrics) -> None:
        record = metrics.model_dump(mode="json")
        record["document_type"] = "engagement_record"
        record["id"]            = metrics.engagement_id
        self._c.upsert_item(record)

    def get_recent_engagements(self, agent_id: str, since: datetime) -> List[dict]:
        query = (
            "SELECT c.owner_azure_ad_id, c.recorded_at FROM c "
            "WHERE c.agent_id=@id AND c.document_type='engagement_record' AND c.recorded_at>=@since"
        )
        params = [
            {"name": "@id",    "value": agent_id},
            {"name": "@since", "value": since.isoformat()},
        ]
        return list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))

    # ── Community reports ────────────────────────

    def save_community_report(self, agent_id: str, reporter_id: str, notes: str) -> None:
        self._c.upsert_item({
            "id":                   f"report_{agent_id}_{reporter_id}_{int(datetime.now().timestamp())}",
            "document_type":        "community_report",
            "agent_id":             agent_id,
            "reporter_azure_ad_id": reporter_id,
            "notes":                notes,
            "reported_at":          datetime.now(timezone.utc).isoformat(),
        })

    def get_reporter_ids_in_window(self, agent_id: str, since: datetime) -> List[str]:
        query = (
            "SELECT DISTINCT c.reporter_azure_ad_id FROM c "
            "WHERE c.agent_id=@id AND c.document_type='community_report' AND c.reported_at>=@since"
        )
        params = [
            {"name": "@id",    "value": agent_id},
            {"name": "@since", "value": since.isoformat()},
        ]
        rows = list(self._c.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        return [r["reporter_azure_ad_id"] for r in rows]
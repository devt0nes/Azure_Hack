"""Unit tests for Cosmos startup integration and container behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import backend_platform
from cosmos_client import CosmosDBClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_default_container_config_supports_legacy_and_new_template_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEDGER_CONTAINER", "TaskLedgers")
    monkeypatch.setenv("AGENT_CONTAINER", "AgentRegistry")
    monkeypatch.setenv("COSMOS_TEMPLATE_CONTAINTER", "LegacyTemplate")
    monkeypatch.delenv("COSMOS_TEMPLATE_CONTAINER", raising=False)

    client = SimpleNamespace(_default_container_config=CosmosDBClient._default_container_config)
    cfg = CosmosDBClient._default_container_config(client)
    assert cfg["TaskLedgers"] == "/task_id"
    assert cfg["AgentRegistry"] == "/agent_id"
    assert cfg["LegacyTemplate"] == "/template_id"


def test_resolve_partition_value_backfills_expected_key():
    fake = SimpleNamespace(
        _container_partition_keys={"AgentRegistry": "/agent_id"},
        _infer_partition_path=lambda _name: "/agent_id",
    )
    doc = {"id": "abc-123", "name": "agent"}
    value = CosmosDBClient._resolve_partition_value(fake, "AgentRegistry", doc, "abc-123")
    assert value == "abc-123"
    assert doc["agent_id"] == "abc-123"


@pytest.mark.anyio
async def test_startup_initializes_cosmos_when_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("COSMOS_CONNECTION_STR", "AccountEndpoint=https://example/;AccountKey=fake;")
    monkeypatch.setenv("PERSIST_CODE_TO_DB", "true")
    monkeypatch.setenv("REQUIRE_COSMOS_ON_STARTUP", "true")

    monkeypatch.setattr(backend_platform, "init_cosmos_db", lambda: True)
    monkeypatch.setattr(backend_platform, "get_cosmos_client", lambda: SimpleNamespace(health_check=lambda: {
        "containers": ["TaskLedgers", "AgentRegistry", "TemplateLibrary"],
        "error": None,
    }))
    monkeypatch.setattr(backend_platform, "seed_default_templates", lambda: {"ok": True, "upserted": ["dashboard-layout", "sidebar-nav"]})

    await backend_platform.startup_event()
    assert backend_platform.COSMOS_STARTUP_STATUS["initialized"] is True
    assert backend_platform.COSMOS_STARTUP_STATUS["error"] is None
    assert "TaskLedgers" in backend_platform.COSMOS_STARTUP_STATUS["containers"]
    assert backend_platform.COSMOS_STARTUP_STATUS["template_seed"]["ok"] is True


@pytest.mark.anyio
async def test_startup_raises_when_cosmos_required_but_init_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("COSMOS_CONNECTION_STR", "AccountEndpoint=https://example/;AccountKey=fake;")
    monkeypatch.setenv("PERSIST_CODE_TO_DB", "true")
    monkeypatch.setenv("REQUIRE_COSMOS_ON_STARTUP", "true")

    monkeypatch.setattr(backend_platform, "init_cosmos_db", lambda: False)

    with pytest.raises(RuntimeError):
        await backend_platform.startup_event()


@pytest.mark.anyio
async def test_health_check_includes_cosmos_payload(monkeypatch: pytest.MonkeyPatch):
    backend_platform.COSMOS_STARTUP_STATUS.update({
        "enabled": True,
        "required": True,
        "initialized": True,
        "containers": ["TaskLedgers"],
        "error": None,
    })
    payload = await backend_platform.health_check()
    assert payload["status"] == "healthy"
    assert payload["cosmos"]["initialized"] is True
    assert payload["cosmos"]["containers"] == ["TaskLedgers"]

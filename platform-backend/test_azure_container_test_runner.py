import types

import pytest

from azure_container_test_runner import AzureContainerTestRunner, sanitize_aci_name


class _FakePoller:
    def result(self):
        return None


class _FakeContainerGroups:
    def __init__(self):
        self.created = []
        self.deleted = []

    def begin_create_or_update(self, resource_group, container_name, container_group):
        self.created.append((resource_group, container_name, container_group))
        return _FakePoller()

    def begin_delete(self, resource_group, container_name):
        self.deleted.append((resource_group, container_name))
        return _FakePoller()


class _FakeClient:
    def __init__(self):
        self.container_groups = _FakeContainerGroups()


def _install_fake_aci_models(monkeypatch):
    models_mod = types.ModuleType("azure.mgmt.containerinstance.models")

    class _Base:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ContainerGroup(_Base):
        pass

    class Container(_Base):
        pass

    class ResourceRequests(_Base):
        pass

    class ResourceRequirements(_Base):
        pass

    class EnvironmentVariable(_Base):
        pass

    models_mod.ContainerGroup = ContainerGroup
    models_mod.Container = Container
    models_mod.ResourceRequests = ResourceRequests
    models_mod.ResourceRequirements = ResourceRequirements
    models_mod.EnvironmentVariable = EnvironmentVariable

    monkeypatch.setitem(__import__("sys").modules, "azure", types.ModuleType("azure"))
    monkeypatch.setitem(__import__("sys").modules, "azure.mgmt", types.ModuleType("azure.mgmt"))
    monkeypatch.setitem(
        __import__("sys").modules,
        "azure.mgmt.containerinstance",
        types.ModuleType("azure.mgmt.containerinstance"),
    )
    monkeypatch.setitem(__import__("sys").modules, "azure.mgmt.containerinstance.models", models_mod)


@pytest.mark.asyncio
async def test_run_all_tests_container_command_and_cleanup(monkeypatch):
    _install_fake_aci_models(monkeypatch)

    runner = AzureContainerTestRunner(
        resource_group="rg-test",
        container_registry="registry.example.io",
        container_image="registry.example.io/nexus-tests:latest",
        timeout_seconds=120,
    )

    fake_client = _FakeClient()
    monkeypatch.setattr(runner, "_get_container_client", lambda: fake_client)

    async def _fake_wait_for_completion(client, container_name, timeout_seconds):
        assert client is fake_client
        assert container_name == "nexus-all-tests"
        assert timeout_seconds == 120
        logs = "=== 12 passed, 1 skipped in 45.2s ==="
        return {
            "success": True,
            "container_name": container_name,
            "status": "completed",
            "duration_seconds": 45,
            "logs": logs,
            "summary": runner._parse_test_summary(logs),
        }

    monkeypatch.setattr(runner, "_wait_for_completion", _fake_wait_for_completion)

    result = await runner.run_all_tests(container_name="nexus-all-tests", environment_vars={"FOO": "BAR"})

    assert result["success"] is True
    assert result["summary"]["passed"] == 12
    assert result["summary"]["skipped"] == 1

    assert len(fake_client.container_groups.created) == 1
    _, _, created_group = fake_client.container_groups.created[0]
    created_container = created_group.containers[0]
    command = created_container.command

    assert command[0] == "/bin/sh"
    assert command[1] == "-lc"
    assert "pytest /app -v" in command[2]
    assert "python /app/orchestrator_contract_verifier_smoketest.py" in command[2]
    assert "python /app/smoke_test.py --workspace /app/workspace --role backend_engineer" in command[2]
    assert "python /app/smoke_test.py --workspace /app/workspace --role frontend_engineer" in command[2]

    assert len(fake_client.container_groups.deleted) == 1
    assert fake_client.container_groups.deleted[0] == ("rg-test", "nexus-all-tests")


def test_parse_test_summary_extracts_all_counts():
    runner = AzureContainerTestRunner(
        resource_group="rg-test",
        container_registry="registry.example.io",
        container_image="registry.example.io/nexus-tests:latest",
    )

    logs = """
=========================== short test summary info ============================
FAILED test_api.py::test_health
================== 21 passed, 2 failed, 3 skipped, 1 error in 88.33s ==================
"""

    summary = runner._parse_test_summary(logs)
    assert summary["passed"] == 21
    assert summary["failed"] == 2
    assert summary["skipped"] == 3
    assert summary["errors"] == 1


@pytest.mark.asyncio
async def test_run_all_tests_sanitizes_invalid_container_name(monkeypatch):
    _install_fake_aci_models(monkeypatch)

    runner = AzureContainerTestRunner(
        resource_group="rg-test",
        container_registry="registry.example.io",
        container_image="registry.example.io/nexus-tests:latest",
        timeout_seconds=120,
    )

    fake_client = _FakeClient()
    monkeypatch.setattr(runner, "_get_container_client", lambda: fake_client)

    async def _fake_wait_for_completion(client, container_name, timeout_seconds):
        assert client is fake_client
        assert container_name == "nexus-smoke-project"
        assert timeout_seconds == 120
        return {
            "success": True,
            "container_name": container_name,
            "status": "completed",
            "duration_seconds": 1,
            "logs": "",
            "summary": {},
        }

    monkeypatch.setattr(runner, "_wait_for_completion", _fake_wait_for_completion)

    requested_name = "nexus-smoke-project-"
    assert sanitize_aci_name(requested_name) == "nexus-smoke-project"

    result = await runner.run_all_tests(container_name=requested_name, environment_vars={})

    assert result["success"] is True
    assert len(fake_client.container_groups.created) == 1
    created_rg, created_name, created_group = fake_client.container_groups.created[0]
    assert created_rg == "rg-test"
    assert created_name == "nexus-smoke-project"
    assert created_group.containers[0].name == "nexus-smoke-project"

    assert len(fake_client.container_groups.deleted) == 1
    assert fake_client.container_groups.deleted[0] == ("rg-test", "nexus-smoke-project")

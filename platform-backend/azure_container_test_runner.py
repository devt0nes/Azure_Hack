"""
Azure Container Instances Test Runner

This script runs ALL project tests in a SINGLE Azure Container Instance.
The container is created once, all tests run sequentially, then container is cleaned up.
This approach minimizes latency compared to creating a new container per test.

Test Discovery: Automatically finds and runs:
  - test_*.py files
  - *_test.py files  
  - smoke_test.py
  - orchestrator_contract_verifier_smoketest.py
"""

import asyncio
import json
import logging
import os
import re
import shlex
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from contextlib import suppress

from dotenv import load_dotenv

logger = logging.getLogger("azure-container-test-runner")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def normalize_acr_registry(registry: str) -> str:
    """Normalize registry value to an ACR login server host.

    Accepts values such as:
      - "nipunregistry" -> "nipunregistry.azurecr.io"
      - "nipunregistry.azurecr.io" -> unchanged
      - "https://nipunregistry.azurecr.io" -> "nipunregistry.azurecr.io"
    """
    value = str(registry or "").strip()
    if not value:
        return ""

    value = re.sub(r"^https?://", "", value, flags=re.IGNORECASE).strip("/")
    if "/" in value:
        value = value.split("/", 1)[0]
    if "." not in value:
        value = f"{value}.azurecr.io"
    return value


def acr_registry_name(registry: str) -> str:
    """Return ACR resource name suitable for Azure CLI (-n).

    Examples:
      - nipunregistry.azurecr.io -> nipunregistry
      - https://nipunregistry.azurecr.io -> nipunregistry
      - nipunregistry -> nipunregistry
    """
    host = normalize_acr_registry(registry)
    if not host:
        return ""
    if host.lower().endswith(".azurecr.io"):
        return host.split(".", 1)[0].strip()
    return host.split(".", 1)[0].strip() or host


def build_container_image_ref(registry: str, repository: str, tag: str = "latest") -> str:
    """Build full container image reference from registry/repository/tag."""
    host = normalize_acr_registry(registry)
    repo = str(repository or "").strip().strip("/")
    if not repo:
        raise ValueError("Container repository/name is required")

    image_tag = str(tag or "latest").strip() or "latest"
    if ":" in repo and "/" in repo and (not tag or tag == "latest"):
        # Already full image reference with explicit tag
        return repo
    if host:
        return f"{host}/{repo}:{image_tag}"
    return f"{repo}:{image_tag}"


def sanitize_aci_name(name: str, fallback_prefix: str = "nexus-smoke") -> str:
    """Return an Azure Container Instance compliant name."""
    value = str(name or "").strip().lower()
    value = re.sub(r"[^a-z0-9-]", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")

    if not value:
        fallback = re.sub(r"[^a-z0-9-]", "-", str(fallback_prefix or "nexus-smoke").lower())
        fallback = re.sub(r"-+", "-", fallback).strip("-") or "nexus-smoke"
        value = f"{fallback}-{int(time.time())}"

    value = value[:63]
    value = value.strip("-")

    if not value:
        value = "nexus-smoke"
    if not value[0].isalnum():
        value = f"n{value}"
    if not value[-1].isalnum():
        value = value.rstrip("-")
        if not value:
            value = "nexus-smoke"

    value = re.sub(r"[^a-z0-9-]", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return (value or "nexus-smoke")[:63]


def fetch_acr_credentials_from_cli(registry_name: str) -> Optional[Tuple[str, str]]:
    """Try to fetch ACR credentials from Azure CLI (az acr credential show).

    Args:
        registry_name: ACR registry name (e.g., "nipunregistry")

    Returns:
        Tuple of (username, password) or None if not found/failed.
    """
    try:
        import subprocess as sp
        registry = acr_registry_name(registry_name)
        if not registry:
            return None

        result = sp.run(
            ["az", "acr", "credential", "show", "-n", registry, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning("az acr credential show failed for %s: %s", registry, result.stderr[:200])
            return None

        creds = json.loads(result.stdout)
        username = str(creds.get("username") or "").strip()
        password = str(creds.get("passwords", [{}])[0].get("value") or "").strip()

        if username and password:
            logger.info("Auto-fetched ACR credentials from Azure CLI for %s", registry)
            return (username, password)
    except Exception as exc:
        logger.debug("Failed to fetch ACR credentials from CLI: %s", exc)
    return None


class AzureContainerTestRunner:
    """Run ALL tests in a single Azure Container Instance for efficiency."""

    def __init__(
        self,
        resource_group: str,
        container_registry: str,
        container_image: str,
        timeout_seconds: int = 3600,
    ):
        """Initialize Azure Container test runner.
        
        Args:
            resource_group: Azure Resource Group name
            container_registry: Container Registry URL (e.g., nipunregistry.azurecr.io)
            container_image: Full container image name with tag
            timeout_seconds: Maximum time to wait for container to complete
        """
        self.resource_group = resource_group
        self.container_registry = container_registry
        self.container_image = container_image
        self.timeout_seconds = timeout_seconds
        self._client = None

    def _get_container_client(self):
        """Lazy load and return Azure Container Instances client."""
        if self._client is not None:
            return self._client
        
        try:
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.containerinstance import ContainerInstanceManagementClient
            
            credential = DefaultAzureCredential()
            subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
            if not subscription_id:
                raise ValueError("AZURE_SUBSCRIPTION_ID environment variable not set")
            
            self._client = ContainerInstanceManagementClient(credential, subscription_id)
            return self._client
        except Exception as exc:
            logger.error("Failed to initialize Container Instances client: %s", exc)
            raise

    def _candidate_locations(self) -> List[str]:
        """Resolve ordered candidate Azure regions for ACI creation."""
        raw = (os.getenv("AZURE_CONTAINER_LOCATIONS") or "").strip()
        locations: List[str] = []
        if raw:
            for token in raw.split(","):
                val = str(token or "").strip()
                if val:
                    locations.append(val)

        primary = (os.getenv("AZURE_CONTAINER_LOCATION") or "").strip()
        if primary:
            locations.insert(0, primary)

        if not locations:
            locations = ["southeastasia"]

        dedup: List[str] = []
        seen = set()
        for loc in locations:
            key = loc.lower()
            if key in seen:
                continue
            seen.add(key)
            dedup.append(loc)
        return dedup

    def _create_or_update_group_with_location_fallback(
        self,
        client: Any,
        container_name: str,
        container_group_kwargs: Dict[str, Any],
        container_group_cls: Any,
    ) -> str:
        """Create ACI container group trying configured locations in order."""
        locations = self._candidate_locations()
        last_exc: Optional[Exception] = None
        for idx, location in enumerate(locations, start=1):
            kwargs = dict(container_group_kwargs)
            kwargs["location"] = location
            try:
                container_group = container_group_cls(**kwargs)
                logger.info(
                    "Creating container '%s' in location '%s' (%d/%d)",
                    container_name,
                    location,
                    idx,
                    len(locations),
                )
                if hasattr(client.container_groups, "begin_create_or_update"):
                    poller = client.container_groups.begin_create_or_update(
                        self.resource_group,
                        container_name,
                        container_group,
                    )
                    poller.result()
                else:
                    client.container_groups.create_or_update(
                        self.resource_group,
                        container_name,
                        container_group,
                    )
                return location
            except Exception as exc:
                last_exc = exc
                msg = str(exc)
                if "RequestDisallowedByAzure" in msg and idx < len(locations):
                    logger.warning(
                        "ACI create disallowed in '%s' by policy; trying next location.",
                        location,
                    )
                    continue
                if idx < len(locations):
                    logger.warning(
                        "ACI create failed in '%s': %s. Trying next location.",
                        location,
                        msg[:300],
                    )
                    continue
                raise

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("No Azure container locations available for ACI create")

    async def run_all_tests(
        self,
        container_name: str = "nexus-all-tests",
        environment_vars: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Run ALL tests in a single container instance.
        
        This is MUCH more efficient than creating a container per test.
        All tests run sequentially in the same container.
        
        Args:
            container_name: Name for the container instance
            environment_vars: Environment variables to pass to container
        
        Returns:
            Dictionary with test results and logs
        """
        try:
            from azure.mgmt.containerinstance.models import (
                ContainerGroup,
                Container,
                ResourceRequests,
                ResourceRequirements,
                EnvironmentVariable,
                ImageRegistryCredential,
            )
        except ImportError as exc:
            ImageRegistryCredential = None  # type: ignore[assignment]
            try:
                from azure.mgmt.containerinstance.models import (
                    ContainerGroup,
                    Container,
                    ResourceRequests,
                    ResourceRequirements,
                    EnvironmentVariable,
                )
            except ImportError:
                logger.error("azure-mgmt-containerinstances not installed: %s", exc)
                return {
                    "success": False,
                    "error": "Required Azure SDK not installed",
                    "container_name": container_name,
                }

        registry_username = (
            os.getenv("AZURE_CONTAINER_REGISTRY_USERNAME")
            or os.getenv("AZURE_ACR_USERNAME")
            or os.getenv("ACR_USERNAME")
            or os.getenv("CONTAINER_REGISTRY_USERNAME")
            or ""
        ).strip()
        registry_password = (
            os.getenv("AZURE_CONTAINER_REGISTRY_PASSWORD")
            or os.getenv("AZURE_ACR_PASSWORD")
            or os.getenv("ACR_PASSWORD")
            or os.getenv("CONTAINER_REGISTRY_PASSWORD")
            or ""
        ).strip()

        if not registry_username or not registry_password:
            cli_creds = fetch_acr_credentials_from_cli(self.container_registry)
            if cli_creds:
                registry_username, registry_password = cli_creds

        image_registry_credentials = []
        if ImageRegistryCredential and registry_username and registry_password:
            image_registry_credentials.append(
                ImageRegistryCredential(
                    server=normalize_acr_registry(self.container_registry),
                    username=registry_username,
                    password=registry_password,
                )
            )

        if not image_registry_credentials and registry_username and not registry_password:
            logger.warning("ACR username was provided without password; private image pull may fail")
        if not image_registry_credentials and registry_password and not registry_username:
            logger.warning("ACR password was provided without username; private image pull may fail")
        if not image_registry_credentials and not registry_username and not registry_password:
            logger.warning(
                "No ACR credentials found in env or Azure CLI for registry '%s' (acr-name='%s'); "
                "image pull may fail for private registries",
                normalize_acr_registry(self.container_registry),
                acr_registry_name(self.container_registry),
            )

        try:
            from azure.mgmt.containerinstance.models import ContainerGroup as _ContainerGroupClass
            supports_registry_credentials = "image_registry_credentials" in getattr(_ContainerGroupClass, "__init__", object).__code__.co_varnames  # type: ignore[attr-defined]
        except Exception:
            supports_registry_credentials = True

        logger.info("Registry host: %s", normalize_acr_registry(self.container_registry))
        if image_registry_credentials:
            logger.info("Using explicit ACR credentials for image pull")

        sanitized_container_name = sanitize_aci_name(container_name)
        if sanitized_container_name != container_name:
            logger.info("Sanitized container name: %s -> %s", container_name, sanitized_container_name)

        client = self._get_container_client()
        
        project_id_expr = "${NEXUS_ACTIVE_PROJECT_ID:-}"
        # Test command: hydrate workspace from blob, run pytest + smoke scripts,
        # then upload workspace back to blob.
        # runtime smoke checks explicitly (when workspace contracts are present).
        # runtime smoke checks explicitly (when workspace contracts are present).
        test_command = [
            "/bin/sh",
            "-lc",
            (
                "set -e; "
                "PYBIN=\"$(command -v python || command -v python3 || true)\"; "
                "if [ -z \"$PYBIN\" ]; then echo '[ACI] python/python3 not found in image' >&2; exit 127; fi; "
                f"if [ -n \"{project_id_expr}\" ]; then "
                "if [ ! -f /app/azure_workspace_sync_cli.py ]; then "
                "echo '[ACI] missing /app/azure_workspace_sync_cli.py in image' >&2; exit 127; "
                "fi; "
                "\"$PYBIN\" /app/azure_workspace_sync_cli.py "
                "--mode download "
                "--project-id \"$NEXUS_ACTIVE_PROJECT_ID\" "
                "--workspace /app/workspace; "
                "else "
                "echo '[ACI] NEXUS_ACTIVE_PROJECT_ID not set; skipping blob download'; "
                "fi; "
                "pytest /app -v --tb=short --color=yes --maxfail=5; "
                "\"$PYBIN\" /app/orchestrator_contract_verifier_smoketest.py; "
                "if [ -f /app/workspace/contracts/backend_api_contract.json ] "
                "&& [ -f /app/workspace/contracts/frontend_route_contract.json ] "
                "&& [ -d /app/workspace/backend ] "
                "&& [ -d /app/workspace/frontend ]; then "
                "\"$PYBIN\" /app/smoke_test.py --workspace /app/workspace --role backend_engineer "
                "--backend-url ${SMOKE_BACKEND_URL:-http://127.0.0.1:5100} "
                "--frontend-url ${SMOKE_FRONTEND_URL:-http://127.0.0.1:5180} "
                "--backend-port ${SMOKE_BACKEND_PORT:-5100} "
                "--frontend-port ${SMOKE_FRONTEND_PORT:-5180} "
                "--timeout ${SMOKE_STARTUP_TIMEOUT_SECONDS:-30} "
                "--max-total-seconds ${SMOKE_MAX_TOTAL_SECONDS:-300}; "
                "\"$PYBIN\" /app/smoke_test.py --workspace /app/workspace --role frontend_engineer "
                "--backend-url ${SMOKE_BACKEND_URL:-http://127.0.0.1:5100} "
                "--frontend-url ${SMOKE_FRONTEND_URL:-http://127.0.0.1:5180} "
                "--backend-port ${SMOKE_BACKEND_PORT:-5100} "
                "--frontend-port ${SMOKE_FRONTEND_PORT:-5180} "
                "--timeout ${SMOKE_STARTUP_TIMEOUT_SECONDS:-30} "
                "--max-total-seconds ${SMOKE_MAX_TOTAL_SECONDS:-300}; "
                "else "
                "echo '[ACI] workspace backend/frontend contracts not found; skipping smoke_test.py runtime checks'; "
                "fi; "
                f"if [ -n \"{project_id_expr}\" ]; then "
                "\"$PYBIN\" /app/azure_workspace_sync_cli.py "
                "--mode upload "
                "--project-id \"$NEXUS_ACTIVE_PROJECT_ID\" "
                "--workspace /app/workspace; "
                "else "
                "echo '[ACI] NEXUS_ACTIVE_PROJECT_ID not set; skipping blob upload'; "
                "fi"
            ),
        ]
        
        logger.info("Test command: %s", " ".join(test_command))
        
        # Prepare environment variables
        env_vars_list = [
            EnvironmentVariable(name="ENVIRONMENT", value="test"),
            EnvironmentVariable(name="PYTHONUNBUFFERED", value="1"),
            EnvironmentVariable(name="LOG_LEVEL", value="INFO"),
        ]
        
        merged_env = dict(environment_vars or {})
        if "AZURE_STORAGE_CONNECTION_STRING" not in merged_env and os.getenv("AZURE_STORAGE_CONNECTION_STRING"):
            merged_env["AZURE_STORAGE_CONNECTION_STRING"] = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
        if "AZURE_STORAGE_CONTAINER" not in merged_env:
            merged_env["AZURE_STORAGE_CONTAINER"] = os.getenv("AZURE_STORAGE_CONTAINER", "project-workspace")
        if "NEXUS_ACTIVE_PROJECT_ID" not in merged_env and os.getenv("NEXUS_ACTIVE_PROJECT_ID"):
            merged_env["NEXUS_ACTIVE_PROJECT_ID"] = os.getenv("NEXUS_ACTIVE_PROJECT_ID", "")
        for key, value in merged_env.items():
            env_vars_list.append(EnvironmentVariable(name=key, value=str(value)))
        
        # Create container specification
        # Increase resources for faster test execution
        container = Container(
            name=sanitized_container_name,
            image=self.container_image,
            command=test_command,
            resources=ResourceRequirements(
                requests=ResourceRequests(cpu=2.0, memory_in_gb=3.0)  # Increased for faster tests
            ),
            environment_variables=env_vars_list,
        )
        
        # Create container group
        container_group_kwargs = {
            "containers": [container],
            "os_type": "Linux",
            "restart_policy": "Never",
        }
        if image_registry_credentials and supports_registry_credentials:
            container_group_kwargs["image_registry_credentials"] = image_registry_credentials
        
        logger.info("Creating container: %s", sanitized_container_name)
        logger.info("Image: %s", self.container_image)
        logger.info("Timeout: %d seconds", self.timeout_seconds)
        
        try:
            # Create the container group (with region fallback support).
            self._create_or_update_group_with_location_fallback(
                client=client,
                container_name=sanitized_container_name,
                container_group_kwargs=container_group_kwargs,
                container_group_cls=ContainerGroup,
            )
            
            # Wait for container to complete
            result = await self._wait_for_completion(
                client, sanitized_container_name, self.timeout_seconds
            )
            
            # Always cleanup
            logger.info("Deleting container: %s", sanitized_container_name)
            try:
                if hasattr(client.container_groups, "begin_delete"):
                    delete_poller = client.container_groups.begin_delete(
                        self.resource_group, sanitized_container_name
                    )
                    delete_poller.result()
                else:
                    client.container_groups.delete(self.resource_group, sanitized_container_name)
            except Exception as cleanup_exc:
                logger.warning("Failed to delete container: %s", cleanup_exc)
            
            return result
        except Exception as exc:
            logger.error("Test execution failed: %s", exc)
            # Attempt cleanup on failure
            try:
                if hasattr(client.container_groups, "begin_delete"):
                    delete_poller = client.container_groups.begin_delete(
                        self.resource_group, sanitized_container_name
                    )
                    delete_poller.result()
                else:
                    client.container_groups.delete(self.resource_group, sanitized_container_name)
            except Exception:
                pass
            
            return {
                "success": False,
                "error": str(exc),
                "container_name": sanitized_container_name,
            }

    async def run_workspace_command(
        self,
        project_id: str,
        command_parts: List[str],
        cwd: str = ".",
        container_name: str = "nexus-cmd",
        environment_vars: Optional[Dict[str, str]] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute a one-off workspace command inside ACI against blob-backed workspace."""
        project_id = str(project_id or "").strip()
        if not project_id:
            return {"success": False, "error": "project_id is required", "container_name": container_name}
        if not command_parts:
            return {"success": False, "error": "command_parts is required", "container_name": container_name}

        safe_parts = [str(p) for p in command_parts if str(p) != ""]
        if not safe_parts:
            return {"success": False, "error": "empty command", "container_name": container_name}
        safe_cmd = " ".join(shlex.quote(p) for p in safe_parts)
        cwd_rel = str(cwd or ".").strip().strip("/")
        cwd_rel = cwd_rel or "."
        cwd_quoted = shlex.quote(cwd_rel)
        dist_rel = "dist" if cwd_rel in {".", ""} else f"{cwd_rel}/dist"
        dist_rel_quoted = shlex.quote(dist_rel)

        run_timeout = int(timeout_seconds or self.timeout_seconds or 600)
        run_timeout = max(60, run_timeout)
        sanitized_container_name = sanitize_aci_name(container_name)
        client = self._get_container_client()

        command = [
            "/bin/sh",
            "-lc",
            (
                "set -e; "
                "PYBIN=\"$(command -v python || command -v python3 || true)\"; "
                "if [ -z \"$PYBIN\" ]; then echo '[ACI] python/python3 not found in image' >&2; exit 127; fi; "
                "if [ ! -f /app/azure_workspace_sync_cli.py ]; then "
                "echo '[ACI] missing /app/azure_workspace_sync_cli.py in image' >&2; exit 127; "
                "fi; "
                "\"$PYBIN\" /app/azure_workspace_sync_cli.py "
                "--mode download "
                f"--project-id {shlex.quote(project_id)} "
                "--workspace /app/workspace; "
                "cd /app/workspace; "
                f"cd {cwd_quoted}; "
                "set +e; "
                f"{safe_cmd} > /tmp/nexus_cmd_stdout.txt 2> /tmp/nexus_cmd_stderr.txt; "
                "EXIT_CODE=$?; "
                "set -e; "
                "\"$PYBIN\" /app/azure_workspace_sync_cli.py "
                "--mode upload "
                f"--project-id {shlex.quote(project_id)} "
                "--workspace /app/workspace || true; "
                "if [ -d ./dist ]; then "
                "\"$PYBIN\" /app/azure_workspace_sync_cli.py "
                "--mode upload-dist-web "
                f"--project-id {shlex.quote(project_id)} "
                "--workspace /app/workspace "
                f"--dist-relative {dist_rel_quoted} || true; "
                "fi; "
                "echo '__NEXUS_CMD_STDOUT_BEGIN__'; "
                "cat /tmp/nexus_cmd_stdout.txt || true; "
                "echo '__NEXUS_CMD_STDOUT_END__'; "
                "echo '__NEXUS_CMD_STDERR_BEGIN__'; "
                "cat /tmp/nexus_cmd_stderr.txt || true; "
                "echo '__NEXUS_CMD_STDERR_END__'; "
                "echo \"__NEXUS_CMD_EXIT_CODE__:${EXIT_CODE}\"; "
                "exit ${EXIT_CODE}"
            ),
        ]

        try:
            from azure.mgmt.containerinstance.models import (
                ContainerGroup,
                Container,
                ResourceRequests,
                ResourceRequirements,
                EnvironmentVariable,
                ImageRegistryCredential,
            )
        except ImportError as exc:
            ImageRegistryCredential = None  # type: ignore[assignment]
            try:
                from azure.mgmt.containerinstance.models import (  # type: ignore[no-redef]
                    ContainerGroup,
                    Container,
                    ResourceRequests,
                    ResourceRequirements,
                    EnvironmentVariable,
                )
            except ImportError:
                return {
                    "success": False,
                    "error": f"Required Azure SDK not installed: {exc}",
                    "container_name": sanitized_container_name,
                }

        registry_username = (
            os.getenv("AZURE_CONTAINER_REGISTRY_USERNAME")
            or os.getenv("AZURE_ACR_USERNAME")
            or os.getenv("ACR_USERNAME")
            or os.getenv("CONTAINER_REGISTRY_USERNAME")
            or ""
        ).strip()
        registry_password = (
            os.getenv("AZURE_CONTAINER_REGISTRY_PASSWORD")
            or os.getenv("AZURE_ACR_PASSWORD")
            or os.getenv("ACR_PASSWORD")
            or os.getenv("CONTAINER_REGISTRY_PASSWORD")
            or ""
        ).strip()
        if not registry_username or not registry_password:
            cli_creds = fetch_acr_credentials_from_cli(self.container_registry)
            if cli_creds:
                registry_username, registry_password = cli_creds

        image_registry_credentials = []
        if ImageRegistryCredential and registry_username and registry_password:
            image_registry_credentials.append(
                ImageRegistryCredential(
                    server=normalize_acr_registry(self.container_registry),
                    username=registry_username,
                    password=registry_password,
                )
            )

        env_map = dict(environment_vars or {})
        env_map.setdefault("NEXUS_ACTIVE_PROJECT_ID", project_id)
        env_map.setdefault("AZURE_STORAGE_CONNECTION_STRING", os.getenv("AZURE_STORAGE_CONNECTION_STRING", ""))
        env_map.setdefault("AZURE_STORAGE_CONTAINER", os.getenv("AZURE_STORAGE_CONTAINER", "project-workspace"))

        env_vars_list = [
            EnvironmentVariable(name="ENVIRONMENT", value="test"),
            EnvironmentVariable(name="PYTHONUNBUFFERED", value="1"),
            EnvironmentVariable(name="LOG_LEVEL", value="INFO"),
        ]
        for key, value in env_map.items():
            env_vars_list.append(EnvironmentVariable(name=key, value=str(value)))

        container = Container(
            name=sanitized_container_name,
            image=self.container_image,
            command=command,
            resources=ResourceRequirements(
                requests=ResourceRequests(cpu=2.0, memory_in_gb=3.0)
            ),
            environment_variables=env_vars_list,
        )

        try:
            from azure.mgmt.containerinstance.models import ContainerGroup as _ContainerGroupClass
            supports_registry_credentials = "image_registry_credentials" in getattr(_ContainerGroupClass, "__init__", object).__code__.co_varnames  # type: ignore[attr-defined]
        except Exception:
            supports_registry_credentials = True

        group_kwargs = {
            "containers": [container],
            "os_type": "Linux",
            "restart_policy": "Never",
        }
        if image_registry_credentials and supports_registry_credentials:
            group_kwargs["image_registry_credentials"] = image_registry_credentials

        try:
            self._create_or_update_group_with_location_fallback(
                client=client,
                container_name=sanitized_container_name,
                container_group_kwargs=group_kwargs,
                container_group_cls=ContainerGroup,
            )

            result = await self._wait_for_completion(client, sanitized_container_name, run_timeout)
            return result
        finally:
            try:
                if hasattr(client.container_groups, "begin_delete"):
                    delete_poller = client.container_groups.begin_delete(
                        self.resource_group, sanitized_container_name
                    )
                    delete_poller.result()
                else:
                    client.container_groups.delete(self.resource_group, sanitized_container_name)
            except Exception:
                pass

    async def _wait_for_completion(
        self, client: Any, container_name: str, timeout_seconds: int
    ) -> Dict[str, Any]:
        """Wait for container to complete and return results."""
        start_time = time.time()
        poll_interval = 10  # Increased to 10 seconds (less frequent checks)
        last_log_length = 0
        
        logger.info("Polling container status every %d seconds...", poll_interval)
        
        while time.time() - start_time < timeout_seconds:
            try:
                cg = client.container_groups.get(self.resource_group, container_name)
                state = cg.instance_view.state
                
                elapsed = int(time.time() - start_time)
                logger.info("Container state: %s (elapsed: %ds)", state, elapsed)
                
                if state == "Succeeded":
                    logs = self._get_container_logs(client, container_name)
                    return {
                        "success": True,
                        "container_name": container_name,
                        "status": "completed",
                        "duration_seconds": int(time.time() - start_time),
                        "logs": logs,
                        "summary": self._parse_test_summary(logs),
                    }
                elif state == "Failed":
                    logs = self._get_container_logs(client, container_name)
                    diagnostics = self._collect_failure_diagnostics(client, container_name)
                    error_msg = "Container execution failed"
                    if diagnostics:
                        error_msg = f"{error_msg}: {diagnostics}"
                    return {
                        "success": False,
                        "container_name": container_name,
                        "status": "failed",
                        "duration_seconds": int(time.time() - start_time),
                        "error": error_msg,
                        "logs": logs,
                    }
                
                # Print new logs incrementally for real-time feedback
                current_logs = self._get_container_logs(client, container_name)
                if len(current_logs) > last_log_length:
                    new_content = current_logs[last_log_length:]
                    # Only print last 5 lines to avoid spam
                    lines = new_content.split('\n')[-5:]
                    for line in lines:
                        if line.strip():
                            logger.info("  > %s", line)
                    last_log_length = len(current_logs)
                
                await asyncio.sleep(poll_interval)
            except Exception as exc:
                logger.error("Error checking container status: %s", exc)
                await asyncio.sleep(poll_interval)
        
        return {
            "success": False,
            "container_name": container_name,
            "status": "timeout",
            "duration_seconds": timeout_seconds,
            "error": f"Container did not complete within {timeout_seconds} seconds",
        }

    def _get_container_logs(self, client: Any, container_name: str) -> str:
        """Retrieve container logs."""
        last_error = None
        for attr_name in ["containers", "container"]:
            ops = getattr(client, attr_name, None)
            if ops is None:
                continue
            for method_name in ["list_logs", "get_logs"]:
                fn = getattr(ops, method_name, None)
                if fn is None:
                    continue
                try:
                    logs = fn(self.resource_group, container_name, container_name)
                    if hasattr(logs, "logs") and getattr(logs, "logs"):
                        return str(logs.logs)
                    if isinstance(logs, str):
                        return logs
                except Exception as exc:
                    last_error = exc
                    continue

        if last_error is not None:
            logger.warning("Failed to retrieve container logs: %s", last_error)
        return ""

    def _collect_failure_diagnostics(self, client: Any, container_name: str) -> str:
        """Extract concise ACI failure details from instance view."""
        try:
            cg = client.container_groups.get(self.resource_group, container_name)
        except Exception as exc:
            return f"failed to fetch container group diagnostics: {exc}"

        details: List[str] = []
        with suppress(Exception):
            group_view = getattr(cg, "instance_view", None)
            events = getattr(group_view, "events", None) or []
            for ev in events:
                msg = str(getattr(ev, "message", "") or "").strip()
                if msg:
                    details.append(msg)

        with suppress(Exception):
            for c in getattr(cg, "containers", []) or []:
                c_name = getattr(c, "name", "container")
                iv = getattr(c, "instance_view", None)
                current = getattr(iv, "current_state", None)
                if current is None:
                    continue
                state = str(getattr(current, "state", "") or "").strip()
                detail_status = str(getattr(current, "detail_status", "") or "").strip()
                exit_code = getattr(current, "exit_code", None)
                msg = f"{c_name}: state={state or 'unknown'}"
                if detail_status:
                    msg += f", detail={detail_status}"
                if exit_code is not None:
                    msg += f", exit_code={exit_code}"
                details.append(msg)

        # De-duplicate while preserving order
        deduped: List[str] = []
        seen = set()
        for d in details:
            key = d.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)

        return " | ".join(deduped[:5])

    def _parse_test_summary(self, logs: str) -> Dict[str, Any]:
        """Parse pytest summary from logs."""
        summary = {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
        }
        
        try:
            candidates = [line.strip() for line in logs.split("\n") if line.strip()]
            # Prefer the last pytest summary-like line if multiple are present.
            summary_line = ""
            for line in candidates:
                if any(token in line for token in [" passed", " failed", " skipped", " error", " errors"]):
                    summary_line = line

            if summary_line:
                for key, target in [
                    ("passed", "passed"),
                    ("failed", "failed"),
                    ("skipped", "skipped"),
                    ("error", "errors"),
                    ("errors", "errors"),
                ]:
                    m = re.search(rf"(\d+)\s+{key}\b", summary_line)
                    if m:
                        summary[target] = int(m.group(1))
        except Exception as exc:
            logger.warning("Failed to parse test summary: %s", exc)
        
        return summary


async def main():
    """Main entry point for testing."""
    load_dotenv()

    # Load configuration from environment
    resource_group = os.getenv("AZURE_RESOURCE_GROUP", "Nipun-Bhattad-RG")
    container_registry = os.getenv("AZURE_CONTAINER_REGISTRY", "nipunregistry")
    container_repository = os.getenv("AZURE_CONTAINER_REPOSITORY", os.getenv("AZURE_CONTAINER_NAME", "nexus-test-runner"))
    container_tag = os.getenv("AZURE_CONTAINER_TAG", "latest")
    timeout_seconds = int(os.getenv("AZURE_CONTAINER_INSTANCES_TIMEOUT", "3600"))

    container_image = build_container_image_ref(container_registry, container_repository, container_tag)
    
    logger.info("=" * 70)
    logger.info("AZURE CONTAINER TEST RUNNER - ALL TESTS IN SINGLE CONTAINER")
    logger.info("=" * 70)
    logger.info("Resource Group: %s", resource_group)
    logger.info("Container Repository: %s", container_repository)
    logger.info("Container Image: %s", container_image)
    logger.info("Timeout: %d seconds", timeout_seconds)
    logger.info("=" * 70)
    
    runner = AzureContainerTestRunner(
        resource_group=resource_group,
        container_registry=container_registry,
        container_image=container_image,
        timeout_seconds=timeout_seconds,
    )
    
    # Run all tests in a single container
    result = await runner.run_all_tests(
        container_name="nexus-all-tests",
        environment_vars={},
    )
    
    # Display results
    logger.info("=" * 70)
    logger.info("TEST RESULTS")
    logger.info("=" * 70)
    logger.info("Success: %s", result.get("success"))
    logger.info("Duration: %s seconds", result.get("duration_seconds", "unknown"))
    logger.info("Status: %s", result.get("status"))
    
    if "summary" in result:
        summary = result["summary"]
        logger.info("Passed: %d", summary.get("passed", 0))
        logger.info("Failed: %d", summary.get("failed", 0))
    
    if "error" in result:
        logger.error("Error: %s", result["error"])
    
    logger.info("=" * 70)
    logger.info("CONTAINER LOGS")
    logger.info("=" * 70)
    logs = result.get("logs", "No logs available")
    print(logs)
    logger.info("=" * 70)
    
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    asyncio.run(main())

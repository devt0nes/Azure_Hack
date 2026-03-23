#!/usr/bin/env python3
"""Azure Container Apps deployment agent."""

from __future__ import annotations

import argparse
import json
import os
import random
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional


@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str


@dataclass
class DeploymentResult:
    status: str
    mode: str
    message: str
    details: Dict[str, str]


class AzureDeploymentAgent:
    def __init__(
        self,
        project_root: Path,
        project_name: str,
        backend_rel: str = "workspace/backend_engineer",
        frontend_rel: str = "workspace/frontend_engineer",
    ) -> None:
        self.project_root = project_root
        self.project_name = project_name
        self.backend_dir = project_root / backend_rel
        self.frontend_dir = project_root / frontend_rel

        self.azure_dir = project_root / "deployment" / "azure"
        self.output_file = project_root / "workspace" / "azure_deployment_todo.md"
        self.deploy_result = self.azure_dir / "deployment_result.json"
        self.mock_env = self.azure_dir / "mock.secrets.env"
        self.backend_dockerfile = self.backend_dir / "Dockerfile"
        self.frontend_dockerfile = self.frontend_dir / "Dockerfile"
        self.frontend_nginx_conf = self.frontend_dir / "nginx.conf"
        self.bicep_file = self.azure_dir / "main.bicep"
        self.bicep_params = self.azure_dir / "main.parameters.json"

        self.tools: Dict[str, Callable[..., DeploymentResult]] = {
            "deploy_to_azure": self.deploy_to_azure,
        }

    def run(self) -> Path:
        self.generate_artifacts()
        self.create_mock_secrets()
        checks = self._run_local_checks()
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.output_file.write_text(self._render_markdown(checks), encoding="utf-8")
        return self.output_file

    def run_tool(self, tool_name: str, **kwargs) -> DeploymentResult:
        tool = self.tools.get(tool_name)
        if not tool:
            return DeploymentResult(
                status="failed",
                mode="tool",
                message=f"Unknown tool: {tool_name}",
                details={"available_tools": ", ".join(self.tools.keys())},
            )
        return tool(**kwargs)

    def generate_artifacts(self) -> None:
        self.azure_dir.mkdir(parents=True, exist_ok=True)
        self.backend_dir.mkdir(parents=True, exist_ok=True)
        self.frontend_dir.mkdir(parents=True, exist_ok=True)

        self.backend_dockerfile.write_text(
            """FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY . .
EXPOSE 5000
CMD [\"npm\", \"start\"]
""",
            encoding="utf-8",
        )

        self.frontend_nginx_conf.write_text(
            """server {
  listen 80;
  server_name _;
  root /usr/share/nginx/html;
  index index.html;
  location / { try_files $uri /index.html; }
}
""",
            encoding="utf-8",
        )

        self.frontend_dockerfile.write_text(
            """FROM node:18-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80
CMD [\"nginx\", \"-g\", \"daemon off;\"]
""",
            encoding="utf-8",
        )

        self.bicep_file.write_text(
            """param location string = resourceGroup().location
param projectName string
param logAnalyticsName string = '${projectName}-law'
param containerAppEnvName string = '${projectName}-env'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: containerAppEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: listKeys(logAnalytics.id, '2022-10-01').primarySharedKey
      }
    }
  }
}

output containerAppEnvironmentId string = containerAppEnv.id
""",
            encoding="utf-8",
        )

        self.bicep_params.write_text(
            json.dumps(
                {
                    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
                    "contentVersion": "1.0.0.0",
                    "parameters": {
                        "projectName": {"value": self.project_name}
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def create_mock_secrets(self) -> Path:
        self.azure_dir.mkdir(parents=True, exist_ok=True)
        mock_values = {
            "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
            "AZURE_RESOURCE_GROUP": "agentic_brocode",
            "AZURE_LOCATION": "southeastasia",
            "JWT_SECRET": f"mock-jwt-{secrets.token_hex(16)}",
            "DB_USER": "mock_user",
            "DB_PASSWORD": "mock_password",
            "DB_HOST": "mock-db.postgres.database.azure.com",
            "DB_PORT": "5432",
            "DB_NAME": "mockdb",
        }
        self.mock_env.write_text("\n".join([f"{k}={v}" for k, v in mock_values.items()]) + "\n", encoding="utf-8")
        return self.mock_env

    def deploy_to_azure(
        self,
        mock_success: bool = False,
        resource_group: str = "agentic_brocode",
        location: str = "southeastasia",
    ) -> DeploymentResult:
        self.generate_artifacts()
        self.create_mock_secrets()

        az_path = shutil.which("az")
        if mock_success or not az_path:
            result = DeploymentResult(
                status="succeeded",
                mode="mock",
                message="Mock deployment succeeded.",
                details={
                    "reason": "forced-mock" if mock_success else "az-cli-not-found",
                    "mock_env_file": str(self.mock_env),
                },
            )
            self._write_deployment_result(result)
            return result

        if not self._is_azure_logged_in(az_path):
            result = DeploymentResult(
                status="failed",
                mode="real",
                message="Azure CLI is not logged in.",
                details={"hint": "Run az login --use-device-code"},
            )
            self._write_deployment_result(result)
            return result

        try:
            suffix = str(random.randint(10000, 99999))
            safe = "".join(ch for ch in self.project_name.lower() if ch.isalnum())[:14] or "agentic"
            acr_name = f"{safe}{suffix}acr"[:50]
            env_name = f"{safe}-env"[:32]
            backend_name = f"{safe}-{suffix}-backend"[:32]
            frontend_name = f"{safe}-{suffix}-frontend"[:32]

            self._run_az(az_path, ["group", "create", "-n", resource_group, "-l", location])
            self._run_az(az_path, ["extension", "add", "-n", "containerapp", "-y"])
            self._run_az(az_path, ["acr", "create", "-g", resource_group, "-n", acr_name, "--sku", "Basic", "--admin-enabled", "true"])

            existing_env = self._find_existing_containerapp_env(az_path, resource_group, location)
            if existing_env:
                env_name = existing_env
            else:
                self._run_az(
                    az_path,
                    ["containerapp", "env", "create", "-g", resource_group, "-n", env_name, "--location", location],
                )

            acr_server = self._run_az(az_path, ["acr", "show", "-n", acr_name, "--query", "loginServer", "-o", "tsv"]).strip()
            acr_user = self._run_az(az_path, ["acr", "credential", "show", "-n", acr_name, "--query", "username", "-o", "tsv"]).strip()
            acr_pass = self._run_az(az_path, ["acr", "credential", "show", "-n", acr_name, "--query", "passwords[0].value", "-o", "tsv"]).strip()

            backend_image = f"{acr_server}/backend:latest"
            frontend_image = f"{acr_server}/frontend:latest"

            self._docker_login(acr_server, acr_user, acr_pass)
            self._docker_build_and_push(self.backend_dir, backend_image)
            self._docker_build_and_push(self.frontend_dir, frontend_image)

            jwt = os.getenv("JWT_SECRET", f"mock-jwt-{secrets.token_hex(16)}")
            db_user = os.getenv("DB_USER", "mock_user")
            db_password = os.getenv("DB_PASSWORD", "mock_password")
            db_host = os.getenv("DB_HOST", "mock-db.postgres.database.azure.com")
            db_port = os.getenv("DB_PORT", "5432")
            db_name = os.getenv("DB_NAME", "mockdb")

            self._run_az(
                az_path,
                [
                    "containerapp", "create",
                    "-g", resource_group,
                    "-n", backend_name,
                    "--environment", env_name,
                    "--image", backend_image,
                    "--target-port", "5000",
                    "--ingress", "external",
                    "--registry-server", acr_server,
                    "--registry-username", acr_user,
                    "--registry-password", acr_pass,
                    "--env-vars",
                    f"NODE_ENV=production JWT_SECRET={jwt} DB_USER={db_user} DB_PASSWORD={db_password} DB_HOST={db_host} DB_PORT={db_port} DB_NAME={db_name}",
                ],
            )

            self._run_az(
                az_path,
                [
                    "containerapp", "create",
                    "-g", resource_group,
                    "-n", frontend_name,
                    "--environment", env_name,
                    "--image", frontend_image,
                    "--target-port", "80",
                    "--ingress", "external",
                    "--registry-server", acr_server,
                    "--registry-username", acr_user,
                    "--registry-password", acr_pass,
                ],
            )

            backend_fqdn = self._run_az(az_path, ["containerapp", "show", "-g", resource_group, "-n", backend_name, "--query", "properties.configuration.ingress.fqdn", "-o", "tsv"]).strip()
            frontend_fqdn = self._run_az(az_path, ["containerapp", "show", "-g", resource_group, "-n", frontend_name, "--query", "properties.configuration.ingress.fqdn", "-o", "tsv"]).strip()

            result = DeploymentResult(
                status="succeeded",
                mode="real",
                message="Azure Container Apps deployment succeeded.",
                details={
                    "resource_group": resource_group,
                    "location": location,
                    "environment": env_name,
                    "acr": acr_name,
                    "backend_app": backend_name,
                    "frontend_app": frontend_name,
                    "backend_url": f"https://{backend_fqdn}" if backend_fqdn else "",
                    "frontend_url": f"https://{frontend_fqdn}" if frontend_fqdn else "",
                },
            )
            self._write_deployment_result(result)
            return result
        except subprocess.CalledProcessError as exc:
            result = DeploymentResult(
                status="failed",
                mode="real",
                message="Azure deployment failed.",
                details={
                    "stderr": (exc.stderr or "")[-4000:],
                    "stdout": (exc.stdout or "")[-4000:],
                },
            )
            self._write_deployment_result(result)
            return result

    def _is_azure_logged_in(self, az_path: str) -> bool:
        try:
            subprocess.run([az_path, "account", "show", "-o", "none"], check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def _run_az(self, az_path: str, args: List[str]) -> str:
        completed = subprocess.run([az_path, *args], check=True, capture_output=True, text=True)
        return completed.stdout

    def _find_existing_containerapp_env(self, az_path: str, resource_group: str, location: str) -> Optional[str]:
        try:
            raw = self._run_az(az_path, ["containerapp", "env", "list", "-g", resource_group, "-o", "json"])
            items = json.loads(raw)
            if not isinstance(items, list) or not items:
                return None

            target_loc = (location or "").strip().lower().replace(" ", "")
            for env in items:
                env_loc = str(env.get("location", "")).strip().lower().replace(" ", "")
                if env_loc == target_loc:
                    return env.get("name")

            # Fallback: if any env exists in RG, use first one.
            first_name = items[0].get("name")
            return first_name if first_name else None
        except Exception:
            return None

    def _docker_login(self, registry: str, username: str, password: str) -> None:
        subprocess.run(
            ["docker", "login", registry, "-u", username, "-p", password],
            check=True,
            capture_output=True,
            text=True,
        )

    def _docker_build_and_push(self, context_dir: Path, image_name: str) -> None:
        subprocess.run(
            ["docker", "build", "-t", image_name, str(context_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["docker", "push", image_name],
            check=True,
            capture_output=True,
            text=True,
        )

    def _write_deployment_result(self, result: DeploymentResult) -> None:
        self.azure_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": result.status,
            "mode": result.mode,
            "message": result.message,
            "details": result.details,
        }
        self.deploy_result.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _run_local_checks(self) -> List[CheckResult]:
        backend_pkg = self.backend_dir / "package.json"
        frontend_pkg = self.frontend_dir / "package.json"
        backend_app = self.backend_dir / "app.js"

        return [
            CheckResult("Backend workspace exists", self.backend_dir.exists(), str(self.backend_dir)),
            CheckResult("Frontend workspace exists", self.frontend_dir.exists(), str(self.frontend_dir)),
            CheckResult("Backend package.json", backend_pkg.exists(), str(backend_pkg)),
            CheckResult("Frontend package.json", frontend_pkg.exists(), str(frontend_pkg)),
            CheckResult("Backend app.js", backend_app.exists(), str(backend_app)),
        ]

    def _render_markdown(self, checks: List[CheckResult]) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        lines = [
            "# Azure Deployment TODO (Container Apps)",
            "",
            f"Generated: {ts}",
            f"Project: {self.project_name}",
            "",
            "## Local checks",
            "",
        ]
        for c in checks:
            lines.append(f"- {'✅' if c.ok else '❌'} {c.name} — {c.details}")
        lines.extend([
            "",
            "## Target",
            "- Resource Group: agentic_brocode",
            "- Location: southeastasia",
            "- Runtime: Azure Container Apps (backend + frontend)",
            "",
        ])
        return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Azure Container Apps deployment agent")
    parser.add_argument("--action", default="full", choices=["init", "deploy", "full"])
    parser.add_argument("--project-name", default="nexus-new")
    parser.add_argument("--resource-group", default="agentic_brocode")
    parser.add_argument("--location", default="southeastasia")
    parser.add_argument("--backend-rel", default="workspace/backend_engineer")
    parser.add_argument("--frontend-rel", default="workspace/frontend_engineer")
    parser.add_argument("--mock-success", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    agent = AzureDeploymentAgent(
        project_root=Path(__file__).resolve().parent,
        project_name=args.project_name,
        backend_rel=args.backend_rel,
        frontend_rel=args.frontend_rel,
    )

    if args.action in ("init", "full"):
        out = agent.run()
        print(f"✅ Checklist generated: {out}")

    if args.action in ("deploy", "full"):
        result = agent.run_tool(
            "deploy_to_azure",
            mock_success=args.mock_success,
            resource_group=args.resource_group,
            location=args.location,
        )
        icon = "✅" if result.status == "succeeded" else "❌"
        print(f"{icon} {result.message}")
        print(f"Result file: {agent.deploy_result}")


if __name__ == "__main__":
    main()

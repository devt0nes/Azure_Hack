import os
import httpx
import logging
import asyncio
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


class DeploymentProvider:
    """Base interface — all providers implement this"""
    async def deploy(self, project_id: str, app_name: str, generated_code_path: Path) -> Dict:
        raise NotImplementedError


class RailwayDeploymentProvider(DeploymentProvider):
    """
    Deploys generated apps to Railway via their API.
    Railway takes a GitHub repo or a directory + Dockerfile.
    We use their GraphQL API to create a project and deploy from source.
    """

    API_URL = "https://backboard.railway.app/graphql/v2"

    def __init__(self):
        self.token = os.environ["RAILWAY_API_TOKEN"]
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def _gql(self, query: str, variables: dict = {}) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.API_URL,
                json={"query": query, "variables": variables},
                headers=self.headers,
            )
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data:
                raise Exception(f"Railway API error: {data['errors']}")
            return data["data"]

    async def deploy(self, project_id: str, app_name: str, generated_code_path: Path) -> Dict:
        logger.info(f"🚂 Starting Railway deployment for {app_name}")

        # Step 1 — Create a Railway project
        create_project = await self._gql("""
            mutation CreateProject($name: String!) {
                projectCreate(input: { name: $name }) {
                    id
                    name
                }
            }
        """, {"name": f"nexus-{app_name}-{project_id[:8]}"})

        railway_project_id = create_project["projectCreate"]["id"]
        logger.info(f"✅ Railway project created: {railway_project_id}")

        # Step 2 — Create an environment
        env_data = await self._gql("""
            mutation CreateEnvironment($projectId: String!) {
                environmentCreate(input: { projectId: $projectId, name: "production" }) {
                    id
                }
            }
        """, {"projectId": railway_project_id})

        environment_id = env_data["environmentCreate"]["id"]

        # Step 3 — Create a service (this is where the app runs)
        service_data = await self._gql("""
            mutation CreateService($projectId: String!, $name: String!) {
                serviceCreate(input: { projectId: $projectId, name: $name }) {
                    id
                }
            }
        """, {"projectId": railway_project_id, "name": app_name})

        service_id = service_data["serviceCreate"]["id"]
        logger.info(f"✅ Railway service created: {service_id}")

        # Step 4 — Upload source and trigger deployment
        # Railway CLI handles the actual file upload — we shell out to it
        import subprocess
        import shutil

        # Check if railway CLI is available
        if not shutil.which("railway"):
            logger.warning("Railway CLI not found — install with: npm install -g @railway/cli")
            # Return partial success with instructions
            return {
                "status": "partial",
                "provider": "railway",
                "project_id": project_id,
                "railway_project_id": railway_project_id,
                "message": "Railway project created but CLI needed for file upload. Run: railway up",
                "deploy_url": f"https://railway.app/project/{railway_project_id}",
                "manual_steps": [
                    f"cd {generated_code_path}",
                    f"railway link {railway_project_id}",
                    "railway up"
                ]
            }

        # Link and deploy via CLI
        result = subprocess.run(
            ["railway", "up", "--detach"],
            cwd=str(generated_code_path),
            env={**os.environ, "RAILWAY_TOKEN": self.token, "RAILWAY_PROJECT_ID": railway_project_id},
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            raise Exception(f"Railway deploy failed: {result.stderr}")

        logger.info("✅ Railway deployment triggered")

        # Step 5 — Get the deployment URL
        # Poll until domain is available (Railway auto-generates one)
        deploy_url = await self._get_deployment_url(railway_project_id, service_id)

        return {
            "status": "success",
            "provider": "railway",
            "project_id": project_id,
            "railway_project_id": railway_project_id,
            "deploy_url": deploy_url,
            "dashboard_url": f"https://railway.app/project/{railway_project_id}",
        }

    async def _get_deployment_url(self, railway_project_id: str, service_id: str) -> str:
        """Poll Railway until the deployment URL is available"""
        for _ in range(12):  # try for ~60 seconds
            await asyncio.sleep(5)
            try:
                data = await self._gql("""
                    query GetServiceDomain($serviceId: String!) {
                        service(id: $serviceId) {
                            domains {
                                edges {
                                    node {
                                        domain
                                    }
                                }
                            }
                        }
                    }
                """, {"serviceId": service_id})

                edges = data["service"]["domains"]["edges"]
                if edges:
                    domain = edges[0]["node"]["domain"]
                    return f"https://{domain}"
            except Exception:
                pass

        return f"https://railway.app/project/{railway_project_id}"  # fallback


class ACADeploymentProvider(DeploymentProvider):
    """
    Azure Container Apps deployment — implement later.
    Swap DEPLOYMENT_PROVIDER=aca in .env to activate.
    """
    async def deploy(self, project_id: str, app_name: str, generated_code_path: Path) -> Dict:
        raise NotImplementedError("ACA deployment not yet implemented — use Railway for now")


def get_deployment_provider() -> DeploymentProvider:
    """Factory — reads DEPLOYMENT_PROVIDER env var to pick the right provider"""
    provider = os.getenv("DEPLOYMENT_PROVIDER", "railway").lower()
    if provider == "railway":
        return RailwayDeploymentProvider()
    elif provider == "aca":
        return ACADeploymentProvider()
    else:
        raise ValueError(f"Unknown deployment provider: {provider}")
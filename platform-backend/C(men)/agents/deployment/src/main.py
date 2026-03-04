import os
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
import sys
import subprocess

sys.path.append(r"C:\Users\hritp\OneDrive\Desktop\Microsoft Hackathon\C(men)")
from shared.clients import call_gpt4o, call_gpt4o_mini

load_dotenv()

app = FastAPI(title="Deployment Agent")

# ─────────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────────

class ProjectConfig(BaseModel):
    project_id: str
    app_name: str
    app_type: str          # "fastapi", "express", "react", "nextjs"
    language: str          # "python", "node", "typescript"
    port: Optional[int] = 8000
    env_vars: Optional[list[str]] = []
    azure_resources: Optional[list[str]] = ["cosmos_db", "blob_storage", "key_vault"]
    description: Optional[str] = ""

class BundleResult(BaseModel):
    project_id: str
    dockerfile: str
    bicep: str
    github_actions: str
    readme: str

class BlueprintResult(BaseModel):
    project_id: str
    agents: list[dict]
    azure_resources: list[dict]
    data_flows: list[dict]
    generated_at: str

class CostEstimate(BaseModel):
    project_id: str
    total_monthly_usd: float
    breakdown: list[dict]
    assumptions: list[str]
    generated_at: str

# ─────────────────────────────────────────────
# GENERATORS
# ─────────────────────────────────────────────

def generate_dockerfile(config: ProjectConfig) -> str:
    templates = {
        "fastapi": f"""FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE {config.port}
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "{config.port}"]""",

        "express": f"""FROM node:20-alpine
WORKDIR /app
COPY package*.json .
RUN npm install
COPY . .
EXPOSE {config.port}
CMD ["node", "index.js"]""",

        "react": f"""FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json .
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/build /usr/share/nginx/html
EXPOSE 80""",

        "nextjs": f"""FROM node:20-alpine
WORKDIR /app
COPY package*.json .
RUN npm install
COPY . .
RUN npm run build
EXPOSE {config.port}
CMD ["npm", "start"]"""
    }
    return templates.get(config.app_type, templates["fastapi"])


def generate_bicep(config: ProjectConfig) -> str:
    resources = config.azure_resources or []

    cosmos = """
resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' = {
  name: '${appName}-cosmos'
  location: location
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [{ locationName: location }]
  }
}""" if "cosmos_db" in resources else ""

    blob = """
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: '${appName}storage'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
}""" if "blob_storage" in resources else ""

    keyvault = """
resource keyVault 'Microsoft.KeyVault/vaults@2023-02-01' = {
  name: '${appName}-kv'
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableSoftDelete: true
  }
}""" if "key_vault" in resources else ""

    return f"""param appName string = '{config.app_name}'
param location string = resourceGroup().location
param acrName string = 'nexusacrteam'

resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {{
  name: '${{appName}}-env'
  location: location
  properties: {{}}
}}

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {{
  name: appName
  location: location
  properties: {{
    managedEnvironmentId: containerAppEnv.id
    configuration: {{
      ingress: {{
        external: true
        targetPort: {config.port}
      }}
    }}
    template: {{
      containers: [{{
        name: appName
        image: '${{acrName}}.azurecr.io/{config.app_name}:latest'
        resources: {{
          cpu: '0.5'
          memory: '1Gi'
        }}
      }}]
    }}
  }}
}}
{cosmos}
{blob}
{keyvault}"""


def generate_github_actions(config: ProjectConfig) -> str:
    return f"""name: Deploy {config.app_name}

on:
  push:
    branches: [main]
  workflow_dispatch:

env:
  ACR_NAME: nexusacrteam.azurecr.io
  APP_NAME: {config.app_name}

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v3

      - name: Login to Azure
        uses: azure/login@v1
        with:
          creds: ${{{{ secrets.AZURE_CREDENTIALS }}}}

      - name: Login to ACR
        run: az acr login --name nexusacrteam

      - name: Build Docker image
        run: docker build -t ${{{{ env.ACR_NAME }}}}/${{{{ env.APP_NAME }}}}:${{{{ github.sha }}}} .

      - name: Push to ACR
        run: docker push ${{{{ env.ACR_NAME }}}}/${{{{ env.APP_NAME }}}}:${{{{ github.sha }}}}

      - name: Deploy to ACA
        run: |
          az containerapp update \\
            --name ${{{{ env.APP_NAME }}}} \\
            --resource-group {os.getenv('PROJECT_RESOURCE_GROUP', 'agentic-nexus')} \\
            --image ${{{{ env.ACR_NAME }}}}/${{{{ env.APP_NAME }}}}:${{{{ github.sha }}}}

      - name: Health check
        run: sleep 30 && curl --fail https://${{{{ env.APP_NAME }}}}.azurecontainerapps.io/health"""


def generate_readme(config: ProjectConfig) -> str:
    prompt = f"""
    Generate a professional README.md for a project with these details:
    - App name: {config.app_name}
    - Type: {config.app_type}
    - Language: {config.language}
    - Description: {config.description}
    - Azure resources used: {config.azure_resources}
    - Port: {config.port}

    Include sections: Overview, Architecture, Setup, Environment Variables, Running Locally, Deployment.
    Keep it concise and professional.
    """
    return call_gpt4o_mini(prompt)


def generate_blueprint(config: ProjectConfig) -> dict:
    prompt = f"""
    Generate a system blueprint JSON for a project called '{config.app_name}'.
    Description: {config.description}
    App type: {config.app_type}
    Azure resources: {config.azure_resources}

    Return a JSON object with exactly these fields:
    - agents: list of agent objects, each with: name, role, endpoints, model
    - azure_resources: list of resource objects, each with: name, type, purpose
    - data_flows: list of flow objects, each with: from, to, description

    Include these Agentic Nexus agents:
    - Director Agent (orchestration)
    - QA Engineer Agent (testing)
    - Healer Agent (auto repair)
    - Deployment Agent (shipping)
    - Data Ingestion Agent (parsing)

    Return JSON only, no explanation.
    """
    raw_response = call_gpt4o(prompt)
    try:
        clean = raw_response.strip().replace("```json", "").replace("```", "")
        return json.loads(clean)
    except Exception:
        return {
            "agents": [],
            "azure_resources": [],
            "data_flows": []
        }


def estimate_cost(config: ProjectConfig) -> dict:
    prompt = f"""
    Estimate the monthly Azure cost for a project with these resources:
    - App type: {config.app_type}
    - Azure resources: {config.azure_resources}
    - Expected port/replicas: 1 replica, {config.port}

    Use these Azure pricing assumptions:
    - Azure Container Apps: ~$0.000024 per vCPU-second, ~$0.000003 per GiB-second
    - Cosmos DB: ~$0.008 per RU/s per hour, assume 400 RU/s
    - Blob Storage: ~$0.018 per GB, assume 10GB
    - Key Vault: ~$0.03 per 10,000 operations
    - Azure Container Registry: ~$5/month for Standard tier
    - Service Bus: ~$0.05 per million operations

    Return a JSON object with exactly these fields:
    - total_monthly_usd: a single float number
    - breakdown: list of objects, each with: resource, tier, monthly_usd, notes
    - assumptions: list of assumption strings used in calculation

    Return JSON only, no explanation.
    """
    raw_response = call_gpt4o(prompt)
    try:
        clean = raw_response.strip().replace("```json", "").replace("```", "")
        return json.loads(clean)
    except Exception:
        return {
            "total_monthly_usd": 0.0,
            "breakdown": [],
            "assumptions": []
        }

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "agent": "deployment"}

@app.post("/build-bundle")
def build_bundle(config: ProjectConfig):
    try:
        dockerfile = generate_dockerfile(config)
        bicep = generate_bicep(config)
        github_actions = generate_github_actions(config)
        readme = generate_readme(config)

        bundle = BundleResult(
            project_id=config.project_id,
            dockerfile=dockerfile,
            bicep=bicep,
            github_actions=github_actions,
            readme=readme
        )

        return {"status": "success", "bundle": bundle.dict()}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ship")
def ship(config: ProjectConfig):
    try:
        image_tag = f"nexusacrteam.azurecr.io/{config.app_name}:latest"
        project_root = r"C:\Users\hritp\OneDrive\Desktop\Microsoft Hackathon\C(men)"

        # Step 1: Build
        print(f"Building image: {image_tag}")
        build_result = subprocess.run(
    ["docker", "build", 
     "-f", "agents/deployment/Dockerfile", 
     "-t", image_tag, 
     "."],
    cwd=r"C:\Users\hritp\OneDrive\Desktop\Microsoft Hackathon\C(men)",
    capture_output=True,
    text=True
)
        if build_result.returncode != 0:
            raise Exception(f"Docker build failed: {build_result.stderr}")
        print("Build successful")

        # Step 2: Push
        print(f"Pushing image: {image_tag}")
        push_result = subprocess.run(
            ["docker", "push", image_tag],
            cwd=project_root,
            capture_output=True,
            text=True
        )
        if push_result.returncode != 0:
            raise Exception(f"Docker push failed: {push_result.stderr}")
        print("Push successful")

        # Extract digest from push output
        digest = ""
        for line in push_result.stdout.split("\n"):
            if "digest:" in line.lower():
                digest = line.strip()
                break

        return {
            "status": "shipped",
            "project_id": config.project_id,
            "image": image_tag,
            "digest": digest,
            "target": "Azure Container Apps",
            "resource_group": os.getenv("PROJECT_RESOURCE_GROUP", "agentic-nexus")
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/blueprint")
def blueprint(config: ProjectConfig):
    try:
        from datetime import datetime
        result = generate_blueprint(config)
        blueprint = BlueprintResult(
            project_id=config.project_id,
            agents=result.get("agents", []),
            azure_resources=result.get("azure_resources", []),
            data_flows=result.get("data_flows", []),
            generated_at=datetime.utcnow().isoformat()
        )
        return {"status": "success", "blueprint": blueprint.dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/estimate-cost")
def estimate_cost_endpoint(config: ProjectConfig):
    try:
        from datetime import datetime
        result = estimate_cost(config)
        estimate = CostEstimate(
            project_id=config.project_id,
            total_monthly_usd=result.get("total_monthly_usd", 0.0),
            breakdown=result.get("breakdown", []),
            assumptions=result.get("assumptions", []),
            generated_at=datetime.utcnow().isoformat()
        )
        return {"status": "success", "estimate": estimate.dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# Azure Container Deployment Guide

## Overview

This guide walks through deploying Agentic Nexus Backend to Azure Container Apps, connected with Azure Static Web Apps frontend.

## Architecture

```
Azure Static Web App (Frontend)
            ↓
    CORS-enabled requests
            ↓
Azure Container Apps (Backend FastAPI)
            ↓
    ├── Azure Cosmos DB (Data)
    ├── Azure Service Bus (Messaging)
    ├── Azure Container Registry (Images)
    └── Azure Storage (Artifacts)
```

## Prerequisites

- Azure CLI: `az --version`
- Docker: `docker --version`
- Git
- An Azure subscription with:
  - Container Registry
  - Container Apps Environment
  - Cosmos DB (optional)
  - Service Bus (optional)

## Step 1: Create Azure Resources

### 1.1 Create Resource Group

```bash
export RESOURCE_GROUP=agentic-nexus-rg
export LOCATION=eastus

az group create \
  --name $RESOURCE_GROUP \
  --location $LOCATION
```

### 1.2 Create Container Registry

```bash
export REGISTRY_NAME=nexusacrteam

az acr create \
  --resource-group $RESOURCE_GROUP \
  --name $REGISTRY_NAME \
  --sku Standard \
  --admin-enabled true
```

Get login credentials:
```bash
az acr credential show --name $REGISTRY_NAME
```

### 1.3 Create Container Apps Environment

```bash
export ENVIRONMENT_NAME=agentic-nexus-env

az containerapp env create \
  --name $ENVIRONMENT_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION
```

### 1.4 (Optional) Create Cosmos DB

```bash
export COSMOS_NAME=agentic-nexus-cosmos

az cosmosdb create \
  --name $COSMOS_NAME \
  --resource-group $RESOURCE_GROUP \
  --default-consistency-level Strong \
  --locations regionName=$LOCATION failoverPriority=0
```

## Step 2: Build and Push Docker Image

### 2.1 Build Image Locally

```bash
docker build -t $REGISTRY_NAME.azurecr.io/agentic-nexus:latest .
```

### 2.2 Push to ACR

```bash
# Login to registry
az acr login --name $REGISTRY_NAME

# Push image
docker push $REGISTRY_NAME.azurecr.io/agentic-nexus:latest
```

Verify:
```bash
az acr repository list --name $REGISTRY_NAME
```

## Step 3: Deploy Container App

### 3.1 Create Container App

```bash
export CONTAINER_APP_NAME=agentic-nexus-api
export CONTAINER_PORT=8000

az containerapp create \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --environment $ENVIRONMENT_NAME \
  --image $REGISTRY_NAME.azurecr.io/agentic-nexus:latest \
  --target-port $CONTAINER_PORT \
  --ingress external \
  --cpu 0.5 \
  --memory 1.0Gi \
  --env-vars \
    ENVIRONMENT=production \
    LOG_LEVEL=INFO \
    AZURE_CONTAINER_REGISTRY=$REGISTRY_NAME \
  --registry-login-server $REGISTRY_NAME.azurecr.io \
  --registry-username <username> \
  --registry-password <password>
```

### 3.2 Configure Scaling

```bash
az containerapp update \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --min-replicas 1 \
  --max-replicas 10
```

### 3.3 Get Application URL

```bash
az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query properties.configuration.ingress.fqdn \
  --output tsv
```

Save this URL as your `API_BASE_URL`

## Step 4: Configure Frontend Static Web App

### 4.1 Create Static Web App (if not exists)

```bash
export STATIC_WEB_APP_NAME=agentic-nexus-web

az staticwebapp create \
  --name $STATIC_WEB_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --source https://github.com/<your-org>/<your-frontend-repo> \
  --location $LOCATION \
  --branch main
```

### 4.2 Configure CORS

Create `staticwebapp.config.json` in frontend root:

```json
{
  "globalHeaders": [
    {
      "name": "Access-Control-Allow-Origin",
      "value": "https://<your-static-web-app>.azurestaticapps.net"
    }
  ],
  "routes": [
    {
      "route": "/api/*",
      "rewrite": "https://<container-app-url>/api/*"
    }
  ]
}
```

## Step 5: Environment Configuration

### 5.1 Create .env File

```bash
cp .env.example .env
```

Edit `.env` with your values:

```bash
# Azure credentials
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_KEY=<your-key>

# Container configuration
AZURE_CONTAINER_REGISTRY=nexusacrteam
AZURE_CONTAINER_APP_NAME=agentic-nexus-api
AZURE_RESOURCE_GROUP=agentic-nexus-rg
AZURE_LOCATION=eastus

# Frontend
FRONTEND_URL=https://<your-static-web-app>.azurestaticapps.net
API_BASE_URL=https://<container-app-url>

# Features
ENABLE_CODE_GENERATION=true
ENABLE_DEPLOYMENT=true
```

### 5.2 Update Container App Secrets

```bash
az containerapp secret set \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --secrets \
    azure-openai-key="$AZURE_OPENAI_KEY" \
    cosmos-key="$COSMOS_KEY"
```

## Step 6: CI/CD Pipeline Setup

### 6.1 GitHub Actions Secrets

Add to GitHub repository secrets:

```
REGISTRY_USERNAME       = <acr-username>
REGISTRY_PASSWORD       = <acr-password>
AZURE_CREDENTIALS       = <service-principal-json>
```

Create service principal for GitHub:

```bash
az ad sp create-for-rbac --name "github-agentic-nexus" \
  --role contributor \
  --scopes /subscriptions/{subscription-id}/resourceGroups/{resource-group}
```

### 6.2 GitHub Actions Workflow

Already in `.github/workflows/deploy.yml`

Push to main branch to trigger deployment:

```bash
git push origin main
```

## Step 7: Verification

### 7.1 Health Check

```bash
API_URL=$(az containerapp show \
  --name agentic-nexus-api \
  --resource-group $RESOURCE_GROUP \
  --query properties.configuration.ingress.fqdn \
  --output tsv)

curl https://${API_URL}/api/health
```

### 7.2 Create Test Project

```bash
curl -X POST https://${API_URL}/api/projects \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Test Project",
    "user_intent": "Create a simple FastAPI application",
    "azure_resources": ["cosmos_db"]
  }'
```

### 7.3 Monitor Logs

```bash
az containerapp logs show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --follow
```

## Step 8: Monitoring & Logging

### 8.1 Enable Application Insights (Optional)

```bash
export APP_INSIGHTS_NAME=agentic-nexus-insights

az monitor app-insights component create \
  --app $APP_INSIGHTS_NAME \
  --location $LOCATION \
  --resource-group $RESOURCE_GROUP \
  --application-type web
```

Get instrumentation key:
```bash
az monitor app-insights component show \
  --app $APP_INSIGHTS_NAME \
  --resource-group $RESOURCE_GROUP \
  --query instrumentationKey
```

### 8.2 Configure Alerts

```bash
az monitor metrics alert create \
  --name cpu-high \
  --resource-group $RESOURCE_GROUP \
  --scopes /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.App/containerApps/$CONTAINER_APP_NAME \
  --condition "avg Percentage CPU > 80" \
  --description "Alert when CPU exceeds 80%"
```

## Step 9: Scaling Configuration

### 9.1 Automatic Scaling Rules

```bash
az containerapp update \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --scale-rule-name http-requests \
  --scale-rule-type http \
  --scale-rule-metadata concurrency=100
```

## Troubleshooting

### Issue: Container not starting

```bash
# Check logs
az containerapp logs show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --follow

# Restart container
az containerapp revision restart \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP
```

### Issue: CORS errors

Ensure `FRONTEND_URL` environment variable matches your Static Web App URL.

### Issue: Azure credential errors

Verify credentials are set in Container App environment:

```bash
az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query properties.template.containers[0].env
```

## Cost Estimation

Using recommended configuration:

- **Container Apps**: ~$45-60/month (0.5 vCPU, 1GB RAM)
- **Cosmos DB**: ~$25/month (400 RU/s)
- **Container Registry**: ~$5/month
- **Static Web App**: ~$10/month (free tier has limits)

**Estimated Total**: ~$85-100/month

See cost estimate from API endpoint for precise calculation.

## Cleanup

To delete all resources:

```bash
az group delete \
  --name $RESOURCE_GROUP \
  --yes --no-wait
```

## Next Steps

1. ✅ Deploy backend to Container Apps
2. ✅ Deploy frontend to Static Web App
3. ✅ Configure custom domain
4. ✅ Enable HTTPS (automatic)
5. ✅ Set up monitoring and alerts
6. ✅ Create backup strategy

For API documentation, see [API_DOCUMENTATION.md](API_DOCUMENTATION.md)

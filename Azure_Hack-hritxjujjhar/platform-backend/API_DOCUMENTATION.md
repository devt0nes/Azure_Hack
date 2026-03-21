# Agentic Nexus Backend API Documentation

## Overview

The Agentic Nexus Backend is a FastAPI-based REST API that orchestrates AI agents for automated code generation and deployment. It's designed to run on Azure Container Apps and integrates with Azure Static Web Apps for the frontend.

## Base URL

```
https://<container-app-url>/api
```

## Authentication

Currently, no authentication is required. In production, enable Azure AD authentication via:
- Set `ENABLE_AUTH=true` in environment
- Set `AUTH_PROVIDER=azure-ad`

## API Endpoints

### Health & Status

#### GET /health
Health check endpoint for load balancers and monitoring.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "version": "1.0.0"
}
```

#### GET /status
System status and metrics.

**Response:**
```json
{
  "status": "operational",
  "timestamp": "2024-01-15T10:30:00Z",
  "active_projects": 3,
  "total_projects": 15
}
```

### Projects

#### POST /projects
Create and start a new code generation project.

**Request Body:**
```json
{
  "project_name": "My API",
  "user_intent": "Create a FastAPI backend for document management with authentication and database integration",
  "description": "Optional detailed description",
  "azure_resources": ["cosmos_db", "blob_storage", "key_vault"]
}
```

**Response (202 Accepted):**
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "project_name": "My API",
  "status": "queued",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "user_intent": "Create a FastAPI backend...",
  "progress": 5
}
```

#### GET /projects
List all projects.

**Response:**
```json
{
  "total_projects": 15,
  "projects": [
    {
      "project_id": "550e8400-e29b-41d4-a716-446655440000",
      "project_name": "My API",
      "status": "completed",
      "created_at": "2024-01-15T10:30:00Z",
      "progress": 100
    }
  ]
}
```

#### GET /projects/{project_id}
Get project status and metadata.

**Response:**
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "project_name": "My API",
  "status": "completed",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "user_intent": "Create a FastAPI backend...",
  "progress": 100
}
```

### Artifacts

#### GET /projects/{project_id}/artifacts
List all generated artifacts for a project.

**Response:**
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "artifact_count": 12,
  "artifacts": [
    {
      "name": "main.py",
      "type": "code",
      "size": 2048,
      "created_at": "2024-01-15T10:35:00Z",
      "path": "agents/backend_engineer/main.py"
    },
    {
      "name": "schema.sql",
      "type": "config",
      "size": 512,
      "created_at": "2024-01-15T10:35:00Z",
      "path": "database/schema.sql"
    }
  ]
}
```

#### GET /projects/{project_id}/artifacts/{artifact_name}
Download a specific artifact.

**Response:** File download (binary)

### Logs

#### GET /projects/{project_id}/logs
Get audit logs for a project.

**Response:**
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "logs": {
    "master_audit.log": "2024-01-15T10:30:00Z - Project created...",
    "requirements.log": "2024-01-15T10:32:00Z - Backend Engineer added requirement..."
  }
}
```

### Deployment

#### POST /projects/{project_id}/deploy
Trigger deployment integration to generate Docker, Bicep, and CI/CD artifacts.

**Request Body:**
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "enable_docker_build": true,
  "enable_infrastructure": true,
  "enable_cicd": true
}
```

**Response (202 Accepted):**
```json
{
  "status": "deployment_queued",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Deployment integration started"
}
```

#### GET /projects/{project_id}/deployment-status
Get deployment status and artifacts.

**Response:**
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "deployment_status": "completed",
  "artifacts": [
    {
      "name": "Dockerfile",
      "size": 1024,
      "created_at": "2024-01-15T10:40:00Z"
    },
    {
      "name": "infrastructure.bicep",
      "size": 3072,
      "created_at": "2024-01-15T10:40:00Z"
    },
    {
      "name": "github-actions.yml",
      "size": 2048,
      "created_at": "2024-01-15T10:40:00Z"
    }
  ],
  "cost_estimate_available": true
}
```

#### GET /projects/{project_id}/cost-estimate
Get monthly Azure cost estimate.

**Response:**
```json
{
  "total_monthly_usd": 85.50,
  "breakdown": [
    {
      "resource": "Azure Container Apps",
      "tier": "Standard",
      "monthly_usd": 45.00,
      "notes": "0.5 vCPU, 1GB RAM, 1 replica"
    },
    {
      "resource": "Cosmos DB",
      "tier": "Standard",
      "monthly_usd": 25.00,
      "notes": "400 RU/s"
    },
    {
      "resource": "Azure Container Registry",
      "tier": "Standard",
      "monthly_usd": 5.00,
      "notes": "Standard tier registry"
    }
  ],
  "assumptions": [
    "1 replica running 24/7",
    "Cosmos DB 400 RU/s baseline",
    "10GB blob storage"
  ]
}
```

## Error Handling

All error responses follow this format:

```json
{
  "error": "Description of the error",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### HTTP Status Codes

- `200 OK` - Successful GET request
- `202 Accepted` - Request queued for processing
- `400 Bad Request` - Invalid request parameters
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

## Example Workflows

### Generate Code

1. **Create Project:**
```bash
curl -X POST https://<api-url>/api/projects \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "My App",
    "user_intent": "Create a REST API with FastAPI",
    "azure_resources": ["cosmos_db", "key_vault"]
  }'
```

2. **Poll Status:**
```bash
curl https://<api-url>/api/projects/{project_id}
```

3. **Wait for Status: completed**

### Download Artifacts

```bash
curl https://<api-url>/api/projects/{project_id}/artifacts \
  | jq '.artifacts[] | .path' | while read path; do
  curl -O https://<api-url>/api/projects/{project_id}/artifacts/$(basename $path) \
    -H "Accept: application/octet-stream"
done
```

### Deploy to Production

1. **Trigger Deployment:**
```bash
curl -X POST https://<api-url>/api/projects/{project_id}/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "enable_docker_build": true,
    "enable_infrastructure": true,
    "enable_cicd": true
  }'
```

2. **Check Deployment Status:**
```bash
curl https://<api-url>/api/projects/{project_id}/deployment-status
```

3. **Get Cost Estimate:**
```bash
curl https://<api-url>/api/projects/{project_id}/cost-estimate
```

## Environment Variables

See `.env.example` for complete list. Key variables:

```bash
# Azure
AZURE_CONTAINER_REGISTRY=nexusacrteam
AZURE_CONTAINER_APP_NAME=agentic-nexus-api
AZURE_LOCATION=eastus

# Frontend
FRONTEND_URL=https://<your-static-web-app>.azurestaticapps.net

# Features
ENABLE_CODE_GENERATION=true
ENABLE_DEPLOYMENT=true
MAX_PROJECT_TIMEOUT_SECONDS=3600
```

## Rate Limiting

Currently not implemented. Will be added in production version.

## WebSocket Support (Future)

For real-time project status updates:
```
wss://<api-url>/ws/projects/{project_id}
```

## OpenAPI/Swagger Documentation

Interactive API documentation available at:
```
https://<api-url>/api/docs
```

Alternative Swagger UI:
```
https://<api-url>/api/redoc
```

## Support

For issues or questions, see:
- GitHub: https://github.com/nexus-agentic/backend
- Documentation: See DEPLOYMENT_QUICK_REFERENCE.md

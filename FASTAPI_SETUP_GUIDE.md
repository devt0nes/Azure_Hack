# FastAPI Backend Setup & Deployment Guide

## 🎯 Quick Summary

Your Agentic Nexus codebase has been **fully converted to FastAPI** and optimized for Azure Container Apps deployment. Here's what changed:

### What's New

| Component | Purpose |
|-----------|---------|
| `app.py` | Main FastAPI application with all endpoints |
| `azure_config.py` | Azure-specific configuration |
| `Dockerfile` | Multi-stage Docker build for Azure |
| `docker-compose.yml` | Local development with services |
| `.github/workflows/deploy.yml` | CI/CD pipeline for Azure |
| `API_DOCUMENTATION.md` | Complete API reference |
| `AZURE_DEPLOYMENT_GUIDE.md` | Step-by-step deployment |
| `requirements.txt` | All Python dependencies |
| `.env.example` | Configuration template |

## 🚀 Getting Started

### Option 1: Local Development (Fastest)

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env with your Azure OpenAI credentials

# 2. Install dependencies
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Start the server
uvicorn app:app --reload --host 0.0.0.0 --port 8000

# 4. Visit API docs
# Open browser to: http://localhost:8000/api/docs
```

### Option 2: Docker Local Development

```bash
# Build and run with Docker Compose
docker-compose up --build

# The API will be at http://localhost:8000/api/docs
```

### Option 3: Azure Container Apps (Production)

See [AZURE_DEPLOYMENT_GUIDE.md](AZURE_DEPLOYMENT_GUIDE.md) for complete instructions.

Quick start:
```bash
# Set environment variables
export RESOURCE_GROUP=agentic-nexus-rg
export REGISTRY_NAME=nexusacrteam
export CONTAINER_APP_NAME=agentic-nexus-api

# Build and push image
docker build -t $REGISTRY_NAME.azurecr.io/agentic-nexus:latest .
docker push $REGISTRY_NAME.azurecr.io/agentic-nexus:latest

# Deploy to Azure
az containerapp create \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --image $REGISTRY_NAME.azurecr.io/agentic-nexus:latest \
  --target-port 8000 \
  --ingress external
```

## 📊 API Architecture

### Main Endpoints

```
POST   /api/projects                          # Create new project
GET    /api/projects                          # List all projects
GET    /api/projects/{project_id}             # Get project status

GET    /api/projects/{project_id}/artifacts   # List generated files
GET    /api/projects/{project_id}/artifacts/{name}  # Download file

POST   /api/projects/{project_id}/deploy      # Start deployment
GET    /api/projects/{project_id}/deployment-status

GET    /api/projects/{project_id}/cost-estimate  # Cost breakdown
GET    /api/projects/{project_id}/logs           # Audit logs

GET    /api/health                            # Health check
GET    /api/status                            # System status
```

### Example: Create a Project

```bash
curl -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Document API",
    "user_intent": "Create a FastAPI backend for document management with authentication and database",
    "azure_resources": ["cosmos_db", "blob_storage", "key_vault"]
  }'
```

Response:
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "project_name": "Document API",
  "status": "queued",
  "progress": 5,
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Example: Check Status

```bash
curl http://localhost:8000/api/projects/550e8400-e29b-41d4-a716-446655440000
```

### Example: Download Artifacts

```bash
# List artifacts
curl http://localhost:8000/api/projects/550e8400-e29b-41d4-a716-446655440000/artifacts

# Download a specific file
curl http://localhost:8000/api/projects/550e8400-e29b-41d4-a716-446655440000/artifacts/main.py \
  -o main.py
```

## 🔧 Configuration

### Environment Variables

Required:
```bash
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://xxx.openai.azure.com/
AZURE_OPENAI_KEY=your-key-here
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

Optional:
```bash
# Container configuration
CONTAINER_PORT=8000
CONTAINER_CPU=0.5
CONTAINER_MEMORY=1Gi

# Frontend integration
FRONTEND_URL=https://your-static-web-app.azurestaticapps.net
API_BASE_URL=https://your-api-url

# Features
ENABLE_CODE_GENERATION=true
ENABLE_DEPLOYMENT=true
```

See `.env.example` for complete list.

## 📦 Docker Deployment

### Build Image

```bash
docker build -t agentic-nexus:latest .
```

### Run Container

```bash
docker run -p 8000:8000 \
  --env-file .env \
  agentic-nexus:latest
```

### Multi-stage Build Benefits

- **Smaller final image** (Python 3.11 slim base)
- **Faster builds** (wheels cached)
- **Production ready** (no build tools in final image)
- **Security** (minimal attack surface)

## 🏗️ System Architecture

### Background Processing

The API uses `BackgroundTasks` for long-running operations:

```python
@app.post("/api/projects")
async def create_project(request: CreateProjectRequest, background_tasks: BackgroundTasks):
    # Create project immediately
    project_id = project_manager.create_project(...)
    
    # Queue code generation as background task
    background_tasks.add_task(
        OrchestrationService.generate_code,
        project_id,
        project
    )
    
    # Return project_id for tracking
    return {"project_id": project_id, "status": "queued"}
```

Clients poll for status:
```python
GET /api/projects/{project_id}  # Returns current progress
```

### Project Tracking

```python
class ProjectManager:
    projects: Dict[str, Dict]  # In-memory storage
    
    # In production, use Cosmos DB:
    # cosmos.save_project(project_id, project_data)
```

## 🔐 Security Considerations

### Current (Development)
- No authentication required
- CORS allows all origins
- Runs on HTTP localhost

### Production Checklist
- [ ] Enable Azure AD authentication
- [ ] Restrict CORS to frontend domain
- [ ] Use HTTPS only
- [ ] Store secrets in Key Vault
- [ ] Enable rate limiting
- [ ] Set up WAF rules
- [ ] Enable logging to Application Insights
- [ ] Regular security scanning

Enable in `.env`:
```bash
ENABLE_AUTH=true
AUTH_PROVIDER=azure-ad
FRONTEND_URL=https://your-domain.azurestaticapps.net
```

## 📈 Performance Tuning

### Container Configuration

```bash
# Memory & CPU
CONTAINER_CPU=0.5      # 0.5 vCPU (500m)
CONTAINER_MEMORY=1Gi   # 1GB RAM

# Scaling
CONTAINER_REPLICAS_MIN=1
CONTAINER_REPLICAS_MAX=10
```

### Code Generation Timeout

```bash
MAX_PROJECT_TIMEOUT_SECONDS=3600  # 1 hour
AGENT_TIMEOUT_SECONDS=300         # 5 minutes per agent
```

## 🧪 Testing

### Health Check

```bash
curl http://localhost:8000/api/health
```

Expected response:
```json
{"status": "healthy", "timestamp": "...", "version": "1.0.0"}
```

### Full Workflow Test

```bash
# 1. Create project
PROJECT=$(curl -s -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{"project_name":"Test","user_intent":"FastAPI app"}' | jq -r .project_id)

echo "Project ID: $PROJECT"

# 2. Poll for completion
for i in {1..60}; do
  STATUS=$(curl -s http://localhost:8000/api/projects/$PROJECT | jq -r .status)
  PROGRESS=$(curl -s http://localhost:8000/api/projects/$PROJECT | jq -r .progress)
  echo "Status: $STATUS, Progress: $PROGRESS%"
  
  if [ "$STATUS" = "completed" ]; then
    echo "✅ Generation complete"
    break
  fi
  
  sleep 5
done

# 3. List artifacts
curl http://localhost:8000/api/projects/$PROJECT/artifacts | jq .
```

## 📚 Frontend Integration

### CORS Configuration

If frontend is at `https://myapp.azurestaticapps.net`:

```python
# In app.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://myapp.azurestaticapps.net"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### API Integration Example (React)

```javascript
// Create project
const response = await fetch('https://api.example.com/api/projects', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    project_name: 'My App',
    user_intent: 'Create a REST API'
  })
});

const project = await response.json();
const projectId = project.project_id;

// Poll for status
const pollStatus = async () => {
  const response = await fetch(`https://api.example.com/api/projects/${projectId}`);
  const project = await response.json();
  return project.status;
};
```

## 🐛 Troubleshooting

### Issue: "Module not found: app"

**Solution**: Ensure you're running `uvicorn app:app` from the project root directory.

### Issue: Azure credential errors

**Solution**: Verify credentials in `.env`:
```bash
# Check if values are present
grep -E "AZURE_OPENAI_(ENDPOINT|KEY)" .env
```

### Issue: Port 8000 already in use

**Solution**: Use different port:
```bash
uvicorn app:app --port 8001
```

### Issue: Docker build fails

**Solution**: Check Docker is running:
```bash
docker ps  # Should show running containers
```

## 📖 Documentation Structure

```
README.md                        # This file
API_DOCUMENTATION.md             # API reference
AZURE_DEPLOYMENT_GUIDE.md        # Step-by-step Azure setup
DEPLOYMENT_INTEGRATION_SUMMARY.md
DEPLOYMENT_QUICK_REFERENCE.md
azure_config.py                  # Azure configuration
.env.example                     # Configuration template
.github/workflows/deploy.yml     # CI/CD pipeline
```

## ✨ Key Features

✅ **Production Ready**
- FastAPI with async/await
- Type hints and validation
- Comprehensive error handling
- Health checks and monitoring

✅ **Azure Native**
- Container Apps compatible
- Static Web App integration
- Cosmos DB ready
- Service Bus messaging

✅ **Developer Friendly**
- Interactive Swagger UI
- Docker Compose for local dev
- Detailed logging
- Background task tracking

✅ **Scalable**
- Auto-scaling configuration
- Efficient resource usage
- Async background processing
- In-memory caching (upgradeable to Redis)

## 🎓 Next Steps

1. **Local Development**
   ```bash
   cp .env.example .env
   # Fill in Azure credentials
   docker-compose up
   ```

2. **Test API**
   - Visit http://localhost:8000/api/docs
   - Create a project
   - Monitor generation

3. **Deploy to Azure**
   - Follow AZURE_DEPLOYMENT_GUIDE.md
   - Set up GitHub Actions secrets
   - Push to main branch

4. **Monitor in Production**
   - Check logs in Azure Portal
   - Set up alerts
   - Track cost usage

## 📞 Support

- **API Docs**: `/api/docs`
- **OpenAPI**: `/api/openapi.json`
- **Health**: `/api/health`
- **Issues**: Check troubleshooting above

---

**Ready to deploy?** Follow the [Azure Deployment Guide](AZURE_DEPLOYMENT_GUIDE.md) for step-by-step instructions.

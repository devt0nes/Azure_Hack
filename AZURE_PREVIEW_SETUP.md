# Azure Container & Preview Setup Guide

## Problem Summary

1. **Docker image not in ACR**: The `nexus-test-runner:latest` image doesn't exist in the registry, causing smoke tests to fail with `InaccessibleImage`.
2. **Preview not displaying**: The frontend preview iframe wasn't properly falling back to workspace files when remote preview wasn't available.

## Solutions Implemented

### 1. Build & Push Docker Image

A script has been created to build and push the image to your ACR:

```bash
bash /home/frozer/Desktop/nexus-new/build-and-push-container.sh
```

**What it does:**
- Verifies Azure CLI authentication
- Checks ACR exists (`nipunregistry.azurecr.io`)
- Authenticates Docker with ACR
- Builds the Docker image from `platform-backend/Dockerfile`
- Pushes the image to `nipunregistry.azurecr.io/nexus-test-runner:latest`

**Prerequisites:**
- `az login` must be active
- Docker daemon must be running
- You must have push permissions on the ACR

### 2. Fixed Preview Display Logic

Updated [platform-frontend/src/pages/Preview.jsx](src/pages/Preview.jsx) to:
- Always compute `apiBase` early to avoid undefined references
- Add fallback: if preview_ready exists with an entry, use the workspace API route `/api/preview/{project}/{entry}`
- Properly chain preview status → progress → fallback logic
- Never leave preview blank if frontend files exist locally

**Preview priority (in order):**
1. Remote Azure container URL (if deployment succeeded)
2. Workspace local preview via `/api/preview/...` endpoint
3. No preview if no frontend artifacts yet

### 3. Fixed ACR Credential Auto-Fetch

Updated [platform-backend/azure_container_test_runner.py](azure_container_test_runner.py) to:
- Auto-fetch ACR credentials from `az acr credential show` if env vars not set
- Properly attach credentials to ACI image pull
- Graceful fallback if credentials unavailable (warning-only, not fatal)

## Next Steps

### 1. Build & Push the Container Image

```bash
bash /home/frozer/Desktop/nexus-new/build-and-push-container.sh
```

This will:
- Build the Dockerfile from platform-backend
- Push to `nipunregistry.azurecr.io/nexus-test-runner:latest`
- Take ~5-10 minutes

### 2. Restart Backend Service

After image is pushed, restart the backend so it picks up new config and auto-fetch logic:

```bash
# Kill any running backend
pkill -f "python.*backend_platform"

# Restart backend
cd /home/frozer/Desktop/nexus-new/platform-backend
python backend_platform.py
```

### 3. Test the Flow

1. Open frontend in browser
2. Create a new project (or use existing one)
3. Click "Preview" tab
4. Should see either:
   - Azure container URL (if deployment succeeded)
   - Workspace preview (generated frontend files)
   - Waiting message (if still generating)

### 4. Optional: Deploy to Azure for Remote Preview

If you want fully remote preview on Azure:

```bash
# In frontend Preview tab, click "Deploy" → "Deploy to Azure"
# This triggers auto-deploy with credentials from env
```

## Configuration Reference

**Environment Variables** (`.env`):

```
# ACR Configuration
AZURE_CONTAINER_REGISTRY=nipunregistry
AZURE_CONTAINER_REPOSITORY=nexus-test-runner
AZURE_CONTAINER_TAG=latest

# Optional: explicit ACR credentials (auto-fetch from CLI if not set)
# AZURE_CONTAINER_REGISTRY_USERNAME=<username>
# AZURE_CONTAINER_REGISTRY_PASSWORD=<password>

# Smoke Tests
RUN_SMOKE_TESTS_IN_AZURE_CONTAINER=true

# Remote Preview (Auto-Deploy)
ENABLE_AUTO_REMOTE_PREVIEW=true
REMOTE_PREVIEW_DEPLOY_COOLDOWN_SECONDS=120
AZURE_FRONTEND_MIN_REPLICAS=1
AZURE_FRONTEND_MAX_REPLICAS=2
```

## Troubleshooting

### Docker image still inaccessible after push

```bash
# Verify image exists in ACR
az acr repository list -n nipunregistry

# Check image tags
az acr repository show -n nipunregistry --repository nexus-test-runner
```

### Preview shows blank iframe

Check browser console for errors:
- If CORS error: verify API base URL is correct
- If 404: frontend artifacts may not be generated yet
- If inaccessible remote: wait for deployment to complete

### az acr login fails

```bash
# Re-authenticate
az login

# Or use credentials directly
az acr credential show -n nipunregistry
# Then: docker login -u <username> -p <password> nipunregistry.azurecr.io
```

## Files Modified

1. **platform-frontend/src/pages/Preview.jsx** - Fixed preview fallback logic
2. **platform-backend/azure_container_test_runner.py** - Added auto-fetch ACR credentials
3. **platform-backend/backend_platform.py** - Added auto-remote-preview deployment
4. **platform-backend/.env** - Added remote preview configuration
5. **build-and-push-container.sh** - NEW: Script to build and push Docker image

---

**Current Status:**
- ✅ ACR credentials auto-fetch implemented
- ✅ Preview fallback chain fixed
- ⏳ Docker image needs to be built and pushed (run the script)
- ⏳ Backend needs restart after image is pushed

#!/bin/bash
# Build and push Docker image to Azure Container Registry

set -e

REGISTRY_NAME="nipunregistry"
REGISTRY_URL="${REGISTRY_NAME}.azurecr.io"
IMAGE_NAME="nexus-test-runner"
IMAGE_TAG="latest"
FULL_IMAGE="${REGISTRY_URL}/${IMAGE_NAME}:${IMAGE_TAG}"

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/platform-backend" && pwd)"
RESOURCE_GROUP="Nipun-Bhattad-RG"

echo "=========================================="
echo "Building and pushing Docker image"
echo "=========================================="
echo "Registry: $REGISTRY_URL"
echo "Image: $FULL_IMAGE"
echo "Working directory: $BACKEND_DIR"
echo ""

# Step 1: Verify Azure CLI is logged in
echo "[1/5] Verifying Azure CLI authentication..."
if ! az account show > /dev/null 2>&1; then
  echo "ERROR: Not logged into Azure. Run: az login"
  exit 1
fi
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo "✓ Logged in to Azure (Subscription: $SUBSCRIPTION_ID)"
echo ""

# Step 2: Verify ACR exists
echo "[2/5] Checking Azure Container Registry..."
if ! az acr show -n "$REGISTRY_NAME" -g "$RESOURCE_GROUP" > /dev/null 2>&1; then
  echo "ERROR: ACR '$REGISTRY_NAME' not found in resource group '$RESOURCE_GROUP'"
  echo "Available registries:"
  az acr list -o table
  exit 1
fi
echo "✓ ACR found: $REGISTRY_URL"
echo ""

# Step 3: Login Docker to ACR
echo "[3/5] Authenticating Docker with ACR..."
az acr login -n "$REGISTRY_NAME" --expose-token | grep -q "You can now use your token as password" && echo "✓ Docker authenticated with ACR" || {
  # Try alternative approach
  PASSWORD=$(az acr credential show -n "$REGISTRY_NAME" --query 'passwords[0].value' -o tsv)
  USERNAME=$(az acr credential show -n "$REGISTRY_NAME" --query 'username' -o tsv)
  echo "$PASSWORD" | docker login -u "$USERNAME" --password-stdin "$REGISTRY_URL" > /dev/null 2>&1
  echo "✓ Docker authenticated with ACR (via credentials)"
}
echo ""

# Step 4: Build Docker image
echo "[4/5] Building Docker image: $FULL_IMAGE"
echo "This may take a few minutes..."
cd "$BACKEND_DIR"
if docker build -t "$FULL_IMAGE" -f Dockerfile . 2>&1 | tail -20; then
  echo "✓ Docker image built successfully"
else
  echo "ERROR: Docker build failed"
  exit 1
fi
echo ""

# Step 5: Push to ACR
echo "[5/5] Pushing image to ACR..."
if docker push "$FULL_IMAGE" 2>&1 | tail -20; then
  echo "✓ Image pushed successfully"
else
  echo "ERROR: Docker push failed"
  exit 1
fi
echo ""

echo "=========================================="
echo "✓ SUCCESS!"
echo "=========================================="
echo "Image is now available at: $FULL_IMAGE"
echo ""
echo "Next steps:"
echo "1. The Azure smoke tests can now pull this image"
echo "2. Container apps deployments will use this image"
echo "3. Preview should start working once deployment completes"
echo ""

#!/bin/bash
# Upload dist/ to Azure Blob Storage $web container for static site hosting
# Usage: ./upload-dist-to-azure.sh

set -e

if [ ! -d "dist" ]; then
  echo "dist/ directory not found. Run 'npm run build' first."
  exit 1
fi

# Set your storage account and container
STORAGE_ACCOUNT=${AZURE_STORAGE_ACCOUNT:-agenticnexusstorage}
CONTAINER_NAME="$web"

# az login and az storage blob upload-batch required
az storage blob upload-batch \
  --account-name "$STORAGE_ACCOUNT" \
  --destination "$CONTAINER_NAME" \
  --source "dist" \
  --overwrite

echo "dist/ uploaded to Azure Blob Storage $web container."

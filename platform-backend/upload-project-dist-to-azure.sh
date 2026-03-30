#!/bin/bash
# Usage: ./upload-project-dist-to-azure.sh <project_id>
# Builds and uploads the dist/ for the given project to the $web container in Azure Storage

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <project_id>"
  exit 1
fi

PROJECT_ID="$1"
STORAGE_ACCOUNT=${AZURE_STORAGE_ACCOUNT:-agenticnexusstorage}
CONTAINER_NAME="$web"

# Path to the project frontend directory
target_dir="../project_workspace/$PROJECT_ID/runtime/workspace/frontend"

if [ ! -d "$target_dir" ]; then
  echo "Frontend directory not found: $target_dir"
  exit 1
fi

cd "$target_dir"

# Build the frontend (assumes package.json and build script exist)
npm install
npm run build

if [ ! -d "dist" ]; then
  echo "dist/ directory not found after build."
  exit 1
fi

# Upload dist/ to Azure $web container
az storage blob upload-batch \
  --account-name "$STORAGE_ACCOUNT" \
  --destination "$CONTAINER_NAME" \
  --source "dist" \
  --overwrite

echo "dist/ for project $PROJECT_ID uploaded to Azure $web container."

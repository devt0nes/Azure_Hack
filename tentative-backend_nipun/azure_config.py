"""
Azure deployment configuration for Agentic Nexus
Handles Azure Container Apps and Static Web App integration
"""

import os
from typing import Optional

# ==========================================
# AZURE CONFIGURATION
# ==========================================

# Container Registry
AZURE_CONTAINER_REGISTRY = os.getenv("AZURE_CONTAINER_REGISTRY", "nexusacrteam")
ACR_LOGIN_SERVER = f"{AZURE_CONTAINER_REGISTRY}.azurecr.io"
ACR_IMAGE_NAME = os.getenv("ACR_IMAGE_NAME", "agentic-nexus")
ACR_IMAGE_TAG = os.getenv("ACR_IMAGE_TAG", "latest")
ACR_IMAGE_FULL = f"{ACR_LOGIN_SERVER}/{ACR_IMAGE_NAME}:{ACR_IMAGE_TAG}"

# Container Apps
AZURE_CONTAINER_APP_NAME = os.getenv("AZURE_CONTAINER_APP_NAME", "agentic-nexus-api")
AZURE_RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP", "agentic-nexus-rg")
AZURE_CONTAINER_APP_ENVIRONMENT = os.getenv("AZURE_CONTAINER_APP_ENVIRONMENT", "agentic-nexus-env")
AZURE_LOCATION = os.getenv("AZURE_LOCATION", "eastus")

# Container App Configuration
CONTAINER_PORT = int(os.getenv("CONTAINER_PORT", "8000"))
CONTAINER_CPU = os.getenv("CONTAINER_CPU", "0.5")  # vCPU
CONTAINER_MEMORY = os.getenv("CONTAINER_MEMORY", "1Gi")  # Memory
CONTAINER_REPLICAS_MIN = int(os.getenv("CONTAINER_REPLICAS_MIN", "1"))
CONTAINER_REPLICAS_MAX = int(os.getenv("CONTAINER_REPLICAS_MAX", "10"))

# Frontend Integration
STATIC_WEB_APP_DOMAIN = os.getenv("STATIC_WEB_APP_DOMAIN", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# ==========================================
# DATABASE CONFIGURATION
# ==========================================

COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT", "")
COSMOS_KEY = os.getenv("COSMOS_KEY", "")
COSMOS_DATABASE = os.getenv("COSMOS_DATABASE", "agentic-nexus-db")

# ==========================================
# AUTHENTICATION
# ==========================================

ENABLE_AUTH = os.getenv("ENABLE_AUTH", "false").lower() == "true"
AUTH_PROVIDER = os.getenv("AUTH_PROVIDER", "azure-ad")  # azure-ad, custom

# ==========================================
# LOGGING & MONITORING
# ==========================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ENABLE_APPLICATION_INSIGHTS = os.getenv("ENABLE_APPLICATION_INSIGHTS", "false").lower() == "true"
APP_INSIGHTS_KEY = os.getenv("APP_INSIGHTS_KEY", "")

# ==========================================
# FEATURE FLAGS
# ==========================================

ENABLE_CODE_GENERATION = os.getenv("ENABLE_CODE_GENERATION", "true").lower() == "true"
ENABLE_DEPLOYMENT = os.getenv("ENABLE_DEPLOYMENT", "true").lower() == "true"
ENABLE_COST_ESTIMATION = os.getenv("ENABLE_COST_ESTIMATION", "true").lower() == "true"
MAX_PROJECT_TIMEOUT_SECONDS = int(os.getenv("MAX_PROJECT_TIMEOUT_SECONDS", "3600"))

# ==========================================
# BICEP TEMPLATE CONFIGURATION
# ==========================================

BICEP_TEMPLATE = """
param containerAppName string = '${AZURE_CONTAINER_APP_NAME}'
param resourceGroupName string = '${AZURE_RESOURCE_GROUP}'
param location string = '${AZURE_LOCATION}'
param imageName string = '${ACR_IMAGE_FULL}'
param port int = ${CONTAINER_PORT}
param cpuCores string = '${CONTAINER_CPU}'
param memorySize string = '${CONTAINER_MEMORY}'
param minReplicas int = ${CONTAINER_REPLICAS_MIN}
param maxReplicas int = ${CONTAINER_REPLICAS_MAX}

// Container App Environment
resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: '${containerAppName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: 'YOUR_LOG_ANALYTICS_WORKSPACE_ID'
        sharedKey: 'YOUR_LOG_ANALYTICS_SHARED_KEY'
      }
    }
  }
}

// Container App
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: port
        transport: 'auto'
      }
      registries: [
        {
          server: '${AZURE_CONTAINER_REGISTRY}.azurecr.io'
          username: 'REGISTRY_USERNAME'
          passwordSecretRef: 'registry-password'
        }
      ]
      secrets: [
        {
          name: 'registry-password'
          value: 'REGISTRY_PASSWORD'
        }
      ]
    }
    template: {
      revisionSuffix: 'v1'
      containers: [
        {
          name: containerAppName
          image: imageName
          resources: {
            cpu: json(cpuCores)
            memory: memorySize
          }
          env: [
            {
              name: 'ENVIRONMENT'
              value: 'production'
            }
            {
              name: 'LOG_LEVEL'
              value: 'INFO'
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-scaling'
            custom: {
              metadata: {
                concurrency: '100'
              }
              type: 'http'
            }
          }
        ]
      }
    }
  }
}

output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
"""

def get_deployment_config() -> dict:
    """Get complete deployment configuration"""
    return {
        "container": {
            "registry": AZURE_CONTAINER_REGISTRY,
            "image": ACR_IMAGE_NAME,
            "tag": ACR_IMAGE_TAG,
            "full_image": ACR_IMAGE_FULL,
            "port": CONTAINER_PORT,
            "cpu": CONTAINER_CPU,
            "memory": CONTAINER_MEMORY,
            "min_replicas": CONTAINER_REPLICAS_MIN,
            "max_replicas": CONTAINER_REPLICAS_MAX,
        },
        "azure": {
            "container_app_name": AZURE_CONTAINER_APP_NAME,
            "resource_group": AZURE_RESOURCE_GROUP,
            "environment": AZURE_CONTAINER_APP_ENVIRONMENT,
            "location": AZURE_LOCATION,
        },
        "frontend": {
            "static_web_app_domain": STATIC_WEB_APP_DOMAIN,
            "frontend_url": FRONTEND_URL,
            "api_base_url": API_BASE_URL,
        },
        "features": {
            "enable_code_generation": ENABLE_CODE_GENERATION,
            "enable_deployment": ENABLE_DEPLOYMENT,
            "enable_cost_estimation": ENABLE_COST_ESTIMATION,
        }
    }

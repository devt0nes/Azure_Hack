variable "resource_group_name" {
  description = "The name of the resource group"
  default     = "agentic-nexus-rg"
}

variable "location" {
  description = "The Azure region to deploy resources"
  default     = "East US"
}

variable "app_service_plan_name" {
  description = "The name of the App Service Plan"
  default     = "agentic-nexus-asp"
}

variable "app_service_name" {
  description = "The name of the App Service"
  default     = "agentic-nexus-app"
}
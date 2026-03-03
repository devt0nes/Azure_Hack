resource "azurerm_log_analytics_workspace" "main" {
  name                = "agentic-nexus-law"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
}

resource "azurerm_monitor_diagnostic_setting" "app_service_monitor" {
  name               = "agentic-nexus-diagnostics"
  target_resource_id = azurerm_app_service.app_service.id

  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  logs {
    category = "AppServiceHTTPLogs"
    enabled  = true
  }

  metrics {
    category = "AllMetrics"
    enabled  = true
  }
}
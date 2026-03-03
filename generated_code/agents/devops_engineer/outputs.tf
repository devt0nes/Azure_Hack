output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "app_service_plan_name" {
  value = azurerm_app_service_plan.app_service_plan.name
}

output "app_service_name" {
  value = azurerm_app_service.app_service.name
}
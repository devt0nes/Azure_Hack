// Azure Bicep file for infrastructure provisioning

resource aksCluster 'Microsoft.ContainerService/managedClusters@2022-09-01' = {
  name: 'YourAKSClusterName'
  location: resourceGroup().location
  properties: {
    dnsPrefix: 'aks-user-management'
    agentPoolProfiles: [
      {
        name: 'nodepool1'
        count: 3
        vmSize: 'Standard_DS2_v2'
        osType: 'Linux'
      }
    ]
    servicePrincipalProfile: {
      clientId: 'YourClientID'
      secret: 'YourClientSecret'
    }
  }
}

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2022-09-01' = {
  name: 'YourContainerRegistryName'
  location: resourceGroup().location
  sku: {
    name: 'Basic'
  }
}
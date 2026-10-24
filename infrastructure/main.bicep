targetScope = 'resourceGroup'

@description('Globally unique Event Hubs namespace name.')
@minLength(6)
@maxLength(50)
param namespaceName string

@description('Event hub name for match events.')
param eventHubName string

@description('Azure region for the Event Hubs namespace and Key Vault.')
param location string = resourceGroup().location

@description('Object ID of the ingestion identity allowed to read the send connection secret. Leave empty until that identity exists.')
param ingestionPrincipalId string = ''

@description('Object ID of the analytics identity allowed to read the listen connection secret. Leave empty until that identity exists.')
param analyticsPrincipalId string = ''

resource eventHubNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: namespaceName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
    capacity: 1
  }
  properties: {
    disableLocalAuth: false
    publicNetworkAccess: 'Enabled'
    isAutoInflateEnabled: false
  }
}

resource matchEvents 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: eventHubNamespace
  name: eventHubName
  properties: {
    partitionCount: 2
    messageRetentionInDays: 1
    status: 'Active'
  }
}

resource broadcastConsumers 'Microsoft.EventHub/namespaces/eventhubs/consumerGroups@2024-01-01' = {
  parent: matchEvents
  name: 'broadcast'
}

resource fanConsumers 'Microsoft.EventHub/namespaces/eventhubs/consumerGroups@2024-01-01' = {
  parent: matchEvents
  name: 'fan'
}

resource sendRule 'Microsoft.EventHub/namespaces/eventhubs/authorizationRules@2024-01-01' = {
  parent: matchEvents
  name: 'ingestion-send'
  properties: {
    rights: [
      'Send'
    ]
  }
}

resource listenRule 'Microsoft.EventHub/namespaces/eventhubs/authorizationRules@2024-01-01' = {
  parent: matchEvents
  name: 'analytics-listen'
  properties: {
    rights: [
      'Listen'
    ]
  }
}

resource connectionVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kvpp${uniqueString(resourceGroup().id, namespaceName)}'
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 90
    accessPolicies: []
    publicNetworkAccess: 'Enabled'
  }
}

resource sendConnectionSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: connectionVault
  name: 'eventhub-ingestion-send-connection'
  properties: {
    value: sendRule.listKeys().primaryConnectionString
  }
}

resource listenConnectionSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: connectionVault
  name: 'eventhub-analytics-listen-connection'
  properties: {
    value: listenRule.listKeys().primaryConnectionString
  }
}

resource speech 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'sp-pp-${uniqueString(resourceGroup().id, namespaceName)}'
  location: location
  kind: 'SpeechServices'
  sku: {
    name: 'S0'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
  }
}

resource speechKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: connectionVault
  name: 'speech-subscription-key'
  properties: {
    value: speech.listKeys().key1
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stpp${uniqueString(resourceGroup().id, namespaceName)}'
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource checkpointContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'checkpoints'
  properties: {
    publicAccess: 'None'
  }
}

resource deadLetterContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'dead-letter'
  properties: {
    publicAccess: 'None'
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'crpp${uniqueString(resourceGroup().id, namespaceName)}'
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource gatewayIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-pp-gateway-${uniqueString(resourceGroup().id, namespaceName)}'
  location: location
}

resource gatewayAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, gatewayIdentity.id, 'AcrPull')
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: gatewayIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource gatewayVaultReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(connectionVault.id, gatewayIdentity.id, 'Key Vault Secrets User')
  scope: connectionVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: gatewayIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource gatewayStorageContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, gatewayIdentity.id, 'Storage Blob Data Contributor')
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: gatewayIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource ingestionSecretReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(ingestionPrincipalId)) {
  name: guid(sendConnectionSecret.id, ingestionPrincipalId, 'Key Vault Secrets User')
  scope: sendConnectionSecret
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: ingestionPrincipalId
  }
}

resource analyticsSecretReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(analyticsPrincipalId)) {
  name: guid(listenConnectionSecret.id, analyticsPrincipalId, 'Key Vault Secrets User')
  scope: listenConnectionSecret
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: analyticsPrincipalId
  }
}

resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law-pp-${uniqueString(resourceGroup().id, namespaceName)}'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2026-01-01' = {
  name: 'cae-pp-${uniqueString(resourceGroup().id, namespaceName)}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logWorkspace.properties.customerId
        sharedKey: logWorkspace.listKeys().primarySharedKey
      }
    }
    publicNetworkAccess: 'Enabled'
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

output eventHubNamespaceId string = eventHubNamespace.id
output eventHubId string = matchEvents.id
output keyVaultName string = connectionVault.name
output sendSecretName string = sendConnectionSecret.name
output listenSecretName string = listenConnectionSecret.name
output logAnalyticsWorkspaceId string = logWorkspace.id
output containerAppsEnvironmentId string = containerAppsEnvironment.id
output registryName string = registry.name
output registryServer string = registry.properties.loginServer
output gatewayIdentityId string = gatewayIdentity.id
output gatewayIdentityClientId string = gatewayIdentity.properties.clientId
output storageAccountUrl string = 'https://${storage.name}.blob.${environment().suffixes.storage}'
output speechRegion string = location
output speechSecretName string = speechKeySecret.name

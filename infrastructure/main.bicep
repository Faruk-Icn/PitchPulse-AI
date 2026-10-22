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
    publicNetworkAccess: 'Disabled'
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

targetScope = 'resourceGroup'

@description('Globally unique Event Hubs namespace name, also used to derive the Key Vault name.')
@minLength(6)
@maxLength(50)
param namespaceName string

@description('Azure region for the Key Vault.')
param location string = resourceGroup().location

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

output keyVaultName string = connectionVault.name

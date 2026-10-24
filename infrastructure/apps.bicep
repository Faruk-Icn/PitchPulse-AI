targetScope = 'resourceGroup'

param location string = resourceGroup().location
param containerAppsEnvironmentId string
param registryServer string
param gatewayIdentityId string
param gatewayIdentityClientId string
param keyVaultName string
param storageAccountUrl string
param speechRegion string
param eventHubName string
param imageTag string
param foundryProjectEndpoint string = ''
param foundryModel string = ''

var image = '${registryServer}/pitchpulse-gateway:${imageTag}'
var vaultUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}'
var commonSecrets = [
  {
    name: 'eventhub-listen'
    keyVaultUrl: '${vaultUrl}/secrets/eventhub-analytics-listen-connection'
    identity: gatewayIdentityId
  }
  {
    name: 'speech-key'
    keyVaultUrl: '${vaultUrl}/secrets/speech-subscription-key'
    identity: gatewayIdentityId
  }
]
var commonEnv = [
  {
    name: 'EVENT_HUB_LISTEN_CONNECTION_STRING'
    secretRef: 'eventhub-listen'
  }
  {
    name: 'EVENT_HUB_NAME'
    value: eventHubName
  }
  {
    name: 'SPEECH_KEY'
    secretRef: 'speech-key'
  }
  {
    name: 'SPEECH_REGION'
    value: speechRegion
  }
  {
    name: 'BLOB_ACCOUNT_URL'
    value: storageAccountUrl
  }
  {
    name: 'CHECKPOINT_CONTAINER'
    value: 'checkpoints'
  }
  {
    name: 'DEAD_LETTER_CONTAINER'
    value: 'dead-letter'
  }
  {
    name: 'AZURE_CLIENT_ID'
    value: gatewayIdentityClientId
  }
  {
    name: 'FOUNDRY_PROJECT_ENDPOINT'
    value: foundryProjectEndpoint
  }
  {
    name: 'FOUNDRY_MODEL'
    value: foundryModel
  }
]

resource broadcast 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-pp-broadcast'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${gatewayIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registryServer
          identity: gatewayIdentityId
        }
      ]
      secrets: commonSecrets
    }
    template: {
      containers: [
        {
          name: 'gateway'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: concat(commonEnv, [
            {
              name: 'EVENT_HUB_CONSUMER_GROUP'
              value: 'broadcast'
            }
            {
              name: 'PITCHPULSE_MODE'
              value: 'broadcast'
            }
          ])
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 20
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

resource fan 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-pp-fan'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${gatewayIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registryServer
          identity: gatewayIdentityId
        }
      ]
      secrets: commonSecrets
    }
    template: {
      containers: [
        {
          name: 'gateway'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: concat(commonEnv, [
            {
              name: 'EVENT_HUB_CONSUMER_GROUP'
              value: 'fan'
            }
            {
              name: 'PITCHPULSE_MODE'
              value: 'fan'
            }
          ])
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 20
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

output broadcastUrl string = 'https://${broadcast.properties.configuration.ingress.fqdn}/studio'
output fanUrl string = 'https://${fan.properties.configuration.ingress.fqdn}/fan'

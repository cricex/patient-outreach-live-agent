// ---------------------------------------------------------------------------
// Live Voice Agent Studio v2 — Azure Infrastructure
// Single-file Bicep template: Container Apps + ACR + Key Vault + Log Analytics
// Deploy: az deployment group create -g <rg> -f infra/main.bicep -p environmentName=voiceagent-dev
// ---------------------------------------------------------------------------

targetScope = 'resourceGroup'

// ---- Parameters -----------------------------------------------------------

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Environment name used as prefix for all resource names (e.g. voiceagent-dev)')
param environmentName string

@description('Full ACR image reference (e.g. myacr.azurecr.io/voiceagent:latest). Leave empty to deploy a placeholder container.')
param containerImage string = ''

// ---- Variables ------------------------------------------------------------

// ACR names must be alphanumeric, lowercase, 5-50 chars
var acrName = toLower(replace('${environmentName}acr', '-', ''))
var logAnalyticsName = '${environmentName}-logs'
var keyVaultName = '${environmentName}-kv'
var managedIdentityName = '${environmentName}-id'
var containerEnvName = '${environmentName}-env'
var containerAppName = '${environmentName}-app'

// Use placeholder image when no custom image is provided
var effectiveImage = empty(containerImage)
  ? 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
  : containerImage

// Built-in role: Key Vault Secrets User (4633458b-17de-408a-b874-0445c86b69e6)
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

// ---- Log Analytics Workspace ----------------------------------------------
// Central logging for Container Apps diagnostics and application logs.

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ---- Container Registry ---------------------------------------------------
// Hosts the Voice Agent container image. Admin enabled for initial setup;
// switch to managed identity pull (acrPull role) for production.

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

// ---- User-Assigned Managed Identity ---------------------------------------
// Used by Container App to access Key Vault secrets at runtime.

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
}

// ---- Key Vault ------------------------------------------------------------
// Stores sensitive configuration: ACS connection string, Voice Live API key,
// Foundry API key. Uses RBAC authorization (no access policies).

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

// ---- Key Vault Role Assignment --------------------------------------------
// Grant the managed identity "Key Vault Secrets User" so the Container App
// can read secrets (ACS_CONNECTION_STRING, AZURE_VOICELIVE_API_KEY, etc.)

resource kvRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, managedIdentity.id, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
  }
}

// ---- Container Apps Environment -------------------------------------------
// Consumption-plan environment linked to Log Analytics for log aggregation.

resource containerEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: containerEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ---- Container App --------------------------------------------------------
// Single-container app running the FastAPI backend + React frontend.
// Ingress on port 8000, scales 0-3 replicas on HTTP traffic.

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      // ACR credentials — uses admin login for simplicity.
      // For production, switch to managed identity with acrPull role.
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'voiceagent'
          image: effectiveImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            // --- Non-sensitive env vars set directly ---
            {
              name: 'WEBSITES_PORT'
              value: '8000'
            }
            {
              name: 'LOG_LEVEL'
              value: 'INFO'
            }
            // --- Sensitive env vars ---
            // Load these from Key Vault secrets at runtime using the managed identity.
            // Option A: Key Vault secret URI references (Container Apps native):
            //   Add secrets in configuration.secrets with keyVaultUrl + identity, then
            //   reference them here via secretRef. Example:
            //
            //   In configuration.secrets:
            //     { name: 'acs-conn-str', keyVaultUrl: '${keyVault.properties.vaultUri}secrets/ACS-CONNECTION-STRING', identity: managedIdentity.id }
            //
            //   Then here:
            //     { name: 'ACS_CONNECTION_STRING', secretRef: 'acs-conn-str' }
            //     { name: 'AZURE_VOICELIVE_API_KEY', secretRef: 'vl-api-key' }
            //     { name: 'FOUNDRY_INFERENCE_API_KEY', secretRef: 'foundry-api-key' }
            //
            // Option B: Use Azure SDK DefaultAzureCredential in app code to fetch secrets
            //   at startup using the managed identity (AZURE_CLIENT_ID env var).
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentity.properties.clientId
            }
            {
              name: 'AZURE_KEYVAULT_NAME'
              value: keyVault.name
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

// ---- Outputs --------------------------------------------------------------

@description('Container App FQDN (use https://)')
output appUrl string = containerApp.properties.configuration.ingress.fqdn

@description('ACR login server for docker push')
output acrLoginServer string = acr.properties.loginServer

@description('Key Vault name for secret management')
output keyVaultName string = keyVault.name

@description('Managed identity resource ID (use for role assignments)')
output managedIdentityId string = managedIdentity.id

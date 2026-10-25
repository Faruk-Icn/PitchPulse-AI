# Connect this repository to Azure

The deployment workflow cannot create or verify a live service until an Azure subscription is linked to GitHub Actions. These steps use OIDC, so there is no long-lived Azure client secret.

1. In [Azure Portal](https://portal.azure.com/), note the **Subscription ID** and **Directory (tenant) ID** for the subscription you want to use.
2. Create a resource group in the Azure region you want to use. The workflow now requires that group to exist before deployment.
3. In **Microsoft Entra ID → App registrations**, create an application for this repository. Copy its **Application (client) ID**.
4. In that app, open **Certificates & secrets → Federated credentials → Add credential**. Choose **GitHub Actions deploying Azure resources**, owner `Faruk-Icn`, repository `PitchPulse-AI`, entity **Branch**, branch `main`. This makes the OIDC subject match this workflow's `main` branch.
5. On the resource group's **Access control (IAM)** page, grant the app **Contributor** and **Role Based Access Control Administrator**. The latter is needed because Bicep creates role assignments for the Container Apps identity. An Azure administrator may need to make these assignments.
6. Open [this repo's Actions settings](https://github.com/Faruk-Icn/PitchPulse-AI/settings/secrets/actions). Under **Secrets**, add `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID` with the IDs above. Under **Variables**, add `AZURE_RESOURCE_GROUP` (the existing group name), `AZURE_LOCATION` (its region code), `EVENT_HUB_NAMESPACE_NAME` (a globally unique name), and `EVENT_HUB_NAME` (the event hub name you choose).
7. Run [Deploy Azure services](https://github.com/Faruk-Icn/PitchPulse-AI/actions/workflows/deploy-infrastructure.yml) with **Run workflow**. The run builds the image, deploys both apps, and performs a real Event Hubs to WebSocket staging check. Read the run's final output for the two URLs and latency report.

The optional `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL` repository variables must be added together. Foundry use also requires model deployment access for the gateway identity. Without those settings, factual studio and fan output works, but generated commentary does not. The Speech resource is provisioned by Bicep and uses a Key Vault-backed key.

This deployment creates billable Azure resources. Review the resource group after the hackathon and remove it when no longer needed.

References: [Microsoft's GitHub OIDC guide](https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect), [Microsoft's federated credential steps](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation-create-trust?pivots=identity-wif-apps-methods-azp), [GitHub's repository variable setup](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables).

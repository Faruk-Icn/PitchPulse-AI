# Deploy your own PitchPulse AI fork to Azure

Each deployment uses the fork owner's Azure subscription and GitHub Actions settings. No Azure identifiers or credentials are committed to the public repository. The deployment uses OIDC, so there is no long-lived Azure client secret. Run the local setup screen at `http://127.0.0.1:8000/setup` after starting the [local demo](../README.md#run-the-local-demo). It remembers the identifiers in that browser and opens your fork's settings pages. It does not send those values to a server or configure Azure for you.

1. Fork the repository into your GitHub account or organization. In [Azure Portal](https://portal.azure.com/), note the **Subscription ID** and **Directory (tenant) ID** for the subscription you want to use.
2. Create a resource group in the Azure region you want to use. The workflow now requires that group to exist before deployment.
3. In **Microsoft Entra ID → App registrations**, create an application for your fork. Copy its **Application (client) ID**.
4. In that app, open **Certificates & secrets → Federated credentials → Add credential**. Choose **GitHub Actions deploying Azure resources**. Enter your fork's GitHub owner and repository, entity **Branch**, branch `main`. The credential must match the owner, repository, and branch that run the workflow.
5. On the resource group's **Access control (IAM)** page, grant the app **Contributor** and **Role Based Access Control Administrator**. The latter is needed because Bicep creates role assignments for the Container Apps identity. An Azure administrator may need to make these assignments.
6. In **your fork's** Settings → Secrets and variables → Actions, add repository secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID`. Add repository variables `AZURE_RESOURCE_GROUP` (the existing group name), `AZURE_LOCATION` (its region code), `EVENT_HUB_NAMESPACE_NAME` (a globally unique name), and `EVENT_HUB_NAME` (the event hub name you choose). The setup screen provides direct links after you enter your GitHub owner and repository name.
7. In **your fork's** Actions tab, run **Deploy Azure services** with **Run workflow**. The run builds the image, deploys both apps, and performs a real Event Hubs to WebSocket staging check. Read the run's final output for the two URLs and latency report. Deployment is manual so a new fork never deploys or incurs Azure charges merely because code is pushed.

The optional `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL` repository variables must be added together. Foundry use also requires model deployment access for the gateway identity. Without those settings, factual studio and fan output works, but generated commentary does not. The Speech resource is provisioned by Bicep and uses a Key Vault-backed key.

This deployment creates billable Azure resources. Review the resource group after the hackathon and remove it when no longer needed.

The setup screen stores identifiers in browser `localStorage` for the origin where you opened it. They are available when you return to that browser and origin, and can be removed with **Clear saved details**. Do not enter passwords, client secrets, API keys, or connection strings. The setup screen is a guide to the GitHub and Azure configuration, not a substitute for completing those steps.

References: [Microsoft's GitHub OIDC guide](https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect), [Microsoft's federated credential steps](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation-create-trust?pivots=identity-wif-apps-methods-azp), [GitHub's repository variable setup](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables).

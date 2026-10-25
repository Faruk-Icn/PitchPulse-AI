# PitchPulse AI — competition pitch

## The problem

Football moves faster than a broadcast team can explain every useful pattern. A pass, press, or shot can matter tactically before an analyst has time to assemble the context. Fans also need updates in a language and style they can follow.

## The product

PitchPulse AI reads structured match events and immediately turns them into an analyst overlay and a fan timeline. The studio highlights event position, pass difficulty, nearby pressure, pass accuracy, and optional concise commentary. The fan feed offers five languages, three text styles, and optional speech. A shared event ID keeps both audience views tied to the same source action.

## What works in this repository

- Synthetic event generation, JSON Schema validation, Event Hubs producer and consumer, and dead-letter handling.
- Microsoft Agent Framework coordination of Tactician, Storyteller, and Stats Analyst logic.
- A broadcast dashboard and fan interface with live WebSocket updates.
- Localized factual text without an LLM; optional Microsoft Foundry prose and Azure Speech audio when configured.
- Azure infrastructure and Container Apps deployment definitions, plus CI, emulator integration tests, and a staging latency verifier.

## Technical stack

| Layer | Implementation |
| --- | --- |
| Stream | Python, Azure Event Hubs SDK, JSON Schema |
| Analysis | Microsoft Agent Framework, spatial and statistical Python modules |
| Generative text | Microsoft Foundry when configured |
| Voice | Azure AI Speech SDK when configured |
| Delivery | FastAPI, WebSockets, HTML, CSS, JavaScript |
| Cloud | Bicep, Azure Container Apps, Blob Storage, Key Vault, Container Registry, Log Analytics |
| Verification | `unittest`, Event Hubs emulator, Docker build, local load benchmark, staging WebSocket check |

## Honest demo scope

The screens use synthetic match events, not a live football feed. The factual studio and fan flows work locally without Azure. Foundry prose, Speech audio, and live Azure staging require cloud configuration; the repository does not claim those services are currently deployed. The user-facing target is sub-second factual delivery, measured separately from AI text and voice.

## Next proof point

With an Azure subscription and GitHub OIDC settings in place, run the staging workflow and publish its end-to-end latency report. A broadcaster pilot would then test analyst usefulness, editorial safety, and integration with a licensed event feed.

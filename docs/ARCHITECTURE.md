# Architecture and verification

## Event path

`src/ingestion/generator.py` emits deterministic synthetic rosters and match events. `config/match-event.schema.json` defines player metadata, positions, passes, and shots. The producer validates every event, batches publication to Azure Event Hubs, and uses a partition key based on match ID to keep a match's order.

The gateway's Event Hubs consumer validates each received body before `MatchAgentCrew` processes it. The Tactician keeps recent positions and produces formation and nearest-player territory estimates when enough position data exists. The Stats Analyst maintains pass accuracy and a shot-location xG estimate. Pass difficulty combines geometry and nearby defenders; tactical pressure counts nearby opposing players. These are descriptive model outputs, not tracking-derived ground truth.

The gateway sends an analysis record to studio WebSockets and a localized factual record to fan WebSockets. Foundry commentary and Azure Speech are optional asynchronous follow-ups, so their response time does not hold the factual update. Each service has a separate Event Hubs consumer group. Blob Storage holds Event Hubs checkpoints and rejected event records when configured. To avoid a Blob write after every match event, the consumer checkpoints after 20 processed events, after five idle seconds, and on orderly shutdown. A restart can replay the uncheckpointed tail.

## Deployment

`infrastructure/main.bicep` defines Event Hubs, consumer groups, Key Vault, Speech, Azure Container Registry, Blob Storage, Log Analytics, a Container Apps environment, and the gateway managed identity and role assignments. `infrastructure/apps.bicep` defines separate broadcast and fan Container Apps from one image. Both use TLS ingress and one replica because match state and WebSocket subscriptions are process-local. The ingestion send and gateway listen rules have separate connection strings in Key Vault.

The deploy workflow compiles Bicep, deploys the resources, builds the gateway image, deploys both apps, and runs `scripts/verify_staging.py` against real Azure endpoints. The staging check sends match events to Event Hubs and verifies that both audience streams receive the same event IDs. It reports p50, p95, and maximum time from producer send to both factual messages, excluding Foundry and speech. Deployment fails if p95 reaches one second.

## Boundaries

- A licensed live event feed, broadcast switching integration, producer replay tooling, and analyst authentication are outside this prototype.
- The gateway keeps tactical and cumulative statistical state in memory. Blob checkpoints protect stream position, but they do not restore historical state after a restart; statistics then reflect only newly processed events.
- The location-only xG model is based on a documented open-data fit in `src/agents/xg_model.json`. It omits goalkeeper, body part, and defensive pressure features.
- A local benchmark does not prove Azure latency. The deployed staging verifier is the release gate for that target.

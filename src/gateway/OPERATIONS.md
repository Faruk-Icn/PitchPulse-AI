# Gateway operation

Install `requirements-gateway.txt` and run `python -m src.gateway` from the
repository root. The server binds to `127.0.0.1:8000`. Open `/studio` for the
analyst dashboard. `/studio?match_id=...` filters the dashboard to one match.
`/ws/studio` carries analyst analysis and later narrative records, with the
same optional match filter. `/ws/fan/{match_id}` carries validated match events and statistics;
fan connections can set `language=en|es|fr|de|ar` and
`style=concise|tactical|casual` query parameters.

Set `EVENT_HUB_LISTEN_CONNECTION_STRING`, `EVENT_HUB_NAME` and a writable
`DEAD_LETTER_PATH` to start the Event Hubs listener. An optional
`EVENT_HUB_CONSUMER_GROUP` selects a different group; otherwise `$Default` is
used. The listen connection string should come from the Key Vault secret
provisioned by `infrastructure/main.bicep`. `/health` reports whether a listener
is running, absent or stopped. The service can run locally without Event Hubs
configuration to inspect the empty studio UI.

Set both `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL` to enable analyst
narratives and personalized fan text. Authentication uses
`DefaultAzureCredential`; the configured identity needs access to the Foundry
model deployment. Event facts are delivered before text generation. Fan text is
generated only for pass and shot events and once per active match/language/style
combination. Failures produce a `personalization_unavailable` record, never
invented fallback text.

The current gateway is a single-process local service. Its WebSocket streams
have no login or TLS termination, so do not expose it directly to the public.
The Event Hubs listener starts from the earliest retained event and keeps match
state only in memory. A production deployment needs durable checkpointing,
authenticated ingress and a durable delivery sink. No Azure deployment or live
Foundry inference is claimed by this repository change.

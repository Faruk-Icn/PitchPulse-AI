# Gateway operation

Install `requirements-gateway.txt` and run `python -m src.gateway` from the
repository root. The server binds to `127.0.0.1:8000`. Open `/studio` for the
analyst dashboard. `/studio?match_id=...` filters the dashboard to one match.
`/ws/studio` carries analyst analysis and later narrative records, with the
same optional match filter. `/ws/fan/{match_id}` carries validated match events and statistics;
fan connections can set `language=en|es|fr|de|ar` and
`style=concise|tactical|casual` query parameters. The fan page saves its
match, language, style and voice choices in that browser's local storage;
there is no account profile service. `/api/fan/config` serves the shared
localization catalog. Validated events carry a translated factual summary even
when Foundry is not configured.

Set `EVENT_HUB_LISTEN_CONNECTION_STRING`, `EVENT_HUB_NAME` and either a writable
`DEAD_LETTER_PATH` or all of `BLOB_ACCOUNT_URL`, `CHECKPOINT_CONTAINER`, and
`DEAD_LETTER_CONTAINER` to start the Event Hubs listener. Blob mode uses Azure
identity for checkpoints and rejected events. An optional
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

Set both `SPEECH_KEY` and `SPEECH_REGION` to enable Azure Speech synthesis.
Fan clients opt in with `voice=1`; the gateway sends a `speech_audio` WebSocket
record with base64 WAV data after the text. If Foundry is unavailable, speech
uses the translated factual event summary. The Speech resource and its Key
Vault secret are defined in `infrastructure/main.bicep`.

`PITCHPULSE_MODE=broadcast` serves the studio routes;
`PITCHPULSE_MODE=fan` serves the fan routes. The Azure definitions run each
service with one replica because match state and WebSocket subscribers are held
in memory. They use separate Event Hubs consumer groups and Blob checkpoints.
Match statistics after a restart only include events processed since that
restart; a state store is needed for continuous cumulative statistics.
Container Apps ingress provides TLS, but the application does not require
analyst sign-in yet. The GitHub Actions deployment needs the Azure OIDC secrets
and repository variables validated in the workflow. Foundry settings are
optional; without them, fan text and speech use localized factual summaries.

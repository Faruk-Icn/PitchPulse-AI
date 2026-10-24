"""One validated event feeds separate analyst and fan channels."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict

from azure.eventhub.aio import EventHubConsumerClient
from azure.eventhub.extensions.checkpointstoreblobaio import BlobCheckpointStore
from azure.identity.aio import DefaultAzureCredential

from src.agents.consumer import CrewStreamProcessor
from src.agents.config import AgentSettings
from src.agents.storyteller import StorytellerAgent
from src.ingestion.dead_letter import JsonlDeadLetterSink

from .fans import FanHub
from .blob_dead_letter import BlobDeadLetterSink
from .overlays import OverlayHub
from .personalization import FanPersonalizer


class GatewayEngine:
    def __init__(
        self, overlays: OverlayHub, fans: FanHub, *, dead_letter_path: str | None = None,
        personalizer: FanPersonalizer | None = None, settings: AgentSettings | None = None,
        mode: str = "both",
    ) -> None:
        self.overlays = overlays
        self.fans = fans
        self.personalizer = personalizer
        self.mode = mode
        settings = settings or AgentSettings.from_env()
        storyteller_factory = (
            (lambda match_id: StorytellerAgent.from_foundry(match_id, settings))
            if mode != "fan" and settings.foundry_project_endpoint and settings.foundry_model else None
        )
        self.processor = CrewStreamProcessor(
            settings=settings, storyteller_factory=storyteller_factory,
            dead_letter=JsonlDeadLetterSink(dead_letter_path) if dead_letter_path else None,
            narrative_sink=self._publish_narrative if mode != "fan" else None,
        )

    async def handle_body(self, body: str) -> None:
        result = await self.processor.process_body(body)
        if result is None:
            return
        event = json.loads(body)
        outputs = []
        if self.mode != "fan":
            outputs.append(self.overlays.broadcast({
                "kind": "analysis", "match_id": result.match_id,
                "sequence": result.sequence, "event": event, "result": asdict(result),
            }))
        if self.mode != "broadcast":
            outputs.append(self.fans.broadcast(event, result))
        await asyncio.gather(*outputs)
        if self.mode == "broadcast":
            return
        if self.personalizer is not None and event["event_type"] in ("pass", "shot"):
            await self.fans.schedule_personalization(event, result, self.personalizer)
        elif event["event_type"] in ("pass", "shot"):
            await self.fans.schedule_fact_voice(event)

    async def _publish_narrative(self, event: dict, result) -> None:
        await self.overlays.broadcast({
            "kind": "narrative", "match_id": result.match_id,
            "sequence": result.sequence, "event": event, "result": asdict(result),
        })

    async def drain(self) -> None:
        await self.processor.drain()
        await self.fans.drain()


async def receive_event_hubs(engine: GatewayEngine) -> None:
    """Read from all partitions; one match is partitioned by match ID upstream."""
    logger = logging.getLogger("pitchpulse.gateway.eventhubs")
    connection = os.environ["EVENT_HUB_LISTEN_CONNECTION_STRING"]
    hub_name = os.environ["EVENT_HUB_NAME"]
    account_url = os.environ.get("BLOB_ACCOUNT_URL")
    checkpoint_container = os.environ.get("CHECKPOINT_CONTAINER")
    dead_letter_container = os.environ.get("DEAD_LETTER_CONTAINER")
    if any((account_url, checkpoint_container, dead_letter_container)) and not all(
        (account_url, checkpoint_container, dead_letter_container)
    ):
        raise ValueError("BLOB_ACCOUNT_URL, CHECKPOINT_CONTAINER and DEAD_LETTER_CONTAINER must be configured together")

    async with DefaultAzureCredential() if account_url else _NoCredential() as credential:
        checkpoint_store = (
            BlobCheckpointStore(account_url, checkpoint_container, credential=credential)
            if account_url else None
        )
        blob_dead_letter = (
            BlobDeadLetterSink(account_url, dead_letter_container, credential)
            if account_url else None
        )
        if blob_dead_letter is not None:
            engine.processor.dead_letter = blob_dead_letter
        consumer = EventHubConsumerClient.from_connection_string(
            connection, consumer_group=os.environ.get("EVENT_HUB_CONSUMER_GROUP", "$Default"),
            eventhub_name=hub_name, checkpoint_store=checkpoint_store,
        )

        async def on_event(partition, event) -> None:
            if event is not None:
                await engine.handle_body(event.body_as_str())
                if checkpoint_store is not None:
                    await partition.update_checkpoint(event)

        async def on_error(partition, error) -> None:
            logger.error("Event Hubs receive failed partition=%s error=%s", partition, error)

        try:
            async with consumer:
                await consumer.receive(on_event=on_event, on_error=on_error, starting_position="-1")
        finally:
            await engine.drain()
            if blob_dead_letter is not None:
                await blob_dead_letter.close()
            if checkpoint_store is not None:
                await checkpoint_store.close()


class _NoCredential:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *_args):
        return None

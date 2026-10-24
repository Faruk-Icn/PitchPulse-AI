"""One validated event feeds separate analyst and fan channels."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict

from azure.eventhub.aio import EventHubConsumerClient

from src.agents.consumer import CrewStreamProcessor
from src.agents.config import AgentSettings
from src.agents.storyteller import StorytellerAgent
from src.ingestion.dead_letter import JsonlDeadLetterSink

from .fans import FanHub
from .overlays import OverlayHub
from .personalization import FanPersonalizer


class GatewayEngine:
    def __init__(
        self, overlays: OverlayHub, fans: FanHub, *, dead_letter_path: str | None = None,
        personalizer: FanPersonalizer | None = None, settings: AgentSettings | None = None,
    ) -> None:
        self.overlays = overlays
        self.fans = fans
        self.personalizer = personalizer
        settings = settings or AgentSettings.from_env()
        storyteller_factory = (
            (lambda match_id: StorytellerAgent.from_foundry(match_id, settings))
            if settings.foundry_project_endpoint and settings.foundry_model else None
        )
        self.processor = CrewStreamProcessor(
            settings=settings, storyteller_factory=storyteller_factory,
            dead_letter=JsonlDeadLetterSink(dead_letter_path) if dead_letter_path else None,
            narrative_sink=self._publish_narrative,
        )

    async def handle_body(self, body: str) -> None:
        result = await self.processor.process_body(body)
        if result is None:
            return
        event = json.loads(body)
        await asyncio.gather(
            self.overlays.broadcast({
                "kind": "analysis", "match_id": result.match_id,
                "sequence": result.sequence, "event": event, "result": asdict(result),
            }),
            self.fans.broadcast(event, result),
        )
        if self.personalizer is not None and event["event_type"] in ("pass", "shot"):
            await self.fans.schedule_personalization(event, result, self.personalizer)

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
    consumer = EventHubConsumerClient.from_connection_string(
        connection, consumer_group=os.environ.get("EVENT_HUB_CONSUMER_GROUP", "$Default"),
        eventhub_name=hub_name,
    )

    async def on_event(_partition, event) -> None:
        if event is not None:
            await engine.handle_body(event.body_as_str())

    async def on_error(partition, error) -> None:
        logger.error("Event Hubs receive failed partition=%s error=%s", partition, error)

    async with consumer:
        try:
            await consumer.receive(on_event=on_event, on_error=on_error, starting_position="-1")
        finally:
            await engine.drain()

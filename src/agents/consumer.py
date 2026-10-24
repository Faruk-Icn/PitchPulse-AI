"""Receive Event Hubs match events and publish crew results as JSON Lines."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict
from typing import Any, Awaitable, Callable

from azure.eventhub.aio import EventHubConsumerClient
from jsonschema import ValidationError

from src.ingestion.dead_letter import JsonlDeadLetterSink
from src.ingestion.validation import validate_event

from .config import AgentSettings, configure_logging
from .crew import CrewResult, MatchAgentCrew
from .storyteller import StorytellerAgent


class CrewStreamProcessor:
    """Maintain independent match state; Event Hubs partitions preserve match order."""

    def __init__(
        self, *, settings: AgentSettings | None = None,
        dead_letter: JsonlDeadLetterSink | None = None,
        storyteller_factory: Callable[[str], StorytellerAgent] | None = None,
        narrative_sink: Callable[[CrewResult], Awaitable[None]] | None = None,
    ) -> None:
        self.settings = settings or AgentSettings.from_env()
        self.dead_letter = dead_letter
        self.storyteller_factory = storyteller_factory
        self.narrative_sink = narrative_sink
        self.crews: dict[str, MatchAgentCrew] = {}
        self._narrative_tasks: set[asyncio.Task] = set()

    async def process_body(self, body: str) -> CrewResult | None:
        try:
            payload: Any = json.loads(body)
            validate_event(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            if self.dead_letter is None:
                raise
            await self.dead_letter.write(body, type(exc).__name__, 1)
            return None

        match_id = payload["match_id"]
        crew = self.crews.get(match_id)
        if crew is None:
            storyteller = self.storyteller_factory(match_id) if self.storyteller_factory else None
            crew = MatchAgentCrew(match_id, settings=self.settings, storyteller=storyteller)
            self.crews[match_id] = crew
        if payload["sequence"] <= crew.stats_analyst.last_sequence:
            return None  # Producer retries may duplicate an accepted event.
        result = await crew.process(payload, generate_narrative=self.narrative_sink is None)
        if self.narrative_sink is not None and crew.storyteller is not None and payload["event_type"] in ("pass", "shot"):
            if len(self._narrative_tasks) >= 100:
                await asyncio.wait(self._narrative_tasks, return_when=asyncio.FIRST_COMPLETED)
            task = asyncio.create_task(self._publish_narrative(crew, payload, result))
            self._narrative_tasks.add(task)
            task.add_done_callback(self._on_narrative_done)
        return result

    def _on_narrative_done(self, task: asyncio.Task) -> None:
        self._narrative_tasks.discard(task)
        error = None if task.cancelled() else task.exception()
        if error is not None:
            logging.getLogger("pitchpulse.agents.consumer").error(
                "narrative delivery failed", exc_info=(type(error), error, error.__traceback__),
            )

    async def _publish_narrative(self, crew: MatchAgentCrew, event: dict, result: CrewResult) -> None:
        narrated = await crew.narrate(event, result)
        assert self.narrative_sink is not None
        await self.narrative_sink(narrated)

    async def drain(self) -> None:
        """Finish outstanding narrative outputs before clean shutdown."""
        if self._narrative_tasks:
            await asyncio.gather(*self._narrative_tasks)


async def run_consumer() -> None:
    settings = AgentSettings.from_env()
    configure_logging(settings)
    logger = logging.getLogger("pitchpulse.agents.consumer")
    connection = os.environ.get("EVENT_HUB_LISTEN_CONNECTION_STRING")
    hub_name = os.environ.get("EVENT_HUB_NAME")
    dead_letter_path = os.environ.get("DEAD_LETTER_PATH")
    if not connection or not hub_name or not dead_letter_path:
        raise ValueError("EVENT_HUB_LISTEN_CONNECTION_STRING, EVENT_HUB_NAME and DEAD_LETTER_PATH are required")
    storyteller_factory = None
    if settings.foundry_project_endpoint and settings.foundry_model:
        storyteller_factory = lambda match_id: StorytellerAgent.from_foundry(match_id, settings)
    async def publish_narrative(result: CrewResult) -> None:
        print(json.dumps({"kind": "narrative", "result": asdict(result)}, separators=(",", ":")), flush=True)

    processor = CrewStreamProcessor(
        settings=settings, dead_letter=JsonlDeadLetterSink(dead_letter_path),
        storyteller_factory=storyteller_factory, narrative_sink=publish_narrative,
    )

    async def on_event(_partition, event) -> None:
        if event is None:
            return
        result = await processor.process_body(event.body_as_str())
        if result is not None:
            print(json.dumps({"kind": "analysis", "result": asdict(result)}, separators=(",", ":")), flush=True)

    async def on_error(partition, error) -> None:
        logger.error("Event Hubs receive failed partition=%s error=%s", partition, error)

    consumer = EventHubConsumerClient.from_connection_string(
        connection, consumer_group=os.environ.get("EVENT_HUB_CONSUMER_GROUP", "$Default"),
        eventhub_name=hub_name,
    )
    async with consumer:
        try:
            await consumer.receive(on_event=on_event, on_error=on_error, starting_position="-1")
        finally:
            await processor.drain()


def main() -> None:
    asyncio.run(run_consumer())


if __name__ == "__main__":
    main()

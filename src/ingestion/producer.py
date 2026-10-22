"""Publish the synthetic match stream to Azure Event Hubs in async batches."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterable
from typing import Protocol

from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient

from .generator import build_parser, stream_match_events
from .models import MatchEvent


class Batch(Protocol):
    def add(self, event: EventData) -> None: ...


class Producer(Protocol):
    async def create_batch(self, *, partition_key: str) -> Batch: ...
    async def send_batch(self, batch: Batch) -> None: ...


async def publish_events(events: AsyncIterable[MatchEvent], producer: Producer) -> int:
    """Publish one match in order, flushing whenever a batch is full."""
    match_id: str | None = None
    batch: Batch | None = None
    batch_count = 0
    published = 0

    async for event in events:
        if match_id is None:
            match_id = event["match_id"]
            batch = await producer.create_batch(partition_key=match_id)
        elif event["match_id"] != match_id:
            raise ValueError("one producer stream must contain a single match_id")

        data = EventData(json.dumps(event, separators=(",", ":")))
        assert batch is not None
        try:
            batch.add(data)
        except ValueError:
            if batch_count == 0:
                raise ValueError("a single match event exceeds the Event Hubs batch limit") from None
            await producer.send_batch(batch)
            published += batch_count
            batch = await producer.create_batch(partition_key=match_id)
            batch_count = 0
            try:
                batch.add(data)
            except ValueError:
                raise ValueError("a single match event exceeds the Event Hubs batch limit") from None
        batch_count += 1

    if batch_count:
        assert batch is not None
        await producer.send_batch(batch)
        published += batch_count
    return published


async def _run() -> None:
    parser = build_parser("Publish a synthetic match stream to Azure Event Hubs")
    args = parser.parse_args()
    connection_string = os.environ.get("EVENT_HUB_SEND_CONNECTION_STRING")
    if not connection_string:
        parser.error("EVENT_HUB_SEND_CONNECTION_STRING must be set")
    eventhub_name = os.environ.get("EVENT_HUB_NAME") or None

    producer = EventHubProducerClient.from_connection_string(
        conn_str=connection_string,
        eventhub_name=eventhub_name,
    )
    async with producer:
        count = await publish_events(
            stream_match_events(
                scenario=args.scenario,
                rate=args.rate,
                count=None if args.count == 0 else args.count,
                seed=args.seed,
                match_id=args.match_id,
            ),
            producer,
        )
    print(f"Published {count} synthetic match events", file=sys.stderr)


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

"""Publish the synthetic match stream to Azure Event Hubs in async batches."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterable
from typing import Any, Protocol

from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient
from azure.eventhub.exceptions import ConnectError, ConnectionLostError, EventDataSendError, OperationTimeoutError
from jsonschema import ValidationError

from .dead_letter import JsonlDeadLetterSink
from .generator import build_parser, stream_match_events
from .models import MatchEvent
from .validation import validate_event


RETRYABLE_ERRORS = (ConnectError, ConnectionLostError, EventDataSendError, OperationTimeoutError)


class Batch(Protocol):
    def add(self, event: EventData) -> None: ...


class Producer(Protocol):
    async def create_batch(self, *, partition_key: str) -> Batch: ...
    async def send_batch(self, batch: Batch) -> None: ...


class DeadLetterSink(Protocol):
    async def write(self, event: Any, reason: str, attempts: int) -> None: ...


async def _reject(event: Any, reason: str, attempts: int, sink: DeadLetterSink | None) -> None:
    if sink is None:
        raise ValueError(f"event rejected without a dead-letter sink: {reason}")
    await sink.write(event, reason, attempts)


async def _send_with_retry(
    producer: Producer,
    batch: Batch,
    events: list[MatchEvent],
    sink: DeadLetterSink | None,
    *,
    max_attempts: int,
    retry_delay: float,
) -> int:
    for attempt in range(1, max_attempts + 1):
        try:
            await producer.send_batch(batch)
            return len(events)
        except RETRYABLE_ERRORS as exc:
            if attempt < max_attempts:
                await asyncio.sleep(retry_delay * 2 ** (attempt - 1))
                continue
            for event in events:
                await _reject(event, type(exc).__name__, attempt, sink)
            return 0
    raise AssertionError("retry loop ended without a result")


async def publish_events(
    events: AsyncIterable[MatchEvent],
    producer: Producer,
    *,
    dead_letter: DeadLetterSink | None = None,
    max_attempts: int = 3,
    retry_delay: float = 0.25,
) -> int:
    """Validate and publish one match in order, retrying transient send failures.

    Retrying an unacknowledged batch can duplicate events; consumers can deduplicate
    by the deterministic event_id. A failed dead-letter write raises immediately.
    """
    if max_attempts < 1 or retry_delay < 0:
        raise ValueError("max_attempts must be positive and retry_delay non-negative")
    match_id: str | None = None
    batch: Batch | None = None
    pending: list[MatchEvent] = []
    published = 0

    async for event in events:
        try:
            validate_event(event)
        except ValidationError:
            await _reject(event, "schema_validation", 0, dead_letter)
            continue

        if match_id is None:
            match_id = event["match_id"]
            batch = await producer.create_batch(partition_key=match_id)
        elif event["match_id"] != match_id:
            await _reject(event, "mixed_match_id", 0, dead_letter)
            continue

        data = EventData(json.dumps(event, separators=(",", ":")))
        assert batch is not None
        try:
            batch.add(data)
        except ValueError:
            if not pending:
                await _reject(event, "event_exceeds_batch_limit", 0, dead_letter)
                continue
            published += await _send_with_retry(
                producer, batch, pending, dead_letter,
                max_attempts=max_attempts, retry_delay=retry_delay,
            )
            batch = await producer.create_batch(partition_key=match_id)
            pending = []
            try:
                batch.add(data)
            except ValueError:
                await _reject(event, "event_exceeds_batch_limit", 0, dead_letter)
                continue
        pending.append(event)

    if pending:
        assert batch is not None
        published += await _send_with_retry(
            producer, batch, pending, dead_letter,
            max_attempts=max_attempts, retry_delay=retry_delay,
        )
    return published


async def _run() -> None:
    parser = build_parser("Publish a synthetic match stream to Azure Event Hubs")
    args = parser.parse_args()
    connection_string = os.environ.get("EVENT_HUB_SEND_CONNECTION_STRING")
    if not connection_string:
        parser.error("EVENT_HUB_SEND_CONNECTION_STRING must be set")
    dead_letter_path = os.environ.get("DEAD_LETTER_PATH")
    if not dead_letter_path:
        parser.error("DEAD_LETTER_PATH must be set to a writable persistent file")
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
            dead_letter=JsonlDeadLetterSink(dead_letter_path),
        )
    print(f"Published {count} synthetic match events", file=sys.stderr)


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

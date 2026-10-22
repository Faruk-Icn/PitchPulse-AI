"""Real SDK round trip against the Azure Event Hubs emulator when configured."""

import asyncio
import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from azure.eventhub.aio import EventHubConsumerClient, EventHubProducerClient

from src.ingestion.dead_letter import JsonlDeadLetterSink
from src.ingestion.generator import iter_match_events
from src.ingestion.producer import publish_events


CONNECTION = os.environ.get("EVENT_HUB_TEST_CONNECTION_STRING")
HUB_NAME = os.environ.get("EVENT_HUB_TEST_NAME")


async def as_async(items):
    for item in items:
        yield item


@unittest.skipUnless(CONNECTION and HUB_NAME, "Event Hubs emulator connection is not configured")
class EventHubRoundTripTests(unittest.TestCase):
    def test_generated_events_are_received_from_event_hubs(self):
        asyncio.run(self._round_trip())

    async def _round_trip(self):
        match_id = f"integration-{uuid.uuid4()}"
        sent = list(iter_match_events(
            scenario="counter_attack", rate=100, count=4, match_id=match_id,
            started_at=datetime.now(timezone.utc),
        ))
        for attempt in range(30):
            probe = EventHubProducerClient.from_connection_string(CONNECTION, eventhub_name=HUB_NAME)
            try:
                async with probe:
                    await probe.get_eventhub_properties()
                    break
            except Exception:
                if attempt == 29:
                    raise
                await asyncio.sleep(2)

        with tempfile.TemporaryDirectory() as directory:
            dead_letter_path = Path(directory) / "failed.jsonl"
            producer = EventHubProducerClient.from_connection_string(CONNECTION, eventhub_name=HUB_NAME)
            async with producer:
                published = await publish_events(
                    as_async(sent), producer,
                    dead_letter=JsonlDeadLetterSink(dead_letter_path),
                )
            self.assertEqual(published, len(sent))
            self.assertFalse(dead_letter_path.exists())

        received = []
        complete = asyncio.Event()

        async def on_event(_partition, event):
            if event is None:
                return
            payload = json.loads(event.body_as_str())
            if payload.get("match_id") == match_id:
                received.append(payload)
                if len(received) == len(sent):
                    complete.set()

        consumer = EventHubConsumerClient.from_connection_string(
            CONNECTION, consumer_group="$Default", eventhub_name=HUB_NAME,
        )
        async with consumer:
            task = asyncio.create_task(consumer.receive(on_event=on_event, starting_position="-1", max_wait_time=2))
            try:
                await asyncio.wait_for(complete.wait(), timeout=45)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertEqual([event["event_id"] for event in received], [event["event_id"] for event in sent])


if __name__ == "__main__":
    unittest.main()

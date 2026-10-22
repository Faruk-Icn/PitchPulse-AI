"""Checks for the match wire format and offline Event Hubs batching."""

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from azure.eventhub.exceptions import EventDataSendError
from jsonschema import Draft202012Validator, FormatChecker

from src.ingestion.dead_letter import JsonlDeadLetterSink
from src.ingestion.generator import PRESETS, iter_match_events
from src.ingestion.producer import publish_events


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "config" / "match-event.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def as_async(items):
    for item in items:
        yield item


class FakeBatch:
    def __init__(self, limit):
        self.limit = limit
        self.items = []

    def add(self, event):
        if len(self.items) >= self.limit:
            raise ValueError("batch full")
        self.items.append(json.loads(event.body_as_str()))


class FakeProducer:
    def __init__(self, limit=2, failures=0):
        self.limit = limit
        self.failures = failures
        self.attempts = 0
        self.partition_keys = []
        self.sent = []

    async def create_batch(self, *, partition_key):
        self.partition_keys.append(partition_key)
        return FakeBatch(self.limit)

    async def send_batch(self, batch):
        self.attempts += 1
        if self.failures:
            self.failures -= 1
            raise EventDataSendError("transient send failure")
        self.sent.append(batch.items)


class IngestionTests(unittest.TestCase):
    def test_every_preset_produces_valid_ordered_events(self):
        Draft202012Validator.check_schema(SCHEMA)
        for scenario in PRESETS:
            with self.subTest(scenario=scenario):
                events = list(iter_match_events(scenario=scenario, rate=2, count=12, seed=7, started_at=START))
                self.assertEqual(len(events), 34)
                self.assertEqual([event["sequence"] for event in events], list(range(34)))
                self.assertEqual(len({event["event_id"] for event in events}), 34)
                self.assertEqual({event["player"]["team_id"] for event in events[:22]}, {"HOME", "AWAY"})
                for event in events:
                    VALIDATOR.validate(event)
                times = [datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")) for event in events]
                self.assertTrue(all((later - earlier).total_seconds() == 0.5 for earlier, later in zip(times, times[1:])))

    def test_fixed_seed_and_start_are_reproducible(self):
        options = dict(scenario="high_press", rate=5, count=9, seed=12, started_at=START)
        self.assertEqual(list(iter_match_events(**options)), list(iter_match_events(**options)))

    def test_scenario_play_sequence_and_coordinates(self):
        for scenario in PRESETS:
            with self.subTest(scenario=scenario):
                events = list(iter_match_events(scenario=scenario, rate=10, count=6, started_at=START))
                play = events[22:]
                self.assertEqual([event["event_type"] for event in play],
                                 ["position", "pass", "position", "pass", "position", "shot"])
                self.assertEqual(play[-1]["team_id"], "HOME")
                self.assertTrue(0 <= play[-1]["location"]["x"] <= 100)

    def test_invalid_event_rate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "rate must be finite"):
            list(iter_match_events(scenario="build_up", rate=float("nan"), count=1))

    def test_batch_overflow_flushes_without_dropping_or_reordering(self):
        events = list(iter_match_events(scenario="build_up", rate=100, count=3, started_at=START))
        fake = FakeProducer(limit=2)
        published = asyncio.run(publish_events(as_async(events), fake))
        self.assertEqual(published, len(events))
        self.assertEqual([len(batch) for batch in fake.sent], [2] * 12 + [1])
        self.assertEqual([item["sequence"] for batch in fake.sent for item in batch], list(range(len(events))))
        self.assertTrue(all(key == "synthetic-match" for key in fake.partition_keys))

    def test_rejects_an_event_that_cannot_fit_a_batch(self):
        event = next(iter_match_events(scenario="build_up", rate=2, count=0, started_at=START))
        with self.assertRaisesRegex(ValueError, "event_exceeds_batch_limit"):
            asyncio.run(publish_events(as_async([event]), FakeProducer(limit=0)))

    def test_invalid_event_is_dead_lettered_before_publish(self):
        event = next(iter_match_events(scenario="build_up", rate=2, count=0, started_at=START))
        event["player"]["shirt_number"] = 0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failed.jsonl"
            fake = FakeProducer()
            count = asyncio.run(publish_events(
                as_async([event]), fake, dead_letter=JsonlDeadLetterSink(path),
            ))
            self.assertEqual(count, 0)
            self.assertEqual(fake.sent, [])
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(record["reason"], "schema_validation")
            self.assertEqual(record["event"]["event_id"], event["event_id"])

    def test_transient_failure_retries_then_publishes(self):
        event = next(iter_match_events(scenario="build_up", rate=2, count=0, started_at=START))
        fake = FakeProducer(failures=2)
        count = asyncio.run(publish_events(as_async([event]), fake, retry_delay=0))
        self.assertEqual(count, 1)
        self.assertEqual(fake.attempts, 3)

    def test_exhausted_retries_dead_letter_the_batch(self):
        event = next(iter_match_events(scenario="build_up", rate=2, count=0, started_at=START))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failed.jsonl"
            fake = FakeProducer(failures=3)
            count = asyncio.run(publish_events(
                as_async([event]), fake,
                dead_letter=JsonlDeadLetterSink(path), retry_delay=0,
            ))
            self.assertEqual(count, 0)
            self.assertEqual(fake.attempts, 3)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["attempts"], 3)


if __name__ == "__main__":
    unittest.main()

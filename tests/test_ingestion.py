"""Checks for the match wire format and offline Event Hubs batching."""

import asyncio
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

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
    def __init__(self, limit=2):
        self.limit = limit
        self.partition_keys = []
        self.sent = []

    async def create_batch(self, *, partition_key):
        self.partition_keys.append(partition_key)
        return FakeBatch(self.limit)

    async def send_batch(self, batch):
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
        with self.assertRaisesRegex(ValueError, "single match event exceeds"):
            asyncio.run(publish_events(as_async([event]), FakeProducer(limit=0)))


if __name__ == "__main__":
    unittest.main()

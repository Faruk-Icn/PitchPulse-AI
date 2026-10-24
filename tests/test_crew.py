"""Deterministic geometry and crew routing tests."""

import asyncio
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from src.agents.consumer import CrewStreamProcessor
from src.agents.pass_difficulty import calculate_pass_difficulty
from src.agents.storyteller import StorytellerAgent
from src.agents.tactician import TacticianAgent
from src.agents.tactical_pressure import calculate_tactical_pressure
from src.ingestion.generator import iter_match_events


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def event(sequence, kind, **fields):
    return {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"crew:{sequence}")),
        "match_id": "synthetic-match",
        "sequence": sequence,
        "occurred_at": (START + timedelta(seconds=sequence / 10)).isoformat().replace("+00:00", "Z"),
        "event_type": kind,
        **fields,
    }


class Runner:
    def __init__(self):
        self.messages = []

    async def run(self, message):
        self.messages.append(json.loads(message))
        return SimpleNamespace(text="A forward pass beats the nearby defender.")


class GeometryTests(unittest.TestCase):
    def test_pass_difficulty_changes_with_lane_distance_and_attack_angle(self):
        start = {"x": 30, "y": 50}
        forward = {"x": 60, "y": 50}
        near = calculate_pass_difficulty(start, forward, "HOME", {"d": {"x": 45, "y": 50}})
        far = calculate_pass_difficulty(start, forward, "HOME", {"d": {"x": 45, "y": 90}})
        backward = calculate_pass_difficulty(forward, start, "HOME", {"d": {"x": 45, "y": 50}})
        self.assertGreater(near.index, far.index)
        self.assertGreater(near.index, backward.index)
        self.assertEqual(near.attack_angle_degrees, 0)
        self.assertEqual(backward.attack_angle_degrees, 180)
        self.assertIsNone(calculate_pass_difficulty(start, forward, "HOME", {}))
        self.assertIsNone(calculate_pass_difficulty(start, start, "HOME", {"d": start}))

    def test_pressure_is_local_density(self):
        carrier = {"x": 50, "y": 50}
        one = calculate_tactical_pressure(carrier, {"d1": {"x": 52, "y": 50}})
        two = calculate_tactical_pressure(carrier, {
            "d1": {"x": 52, "y": 50}, "d2": {"x": 53, "y": 50},
        })
        distant = calculate_tactical_pressure(carrier, {"d1": {"x": 90, "y": 50}})
        self.assertEqual(one.defenders_within_10m, 1)
        self.assertEqual(two.defenders_within_10m, 2)
        self.assertGreater(two.defenders_per_100m2, one.defenders_per_100m2)
        self.assertGreater(two.weighted_pressure_index, one.weighted_pressure_index)
        self.assertEqual(distant.weighted_pressure_index, 0)
        self.assertIsNone(calculate_tactical_pressure(carrier, {}))


class CrewTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_pass_with_shared_snapshots_and_deduplicates(self):
        runner = Runner()
        processor = CrewStreamProcessor(
            storyteller_factory=lambda match_id: StorytellerAgent(match_id, runner),
        )
        roster = list(iter_match_events(
            scenario="build_up", rate=10, count=0, started_at=START,
        ))
        for item in roster:
            result = await processor.process_body(json.dumps(item))
            self.assertIsNone(result.narrative)
        position = event(22, "position", player_id="away-02", team_id="AWAY",
                         coordinates={"x": 45, "y": 50})
        await processor.process_body(json.dumps(position))
        passed = event(23, "pass", player_id="home-07", team_id="HOME",
                       recipient_id="home-09", start={"x": 30, "y": 50},
                       end={"x": 60, "y": 50}, outcome="completed")
        result = await processor.process_body(json.dumps(passed))
        self.assertEqual(result.tactical.sequence, 23)
        self.assertEqual(result.stats.pass_attempts["HOME"], 1)
        self.assertEqual(result.narrative.sequence, 23)
        self.assertGreater(result.pass_difficulty.index, 0)
        self.assertEqual(result.tactical_pressure.defenders_within_10m, 0)
        self.assertEqual(runner.messages[0]["stats"]["sequence"], 23)
        self.assertIsNotNone(runner.messages[0]["calculations"]["pass_difficulty"])
        self.assertIsNone(await processor.process_body(json.dumps(passed)))
        self.assertEqual(len(runner.messages), 1)

    async def test_sparse_positions_report_unavailable_metrics(self):
        processor = CrewStreamProcessor()
        passed = event(0, "pass", player_id="home-07", team_id="HOME",
                       recipient_id="home-09", start={"x": 30, "y": 50},
                       end={"x": 60, "y": 50}, outcome="completed")
        result = await processor.process_body(json.dumps(passed))
        self.assertIsNone(result.pass_difficulty)
        self.assertIsNone(result.tactical_pressure)

    async def test_analysis_does_not_wait_for_narrative(self):
        class SlowRunner:
            async def run(self, _message):
                await asyncio.sleep(0.05)
                return SimpleNamespace(text="A pass is attempted.")

        delivered = []

        async def sink(_event, result):
            delivered.append(result)

        processor = CrewStreamProcessor(
            storyteller_factory=lambda match_id: StorytellerAgent(match_id, SlowRunner()),
            narrative_sink=sink,
        )
        passed = event(0, "pass", player_id="home-07", team_id="HOME",
                       recipient_id="home-09", start={"x": 30, "y": 50},
                       end={"x": 60, "y": 50}, outcome="completed")
        analysis = await processor.process_body(json.dumps(passed))
        self.assertIsNone(analysis.narrative)
        self.assertEqual(delivered, [])
        await processor.drain()
        self.assertEqual(delivered[0].narrative.sequence, 0)

    async def test_spatial_snapshot_is_reused_until_position_changes(self):
        tactician = TacticianAgent("synthetic-match")
        position = event(0, "position", player_id="away-02", team_id="AWAY",
                         coordinates={"x": 45, "y": 50})
        passed = event(1, "pass", player_id="home-07", team_id="HOME",
                       recipient_id="home-09", start={"x": 30, "y": 50},
                       end={"x": 60, "y": 50}, outcome="completed")
        tactician.process(position)
        with patch.object(tactician, "_pitch_control", wraps=tactician._pitch_control) as control:
            tactician.process(passed)
            self.assertEqual(control.call_count, 0)
            moved = event(2, "position", player_id="away-02", team_id="AWAY",
                          coordinates={"x": 40, "y": 50})
            tactician.process(moved)
            self.assertEqual(control.call_count, 1)


if __name__ == "__main__":
    unittest.main()

"""Agent behavior against the real synthetic match wire format."""

import asyncio
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_framework import Agent, ChatResponse, Message

from src.agents.config import AgentSettings
from src.agents.stats_analyst import StatsAnalystAgent
from src.agents.storyteller import StorytellerAgent
from src.agents.tactician import TacticianAgent
from src.agents.xg_geometry import live_features, statsbomb_features
from src.ingestion.generator import iter_match_events


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def roster():
    return list(iter_match_events(scenario="build_up", rate=10, count=0, started_at=START))


def full_position_stream():
    events = roster()
    for index, record in enumerate(events[:]):
        player = record["player"]
        number = player["shirt_number"]
        if number == 1:
            x = 5
            y = 50
        elif number <= 5:
            x = 25
            y = 15 + (number - 2) * 23
        elif number <= 8:
            x = 50
            y = 25 + (number - 6) * 25
        else:
            x = 78
            y = 25 + (number - 9) * 25
        if player["team_id"] == "AWAY":
            x = 100 - x
        sequence = 22 + index
        events.append({
            "schema_version": "1.0",
            "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"test-match:{sequence}")),
            "match_id": "synthetic-match",
            "sequence": sequence,
            "occurred_at": (START + timedelta(seconds=sequence / 10)).isoformat().replace("+00:00", "Z"),
            "event_type": "position",
            "player_id": player["player_id"],
            "team_id": player["team_id"],
            "coordinates": {"x": x, "y": y},
        })
    return events


class FakeRunner:
    def __init__(self, texts):
        self.texts = iter(texts)
        self.messages = []

    async def run(self, message):
        self.messages.append(json.loads(message))
        return SimpleNamespace(text=next(self.texts))


class OfflineChatClient:
    async def get_response(self, messages, **_kwargs):
        return ChatResponse(messages=Message("assistant", ["The pass is complete."]))


class AgentTests(unittest.TestCase):
    def test_tactician_requires_complete_fresh_positions(self):
        agent = TacticianAgent("synthetic-match")
        for event in roster():
            snapshot = agent.process(event)
        self.assertEqual(snapshot.formations, {"HOME": None, "AWAY": None})
        self.assertIsNone(snapshot.pitch_control_proxy)

        agent = TacticianAgent("synthetic-match")
        for event in full_position_stream():
            snapshot = agent.process(event)
        self.assertEqual(snapshot.formations, {"HOME": "4-3-3", "AWAY": "4-3-3"})
        self.assertEqual(snapshot.observed_positions, {"HOME": 11, "AWAY": 11})
        self.assertIsNotNone(snapshot.pitch_control_proxy)
        self.assertAlmostEqual(sum(snapshot.pitch_control_proxy.values()), 1.0, places=4)

    def test_tactician_expires_old_positions(self):
        agent = TacticianAgent("synthetic-match", AgentSettings(position_max_age_seconds=1))
        for event in full_position_stream():
            snapshot = agent.process(event)
        self.assertIsNone(snapshot.pitch_control_proxy)

    def test_stats_aggregates_passes_and_location_xg(self):
        agent = StatsAnalystAgent("synthetic-match")
        events = list(iter_match_events(scenario="build_up", rate=10, count=6, started_at=START))
        for event in events:
            snapshot = agent.process(event)
        self.assertEqual(snapshot.pass_attempts["HOME"], 2)
        self.assertEqual(snapshot.completed_passes["HOME"], 2)
        self.assertEqual(snapshot.passing_accuracy["HOME"], 1.0)
        self.assertIsNone(snapshot.passing_accuracy["AWAY"])
        self.assertEqual(snapshot.shots["HOME"], 1)
        self.assertGreater(snapshot.latest_shot_xg, 0)
        self.assertEqual(snapshot.cumulative_xg["HOME"], snapshot.latest_shot_xg)

        pressured = StatsAnalystAgent("synthetic-match")
        for event in iter_match_events(scenario="high_press", rate=10, count=6, started_at=START):
            pressured_snapshot = pressured.process(event)
        self.assertEqual(pressured_snapshot.passing_accuracy["AWAY"], 0.0)
        self.assertEqual(pressured_snapshot.passing_accuracy["HOME"], 1.0)

    def test_xg_features_respect_attack_direction_and_training_scale(self):
        self.assertEqual(live_features({"x": 80, "y": 50}, "HOME"),
                         live_features({"x": 20, "y": 50}, "AWAY"))
        self.assertEqual(live_features({"x": 80, "y": 50}, "HOME"), statsbomb_features(96, 40))
        model = json.loads((Path(__file__).parents[1] / "src" / "agents" / "xg_model.json").read_text())
        self.assertGreater(model["train_shots"], 1000)
        self.assertLess(model["test_brier"], model["constant_baseline_test_brier"])
        weights = model["coefficients"]
        near = sum(a * b for a, b in zip(weights, live_features({"x": 90, "y": 50}, "HOME")))
        far = sum(a * b for a, b in zip(weights, live_features({"x": 50, "y": 50}, "HOME")))
        self.assertGreater(near, far)

    def test_storyteller_sends_structured_event_and_retries_empty_response(self):
        event = roster()[0]
        runner = FakeRunner([" ", "A synthetic player record arrived."])
        agent = StorytellerAgent("synthetic-match", runner)
        with self.assertRaisesRegex(ValueError, "empty commentary"):
            asyncio.run(agent.process(event))
        result = asyncio.run(agent.process(event))
        self.assertEqual(result.sequence, event["sequence"])
        self.assertEqual(runner.messages[1]["event"]["event_id"], event["event_id"])
        self.assertEqual(agent.last_sequence, event["sequence"])

    def test_storyteller_uses_agent_framework_foundry_client(self):
        settings = AgentSettings(
            foundry_project_endpoint="https://unit-test.services.ai.azure.com/api/projects/check",
            foundry_model="unit-test-deployment",
        )
        with patch("src.agents.storyteller.DefaultAzureCredential") as credential, \
             patch("src.agents.storyteller.FoundryChatClient") as client, \
             patch("src.agents.storyteller.Agent") as framework_agent:
            result = StorytellerAgent.from_foundry("synthetic-match", settings)
        client.assert_called_once_with(
            project_endpoint=settings.foundry_project_endpoint,
            model=settings.foundry_model,
            credential=credential.return_value,
        )
        self.assertIs(result.runner, framework_agent.return_value)

    def test_storyteller_runs_through_real_agent_framework_agent(self):
        event = roster()[0]
        framework_agent = Agent(client=OfflineChatClient(), instructions="Speak briefly")
        storyteller = StorytellerAgent("synthetic-match", framework_agent)
        result = asyncio.run(storyteller.process(event))
        self.assertEqual(result.text, "The pass is complete.")


if __name__ == "__main__":
    unittest.main()

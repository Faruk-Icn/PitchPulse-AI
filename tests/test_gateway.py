"""WebSocket delivery and gateway behavior without live Azure services."""

import unittest
import json
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.gateway.app import create_app
from src.gateway.personalization import FanPersonalizer, FanProfile
from src.agents.config import AgentSettings
from src.ingestion.generator import iter_match_events


class OverlayTests(unittest.TestCase):
    def test_studio_serves_ui_and_syncs_live_overlay(self):
        app = create_app()
        record = {"kind": "analysis", "match_id": "match-1", "event": {"match_id": "match-1", "sequence": 1}, "result": {}}
        with TestClient(app) as client:
            response = client.get("/studio")
            self.assertEqual(response.status_code, 200)
            self.assertIn("PitchPulse AI", response.text)
            fan = client.get("/fan")
            self.assertEqual(fan.status_code, 200)
            self.assertIn("preferences-form", fan.text)
            setup = client.get("/setup")
            self.assertEqual(setup.status_code, 200)
            self.assertIn('id="setup-form"', setup.text)
            self.assertEqual(client.get("/static/setup.js").status_code, 200)
            with client.websocket_connect("/ws/studio") as socket:
                client.portal.call(app.state.overlays.broadcast, record)
                self.assertEqual(socket.receive_json(), record)
            with client.websocket_connect("/ws/studio") as socket:
                self.assertEqual(socket.receive_json(), record)

    def test_studio_match_filter_receives_only_its_match(self):
        app = create_app()
        with TestClient(app) as client:
            with client.websocket_connect("/ws/studio?match_id=match-2") as socket:
                client.portal.call(app.state.overlays.broadcast, {
                    "kind": "analysis", "match_id": "match-1", "sequence": 0,
                })
                client.portal.call(app.state.overlays.broadcast, {
                    "kind": "analysis", "match_id": "match-2", "sequence": 1,
                })
                self.assertEqual(socket.receive_json()["match_id"], "match-2")

    def test_event_routes_to_analyst_and_match_scoped_fan_stream(self):
        app = create_app()
        event = next(iter(iter_match_events(
            scenario="build_up", rate=10, count=1,
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )))
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").json()["status"], "waiting_for_source")
            with client.websocket_connect("/ws/studio") as studio:
                with client.websocket_connect(f"/ws/fan/{event['match_id']}") as fan:
                    client.portal.call(app.state.engine.handle_body, json.dumps(event))
                    analyst_record = studio.receive_json()
                    fan_record = fan.receive_json()
                    self.assertEqual(analyst_record["kind"], "analysis")
                    self.assertEqual(analyst_record["event"]["event_id"], event["event_id"])
                    self.assertEqual(fan_record["kind"], "match_event")
                    self.assertEqual(fan_record["match_id"], event["match_id"])
                    self.assertEqual(fan_record["stats"]["sequence"], event["sequence"])

    def test_fan_profiles_share_one_generation_per_language_and_style(self):
        class Personalizer:
            def __init__(self):
                self.calls = []

            async def generate(self, event, _result, profile):
                self.calls.append((event["sequence"], profile))
                return f"{profile.language}: pass received"

        personalizer = Personalizer()
        app = create_app(personalizer=personalizer)
        event = {
            "schema_version": "1.0", "event_id": "6e93cb84-f6e1-4990-a42e-13d066bf0869",
            "match_id": "match-1", "sequence": 0,
            "occurred_at": "2026-01-01T00:00:00Z", "event_type": "pass",
            "player_id": "home-07", "recipient_id": "home-09", "team_id": "HOME",
            "start": {"x": 30, "y": 50}, "end": {"x": 60, "y": 50},
            "outcome": "completed",
        }
        with TestClient(app) as client:
            with client.websocket_connect("/ws/fan/match-1?language=en&style=concise") as first:
                with client.websocket_connect("/ws/fan/match-1?language=en&style=concise") as second:
                    with client.websocket_connect("/ws/fan/match-1?language=es&style=tactical") as spanish:
                        client.portal.call(app.state.engine.handle_body, json.dumps(event))
                        for socket in (first, second, spanish):
                            self.assertEqual(socket.receive_json()["kind"], "match_event")
                        client.portal.call(app.state.engine.drain)
                        self.assertEqual(first.receive_json()["text"], "en: pass received")
                        self.assertEqual(second.receive_json()["text"], "en: pass received")
                        self.assertEqual(spanish.receive_json()["text"], "es: pass received")
        self.assertEqual(len(personalizer.calls), 2)


class FoundryPersonalizationTests(unittest.TestCase):
    def test_generation_uses_fact_payload_and_requested_language(self):
        from src.agents.crew import MatchAgentCrew

        event = {
            "schema_version": "1.0", "event_id": "6e93cb84-f6e1-4990-a42e-13d066bf0869",
            "match_id": "match-1", "sequence": 0,
            "occurred_at": "2026-01-01T00:00:00Z", "event_type": "pass",
            "player_id": "home-07", "recipient_id": "home-09", "team_id": "HOME",
            "start": {"x": 30, "y": 50}, "end": {"x": 60, "y": 50},
            "outcome": "completed",
        }
        result = asyncio.run(MatchAgentCrew("match-1").process(event))
        with patch("src.gateway.personalization.Agent") as agent:
            agent.return_value.run = AsyncMock(return_value=SimpleNamespace(text="  Passe réussie.  "))
            text = asyncio.run(FanPersonalizer(object()).generate(event, result, FanProfile("fr", "concise")))
        self.assertEqual(text, "Passe réussie.")
        self.assertIn("French", agent.call_args.kwargs["instructions"])
        supplied = json.loads(agent.return_value.run.call_args.args[0])
        self.assertEqual(supplied["event"]["event_id"], event["event_id"])
        self.assertEqual(supplied["stats"]["pass_attempts"]["HOME"], 1)

    def test_foundry_client_uses_project_endpoint_and_model(self):
        settings = AgentSettings(foundry_project_endpoint="https://foundry.invalid/project", foundry_model="deployed-model")
        with patch("src.gateway.personalization.DefaultAzureCredential") as credential:
            with patch("src.gateway.personalization.FoundryChatClient") as client:
                result = FanPersonalizer.from_settings(settings)
        client.assert_called_once_with(
            project_endpoint=settings.foundry_project_endpoint,
            model=settings.foundry_model,
            credential=credential.return_value,
        )
        self.assertIs(result.client, client.return_value)


if __name__ == "__main__":
    unittest.main()

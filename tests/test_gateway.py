"""WebSocket delivery and gateway behavior without live Azure services."""

import unittest
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.gateway.app import create_app
from src.ingestion.generator import iter_match_events


class OverlayTests(unittest.TestCase):
    def test_studio_serves_ui_and_syncs_live_overlay(self):
        app = create_app()
        record = {"kind": "analysis", "event": {"match_id": "match-1", "sequence": 1}, "result": {}}
        with TestClient(app) as client:
            response = client.get("/studio")
            self.assertEqual(response.status_code, 200)
            self.assertIn("PitchPulse AI", response.text)
            with client.websocket_connect("/ws/studio") as socket:
                client.portal.call(app.state.overlays.broadcast, record)
                self.assertEqual(socket.receive_json(), record)
            with client.websocket_connect("/ws/studio") as socket:
                self.assertEqual(socket.receive_json(), record)

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


if __name__ == "__main__":
    unittest.main()

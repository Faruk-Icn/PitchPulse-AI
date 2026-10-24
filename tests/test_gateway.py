"""WebSocket delivery and gateway behavior without live Azure services."""

import unittest

from fastapi.testclient import TestClient

from src.gateway.app import create_app


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


if __name__ == "__main__":
    unittest.main()

"""Fan locale completeness and match fact translations."""

import json
import unittest

from fastapi.testclient import TestClient

from src.gateway.app import create_app
from src.gateway.localization import CATALOG, localize_event


PASS = {
    "schema_version": "1.0", "event_id": "6e93cb84-f6e1-4990-a42e-13d066bf0869",
    "match_id": "match-1", "sequence": 0,
    "occurred_at": "2026-01-01T00:00:00Z", "event_type": "pass",
    "player_id": "home-07", "recipient_id": "home-09", "team_id": "HOME",
    "start": {"x": 30, "y": 50}, "end": {"x": 60, "y": 50},
    "outcome": "completed",
}


class LocalizationTests(unittest.TestCase):
    def test_catalog_covers_supported_languages_and_right_to_left_arabic(self):
        self.assertEqual(set(CATALOG), {"en", "es", "fr", "de", "ar"})
        self.assertEqual(CATALOG["ar"]["dir"], "rtl")
        self.assertEqual(CATALOG["fr"]["dir"], "ltr")
        self.assertEqual(localize_event(PASS, "es"), "LOCAL: Pase completado")
        self.assertEqual(localize_event(PASS, "ar"), "صاحب الأرض: تمريرة مكتملة")

    def test_config_and_websocket_use_same_catalog(self):
        app = create_app()
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/fan/config").json()["locales"], CATALOG)
            with client.websocket_connect("/ws/fan/match-1?language=fr") as fan:
                client.portal.call(app.state.engine.handle_body, json.dumps(PASS))
                record = fan.receive_json()
                self.assertEqual(record["language"], "fr")
                self.assertEqual(record["summary"], "DOMICILE: Passe réussie")


if __name__ == "__main__":
    unittest.main()

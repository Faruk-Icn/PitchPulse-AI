"""One Event Hubs event reaches analyst and personalized fan WebSockets."""

import base64
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from azure.eventhub.aio import EventHubProducerClient
from fastapi.testclient import TestClient

from src.gateway.app import create_app
from src.ingestion.dead_letter import JsonlDeadLetterSink
from src.ingestion.producer import publish_events


CONNECTION = os.environ.get("EVENT_HUB_TEST_CONNECTION_STRING")
HUB_NAME = os.environ.get("EVENT_HUB_TEST_NAME")


async def one_event(event):
    yield event


@unittest.skipUnless(CONNECTION and HUB_NAME, "Event Hubs emulator connection is not configured")
class MultiStreamIntegrationTests(unittest.TestCase):
    def test_event_hubs_to_studio_and_multilingual_fan_text_and_voice(self):
        class Personalizer:
            async def generate(self, _event, _result, profile):
                return f"{profile.language}: completed pass"

        class Voice:
            async def synthesize(self, text, language):
                self.text = text
                self.language = language
                return b"RIFF\x00\x00\x00\x00WAVE"

        match_id = f"multistream-{uuid.uuid4()}"
        event = {
            "schema_version": "1.0", "event_id": str(uuid.uuid4()),
            "match_id": match_id, "sequence": 0,
            "occurred_at": "2026-01-01T00:00:00Z", "event_type": "pass",
            "player_id": "home-07", "recipient_id": "home-09", "team_id": "HOME",
            "start": {"x": 30, "y": 50}, "end": {"x": 60, "y": 50},
            "outcome": "completed",
        }
        voice = Voice()
        with tempfile.TemporaryDirectory() as directory:
            dead_letter = Path(directory) / "failed.jsonl"
            with patch.dict(os.environ, {
                "EVENT_HUB_LISTEN_CONNECTION_STRING": CONNECTION,
                "EVENT_HUB_NAME": HUB_NAME,
                "DEAD_LETTER_PATH": str(dead_letter),
                "PITCHPULSE_MODE": "both",
            }):
                app = create_app(personalizer=Personalizer(), voice_engine=voice)
                with TestClient(app) as client:
                    with client.websocket_connect(f"/ws/studio?match_id={match_id}") as studio, \
                            client.websocket_connect(f"/ws/fan/{match_id}?language=en") as english, \
                            client.websocket_connect(f"/ws/fan/{match_id}?language=es&voice=1") as spanish:
                        async def publish():
                            producer = EventHubProducerClient.from_connection_string(
                                CONNECTION, eventhub_name=HUB_NAME,
                            )
                            async with producer:
                                return await publish_events(
                                    one_event(event), producer,
                                    dead_letter=JsonlDeadLetterSink(dead_letter),
                                )

                        self.assertEqual(client.portal.call(publish), 1)
                        analyst = studio.receive_json()
                        en_fact = english.receive_json()
                        es_fact = spanish.receive_json()
                        self.assertEqual(analyst["kind"], "analysis")
                        self.assertEqual(analyst["event"]["event_id"], event["event_id"])
                        self.assertEqual(en_fact["kind"], "match_event")
                        self.assertEqual(es_fact["kind"], "match_event")
                        self.assertEqual(en_fact["match_id"], match_id)
                        self.assertEqual(en_fact["language"], "en")
                        self.assertEqual(es_fact["language"], "es")
                        self.assertNotEqual(en_fact["summary"], es_fact["summary"])
                        self.assertEqual(english.receive_json()["text"], "en: completed pass")
                        self.assertEqual(spanish.receive_json()["text"], "es: completed pass")
                        audio = spanish.receive_json()
                        self.assertEqual(audio["kind"], "speech_audio")
                        self.assertEqual(base64.b64decode(audio["audio_base64"]), b"RIFF\x00\x00\x00\x00WAVE")
                        self.assertEqual((voice.text, voice.language), ("es: completed pass", "es"))
            self.assertFalse(dead_letter.exists())


if __name__ == "__main__":
    unittest.main()

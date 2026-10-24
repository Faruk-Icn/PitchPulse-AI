"""Speech SDK setup and fan audio routing without an Azure Speech account."""

import asyncio
import json
import unittest
from unittest.mock import MagicMock, patch

import azure.cognitiveservices.speech as speechsdk
from fastapi.testclient import TestClient

from src.gateway.app import create_app
from src.gateway.voice import SpeechVoiceEngine, VOICE_BY_LANGUAGE


PASS = {
    "schema_version": "1.0", "event_id": "6e93cb84-f6e1-4990-a42e-13d066bf0869",
    "match_id": "match-1", "sequence": 0,
    "occurred_at": "2026-01-01T00:00:00Z", "event_type": "pass",
    "player_id": "home-07", "recipient_id": "home-09", "team_id": "HOME",
    "start": {"x": 30, "y": 50}, "end": {"x": 60, "y": 50},
    "outcome": "completed",
}


class VoiceTests(unittest.TestCase):
    def test_speech_sdk_uses_language_voice_and_returns_wav_bytes(self):
        result = MagicMock()
        result.reason = speechsdk.ResultReason.SynthesizingAudioCompleted
        result.audio_data = b"RIFF\x00\x00\x00\x00WAVE"
        with patch("src.gateway.voice.speechsdk.SpeechConfig") as config:
            with patch("src.gateway.voice.speechsdk.SpeechSynthesizer") as synthesizer:
                synthesizer.return_value.speak_text_async.return_value.get.return_value = result
                audio = SpeechVoiceEngine("nonsecret-test-key", "westus")._synthesize_blocking("Passe réussie", "fr")
        self.assertEqual(audio, result.audio_data)
        self.assertEqual(config.return_value.speech_synthesis_voice_name, VOICE_BY_LANGUAGE["fr"])
        config.return_value.set_speech_synthesis_output_format.assert_called_once_with(
            speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm,
        )
        synthesizer.assert_called_once_with(speech_config=config.return_value, audio_config=None)

    def test_fan_voice_reuses_one_synthesis_for_profile(self):
        class Personalizer:
            async def generate(self, _event, _result, _profile):
                return "A pass was completed."

        class Voice:
            def __init__(self):
                self.calls = []

            async def synthesize(self, text, language):
                self.calls.append((text, language))
                return b"RIFF\x00\x00\x00\x00WAVE"

        voice = Voice()
        app = create_app(personalizer=Personalizer(), voice_engine=voice)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/fan/match-1?voice=1") as fan:
                client.portal.call(app.state.engine.handle_body, json.dumps(PASS))
                self.assertEqual(fan.receive_json()["kind"], "match_event")
                self.assertEqual(fan.receive_json()["kind"], "personalized_text")
                audio = fan.receive_json()
                self.assertEqual(audio["kind"], "speech_audio")
                self.assertEqual(audio["content_type"], "audio/wav")
        self.assertEqual(voice.calls, [("A pass was completed.", "en")])

    def test_unsupported_language_fails_before_speech_call(self):
        with self.assertRaises(ValueError):
            asyncio.run(SpeechVoiceEngine("key", "westus").synthesize("Hello", "xx"))


if __name__ == "__main__":
    unittest.main()

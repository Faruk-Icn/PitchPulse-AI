"""Azure Speech text-to-speech for the supported fan languages."""

from __future__ import annotations

import asyncio

import azure.cognitiveservices.speech as speechsdk


VOICE_BY_LANGUAGE = {
    "en": "en-US-JennyNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "ar": "ar-SA-ZariyahNeural",
}
CONTENT_TYPE = "audio/wav"


class SpeechVoiceEngine:
    def __init__(self, subscription_key: str, region: str) -> None:
        if not subscription_key or not region:
            raise ValueError("Speech key and region are required")
        self.subscription_key = subscription_key
        self.region = region

    async def synthesize(self, text: str, language: str) -> bytes:
        if language not in VOICE_BY_LANGUAGE:
            raise ValueError("unsupported voice language")
        if not text.strip():
            raise ValueError("speech text must not be empty")
        return await asyncio.to_thread(self._synthesize_blocking, text, language)

    def _synthesize_blocking(self, text: str, language: str) -> bytes:
        config = speechsdk.SpeechConfig(subscription=self.subscription_key, region=self.region)
        config.speech_synthesis_voice_name = VOICE_BY_LANGUAGE[language]
        config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm,
        )
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
        result = synthesizer.speak_text_async(text).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted or not result.audio_data:
            detail = speechsdk.SpeechSynthesisCancellationDetails.from_result(result)
            raise RuntimeError(f"Speech synthesis failed: {detail.reason}")
        return result.audio_data

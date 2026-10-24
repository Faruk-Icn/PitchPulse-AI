"""Match-scoped fan WebSocket stream carrying validated event facts."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import asdict, dataclass

from fastapi import WebSocket, WebSocketDisconnect

from src.agents.crew import CrewResult
from src.ingestion.models import MatchEvent

from .personalization import FanPersonalizer, FanProfile
from .localization import localize_event
from .voice import CONTENT_TYPE, SpeechVoiceEngine


@dataclass
class FanSubscription:
    match_id: str
    profile: FanProfile
    voice: bool
    lock: asyncio.Lock


class FanHub:
    def __init__(self, voice_engine: SpeechVoiceEngine | None = None) -> None:
        self._clients: dict[WebSocket, FanSubscription] = {}
        self._latest_by_match: dict[str, dict] = {}
        self._personalization_tasks: set[asyncio.Task] = set()
        self._model_slots = asyncio.Semaphore(4)
        self._voice_slots = asyncio.Semaphore(2)
        self.voice_engine = voice_engine
        self.logger = logging.getLogger("pitchpulse.gateway.fans")

    async def connect(self, socket: WebSocket, match_id: str, profile: FanProfile, *, voice: bool = False) -> None:
        await socket.accept()
        self._clients[socket] = FanSubscription(match_id, profile, voice, asyncio.Lock())
        if match_id in self._latest_by_match:
            await self._send(socket, self._localized_record(self._latest_by_match[match_id], profile.language))
        try:
            while True:
                await socket.receive_text()
        except WebSocketDisconnect:
            self._clients.pop(socket, None)

    async def broadcast(self, event: MatchEvent, result: CrewResult) -> None:
        record = {
            "kind": "match_event",
            "match_id": event["match_id"],
            "sequence": event["sequence"],
            "event": event,
            "stats": asdict(result.stats),
        }
        self._latest_by_match[event["match_id"]] = record
        recipients = [
            (socket, subscription.profile.language)
            for socket, subscription in tuple(self._clients.items())
            if subscription.match_id == event["match_id"]
        ]
        payloads = {
            language: self._encode(self._localized_record(record, language))
            for language in {language for _, language in recipients}
        }
        await asyncio.gather(*(
            self._send_text(socket, payloads[language]) for socket, language in recipients
        ))

    @staticmethod
    def _localized_record(record: dict, language: str) -> dict:
        return {**record, "language": language, "summary": localize_event(record["event"], language)}

    @staticmethod
    def _encode(record: dict) -> str:
        return json.dumps(record, separators=(",", ":"), ensure_ascii=False)

    async def schedule_personalization(
        self, event: MatchEvent, result: CrewResult, personalizer: FanPersonalizer,
    ) -> None:
        profiles = {
            subscription.profile for subscription in self._clients.values()
            if subscription.match_id == event["match_id"]
        }
        for profile in profiles:
            if len(self._personalization_tasks) >= 100:
                await asyncio.wait(self._personalization_tasks, return_when=asyncio.FIRST_COMPLETED)
            task = asyncio.create_task(self._personalize(event, result, profile, personalizer))
            self._personalization_tasks.add(task)
            task.add_done_callback(self._on_task_done)

    async def schedule_fact_voice(self, event: MatchEvent) -> None:
        if self.voice_engine is None:
            return
        profiles = {
            subscription.profile for subscription in self._clients.values()
            if subscription.match_id == event["match_id"] and subscription.voice
        }
        for profile in profiles:
            if len(self._personalization_tasks) >= 100:
                await asyncio.wait(self._personalization_tasks, return_when=asyncio.FIRST_COMPLETED)
            text = localize_event(event, profile.language)
            task = asyncio.create_task(self._publish_voice(event, profile, text))
            self._personalization_tasks.add(task)
            task.add_done_callback(self._on_task_done)

    async def _personalize(
        self, event: MatchEvent, result: CrewResult,
        profile: FanProfile, personalizer: FanPersonalizer,
    ) -> None:
        try:
            async with self._model_slots:
                text = await asyncio.wait_for(personalizer.generate(event, result, profile), timeout=15)
            record = {
                "kind": "personalized_text", "match_id": event["match_id"],
                "sequence": event["sequence"], "language": profile.language,
                "style": profile.style, "text": text,
            }
        except Exception:
            self.logger.exception("fan personalization failed match=%s sequence=%s", event["match_id"], event["sequence"])
            record = {
                "kind": "personalization_unavailable", "match_id": event["match_id"],
                "sequence": event["sequence"], "language": profile.language,
                "style": profile.style,
            }
        recipients = [
            socket for socket, subscription in tuple(self._clients.items())
            if subscription.match_id == event["match_id"] and subscription.profile == profile
        ]
        if recipients:
            payload = self._encode(record)
            await asyncio.gather(*(self._send_text(socket, payload) for socket in recipients))
        if record["kind"] == "personalized_text" and self.voice_engine is not None:
            await self._publish_voice(event, profile, text)
        elif record["kind"] == "personalization_unavailable" and self.voice_engine is not None:
            await self._publish_voice(event, profile, localize_event(event, profile.language))

    async def _publish_voice(self, event: MatchEvent, profile: FanProfile, text: str) -> None:
        listeners = [
            socket for socket, subscription in tuple(self._clients.items())
            if subscription.match_id == event["match_id"]
            and subscription.profile == profile and subscription.voice
        ]
        if not listeners:
            return
        try:
            async with self._voice_slots:
                audio = await asyncio.wait_for(self.voice_engine.synthesize(text, profile.language), timeout=20)
            record = {
                "kind": "speech_audio", "match_id": event["match_id"],
                "sequence": event["sequence"], "language": profile.language,
                "style": profile.style, "content_type": CONTENT_TYPE,
                "audio_base64": base64.b64encode(audio).decode("ascii"),
            }
        except Exception:
            self.logger.exception("fan speech failed match=%s sequence=%s", event["match_id"], event["sequence"])
            record = {
                "kind": "speech_unavailable", "match_id": event["match_id"],
                "sequence": event["sequence"], "language": profile.language,
                "style": profile.style,
            }
        if listeners:
            payload = self._encode(record)
            await asyncio.gather(*(self._send_text(socket, payload) for socket in listeners))

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._personalization_tasks.discard(task)
        error = None if task.cancelled() else task.exception()
        if error is not None:
            self.logger.error("fan output delivery failed", exc_info=(type(error), error, error.__traceback__))

    async def drain(self) -> None:
        if self._personalization_tasks:
            await asyncio.gather(*self._personalization_tasks)

    async def _send(self, socket: WebSocket, record: dict) -> None:
        await self._send_text(socket, self._encode(record))

    async def _send_text(self, socket: WebSocket, payload: str) -> None:
        client = self._clients.get(socket)
        if client is None:
            return
        try:
            async with client.lock:
                await asyncio.wait_for(socket.send_text(payload), timeout=1.0)
        except Exception:
            self.logger.warning("fan WebSocket disconnected during delivery")
            self._clients.pop(socket, None)

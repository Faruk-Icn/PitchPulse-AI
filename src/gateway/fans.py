"""Match-scoped fan WebSocket stream carrying validated event facts."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

from fastapi import WebSocket, WebSocketDisconnect

from src.agents.crew import CrewResult
from src.ingestion.models import MatchEvent


class FanHub:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, tuple[str, asyncio.Lock]] = {}
        self._latest_by_match: dict[str, dict] = {}
        self.logger = logging.getLogger("pitchpulse.gateway.fans")

    async def connect(self, socket: WebSocket, match_id: str) -> None:
        await socket.accept()
        self._clients[socket] = (match_id, asyncio.Lock())
        if match_id in self._latest_by_match:
            await self._send(socket, self._latest_by_match[match_id])
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
        await asyncio.gather(*(
            self._send(socket, record) for socket, (match_id, _) in tuple(self._clients.items())
            if match_id == event["match_id"]
        ))

    async def _send(self, socket: WebSocket, record: dict) -> None:
        client = self._clients.get(socket)
        if client is None:
            return
        try:
            async with client[1]:
                await asyncio.wait_for(socket.send_json(record), timeout=1.0)
        except Exception:
            self.logger.warning("fan WebSocket disconnected during delivery")
            self._clients.pop(socket, None)

"""WebSocket fan-out of verified analyst overlay records."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from fastapi import WebSocket, WebSocketDisconnect


@dataclass
class StudioSubscription:
    match_id: str | None
    lock: asyncio.Lock


class OverlayHub:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, StudioSubscription] = {}
        self._latest: dict | None = None
        self._latest_by_match: dict[str, dict] = {}
        self.logger = logging.getLogger("pitchpulse.gateway.overlays")

    async def connect(self, socket: WebSocket, match_id: str | None = None) -> None:
        await socket.accept()
        self._clients[socket] = StudioSubscription(match_id, asyncio.Lock())
        latest = self._latest_by_match.get(match_id) if match_id else self._latest
        if latest is not None:
            await self._send(socket, latest)
        try:
            while True:
                await socket.receive_text()
        except WebSocketDisconnect:
            self._clients.pop(socket, None)

    async def broadcast(self, record: dict) -> None:
        if record.get("kind") == "analysis":
            self._latest = record
            self._latest_by_match[record["match_id"]] = record
        await asyncio.gather(*(
            self._send(socket, record) for socket, subscription in tuple(self._clients.items())
            if subscription.match_id is None or subscription.match_id == record.get("match_id")
        ))

    async def _send(self, socket: WebSocket, record: dict) -> None:
        subscription = self._clients.get(socket)
        if subscription is None:
            return
        try:
            async with subscription.lock:
                await asyncio.wait_for(socket.send_json(record), timeout=1.0)
        except Exception:
            self.logger.warning("studio WebSocket disconnected during overlay delivery")
            self._clients.pop(socket, None)


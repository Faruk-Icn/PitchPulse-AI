"""WebSocket fan-out of verified analyst overlay records."""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect


class OverlayHub:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, asyncio.Lock] = {}
        self._latest: dict | None = None
        self.logger = logging.getLogger("pitchpulse.gateway.overlays")

    async def connect(self, socket: WebSocket) -> None:
        await socket.accept()
        self._clients[socket] = asyncio.Lock()
        if self._latest is not None:
            await self._send(socket, self._latest)
        try:
            while True:
                await socket.receive_text()
        except WebSocketDisconnect:
            self._clients.pop(socket, None)

    async def broadcast(self, record: dict) -> None:
        if record.get("kind") == "analysis":
            self._latest = record
        await asyncio.gather(*(self._send(socket, record) for socket in tuple(self._clients)))

    async def _send(self, socket: WebSocket, record: dict) -> None:
        lock = self._clients.get(socket)
        if lock is None:
            return
        try:
            async with lock:
                await asyncio.wait_for(socket.send_json(record), timeout=1.0)
        except Exception:
            self.logger.warning("studio WebSocket disconnected during overlay delivery")
            self._clients.pop(socket, None)


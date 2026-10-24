"""HTTP and WebSocket entry point for PitchPulse studio."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.agents.config import AgentSettings

from .engine import GatewayEngine, receive_event_hubs
from .fans import FanHub
from .overlays import OverlayHub
from .personalization import FanPersonalizer, FanProfile


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def create_app(*, personalizer: FanPersonalizer | None = None) -> FastAPI:
    overlays = OverlayHub()
    fans = FanHub()
    settings = AgentSettings.from_env()
    if bool(settings.foundry_project_endpoint) != bool(settings.foundry_model):
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL must be configured together")
    if personalizer is None and settings.foundry_project_endpoint:
        personalizer = FanPersonalizer.from_settings(settings)
    engine = GatewayEngine(
        overlays, fans, dead_letter_path=os.environ.get("DEAD_LETTER_PATH"),
        personalizer=personalizer, settings=settings,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        connection = os.environ.get("EVENT_HUB_LISTEN_CONNECTION_STRING")
        hub_name = os.environ.get("EVENT_HUB_NAME")
        if bool(connection) != bool(hub_name):
            raise ValueError("EVENT_HUB_LISTEN_CONNECTION_STRING and EVENT_HUB_NAME must be configured together")
        if connection and not os.environ.get("DEAD_LETTER_PATH"):
            raise ValueError("DEAD_LETTER_PATH is required when Event Hubs is configured")
        task = asyncio.create_task(receive_event_hubs(engine)) if connection else None
        app.state.source_task = task
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await engine.drain()

    app = FastAPI(title="PitchPulse AI Gateway", lifespan=lifespan)
    app.state.overlays = overlays
    app.state.fans = fans
    app.state.engine = engine
    app.state.source_task = None
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/health")
    async def health() -> JSONResponse:
        task = app.state.source_task
        if task is not None and task.done():
            error = task.exception() if not task.cancelled() else None
            logging.getLogger("pitchpulse.gateway").error("Event Hubs listener stopped", exc_info=error)
            return JSONResponse({"status": "source_failed"}, status_code=503)
        return JSONResponse({"status": "running" if task else "waiting_for_source"})

    @app.get("/studio", include_in_schema=False)
    async def studio() -> FileResponse:
        return FileResponse(FRONTEND / "index.html")

    @app.websocket("/ws/studio")
    async def studio_socket(socket: WebSocket) -> None:
        match_id = socket.query_params.get("match_id")
        if match_id and len(match_id) > 100:
            await socket.close(code=1008)
            return
        await app.state.overlays.connect(socket, match_id)

    @app.websocket("/ws/fan/{match_id}")
    async def fan_socket(socket: WebSocket, match_id: str) -> None:
        if not match_id or len(match_id) > 100:
            await socket.close(code=1008)
            return
        try:
            profile = FanProfile(
                language=socket.query_params.get("language", "en"),
                style=socket.query_params.get("style", "concise"),
            )
        except ValueError:
            await socket.close(code=1008)
            return
        await app.state.fans.connect(socket, match_id, profile)

    return app


app = create_app()

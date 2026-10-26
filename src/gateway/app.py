"""HTTP and WebSocket entry point for PitchPulse studio."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.agents.config import AgentSettings

from .engine import GatewayEngine, receive_event_hubs
from .fans import FanHub
from .localization import CATALOG
from .overlays import OverlayHub
from .personalization import FanPersonalizer, FanProfile
from .voice import SpeechVoiceEngine


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def create_app(*, personalizer: FanPersonalizer | None = None, voice_engine: SpeechVoiceEngine | None = None) -> FastAPI:
    mode = os.environ.get("PITCHPULSE_MODE", "both")
    if mode not in ("both", "broadcast", "fan"):
        raise ValueError("PITCHPULSE_MODE must be both, broadcast, or fan")
    overlays = OverlayHub()
    speech_key = os.environ.get("SPEECH_KEY")
    speech_region = os.environ.get("SPEECH_REGION")
    if bool(speech_key) != bool(speech_region):
        raise ValueError("SPEECH_KEY and SPEECH_REGION must be configured together")
    if voice_engine is None and speech_key and mode != "broadcast":
        voice_engine = SpeechVoiceEngine(speech_key, speech_region)
    fans = FanHub(voice_engine)
    settings = AgentSettings.from_env()
    if bool(settings.foundry_project_endpoint) != bool(settings.foundry_model):
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL must be configured together")
    if personalizer is None and settings.foundry_project_endpoint and mode != "broadcast":
        personalizer = FanPersonalizer.from_settings(settings)
    engine = GatewayEngine(
        overlays, fans, dead_letter_path=os.environ.get("DEAD_LETTER_PATH"),
        personalizer=personalizer, settings=settings, mode=mode,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        connection = os.environ.get("EVENT_HUB_LISTEN_CONNECTION_STRING")
        hub_name = os.environ.get("EVENT_HUB_NAME")
        if bool(connection) != bool(hub_name):
            raise ValueError("EVENT_HUB_LISTEN_CONNECTION_STRING and EVENT_HUB_NAME must be configured together")
        blob_settings = [os.environ.get(name) for name in (
            "BLOB_ACCOUNT_URL", "CHECKPOINT_CONTAINER", "DEAD_LETTER_CONTAINER",
        )]
        if any(blob_settings) and not all(blob_settings):
            raise ValueError("BLOB_ACCOUNT_URL, CHECKPOINT_CONTAINER and DEAD_LETTER_CONTAINER must be configured together")
        if connection and not (os.environ.get("DEAD_LETTER_PATH") or all(blob_settings)):
            raise ValueError("DEAD_LETTER_PATH or Blob dead-letter storage is required when Event Hubs is configured")
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
        if mode == "fan":
            raise HTTPException(status_code=404)
        return FileResponse(FRONTEND / "index.html")

    @app.get("/setup", include_in_schema=False)
    async def setup_page() -> FileResponse:
        return FileResponse(FRONTEND / "setup.html")

    @app.get("/fan", include_in_schema=False)
    async def fan_page() -> FileResponse:
        if mode == "broadcast":
            raise HTTPException(status_code=404)
        return FileResponse(FRONTEND / "fan.html")

    @app.get("/api/fan/config")
    async def fan_config() -> JSONResponse:
        if mode == "broadcast":
            raise HTTPException(status_code=404)
        return JSONResponse({"locales": CATALOG})

    @app.websocket("/ws/studio")
    async def studio_socket(socket: WebSocket) -> None:
        if mode == "fan":
            await socket.close(code=1008)
            return
        match_id = socket.query_params.get("match_id")
        if match_id and len(match_id) > 100:
            await socket.close(code=1008)
            return
        await app.state.overlays.connect(socket, match_id)

    @app.websocket("/ws/fan/{match_id}")
    async def fan_socket(socket: WebSocket, match_id: str) -> None:
        if mode == "broadcast":
            await socket.close(code=1008)
            return
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
        voice = socket.query_params.get("voice", "0")
        if voice not in ("0", "1"):
            await socket.close(code=1008)
            return
        await app.state.fans.connect(socket, match_id, profile, voice=voice == "1")

    return app


app = create_app()

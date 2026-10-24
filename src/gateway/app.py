"""HTTP and WebSocket entry point for PitchPulse studio."""

from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .overlays import OverlayHub


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(title="PitchPulse AI Gateway")
    app.state.overlays = OverlayHub()
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/studio", include_in_schema=False)
    async def studio() -> FileResponse:
        return FileResponse(FRONTEND / "index.html")

    @app.websocket("/ws/studio")
    async def studio_socket(socket: WebSocket) -> None:
        await app.state.overlays.connect(socket)

    return app


app = create_app()

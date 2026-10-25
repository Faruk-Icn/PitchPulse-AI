"""Run both real gateway views against the project's synthetic match stream."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

import uvicorn

from src.gateway.app import create_app
from src.ingestion.generator import PRESETS, stream_match_events


async def run(*, host: str, port: int, rate: float, scenario: str, match_id: str) -> None:
    if os.environ.get("EVENT_HUB_LISTEN_CONNECTION_STRING"):
        raise ValueError("Remove Event Hubs listener configuration before starting the local demo")
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))

    async def produce() -> None:
        while not server.started and not server.should_exit:
            await asyncio.sleep(.05)
        async for event in stream_match_events(
            scenario=scenario, rate=rate, count=None, match_id=match_id,
        ):
            await app.state.engine.handle_body(json.dumps(event, separators=(",", ":")))

    task = asyncio.create_task(produce())
    try:
        await server.serve()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await app.state.engine.drain()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--rate", type=float, default=8)
    parser.add_argument("--scenario", choices=sorted(PRESETS), default="high_press")
    parser.add_argument("--match-id", default="demo-match")
    args = parser.parse_args()
    asyncio.run(run(**vars(args)))


if __name__ == "__main__":
    main()

"""Measure validated event-to-WebSocket fan-out without cloud or model latency.

The sockets are in-memory transports. This isolates the synchronous factual
path and never counts Foundry or speech generation as part of the result.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from datetime import datetime, timezone

from src.gateway.engine import GatewayEngine
from src.gateway.fans import FanHub, FanSubscription
from src.gateway.overlays import OverlayHub, StudioSubscription
from src.gateway.personalization import FanProfile
from src.ingestion.generator import iter_match_events


class CountingSocket:
    def __init__(self) -> None:
        self.messages = 0

    async def send_text(self, _payload: str) -> None:
        self.messages += 1


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))]


async def benchmark(*, events: int, studio_clients: int, fan_clients: int) -> dict:
    if events <= 0 or studio_clients < 0 or fan_clients < 0:
        raise ValueError("events must be positive and client counts non-negative")
    overlays, fans = OverlayHub(), FanHub()
    engine = GatewayEngine(overlays, fans)
    sockets = []
    for _ in range(studio_clients):
        socket = CountingSocket()
        sockets.append(socket)
        overlays._clients[socket] = StudioSubscription("benchmark-match", asyncio.Lock())
    for index in range(fan_clients):
        socket = CountingSocket()
        sockets.append(socket)
        language = ("en", "es", "fr", "de", "ar")[index % 5]
        fans._clients[socket] = FanSubscription(
            "benchmark-match", FanProfile(language, "concise"), False, asyncio.Lock(),
        )
    source = iter_match_events(
        scenario="high_press", rate=100, count=events,
        match_id="benchmark-match", started_at=datetime.now(timezone.utc),
    )
    # Roster records establish state before timing the requested play events.
    for _ in range(22):
        await engine.handle_body(json.dumps(next(source), separators=(",", ":")))
    durations = []
    started = time.perf_counter()
    for event in source:
        body = json.dumps(event, separators=(",", ":"))
        before = time.perf_counter()
        await engine.handle_body(body)
        durations.append((time.perf_counter() - before) * 1000)
    elapsed = time.perf_counter() - started
    return {
        "scope": "in-process validation, analysis, and completed factual WebSocket sends; excludes Event Hubs, network, Foundry, and speech",
        "events": events,
        "studio_clients": studio_clients,
        "fan_clients": fan_clients,
        "p50_ms": round(statistics.median(durations), 2),
        "p95_ms": round(percentile(durations, .95), 2),
        "p99_ms": round(percentile(durations, .99), 2),
        "max_ms": round(max(durations), 2),
        "events_per_second": round(events / elapsed, 1),
        "socket_messages": sum(socket.messages for socket in sockets),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=200)
    parser.add_argument("--studio-clients", type=int, default=10)
    parser.add_argument("--fan-clients", type=int, default=50)
    parser.add_argument("--max-p95-ms", type=float)
    args = parser.parse_args()
    result = asyncio.run(benchmark(
        events=args.events, studio_clients=args.studio_clients, fan_clients=args.fan_clients,
    ))
    print(json.dumps(result, indent=2))
    if args.max_p95_ms is not None and result["p95_ms"] >= args.max_p95_ms:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

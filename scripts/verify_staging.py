"""Verify deployed Event Hubs -> analyst and fan WebSocket delivery."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx
from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient
from websockets.asyncio.client import connect

from scripts.benchmark_stream import percentile


def socket_url(site_url: str, path: str) -> str:
    parsed = urlparse(site_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("site URL must be an HTTP(S) address")
    return f"{'wss' if parsed.scheme == 'https' else 'ws'}://{parsed.netloc}{path}"


async def wait_for_event(socket, kind: str, sequence: int) -> dict:
    while True:
        record = json.loads(await asyncio.wait_for(socket.recv(), timeout=30))
        if record.get("kind") == kind and record.get("sequence") == sequence:
            return record


async def verify(*, broadcast_url: str, fan_url: str, eventhub_name: str, count: int) -> dict:
    if count < 2:
        raise ValueError("count must be at least two to exclude warm-up from latency")
    match_id = f"staging-{uuid.uuid4()}"
    async with httpx.AsyncClient(timeout=10) as http:
        for base in (broadcast_url, fan_url):
            parsed = urlparse(base)
            response = await http.get(f"{parsed.scheme}://{parsed.netloc}/health")
            response.raise_for_status()
            if response.json().get("status") != "running":
                raise RuntimeError(f"listener is not running at {parsed.netloc}")

    studio_ws = socket_url(broadcast_url, f"/ws/studio?match_id={quote(match_id)}")
    fan_ws = socket_url(fan_url, f"/ws/fan/{quote(match_id)}?language=es&style=concise")
    connection = os.environ["EVENT_HUB_SEND_CONNECTION_STRING"]
    studio_ms, fan_ms = [], []
    async with connect(studio_ws, open_timeout=15) as studio, connect(fan_ws, open_timeout=15) as fan:
        producer = EventHubProducerClient.from_connection_string(connection, eventhub_name=eventhub_name)
        async with producer:
            for sequence in range(count):
                event = {
                    "schema_version": "1.0", "event_id": str(uuid.uuid4()),
                    "match_id": match_id, "sequence": sequence,
                    "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "event_type": "pass", "player_id": "home-07", "recipient_id": "home-09",
                    "team_id": "HOME", "start": {"x": 30, "y": 50},
                    "end": {"x": 60, "y": 50}, "outcome": "completed",
                }
                batch = await producer.create_batch(partition_key=match_id)
                batch.add(EventData(json.dumps(event, separators=(",", ":"))))
                started = time.perf_counter()
                await producer.send_batch(batch)
                analyst, localized = await asyncio.gather(
                    wait_for_event(studio, "analysis", sequence),
                    wait_for_event(fan, "match_event", sequence),
                )
                finished = time.perf_counter()
                if analyst["event"]["event_id"] != event["event_id"]:
                    raise AssertionError("studio received the wrong event")
                if localized["event"]["event_id"] != event["event_id"] or localized["language"] != "es":
                    raise AssertionError("fan received the wrong event or language")
                # The receive calls finish together; this is the conservative
                # time until both audiences have the same factual event.
                both_ms = (finished - started) * 1000
                studio_ms.append(both_ms)
                fan_ms.append(both_ms)
    measured = fan_ms[1:]
    return {
        "scope": "Azure Event Hubs send to both deployed factual WebSocket streams; excludes Foundry and speech",
        "match_id": match_id,
        "events_measured": len(measured),
        "both_streams_p50_ms": round(statistics.median(measured), 2),
        "both_streams_p95_ms": round(percentile(measured, .95), 2),
        "both_streams_max_ms": round(max(measured), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broadcast-url", required=True)
    parser.add_argument("--fan-url", required=True)
    parser.add_argument("--eventhub-name", required=True)
    parser.add_argument("--count", type=int, default=11)
    parser.add_argument("--max-p95-ms", type=float, default=1000)
    args = parser.parse_args()
    result = asyncio.run(verify(
        broadcast_url=args.broadcast_url, fan_url=args.fan_url,
        eventhub_name=args.eventhub_name, count=args.count,
    ))
    print(json.dumps(result, indent=2))
    if result["both_streams_p95_ms"] >= args.max_p95_ms:
        raise SystemExit(f"p95 factual delivery exceeded {args.max_p95_ms} ms")


if __name__ == "__main__":
    main()

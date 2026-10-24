"""Measure local analysis latency without Event Hubs transport or Foundry calls."""

import asyncio
import json
import statistics
import time

from src.agents.consumer import CrewStreamProcessor
from src.ingestion.generator import iter_match_events


async def main() -> None:
    processor = CrewStreamProcessor()
    durations_ms = []
    for event in iter_match_events(scenario="build_up", rate=100, count=1000):
        started = time.perf_counter()
        await processor.process_body(json.dumps(event, separators=(",", ":")))
        durations_ms.append((time.perf_counter() - started) * 1000)
    ordered = sorted(durations_ms)
    percentile = lambda fraction: ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]
    print(json.dumps({
        "events": len(ordered),
        "mean_ms": round(statistics.mean(ordered), 3),
        "p50_ms": round(percentile(0.50), 3),
        "p95_ms": round(percentile(0.95), 3),
        "p99_ms": round(percentile(0.99), 3),
        "max_ms": round(ordered[-1], 3),
        "scope": "local JSON validation and deterministic agents; excludes Event Hubs and Foundry",
    }))


if __name__ == "__main__":
    asyncio.run(main())

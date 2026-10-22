"""Generate paced, reproducible synthetic football match events as JSON Lines."""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
import random
import sys
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import MatchEvent, Player, Point, Role, TeamId


ROLES: tuple[Role, ...] = (
    "goalkeeper", "defender", "defender", "defender", "defender",
    "midfielder", "midfielder", "midfielder", "forward", "forward", "forward",
)

# Each preset is a repeating tactical sequence. Coordinates are normalized pitch
# percentages; HOME attacks toward x=100 and AWAY toward x=0.
PRESETS: dict[str, tuple[dict[str, Any], ...]] = {
    "build_up": (
        {"event_type": "position", "player_id": "home-05", "team_id": "HOME", "coordinates": (25, 55)},
        {"event_type": "pass", "player_id": "home-05", "team_id": "HOME", "recipient_id": "home-08", "start": (25, 55), "end": (42, 52), "outcome": "completed"},
        {"event_type": "position", "player_id": "home-08", "team_id": "HOME", "coordinates": (42, 52)},
        {"event_type": "pass", "player_id": "home-08", "team_id": "HOME", "recipient_id": "home-10", "start": (42, 52), "end": (67, 60), "outcome": "completed"},
        {"event_type": "position", "player_id": "home-10", "team_id": "HOME", "coordinates": (67, 60)},
        {"event_type": "shot", "player_id": "home-10", "team_id": "HOME", "location": (84, 55), "outcome": "saved"},
    ),
    "high_press": (
        {"event_type": "position", "player_id": "away-05", "team_id": "AWAY", "coordinates": (62, 52)},
        {"event_type": "pass", "player_id": "away-05", "team_id": "AWAY", "recipient_id": "away-08", "start": (62, 52), "end": (51, 54), "outcome": "intercepted"},
        {"event_type": "position", "player_id": "home-10", "team_id": "HOME", "coordinates": (53, 54)},
        {"event_type": "pass", "player_id": "home-10", "team_id": "HOME", "recipient_id": "home-11", "start": (53, 54), "end": (78, 56), "outcome": "completed"},
        {"event_type": "position", "player_id": "home-11", "team_id": "HOME", "coordinates": (78, 56)},
        {"event_type": "shot", "player_id": "home-11", "team_id": "HOME", "location": (87, 55), "outcome": "blocked"},
    ),
    "counter_attack": (
        {"event_type": "position", "player_id": "away-10", "team_id": "AWAY", "coordinates": (76, 42)},
        {"event_type": "pass", "player_id": "away-10", "team_id": "AWAY", "recipient_id": "away-11", "start": (76, 42), "end": (62, 45), "outcome": "intercepted"},
        {"event_type": "position", "player_id": "home-08", "team_id": "HOME", "coordinates": (62, 45)},
        {"event_type": "pass", "player_id": "home-08", "team_id": "HOME", "recipient_id": "home-11", "start": (62, 45), "end": (82, 49), "outcome": "completed"},
        {"event_type": "position", "player_id": "home-11", "team_id": "HOME", "coordinates": (82, 49)},
        {"event_type": "shot", "player_id": "home-11", "team_id": "HOME", "location": (89, 50), "outcome": "off_target"},
    ),
}


def _roster() -> Iterator[Player]:
    for team_id, prefix in (("HOME", "home"), ("AWAY", "away")):
        for shirt_number, role in enumerate(ROLES, start=1):
            yield {
                "player_id": f"{prefix}-{shirt_number:02d}",
                "team_id": team_id,
                "display_name": f"{team_id.title()} Player {shirt_number}",
                "role": role,
                "shirt_number": shirt_number,
            }


def _point(raw: tuple[int, int], rng: random.Random) -> Point:
    return {
        "x": round(min(100.0, max(0.0, raw[0] + rng.uniform(-2.0, 2.0))), 2),
        "y": round(min(100.0, max(0.0, raw[1] + rng.uniform(-2.0, 2.0))), 2),
    }


def _envelope(match_id: str, sequence: int, started_at: datetime, rate: float, event_type: str) -> dict[str, Any]:
    occurred_at = started_at + timedelta(seconds=sequence / rate)
    return {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{match_id}:{sequence}")),
        "match_id": match_id,
        "sequence": sequence,
        "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
        "event_type": event_type,
    }


def iter_match_events(
    *,
    scenario: str,
    rate: float,
    count: int | None,
    seed: int = 1,
    match_id: str = "synthetic-match",
    started_at: datetime | None = None,
) -> Iterator[MatchEvent]:
    """Yield 22 player records, then ``count`` play events (or forever if None)."""
    if scenario not in PRESETS:
        raise ValueError(f"Unknown scenario: {scenario}")
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("rate must be finite and positive")
    if count is not None and count < 0:
        raise ValueError("count must be non-negative")
    if not match_id:
        raise ValueError("match_id must not be empty")
    started_at = started_at or datetime.now(timezone.utc)
    if started_at.tzinfo is None or started_at.utcoffset() != timedelta(0):
        raise ValueError("started_at must be UTC timezone-aware")

    rng = random.Random(seed)
    players = tuple(_roster())
    for sequence, player in enumerate(players):
        yield {**_envelope(match_id, sequence, started_at, rate, "player_metadata"), "player": player}  # type: ignore[return-value]

    indices = itertools.count() if count is None else range(count)
    for index in indices:
        spec = PRESETS[scenario][index % len(PRESETS[scenario])]
        event_type = spec["event_type"]
        event = _envelope(match_id, len(players) + index, started_at, rate, event_type)
        event.update({key: value for key, value in spec.items() if key not in {"event_type", "coordinates", "start", "end", "location"}})
        for key in ("coordinates", "start", "end", "location"):
            if key in spec:
                event[key] = _point(spec[key], rng)
        yield event  # type: ignore[misc]


async def stream_match_events(**kwargs: Any) -> AsyncIterator[MatchEvent]:
    """Pace events at the requested event rate without blocking the event loop."""
    rate = kwargs["rate"]
    start = time.monotonic()
    for index, event in enumerate(iter_match_events(**kwargs)):
        await asyncio.sleep(max(0.0, start + index / rate - time.monotonic()))
        yield event


def build_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--scenario", choices=sorted(PRESETS), default="build_up")
    parser.add_argument("--rate", type=float, default=2.0, help="events per second")
    parser.add_argument("--count", type=int, default=100, help="play events after player metadata; 0 streams indefinitely")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--match-id", default="synthetic-match")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser("Print a paced synthetic match stream as JSON Lines").parse_args(argv)


async def _run(args: argparse.Namespace) -> None:
    async for event in stream_match_events(
        scenario=args.scenario,
        rate=args.rate,
        count=None if args.count == 0 else args.count,
        seed=args.seed,
        match_id=args.match_id,
    ):
        print(json.dumps(event, separators=(",", ":")), flush=True)


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(_run(args))
    except (ValueError, KeyboardInterrupt) as exc:
        if isinstance(exc, ValueError):
            print(exc, file=sys.stderr)
            raise SystemExit(2) from exc


if __name__ == "__main__":
    main()

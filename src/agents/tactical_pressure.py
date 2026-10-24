"""Local opponent density around the ball carrier."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from src.ingestion.models import Point

from .pass_difficulty import metres


RADIUS_M = 10.0


@dataclass(frozen=True)
class TacticalPressure:
    defenders_within_10m: int
    defenders_per_100m2: float
    weighted_pressure_index: float
    defenders_observed: int


def calculate_tactical_pressure(
    carrier: Point, defenders: Mapping[str, Point],
) -> TacticalPressure | None:
    """Count nearby defenders and weight their distance from the carrier.

    Density uses a fixed 10 m circle, including at pitch boundaries. The
    pressure index is descriptive, not a calibrated possession-loss probability.
    """
    if not defenders:
        return None
    cx, cy = metres(carrier)
    distances = [math.hypot(cx - x, cy - y) for x, y in map(metres, defenders.values())]
    local = [distance for distance in distances if distance <= RADIUS_M]
    density = len(local) * 100.0 / (math.pi * RADIUS_M * RADIUS_M)
    weighted = sum(1.0 - distance / RADIUS_M for distance in local)
    index = 1.0 - math.exp(-weighted)
    return TacticalPressure(len(local), round(density, 4), round(index, 4), len(defenders))

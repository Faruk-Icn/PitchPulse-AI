"""Geometry-only pass difficulty index; it is not a success probability."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from src.ingestion.models import Point, TeamId


def metres(point: Point) -> tuple[float, float]:
    """Map percentage pitch coordinates onto a 105 by 68 metre pitch."""
    return point["x"] * 1.05, point["y"] * 0.68


@dataclass(frozen=True)
class PassDifficulty:
    index: float
    nearest_lane_defender_m: float
    attack_angle_degrees: float
    defenders_observed: int


def calculate_pass_difficulty(
    start: Point, end: Point, team_id: TeamId, defenders: Mapping[str, Point],
) -> PassDifficulty | None:
    """Score pass geometry from lane proximity and angle toward the goal.

    The index is a transparent heuristic in [0, 1]. It has no fitted outcome
    calibration. A missing defender sample or zero-length pass yields no score.
    """
    if not defenders:
        return None
    sx, sy = metres(start)
    ex, ey = metres(end)
    dx, dy = ex - sx, ey - sy
    length2 = dx * dx + dy * dy
    if length2 < 1e-12:
        return None
    length = math.sqrt(length2)
    forward = dx / length if team_id == "HOME" else -dx / length
    angle = math.degrees(math.acos(max(-1.0, min(1.0, forward))))

    distances = []
    for point in defenders.values():
        px, py = metres(point)
        projection = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / length2))
        distances.append(math.hypot(px - (sx + projection * dx), py - (sy + projection * dy)))
    nearest = min(distances)
    lane_risk = math.exp(-nearest / 6.0)
    forward_risk = max(0.0, forward)
    index = round(0.8 * lane_risk + 0.2 * forward_risk, 4)
    return PassDifficulty(index, round(nearest, 3), round(angle, 2), len(defenders))

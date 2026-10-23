"""Shot-location features shared by training and live inference."""

import math

from src.ingestion.models import Point, TeamId


def features_from_goal_offset(dx_m: float, dy_m: float) -> tuple[float, float, float]:
    dx_m = max(0.1, dx_m)
    distance = math.hypot(dx_m, dy_m)
    angle = abs(math.atan2(3.66 - dy_m, dx_m) - math.atan2(-3.66 - dy_m, dx_m))
    return 1.0, distance / 20.0, angle


def statsbomb_features(x: float, y: float) -> tuple[float, float, float]:
    return features_from_goal_offset((120.0 - x) * 105.0 / 120.0, abs(y - 40.0) * 68.0 / 80.0)


def live_features(location: Point, team_id: TeamId) -> tuple[float, float, float]:
    attacking_x = location["x"] if team_id == "HOME" else 100.0 - location["x"]
    return features_from_goal_offset(
        (100.0 - attacking_x) * 105.0 / 100.0,
        abs(location["y"] - 50.0) * 68.0 / 100.0,
    )

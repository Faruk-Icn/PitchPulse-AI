"""Incremental passing accuracy and shot-location expected-goals estimates."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from src.ingestion.models import MatchEvent

from .base import BaseMatchAgent
from .xg_geometry import live_features


MODEL_PATH = Path(__file__).with_name("xg_model.json")


@dataclass(frozen=True)
class StatsSnapshot:
    match_id: str
    sequence: int
    pass_attempts: dict[str, int]
    completed_passes: dict[str, int]
    passing_accuracy: dict[str, float | None]
    shots: dict[str, int]
    cumulative_xg: dict[str, float]
    latest_shot_xg: float | None
    xg_model: str


class StatsAnalystAgent(BaseMatchAgent):
    def __init__(self, match_id: str, settings=None) -> None:
        super().__init__(match_id, settings)
        model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
        if model["features"] != ["intercept", "distance_m/20", "goal_angle_radians"]:
            raise ValueError("unexpected xG feature contract")
        self.model_name = model["model"]
        self.coefficients = tuple(model["coefficients"])
        if len(self.coefficients) != 3 or not all(math.isfinite(value) for value in self.coefficients):
            raise ValueError("invalid xG coefficients")
        self.pass_attempts = {"HOME": 0, "AWAY": 0}
        self.completed_passes = {"HOME": 0, "AWAY": 0}
        self.shots = {"HOME": 0, "AWAY": 0}
        self.xg = {"HOME": 0.0, "AWAY": 0.0}

    def process(self, event: MatchEvent) -> StatsSnapshot:
        self.inspect_event(event)
        latest_shot_xg = None
        if event["event_type"] == "pass":
            team = event["team_id"]
            self.pass_attempts[team] += 1
            if event["outcome"] == "completed":
                self.completed_passes[team] += 1
        elif event["event_type"] == "shot":
            team = event["team_id"]
            features = live_features(event["location"], team)
            score = sum(coefficient * feature for coefficient, feature in zip(self.coefficients, features))
            latest_shot_xg = 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, score))))
            self.shots[team] += 1
            self.xg[team] += latest_shot_xg

        snapshot = StatsSnapshot(
            match_id=self.match_id,
            sequence=event["sequence"],
            pass_attempts=self.pass_attempts.copy(),
            completed_passes=self.completed_passes.copy(),
            passing_accuracy={
                team: round(self.completed_passes[team] / self.pass_attempts[team], 4)
                if self.pass_attempts[team] else None
                for team in ("HOME", "AWAY")
            },
            shots=self.shots.copy(),
            cumulative_xg={team: round(self.xg[team], 4) for team in ("HOME", "AWAY")},
            latest_shot_xg=round(latest_shot_xg, 4) if latest_shot_xg is not None else None,
            xg_model=self.model_name,
        )
        self.complete_event(event)
        return snapshot

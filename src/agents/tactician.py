"""Formation and spatial-control estimates from fresh player positions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.ingestion.models import MatchEvent, Player, Point, TeamId

from .base import BaseMatchAgent


@dataclass(frozen=True)
class TacticalSnapshot:
    match_id: str
    sequence: int
    observed_positions: dict[str, int]
    formations: dict[str, str | None]
    pitch_control_proxy: dict[str, float] | None


class TacticianAgent(BaseMatchAgent):
    """Use nearest-player territory as a transparent pitch-control proxy.

    Formation needs all ten outfielders on one team; territorial share needs
    eleven fresh positions on both teams. Sparse feeds return None.
    """

    def __init__(self, match_id: str, settings=None) -> None:
        super().__init__(match_id, settings)
        self.players: dict[str, Player] = {}
        self.positions: dict[str, tuple[Point, datetime, TeamId]] = {}

    def process(self, event: MatchEvent) -> TacticalSnapshot:
        now = self.inspect_event(event)
        if event["event_type"] == "player_metadata":
            player = event["player"]
            position = self.positions.get(player["player_id"])
            if position is not None and position[2] != player["team_id"]:
                raise ValueError("player metadata team does not match position")
            self.players[player["player_id"]] = player
        elif event["event_type"] == "position":
            player = self.players.get(event["player_id"])
            if player is not None and player["team_id"] != event["team_id"]:
                raise ValueError("position team does not match player metadata")
            self.positions[event["player_id"]] = (event["coordinates"], now, event["team_id"])

        fresh: dict[TeamId, dict[str, Point]] = {"HOME": {}, "AWAY": {}}
        for player_id, (point, observed_at, team_id) in self.positions.items():
            age = (now - observed_at).total_seconds()
            if 0 <= age <= self.settings.position_max_age_seconds:
                fresh[team_id][player_id] = point

        result = TacticalSnapshot(
            match_id=self.match_id,
            sequence=event["sequence"],
            observed_positions={team: len(points) for team, points in fresh.items()},
            formations={team: self._formation(team, fresh[team]) for team in ("HOME", "AWAY")},
            pitch_control_proxy=self._pitch_control(fresh),
        )
        self.complete_event(event)
        return result

    def _formation(self, team_id: TeamId, positions: dict[str, Point]) -> str | None:
        outfielders = [
            player for player in self.players.values()
            if player["team_id"] == team_id and player["role"] != "goalkeeper"
        ]
        if len(outfielders) != 10 or any(player["player_id"] not in positions for player in outfielders):
            return None
        coordinates = sorted(
            positions[player["player_id"]]["x"] if team_id == "HOME"
            else 100 - positions[player["player_id"]]["x"]
            for player in outfielders
        )

        def variance(values: list[float]) -> float:
            center = sum(values) / len(values)
            return sum((value - center) ** 2 for value in values)

        candidates = []
        for first in range(2, 7):
            for second in range(first + 2, 9):
                lines = [coordinates[:first], coordinates[first:second], coordinates[second:]]
                if len(lines[2]) < 2:
                    continue
                centers = [sum(line) / len(line) for line in lines]
                if min(centers[1] - centers[0], centers[2] - centers[1]) < 8:
                    continue
                candidates.append((sum(variance(line) for line in lines), (first, second - first, 10 - second)))
        if not candidates:
            return None
        _, counts = min(candidates)
        return "-".join(map(str, counts))

    def _pitch_control(self, positions: dict[TeamId, dict[str, Point]]) -> dict[str, float] | None:
        if any(len(positions[team]) != 11 for team in ("HOME", "AWAY")):
            return None
        home_points = tuple(positions["HOME"].values())
        away_points = tuple(positions["AWAY"].values())
        home_share = 0.0
        total = self.settings.pitch_grid_columns * self.settings.pitch_grid_rows
        for column in range(self.settings.pitch_grid_columns):
            x = column * 100 / (self.settings.pitch_grid_columns - 1)
            for row in range(self.settings.pitch_grid_rows):
                y = row * 100 / (self.settings.pitch_grid_rows - 1)
                home_distance = min((x - point["x"]) ** 2 + (y - point["y"]) ** 2 for point in home_points)
                away_distance = min((x - point["x"]) ** 2 + (y - point["y"]) ** 2 for point in away_points)
                home_share += 1 if home_distance < away_distance else 0.5 if home_distance == away_distance else 0
        home_share = round(home_share / total, 4)
        return {"HOME": home_share, "AWAY": round(1 - home_share, 4)}

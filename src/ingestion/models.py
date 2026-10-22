"""Typed wire contract for synthetic match events.

Pitch coordinates are percentages from 0 to 100, with HOME attacking toward x=100.
"""

from typing import Literal, TypeAlias, TypedDict


TeamId: TypeAlias = Literal["HOME", "AWAY"]
Role: TypeAlias = Literal["goalkeeper", "defender", "midfielder", "forward"]
PassOutcome: TypeAlias = Literal["completed", "incomplete", "intercepted"]
ShotOutcome: TypeAlias = Literal["goal", "saved", "off_target", "blocked"]


class Point(TypedDict):
    x: float
    y: float


class Player(TypedDict):
    player_id: str
    team_id: TeamId
    display_name: str
    role: Role
    shirt_number: int


class EventEnvelope(TypedDict):
    schema_version: Literal["1.0"]
    event_id: str
    match_id: str
    sequence: int
    occurred_at: str


class PlayerMetadataEvent(EventEnvelope):
    event_type: Literal["player_metadata"]
    player: Player


class PositionEvent(EventEnvelope):
    event_type: Literal["position"]
    player_id: str
    team_id: TeamId
    coordinates: Point


class PassEvent(EventEnvelope):
    event_type: Literal["pass"]
    player_id: str
    team_id: TeamId
    recipient_id: str
    start: Point
    end: Point
    outcome: PassOutcome


class ShotEvent(EventEnvelope):
    event_type: Literal["shot"]
    player_id: str
    team_id: TeamId
    location: Point
    outcome: ShotOutcome


MatchEvent: TypeAlias = PlayerMetadataEvent | PositionEvent | PassEvent | ShotEvent

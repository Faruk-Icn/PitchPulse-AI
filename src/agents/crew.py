"""Ordered coordination of the three agents for one match."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import datetime

from src.ingestion.models import MatchEvent

from .config import AgentSettings
from .pass_difficulty import PassDifficulty, calculate_pass_difficulty
from .stats_analyst import StatsAnalystAgent, StatsSnapshot
from .storyteller import BroadcastNarrative, StorytellerAgent
from .tactician import TacticalSnapshot, TacticianAgent
from .tactical_pressure import TacticalPressure, calculate_tactical_pressure


@dataclass(frozen=True)
class CrewResult:
    match_id: str
    sequence: int
    tactical: TacticalSnapshot
    stats: StatsSnapshot
    narrative: BroadcastNarrative | None
    pass_difficulty: PassDifficulty | None = None
    tactical_pressure: TacticalPressure | None = None
    narrative_error: str | None = None


class MatchAgentCrew:
    """Share same-event snapshots while preserving sequence order per match.

    The caller must await each result before submitting the next event for this
    match. Other matches may be processed concurrently by separate crews.
    """

    def __init__(
        self, match_id: str, *, settings: AgentSettings | None = None,
        storyteller: StorytellerAgent | None = None,
    ) -> None:
        self.match_id = match_id
        self.settings = settings or AgentSettings.from_env()
        self.tactician = TacticianAgent(match_id, self.settings)
        self.stats_analyst = StatsAnalystAgent(match_id, self.settings)
        if storyteller is not None and storyteller.match_id != match_id:
            raise ValueError("storyteller belongs to a different match")
        self.storyteller = storyteller
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger("pitchpulse.agents.crew")

    async def process(self, event: MatchEvent) -> CrewResult:
        if event["match_id"] != self.match_id:
            raise ValueError("event belongs to a different match")
        async with self._lock:
            tactical = self.tactician.process(event)
            stats = self.stats_analyst.process(event)
            narrative = None
            pass_difficulty = None
            pressure = None
            narrative_error = None
            if event["event_type"] == "pass":
                occurred_at = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
                opposing_team = "AWAY" if event["team_id"] == "HOME" else "HOME"
                defenders = self.tactician.fresh_positions(occurred_at, opposing_team)
                pass_difficulty = calculate_pass_difficulty(
                    event["start"], event["end"], event["team_id"], defenders,
                )
                pressure = calculate_tactical_pressure(event["start"], defenders)
            if self.storyteller is not None and event["event_type"] in ("pass", "shot"):
                try:
                    narrative = await self.storyteller.process(
                        event, tactical=tactical, stats=stats,
                        calculations={
                            "pass_difficulty": asdict(pass_difficulty) if pass_difficulty else None,
                            "tactical_pressure": asdict(pressure) if pressure else None,
                        },
                    )
                except Exception as exc:
                    narrative_error = type(exc).__name__
                    self.logger.exception("Storyteller failed for match=%s sequence=%s", self.match_id, event["sequence"])
            return CrewResult(
                self.match_id, event["sequence"], tactical, stats, narrative,
                pass_difficulty, pressure, narrative_error,
            )

"""Ordered coordination of the three agents for one match."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from src.ingestion.models import MatchEvent

from .config import AgentSettings
from .stats_analyst import StatsAnalystAgent, StatsSnapshot
from .storyteller import BroadcastNarrative, StorytellerAgent
from .tactician import TacticalSnapshot, TacticianAgent


@dataclass(frozen=True)
class CrewResult:
    match_id: str
    sequence: int
    tactical: TacticalSnapshot
    stats: StatsSnapshot
    narrative: BroadcastNarrative | None


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

    async def process(self, event: MatchEvent) -> CrewResult:
        if event["match_id"] != self.match_id:
            raise ValueError("event belongs to a different match")
        async with self._lock:
            tactical = self.tactician.process(event)
            stats = self.stats_analyst.process(event)
            narrative = None
            if self.storyteller is not None and event["event_type"] in ("pass", "shot"):
                narrative = await self.storyteller.process(event, tactical=tactical, stats=stats)
            return CrewResult(self.match_id, event["sequence"], tactical, stats, narrative)

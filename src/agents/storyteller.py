"""Generate concise broadcast commentary through Microsoft Agent Framework."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Protocol

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential

from src.ingestion.models import MatchEvent

from .base import BaseMatchAgent
from .config import AgentSettings
from .tactician import TacticalSnapshot

if TYPE_CHECKING:
    from .stats_analyst import StatsSnapshot


INSTRUCTIONS = (
    "You are PitchPulse's live football broadcast storyteller. Write one or two "
    "short, factual sentences about the supplied event. Use only the supplied "
    "event and analytical context. Never invent a score, player identity, match "
    "clock, outcome, formation, or statistic. Label location-based xG and "
    "nearest-player pitch control as estimates. If context is unavailable, omit it."
)


class NarrativeRunner(Protocol):
    async def run(self, message: str): ...


@dataclass(frozen=True)
class BroadcastNarrative:
    match_id: str
    sequence: int
    text: str


class StorytellerAgent(BaseMatchAgent):
    def __init__(self, match_id: str, runner: NarrativeRunner, settings: AgentSettings | None = None) -> None:
        super().__init__(match_id, settings)
        self.runner = runner

    @classmethod
    def from_foundry(cls, match_id: str, settings: AgentSettings | None = None) -> "StorytellerAgent":
        settings = settings or AgentSettings.from_env()
        if not settings.foundry_project_endpoint or not settings.foundry_model:
            raise ValueError("FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL must be configured")
        client = FoundryChatClient(
            project_endpoint=settings.foundry_project_endpoint,
            model=settings.foundry_model,
            credential=DefaultAzureCredential(),
        )
        runner = Agent(client=client, name="Storyteller", instructions=INSTRUCTIONS)
        return cls(match_id, runner, settings)

    async def process(
        self,
        event: MatchEvent,
        *,
        tactical: TacticalSnapshot | None = None,
        stats: StatsSnapshot | None = None,
    ) -> BroadcastNarrative:
        self.inspect_event(event)
        if tactical is not None and (tactical.match_id != self.match_id or tactical.sequence != event["sequence"]):
            raise ValueError("tactical context does not match event")
        if stats is not None and (stats.match_id != self.match_id or stats.sequence != event["sequence"]):
            raise ValueError("stats context does not match event")
        payload = {
            "event": event,
            "tactical": asdict(tactical) if tactical is not None else None,
            "stats": asdict(stats) if stats is not None else None,
        }
        response = await self.runner.run(json.dumps(payload, separators=(",", ":")))
        text = response.text.strip()
        if not text:
            raise ValueError("Storyteller returned empty commentary")
        self.complete_event(event)
        return BroadcastNarrative(self.match_id, event["sequence"], text)

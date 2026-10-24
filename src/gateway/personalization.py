"""Fact-bound fan text through Microsoft Agent Framework and Foundry."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Protocol

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential

from src.agents.config import AgentSettings
from src.agents.crew import CrewResult
from src.ingestion.models import MatchEvent

from .localization import CATALOG


LANGUAGES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "ar": "Arabic"}
if set(LANGUAGES) != set(CATALOG):
    raise ValueError("Foundry language instructions do not match the fan catalog")
STYLES = {"concise": "one short factual sentence", "tactical": "two short factual sentences with available tactical context", "casual": "one short accessible sentence"}


@dataclass(frozen=True)
class FanProfile:
    language: str = "en"
    style: str = "concise"

    def __post_init__(self) -> None:
        if self.language not in LANGUAGES or self.style not in STYLES:
            raise ValueError("unsupported fan language or style")


class ChatClient(Protocol):
    async def get_response(self, messages, **kwargs): ...


class FanPersonalizer:
    def __init__(self, client: ChatClient) -> None:
        self.client = client

    @classmethod
    def from_settings(cls, settings: AgentSettings) -> "FanPersonalizer":
        if not settings.foundry_project_endpoint or not settings.foundry_model:
            raise ValueError("FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL are required")
        return cls(FoundryChatClient(
            project_endpoint=settings.foundry_project_endpoint,
            model=settings.foundry_model,
            credential=DefaultAzureCredential(),
        ))

    async def generate(self, event: MatchEvent, result: CrewResult, profile: FanProfile) -> str:
        """Create a fresh agent per call while reusing the Foundry chat client."""
        instructions = (
            f"Write in {LANGUAGES[profile.language]} as {STYLES[profile.style]}. "
            "Describe only the supplied football event and computed context. "
            "Do not invent a score, clock, player name, result or statistic. "
            "Call pass difficulty and tactical pressure descriptive estimates, not probabilities. "
            "Omit unavailable context. Return only the fan-facing text."
        )
        agent = Agent(client=self.client, name="FanCommentator", instructions=instructions)
        message = json.dumps({
            "event": event,
            "stats": asdict(result.stats),
            "pass_difficulty": asdict(result.pass_difficulty) if result.pass_difficulty else None,
            "tactical_pressure": asdict(result.tactical_pressure) if result.tactical_pressure else None,
        }, separators=(",", ":"))
        response = await agent.run(message)
        text = response.text.strip()
        if not text:
            raise ValueError("Foundry returned empty fan text")
        return text

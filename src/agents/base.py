"""Shared event validation, ordering, and logging for one match per agent."""

from __future__ import annotations

import logging
from datetime import datetime

from src.ingestion.models import MatchEvent
from src.ingestion.validation import validate_event

from .config import AgentSettings


class BaseMatchAgent:
    def __init__(self, match_id: str, settings: AgentSettings | None = None) -> None:
        if not match_id:
            raise ValueError("match_id must not be empty")
        self.match_id = match_id
        self.settings = settings or AgentSettings.from_env()
        self.last_sequence = -1
        self.logger = logging.getLogger(f"pitchpulse.agents.{type(self).__name__}")

    def inspect_event(self, event: MatchEvent) -> datetime:
        """Validate one wire event and enforce in-order processing."""
        validate_event(event)
        if event["match_id"] != self.match_id:
            raise ValueError("event belongs to a different match")
        sequence = event["sequence"]
        if sequence <= self.last_sequence:
            raise ValueError("event sequence is not increasing")
        if self.last_sequence >= 0 and sequence != self.last_sequence + 1:
            self.logger.warning("sequence gap: previous=%s current=%s", self.last_sequence, sequence)
        timestamp = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        return timestamp

    def complete_event(self, event: MatchEvent) -> None:
        """Commit the sequence only after processing has succeeded."""
        self.last_sequence = event["sequence"]
        self.logger.debug("accepted event type=%s sequence=%s", event["event_type"], event["sequence"])

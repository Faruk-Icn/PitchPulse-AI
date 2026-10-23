"""Agent settings loaded from process configuration."""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSettings:
    position_max_age_seconds: float = 30.0
    pitch_grid_columns: int = 21
    pitch_grid_rows: int = 13
    foundry_project_endpoint: str | None = None
    foundry_model: str | None = None
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not math.isfinite(self.position_max_age_seconds) or self.position_max_age_seconds <= 0:
            raise ValueError("position_max_age_seconds must be finite and positive")
        if self.pitch_grid_columns < 3 or self.pitch_grid_rows < 3:
            raise ValueError("pitch grid dimensions must be at least 3")
        if self.log_level.upper() not in logging.getLevelNamesMapping():
            raise ValueError("unknown log level")

    @classmethod
    def from_env(cls) -> "AgentSettings":
        return cls(
            position_max_age_seconds=float(os.getenv("AGENT_POSITION_MAX_AGE_SECONDS", "30")),
            pitch_grid_columns=int(os.getenv("AGENT_PITCH_GRID_COLUMNS", "21")),
            pitch_grid_rows=int(os.getenv("AGENT_PITCH_GRID_ROWS", "13")),
            foundry_project_endpoint=os.getenv("FOUNDRY_PROJECT_ENDPOINT") or None,
            foundry_model=os.getenv("FOUNDRY_MODEL") or None,
            log_level=os.getenv("AGENT_LOG_LEVEL", "INFO").upper(),
        )


def configure_logging(settings: AgentSettings) -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

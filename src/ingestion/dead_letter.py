"""Append rejected match events to a local JSON Lines dead-letter file."""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JsonlDeadLetterSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.name:
            raise ValueError("dead-letter path must name a file")

    async def write(self, event: Any, reason: str, attempts: int) -> None:
        record = {
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "attempts": attempts,
            "event": event,
        }
        await asyncio.to_thread(self._append, record)

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

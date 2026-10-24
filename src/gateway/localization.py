"""Shared fan language catalog and deterministic event summaries."""

from __future__ import annotations

import json
from pathlib import Path

from src.ingestion.models import MatchEvent


CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "fan-locales.json"
CATALOG: dict[str, dict] = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _check_catalog() -> None:
    if set(CATALOG) != {"en", "es", "fr", "de", "ar"}:
        raise ValueError("fan locale catalog must cover all supported languages")
    reference = CATALOG["en"]
    for language, entry in CATALOG.items():
        if set(entry["labels"]) != set(reference["labels"]):
            raise ValueError(f"missing interface label in {language}")
        if set(entry["events"]) != set(reference["events"]):
            raise ValueError(f"missing event label in {language}")
        if set(entry["styles"]) != {"concise", "tactical", "casual"}:
            raise ValueError(f"missing style label in {language}")
        if entry["dir"] not in ("ltr", "rtl"):
            raise ValueError(f"invalid text direction in {language}")


_check_catalog()


def localize_event(event: MatchEvent, language: str) -> str:
    if language not in CATALOG:
        raise ValueError("unsupported fan language")
    labels = CATALOG[language]
    kind = event["event_type"]
    if kind in ("pass", "shot"):
        phrase = labels["events"][f"{kind}_{event['outcome']}"]
    elif kind == "position":
        phrase = labels["events"]["position_update"]
    else:
        phrase = labels["events"]["player_registered"]
    team = event.get("team_id") or event["player"]["team_id"]
    return f"{labels['labels'][team.lower()]}: {phrase}"

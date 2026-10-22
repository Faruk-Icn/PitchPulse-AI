"""Validate the event wire format before publishing it."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "match-event.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def validate_event(event: object) -> None:
    """Raise jsonschema.ValidationError for a malformed match event."""
    VALIDATOR.validate(event)

"""Read a recorded attempt history, tolerating only an interrupted final record."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from live_tracker.recorder import LOG_NAME, SCHEMA, SCHEMA_VERSION


class RecordingError(RuntimeError):
    """The saved history is corrupt, has a gap, or uses an unsupported schema."""


def read_attempt_events(directory: Path) -> list[dict[str, Any]]:
    log = Path(directory) / LOG_NAME
    if not log.is_file():
        return []
    # Only a final line without its newline can be an interrupted append; it is not a record.
    complete_lines = log.read_bytes().split(b"\n")[:-1]
    events: list[dict[str, Any]] = []
    for sequence, line in enumerate(complete_lines, 1):
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise RecordingError(f"event {sequence} is not valid JSON: {exc}") from exc
        if event.get("schema") != SCHEMA or event.get("schema_version") != SCHEMA_VERSION:
            raise RecordingError(f"event {sequence} has an unsupported schema")
        if event.get("sequence") != sequence:
            raise RecordingError(f"event {sequence} has sequence {event.get('sequence')}")
        events.append(event)
    return events

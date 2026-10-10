"""Read-only adapter for the first live pair's legacy trace (trace.jsonl, no attempt event log).

The adapter maps each recorded trace record onto the viewer's event shape. It never fabricates a
start, phase, node, state or attempt boundary the old trace did not record, and it labels every
field that is unavailable, derived (computed now from bytes) or inline (the trace carried it).
Nothing is written: the original files stay byte-identical.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


LEGACY_FORMAT = "legacy-trace"
TRACE_NAME = "trace.jsonl"
ENVELOPE_KEYS = {"event_id", "timestamp", "type"}
TYPE_NAMES = {"model": "model.outcome", "tool": "tool.outcome"}

UNAVAILABLE = [
    "attempt_started", "attempt_finished", "operation starts", "operation_id",
    "phase.enter", "node transitions", "state",
    "elapsed_seconds", "intermediate captures", "recording status",
]
DERIVED = [
    "sequence (the legacy event_id)",
    "output.txt sha256 (computed from the current bytes; the trace did not record a digest)",
]
EVENT_UNAVAILABLE = ["operation starts", "operation_id", "elapsed_seconds"]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tool_output(directory: Path, record: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Link the preserved full output by its recorded relative path, with a computed digest."""
    relative = record.get("result", {}).get("output_artifact")
    if not isinstance(relative, str):
        return [], []
    path = directory / relative
    if not path.is_file():
        return [{"role": "output.txt", "path": relative, "bytes": None, "sha256": None,
                 "integrity": "missing"}], ["output_artifact link (added after the run)"]
    artifact = {"role": "output.txt", "path": relative, "bytes": path.stat().st_size,
                "sha256": _digest(path), "integrity": "ok"}
    return [artifact], ["output_artifact link (added after the run)",
                        "output.txt sha256 computed from current bytes"]


def _event(sequence: int, record: dict[str, Any], directory: Path) -> dict[str, Any]:
    kind = record["type"]
    type_name = TYPE_NAMES.get(kind, kind)
    unavailable = list(EVENT_UNAVAILABLE)
    derived: list[str] = []
    inline: list[str] = []
    artifacts: list[dict[str, Any]] = []
    if kind == "model":
        data = {key: value for key, value in record.items() if key not in ENVELOPE_KEYS}
        inline.append("response inline in legacy trace")
    elif kind == "tool":
        unavailable.append("intermediate capture")
        data = {key: value for key, value in record.items() if key not in ENVELOPE_KEYS | {"result"}}
        result = dict(record.get("result", {}))
        result.pop("output", None)
        result.pop("output_artifact", None)
        data["result"] = result
        artifacts, derived = _tool_output(directory, record)
    else:
        data = {key: value for key, value in record.items() if key not in ENVELOPE_KEYS}
        if kind == "initial_context":
            inline.append("messages inline in legacy trace")
    return {
        "format": LEGACY_FORMAT,
        "legacy": True,
        "sequence": sequence,
        "type": type_name,
        "timestamp": record.get("timestamp"),
        "elapsed_seconds": None,
        "data": data,
        "artifacts": artifacts,
        "labels": {"unavailable": unavailable, "derived": derived, "inline": inline},
    }


def read_legacy_events(directory: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (events, problems) for a legacy trace. A bad or out-of-order record ends the prefix."""
    directory = Path(directory)
    events: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    text = (directory / TRACE_NAME).read_text(encoding="utf-8")
    for sequence, line in enumerate(text.splitlines(), 1):
        try:
            record = json.loads(line)
        except ValueError as exc:
            problems.append({"kind": "malformed", "sequence": sequence,
                             "detail": f"trace record is not valid JSON: {exc}"})
            break
        if not isinstance(record, dict) or record.get("event_id") != sequence or "type" not in record:
            problems.append({"kind": "sequence_gap", "sequence": sequence,
                             "detail": f"expected event {sequence} in the legacy trace"})
            break
        events.append(_event(sequence, record, directory))
    return events, problems


LABELS = {"unavailable": UNAVAILABLE, "derived": DERIVED,
          "note": "Legacy first-live-pair trace: recorded fields only; nothing was added or re-timed."}

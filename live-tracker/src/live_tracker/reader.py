"""Read a recorded attempt history without changing a byte of it.

The reader returns the verified prefix, every problem it found, unresolved
operations and the recording state. It never skips a damaged record silently,
never appends, and never resumes or executes anything.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from live_tracker.recorder import ARTIFACT_DIRECTORY, FAILURE_MARKER, LOG_NAME, SCHEMA, SCHEMA_VERSION


ARTIFACT_PATH = re.compile(rf"^{ARTIFACT_DIRECTORY}/[0-9a-f]{{64}}$")
# ponytail: artifacts are content-addressed, so a verified digest is cached per file stat to avoid
# re-hashing on every SSE poll. Upgrade to a persistent index if artifacts ever become mutable.
_VERIFIED: dict[str, tuple[int, int]] = {}


@dataclass(frozen=True)
class AttemptHistory:
    state: str  # empty | open | interrupted | complete | failed | corrupt
    events: list[dict[str, Any]]
    problems: list[dict[str, Any]]
    torn_tail_bytes: int
    unresolved_operations: list[str]
    failure: dict[str, Any] | None

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "verified_events": len(self.events),
            "torn_tail_bytes": self.torn_tail_bytes,
            "unresolved_operations": self.unresolved_operations,
            "problems": self.problems,
            "failure": self.failure,
        }


def _problem(kind: str, sequence: int | None, detail: str) -> dict[str, Any]:
    return {"kind": kind, "sequence": sequence, "detail": detail}


def _record_problem(event: Any, sequence: int, attempt_id: str | None,
                    starts: dict[str, str], outcomes: set[str]) -> dict[str, Any] | None:
    """Structural checks that end the verified prefix at this record."""
    if not isinstance(event, dict):
        return _problem("malformed", sequence, "record is not a JSON object")
    if event.get("schema") != SCHEMA or event.get("schema_version") != SCHEMA_VERSION:
        return _problem("unsupported_schema", sequence,
                        f"schema {event.get('schema')!r} version {event.get('schema_version')!r} is not supported")
    if event.get("sequence") != sequence:
        found = event.get("sequence")
        kind = "sequence_gap" if isinstance(found, int) and found > sequence else "sequence_conflict"
        return _problem(kind, sequence, f"expected sequence {sequence}, found {found!r}")
    if not isinstance(event.get("attempt_id"), str):
        return _problem("malformed", sequence, "record has no attempt id")
    if attempt_id is not None and event["attempt_id"] != attempt_id:
        return _problem("identity_conflict", sequence, "attempt id differs from the first record")
    if not isinstance(event.get("type"), str) or not isinstance(event.get("artifacts", []), list):
        return _problem("malformed", sequence, "record has no event type or artifact list")
    # Only a repeated operation identity is a conflict. Records without one, and outcomes whose start
    # is absent, are shown as recorded: they cannot be paired, so they are never reported unresolved.
    operation = event.get("operation_id")
    if isinstance(operation, str) and event["type"].endswith(".start"):
        if operation in starts:
            return _problem("identity_conflict", sequence, f"operation {operation} started twice")
        starts[operation] = event["type"]
    elif isinstance(operation, str) and event["type"].endswith(".outcome"):
        if operation in outcomes:
            return _problem("identity_conflict", sequence, f"operation {operation} has two outcomes")
        outcomes.add(operation)
    return None


def _artifact_integrity(directory: Path, artifact: Any) -> str:
    """Return ok, missing, damaged or invalid for one linked artifact (never raises)."""
    if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
        return "invalid"
    path, digest, size = artifact["path"], artifact.get("sha256"), artifact.get("bytes")
    if not ARTIFACT_PATH.match(path) or path != f"{ARTIFACT_DIRECTORY}/{digest}":
        return "invalid"
    target = directory / path
    if not target.is_file():
        return "missing"
    stat = target.stat()
    key = f"{target}:{digest}"
    if _VERIFIED.get(key) == (stat.st_size, stat.st_mtime_ns) and stat.st_size == size:
        return "ok"
    content = target.read_bytes()
    if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
        return "damaged"
    _VERIFIED[key] = (stat.st_size, stat.st_mtime_ns)
    return "ok"


def _read_failure(directory: Path, problems: list[dict[str, Any]]) -> dict[str, Any] | None:
    marker = directory / FAILURE_MARKER
    if not marker.is_file():
        return None
    try:
        failure = json.loads(marker.read_bytes())
    except ValueError:
        failure = None
    if not isinstance(failure, dict) or failure.get("schema") != SCHEMA:
        problems.append(_problem("damaged_failure_marker", None, "failure marker is not a valid record"))
        return None
    return failure


def read_attempt_history(directory: Path) -> AttemptHistory:
    directory = Path(directory)
    problems: list[dict[str, Any]] = []
    failure = _read_failure(directory, problems)
    log = directory / LOG_NAME
    if not log.is_file():
        return AttemptHistory("failed" if failure else "empty", [], problems, 0, [], failure)

    # Only bytes after the last newline can be an interrupted append; they are not verified records.
    head, separator, tail = log.read_bytes().rpartition(b"\n")
    lines = head.split(b"\n") if separator else []
    events: list[dict[str, Any]] = []
    starts: dict[str, str] = {}
    outcomes: set[str] = set()
    attempt_id: str | None = None
    for sequence, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except ValueError as exc:
            problems.append(_problem("malformed", sequence, f"record is not valid JSON: {exc}"))
            break
        problem = _record_problem(event, sequence, attempt_id, starts, outcomes)
        if problem:
            problems.append(problem)
            break
        attempt_id = event["attempt_id"]
        for artifact in event.get("artifacts", []):
            integrity = _artifact_integrity(directory, artifact)
            if isinstance(artifact, dict):
                artifact["integrity"] = integrity
            if integrity != "ok":
                problems.append(_problem(
                    f"{integrity}_artifact", sequence,
                    f"artifact {artifact.get('role') if isinstance(artifact, dict) else '?'} is {integrity}",
                ))
        events.append(event)

    if failure and attempt_id is not None and failure.get("attempt_id") != attempt_id:
        problems.append(_problem("identity_conflict", None, "failure marker belongs to another attempt"))
    unresolved = [operation for operation in starts if operation not in outcomes]
    finished = bool(events) and events[-1]["type"] == "attempt_finished"
    if problems:
        state = "corrupt"
    elif failure:
        state = "failed"
    elif tail:
        state = "interrupted"
    elif finished:
        state = "complete"
    else:
        state = "open"
    return AttemptHistory(state, events, problems, len(tail), unresolved, failure)

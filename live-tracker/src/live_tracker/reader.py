"""Read a recorded attempt history without changing a byte of it.

The reader returns the verified prefix, every problem it found, unresolved
operations and the recording state. It never skips a damaged record silently,
never appends, and never resumes or executes anything. The format is declared by
the caller (a preserved legacy trace is read only when registered as one).

AttemptReader keeps the verified prefix between polls, so a live connection reads
only bytes appended since its last poll. A full read is one fresh AttemptReader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from live_tracker.legacy import LABELS, LEGACY_FORMAT, TRACE_NAME, read_legacy_events
from live_tracker.recorder import (
    ARTIFACT_DIRECTORY, FAILURE_MARKER, LOG_NAME, OPERATION_OUTCOMES, OPERATION_STARTS, SCHEMA, SCHEMA_VERSION,
)


ARTIFACT_PATH = re.compile(rf"^{ARTIFACT_DIRECTORY}/[0-9a-f]{{64}}$")
# ponytail: artifacts are content-addressed, so a verified digest is cached per file stat to avoid
# re-hashing on every SSE poll. Upgrade to a persistent index if artifacts ever become mutable.
_VERIFIED: dict[str, tuple[int, int]] = {}


@dataclass(frozen=True)
class AttemptHistory:
    state: str  # empty | open | interrupted | complete | failed | corrupt | legacy
    events: list[dict[str, Any]]
    problems: list[dict[str, Any]]
    torn_tail_bytes: int
    unresolved_operations: list[str]
    failure: dict[str, Any] | None
    format: str = SCHEMA
    labels: dict[str, Any] = field(default_factory=dict)

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "format": self.format,
            "verified_events": len(self.events),
            "torn_tail_bytes": self.torn_tail_bytes,
            "unresolved_operations": self.unresolved_operations,
            "problems": self.problems,
            "failure": self.failure,
            "labels": self.labels,
        }


def _problem(kind: str, sequence: int | None, detail: str) -> dict[str, Any]:
    return {"kind": kind, "sequence": sequence, "detail": detail}


def _record_problem(event: Any, sequence: int, attempt_id: str | None, started: set[str],
                    outcomes: set[str], pending: dict[str, str]) -> dict[str, Any] | None:
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
    if isinstance(operation, str) and event["type"] in OPERATION_STARTS:
        if operation in started:
            return _problem("identity_conflict", sequence, f"operation {operation} started twice")
        started.add(operation)
        pending[operation] = event["type"]
    elif isinstance(operation, str) and event["type"] in OPERATION_OUTCOMES:
        if operation in outcomes:
            return _problem("identity_conflict", sequence, f"operation {operation} has two outcomes")
        outcomes.add(operation)
        pending.pop(operation, None)
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


def _legacy_history(directory: Path) -> AttemptHistory:
    """A preserved trace without an event log: read-only, labelled, and never resumed or appended."""
    if not (directory / TRACE_NAME).is_file():
        problem = _problem("missing_trace", None, f"legacy {TRACE_NAME} is missing")
        return AttemptHistory("corrupt", [], [problem], 0, [], None, format=LEGACY_FORMAT, labels=LABELS)
    events, problems = read_legacy_events(directory)
    state = "corrupt" if problems else "legacy"
    return AttemptHistory(state, events, problems, 0, [], None, format=LEGACY_FORMAT, labels=LABELS)


class AttemptReader:
    """The verified prefix of one attempt log, kept between polls.

    poll() reads only the bytes appended since the previous call. If the log was replaced, truncated,
    or ended at a damaged record, the reader starts again from the first byte, exactly as a full read does.
    """

    def __init__(self, directory: Path, format: str = SCHEMA):
        self.directory = Path(directory)
        self.format = format
        self._reset()

    def _reset(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.problems: list[dict[str, Any]] = []
        self.tail_bytes = 0
        self.offset = 0
        self.inode: int | None = None
        self.stopped = False
        self.attempt_id: str | None = None
        self.started: set[str] = set()
        self.outcomes: set[str] = set()
        self.pending: dict[str, str] = {}

    def poll(self) -> AttemptHistory:
        if self.format == LEGACY_FORMAT:
            return _legacy_history(self.directory)
        marker_problems: list[dict[str, Any]] = []
        failure = _read_failure(self.directory, marker_problems)
        log = self.directory / LOG_NAME
        if not log.is_file():
            self._reset()
            return AttemptHistory("failed" if failure else "empty", [], marker_problems, 0, [], failure)
        self._consume(log)

        problems = [*marker_problems, *self.problems]
        if failure and self.attempt_id is not None and failure.get("attempt_id") != self.attempt_id:
            problems.append(_problem("identity_conflict", None, "failure marker belongs to another attempt"))
        finished = bool(self.events) and self.events[-1]["type"] == "attempt_finished"
        if problems:
            state = "corrupt"
        elif failure:
            state = "failed"
        elif self.tail_bytes:
            state = "interrupted"
        elif finished:
            state = "complete"
        else:
            state = "open"
        # The events list is shared with the reader, which only ever appends to it.
        return AttemptHistory(state, self.events, problems, self.tail_bytes, list(self.pending), failure)

    def _consume(self, log: Path) -> None:
        stat = log.stat()
        if self.stopped or stat.st_ino != self.inode or stat.st_size < self.offset:
            self._reset()
            self.inode = stat.st_ino
        with log.open("rb") as handle:
            handle.seek(self.offset)
            data = handle.read()
        # Only bytes after the last newline can be an interrupted append; they are not verified records.
        head, separator, tail = data.rpartition(b"\n")
        self.tail_bytes = len(tail) if separator else len(data)
        if not separator:
            return
        for line in head.split(b"\n"):
            sequence = len(self.events) + 1
            try:
                event = json.loads(line)
            except ValueError as exc:
                self.problems.append(_problem("malformed", sequence, f"record is not valid JSON: {exc}"))
                self.stopped = True
                return
            problem = _record_problem(event, sequence, self.attempt_id, self.started, self.outcomes, self.pending)
            if problem:
                self.problems.append(problem)
                self.stopped = True
                return
            self.attempt_id = event["attempt_id"]
            for artifact in event.get("artifacts", []):
                integrity = _artifact_integrity(self.directory, artifact)
                if isinstance(artifact, dict):
                    artifact["integrity"] = integrity
                if integrity != "ok":
                    self.problems.append(_problem(
                        f"{integrity}_artifact", sequence,
                        f"artifact {artifact.get('role') if isinstance(artifact, dict) else '?'} is {integrity}",
                    ))
            self.events.append(event)
        self.offset += len(head) + 1


def read_attempt_history(directory: Path, format: str = SCHEMA) -> AttemptHistory:
    """A full read: the same verification as a live poll, from the first byte."""
    return AttemptReader(directory, format).poll()

"""Append-only, fsynced attempt event log with content-addressed linked artifacts.

Durability contract (process crashes on a local filesystem): an artifact is
fsynced and renamed into place before the event that references it is
appended, and an event is fsynced before emit returns. A mandatory write that
fails stops the recorder: later emits raise without writing, and a failure
marker is saved when storage still accepts it.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Mapping
import uuid
from datetime import datetime, timezone

from agent_eval_harness.harness.context import _json_default
from agent_eval_harness.harness.hooks import EventRecordingError


SCHEMA = "agent-eval-harness/attempt-events"
SCHEMA_VERSION = 1
LOG_NAME = "events.jsonl"
ARTIFACT_DIRECTORY = "artifacts"
FAILURE_MARKER = "recording-failure.json"
# One shared rule for operation pairing (web/src/model.ts mirrors the starts): a start without an outcome is unresolved.
OPERATION_STARTS = frozenset({"model.start", "tool.start", "node.enter"})
OPERATION_OUTCOMES = frozenset({"model.outcome", "tool.outcome", "node.outcome"})


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class DurableStorage:
    """The only code that writes recorder files. Tests substitute FaultyStorage."""

    def write_artifact(self, path: Path, content: bytes, event_type: str) -> None:
        self._publish(path, content)

    def write_marker(self, path: Path, content: bytes, event_type: str) -> None:
        self._publish(path, content)

    def append_event(self, path: Path, line: bytes, event_type: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        created = not path.exists()
        with path.open("ab") as log:
            log.write(line)
            log.flush()
            os.fsync(log.fileno())
        if created:
            _fsync_directory(path.parent)

    def _publish(self, path: Path, content: bytes) -> None:
        """Make a complete file visible only after its bytes are synced."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return
        descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(name)
            raise
        _fsync_directory(path.parent)


class FaultyStorage(DurableStorage):
    """Fault-injection seam: fails the chosen storage call, optionally after a torn append.

    `kind` is "artifact" or "log"; `event_type` names the event being written.
    `calls` records every storage call in order, for durability-ordering checks.
    """

    def __init__(self, kind: str, event_type: str, *, occurrence: int = 1,
                 tear: bool = False, fail_marker: bool = False):
        self.kind = kind
        self.event_type = event_type
        self.occurrence = occurrence
        self.tear = tear
        self.fail_marker = fail_marker
        self.calls: list[tuple[str, str]] = []
        self._matches = 0

    def _should_fail(self, kind: str, event_type: str) -> bool:
        self.calls.append((kind, event_type))
        if (kind, event_type) != (self.kind, self.event_type):
            return False
        self._matches += 1
        return self._matches == self.occurrence

    def write_artifact(self, path: Path, content: bytes, event_type: str) -> None:
        if self._should_fail("artifact", event_type):
            raise OSError(f"injected artifact write failure for {event_type}")
        super().write_artifact(path, content, event_type)

    def append_event(self, path: Path, line: bytes, event_type: str) -> None:
        if self._should_fail("log", event_type):
            if self.tear:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("ab") as log:
                    log.write(line[: max(1, len(line) // 2)])
            raise OSError(f"injected log append failure for {event_type}")
        super().append_event(path, line, event_type)

    def write_marker(self, path: Path, content: bytes, event_type: str) -> None:
        self.calls.append(("marker", event_type))
        if self.fail_marker:
            raise OSError("injected failure marker write refusal")
        super().write_marker(path, content, event_type)


class AttemptRecorder:
    """Implements the harness event sink: the recorder owns sequence, time and storage."""

    def __init__(self, directory: Path, *, attempt_id: str | None = None,
                 storage: DurableStorage | None = None):
        self.directory = Path(directory).expanduser().resolve()
        if (self.directory / LOG_NAME).exists():
            raise FileExistsError(f"attempt log already exists; a recorder never resumes: {self.directory}")
        self.attempt_id = attempt_id or uuid.uuid4().hex
        # Set once a mandatory write fails; every later emit is refused.
        self.failure: dict[str, Any] | None = None
        self._storage = storage or DurableStorage()
        self._sequence = 0
        self._started = time.monotonic()
        self._lock = threading.Lock()

    def emit(
        self,
        event_type: str,
        data: Mapping[str, Any],
        artifacts: Mapping[str, bytes] | None = None,
        *,
        operation_id: str | None = None,
        parent_operation_id: str | None = None,
    ) -> None:
        with self._lock:
            if self.failure is not None:
                raise EventRecordingError(
                    f"recording already failed at {self.failure['failed_event_type']}; "
                    f"{event_type} was not written"
                )
            try:
                self._append(event_type, data, artifacts or {}, operation_id, parent_operation_id)
            except Exception as exc:
                message = self._fail(event_type, operation_id, exc)
                raise EventRecordingError(message) from exc

    def _append(self, event_type: str, data: Mapping[str, Any], artifacts: Mapping[str, bytes],
                operation_id: str | None, parent_operation_id: str | None) -> None:
        # Snapshot now so later mutation of harness objects cannot change the record.
        payload = json.loads(json.dumps(dict(data), ensure_ascii=False, default=_json_default))
        linked = []
        for role, content in artifacts.items():
            digest = hashlib.sha256(content).hexdigest()
            relative = f"{ARTIFACT_DIRECTORY}/{digest}"
            self._storage.write_artifact(self.directory / relative, content, event_type)
            linked.append({"role": role, "path": relative, "bytes": len(content), "sha256": digest})
        event: dict[str, Any] = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "attempt_id": self.attempt_id,
            "sequence": self._sequence + 1,
            "type": event_type,
            "timestamp": _utc_now(),
            "elapsed_seconds": round(time.monotonic() - self._started, 6),
            "data": payload,
            "artifacts": linked,
        }
        if operation_id is not None:
            event["operation_id"] = operation_id
        if parent_operation_id is not None:
            event["parent_operation_id"] = parent_operation_id
        line = json.dumps(event, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
        self._storage.append_event(self.directory / LOG_NAME, line, event_type)
        self._sequence += 1

    def _fail(self, event_type: str, operation_id: str | None, exc: Exception) -> str:
        error = f"{type(exc).__name__}: {exc}"
        marker = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "attempt_id": self.attempt_id,
            "failed_event_type": event_type,
            "operation_id": operation_id,
            "last_sequence": self._sequence,
            "error": error,
            "failed_at": _utc_now(),
        }
        try:
            self._storage.write_marker(
                self.directory / FAILURE_MARKER,
                json.dumps(marker, ensure_ascii=False, sort_keys=True).encode("utf-8"),
                event_type,
            )
            saved = True
        except Exception:
            saved = False
        self.failure = {"failed_event_type": event_type, "operation_id": operation_id,
                        "error": error, "marker_saved": saved}
        note = (
            "a failure marker was saved" if saved
            else "no failure marker could be saved, so the saved prefix stays incomplete"
        )
        return f"recording failed at {event_type}: {error}; {note}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

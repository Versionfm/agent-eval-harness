"""Append-only, fsynced attempt event log with content-addressed linked artifacts."""

from __future__ import annotations

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

from agent_eval_harness.context import _json_default


SCHEMA = "agent-eval-harness/attempt-events"
SCHEMA_VERSION = 1
LOG_NAME = "events.jsonl"
ARTIFACT_DIRECTORY = "artifacts"


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, content: bytes) -> None:
    """Make a complete file visible only after its bytes are synced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, prefix=".tmp-") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(handle.name, path)
    _fsync_directory(path.parent)


class AttemptRecorder:
    """Implements the harness event sink: the recorder owns sequence, time and storage."""

    def __init__(self, directory: Path, *, attempt_id: str | None = None):
        self.directory = Path(directory).expanduser().resolve()
        self.attempt_id = attempt_id or uuid.uuid4().hex
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
            # Snapshot now so later mutation of harness objects cannot change the record.
            payload = json.loads(json.dumps(dict(data), ensure_ascii=False, default=_json_default))
            linked = []
            for role, content in (artifacts or {}).items():
                digest = hashlib.sha256(content).hexdigest()
                relative = f"{ARTIFACT_DIRECTORY}/{digest}"
                _write_atomic(self.directory / relative, content)
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
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / LOG_NAME).open("ab") as log:
                log.write(line)
                log.flush()
                os.fsync(log.fileno())
            self._sequence += 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

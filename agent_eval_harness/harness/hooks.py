"""Optional observation sink for attempt lifecycle events.

The harness only describes what happened. A sink (for example the live tracker
recorder) decides sequence numbers, timestamps, storage and durability. The
harness never imports the observer implementation.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Protocol

from agent_eval_harness.harness.context import _json_default


def json_artifact(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default).encode("utf-8")


class EventRecordingError(RuntimeError):
    """A mandatory event could not be recorded. The harness must not run another operation."""


class AttemptEventSink(Protocol):
    def emit(
        self,
        event_type: str,
        data: Mapping[str, Any],
        artifacts: Mapping[str, bytes] | None = None,
        *,
        operation_id: str | None = None,
        parent_operation_id: str | None = None,
    ) -> None:
        """Durably record one event before returning. Raising stops further work."""


class NullEventSink:
    """Default observer: records nothing, so unobserved attempts keep their behavior."""

    def emit(
        self,
        event_type: str,
        data: Mapping[str, Any],
        artifacts: Mapping[str, bytes] | None = None,
        *,
        operation_id: str | None = None,
        parent_operation_id: str | None = None,
    ) -> None:
        return None


NULL_EVENT_SINK = NullEventSink()

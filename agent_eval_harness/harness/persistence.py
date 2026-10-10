"""06 · Session records — ordered attempt trace events, kept in memory.

_record appends an event to the in-memory trace. _record_final also publishes it to the event sink.
The saved artifact set is written by bench/artifacts.py, not here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_eval_harness.harness.hooks import NULL_EVENT_SINK, AttemptEventSink, EventRecordingError


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

def _record(trace: list[dict[str, Any]], event_type: str, **data: Any) -> dict[str, Any]:
    event = {"event_id": len(trace) + 1, "type": event_type, "timestamp": _timestamp(), **data}
    trace.append(event)
    return event

def _record_final(trace: list[dict[str, Any]], sink: AttemptEventSink, event_type: str,
                  **data: Any) -> dict[str, Any]:
    """Record a final fact in the in-memory trace and publish the same fields to the observer.

    A refused write is not raised here, so scoring and cleanup still finish. The recorder refuses every later
    mandatory write, so no model or tool operation can follow, and attempt_finished reports the recording status.
    """
    event = _record(trace, event_type, **data)
    if sink is not NULL_EVENT_SINK:
        try:
            sink.emit(event_type, data)
        except EventRecordingError:
            pass
    return event


timestamp = _timestamp
record_event = _record

"""Ordered attempt trace events and the complete saved artifact set."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from agent_eval_harness.context import _json_default
from agent_eval_harness.observation import NULL_EVENT_SINK, AttemptEventSink, EventRecordingError
from agent_eval_harness.report import render_attempt_report


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


def _collect_artifacts(result: dict[str, Any], artifact_directory: Path, *, observed: bool = False) -> None:
    """Write the final artifacts. An observed attempt keeps its history in the log only: the harness
    writes metadata, the candidate and the checks beside it, and the tracker projects the rest."""
    artifact_directory.mkdir(parents=True, exist_ok=True)
    if not observed:
        full_output_directory = artifact_directory / "tool-results"
        for event in result.get("trace", []):
            if event.get("type") != "tool" or not isinstance(event.get("result"), dict):
                continue
            full_output_directory.mkdir(parents=True, exist_ok=True)
            relative = f"tool-results/event-{event['event_id']:04d}.txt"
            output = str(event["result"].get("output", ""))
            (artifact_directory / relative).write_text(output, encoding="utf-8")
            event["result"]["output_artifact"] = relative
    metadata = result.get("metadata", {})
    (artifact_directory / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    if not observed:
        (artifact_directory / "trace.jsonl").write_text(
            "".join(json.dumps(event, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n"
                    for event in result.get("trace", [])),
            encoding="utf-8",
        )
    candidate = result.get("candidate", {"changed_files": [], "files": [], "patch": ""})
    (artifact_directory / "candidate.patch").write_text(candidate.get("patch", ""), encoding="utf-8")
    (artifact_directory / "candidate-files.json").write_text(
        json.dumps(candidate.get("files", []), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifact_directory / "checks.json").write_text(
        json.dumps(result.get("evaluation", {}), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if observed:
        return
    (artifact_directory / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    (artifact_directory / "report.html").write_text(render_attempt_report(result), encoding="utf-8")


timestamp = _timestamp
record_event = _record
collect_artifacts = _collect_artifacts

"""Ordered attempt trace events and the complete saved artifact set."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from agent_eval_harness.context import _json_default
from agent_eval_harness.report import render_attempt_report


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record(trace: list[dict[str, Any]], event_type: str, **data: Any) -> dict[str, Any]:
    event = {"event_id": len(trace) + 1, "type": event_type, "timestamp": _timestamp(), **data}
    trace.append(event)
    return event


def _collect_artifacts(result: dict[str, Any], artifact_directory: Path) -> None:
    artifact_directory.mkdir(parents=True, exist_ok=True)
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
    (artifact_directory / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    (artifact_directory / "report.html").write_text(render_attempt_report(result), encoding="utf-8")


timestamp = _timestamp
record_event = _record
collect_artifacts = _collect_artifacts

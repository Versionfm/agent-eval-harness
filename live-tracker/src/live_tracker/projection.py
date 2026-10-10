"""Final report and final results, projected from one attempt's authoritative history.

Observed attempts are rebuilt from events.jsonl and its linked artifacts. The harness publishes its
final records (termination, patch collection, evaluation, errors, attempt_finished) to the log, so
candidate and evaluation facts are read from those records only: a fact the log does not hold is
"not recorded", never inferred. Preserved legacy traces use their recorded final artifacts (result.json,
the trace records, review.json). The projection reads the attempt directory, and write_projection
is the only writer: it saves result.json, trace.jsonl and report.html, which never change the log.
The Codex review is read separately from the run metadata: the run records it as pending, and a
later review.json completes it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval_harness.context import _json_default
from agent_eval_harness.report import render_attempt_report
from live_tracker.legacy import LEGACY_FORMAT, TRACE_NAME
from live_tracker.reader import AttemptHistory, read_attempt_history
from live_tracker.recorder import SCHEMA


REVIEW_NAME = "review.json"
REPORT_NAME = "report.html"
NOT_RECORDED = "not recorded"
UNAVAILABLE_MONEY = {"status": "unavailable", "amount": None, "currency": "USD"}
# Final records the harness publishes in the same order and shape as its in-memory trace records.
FINAL_RECORD_TYPES = {"termination", "patch_collection", "evaluation", "harness_error", "cleanup_error",
                      "interruption"}


def review_status(directory: Path) -> dict[str, Any]:
    """The Codex review as recorded after the run; pending until review.json is complete."""
    path = Path(directory) / REVIEW_NAME
    if not path.is_file():
        return {"status": "pending"}
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"status": "unreadable", "detail": f"{REVIEW_NAME} is not valid JSON"}
    if review.get("status") != "complete":
        return {"status": "pending", "detail": f"{REVIEW_NAME} status is {review.get('status')!r}"}
    return {"status": "completed", "reviewer": review.get("reviewer"), "reviewed_at": review.get("reviewed_at")}


def _artifact(event: dict[str, Any], role: str) -> dict[str, Any] | None:
    for artifact in event.get("artifacts", []):
        if artifact.get("role") == role and artifact.get("integrity") == "ok":
            return artifact
    return None


def _artifact_bytes(directory: Path, event: dict[str, Any] | None, role: str) -> bytes | None:
    artifact = _artifact(event, role) if event else None
    return (directory / artifact["path"]).read_bytes() if artifact else None


def _from_log(directory: Path, history: AttemptHistory) -> dict[str, Any]:
    events = history.events
    finished = next((event for event in reversed(events) if event["type"] == "attempt_finished"), None)
    started = next((event["data"] for event in events if event["type"] == "attempt_started"), {})
    starts = {event["operation_id"]: event for event in events
              if event.get("operation_id") and event["type"].endswith(".start")}
    trace: list[dict[str, Any]] = []
    usage_by_call: list[dict[str, Any]] = []
    model_calls = retries = 0
    initial_messages: list[Any] = []
    last_state: dict[str, Any] | None = None
    harness_error: str | None = None
    for event in events:
        kind, data = event["type"], event["data"]
        if kind == "initial_context":
            raw = _artifact_bytes(directory, event, "messages.json")
            initial_messages = json.loads(raw) if raw is not None else []
            trace.append({**data, "event_id": len(trace) + 1, "type": "initial_context",
                          "timestamp": event["timestamp"], "messages": initial_messages})
        elif kind == "model.start":
            model_calls += 1
        elif kind == "model.outcome":
            request = _artifact_bytes(directory, starts.get(event.get("operation_id")), "request.json")
            record = {**data, "event_id": len(trace) + 1, "type": "model", "timestamp": event["timestamp"],
                      "request_messages": json.loads(request) if request is not None else None}
            raw = _artifact_bytes(directory, event, "response.json")
            if raw is not None:
                response = json.loads(raw)
                record["response"] = response
                usage_by_call.append({**response.get("usage", {}), "observed_model": response.get("observed_model")})
            retries += 1 if data.get("retrying") else 0
            trace.append(record)
        elif kind == "tool.outcome":
            start = starts.get(event.get("operation_id"), {})
            result = dict(data.get("result", {}))
            output = _artifact(event, "output.txt")
            if output is not None:
                result["output"] = (directory / output["path"]).read_bytes().decode("utf-8", errors="replace")
                result["output_artifact"] = output["path"]
            trace.append({
                "event_id": len(trace) + 1, "type": "tool", "timestamp": event["timestamp"],
                "tool_name": data.get("tool_name"), "tool_call_id": data.get("tool_call_id"),
                "arguments": start.get("data", {}).get("arguments"), "status": data.get("status"),
                "duration_seconds": data.get("duration_seconds"), "result": result,
                "model_visible_result": data.get("model_visible_result"),
            })
        elif kind in FINAL_RECORD_TYPES:
            trace.append({**data, "event_id": len(trace) + 1, "type": kind, "timestamp": event["timestamp"]})
            if kind == "harness_error":
                harness_error = data.get("error")
        elif kind == "state":
            last_state = data
    final = finished["data"] if finished else {}
    patch = _artifact_bytes(directory, finished, "candidate.patch") or b""
    result = {
        "termination_reason": final.get("termination_reason", NOT_RECORDED),
        "functional_verdict": final.get("functional_verdict", NOT_RECORDED),
        "failure_category": final.get("failure_category"),
        "duration_seconds": final.get("duration_seconds"),
        "trace": trace,
        "initial_context": initial_messages,
        "candidate": {"status": final.get("candidate_status", NOT_RECORDED),
                      "changed_files": final.get("changed_files", []), "files": [],
                      "patch": patch.decode("utf-8", errors="replace")},
        "evaluation": {"status": final.get("evaluation_status", NOT_RECORDED),
                       "failure_category": final.get("evaluation_failure_category"),
                       "checks": final.get("checks", {}), "messages": {},
                       "error": final.get("evaluation_error", NOT_RECORDED)},
        "metadata": {
            "task_id": started.get("task_id"), "orchestrator": started.get("orchestrator"),
            "requested_model": started.get("requested_model"), "provider": started.get("provider"),
            "model_call_count": model_calls, "retry_count": retries, "usage_by_call": usage_by_call,
            "observed_models": sorted({call["observed_model"] for call in usage_by_call
                                       if call.get("observed_model")}),
            "cost": {"estimated": (last_state or {}).get("estimated_cost", UNAVAILABLE_MONEY),
                     "reported": (last_state or {}).get("reported_cost", UNAVAILABLE_MONEY)},
            "qualitative_review": review_status(directory),
        },
        "recording": {"status": history.state, "error": (history.failure or {}).get("error")},
    }
    if harness_error is not None:
        result["harness_error"] = harness_error
    return result


def _from_legacy(directory: Path) -> dict[str, Any]:
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    lines = (directory / TRACE_NAME).read_text(encoding="utf-8").splitlines()
    result["trace"] = [json.loads(line) for line in lines]
    result["metadata"]["qualitative_review"] = review_status(directory)
    result["recording"] = {"status": "legacy", "error": None}
    return result


def build_result(directory: Path, format: str = SCHEMA) -> dict[str, Any]:
    """The projected result of one attempt, read in the format it was registered with."""
    directory = Path(directory)
    if format == LEGACY_FORMAT:
        return _from_legacy(directory)
    return _from_log(directory, read_attempt_history(directory, format))


def final_results(directory: Path, format: str = SCHEMA) -> dict[str, Any]:
    """Final facts only: never a selected point's state."""
    result = build_result(directory, format)
    return {
        "termination_reason": result["termination_reason"],
        "functional_verdict": result["functional_verdict"],
        "failure_category": result.get("failure_category"),
        "candidate": {"status": result["candidate"]["status"],
                      "changed_files": result["candidate"].get("changed_files", []),
                      "patch": result["candidate"].get("patch", "")},
        "checks": result["evaluation"].get("checks", {}),
        "evaluation_status": result["evaluation"].get("status"),
        "evaluation_error": result["evaluation"].get("error"),
        "recording": result["recording"],
        "review": result["metadata"]["qualitative_review"],
    }


def render_report(directory: Path, format: str = SCHEMA) -> str:
    return render_attempt_report(build_result(Path(directory), format))


def write_projection(directory: Path) -> Path:
    """Save the observed attempt's result.json, trace.jsonl and report.html, projected from its log.

    Only these three files are written, and the log is never rewritten. They are the same shapes the
    harness writes for unobserved attempts, so the comparison loader reads an observed directory unchanged.
    """
    directory = Path(directory)
    result = build_result(directory)
    (directory / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    (directory / "trace.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n"
                for event in result["trace"]),
        encoding="utf-8",
    )
    report = directory / REPORT_NAME
    report.write_text(render_attempt_report(result), encoding="utf-8")
    return report

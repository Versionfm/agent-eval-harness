"""Synthetic observed attempts written through the public recorder (shared by tracker tests).

Every value a test asserts is a literal written here, so expectations never come from the code under test.
"""

import contextlib
from pathlib import Path

from agent_eval_harness.observation import json_artifact
from live_tracker.recorder import AttemptRecorder


RESPONSE = "I will read the source file first."
REASONING = "Check the retrieval path before editing."
FULL_OUTPUT = "LINE-A first line\nLINE-B second line"
PATCH = "diff --git a/app/source.py b/app/source.py\n+one line\n"
CHECKS = {"title_retrieval": True, "body_relevance": False}


def record_attempt(directory: Path, *, finish: bool = True, storage=None) -> AttemptRecorder:
    recorder = AttemptRecorder(directory, attempt_id="attempt-proj-1", storage=storage)
    recorder.emit("attempt_started", {"task_id": "t1", "orchestrator": "python-loop",
                                      "requested_model": "scripted-1", "provider": "scripted"})
    messages = [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "TASK"}]
    recorder.emit("initial_context", {"message_count": 2}, {"messages.json": json_artifact(messages)})
    response = {
        "content": RESPONSE,
        "reasoning_fields": {"reasoning_content": REASONING},
        "tool_calls": [{"name": "read_file", "arguments": {"path": "app/source.py"}, "call_id": "read-1"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "observed_model": "scripted-1"},
        "observed_model": "scripted-1",
    }
    recorder.emit("model.start", {"model_call": 1, "message_count": 2},
                  {"request.json": json_artifact(messages)}, operation_id="model-1")
    recorder.emit("model.outcome", {"model_call": 1, "status": "ok", "duration_seconds": 0.5},
                  {"response.json": json_artifact(response)}, operation_id="model-1")
    recorder.emit("tool.start", {"tool_name": "read_file", "tool_call_id": "read-1",
                                 "arguments": {"path": "app/source.py"}},
                  operation_id="tool-1-1", parent_operation_id="model-1")
    recorder.emit("tool.outcome", {
        "tool_name": "read_file", "tool_call_id": "read-1", "status": "ok", "duration_seconds": 0.1,
        "result": {"status": "ok", "error": None, "exit_code": None},
        "model_visible_result": {"status": "ok", "output": "LINE-A first line", "truncated": True},
    }, {"output.txt": FULL_OUTPUT.encode("utf-8")}, operation_id="tool-1-1", parent_operation_id="model-1")
    recorder.emit("state", {
        "model_calls": 1, "max_model_calls": 4, "context_bytes": 120, "max_context_bytes": 4096,
        "usage_totals": {"prompt_tokens": 11, "completion_tokens": 3},
        "estimated_cost": {"status": "estimated", "amount": 0.001, "currency": "USD"},
        "reported_cost": {"status": "unavailable", "amount": None, "currency": "USD"},
        "loop_step": 1, "after_phase": "tool_execution",
    })
    if finish:
        recorder.emit("model.start", {"model_call": 2, "message_count": 4},
                      {"request.json": json_artifact(messages)}, operation_id="model-2")
        recorder.emit("model.outcome", {"model_call": 2, "status": "ok", "duration_seconds": 0.4},
                      {"response.json": json_artifact({"content": "Done.", "reasoning_fields": {},
                                                       "tool_calls": [], "usage": {"prompt_tokens": 40,
                                                                                   "completion_tokens": 7}})},
                      operation_id="model-2")
        recorder.emit("attempt_finished", {
            "termination_reason": "agent_completed", "functional_verdict": "failure",
            "failure_category": "acceptance_failed", "changed_files": ["app/source.py"], "checks": CHECKS,
        }, {"candidate.patch": PATCH.encode("utf-8")})
    return recorder


def build_docker_fixtures(root: Path, admission: Path, source: Path) -> dict[str, Path]:
    """Real Docker attempts saved as playback fixtures: complete, torn final record, failed mandatory write."""
    from live_tracker.recorder import AttemptRecorder, FaultyStorage
    from live_tracker.run_scripted import run_attempt

    fixtures = {
        "new-attempt": None,
        "interrupted-attempt": FaultyStorage("log", "model.outcome", tear=True, fail_marker=True),
        "failed-attempt": FaultyStorage("log", "tool.outcome"),
    }
    paths = {}
    for name, storage in fixtures.items():
        directory = root / name
        recorder = AttemptRecorder(directory, storage=storage)
        if storage is None:
            run_attempt(admission_evidence=admission, source_repository=source, output_dir=directory,
                        event_sink=recorder, scenario="workbench")
        else:
            # The faulted write is refused on purpose; the harness stops at that boundary and keeps the prefix.
            with contextlib.suppress(Exception):
                run_attempt(admission_evidence=admission, source_repository=source, output_dir=directory,
                            event_sink=recorder, scenario="workbench")
        paths[name] = directory
    return paths

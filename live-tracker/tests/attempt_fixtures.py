"""Synthetic observed attempts written through the public recorder (shared by tracker tests).

Every value a test asserts is a literal written here, so expectations never come from the code under test.
"""

import contextlib
from pathlib import Path

from agent_eval_harness.observation import EventRecordingError, json_artifact
from live_tracker.recorder import AttemptRecorder, FaultyStorage


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


WORKFLOW_ATTEMPT_ID = "workflow"  # the registry key the browser test serves each workflow recording under
MODEL_SOURCE = "agent_eval_harness.loop:_request_model_turn"
TOOL_SOURCE = "agent_eval_harness.tools:execute_tool_turn"
ROUTER_SOURCE = "agent_eval_harness.langgraph_attempt:route_after_node"


def _python_workflow_events() -> list[tuple]:
    """One python-loop attempt: two model turns, one mutating tool with its capture, then completion.

    Each entry is (type, data, operation_id, parent_operation_id); sequence numbers are 1-based positions.
    """
    return [
        ("attempt_started", {"task_id": "workflow-task", "orchestrator": "python-loop",
                             "requested_model": "scripted-1", "provider": "scripted"}, None, None),
        ("initial_context", {"status": "ready", "message_count": 2}, None, None),
        ("phase.enter", {"phase": "model_request", "loop_step": 1, "source": MODEL_SOURCE}, None, None),
        ("model.start", {"model_call": 1, "message_count": 2}, "model-1", None),
        ("model.outcome", {"model_call": 1, "status": "ok"}, "model-1", None),
        ("state", {"after_phase": "model_request", "loop_step": 1, "model_calls": 1, "max_model_calls": 4},
         None, None),
        ("phase.enter", {"phase": "tool_execution", "loop_step": 1, "source": TOOL_SOURCE}, None, None),
        ("tool.start", {"tool_name": "apply_patch", "tool_call_id": "patch-1"}, "tool-1-1", "model-1"),
        ("tool.outcome", {"tool_name": "apply_patch", "tool_call_id": "patch-1", "status": "ok"},
         "tool-1-1", "model-1"),
        ("tool.capture", {"tool_name": "apply_patch", "status": "captured"}, None, "tool-1-1"),
        ("state", {"after_phase": "tool_execution", "loop_step": 1, "model_calls": 1, "max_model_calls": 4},
         None, None),
        ("phase.enter", {"phase": "model_request", "loop_step": 2, "source": MODEL_SOURCE}, None, None),
        ("model.start", {"model_call": 2, "message_count": 4}, "model-2", None),
        ("model.outcome", {"model_call": 2, "status": "ok"}, "model-2", None),
        ("state", {"after_phase": "model_request", "loop_step": 2, "model_calls": 2, "max_model_calls": 4},
         None, None),
        ("termination", {"reason": "agent_completed"}, None, None),
        ("patch_collection", {"status": "captured", "changed_files": ["app/source.py"]}, None, None),
        ("evaluation", {"status": "ok", "checks": CHECKS}, None, None),
        ("attempt_finished", {"termination_reason": "agent_completed", "functional_verdict": "success",
                              "failure_category": None, "changed_files": ["app/source.py"], "checks": CHECKS},
         None, None),
    ]


def _langgraph_workflow_events() -> list[tuple]:
    """One LangGraph attempt: model, tool, model, then the router ends the graph with agent_completed."""
    return [
        ("attempt_started", {"task_id": "workflow-task", "orchestrator": "langgraph",
                             "requested_model": "scripted-1", "provider": "scripted"}, None, None),
        ("initial_context", {"status": "ready", "message_count": 2}, None, None),
        ("node.enter", {"node": "model_request", "graph_step_count": 1, "source": MODEL_SOURCE},
         "graph-step-1", None),
        ("model.start", {"model_call": 1, "message_count": 2}, "model-1", None),
        ("model.outcome", {"model_call": 1, "status": "ok"}, "model-1", None),
        ("node.outcome", {"node": "model_request", "graph_step_count": 1, "termination_reason": None},
         "graph-step-1", None),
        ("state", {"after_node": "model_request", "graph_step_count": 1, "model_calls": 1}, None, None),
        ("route.decision", {"after_node": "model_request", "next": "tool_execution", "reason": "tool_calls",
                            "graph_step_count": 1, "max_graph_steps": 5, "source": ROUTER_SOURCE}, None, None),
        ("node.enter", {"node": "tool_execution", "graph_step_count": 2, "source": TOOL_SOURCE},
         "graph-step-2", None),
        ("tool.start", {"tool_name": "read_file", "tool_call_id": "read-1"}, "tool-1-1", "model-1"),
        ("tool.outcome", {"tool_name": "read_file", "tool_call_id": "read-1", "status": "ok"},
         "tool-1-1", "model-1"),
        ("node.outcome", {"node": "tool_execution", "graph_step_count": 2, "termination_reason": None},
         "graph-step-2", None),
        ("state", {"after_node": "tool_execution", "graph_step_count": 2, "model_calls": 1}, None, None),
        ("route.decision", {"after_node": "tool_execution", "next": "model_request", "reason": "tool_results",
                            "graph_step_count": 2, "max_graph_steps": 5, "source": ROUTER_SOURCE}, None, None),
        ("node.enter", {"node": "model_request", "graph_step_count": 3, "source": MODEL_SOURCE},
         "graph-step-3", None),
        ("model.start", {"model_call": 2, "message_count": 4}, "model-2", None),
        ("model.outcome", {"model_call": 2, "status": "ok"}, "model-2", None),
        ("termination", {"reason": "agent_completed"}, None, None),
        ("node.outcome", {"node": "model_request", "graph_step_count": 3, "termination_reason": "agent_completed"},
         "graph-step-3", None),
        ("state", {"after_node": "model_request", "graph_step_count": 3, "model_calls": 2}, None, None),
        ("route.decision", {"after_node": "model_request", "next": "end", "reason": "agent_completed",
                            "graph_step_count": 3, "max_graph_steps": 5, "source": ROUTER_SOURCE}, None, None),
        ("patch_collection", {"status": "captured", "changed_files": []}, None, None),
        ("evaluation", {"status": "ok", "checks": CHECKS}, None, None),
        ("attempt_finished", {"termination_reason": "agent_completed", "functional_verdict": "success",
                              "failure_category": None, "changed_files": [], "checks": CHECKS}, None, None),
    ]


def _write_workflow(recorder: AttemptRecorder, events: list[tuple], limit: int | None = None) -> None:
    for event_type, data, operation_id, parent_operation_id in events[:limit]:
        recorder.emit(event_type, data, operation_id=operation_id, parent_operation_id=parent_operation_id)


def record_python_workflow(directory: Path) -> AttemptRecorder:
    """Complete python-loop recording for the workflow map (19 events)."""
    recorder = AttemptRecorder(directory, attempt_id=WORKFLOW_ATTEMPT_ID)
    _write_workflow(recorder, _python_workflow_events())
    return recorder


def record_langgraph_workflow(directory: Path) -> AttemptRecorder:
    """Complete LangGraph recording for the workflow map (24 events)."""
    recorder = AttemptRecorder(directory, attempt_id=WORKFLOW_ATTEMPT_ID)
    _write_workflow(recorder, _langgraph_workflow_events())
    return recorder


def record_open_python_workflow(directory: Path) -> AttemptRecorder:
    """A live python-loop attempt whose model request has started and not yet returned (4 events, open)."""
    recorder = AttemptRecorder(directory, attempt_id=WORKFLOW_ATTEMPT_ID)
    _write_workflow(recorder, _python_workflow_events(), limit=4)
    return recorder


def record_interrupted_python_workflow(directory: Path) -> AttemptRecorder:
    """The model outcome's final record is torn: the recording is interrupted after model.start (4 events)."""
    recorder = AttemptRecorder(directory, attempt_id=WORKFLOW_ATTEMPT_ID,
                               storage=FaultyStorage("log", "model.outcome", tear=True, fail_marker=True))
    # The faulted write is refused on purpose; the harness would stop at that boundary and keep the prefix.
    with contextlib.suppress(EventRecordingError):
        _write_workflow(recorder, _python_workflow_events())
    return recorder

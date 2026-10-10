"""Tool registry, validation, ordered dispatch, and model-visible results."""

from __future__ import annotations

import json
import time
from typing import Any

from agent_eval_harness.builtins import apply_patch, read_file, run_shell, search_text
from agent_eval_harness.capture import MUTATING_TOOLS, RepositoryCapture
from agent_eval_harness.context import _json_copy, _tool_output_for_model
from agent_eval_harness.environment import DockerTaskContainer
from agent_eval_harness.model import ModelResponse, ToolCall
from agent_eval_harness.observation import NULL_EVENT_SINK, AttemptEventSink
from agent_eval_harness.persistence import _record, _record_final


TOOL_DEFINITIONS: dict[str, dict[str, str]] = {
    "read_file": {"description": "Read a UTF-8 file from the task repository. Arguments: path."},
    "search_text": {"description": "Search repository text, case-insensitively. Arguments: query."},
    "apply_patch": {"description": "Create a file with path/content, or replace one exact old_text match with new_text."},
    "run_shell": {"description": "Run a shell command from the task repository root. Arguments: command."},
}


def _dispatch_tool(
    container: DockerTaskContainer,
    call: ToolCall,
    budgets: Any,
    timeout_seconds: float,
) -> dict[str, Any]:
    args = dict(call.arguments)
    if call.name == "read_file":
        if not isinstance(args.get("path"), str):
            return {"status": "error", "output": "", "error": "path must be text", "exit_code": None}
        return read_file(container, args["path"], timeout=timeout_seconds)
    if call.name == "search_text":
        if not isinstance(args.get("query"), str):
            return {"status": "error", "output": "", "error": "query must be text", "exit_code": None}
        return search_text(container, args["query"], timeout=timeout_seconds)
    if call.name == "apply_patch":
        return apply_patch(container, args, timeout=timeout_seconds)
    if call.name == "run_shell":
        command = args.get("command")
        if not isinstance(command, str):
            return {"status": "error", "output": "", "error": "command must be text", "exit_code": None}
        return run_shell(container, command, timeout_seconds)
    return {"status": "error", "output": "", "error": f"unknown tool: {call.name}", "exit_code": None}


def _classify_tool_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Give every tool result a stable, model-readable status and failure category."""
    normalized = dict(result)
    if normalized.get("status") == "error":
        if "error_category" not in normalized:
            if tool_name == "apply_patch":
                category = "patch_rejected"
            elif "timed out" in str(normalized.get("error", "")).casefold():
                category = "command_timeout"
            elif tool_name == "run_shell":
                category = "command_failed"
            else:
                category = "tool_failed"
            normalized["error_category"] = category
        normalized.setdefault("retryable", False)
    return normalized


def execute_tool_turn(
    *,
    response: ModelResponse,
    messages: list[dict[str, Any]],
    model_call_count: int,
    container: DockerTaskContainer,
    budgets: Any,
    work_deadline: float,
    trace: list[dict[str, Any]],
    event_sink: AttemptEventSink = NULL_EVENT_SINK,
    repository_capture: RepositoryCapture | None = None,
) -> str | None:
    """Run one ordered tool node and append its bounded outputs to conversation state."""
    for index, call in enumerate(response.tool_calls, 1):
        tool_id = call.call_id or f"call-{model_call_count}-{index}"
        operation_id = f"tool-{model_call_count}-{index}"
        # Before any dispatch: a failed start record must stop the tool from running.
        event_sink.emit(
            "tool.start", {"tool_name": call.name, "tool_call_id": tool_id,
                           "arguments": _json_copy(dict(call.arguments))},
            operation_id=operation_id, parent_operation_id=f"model-{model_call_count}",
        )
        # The budget is measured after the start record: writing it takes time the tool did not spend.
        tool_started = time.monotonic()
        tool_remaining = work_deadline - tool_started
        default_timeout = float(budgets.shell_timeout_seconds) if call.name == "run_shell" else 30.0
        dispatched = tool_remaining > 0
        if tool_remaining <= 0:
            tool_result = {
                "status": "error", "output": "",
                "error": "Attempt deadline reached before tool execution",
                "exit_code": None, "error_category": "attempt_deadline", "retryable": False,
            }
        else:
            effective_timeout = min(default_timeout, tool_remaining)
            try:
                tool_result = _classify_tool_result(
                    call.name,
                    _dispatch_tool(container, call, budgets, effective_timeout),
                )
            except Exception as exc:
                tool_result = {
                    "status": "error", "output": "",
                    "error": f"{type(exc).__name__}: {exc}", "exit_code": None,
                    "error_category": "tool_failed", "retryable": False,
                }
            if (
                time.monotonic() >= work_deadline
                and tool_result.get("status") == "error"
                and tool_result.get("error_category") == "command_timeout"
            ):
                tool_result["error_category"] = "attempt_deadline"
                tool_result["error"] = "Attempt deadline expired during tool execution"
        deadline_hit = time.monotonic() >= work_deadline
        duration = time.monotonic() - tool_started
        tool_result["duration_seconds"] = round(duration, 6)
        visible_output, truncated = _tool_output_for_model(
            str(tool_result.get("output", "")), budgets.tool_output_limit_bytes
        )
        visible = {
            "status": tool_result.get("status"),
            "output": visible_output,
            "error": tool_result.get("error"),
            "exit_code": tool_result.get("exit_code"),
            "error_category": tool_result.get("error_category"),
            "retryable": tool_result.get("retryable", False),
            "truncated": truncated,
        }
        _record(
            trace, "tool", tool_name=call.name, tool_call_id=tool_id,
            arguments=_json_copy(dict(call.arguments)), status=tool_result.get("status"),
            duration_seconds=round(duration, 6), result=tool_result,
            model_visible_result=visible,
        )
        full_output = str(tool_result.get("output", ""))
        inline_result = {key: value for key, value in tool_result.items() if key != "output"}
        event_sink.emit(
            "tool.outcome", {
                "tool_name": call.name, "tool_call_id": tool_id,
                "status": tool_result.get("status"), "duration_seconds": round(duration, 6),
                "result": inline_result, "model_visible_result": visible,
            },
            {"output.txt": full_output.encode("utf-8", errors="replace")},
            operation_id=operation_id, parent_operation_id=f"model-{model_call_count}",
        )
        # Observation only: the capture never changes the tool result, the messages or the candidate.
        if repository_capture is not None and dispatched and call.name in MUTATING_TOOLS:
            capture_data, capture_artifacts = repository_capture.observe(call.name)
            event_sink.emit("tool.capture", capture_data, capture_artifacts, parent_operation_id=operation_id)
        messages.append({
            "role": "tool", "tool_call_id": tool_id, "name": call.name,
            "content": json.dumps(visible, ensure_ascii=False, sort_keys=True),
        })
        if deadline_hit:
            termination = "attempt_deadline"
            _record_final(trace, event_sink, "termination", reason=termination, model_calls=model_call_count)
            return termination
    return None

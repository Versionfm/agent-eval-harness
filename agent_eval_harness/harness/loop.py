"""01 · While loop — bounded provider requests and the explicit Python agent loop."""

from __future__ import annotations

import copy
import queue
import threading
import time
from typing import Any, Callable

from agent_eval_harness.harness.context import _assistant_message, _context_size_bytes, _json_copy
from agent_eval_harness.harness.model import (
    ModelAdapter, ModelConfig, ModelRequest, ModelResponse, RequestBudgetExceeded,
    RetryableProviderError,
)
from agent_eval_harness.harness.hooks import NULL_EVENT_SINK, AttemptEventSink, json_artifact
from agent_eval_harness.harness.persistence import _record, _record_final


def _record_model_outcome(
    event_sink: AttemptEventSink, operation_id: str, trace: list[dict[str, Any]], **data: Any
) -> dict[str, Any]:
    """Record a model outcome in the trace and publish it under its start's operation id."""
    event = _record(trace, "model", **data)
    payload = {
        key: value for key, value in event.items()
        if key not in {"event_id", "timestamp", "request_messages", "response"}
    }
    artifacts = {"response.json": json_artifact(event["response"])} if "response" in event else None
    event_sink.emit("model.outcome", payload, artifacts, operation_id=operation_id)
    return event


class ModelCallDeadlineExceeded(TimeoutError):
    """A synchronous provider request did not return before its allocated time."""


def _complete_with_deadline(
    model: ModelAdapter, request: ModelRequest, timeout_seconds: float
) -> ModelResponse:
    """Bound a synchronous provider call without making cleanup wait for it."""
    completed: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def invoke() -> None:
        try:
            completed.put((True, model.complete(request)))
        except BaseException as exc:
            completed.put((False, exc))

    worker = threading.Thread(target=invoke, name="agent-eval-provider-call", daemon=True)
    worker.start()
    worker.join(timeout=max(0.0, timeout_seconds))
    if worker.is_alive():
        raise ModelCallDeadlineExceeded(
            "provider request exceeded the remaining attempt deadline"
        )
    succeeded, value = completed.get_nowait()
    if not succeeded:
        raise value
    return value


def _request_model_turn(
    *,
    messages: list[dict[str, Any]],
    model: ModelAdapter,
    model_config: ModelConfig,
    budgets: Any,
    work_deadline: float,
    trace: list[dict[str, Any]],
    result: dict[str, Any],
    usage_records: list[dict[str, Any]],
    model_call_count: int,
    event_sink: AttemptEventSink = NULL_EVENT_SINK,
) -> tuple[ModelResponse | None, int, str | None]:
    """Run one shared model node, including deadline, context, and retry policy."""
    if time.monotonic() >= work_deadline:
        termination = "attempt_deadline"
        _record_final(
            trace, event_sink, "termination", reason=termination,
            attempt_deadline_seconds=budgets.attempt_deadline_seconds,
        )
        return None, model_call_count, termination
    if model_call_count >= budgets.max_model_calls:
        termination = "model_call_budget"
        _record_final(trace, event_sink, "termination", reason=termination, model_calls=model_call_count)
        return None, model_call_count, termination

    context_bytes = _context_size_bytes(messages)
    result["metadata"]["context_bytes_at_last_check"] = context_bytes
    if context_bytes > budgets.max_context_bytes:
        termination = "context_budget"
        result["metadata"]["context_bytes_at_stop"] = context_bytes
        _record_final(
            trace, event_sink, "termination", reason=termination,
            context_bytes=context_bytes, max_context_bytes=budgets.max_context_bytes,
        )
        return None, model_call_count, termination

    request_retry_count = 0
    response: ModelResponse | None = None
    request: ModelRequest | None = None
    call_started = time.monotonic()
    termination: str | None = None
    while response is None and termination is None:
        if time.monotonic() >= work_deadline:
            termination = "attempt_deadline"
            _record_final(trace, event_sink, "termination", reason=termination, model_calls=model_call_count)
            break
        if model_call_count >= budgets.max_model_calls:
            termination = "model_call_budget"
            _record_final(trace, event_sink, "termination", reason=termination, model_calls=model_call_count)
            break
        request = ModelRequest(
            messages=copy.deepcopy(messages),
            config=model_config,
            timeout_seconds=work_deadline - time.monotonic(),
        )
        model_call_count += 1
        operation_id = f"model-{model_call_count}"
        # Outside the provider try: a failed start record must stop before the provider call.
        event_sink.emit(
            "model.start", {"model_call": model_call_count, "message_count": len(request.messages)},
            {"request.json": json_artifact(request.messages)}, operation_id=operation_id,
        )
        call_started = time.monotonic()
        try:
            response = _complete_with_deadline(model, request, work_deadline - call_started)
            if not isinstance(response, ModelResponse):
                raise TypeError("model adapter must return ModelResponse")
        except RequestBudgetExceeded as exc:
            duration = time.monotonic() - call_started
            snapshotter = getattr(model, "accounting_snapshot", None)
            try:
                budget_snapshot = snapshotter() if callable(snapshotter) else None
            except Exception as snapshot_error:
                budget_snapshot = {
                    "status": "unavailable",
                    "error": f"{type(snapshot_error).__name__}: {snapshot_error}",
                }
            _record_model_outcome(
                event_sink, operation_id, trace, model_call=model_call_count, status="budget_stopped",
                duration_seconds=round(duration, 6), request_messages=request.messages,
                error=f"{type(exc).__name__}: {exc}", error_category="spending_budget",
                retrying=False, spend_budget=budget_snapshot,
            )
            termination = "spending_budget"
            _record_final(trace, event_sink, "termination", reason=termination, model_calls=model_call_count)
        except ModelCallDeadlineExceeded as exc:
            duration = time.monotonic() - call_started
            _record_model_outcome(
                event_sink, operation_id, trace, model_call=model_call_count, status="timeout",
                duration_seconds=round(duration, 6), request_messages=request.messages,
                error=f"{type(exc).__name__}: {exc}", error_category="attempt_deadline",
            )
            termination = "attempt_deadline"
        except KeyboardInterrupt as exc:
            duration = time.monotonic() - call_started
            _record_model_outcome(
                event_sink, operation_id, trace, model_call=model_call_count, status="interrupted",
                duration_seconds=round(duration, 6), request_messages=request.messages,
                error=f"{type(exc).__name__}: {exc}", error_category="interrupted",
            )
            termination = "interrupted"
        except RetryableProviderError as exc:
            duration = time.monotonic() - call_started
            can_retry = (
                request_retry_count < budgets.max_provider_retries
                and model_call_count < budgets.max_model_calls
                and time.monotonic() < work_deadline
            )
            delay = min(
                budgets.provider_retry_delay_seconds,
                max(0.0, work_deadline - time.monotonic()),
            ) if can_retry else 0.0
            _record_model_outcome(
                event_sink, operation_id, trace, model_call=model_call_count, status="error",
                duration_seconds=round(duration, 6), request_messages=request.messages,
                error=f"{type(exc).__name__}: {exc}",
                error_category="retryable_provider_error", retrying=can_retry,
                retry_number=request_retry_count + 1, retry_delay_seconds=delay,
            )
            if not can_retry:
                termination = (
                    "model_call_budget"
                    if model_call_count >= budgets.max_model_calls else "provider_error"
                )
                _record_final(trace, event_sink, "termination", reason=termination, model_calls=model_call_count)
                break
            request_retry_count += 1
            result["metadata"]["retry_count"] = result["metadata"].get("retry_count", 0) + 1
            if delay:
                time.sleep(delay)
            if time.monotonic() >= work_deadline:
                termination = "attempt_deadline"
                _record_final(trace, event_sink, "termination", reason=termination, model_calls=model_call_count)
        except Exception as exc:
            duration = time.monotonic() - call_started
            _record_model_outcome(
                event_sink, operation_id, trace, model_call=model_call_count, status="error",
                duration_seconds=round(duration, 6), request_messages=request.messages,
                error=f"{type(exc).__name__}: {exc}", error_category="provider_error",
                retrying=False,
            )
            termination = "provider_error"
            _record_final(trace, event_sink, "termination", reason=termination, model_calls=model_call_count)

    if response is None:
        return None, model_call_count, termination or "provider_error"

    duration = time.monotonic() - call_started
    usage = _json_copy(dict(response.usage))
    usage["observed_model"] = response.observed_model
    usage_records.append(usage)
    response_payload = {
        "content": response.content,
        "reasoning_fields": _json_copy(dict(response.reasoning_fields)),
        "tool_calls": [
            {
                "name": call.name,
                "arguments": _json_copy(dict(call.arguments)),
                "call_id": call.call_id,
            }
            for call in response.tool_calls
        ],
        "usage": usage,
        "observed_model": response.observed_model,
    }
    _record_model_outcome(
        event_sink, operation_id, trace, model_call=model_call_count, status="ok",
        duration_seconds=round(duration, 6), request_messages=request.messages,
        response=response_payload,
    )
    messages.append(_assistant_message(response))
    if usage.get("provider_finish_reason") == "length":
        termination = "provider_output_limit"
        _record_final(
            trace, event_sink, "termination", reason=termination,
            error_category="provider_output_limit", provider_finish_reason="length",
            model_calls=model_call_count,
        )
        return response, model_call_count, termination
    if not response.tool_calls:
        termination = "agent_completed"
        _record_final(trace, event_sink, "termination", reason=termination, model_calls=model_call_count)
    return response, model_call_count, termination


# Source identities (module:function) the live tracker resolves to registered source excerpts.
MODEL_PHASE_SOURCE = "agent_eval_harness.harness.loop:_request_model_turn"
TOOL_PHASE_SOURCE = "agent_eval_harness.harness.tools:execute_tool_turn"


def run_python_loop(
    messages: list[dict[str, Any]],
    *,
    request_model: Callable[[list[dict[str, Any]], int], tuple[ModelResponse | None, int, str | None]],
    execute_tools: Callable[[ModelResponse, list[dict[str, Any]], int], str | None],
    event_sink: AttemptEventSink = NULL_EVENT_SINK,
    snapshot: Callable[[list[dict[str, Any]], int], dict[str, Any]] | None = None,
) -> tuple[str, int]:
    """Advance model and tool turns until a shared stop reason ends the attempt.

    With a sink, each phase transition is published before it runs. With a snapshot,
    a `state` event follows each phase so selected-point state depends only on earlier events.
    """
    termination = "harness_error"
    model_call_count = 0
    loop_step = 0
    while termination == "harness_error":
        loop_step += 1
        event_sink.emit("phase.enter", {"phase": "model_request", "loop_step": loop_step,
                                        "source": MODEL_PHASE_SOURCE})
        response, model_call_count, stop_reason = request_model(messages, model_call_count)
        if snapshot is not None:
            event_sink.emit("state", {**snapshot(messages, model_call_count),
                                      "loop_step": loop_step, "after_phase": "model_request"})
        if stop_reason is not None:
            termination = stop_reason
            break
        if response is None:
            termination = "provider_error"
            break
        event_sink.emit("phase.enter", {"phase": "tool_execution", "loop_step": loop_step,
                                        "source": TOOL_PHASE_SOURCE})
        termination = execute_tools(response, messages, model_call_count) or "harness_error"
        if snapshot is not None:
            event_sink.emit("state", {**snapshot(messages, model_call_count),
                                      "loop_step": loop_step, "after_phase": "tool_execution"})
    return termination, model_call_count

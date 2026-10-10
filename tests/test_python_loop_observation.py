import time
import unittest
from types import SimpleNamespace

from agent_eval_harness.harness.context import _context_size_bytes
from agent_eval_harness.harness.loop import (
    MODEL_PHASE_SOURCE, TOOL_PHASE_SOURCE, _request_model_turn, run_python_loop,
)
from agent_eval_harness.harness.model import ModelConfig, ModelResponse, ScriptedModel, ToolCall


class RecordingSink:
    def __init__(self):
        self.events = []

    def emit(self, event_type, data, artifacts=None, *, operation_id=None, parent_operation_id=None):
        self.events.append((event_type, dict(data), operation_id))


def _budgets():
    return SimpleNamespace(
        max_model_calls=4, max_context_bytes=1_000_000, max_provider_retries=0,
        provider_retry_delay_seconds=0, attempt_deadline_seconds=600, tool_output_limit_bytes=16384,
    )


def _run(sink=None, snapshot=None):
    model = ScriptedModel([
        ModelResponse(tool_calls=(ToolCall("read_file", {"path": "a.py"}, "read-1"),)),
        ModelResponse(content="done"),
    ])
    budgets = _budgets()
    trace, result, usage_records = [], {"metadata": {}}, []
    messages = [{"role": "user", "content": "task"}]

    def request_model(current, count):
        return _request_model_turn(
            messages=current, model=model,
            model_config=ModelConfig(provider="scripted", requested_model="scripted-v1"),
            budgets=budgets, work_deadline=time.monotonic() + 60, trace=trace, result=result,
            usage_records=usage_records, model_call_count=count,
            **({"event_sink": sink} if sink is not None else {}),
        )

    def execute_tools(response, current, count):
        current.append({"role": "tool", "tool_call_id": "read-1", "content": "{}"})
        return None

    kwargs = {"request_model": request_model, "execute_tools": execute_tools}
    if sink is not None:
        kwargs["event_sink"] = sink
    if snapshot is not None:
        kwargs["snapshot"] = snapshot
    termination, count = run_python_loop(messages, **kwargs)
    return termination, count, messages


class PythonLoopObservationTests(unittest.TestCase):
    def test_phases_and_state_snapshots_bracket_each_model_and_tool_turn(self):
        sink = RecordingSink()

        def snapshot(current, count):
            return {"model_calls": count, "context_bytes": _context_size_bytes(current)}

        termination, count, messages = _run(sink, snapshot)

        self.assertEqual((termination, count), ("agent_completed", 2))
        self.assertEqual(
            [event_type for event_type, _, _ in sink.events],
            ["phase.enter", "model.start", "model.outcome", "state",
             "phase.enter", "state",
             "phase.enter", "model.start", "model.outcome", "termination", "state"],
        )
        phases = [(data["phase"], data["source"], data["loop_step"])
                  for event_type, data, _ in sink.events if event_type == "phase.enter"]
        self.assertEqual(phases, [
            ("model_request", MODEL_PHASE_SOURCE, 1),
            ("tool_execution", TOOL_PHASE_SOURCE, 1),
            ("model_request", MODEL_PHASE_SOURCE, 2),
        ])
        states = [data for event_type, data, _ in sink.events if event_type == "state"]
        self.assertEqual([state["model_calls"] for state in states], [1, 1, 2])
        self.assertEqual(
            [state["after_phase"] for state in states],
            ["model_request", "tool_execution", "model_request"],
        )
        context_sizes = [state["context_bytes"] for state in states]
        self.assertEqual(context_sizes, sorted(context_sizes))
        self.assertLess(context_sizes[0], context_sizes[1])
        self.assertEqual(context_sizes[-1], _context_size_bytes(messages))
        self.assertEqual({"user", "assistant", "tool"}, {message["role"] for message in messages})
        self.assertNotIn("state", str(messages))

    def test_unobserved_loop_keeps_the_same_stop_reason_and_conversation(self):
        observed_sink = RecordingSink()

        def snapshot(current, count):
            return {"model_calls": count}

        observed = _run(observed_sink, snapshot)
        unobserved = _run()

        self.assertEqual(observed[:2], unobserved[:2])
        self.assertEqual(observed[2], unobserved[2])


if __name__ == "__main__":
    unittest.main()

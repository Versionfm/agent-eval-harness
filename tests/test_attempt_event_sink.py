import time
import unittest
from unittest import mock

from agent_eval_harness import tools
from agent_eval_harness.attempt import AttemptBudgets
from agent_eval_harness.loop import _request_model_turn
from agent_eval_harness.model import ModelConfig, ModelResponse, ScriptedModel, ToolCall
from agent_eval_harness.tools import execute_tool_turn


class RecordingSink:
    def __init__(self, fail_on: str | None = None):
        self.events = []
        self.fail_on = fail_on

    def emit(self, event_type, data, artifacts=None, *, operation_id=None, parent_operation_id=None):
        if event_type == self.fail_on:
            raise OSError("recording failed")
        self.events.append((event_type, operation_id, parent_operation_id, dict(data)))


class SinkLifecycleTests(unittest.TestCase):
    def _model_turn(self, model, sink):
        return _request_model_turn(
            messages=[{"role": "user", "content": "hi"}],
            model=model,
            model_config=ModelConfig(provider="scripted", requested_model="m"),
            budgets=AttemptBudgets(max_model_calls=3),
            work_deadline=time.monotonic() + 60,
            trace=[],
            result={"metadata": {}},
            usage_records=[],
            model_call_count=0,
            event_sink=sink,
        )

    def test_model_start_failure_stops_before_the_provider_is_called(self):
        model = ScriptedModel([ModelResponse(content="never sent")])
        with self.assertRaises(OSError):
            self._model_turn(model, RecordingSink(fail_on="model.start"))
        self.assertEqual(model.requests, [])

    def test_model_start_and_outcome_share_an_operation_identity(self):
        sink = RecordingSink()
        response, count, stop = self._model_turn(ScriptedModel([ModelResponse(content="done")]), sink)
        self.assertEqual((count, stop), (1, "agent_completed"))
        self.assertEqual(
            [(kind, op) for kind, op, _, _ in sink.events],
            [("model.start", "model-1"), ("model.outcome", "model-1"), ("termination", None)],
        )
        self.assertEqual(sink.events[1][3]["status"], "ok")

    def test_tool_start_failure_stops_before_dispatch(self):
        response = ModelResponse(tool_calls=(ToolCall("read_file", {"path": "a.py"}, "call-a"),))
        messages = []
        with mock.patch.object(tools, "_dispatch_tool") as dispatch:
            with self.assertRaises(OSError):
                execute_tool_turn(
                    response=response, messages=messages, model_call_count=2, container=None,
                    budgets=AttemptBudgets(), work_deadline=time.monotonic() + 60, trace=[],
                    event_sink=RecordingSink(fail_on="tool.start"),
                )
        dispatch.assert_not_called()
        self.assertEqual(messages, [])

    def test_tool_start_and_outcome_are_paired_under_their_model_turn(self):
        response = ModelResponse(tool_calls=(ToolCall("read_file", {"path": "a.py"}, "call-a"),))
        sink = RecordingSink()
        with mock.patch.object(tools, "_dispatch_tool", return_value={"status": "ok", "output": "x", "error": None, "exit_code": 0}):
            execute_tool_turn(
                response=response, messages=[], model_call_count=2, container=None,
                budgets=AttemptBudgets(), work_deadline=time.monotonic() + 60, trace=[], event_sink=sink,
            )
        self.assertEqual(
            [(kind, op, parent) for kind, op, parent, _ in sink.events],
            [("tool.start", "tool-2-1", "model-2"), ("tool.outcome", "tool-2-1", "model-2")],
        )


if __name__ == "__main__":
    unittest.main()

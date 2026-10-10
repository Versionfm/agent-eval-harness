"""A tool's budget is measured after its start record is written, not before (review fix, #10)."""

import time
import unittest
from types import SimpleNamespace
from unittest import mock

from agent_eval_harness import tools
from agent_eval_harness.model import ModelResponse, ToolCall


class SlowStartSink:
    """Observer whose start record takes longer than the budget left before the deadline."""

    def emit(self, event_type, data, artifacts=None, *, operation_id=None, parent_operation_id=None):
        if event_type == "tool.start":
            time.sleep(0.3)


class ToolDeadlineAfterStartRecordTests(unittest.TestCase):
    def test_a_slow_start_record_consumes_the_budget_before_dispatch(self):
        response = ModelResponse(tool_calls=(ToolCall("read_file", {"path": "app/source.py"}, "read-1"),))
        budgets = SimpleNamespace(shell_timeout_seconds=60, tool_output_limit_bytes=16384)
        trace, messages = [], []
        with mock.patch.object(tools, "_dispatch_tool", return_value={"status": "ok", "output": ""}) as dispatch:
            stop = tools.execute_tool_turn(
                response=response, messages=messages, model_call_count=1, container=object(),
                budgets=budgets, work_deadline=time.monotonic() + 0.2, trace=trace,
                event_sink=SlowStartSink(),
            )
        dispatch.assert_not_called()
        self.assertEqual(stop, "attempt_deadline")
        self.assertEqual(trace[0]["result"]["error_category"], "attempt_deadline")


if __name__ == "__main__":
    unittest.main()

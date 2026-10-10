"""Tool hooks (08): pre hooks block a call before dispatch; post hooks observe a dispatched call."""

import json
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from agent_eval_harness.bench.attempt import _capture_hook
from agent_eval_harness.harness import tools
from agent_eval_harness.harness.hooks import ToolHooks, block_tools
from agent_eval_harness.harness.model import ModelResponse, ToolCall


BUDGETS = SimpleNamespace(shell_timeout_seconds=60, tool_output_limit_bytes=16384)
OK_RESULT = {"status": "ok", "output": "x", "error": None, "exit_code": 0}
READ = ToolCall("read_file", {"path": "a.py"}, "read-1")


class RecordingSink:
    def __init__(self, log=None):
        self.events = []
        self.log = log

    def emit(self, event_type, data, artifacts=None, *, operation_id=None, parent_operation_id=None):
        self.events.append((event_type, dict(data), operation_id))
        if self.log is not None:
            self.log.append(event_type)


def _turn(calls, hooks=ToolHooks(), sink=None):
    response = ModelResponse(tool_calls=tuple(calls))
    messages, trace = [], []
    with mock.patch.object(tools, "_dispatch_tool", return_value=OK_RESULT) as dispatch:
        stop = tools.execute_tool_turn(
            response=response, messages=messages, model_call_count=1, container=object(),
            budgets=BUDGETS, work_deadline=time.monotonic() + 60, trace=trace,
            event_sink=sink or RecordingSink(), hooks=hooks,
        )
    return stop, messages, trace, dispatch


class BlockedCallTests(unittest.TestCase):
    def test_a_blocked_call_is_not_dispatched_and_the_model_sees_the_reason(self):
        call = ToolCall("apply_patch", {"path": "a.py", "content": "x"}, "patch-1")
        hooks = ToolHooks(pre=(block_tools({"apply_patch"}, "read-only attempt"),))
        stop, messages, trace, dispatch = _turn([call], hooks=hooks)

        dispatch.assert_not_called()
        self.assertIsNone(stop)
        self.assertEqual(json.loads(messages[0]["content"]), {
            "status": "error", "output": "", "error": "blocked by hook: read-only attempt",
            "exit_code": None, "error_category": "blocked_by_hook", "retryable": False, "truncated": False,
        })
        self.assertEqual(trace[0]["result"]["error_category"], "blocked_by_hook")

    def test_start_and_outcome_record_the_block_under_the_same_operation(self):
        sink = RecordingSink()
        hooks = ToolHooks(pre=(block_tools({"run_shell"}, "no shell"),))
        _turn([ToolCall("run_shell", {"command": "true"}, "shell-1")], hooks=hooks, sink=sink)

        self.assertEqual(
            [(kind, op) for kind, _, op in sink.events],
            [("tool.start", "tool-1-1"), ("tool.outcome", "tool-1-1")],
        )
        outcome = sink.events[1][1]
        self.assertEqual((outcome["status"], outcome["result"]["error_category"]), ("error", "blocked_by_hook"))


class PreHookOrderTests(unittest.TestCase):
    def test_pre_hooks_run_in_order_and_the_first_reason_blocks(self):
        seen = []

        def allow(call):
            seen.append("allow")

        def block(call):
            seen.append("block")
            return "first reason"

        def later(call):
            seen.append("later")
            return "second reason"

        _stop, messages, _trace, dispatch = _turn([READ], hooks=ToolHooks(pre=(allow, block, later)))
        self.assertEqual(seen, ["allow", "block"])
        dispatch.assert_not_called()
        self.assertIn("blocked by hook: first reason", messages[0]["content"])

    def test_block_tools_blocks_only_the_named_tools(self):
        hook = block_tools({"apply_patch"}, "read-only attempt")
        self.assertIsNone(hook(READ))
        self.assertEqual(hook(ToolCall("apply_patch", {}, "p")), "read-only attempt")


class PostHookTests(unittest.TestCase):
    def test_post_hooks_run_after_the_outcome_of_a_dispatched_call_in_order(self):
        log = []
        sink = RecordingSink(log)

        def first(call, result, operation_id):
            log.append(("first", call.name, result["status"], operation_id))

        def second(call, result, operation_id):
            log.append(("second", call.name, result["status"], operation_id))

        _turn([READ], hooks=ToolHooks(post=(first, second)), sink=sink)
        self.assertEqual(log, [
            "tool.start", "tool.outcome",
            ("first", "read_file", "ok", "tool-1-1"), ("second", "read_file", "ok", "tool-1-1"),
        ])

    def test_post_hooks_do_not_run_for_a_blocked_call(self):
        post = mock.Mock()
        hooks = ToolHooks(pre=(block_tools({"read_file"}, "no reads"),), post=(post,))
        _turn([READ], hooks=hooks)
        post.assert_not_called()

    def test_a_post_hook_error_propagates_and_stops_the_turn(self):
        def failing(call, result, operation_id):
            raise OSError("capture failed")

        with self.assertRaises(OSError):
            _turn([READ], hooks=ToolHooks(post=(failing,)))

    def test_capture_records_only_mutating_calls_under_their_tool_operation(self):
        class FakeCapture:
            def __init__(self):
                self.observed = []

            def observe(self, name):
                self.observed.append(name)
                return {"status": "captured"}, {"capture.json": b"{}"}

        capture, sink = FakeCapture(), mock.Mock()
        hooks = ToolHooks(post=(_capture_hook(capture, sink),))
        _turn([READ, ToolCall("run_shell", {"command": "true"}, "shell-1")], hooks=hooks, sink=sink)

        self.assertEqual(capture.observed, ["run_shell"])
        self.assertEqual(
            [c for c in sink.emit.call_args_list if c.args[0] == "tool.capture"],
            [mock.call("tool.capture", {"status": "captured"}, {"capture.json": b"{}"},
                       parent_operation_id="tool-1-2")],
        )


if __name__ == "__main__":
    unittest.main()

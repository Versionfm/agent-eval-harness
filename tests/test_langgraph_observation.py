"""Offline checks for LangGraph node, routing and state events through the shared sink."""

from __future__ import annotations

import unittest

from agent_eval_harness.langgraph_attempt import run_attempt_graph
from agent_eval_harness.model import ModelResponse, ToolCall


class RecordingSink:
    def __init__(self, fail_on: str | None = None):
        self.events = []
        self.fail_on = fail_on

    def emit(self, event_type, data, artifacts=None, *, operation_id=None, parent_operation_id=None):
        if event_type == self.fail_on:
            raise OSError("recording failed")
        self.events.append((event_type, dict(data), operation_id))


def _steps(calls):
    """Scripted nodes: one tool call, then completion."""
    responses = [
        ModelResponse(tool_calls=(ToolCall("read_file", {"path": "a.py"}, "read-1"),)),
        ModelResponse(content="done"),
    ]

    def model_step(state):
        calls.append(("model", state["graph_step_count"]))
        response = responses.pop(0)
        stop = None if response.tool_calls else "agent_completed"
        return {"messages": [{"role": "assistant", "content": "x"}], "model_response": response,
                "model_call_count": state["model_call_count"] + 1, "termination_reason": stop}

    def tool_step(state):
        calls.append(("tool", state["graph_step_count"]))
        return {"messages": [{"role": "tool", "tool_call_id": "read-1", "content": "{}"}],
                "model_response": state["model_response"], "termination_reason": None}

    return model_step, tool_step


def _run(sink=None, snapshot=None, max_graph_steps=10, calls=None):
    model_step, tool_step = _steps([] if calls is None else calls)
    kwargs = {"initial_messages": [{"role": "user", "content": "task"}],
              "model_step": model_step, "tool_step": tool_step, "max_graph_steps": max_graph_steps}
    if sink is not None:
        kwargs["event_sink"] = sink
    if snapshot is not None:
        kwargs["snapshot"] = snapshot
    return run_attempt_graph(**kwargs)


class LangGraphObservationTests(unittest.TestCase):
    def test_nodes_routes_and_state_are_recorded_in_execution_order(self):
        sink = RecordingSink()

        def snapshot(messages, count):
            return {"model_calls": count, "message_count": len(messages)}

        state = _run(sink, snapshot)

        self.assertEqual(
            [event_type for event_type, _, _ in sink.events],
            ["node.enter", "node.outcome", "state", "route.decision",
             "node.enter", "node.outcome", "state", "route.decision",
             "node.enter", "node.outcome", "state", "route.decision"],
        )
        entries = [(data["node"], data["graph_step_count"], op)
                   for event_type, data, op in sink.events if event_type == "node.enter"]
        self.assertEqual(entries, [
            ("model_request", 1, "graph-step-1"),
            ("tool_execution", 2, "graph-step-2"),
            ("model_request", 3, "graph-step-3"),
        ])
        routes = [(data["after_node"], data["next"], data["reason"])
                  for event_type, data, _ in sink.events if event_type == "route.decision"]
        self.assertEqual(routes, [
            ("model_request", "tool_execution", "tool_calls"),
            ("tool_execution", "model_request", "tool_results"),
            ("model_request", "end", "agent_completed"),
        ])
        states = [data for event_type, data, _ in sink.events if event_type == "state"]
        self.assertEqual([s["graph_step_count"] for s in states], [1, 2, 3])
        self.assertEqual([s["after_node"] for s in states],
                         ["model_request", "tool_execution", "model_request"])
        self.assertEqual([s["model_calls"] for s in states], [1, 1, 2])
        self.assertEqual(state["graph_step_count"], 3)
        self.assertEqual(state["termination_reason"], "agent_completed")

    def test_observation_does_not_change_graph_state(self):
        observed = _run(RecordingSink(), lambda messages, count: {"model_calls": count})
        unobserved = _run()
        self.assertEqual(observed["messages"], unobserved["messages"])
        self.assertEqual(
            (observed["graph_step_count"], observed["model_call_count"], observed["termination_reason"]),
            (unobserved["graph_step_count"], unobserved["model_call_count"], unobserved["termination_reason"]),
        )

    def test_graph_step_budget_is_recorded_as_the_routing_reason(self):
        sink = RecordingSink()
        state = _run(sink, max_graph_steps=2)
        routes = [data for event_type, data, _ in sink.events if event_type == "route.decision"]
        self.assertEqual(routes[-1]["reason"], "graph_step_budget")
        self.assertEqual(routes[-1]["next"], "end")
        self.assertIsNone(state["termination_reason"])
        self.assertEqual(state["graph_step_count"], 2)

    def test_node_entry_failure_stops_before_the_node_runs(self):
        calls = []
        with self.assertRaises(OSError):
            _run(RecordingSink(fail_on="node.enter"), calls=calls)
        self.assertEqual(calls, [])

    def test_a_node_without_an_outcome_stays_unresolved(self):
        sink = RecordingSink()

        def failing_model_step(state):
            raise RuntimeError("provider exploded")

        with self.assertRaises(RuntimeError):
            run_attempt_graph(
                initial_messages=[], model_step=failing_model_step,
                tool_step=failing_model_step, max_graph_steps=5, event_sink=sink,
            )
        self.assertEqual([event_type for event_type, _, _ in sink.events], ["node.enter"])
        self.assertEqual(sink.events[0][2], "graph-step-1")


if __name__ == "__main__":
    unittest.main()

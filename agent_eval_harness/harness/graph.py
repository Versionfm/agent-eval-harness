"""01 · While loop, as a LangGraph — a second way to run the same loop, with explicit nodes and routes.

Routing and graph-step counting live here. The node functions are defined in bench/attempt.py and call the
shared model and tool steps in loop.py and tools.py. With an event sink, each node entry and outcome,
each routing decision and each selected-point state is published where it happens.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from agent_eval_harness.harness.model import ModelResponse
from agent_eval_harness.harness.hooks import NULL_EVENT_SINK, AttemptEventSink


class AttemptGraphState(TypedDict):
    """Workflow state; messages append while per-turn values replace prior ones."""

    messages: Annotated[list[dict[str, Any]], add]
    model_response: ModelResponse | None
    model_call_count: int
    graph_step_count: int
    termination_reason: str | None


Node = Callable[[AttemptGraphState], dict[str, Any]]
Snapshot = Callable[[list[dict[str, Any]], int], dict[str, Any]]

# Source identities (module:function) the live tracker resolves to registered source excerpts.
NODE_SOURCES = {
    "model_request": "agent_eval_harness.harness.loop:_request_model_turn",
    "tool_execution": "agent_eval_harness.harness.tools:execute_tool_turn",
}
ROUTER_SOURCE = "agent_eval_harness.harness.graph:route_after_node"
NEXT_NODE = {"model_request": "tool_execution", "tool_execution": "model_request"}


def route_after_node(
    state: AttemptGraphState,
    *,
    after_node: str,
    max_graph_steps: int,
    event_sink: AttemptEventSink = NULL_EVENT_SINK,
) -> str:
    """Choose the next node (or END) and publish the decision with its reason."""
    response = state["model_response"]
    if state["termination_reason"] is not None:
        next_node, reason = END, state["termination_reason"]
    elif after_node == "model_request" and response is None:
        next_node, reason = END, "no_model_response"
    elif after_node == "model_request" and not response.tool_calls:
        next_node, reason = END, "no_tool_calls"
    elif state["graph_step_count"] >= max_graph_steps:
        next_node, reason = END, "graph_step_budget"
    else:
        next_node = NEXT_NODE[after_node]
        reason = "tool_calls" if after_node == "model_request" else "tool_results"
    event_sink.emit("route.decision", {
        "after_node": after_node, "next": "end" if next_node == END else next_node,
        "reason": reason, "graph_step_count": state["graph_step_count"],
        "max_graph_steps": max_graph_steps, "source": ROUTER_SOURCE,
    })
    return next_node


def run_attempt_graph(
    *,
    initial_messages: list[dict[str, Any]],
    model_step: Node,
    tool_step: Node,
    max_graph_steps: int,
    event_sink: AttemptEventSink = NULL_EVENT_SINK,
    snapshot: Snapshot | None = None,
) -> AttemptGraphState:
    """Compile and invoke an explicit model/tool graph with a separate step cap."""
    if max_graph_steps < 1:
        raise ValueError("max_graph_steps must be positive")

    builder = StateGraph(AttemptGraphState)

    def counted(name: str, step: Node) -> Node:
        """Run a node between its recorded entry and outcome, counting one graph step."""
        def node(state: AttemptGraphState) -> dict[str, Any]:
            count = state["graph_step_count"] + 1
            operation_id = f"graph-step-{count}"
            # Before the node runs: a failed entry record must stop the node's model or tool work.
            event_sink.emit("node.enter", {"node": name, "graph_step_count": count,
                                           "source": NODE_SOURCES[name]}, operation_id=operation_id)
            update = dict(step(state))
            update["graph_step_count"] = count
            event_sink.emit("node.outcome", {"node": name, "graph_step_count": count,
                                             "source": NODE_SOURCES[name],
                                             "termination_reason": update.get("termination_reason")},
                            operation_id=operation_id)
            if snapshot is not None:
                messages = list(state["messages"]) + list(update.get("messages", []))
                count_after = update.get("model_call_count", state["model_call_count"])
                event_sink.emit("state", {**snapshot(messages, count_after), "graph_step_count": count,
                                          "after_node": name})
            return update
        return node

    def after_model(state: AttemptGraphState) -> str:
        return route_after_node(state, after_node="model_request", max_graph_steps=max_graph_steps,
                                event_sink=event_sink)

    def after_tools(state: AttemptGraphState) -> str:
        return route_after_node(state, after_node="tool_execution", max_graph_steps=max_graph_steps,
                                event_sink=event_sink)

    builder.add_node("model_request", counted("model_request", model_step))
    builder.add_node("tool_execution", counted("tool_execution", tool_step))
    builder.add_edge(START, "model_request")
    builder.add_conditional_edges("model_request", after_model)
    builder.add_conditional_edges("tool_execution", after_tools)
    graph = builder.compile()
    return graph.invoke(
        {
            "messages": initial_messages,
            "model_response": None,
            "model_call_count": 0,
            "graph_step_count": 0,
            "termination_reason": None,
        },
        config={"recursion_limit": max_graph_steps + 1},
    )

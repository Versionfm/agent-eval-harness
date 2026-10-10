"""Explicit LangGraph wiring for the shared coding-agent attempt steps."""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from agent_eval_harness.model import ModelResponse


class AttemptGraphState(TypedDict):
    """Workflow state; messages append while per-turn values replace prior ones."""

    messages: Annotated[list[dict[str, Any]], add]
    model_response: ModelResponse | None
    model_call_count: int
    graph_step_count: int
    termination_reason: str | None


Node = Callable[[AttemptGraphState], dict[str, Any]]


def run_attempt_graph(
    *,
    initial_messages: list[dict[str, Any]],
    model_step: Node,
    tool_step: Node,
    max_graph_steps: int,
) -> AttemptGraphState:
    """Compile and invoke an explicit model/tool graph with a separate step cap."""
    if max_graph_steps < 1:
        raise ValueError("max_graph_steps must be positive")

    builder = StateGraph(AttemptGraphState)

    def counted_model_step(state: AttemptGraphState) -> dict[str, Any]:
        update = dict(model_step(state))
        update["graph_step_count"] = state["graph_step_count"] + 1
        return update

    def counted_tool_step(state: AttemptGraphState) -> dict[str, Any]:
        update = dict(tool_step(state))
        update["graph_step_count"] = state["graph_step_count"] + 1
        return update

    def after_model(state: AttemptGraphState) -> str:
        if state["termination_reason"] is not None:
            return END
        response = state["model_response"]
        if response is None or not response.tool_calls:
            return END
        if state["graph_step_count"] >= max_graph_steps:
            return END
        return "tool_execution"

    def after_tools(state: AttemptGraphState) -> str:
        if state["termination_reason"] is not None:
            return END
        if state["graph_step_count"] >= max_graph_steps:
            return END
        return "model_request"

    builder.add_node("model_request", counted_model_step)
    builder.add_node("tool_execution", counted_tool_step)
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

"""Registered source identities the workbench may show, resolved by name and never by client path."""

from __future__ import annotations

import ast
from importlib.util import find_spec
from pathlib import Path
from typing import Any


REGISTERED_SOURCES: dict[str, str] = {
    "agent_eval_harness.attempt:attempt_and_evaluate": (
        "Attempt lifecycle: prepares the task container, runs the selected orchestrator, "
        "collects the candidate, evaluates it and writes the evidence."
    ),
    "agent_eval_harness.loop:run_python_loop": (
        "Python loop: alternates the model request phase and the tool execution phase "
        "until a shared stop reason ends the attempt."
    ),
    "agent_eval_harness.loop:_request_model_turn": (
        "Model request phase: enforces deadline, context and call budgets, calls the provider "
        "with the retry policy and records one model outcome."
    ),
    "agent_eval_harness.tools:execute_tool_turn": (
        "Tool execution phase: runs the model's tool calls in order, bounds the model-visible "
        "output and appends each tool result to the conversation."
    ),
    "agent_eval_harness.langgraph_attempt:route_after_node": (
        "LangGraph router: after each node, chooses the next node or the end from the recorded "
        "stop reason, the model's tool calls and the separate graph-step budget."
    ),
}


def resolve_source(identity: str) -> dict[str, Any]:
    """Return the registered function's file, line range and source text; refuse anything else."""
    if identity not in REGISTERED_SOURCES:
        raise KeyError(f"unregistered source identity: {identity}")
    module_name, function_name = identity.split(":")
    spec = find_spec(module_name)
    if spec is None or spec.origin is None:
        raise KeyError(f"source module not found: {module_name}")
    lines = Path(spec.origin).read_text(encoding="utf-8").splitlines()
    tree = ast.parse("\n".join(lines))
    node = next(
        (item for item in tree.body
         if isinstance(item, ast.FunctionDef) and item.name == function_name),
        None,
    )
    if node is None:
        raise KeyError(f"source function not found: {identity}")
    return {
        "identity": identity,
        "file": module_name.replace(".", "/") + ".py",
        "line": node.lineno,
        "end_line": node.end_lineno,
        "responsibility": REGISTERED_SOURCES[identity],
        "text": "\n".join(lines[node.lineno - 1:node.end_lineno]),
    }

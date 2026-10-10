"""Evaluator-owned assertions over observations from an isolated candidate worker.

This module is imported by the outer harness. Candidate code runs in a separate
Docker container and can return observations, but it never imports this module,
sees its check IDs, or controls the functional verdict.
"""

from __future__ import annotations

import platform
from typing import Any, Mapping


CHECK_IDS = (
    "title_retrieval",
    "title_context",
    "body_relevance",
    "case_normalization",
    "top_k_limit",
    "input_immutable",
    "full_context_bypass",
    "history_mode",
    "input_order_independence",
)
TITLE_ID = "synthetic.weight-decay"
DECOY_ID = "synthetic.unrelated"

# Sent through stdin to a clean worker process in a fresh, candidate-only
# container. The worker returns observations, never a verdict or check map.
PROBE_SCRIPT = r'''import contextlib
import copy
import io
import json
import platform
import sys

MARKER = "__AGENT_EVAL_OBSERVATIONS__"
protocol = sys.__stdout__

def emit(payload):
    protocol.write(MARKER + json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    protocol.flush()

class FakeChat:
    def __init__(self):
        self.calls = []
    def __call__(self, system, messages):
        self.calls.append((system, messages))
        return "Synthetic answer [synthetic.weight-decay]."

def title_sections():
    return [
        {"id": "synthetic.unrelated", "title": "Graph Output",
         "url": "https://example.invalid/graph-output",
         "text": "This synthetic section discusses tensor logging only."},
        {"id": "synthetic.weight-decay", "title": "Weight Decay",
         "url": "https://example.invalid/weight-decay",
         "text": "A synthetic passage whose body omits the queried words."},
    ]

def body_sections():
    return [
        {"id": "synthetic.optimizer-state", "title": "Optimizer State",
         "url": "https://example.invalid/optimizer-state",
         "text": "Momentum buffers preserve earlier update directions."},
        {"id": "synthetic.gradient-descent", "title": "Parameter Updates",
         "url": "https://example.invalid/parameter-updates",
         "text": "Gradient descent subtracts a scaled gradient from the weights."},
    ]

def run():
    try:
        from app.source import retrieve
        from app.tutor import answer
    except BaseException as exc:
        return {"worker_status": "candidate_error",
                "error": f"{type(exc).__name__}: {exc}",
                "python_version": platform.python_version()}

    observations = {}
    def capture(name, operation):
        try:
            observations[name] = {"value": operation()}
        except BaseException as exc:
            observations[name] = {"error": f"{type(exc).__name__}: {exc}"}

    capture("title_retrieval", lambda: {
        "ids": [item.get("id") for item in retrieve(
            "WHAT IS WEIGHT DECAY?", title_sections(), k=1)]})

    def title_context():
        chat = FakeChat()
        answer("WHAT IS WEIGHT DECAY?", chat=chat, sections=title_sections(),
               prompt="Synthetic tutor rules", k=1)
        return {"system": chat.calls[0][0]}
    capture("title_context", title_context)

    capture("body_relevance", lambda: {
        "ids": [item.get("id") for item in retrieve(
            "How does gradient descent update weights?", body_sections(), k=1)]})
    capture("case_normalization", lambda: {
        "ids": [item.get("id") for item in retrieve(
            "WHAT DOES GRADIENT DESCENT DO?", body_sections(), k=1)]})
    capture("top_k_limit", lambda: {
        "count": len(retrieve("gradient descent", body_sections() + [{
            "id": "synthetic.loss", "title": "Loss",
            "url": "https://example.invalid/loss",
            "text": "A loss measures prediction error."}], k=2))})

    def input_immutable():
        sections = title_sections()
        before = copy.deepcopy(sections)
        retrieve("WHAT IS WEIGHT DECAY?", sections, k=1)
        return {"before": before, "after": sections}
    capture("input_immutable", input_immutable)

    def full_context_bypass():
        sections = title_sections() + body_sections()
        chat = FakeChat()
        answer("WHAT IS WEIGHT DECAY?", chat=chat, sections=sections,
               prompt="Synthetic tutor rules", retrieval="full", k=1)
        return {"system": chat.calls[0][0],
                "ids": [section["id"] for section in sections]}
    capture("full_context_bypass", full_context_bypass)

    def history_mode():
        history = [
            {"role": "user", "content": "Prior synthetic question"},
            {"role": "assistant", "content": "Prior synthetic answer"},
        ]
        chat = FakeChat()
        answer("Quiz me", chat=chat, sections=body_sections(), prompt="RULES",
               history=history, mode="quiz")
        system, messages = chat.calls[0]
        return {"system": system, "messages": messages, "history": history}
    capture("history_mode", history_mode)

    def input_order_independence():
        decoy, target = title_sections()
        return {
            "forward": [item.get("id") for item in retrieve(
                "WHAT IS WEIGHT DECAY?", [decoy, target], k=1)],
            "reverse": [item.get("id") for item in retrieve(
                "WHAT IS WEIGHT DECAY?", [target, decoy], k=1)],
        }
    capture("input_order_independence", input_order_independence)
    return {"worker_status": "completed", "python_version": platform.python_version(),
            "observations": observations}

with contextlib.redirect_stdout(io.StringIO()):
    payload = run()
emit(payload)
'''


def _failed_candidate_result(message: str) -> dict[str, Any]:
    return {
        "status": "completed",
        "checks": {check_id: False for check_id in CHECK_IDS},
        "messages": {check_id: message for check_id in CHECK_IDS},
        "candidate_execution_error": message,
    }


def evaluate_observations(
    payload: Mapping[str, Any], *, expected_python_version: str
) -> dict[str, Any]:
    """Assert canonical behavior in the evaluator process, outside candidate code."""
    if payload.get("worker_status") == "candidate_error":
        return _failed_candidate_result(
            f"Candidate import/runtime error: {payload.get('error', 'unknown error')}"
        )
    if payload.get("worker_status") != "completed":
        return _failed_candidate_result("Candidate worker did not return observations.")
    if payload.get("python_version") != expected_python_version:
        return {
            "status": "error",
            "checks": {},
            "error": (
                f"Evaluator worker used Python {payload.get('python_version')!r}; "
                f"expected {expected_python_version!r}."
            ),
        }

    observations = payload.get("observations")
    if not isinstance(observations, Mapping) or set(observations) != set(CHECK_IDS):
        return _failed_candidate_result("Candidate worker returned incomplete observations.")

    checks: dict[str, bool] = {}
    check_messages: dict[str, str] = {}

    def value(check_id: str) -> Mapping[str, Any] | None:
        record = observations.get(check_id)
        if not isinstance(record, Mapping) or set(record) not in ({"value"}, {"error"}):
            checks[check_id] = False
            check_messages[check_id] = "Candidate worker returned a malformed observation."
            return None
        if "error" in record:
            checks[check_id] = False
            check_messages[check_id] = f"Candidate execution error: {record['error']}"
            return None
        observed = record["value"]
        if not isinstance(observed, Mapping):
            checks[check_id] = False
            check_messages[check_id] = "Candidate worker returned a malformed observation value."
            return None
        return observed

    def check(check_id: str, predicate: bool, passed: str, failed: str) -> None:
        if check_id not in checks:
            checks[check_id] = predicate
            check_messages[check_id] = passed if predicate else failed

    observed = value("title_retrieval")
    check("title_retrieval", bool(observed and observed.get("ids") == [TITLE_ID]),
          "title-matched passage ranked first", "title-matched passage was not ranked first")

    observed = value("title_context")
    system = observed.get("system", "") if observed else ""
    check("title_context", isinstance(system, str) and f'id="{TITLE_ID}"' in system
          and f'id="{DECOY_ID}"' not in system,
          "tutor context included the title match only",
          "tutor context omitted the title match or retained the unrelated passage")

    observed = value("body_relevance")
    check("body_relevance", bool(observed and observed.get("ids") == ["synthetic.gradient-descent"]),
          "body-text match ranked first", "body-text match did not rank first")

    observed = value("case_normalization")
    check("case_normalization", bool(observed and observed.get("ids") == ["synthetic.gradient-descent"]),
          "uppercase query matched lowercase body terms",
          "uppercase query did not match lowercase body terms")

    observed = value("top_k_limit")
    check("top_k_limit", bool(observed and observed.get("count") == 2),
          "k=2 returned two passages", "k=2 did not return exactly two passages")

    observed = value("input_immutable")
    check("input_immutable", bool(observed and observed.get("before") == observed.get("after")),
          "retrieval preserved its input passages", "retrieval changed its input passages")

    observed = value("full_context_bypass")
    system = observed.get("system", "") if observed else ""
    ids = observed.get("ids", []) if observed else []
    check("full_context_bypass", isinstance(system, str) and isinstance(ids, list)
          and all(isinstance(item, str) and f'id="{item}"' in system for item in ids),
          "full-context mode included all passages", "full-context mode omitted passages")

    observed = value("history_mode")
    if observed:
        system = observed.get("system")
        messages = observed.get("messages")
        history = observed.get("history")
        passed = (isinstance(system, str) and "Mode: quiz" in system
                  and isinstance(messages, list) and messages[:len(history)] == history
                  and messages[-1:] == [{"role": "user", "content": "Quiz me"}])
    else:
        passed = False
    check("history_mode", passed, "history and quiz mode were preserved",
          "history, quiz mode, or the current question was lost")

    observed = value("input_order_independence")
    check("input_order_independence", bool(observed and observed.get("forward") == [TITLE_ID]
          and observed.get("reverse") == [TITLE_ID]),
          "title match ranked first in both input orders",
          "title match did not rank first in both input orders")

    return {
        "status": "completed",
        "python_version": expected_python_version,
        "checks": checks,
        "messages": check_messages,
    }

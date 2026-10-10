"""08 · Hooks — the attempt event sink, and pre/post hooks around each tool call.

The harness only describes what happened. A sink (for example the live tracker
recorder) decides sequence numbers, timestamps, storage and durability. The
harness never imports the observer implementation. A pre tool hook can block a
call before dispatch; a post tool hook observes a dispatched call. Repository
capture is a post hook built in bench/attempt.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Protocol

from agent_eval_harness.harness.context import _json_default
from agent_eval_harness.harness.model import ToolCall


def json_artifact(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default).encode("utf-8")


class EventRecordingError(RuntimeError):
    """A mandatory event could not be recorded. The harness must not run another operation."""


class AttemptEventSink(Protocol):
    def emit(
        self,
        event_type: str,
        data: Mapping[str, Any],
        artifacts: Mapping[str, bytes] | None = None,
        *,
        operation_id: str | None = None,
        parent_operation_id: str | None = None,
    ) -> None:
        """Durably record one event before returning. Raising stops further work."""


class NullEventSink:
    """Default observer: records nothing, so unobserved attempts keep their behavior."""

    def emit(
        self,
        event_type: str,
        data: Mapping[str, Any],
        artifacts: Mapping[str, bytes] | None = None,
        *,
        operation_id: str | None = None,
        parent_operation_id: str | None = None,
    ) -> None:
        return None


NULL_EVENT_SINK = NullEventSink()

PreToolHook = Callable[[ToolCall], str | None]  # a reason to block the call, or None to allow it
PostToolHook = Callable[[ToolCall, dict[str, Any], str], None]  # observes (call, full result, operation_id)


@dataclass(frozen=True)
class ToolHooks:
    pre: tuple[PreToolHook, ...] = ()
    post: tuple[PostToolHook, ...] = ()


NO_TOOL_HOOKS = ToolHooks()


def block_tools(names: Iterable[str], reason: str) -> PreToolHook:
    blocked = frozenset(names)

    def hook(call: ToolCall) -> str | None:
        return reason if call.name in blocked else None

    return hook

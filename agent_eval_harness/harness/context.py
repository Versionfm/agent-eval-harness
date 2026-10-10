"""Conversation state encoding, provider continuation, and context measurements."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval_harness.harness.model import ModelResponse


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


def _tool_output_for_model(output: str, limit: int) -> tuple[str, bool]:
    encoded = output.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return output, False
    marker = "\n...[output truncated; full output is retained in the attempt trace]"
    prefix = encoded[:max(0, limit - len(marker.encode()))].decode("utf-8", errors="ignore")
    return prefix + marker, True


def _context_size_bytes(messages: list[dict[str, Any]]) -> int:
    serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    return len(serialized.encode("utf-8"))


def _assistant_message(response: ModelResponse) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": response.content,
        "tool_calls": [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(dict(call.arguments), ensure_ascii=False, sort_keys=True),
                },
            }
            for call in response.tool_calls
        ],
    }
    for key, value in response.reasoning_fields.items():
        if key not in {"role", "content", "tool_calls"}:
            message[key] = _json_copy(value)
    return message

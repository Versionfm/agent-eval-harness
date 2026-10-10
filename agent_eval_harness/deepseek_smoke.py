"""Bounded direct-DeepSeek smoke check, with no repository edits or shell tools."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from agent_eval_harness.deepseek import (
    DEFAULT_BASE_URL,
    PRICING_SOURCE_CHECKED_AT,
    PRICING_SOURCE_URL,
    DeepSeekModelAdapter,
    SpendBudget,
)
from agent_eval_harness.model import (
    ModelConfig,
    ModelRequest,
    RequestBudgetExceeded,
    RetryableProviderError,
)


def _assistant_message(response: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": response.content,
        "tool_calls": [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(
                        dict(call.arguments), ensure_ascii=False, sort_keys=True
                    ),
                },
            }
            for call in response.tool_calls
        ],
    }
    message.update(dict(response.reasoning_fields))
    return message


def _call_with_one_retry(
    adapter: DeepSeekModelAdapter,
    request: ModelRequest,
    *,
    max_retries: int,
) -> tuple[Any | None, list[dict[str, Any]], int]:
    events = []
    retries = 0
    while True:
        started = time.monotonic()
        try:
            response = adapter.complete(request)
            events.append({
                "status": "ok",
                "duration_seconds": round(time.monotonic() - started, 6),
                "response": {
                    "content": response.content,
                    "reasoning_fields": dict(response.reasoning_fields),
                    "tool_calls": [
                        {"name": call.name, "arguments": dict(call.arguments),
                         "call_id": call.call_id}
                        for call in response.tool_calls
                    ],
                    "usage": dict(response.usage),
                    "observed_model": response.observed_model,
                },
            })
            return response, events, retries
        except RetryableProviderError as exc:
            retrying = retries < max_retries
            events.append({
                "status": "error",
                "duration_seconds": round(time.monotonic() - started, 6),
                "error_category": "retryable_provider_error",
                "error": f"{type(exc).__name__}: {exc}",
                "retrying": retrying,
                "retry_number": retries + 1,
            })
            if not retrying:
                return None, events, retries
            retries += 1
        except Exception as exc:
            events.append({
                "status": "error",
                "duration_seconds": round(time.monotonic() - started, 6),
                "error_category": (
                    "spending_budget" if isinstance(exc, RequestBudgetExceeded)
                    else "provider_error"
                ),
                "error": f"{type(exc).__name__}: {exc}",
                "retrying": False,
            })
            return None, events, retries


def run_smoke(
    *,
    adapter: DeepSeekModelAdapter,
    timeout_seconds: float = 20,
    max_output_tokens: int = 512,
    max_retries: int = 1,
) -> dict[str, Any]:
    """Verify account access plus one tool-call continuation without forced tool choice."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if not 1 <= max_output_tokens <= 8192:
        raise ValueError("max_output_tokens must be from 1 to 8192")
    if max_retries < 0:
        raise ValueError("max_retries cannot be negative")

    config = ModelConfig(
        provider="deepseek",
        requested_model="deepseek-flash",
        settings={
            "thinking": "enabled",
            "reasoning_effort": "low",
            "max_output_tokens": max_output_tokens,
        },
    )
    messages: list[dict[str, Any]] = [{
        "role": "user",
        "content": (
            "This is a bounded API smoke check. Call the search_text tool exactly once "
            "with query 'deepseek-smoke-sentinel'. Do not edit files or run shell commands. "
            "After receiving its result, reply exactly SMOKE_OK."
        ),
    }]
    result: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider": "deepseek",
        "requested_model": "deepseek-flash",
        "expected_observed_model": "DeepSeek-V4.1-Flash",
        "endpoint": f"{DEFAULT_BASE_URL}/chat/completions",
        "pricing_source_url": PRICING_SOURCE_URL,
        "pricing_source_checked_at": PRICING_SOURCE_CHECKED_AT,
        "pricing_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "settings": {
            "thinking": "enabled", "reasoning_effort": "low",
            "max_output_tokens": max_output_tokens,
            "tool_choice": "provider-selected; not forced",
        },
        "timeout_seconds_per_request": timeout_seconds,
        "max_provider_retries_per_turn": max_retries,
        "account_access": "unverified",
        "tool_call_status": "unverified",
        "continuation_status": "unverified",
        "events": [],
        "conversation": messages,
        "usage_by_response": [],
        "retry_count": 0,
    }

    first, first_events, first_retries = _call_with_one_retry(
        adapter,
        ModelRequest(messages=messages, config=config, timeout_seconds=timeout_seconds),
        max_retries=max_retries,
    )
    result["events"].extend(first_events)
    result["retry_count"] += first_retries
    if first is None:
        result["status"] = "failed"
        result["account_access"] = "failed"
        result["tool_call_status"] = "not_reached"
        result["continuation_status"] = "not_reached"
        result["spend_budget"] = adapter.accounting_snapshot()
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        return result

    result["account_access"] = "confirmed"
    result["usage_by_response"].append(dict(first.usage))
    result["observed_model"] = first.observed_model
    if (len(first.tool_calls) != 1 or first.tool_calls[0].name != "search_text"
            or first.tool_calls[0].arguments.get("query") != "deepseek-smoke-sentinel"):
        result["status"] = "tool_call_missing_or_invalid"
        result["tool_call_status"] = "missing_or_invalid"
        result["continuation_status"] = "not_reached"
        result["events"].append({"status": "smoke_check_failed", "step": "expected_tool_call"})
        result["spend_budget"] = adapter.accounting_snapshot()
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        return result

    result["tool_call_status"] = "verified"
    messages.append(_assistant_message(first))
    call = first.tool_calls[0]
    messages.append({
        "role": "tool",
        "tool_call_id": call.call_id,
        "name": call.name,
        "content": json.dumps({
            "status": "ok",
            "output": "Controlled smoke sentinel found; no repository was inspected.",
        }, ensure_ascii=False, sort_keys=True),
    })
    result["conversation"] = messages

    second, second_events, second_retries = _call_with_one_retry(
        adapter,
        ModelRequest(messages=messages, config=config, timeout_seconds=timeout_seconds),
        max_retries=max_retries,
    )
    result["events"].extend(second_events)
    result["retry_count"] += second_retries
    if second is None:
        result["status"] = "continuation_failed"
        result["continuation_status"] = "failed"
    else:
        result["usage_by_response"].append(dict(second.usage))
        result["continuation_status"] = (
            "verified" if not second.tool_calls and second.content is not None else "invalid"
        )
        result["status"] = (
            "passed" if result["continuation_status"] == "verified" else "continuation_invalid"
        )
    result["spend_budget"] = adapter.accounting_snapshot()
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    return result


def load_credential_file(path: Path) -> str:
    """Read a plain-text API key from the user-provided outer-harness file."""
    api_key = path.expanduser().read_text(encoding="utf-8").strip()
    if not api_key:
        raise ValueError("credential file is empty")
    return api_key


def write_smoke_artifact(result: dict[str, Any], directory: Path) -> Path:
    directory = directory.expanduser().resolve()
    if directory.exists():
        raise ValueError(f"Smoke artifact directory already exists: {directory}")
    directory.mkdir(parents=True)
    target = directory / "smoke.json"
    target.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run a bounded DeepSeek tool-call smoke check")
    parser.add_argument("--credential-file", type=Path, required=True,
                        help="plain-text API key file; read only by the outer harness")
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--max-budget-usd", type=float, default=0.10)
    parser.add_argument("--timeout-seconds", type=float, default=20)
    args = parser.parse_args(argv)
    try:
        api_key = load_credential_file(args.credential_file)
        budget = SpendBudget(args.max_budget_usd, name="smoke")
        adapter = DeepSeekModelAdapter(api_key=api_key, spend_budget=budget)
        result = run_smoke(adapter=adapter, timeout_seconds=args.timeout_seconds)
        artifact = write_smoke_artifact(result, args.artifact_dir)
    except Exception as exc:
        parser.exit(2, f"DeepSeek smoke could not run: {type(exc).__name__}: {exc}\n")
    print(f"DeepSeek smoke: {result['status']}; artifact: {artifact}")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

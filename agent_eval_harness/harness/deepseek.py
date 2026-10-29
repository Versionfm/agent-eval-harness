"""Model adapter · direct DeepSeek Chat Completions adapter for the shared model contract, with spend budgeting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import math
import socket
import threading
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent_eval_harness.harness.model import (
    ModelRequest,
    ModelResponse,
    ProviderRequestError,
    RequestBudgetExceeded,
    RetryableProviderError,
    ToolCall,
)


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MAX_OUTPUT_TOKENS = 20000
MAX_OUTPUT_TOKENS = 20000
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
TRANSIENT_HTTP_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
PRICING_SOURCE_URL = "https://api-docs.deepseek.com/quick_start/pricing/"
PRICING_SOURCE_CHECKED_AT = "2026-10-10"
USD_PER_MILLION_PEAK = {"cache_hit_input": 0.006, "cache_miss_input": 0.30, "output": 1.20}
USD_PER_MILLION_OFFPEAK = {"cache_hit_input": 0.003, "cache_miss_input": 0.15, "output": 0.60}


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: str


class SpendBudget:
    """Thread-safe USD ceiling; a parent can enforce a shared smoke-plus-run cap."""

    def __init__(
        self,
        limit_usd: float,
        *,
        name: str = "attempt",
        parent: "SpendBudget | None" = None,
    ) -> None:
        if not math.isfinite(limit_usd) or limit_usd <= 0:
            raise ValueError("spend budget limit must be a finite positive USD amount")
        self.limit_usd = float(limit_usd)
        self.name = name
        self.parent = parent
        self._reserved_or_estimated_usd = 0.0
        self._lock = threading.Lock()

    def reserve(self, amount_usd: float) -> "SpendReservation":
        if not math.isfinite(amount_usd) or amount_usd < 0:
            raise ValueError("reservation must be a finite non-negative USD amount")
        parent_reservation = self.parent.reserve(amount_usd) if self.parent else None
        try:
            with self._lock:
                if self._reserved_or_estimated_usd + amount_usd > self.limit_usd + 1e-12:
                    raise RequestBudgetExceeded(
                        f"{self.name} USD spending limit would be exceeded by this request"
                    )
                self._reserved_or_estimated_usd += amount_usd
        except RequestBudgetExceeded:
            if parent_reservation is not None:
                parent_reservation.release()
            raise
        return SpendReservation(self, amount_usd, parent_reservation)

    def _replace_reservation(self, prior_usd: float, final_usd: float) -> None:
        with self._lock:
            self._reserved_or_estimated_usd += final_usd - prior_usd

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            amount = self._reserved_or_estimated_usd
        return {
            "name": self.name,
            "limit_usd": round(self.limit_usd, 12),
            "reserved_or_estimated_usd": round(amount, 12),
            "remaining_usd": round(max(0.0, self.limit_usd - amount), 12),
            "status": "within_limit" if amount < self.limit_usd else "limit_reached",
        }


class SpendReservation:
    def __init__(
        self,
        budget: SpendBudget,
        amount_usd: float,
        parent_reservation: "SpendReservation | None",
    ) -> None:
        self._budget = budget
        self.amount_usd = amount_usd
        self._parent_reservation = parent_reservation
        self._settled = False

    def settle(self, estimated_cost_usd: float | None) -> None:
        if self._settled:
            return
        final_amount = self.amount_usd if estimated_cost_usd is None else estimated_cost_usd
        self._budget._replace_reservation(self.amount_usd, final_amount)
        if self._parent_reservation is not None:
            self._parent_reservation.settle(estimated_cost_usd)
        self._settled = True

    def release(self) -> None:
        """Release only a reservation for a request that was never sent."""
        if self._settled:
            return
        self._budget._replace_reservation(self.amount_usd, 0.0)
        if self._parent_reservation is not None:
            self._parent_reservation.release()
        self._settled = True


class JsonTransport(Protocol):
    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HttpResponse:
        """Perform a bounded JSON POST and return the HTTP response."""


class UrllibJsonTransport:
    """Small standard-library transport with a socket timeout on blocking I/O."""

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HttpResponse:
        if timeout_seconds <= 0:
            raise TimeoutError("DeepSeek request deadline has expired")
        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise ProviderRequestError("DeepSeek response exceeded the 4 MiB limit")
                return HttpResponse(response.status, payload.decode("utf-8"))
        except HTTPError as response:
            try:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
            finally:
                response.close()
            if len(payload) > MAX_RESPONSE_BYTES:
                payload = payload[:MAX_RESPONSE_BYTES]
            return HttpResponse(response.code, payload.decode("utf-8", errors="replace"))
        except (TimeoutError, socket.timeout, URLError, ConnectionError) as exc:
            raise RetryableProviderError(
                f"DeepSeek transport failed: {type(exc).__name__}"
            ) from exc


_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 file from the task repository. Arguments: path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search repository text, case-insensitively. Arguments: query.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": (
                "Create a file with path/content, or replace one exact old_text match with new_text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command from the task repository root. Arguments: command.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
)


class DeepSeekModelAdapter:
    """Call the direct DeepSeek API and preserve its tool/thinking conversation fields."""

    def __init__(
        self,
        *,
        api_key: str,
        transport: JsonTransport | None = None,
        base_url: str = DEFAULT_BASE_URL,
        spend_budget: SpendBudget | None = None,
        pricing_clock: Any = None,
        chinese_public_holidays: frozenset[str] = frozenset(),
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("A non-empty DeepSeek API key is required")
        if not isinstance(base_url, str) or not base_url.startswith("https://"):
            raise ValueError("DeepSeek base_url must use HTTPS")
        self._api_key = api_key.strip()
        self._transport = transport or UrllibJsonTransport()
        self._execution_mode = "live_https" if transport is None else "controlled_transport"
        self._base_url = base_url.rstrip("/")
        self._spend_budget = spend_budget or SpendBudget(0.30)
        self._pricing_clock = pricing_clock or (lambda: datetime.now(timezone.utc))
        self._chinese_public_holidays = frozenset(chinese_public_holidays)

    def accounting_snapshot(self) -> dict[str, Any]:
        snapshot = self._spend_budget.snapshot()
        if self._spend_budget.parent is not None:
            snapshot["shared_budget"] = self._spend_budget.parent.snapshot()
        return snapshot

    def run_metadata(self) -> dict[str, Any]:
        return {
            "provider_endpoint": f"{self._base_url}/chat/completions",
            "documented_model_version": "DeepSeek-V4.1-Flash",
            "pricing_source_url": PRICING_SOURCE_URL,
            "pricing_source_checked_at": PRICING_SOURCE_CHECKED_AT,
            "pricing_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "transport_timeout": "ModelRequest.timeout_seconds applied to blocking HTTP I/O",
            "execution_mode": self._execution_mode,
            "credential_location": "outer harness; excluded from attempt metadata and artifacts",
        }

    def complete(self, request: ModelRequest) -> ModelResponse:
        if request.config.requested_model != "deepseek-flash":
            raise ProviderRequestError("DeepSeek attempt requires model deepseek-flash")
        if request.timeout_seconds is None or request.timeout_seconds <= 0:
            raise TimeoutError("DeepSeek request requires a positive remaining timeout")
        settings = dict(request.config.settings)
        max_output_tokens = settings.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)
        if (not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool)
                or not 1 <= max_output_tokens <= MAX_OUTPUT_TOKENS):
            raise ProviderRequestError(
                f"max_output_tokens must be an integer from 1 to {MAX_OUTPUT_TOKENS}"
            )

        body = json.dumps({
            "model": "deepseek-flash",
            "messages": request.messages,
            "tools": _TOOL_SCHEMAS,
            "reasoning_effort": "low",
            "thinking": {"type": "enabled"},
            "max_tokens": max_output_tokens,
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        # UTF-8 bytes form a conservative text-token bound. Add framing tokens for
        # chat roles and provider-internal request markers, then reserve at peak,
        # uncached rates and the configured maximum output before any HTTP call.
        max_input_tokens = len(body) + 128
        reservation_usd = _max_request_cost_usd(max_input_tokens, max_output_tokens)
        reservation = self._spend_budget.reserve(reservation_usd)
        try:
            response = self._transport.post_json(
                f"{self._base_url}/chat/completions",
                {
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body,
                request.timeout_seconds,
            )
        except RetryableProviderError:
            reservation.settle(None)
            raise
        except (TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
            reservation.settle(None)
            raise RetryableProviderError(
                f"DeepSeek transport failed: {type(exc).__name__}"
            ) from exc

        if response.status_code in TRANSIENT_HTTP_STATUSES:
            reservation.settle(None)
            raise RetryableProviderError(
                f"DeepSeek returned transient HTTP status {response.status_code}"
            )
        if not 200 <= response.status_code < 300:
            reservation.settle(None)
            raise ProviderRequestError(
                f"DeepSeek rejected the request with HTTP status {response.status_code}"
            )
        parsed = _parse_response(response.body)
        pricing_time = self._pricing_clock()
        estimated_cost, pricing_metadata = _estimate_cost(
            parsed.usage,
            pricing_time,
            chinese_public_holidays=self._chinese_public_holidays,
        )
        reservation.settle(estimated_cost)
        usage = dict(parsed.usage)
        usage["billing"] = {
            "reported_cost": {
                "status": "unavailable", "amount": None, "currency": "USD"
            },
            "estimated_cost": {
                "status": "estimated" if estimated_cost is not None else "unavailable",
                "amount": estimated_cost,
                "currency": "USD",
            },
            "reservation_usd": round(reservation_usd, 12),
            "pricing": pricing_metadata,
        }
        return ModelResponse(
            content=parsed.content,
            tool_calls=parsed.tool_calls,
            reasoning_fields=parsed.reasoning_fields,
            usage=usage,
            observed_model=parsed.observed_model,
        )


def _parse_response(body: str) -> ModelResponse:
    try:
        payload = json.loads(body)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProviderRequestError("DeepSeek returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderRequestError("DeepSeek response must be a JSON object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderRequestError("DeepSeek response did not contain a message choice")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ProviderRequestError("DeepSeek response choice did not contain a message")
    finish_reason = choices[0].get("finish_reason")
    if finish_reason is not None and not isinstance(finish_reason, str):
        raise ProviderRequestError("DeepSeek finish_reason must be text or null")
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ProviderRequestError("DeepSeek message content must be text or null")

    reasoning_fields = {
        key: value for key, value in message.items()
        if key not in {"role", "content", "tool_calls"}
    }
    raw_calls = message.get("tool_calls") or []
    if not isinstance(raw_calls, list):
        raise ProviderRequestError("DeepSeek tool_calls must be a list")
    tool_calls: list[ToolCall] = []
    for raw_call in raw_calls:
        try:
            function = raw_call["function"]
            name = function["name"]
            arguments_value = function["arguments"]
            arguments = (
                json.loads(arguments_value) if isinstance(arguments_value, str)
                else arguments_value
            )
            call_id = raw_call.get("id", "")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            if finish_reason == "length":
                raise ProviderRequestError(
                    "DeepSeek output limit truncated an invalid tool call "
                    "(finish_reason=length)"
                ) from exc
            raise ProviderRequestError("DeepSeek returned an invalid tool call") from exc
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise ProviderRequestError("DeepSeek tool call requires a name and object arguments")
        if call_id is None:
            call_id = ""
        if not isinstance(call_id, str):
            raise ProviderRequestError("DeepSeek tool call id must be text")
        tool_calls.append(ToolCall(name=name, arguments=arguments, call_id=call_id))

    raw_usage = payload.get("usage")
    usage = dict(raw_usage) if isinstance(raw_usage, dict) else {}
    if finish_reason is not None:
        usage["provider_finish_reason"] = finish_reason
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict) and "reasoning_tokens" in details:
        usage["reasoning_tokens"] = details["reasoning_tokens"]
    observed_model = payload.get("model")
    if observed_model is not None and not isinstance(observed_model, str):
        raise ProviderRequestError("DeepSeek response model identifier must be text")
    return ModelResponse(
        content=content,
        tool_calls=tuple(tool_calls),
        reasoning_fields=reasoning_fields,
        usage=usage,
        observed_model=observed_model,
    )


def _max_request_cost_usd(input_tokens: int, output_tokens: int) -> float:
    rates = USD_PER_MILLION_PEAK
    return round(
        (input_tokens * rates["cache_miss_input"]
         + output_tokens * rates["output"]) / 1_000_000,
        12,
    )


def _token_count(usage: dict[str, Any], key: str) -> int | None:
    value = usage.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _rate_band(
    pricing_time: datetime, chinese_public_holidays: frozenset[str]
) -> tuple[str, dict[str, float]]:
    if pricing_time.tzinfo is None:
        pricing_time = pricing_time.replace(tzinfo=timezone.utc)
    utc_time = pricing_time.astimezone(timezone.utc)
    holiday = utc_time.date().isoformat() in chinese_public_holidays
    peak_hour = 1 <= utc_time.hour < 4 or 6 <= utc_time.hour < 10
    is_peak = utc_time.weekday() < 5 and not holiday and peak_hour
    if is_peak:
        return "peak", USD_PER_MILLION_PEAK
    return "offpeak", USD_PER_MILLION_OFFPEAK


def _estimate_cost(
    usage: dict[str, Any],
    pricing_time: datetime,
    *,
    chinese_public_holidays: frozenset[str],
) -> tuple[float | None, dict[str, Any]]:
    rate_band, rates = _rate_band(pricing_time, chinese_public_holidays)
    hit = _token_count(usage, "prompt_cache_hit_tokens")
    miss = _token_count(usage, "prompt_cache_miss_tokens")
    prompt = _token_count(usage, "prompt_tokens")
    output = _token_count(usage, "completion_tokens")

    if hit is not None and miss is not None:
        input_hit, input_miss = hit, miss
    elif prompt is not None and hit is not None and hit <= prompt:
        input_hit, input_miss = hit, prompt - hit
    elif prompt is not None and miss is not None and miss <= prompt:
        input_hit, input_miss = prompt - miss, miss
    elif prompt is not None:
        input_hit, input_miss = 0, prompt
    elif hit is not None and miss is not None:
        input_hit, input_miss = hit, miss
    else:
        input_hit = input_miss = None

    estimated_cost = None
    if input_hit is not None and input_miss is not None and output is not None:
        estimated_cost = round(
            (
                input_hit * rates["cache_hit_input"]
                + input_miss * rates["cache_miss_input"]
                + output * rates["output"]
            ) / 1_000_000,
            12,
        )
    pricing = {
        "source_url": PRICING_SOURCE_URL,
        "source_checked_at": PRICING_SOURCE_CHECKED_AT,
        "pricing_timestamp_utc": (
            pricing_time.astimezone(timezone.utc).isoformat()
            if pricing_time.tzinfo is not None
            else pricing_time.replace(tzinfo=timezone.utc).isoformat()
        ),
        "rate_band": rate_band,
        "rates_usd_per_million_tokens": dict(rates),
        "chinese_public_holidays": sorted(chinese_public_holidays),
        "holiday_calendar_status": (
            "caller_supplied" if chinese_public_holidays else "not_configured"
        ),
    }
    return estimated_cost, pricing

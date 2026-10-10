"""Small provider-neutral model contracts for coding-agent attempts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    requested_model: str
    settings: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]
    call_id: str


@dataclass(frozen=True)
class ModelResponse:
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    reasoning_fields: Mapping[str, Any] = field(default_factory=dict)
    usage: Mapping[str, Any] = field(default_factory=dict)
    observed_model: str | None = None


@dataclass(frozen=True)
class ModelRequest:
    messages: list[dict[str, Any]]
    config: ModelConfig
    timeout_seconds: float | None = None


class ModelAdapter(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse:
        """Return one provider response without dropping provider-specific fields."""


class RetryableProviderError(RuntimeError):
    """Provider transport failure that may succeed when the same request is retried."""


class ProviderRequestError(RuntimeError):
    """A provider rejected a request or returned an invalid response."""


class RequestBudgetExceeded(RuntimeError):
    """A provider adapter refused a request that would exceed its spend budget."""


class ScriptedModel:
    """Deterministic model adapter for exercising the production attempt loop."""

    def __init__(self, responses: list[ModelResponse]):
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(deepcopy(request))
        if not self._responses:
            raise RuntimeError("scripted model responses exhausted")
        response = self._responses.pop(0)
        if not isinstance(response, ModelResponse):
            raise TypeError("scripted responses must be ModelResponse instances")
        return response

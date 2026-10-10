import json
from datetime import datetime, timezone
import unittest

from agent_eval_harness.deepseek import DeepSeekModelAdapter, HttpResponse, SpendBudget
from agent_eval_harness.deepseek_smoke import run_smoke
from agent_eval_harness.model import (
    ModelConfig,
    ModelRequest,
    ProviderRequestError,
    RequestBudgetExceeded,
    RetryableProviderError,
)


class FixtureTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def post_json(self, url, headers, body, timeout_seconds):
        self.requests.append({
            "url": url,
            "headers": dict(headers),
            "body": json.loads(body),
            "timeout_seconds": timeout_seconds,
        })
        return self.responses.pop(0)


class DeepSeekAdapterTests(unittest.TestCase):
    def test_complete_sends_bounded_thinking_request_and_preserves_tool_continuation(self):
        transport = FixtureTransport([HttpResponse(200, json.dumps({
            "model": "DeepSeek-V4.1-Flash",
            "choices": [{"message": {
                "role": "assistant",
                "content": "I will inspect the relevant file.",
                "reasoning_content": "The title must affect ranking.",
                "tool_calls": [{
                    "id": "call_17",
                    "type": "function",
                    "function": {
                        "name": "search_text",
                        "arguments": "{\"query\":\"def retrieve\"}",
                    },
                }],
            }}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 16,
                "prompt_cache_hit_tokens": 40,
                "prompt_cache_miss_tokens": 80,
                "completion_tokens_details": {"reasoning_tokens": 9},
            },
        }))])
        messages = [
            {"role": "user", "content": "Inspect title retrieval."},
            {"role": "assistant", "content": "Let me inspect.",
             "reasoning_content": "I should find the retrieval function."},
            {"role": "tool", "tool_call_id": "call_16", "name": "search_text",
             "content": "app/source.py: def retrieve(...)"},
        ]
        adapter = DeepSeekModelAdapter(
            api_key="fixture-secret",
            transport=transport,
            spend_budget=SpendBudget(0.30),
            pricing_clock=lambda: datetime(2026, 10, 10, 12, tzinfo=timezone.utc),
        )

        response = adapter.complete(ModelRequest(
            messages=messages,
            config=ModelConfig(
                provider="deepseek",
                requested_model="deepseek-flash",
                settings={"thinking": "enabled", "reasoning_effort": "low",
                          "max_output_tokens": 256},
            ),
            timeout_seconds=7.25,
        ))

        sent = transport.requests[0]
        self.assertEqual(sent["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer fixture-secret")
        self.assertEqual(sent["timeout_seconds"], 7.25)
        self.assertEqual(sent["body"]["model"], "deepseek-flash")
        self.assertEqual(sent["body"]["reasoning_effort"], "low")
        self.assertEqual(sent["body"]["thinking"], {"type": "enabled"})
        self.assertEqual(sent["body"]["max_tokens"], 256)
        self.assertNotIn("tool_choice", sent["body"])
        self.assertEqual(sent["body"]["messages"][1]["reasoning_content"],
                         "I should find the retrieval function.")
        self.assertTrue(sent["body"]["tools"])
        self.assertEqual(response.content, "I will inspect the relevant file.")
        self.assertEqual(response.reasoning_fields, {
            "reasoning_content": "The title must affect ranking."
        })
        self.assertEqual(response.tool_calls[0].name, "search_text")
        self.assertEqual(response.tool_calls[0].arguments, {"query": "def retrieve"})
        self.assertEqual(response.tool_calls[0].call_id, "call_17")
        self.assertEqual(response.observed_model, "DeepSeek-V4.1-Flash")
        self.assertEqual(response.usage["prompt_cache_hit_tokens"], 40)
        self.assertEqual(response.usage["reasoning_tokens"], 9)
        self.assertEqual(response.usage["billing"]["estimated_cost"]["amount"], 0.00002172)
        self.assertEqual(response.usage["billing"]["estimated_cost"]["status"], "estimated")
        self.assertEqual(response.usage["billing"]["reported_cost"]["status"], "unavailable")
        self.assertEqual(response.usage["billing"]["pricing"]["rate_band"], "offpeak")
        self.assertEqual(
            response.usage["billing"]["pricing"]["source_url"],
            "https://api-docs.deepseek.com/quick_start/pricing/",
        )
        self.assertEqual(adapter.run_metadata()["execution_mode"], "controlled_transport")
        self.assertLessEqual(sent["body"]["max_tokens"], 8192)

    def test_default_transport_is_labeled_as_live_https_without_making_a_request(self):
        adapter = DeepSeekModelAdapter(api_key="fixture-secret")

        self.assertEqual(adapter.run_metadata()["execution_mode"], "live_https")

    def test_complete_refuses_a_request_whose_worst_case_reservation_exceeds_the_cap(self):
        transport = FixtureTransport([HttpResponse(200, "{}")])
        adapter = DeepSeekModelAdapter(
            api_key="fixture-secret",
            transport=transport,
            spend_budget=SpendBudget(0.000001),
        )

        with self.assertRaises(RequestBudgetExceeded):
            adapter.complete(ModelRequest(
                messages=[{"role": "user", "content": "Repair the retrieval bug."}],
                config=ModelConfig(
                    provider="deepseek", requested_model="deepseek-flash",
                    settings={"max_output_tokens": 256},
                ),
                timeout_seconds=2,
            ))

        self.assertEqual(transport.requests, [])

    def test_transient_provider_status_is_retryable_without_exposing_credentials(self):
        transport = FixtureTransport([HttpResponse(503, "provider unavailable")])
        adapter = DeepSeekModelAdapter(api_key="never-log-this", transport=transport)

        with self.assertRaises(RetryableProviderError) as raised:
            adapter.complete(ModelRequest(
                messages=[{"role": "user", "content": "hello"}],
                config=ModelConfig(provider="deepseek", requested_model="deepseek-flash"),
                timeout_seconds=3,
            ))

        self.assertNotIn("never-log-this", str(raised.exception))

    def test_invalid_provider_request_is_not_retried(self):
        transport = FixtureTransport([HttpResponse(400, "invalid request")])
        adapter = DeepSeekModelAdapter(api_key="fixture-secret", transport=transport)

        with self.assertRaises(ProviderRequestError) as raised:
            adapter.complete(ModelRequest(
                messages=[{"role": "user", "content": "hello"}],
                config=ModelConfig(provider="deepseek", requested_model="deepseek-flash"),
                timeout_seconds=3,
            ))

        self.assertEqual(str(raised.exception),
                         "DeepSeek rejected the request with HTTP status 400")

    def test_output_limited_incomplete_tool_arguments_remain_a_provider_failure(self):
        transport = FixtureTransport([HttpResponse(200, json.dumps({
            "model": "DeepSeek-V4.1-Flash",
            "choices": [{
                "finish_reason": "length",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "truncated-call",
                        "type": "function",
                        "function": {"name": "apply_patch", "arguments": '{"path":'},
                    }],
                },
            }],
            "usage": {"prompt_tokens": 12, "completion_tokens": 64},
        }))])
        adapter = DeepSeekModelAdapter(api_key="fixture-secret", transport=transport)

        with self.assertRaises(ProviderRequestError) as raised:
            adapter.complete(ModelRequest(
                messages=[{"role": "user", "content": "Repair the bug."}],
                config=ModelConfig(
                    provider="deepseek", requested_model="deepseek-flash",
                    settings={"max_output_tokens": 64},
                ),
                timeout_seconds=3,
            ))

        self.assertIn("output limit truncated", str(raised.exception))
        self.assertNotIn("fixture-secret", str(raised.exception))

    def test_peak_pricing_is_applied_to_uncached_input_and_output(self):
        transport = FixtureTransport([HttpResponse(200, json.dumps({
            "model": "DeepSeek-V4.1-Flash",
            "choices": [{"message": {"role": "assistant", "content": "Done."}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10},
        }))])
        adapter = DeepSeekModelAdapter(
            api_key="fixture-secret",
            transport=transport,
            spend_budget=SpendBudget(0.30),
            pricing_clock=lambda: datetime(2026, 10, 12, 2, tzinfo=timezone.utc),
        )

        response = adapter.complete(ModelRequest(
            messages=[{"role": "user", "content": "hello"}],
            config=ModelConfig(provider="deepseek", requested_model="deepseek-flash",
                               settings={"max_output_tokens": 64}),
            timeout_seconds=3,
        ))

        self.assertEqual(response.usage["billing"]["pricing"]["rate_band"], "peak")
        self.assertEqual(response.usage["billing"]["estimated_cost"]["amount"], 0.000042)

    def test_unknown_usage_from_a_failed_request_consumes_shared_retry_headroom(self):
        transport = FixtureTransport([
            HttpResponse(503, "temporary service issue"),
            HttpResponse(200, json.dumps({
                "model": "DeepSeek-V4.1-Flash",
                "choices": [{"message": {"role": "assistant", "content": "Done."}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 4},
            })),
        ])
        shared_budget = SpendBudget(0.015, name="shared total")
        attempt_budget = SpendBudget(0.03, name="attempt", parent=shared_budget)
        adapter = DeepSeekModelAdapter(
            api_key="fixture-secret", transport=transport, spend_budget=attempt_budget
        )
        request = ModelRequest(
            messages=[{"role": "user", "content": "Repair the retrieval bug."}],
            config=ModelConfig(
                provider="deepseek", requested_model="deepseek-flash",
                settings={"max_output_tokens": 8192},
            ),
            timeout_seconds=3,
        )

        with self.assertRaises(RetryableProviderError):
            adapter.complete(request)
        with self.assertRaises(RequestBudgetExceeded):
            adapter.complete(request)

        self.assertEqual(len(transport.requests), 1)
        self.assertGreater(attempt_budget.snapshot()["reserved_or_estimated_usd"], 0)
        self.assertGreater(shared_budget.snapshot()["reserved_or_estimated_usd"], 0)
        self.assertEqual(shared_budget.snapshot()["limit_usd"], 0.015)

    def test_missing_usage_remains_unavailable_and_keeps_a_conservative_reservation(self):
        transport = FixtureTransport([HttpResponse(200, json.dumps({
            "model": "DeepSeek-V4.1-Flash",
            "choices": [{"message": {"role": "assistant", "content": "Done."}}],
        }))])
        budget = SpendBudget(0.30)
        adapter = DeepSeekModelAdapter(
            api_key="fixture-secret", transport=transport, spend_budget=budget
        )

        response = adapter.complete(ModelRequest(
            messages=[{"role": "user", "content": "Repair the retrieval bug."}],
            config=ModelConfig(
                provider="deepseek", requested_model="deepseek-flash",
                settings={"max_output_tokens": 256},
            ),
            timeout_seconds=3,
        ))

        self.assertEqual(response.usage["billing"]["estimated_cost"]["status"], "unavailable")
        self.assertIsNone(response.usage["billing"]["estimated_cost"]["amount"])
        self.assertGreater(response.usage["billing"]["reservation_usd"], 0)
        self.assertGreater(budget.snapshot()["reserved_or_estimated_usd"], 0)

    def test_bounded_smoke_requires_a_real_tool_continuation_and_preserves_reasoning(self):
        transport = FixtureTransport([
            HttpResponse(200, json.dumps({
                "model": "DeepSeek-V4.1-Flash",
                "choices": [{"message": {
                    "role": "assistant",
                    "content": "I will run the sentinel search.",
                    "reasoning_content": "The smoke request asks for one harmless search.",
                    "tool_calls": [{
                        "id": "smoke-call",
                        "type": "function",
                        "function": {
                            "name": "search_text",
                            "arguments": "{\"query\":\"deepseek-smoke-sentinel\"}",
                        },
                    }],
                }}],
                "usage": {"prompt_tokens": 30, "completion_tokens": 8},
            })),
            HttpResponse(200, json.dumps({
                "model": "DeepSeek-V4.1-Flash",
                "choices": [{"message": {
                    "role": "assistant", "content": "SMOKE_OK",
                    "reasoning_content": "The controlled tool result completed the smoke.",
                }}],
                "usage": {"prompt_tokens": 60, "completion_tokens": 4},
            })),
        ])
        adapter = DeepSeekModelAdapter(
            api_key="fixture-secret",
            transport=transport,
            spend_budget=SpendBudget(0.10),
        )

        result = run_smoke(adapter=adapter, timeout_seconds=9, max_output_tokens=64)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["account_access"], "confirmed")
        self.assertEqual(result["tool_call_status"], "verified")
        self.assertEqual(result["continuation_status"], "verified")
        self.assertEqual(len(transport.requests), 2)
        followup = transport.requests[1]["body"]["messages"]
        self.assertEqual(followup[-2]["reasoning_content"],
                         "The smoke request asks for one harmless search.")
        self.assertEqual(followup[-1]["role"], "tool")
        self.assertNotIn("tool_choice", transport.requests[0]["body"])
        self.assertEqual(transport.requests[0]["timeout_seconds"], 9)


if __name__ == "__main__":
    unittest.main()

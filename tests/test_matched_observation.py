"""Offline checks for the observed matched pair: sink wiring, stage ceilings, and the shared ledger."""

from __future__ import annotations

import tempfile
import time
from datetime import datetime, timezone
from unittest import mock
import unittest
from pathlib import Path

from agent_eval_harness import run_matched_comparison as coordinator
from agent_eval_harness.attempt import AttemptBudgets
from agent_eval_harness.deepseek import DeepSeekModelAdapter, HttpResponse, SpendBudget
from agent_eval_harness.loop import _request_model_turn
from agent_eval_harness.model import ModelConfig, ModelRequest, RequestBudgetExceeded
from agent_eval_harness.run_matched_comparison import _validate_budget_limits, run_matched_comparison
from tests.test_matched_comparison import write_inputs
from tests.test_matched_comparison_docker import MatchedRepairTransport


CONFIG = ModelConfig(
    provider="deepseek",
    requested_model="deepseek-flash",
    settings={"thinking": "enabled", "reasoning_effort": "low", "max_output_tokens": 512},
)
# Usage in the controlled responses: 200 prompt tokens and 30 completion tokens, no cache split.
# Peak-uncached estimate is not used here; settled cost is (200 * 0.30 + 30 * 1.20) / 1e6.
SETTLED_USD = 0.000096
# Monday 02:00 UTC is inside the documented peak band, so settled rates are the peak rates.
PEAK_CLOCK = lambda: datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)


class ListTransport:
    """Returns the scripted HTTP responses in order and records each request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post_json(self, url, headers, body, timeout_seconds):
        self.calls += 1
        return self.responses.pop(0)


def _ok():
    return HttpResponse(200, '{"model":"DeepSeek-V4.1-Flash","choices":[{"message":'
                             '{"role":"assistant","content":"done"}}],'
                             '"usage":{"prompt_tokens":200,"completion_tokens":30}}')


def _request():
    return ModelRequest(messages=[{"role": "user", "content": "task"}], config=CONFIG, timeout_seconds=30)


class ObservedCoordinatorWiringTests(unittest.TestCase):
    def test_each_attempt_gets_its_own_sink_and_is_projected_before_it_is_reported(self):
        seen = []
        projected = []

        def fake_attempt(**kwargs):
            kwargs["artifact_directory"].mkdir(parents=True)
            seen.append((kwargs["orchestrator"], kwargs["event_sink"]))
            # An invalid provider termination stops the pair after the first attempt.
            return {"termination_reason": "provider_error", "functional_verdict": "failure",
                    "metadata": {}, "evaluation": {"status": "completed"}}

        sinks = {}

        def factory(orchestrator, directory):
            sinks[orchestrator] = object()
            self.assertEqual(directory.name, orchestrator)
            return sinks[orchestrator]

        with tempfile.TemporaryDirectory(prefix="observed-wiring-") as temporary:
            root = Path(temporary)
            admission, parity, source, credential = write_inputs(root)
            with mock.patch.object(coordinator, "attempt_and_evaluate", fake_attempt):
                run_matched_comparison(
                    admission_evidence=admission, parity_evidence=parity, source_repository=source,
                    credential_file=credential, artifact_directory=root / "artifacts",
                    transport=MatchedRepairTransport(),
                    event_sink_factory=factory,
                    attempt_finished=lambda orchestrator, directory: projected.append(
                        (orchestrator, directory.name, directory.is_dir())),
                )

        self.assertEqual(seen, [("python-loop", sinks["python-loop"])])
        self.assertEqual(projected, [("python-loop", "python-loop", True)])

    def test_unobserved_attempts_receive_no_sink(self):
        seen = []

        def fake_attempt(**kwargs):
            kwargs["artifact_directory"].mkdir(parents=True)
            seen.append(kwargs["event_sink"])
            return {"termination_reason": "provider_error", "functional_verdict": "failure",
                    "metadata": {}, "evaluation": {"status": "completed"}}

        with tempfile.TemporaryDirectory(prefix="unobserved-wiring-") as temporary:
            root = Path(temporary)
            admission, parity, source, credential = write_inputs(root)
            with mock.patch.object(coordinator, "attempt_and_evaluate", fake_attempt):
                run_matched_comparison(
                    admission_evidence=admission, parity_evidence=parity, source_repository=source,
                    credential_file=credential, artifact_directory=root / "artifacts",
                    transport=MatchedRepairTransport(),
                )
        self.assertEqual(seen, [None])


class StageCeilingTests(unittest.TestCase):
    def test_a_stage_ceiling_must_admit_one_request_at_the_output_limit(self):
        # 2048 output tokens reserve 2048 * 1.20 / 1e6 = 0.0024576 USD at peak rate.
        kwargs = dict(shared_budget_usd=0.10, smoke_budget_usd=0.01, attempt_budget_usd=0.04,
                      max_model_calls=10, max_context_bytes=131072, attempt_deadline_seconds=600.0,
                      shell_timeout_seconds=60, max_output_tokens=2048)
        _validate_budget_limits(**kwargs)
        with self.assertRaisesRegex(ValueError, "output"):
            _validate_budget_limits(**{**kwargs, "attempt_budget_usd": 0.001})
        with self.assertRaisesRegex(ValueError, "output"):
            _validate_budget_limits(**{**kwargs, "smoke_budget_usd": 0.0001})

    def test_combined_ceiling_must_cover_smoke_and_both_attempts(self):
        kwargs = dict(shared_budget_usd=0.08, smoke_budget_usd=0.01, attempt_budget_usd=0.04,
                      max_model_calls=10, max_context_bytes=131072, attempt_deadline_seconds=600.0,
                      shell_timeout_seconds=60, max_output_tokens=2048)
        with self.assertRaisesRegex(ValueError, "shared budget"):
            _validate_budget_limits(**kwargs)


class SharedLedgerTests(unittest.TestCase):
    def test_shared_ledger_covers_smoke_both_attempts_and_a_retry(self):
        transport = ListTransport([_ok(), HttpResponse(503, "busy"), _ok(), _ok()])
        shared = SpendBudget(0.10, name="shared")
        smoke = SpendBudget(0.01, name="smoke", parent=shared)
        python_budget = SpendBudget(0.04, name="python-loop", parent=shared)
        graph_budget = SpendBudget(0.04, name="langgraph", parent=shared)
        smoke_model = DeepSeekModelAdapter(api_key="k", pricing_clock=PEAK_CLOCK, transport=transport, spend_budget=smoke)
        python_model = DeepSeekModelAdapter(api_key="k", pricing_clock=PEAK_CLOCK, transport=transport, spend_budget=python_budget)
        graph_model = DeepSeekModelAdapter(api_key="k", pricing_clock=PEAK_CLOCK, transport=transport, spend_budget=graph_budget)

        smoke_model.complete(_request())
        self.assertAlmostEqual(smoke.snapshot()["reserved_or_estimated_usd"], SETTLED_USD, places=12)

        # The transient 503 keeps its peak reservation: a failed request still counts.
        with self.assertRaises(Exception):
            python_model.complete(_request())
        pending = python_budget.snapshot()["reserved_or_estimated_usd"]
        self.assertGreater(pending, 0.0)

        python_model.complete(_request())  # the retry settles to the estimated cost
        python_reserved = python_budget.snapshot()["reserved_or_estimated_usd"]
        self.assertAlmostEqual(python_reserved, pending + SETTLED_USD, places=12)

        graph_model.complete(_request())
        graph_reserved = graph_budget.snapshot()["reserved_or_estimated_usd"]
        self.assertAlmostEqual(graph_reserved, SETTLED_USD, places=12)

        total = shared.snapshot()["reserved_or_estimated_usd"]
        self.assertAlmostEqual(
            total,
            smoke.snapshot()["reserved_or_estimated_usd"] + python_reserved + graph_reserved,
            places=12,
        )
        self.assertEqual(transport.calls, 4)


class RefusedRequestTests(unittest.TestCase):
    def test_request_that_cannot_fit_is_refused_before_any_transport_call(self):
        transport = ListTransport([_ok()])
        attempt = SpendBudget(0.0000001, name="attempt")
        model = DeepSeekModelAdapter(api_key="k", pricing_clock=PEAK_CLOCK, transport=transport, spend_budget=attempt)
        with self.assertRaises(RequestBudgetExceeded):
            model.complete(_request())
        self.assertEqual(transport.calls, 0)
        self.assertEqual(attempt.snapshot()["reserved_or_estimated_usd"], 0.0)

    def test_refusal_at_the_shared_ceiling_leaves_no_child_reservation(self):
        transport = ListTransport([_ok()])
        shared = SpendBudget(0.0000001, name="shared")
        attempt = SpendBudget(0.04, name="attempt", parent=shared)
        model = DeepSeekModelAdapter(api_key="k", pricing_clock=PEAK_CLOCK, transport=transport, spend_budget=attempt)
        with self.assertRaises(RequestBudgetExceeded):
            model.complete(_request())
        self.assertEqual(transport.calls, 0)
        self.assertEqual(attempt.snapshot()["reserved_or_estimated_usd"], 0.0)
        self.assertEqual(shared.snapshot()["reserved_or_estimated_usd"], 0.0)

    def test_the_loop_stops_with_spending_budget_and_no_transport_call(self):
        transport = ListTransport([_ok()])
        model = DeepSeekModelAdapter(
            api_key="k", pricing_clock=PEAK_CLOCK, transport=transport, spend_budget=SpendBudget(0.0000001, name="attempt"),
        )
        trace, result, usage_records = [], {"metadata": {}}, []
        budgets = AttemptBudgets(max_model_calls=10)
        response, count, termination = _request_model_turn(
            messages=[{"role": "user", "content": "task"}], model=model, model_config=CONFIG,
            budgets=budgets, work_deadline=time.monotonic() + 600, trace=trace, result=result,
            usage_records=usage_records, model_call_count=0,
        )
        self.assertIsNone(response)
        self.assertEqual(termination, "spending_budget")
        self.assertEqual(count, 1)
        self.assertEqual(transport.calls, 0)
        self.assertEqual(trace[-2]["error_category"], "spending_budget")


if __name__ == "__main__":
    unittest.main()

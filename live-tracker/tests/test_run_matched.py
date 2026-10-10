"""Offline checks for the observed matched-pair command: its own defaults, sink timing, and pricing provenance."""

import unittest

from agent_eval_harness.harness.deepseek import (
    PRICING_SOURCE_CHECKED_AT,
    PRICING_SOURCE_URL,
    USD_PER_MILLION_OFFPEAK,
    USD_PER_MILLION_PEAK,
)
from agent_eval_harness.harness.hooks import EventRecordingError
from agent_eval_harness.cli import run_matched_comparison as coordinator
from live_tracker import run_matched as pair


class PairDefaultsTests(unittest.TestCase):
    def test_the_command_defaults_fit_the_ten_cent_ceiling(self):
        args = pair.build_parser().parse_args(["--credential-file", "key.txt"])
        self.assertEqual(args.shared_budget_usd, 0.10)
        self.assertEqual(args.smoke_budget_usd, 0.01)
        self.assertEqual(args.attempt_budget_usd, 0.04)
        self.assertLessEqual(args.smoke_budget_usd + 2 * args.attempt_budget_usd, args.shared_budget_usd)

    def test_the_command_does_not_borrow_the_matched_run_budgets(self):
        self.assertNotEqual(pair.DEFAULT_SHARED_BUDGET_USD, coordinator.DEFAULT_SHARED_BUDGET_USD)
        self.assertNotEqual(pair.DEFAULT_SMOKE_BUDGET_USD, coordinator.DEFAULT_SMOKE_BUDGET_USD)
        self.assertNotEqual(pair.DEFAULT_ATTEMPT_BUDGET_USD, coordinator.DEFAULT_ATTEMPT_BUDGET_USD)

    def test_the_other_attempt_settings_match_the_first_live_pair(self):
        args = pair.build_parser().parse_args(["--credential-file", "key.txt"])
        self.assertEqual(args.max_output_tokens, coordinator.DEFAULT_MAX_OUTPUT_TOKENS)
        self.assertEqual(args.max_model_calls, coordinator.DEFAULT_MAX_MODEL_CALLS)
        self.assertEqual(args.max_context_bytes, coordinator.DEFAULT_MAX_CONTEXT_BYTES)
        self.assertEqual(args.attempt_deadline_seconds, coordinator.DEFAULT_ATTEMPT_DEADLINE_SECONDS)
        self.assertEqual(args.shell_timeout_seconds, coordinator.DEFAULT_SHELL_TIMEOUT_SECONDS)


class TimedSinkTests(unittest.TestCase):
    class Recording:
        def __init__(self):
            self.calls = []

        def emit(self, event_type, data, artifacts=None, *, operation_id=None, parent_operation_id=None):
            self.calls.append((event_type, dict(data), operation_id, parent_operation_id))

    def test_each_emit_is_passed_through_and_counted(self):
        inner = self.Recording()
        timed = pair.TimedSink(inner)
        timed.emit("attempt_started", {"task_id": "t1"})
        timed.emit("model.start", {"model_call": 1}, {"request.json": b"[]"},
                   operation_id="model-1", parent_operation_id=None)
        self.assertEqual(timed.events, 2)
        self.assertGreaterEqual(timed.seconds, 0.0)
        self.assertEqual(inner.calls[1], ("model.start", {"model_call": 1}, "model-1", None))

    def test_a_refused_record_propagates_and_is_still_counted(self):
        class Refusing:
            def emit(self, event_type, data, artifacts=None, *, operation_id=None, parent_operation_id=None):
                raise EventRecordingError("disk full")

        timed = pair.TimedSink(Refusing())
        with self.assertRaises(EventRecordingError):
            timed.emit("tool.start", {})
        self.assertEqual(timed.events, 1)


class PricingProvenanceTests(unittest.TestCase):
    def test_pricing_is_recorded_from_the_adapter_constants(self):
        provenance = pair.pricing_provenance()
        self.assertEqual(provenance["source_url"], PRICING_SOURCE_URL)
        self.assertEqual(provenance["source_checked_at"], PRICING_SOURCE_CHECKED_AT)
        self.assertEqual(provenance["rates_usd_per_million_tokens"]["peak"], USD_PER_MILLION_PEAK)
        self.assertEqual(provenance["rates_usd_per_million_tokens"]["offpeak"], USD_PER_MILLION_OFFPEAK)


if __name__ == "__main__":
    unittest.main()

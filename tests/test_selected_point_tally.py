"""Running selected-point totals give the same values as the from-scratch rescan they replace (#10 review).

The reference below is the original full-history rule, written independently of the tally. Every
prefix of a random history must produce identical state, so the observer can add only new items.
"""

import random
import unittest
from types import SimpleNamespace

from agent_eval_harness.attempt import _SelectedPointTally
from agent_eval_harness.context import _context_size_bytes


def _reference_state(messages, model_call_count, *, budgets, usage_records, trace):
    usage_totals = {}
    for usage in usage_records:
        for key, value in usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage_totals[key] = usage_totals.get(key, 0) + value
    return {
        "model_calls": model_call_count,
        "max_model_calls": budgets.max_model_calls,
        "context_bytes": _context_size_bytes(messages),
        "max_context_bytes": budgets.max_context_bytes,
        "tool_result_messages": sum(1 for message in messages if message.get("role") == "tool"),
        "tool_output_limit_bytes": budgets.tool_output_limit_bytes,
        "attempt_deadline_seconds": budgets.attempt_deadline_seconds,
        "usage_totals": usage_totals,
        **_reference_cost(usage_records, trace),
    }


def _reference_cost(usage_records, trace):
    model_events = [event for event in trace if event.get("type") == "model"]
    request_events = [event for event in model_events if event.get("status") != "budget_stopped"]
    billing_records = [
        usage.get("billing") for usage in usage_records
        if isinstance(usage, dict) and isinstance(usage.get("billing"), dict)
    ]
    if not billing_records:
        unavailable = {"status": "unavailable", "amount": None, "currency": "USD"}
        return {"reported_cost": dict(unavailable), "estimated_cost": dict(unavailable)}
    known_estimates, known_reports = [], []
    for billing in billing_records:
        estimate = billing.get("estimated_cost", {})
        if isinstance(estimate, dict) and estimate.get("status") == "estimated" and isinstance(estimate.get("amount"), (int, float)):
            known_estimates.append(float(estimate["amount"]))
        report = billing.get("reported_cost", {})
        if isinstance(report, dict) and report.get("status") == "reported" and isinstance(report.get("amount"), (int, float)):
            known_reports.append(float(report["amount"]))
    count = len(request_events)
    missing = max(0, count - len(known_estimates))
    if known_estimates:
        estimated = {"status": "partial" if missing else "estimated", "amount": round(sum(known_estimates), 12),
                     "currency": "USD", "missing_usage_calls": missing, "request_count": count}
    else:
        estimated = {"status": "unavailable", "amount": None, "currency": "USD",
                     "missing_usage_calls": count, "request_count": count}
    missing_reports = max(0, count - len(known_reports))
    if known_reports:
        reported = {"status": "partial" if missing_reports else "reported", "amount": round(sum(known_reports), 12),
                    "currency": "USD", "missing_charge_calls": missing_reports, "request_count": count}
    else:
        reported = {"status": "unavailable", "amount": None, "currency": "USD",
                    "missing_charge_calls": count, "request_count": count}
    return {"reported_cost": reported, "estimated_cost": estimated}


def _history(rng: random.Random, steps: int):
    messages, usage_records, trace = [], [], []
    for index in range(steps):
        kind = rng.random()
        if kind < 0.35:
            messages.append({"role": rng.choice(["assistant", "tool"]),
                             "content": "ünïcode " * rng.randint(0, 40) + str(index)})
        if kind < 0.6:
            billing = {}
            if rng.random() < 0.8:
                billing["estimated_cost"] = {"status": rng.choice(["estimated", "unavailable"]),
                                             "amount": rng.random() * 10 ** rng.randint(-7, 3)}
            if rng.random() < 0.5:
                billing["reported_cost"] = {"status": rng.choice(["reported", "partial"]),
                                            "amount": rng.random() * 10 ** rng.randint(-6, 2)}
            usage = {"prompt_tokens": rng.randint(0, 900), "completion_tokens": rng.randint(0, 90),
                     "observed_model": "scripted-1", "flag": True}
            if billing or rng.random() < 0.5:
                usage["billing"] = billing
            usage_records.append(usage)
            trace.append({"type": "model", "status": rng.choice(["ok", "budget_stopped", "error"])})
        else:
            trace.append({"type": "tool", "status": "ok"})
    return messages, usage_records, trace


class SelectedPointTallyTests(unittest.TestCase):
    def test_every_prefix_matches_the_from_scratch_values(self):
        budgets = SimpleNamespace(max_model_calls=30, max_context_bytes=131072, tool_output_limit_bytes=16384,
                                  attempt_deadline_seconds=600)
        for seed in range(5):
            rng = random.Random(seed)
            messages, usage_records, trace = _history(rng, 120)
            tally = _SelectedPointTally()
            for end in range(0, len(messages) + 1, 3):
                current_messages = messages[:end]
                current_usage = usage_records[:min(len(usage_records), end)]
                current_trace = trace[:min(len(trace), end)]
                expected = _reference_state(current_messages, end, budgets=budgets,
                                            usage_records=current_usage, trace=current_trace)
                actual = tally.state(current_messages, end, budgets=budgets,
                                     usage_records=current_usage, trace=current_trace)
                self.assertEqual(actual["usage_totals"], expected["usage_totals"])
                self.assertEqual(actual["context_bytes"], expected["context_bytes"])
                self.assertEqual(actual["tool_result_messages"], expected["tool_result_messages"])
                self.assertEqual(actual["estimated_cost"], expected["estimated_cost"])
                self.assertEqual(actual["reported_cost"], expected["reported_cost"])


if __name__ == "__main__":
    unittest.main()

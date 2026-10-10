import unittest

from agent_eval_harness.report import render_attempt_report


class AttemptCostReportTests(unittest.TestCase):
    def test_report_distinguishes_provider_charges_estimates_and_budget_reservations(self):
        html = render_attempt_report({
            "termination_reason": "agent_completed",
            "functional_verdict": "success",
            "duration_seconds": 3.0,
            "trace": [],
            "candidate": {"status": "collected", "patch": ""},
            "evaluation": {"status": "completed", "checks": {"repair": True}},
            "metadata": {
                "cost": {
                    "reported": {"status": "unavailable", "amount": None, "currency": "USD"},
                    "estimated": {"status": "partial", "amount": 0.00002172,
                                   "currency": "USD", "missing_usage_calls": 1},
                },
                "spend_budget": {
                    "name": "attempt", "limit_usd": 0.30,
                    "reserved_or_estimated_usd": 0.04, "remaining_usd": 0.26,
                    "status": "within_limit",
                },
            },
        })

        self.assertIn("Reported charge", html)
        self.assertIn("unavailable", html)
        self.assertIn("Estimated cost", html)
        self.assertIn("partial", html)
        self.assertIn("0.00002172 USD", html)
        self.assertIn("USD spending ceiling", html)
        self.assertIn("0.04 USD reserved or estimated", html)


if __name__ == "__main__":
    unittest.main()

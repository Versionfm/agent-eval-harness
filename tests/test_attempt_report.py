import unittest

from agent_eval_harness.report import render_attempt_report


class SingleAttemptReportTests(unittest.TestCase):
    def test_long_context_is_collapsed_and_missing_durations_have_no_unit(self):
        rendered = render_attempt_report({
            "functional_verdict": "failure",
            "termination_reason": "model_call_budget",
            "duration_seconds": None,
            "initial_context": [{"role": "system", "content": "Long prompt context."}],
            "trace": [
                {"event_id": 1, "type": "model", "status": "timeout"},
                {
                    "event_id": 2,
                    "type": "tool",
                    "tool_name": "run_shell",
                    "status": "error",
                    "result": {"status": "error", "output": "command failed"},
                },
            ],
            "candidate": {"status": "collected", "patch": ""},
            "evaluation": {"status": "completed", "checks": {"repair": False}},
            "metadata": {},
        })

        self.assertIn('<details class="initial-context">', rendered)
        self.assertNotIn('<details class="initial-context" open>', rendered)
        self.assertIn("Long prompt context.", rendered)
        self.assertIn("<dt>Duration</dt><dd>Unavailable</dd>", rendered)
        self.assertIn("<dt>Attempt duration</dt><dd>Unavailable</dd>", rendered)
        self.assertEqual(rendered.count("<small>Unavailable</small>"), 2)
        self.assertNotIn("Unavailable s</small>", rendered)


if __name__ == "__main__":
    unittest.main()

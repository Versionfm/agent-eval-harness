import unittest

from agent_eval_harness.admission import assess_admission


CHECK_IDS = (
    "title_retrieval",
    "title_context",
    "body_relevance",
    "case_normalization",
    "top_k_limit",
    "input_immutable",
    "full_context_bypass",
    "history_mode",
    "input_order_independence",
)
TITLE_RELEVANCE_FAILURES = (
    "title_retrieval",
    "title_context",
    "input_order_independence",
)


def variant(*failed_checks):
    return {
        "status": "completed",
        "checks": {check_id: check_id not in failed_checks for check_id in CHECK_IDS},
    }


class AdmissionOutcomeTests(unittest.TestCase):
    def test_admits_baseline_defect_and_repair_evidence_with_expected_behavior(self):
        runs = {
            "baseline": variant(),
            "defect": variant(*TITLE_RELEVANCE_FAILURES),
            "repair": variant(),
        }

        outcome = assess_admission(runs)

        self.assertEqual(outcome["status"], "admitted")
        self.assertEqual(
            outcome["defect_failed_checks"],
            ["title_retrieval", "title_context", "input_order_independence"],
        )

    def test_classifies_malformed_check_output_as_invalid_environment(self):
        runs = {
            "baseline": variant(),
            "defect": variant(*TITLE_RELEVANCE_FAILURES),
            "repair": variant(),
        }
        runs["baseline"]["checks"]["body_relevance"] = None

        outcome = assess_admission(runs)

        self.assertEqual(outcome["status"], "invalid_environment")
        self.assertEqual(outcome["invalid_runs"], ["baseline"])

    def test_rejects_a_mutant_that_breaks_behavior_outside_the_title_regression(self):
        runs = {
            "baseline": variant(),
            "defect": variant(*TITLE_RELEVANCE_FAILURES, "body_relevance"),
            "repair": variant(),
        }

        outcome = assess_admission(runs)

        self.assertEqual(outcome["status"], "rejected")
        self.assertIn("body_relevance", outcome["reasons"][0])

if __name__ == "__main__":
    unittest.main()

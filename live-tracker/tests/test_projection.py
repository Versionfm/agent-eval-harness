"""Final report and final results projected from the authoritative log (#14), offline.

The fixture is written through the public recorder, so every expected value below is a literal
written by the test, not something recomputed by the projection.
"""

import html
import json
import tempfile
import unittest
from pathlib import Path

from attempt_fixtures import CHECKS, PATCH, REASONING, RESPONSE, record_attempt
from live_tracker.projection import build_result, final_results, render_report
from live_tracker.recorder import FaultyStorage


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="live-projection-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "attempt"
        record_attempt(self.directory)

    def test_report_shows_the_response_reasoning_tool_arguments_and_outputs_recorded_in_the_log(self):
        report = html.unescape(render_report(self.directory))
        self.assertIn(RESPONSE, report)
        self.assertIn(REASONING, report)
        self.assertIn('"path": "app/source.py"', report)
        self.assertIn("LINE-B second line", report, "the full retained output is in the report")
        self.assertIn("Open output artifact", report)

    def test_accounting_comes_from_the_recorded_usage_and_selected_state_facts(self):
        report = render_report(self.directory)
        self.assertIn("input 51; output 10", report, "per-call usage summed from the responses")
        self.assertIn("estimated: 0.00100000 USD", report, "the last recorded state's estimate")
        self.assertIn("Reported charge", report)
        result = build_result(self.directory)
        self.assertEqual([call["prompt_tokens"] for call in result["metadata"]["usage_by_call"]], [11, 40])
        self.assertEqual(result["metadata"]["model_call_count"], 2)

    def test_recording_status_and_review_status_appear_in_the_report(self):
        report = render_report(self.directory)
        self.assertIn("Recording</dt><dd>complete", report)
        self.assertIn("Qualitative review pending", report)

    def test_final_results_come_from_the_finish_record_not_the_selected_point(self):
        final = final_results(self.directory)
        self.assertEqual(final["functional_verdict"], "failure")
        self.assertEqual(final["termination_reason"], "agent_completed")
        self.assertEqual(final["candidate"]["patch"], PATCH)
        self.assertEqual(final["checks"], CHECKS)
        self.assertEqual(final["recording"]["status"], "complete")
        self.assertEqual(final["review"]["status"], "pending")
        self.assertNotIn("usage_totals", json.dumps(final), "selected-point state is not a final fact")

    def test_codex_review_is_pending_until_review_json_completes_it(self):
        before = (self.directory / "events.jsonl").read_bytes()
        (self.directory / "review.json").write_text(json.dumps({
            "schema_version": "1", "status": "complete", "reviewer": "Codex root orchestrator",
            "reviewed_at": "2026-10-10T17:00:00+00:00",
        }), encoding="utf-8")
        self.assertEqual(final_results(self.directory)["review"]["status"], "completed")
        self.assertIn("Codex root orchestrator", render_report(self.directory))
        self.assertEqual((self.directory / "events.jsonl").read_bytes(), before, "the log is never rewritten")

    def test_an_incomplete_recording_reports_missing_final_facts_as_not_recorded(self):
        with tempfile.TemporaryDirectory(prefix="live-projection-") as temporary:
            directory = Path(temporary) / "attempt"
            record_attempt(directory, finish=False)
            final = final_results(directory)
            self.assertEqual(final["functional_verdict"], "not recorded")
            self.assertEqual(final["termination_reason"], "not recorded")
            self.assertEqual(final["recording"]["status"], "open")
            report = render_report(directory)
            self.assertIn("not recorded", report)
            self.assertIn("Recording</dt><dd>open", report)
            self.assertIn(RESPONSE, report, "the evidence that was recorded is still shown")

    def test_a_failed_mandatory_write_is_reported_as_a_recording_failure(self):
        with tempfile.TemporaryDirectory(prefix="live-projection-") as temporary:
            directory = Path(temporary) / "attempt"
            try:
                record_attempt(directory, finish=False, storage=FaultyStorage("log", "tool.outcome"))
            except Exception:
                pass  # the recorder refused the mandatory write, as designed
            self.assertEqual(final_results(directory)["recording"]["status"], "failed")
            self.assertIn("Recording</dt><dd>failed", render_report(directory))


if __name__ == "__main__":
    unittest.main()

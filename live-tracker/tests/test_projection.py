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
from live_tracker.recorder import AttemptRecorder, FaultyStorage


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


class RecordedFinalFactsTests(unittest.TestCase):
    """The final records the harness publishes are the only source for candidate and evaluation facts."""

    def _finished(self, directory: Path, finish_facts: dict) -> None:
        recorder = AttemptRecorder(directory, attempt_id="attempt-final")
        recorder.emit("attempt_started", {"task_id": "t1", "orchestrator": "python-loop"})
        recorder.emit("termination", {"reason": "agent_completed", "model_calls": 1})
        recorder.emit("patch_collection", {"status": "completed", "changed_files": ["app/source.py"],
                                           "change_count": 1})
        recorder.emit("evaluation", {"status": "completed", "failure_category": "acceptance_failed",
                                     "functional_verdict": "failure", "checks": CHECKS, "error": None})
        recorder.emit("attempt_finished", {
            "termination_reason": "agent_completed", "functional_verdict": "failure",
            "failure_category": "acceptance_failed", "changed_files": ["app/source.py"], "checks": CHECKS,
            **finish_facts,
        }, {"candidate.patch": PATCH.encode("utf-8")})

    def test_recorded_candidate_and_evaluation_facts_are_projected_as_recorded(self):
        with tempfile.TemporaryDirectory(prefix="live-projection-") as temporary:
            directory = Path(temporary) / "attempt"
            self._finished(directory, {"candidate_status": "collected", "evaluation_status": "completed",
                                       "evaluation_error": None, "evaluation_failure_category": "acceptance_failed"})
            result = build_result(directory)
            self.assertEqual(result["candidate"]["status"], "collected")
            self.assertEqual(result["evaluation"]["status"], "completed")
            self.assertIsNone(result["evaluation"]["error"])
            self.assertEqual(final_results(directory)["evaluation_status"], "completed")

    def test_a_recorded_evaluation_error_is_projected_as_recorded(self):
        with tempfile.TemporaryDirectory(prefix="live-projection-") as temporary:
            directory = Path(temporary) / "attempt"
            self._finished(directory, {"candidate_status": "unavailable", "evaluation_status": "invalid_patch",
                                       "evaluation_error": "bad patch", "evaluation_failure_category": "invalid_patch"})
            result = build_result(directory)
            self.assertEqual(result["candidate"]["status"], "unavailable")
            self.assertEqual(result["evaluation"]["status"], "invalid_patch")
            self.assertEqual(result["evaluation"]["error"], "bad patch")

    def test_facts_the_log_does_not_record_are_not_recorded_rather_than_invented(self):
        with tempfile.TemporaryDirectory(prefix="live-projection-") as temporary:
            directory = Path(temporary) / "attempt"
            self._finished(directory, {})
            result = build_result(directory)
            self.assertEqual(result["candidate"]["status"], "not recorded")
            self.assertEqual(result["evaluation"]["status"], "not recorded")
            self.assertEqual(result["evaluation"]["error"], "not recorded")
            self.assertEqual(final_results(directory)["evaluation_status"], "not recorded")

    def test_the_projected_trace_keeps_the_recorded_final_records_in_order(self):
        with tempfile.TemporaryDirectory(prefix="live-projection-") as temporary:
            directory = Path(temporary) / "attempt"
            self._finished(directory, {"candidate_status": "collected", "evaluation_status": "completed",
                                       "evaluation_error": None})
            trace = build_result(directory)["trace"]
            self.assertEqual([event["type"] for event in trace], ["termination", "patch_collection", "evaluation"])
            self.assertEqual([event["event_id"] for event in trace], [1, 2, 3])
            self.assertEqual(trace[1]["changed_files"], ["app/source.py"])


if __name__ == "__main__":
    unittest.main()

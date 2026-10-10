"""An observed attempt keeps one history: the log, plus the final files the harness writes (ADR 0005, #10 review).

The harness writes metadata.json, candidate.patch, candidate-files.json and checks.json beside the log.
The tracker's projection writes result.json, trace.jsonl and report.html from the log, and the
comparison loader still reads the directory without any change to its contract.
"""

import tempfile
import unittest
from pathlib import Path

from agent_eval_harness.reports.compare_report import _load_attempt, build_comparison_report
from agent_eval_harness.bench.artifacts import _collect_artifacts
from attempt_fixtures import CHECKS, PATCH, record_attempt
from live_tracker.projection import write_projection


FINAL_RESULT = {
    "trace": [],
    "candidate": {"status": "collected", "changed_files": ["app/source.py"], "files": [], "patch": PATCH},
    "evaluation": {"status": "completed", "checks": CHECKS, "messages": {}, "error": None},
    "metadata": {
        "schema_version": "1", "task_id": "t1", "task_version": "1", "source_revision": "r1",
        "acceptance_check_version": "1", "requested_model": "scripted-1", "provider": "scripted",
        "orchestrator": "python-loop", "started_at": "2026-10-10T17:00:00+00:00",
        "harness_revision": "rev", "dependency_versions": {}, "budgets": {}, "model_settings": {},
        "model_call_count": 2, "retry_count": 0, "usage_by_call": [], "observed_models": [],
        "cost": {"reported": {"status": "unavailable"}, "estimated": {"status": "unavailable"}},
        "qualitative_review": {"status": "pending"},
    },
    "termination_reason": "agent_completed",
    "functional_verdict": "failure",
    "failure_category": "acceptance_failed",
    "duration_seconds": 1.0,
}


class ObservedProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="live-observed-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def _observed(self, name: str) -> Path:
        directory = self.root / name
        record_attempt(directory)
        _collect_artifacts(FINAL_RESULT, directory, observed=True)
        return directory

    def test_the_harness_writes_only_final_files_beside_an_observed_log(self):
        directory = self._observed("python")
        names = sorted(path.name for path in directory.iterdir())
        self.assertEqual(names, ["artifacts", "candidate-files.json", "candidate.patch", "checks.json",
                                 "events.jsonl", "metadata.json"])

    def test_the_projection_writes_the_comparison_files_and_the_loader_reads_them(self):
        python = self._observed("python")
        langgraph = self._observed("langgraph")
        for directory in (python, langgraph):
            write_projection(directory)
        attempt = _load_attempt(python)
        self.assertEqual(attempt["functional_verdict"], "failure")
        self.assertEqual(attempt["candidate"]["patch"], PATCH)
        self.assertEqual([event["type"] for event in attempt["trace"]],
                         ["initial_context", "model", "tool", "model"])
        output = build_comparison_report(python, langgraph, self.root / "comparison.html")
        self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()

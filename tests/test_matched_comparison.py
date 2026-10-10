"""Offline contract checks for matched-run admission and provider preflight."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from agent_eval_harness.attempt import DEFAULT_TASK_PACKAGE
from agent_eval_harness.deepseek import HttpResponse
from agent_eval_harness.run_matched_comparison import run_matched_comparison


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


def write_inputs(root: Path, *, parity_passed: bool = True) -> tuple[Path, Path, Path, Path]:
    task_package = DEFAULT_TASK_PACKAGE
    manifest = json.loads((task_package / "manifest.json").read_text(encoding="utf-8"))
    admission_path = root / "admission.json"
    admission_path.write_text(json.dumps({
        "assessment": {"status": "admitted"},
        "source_revision": manifest["source"]["revision"],
        "environment_evidence": {
            "image_tag": "agent-eval-harness/test:1",
            "image_id": "sha256:fixture-image",
        },
    }), encoding="utf-8")
    parity_path = root / "parity.json"
    common = {
        "common_model_request_prefix_matches",
        "tool_actions_match",
        "canonical_checks_match",
        "both_canonical_evaluations_pass",
    }
    parity_path.write_text(json.dumps({
        "passed": parity_passed,
        "task_id": manifest["task_id"],
        "source_revision": manifest["source"]["revision"],
        "scenarios": {
            "correct": {"checks": {key: True for key in common | {
                "model_request_histories_match", "termination_matches",
                "model_call_count_matches", "termination_matches_scenario",
                "functional_verdict_matches",
            }}},
            "error-recovery-budget": {"checks": {key: True for key in common | {
                "model_request_histories_match", "termination_matches",
                "model_call_count_matches", "termination_matches_scenario",
                "functional_verdict_matches",
            }}},
            "graph-step-budget": {"checks": {key: True for key in common | {
                "graph_stops_on_its_node_budget", "python_loop_does_not_consume_graph_budget",
                "partial_graph_candidate_passes",
            }}},
        },
    }), encoding="utf-8")
    source = root / "source"
    source.mkdir()
    credential = root / "provider-key.txt"
    credential.write_text("fixture-key", encoding="utf-8")
    return admission_path, parity_path, source, credential


class MatchedComparisonPreflightTests(unittest.TestCase):
    def test_provider_preflight_failure_is_not_reported_as_an_agent_failure(self):
        with tempfile.TemporaryDirectory(prefix="matched-preflight-") as temporary:
            root = Path(temporary)
            admission, parity, source, credential = write_inputs(root)
            transport = FixtureTransport([
                HttpResponse(503, "temporary provider outage"),
                HttpResponse(503, "temporary provider outage"),
            ])

            result = run_matched_comparison(
                admission_evidence=admission,
                parity_evidence=parity,
                source_repository=source,
                credential_file=credential,
                artifact_directory=root / "artifacts",
                transport=transport,
            )

            artifacts = root / "artifacts"
            self.assertEqual(result["status"], "preflight_failed")
            self.assertFalse(result["valid_measurement"])
            self.assertEqual(result["agent_attempts"], "not_started")
            self.assertEqual(result["execution_mode"], "controlled_transport")
            self.assertFalse(result["live_measurement"])
            self.assertEqual(
                result["live_acceptance_status"],
                "pending_live_provider_run_and_human_review",
            )
            self.assertTrue((artifacts / "smoke" / "smoke.json").is_file())
            self.assertTrue((artifacts / "experiment.json").is_file())
            self.assertTrue((artifacts / "report.html").is_file())
            self.assertFalse((artifacts / "python-loop").exists())
            self.assertFalse((artifacts / "langgraph").exists())
            self.assertIn("No valid measurement", (artifacts / "report.html").read_text())
            self.assertIn(
                "no live provider inference occurred",
                (artifacts / "report.html").read_text(),
            )
            for path in artifacts.rglob("*"):
                if path.is_file():
                    self.assertNotIn(
                        "fixture-key",
                        path.read_text(encoding="utf-8", errors="replace"),
                    )
            self.assertEqual(len(transport.requests), 2)
            self.assertTrue(all(
                "fixture-key" not in request["headers"].values()
                for request in transport.requests
            ))

    def test_failed_scripted_parity_is_rejected_before_provider_preflight(self):
        with tempfile.TemporaryDirectory(prefix="matched-parity-gate-") as temporary:
            root = Path(temporary)
            admission, parity, source, credential = write_inputs(root, parity_passed=False)
            transport = FixtureTransport([])

            with self.assertRaisesRegex(ValueError, "scripted parity evidence"):
                run_matched_comparison(
                    admission_evidence=admission,
                    parity_evidence=parity,
                    source_repository=source,
                    credential_file=credential,
                    artifact_directory=root / "artifacts",
                    transport=transport,
                )

            self.assertEqual(transport.requests, [])
            self.assertFalse((root / "artifacts").exists())


if __name__ == "__main__":
    unittest.main()

"""Offline contract checks for matched-run admission and provider preflight."""

from __future__ import annotations

import json
import platform
from pathlib import Path
import tempfile
import unittest

from agent_eval_harness.bench.admission import task_package_evidence
from agent_eval_harness.bench.attempt import (
    DEFAULT_TASK_PACKAGE,
    _dependency_versions,
    _harness_provenance,
)
from agent_eval_harness.harness.deepseek import HttpResponse
from agent_eval_harness.cli.run_matched_comparison import (
    _attempt_is_measurement,
    _configuration_matches,
    run_matched_comparison,
)


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
    fingerprint = task_package_evidence(task_package, manifest)
    admission_path = root / "admission.json"
    admission_path.write_text(json.dumps({
        "assessment": {"status": "admitted"},
        "source_revision": manifest["source"]["revision"],
        "task_package": fingerprint,
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
        "harness_provenance_matches",
    }
    provenance = {
        "harness_revision": _harness_provenance(),
        "dependency_versions": _dependency_versions(),
    }
    scenarios = {
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
    }
    parity_path.write_text(json.dumps({
        "passed": parity_passed,
        "task_id": manifest["task_id"],
        "task_version": manifest["task_version"],
        "source_revision": manifest["source"]["revision"],
        "acceptance_check_version": manifest["acceptance_check_version"],
        "task_identity": fingerprint["identity"],
        "task_package_sha256": fingerprint["sha256"],
        "scenarios": scenarios,
        "attempt_provenance": {
            scenario: {"python-loop": provenance, "langgraph": provenance}
            for scenario in scenarios
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

    def test_stale_task_fingerprint_or_check_version_is_rejected_before_provider_calls(self):
        for field, replacement in (
            ("task_version", "stale-task-version"),
            ("acceptance_check_version", "stale-check-version"),
            ("task_package_sha256", "0" * 64),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory(
                prefix="matched-parity-fingerprint-"
            ) as temporary:
                root = Path(temporary)
                admission, parity, source, credential = write_inputs(root)
                evidence = json.loads(parity.read_text(encoding="utf-8"))
                evidence[field] = replacement
                parity.write_text(json.dumps(evidence), encoding="utf-8")
                transport = FixtureTransport([])

                with self.assertRaisesRegex(ValueError, "task fingerprint or check version"):
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

    def test_stale_parity_dependency_and_harness_provenance_rejected_before_provider_calls(self):
        for field, replacement in (
            ("dependency_versions", {}),
            ("harness_revision", {"commit": "stale", "working_tree": "clean",
                                  "working_tree_sha256": None}),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory(
                prefix="matched-parity-provenance-"
            ) as temporary:
                root = Path(temporary)
                admission, parity, source, credential = write_inputs(root)
                evidence = json.loads(parity.read_text(encoding="utf-8"))
                evidence["attempt_provenance"]["correct"]["python-loop"][field] = replacement
                parity.write_text(json.dumps(evidence), encoding="utf-8")
                transport = FixtureTransport([])

                with self.assertRaisesRegex(ValueError, "provenance"):
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

    def test_parity_rejects_dependency_versions_missing_from_both_orchestrators(self):
        with tempfile.TemporaryDirectory(prefix="matched-parity-missing-deps-") as temporary:
            root = Path(temporary)
            admission, parity, source, credential = write_inputs(root)
            evidence = json.loads(parity.read_text(encoding="utf-8"))
            for orchestrators in evidence["attempt_provenance"].values():
                for provenance in orchestrators.values():
                    provenance["dependency_versions"] = {}
            parity.write_text(json.dumps(evidence), encoding="utf-8")
            transport = FixtureTransport([])

            with self.assertRaisesRegex(ValueError, "dependency provenance"):
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

    def test_parity_rejects_differing_orchestrator_dependency_versions(self):
        with tempfile.TemporaryDirectory(prefix="matched-parity-differing-deps-") as temporary:
            root = Path(temporary)
            admission, parity, source, credential = write_inputs(root)
            evidence = json.loads(parity.read_text(encoding="utf-8"))
            evidence["attempt_provenance"]["correct"]["langgraph"]["dependency_versions"] = {
                "langgraph": "different"
            }
            parity.write_text(json.dumps(evidence), encoding="utf-8")
            transport = FixtureTransport([])

            with self.assertRaisesRegex(ValueError, "dependency provenance"):
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


class MatchedMeasurementClassificationTests(unittest.TestCase):
    def test_functional_invalid_patch_is_a_measured_candidate_failure(self):
        measured, reason = _attempt_is_measurement({
            "termination_reason": "agent_completed",
            "functional_verdict": "failure",
            "failure_category": "invalid_patch",
            "evaluation": {"status": "invalid_patch"},
        })
        self.assertTrue(measured)
        self.assertIsNone(reason)

    def test_unclassified_invalid_patch_remains_an_invalid_measurement(self):
        measured, reason = _attempt_is_measurement({
            "termination_reason": "agent_completed",
            "functional_verdict": "invalid_environment",
            "failure_category": "evaluator_error",
            "evaluation": {"status": "invalid_patch"},
        })
        self.assertFalse(measured)
        self.assertEqual(reason, "attempt_environment_invalid")

    def test_missing_or_differing_dependency_versions_prevent_matched_measurement(self):
        metadata = {
            "task_id": "task",
            "task_version": "1",
            "task_identity": {"task_id": "task", "task_version": "1"},
            "task_package_sha256": "c" * 64,
            "source_revision": "revision",
            "acceptance_check_version": "checks-1",
            "provider": "provider",
            "requested_model": "model",
            "provider_endpoint": "https://provider.invalid",
            "model_settings": {"effort": "low"},
            "dependency_versions": {"langgraph": "1.0"},
            "harness_revision": {"commit": "abc", "working_tree": "clean",
                                 "working_tree_sha256": None},
            "budgets": {"max_calls": 4},
            "pricing_source_url": "https://provider.invalid/pricing",
            "pricing_source_checked_at": "2026-10-10",
            "initial_context_sha256": "a" * 64,
            "observed_models": ["model"],
            "task_image_evidence": {"dockerfile_sha256": "b" * 64, "runtime_version": "3.12"},
        }
        python_result = {"metadata": json.loads(json.dumps(metadata))}
        graph_result = {"metadata": json.loads(json.dumps(metadata))}
        self.assertTrue(_configuration_matches(python_result, graph_result)[0])

        graph_result["metadata"]["task_package_sha256"] = "0" * 64
        matched, mismatches = _configuration_matches(python_result, graph_result)
        self.assertFalse(matched)
        self.assertIn("task package fingerprint", mismatches)
        graph_result["metadata"]["task_package_sha256"] = "c" * 64

        python_result["metadata"]["dependency_versions"] = {}
        graph_result["metadata"]["dependency_versions"] = {}
        matched, mismatches = _configuration_matches(python_result, graph_result)
        self.assertFalse(matched)
        self.assertIn("dependency versions", mismatches)
        python_result["metadata"]["dependency_versions"] = {"langgraph": "1.0"}
        graph_result["metadata"]["dependency_versions"] = {"langgraph": "2.0"}
        matched, mismatches = _configuration_matches(python_result, graph_result)
        self.assertFalse(matched)
        self.assertIn("dependency versions", mismatches)

    def test_dependency_provenance_includes_outer_python_and_langgraph(self):
        versions = _dependency_versions()
        self.assertEqual(versions["python-runtime"], platform.python_version())
        self.assertTrue(versions["langgraph"])


if __name__ == "__main__":
    unittest.main()

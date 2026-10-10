import unittest
import json
from pathlib import Path
import shutil
import tempfile

from agent_eval_harness.admission import assess_admission, task_package_evidence
from agent_eval_harness.attempt import AdmittedTask


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


class AdmissionIdentityTests(unittest.TestCase):
    def _prepare(self, root: Path):
        source_package = Path(__file__).resolve().parents[1] / "tasks" / "ml_tutor_retrieval"
        package = root / "task"
        shutil.copytree(source_package, package)
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        evidence = {
            "assessment": {"status": "admitted"},
            "source_revision": manifest["source"]["revision"],
            "task_package": task_package_evidence(package, manifest),
            "environment_evidence": {
                "image_tag": "agent-eval/test:task",
                "image_id": "sha256:prepared-image",
            },
        }
        evidence_path = root / "admission.json"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        return package, evidence_path, evidence

    def test_admission_rejects_changed_task_identity_before_attempt(self):
        with tempfile.TemporaryDirectory(prefix="admission-identity-") as temporary:
            root = Path(temporary)
            package, evidence_path, _ = self._prepare(root)
            manifest_path = package / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["task_id"] = "unadmitted-task"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "identity and package contents"):
                AdmittedTask.from_evidence(
                    evidence_path, source_repository=root, task_package=package
                )

    def test_admission_rejects_changed_check_content_before_attempt(self):
        with tempfile.TemporaryDirectory(prefix="admission-content-") as temporary:
            root = Path(temporary)
            package, evidence_path, _ = self._prepare(root)
            checks = package / "curator" / "checks.py"
            checks.write_text(checks.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "identity and package contents"):
                AdmittedTask.from_evidence(
                    evidence_path, source_repository=root, task_package=package
                )

if __name__ == "__main__":
    unittest.main()

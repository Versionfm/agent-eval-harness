"""Evaluator setup and candidate execution failures stay in distinct categories."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from agent_eval_harness.attempt import _evaluate_candidate_changes
from agent_eval_harness.environment import (
    CommandTimeout,
    EnvironmentFailure,
    run_canonical_checks,
)


TASK_PACKAGE = Path(__file__).resolve().parents[1] / "tasks" / "ml_tutor_retrieval"


class EvaluatorFailureClassificationTests(unittest.TestCase):
    def test_worker_start_timeout_is_an_environment_error(self):
        with patch(
            "agent_eval_harness.environment.DockerTaskContainer.start",
            side_effect=CommandTimeout(
                "docker start timed out", timeout_seconds=1
            ),
        ) as start, patch(
            "agent_eval_harness.environment.DockerTaskContainer.exec"
        ) as execute:
            result = run_canonical_checks(
                "fixture-image",
                TASK_PACKAGE,
                TASK_PACKAGE / "curator",
                "3.12.13",
                timeout_seconds=1,
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["checks"], {})
        self.assertIn("could not start", result["error"])
        start.assert_called_once()
        execute.assert_not_called()

    def test_worker_execution_timeout_is_a_candidate_repair_failure(self):
        with patch(
            "agent_eval_harness.environment.DockerTaskContainer.start"
        ) as start, patch(
            "agent_eval_harness.environment.DockerTaskContainer.exec",
            side_effect=CommandTimeout(
                "candidate probe timed out", stdout="partial output",
                timeout_seconds=2,
            ),
        ) as execute:
            result = run_canonical_checks(
                "fixture-image",
                TASK_PACKAGE,
                TASK_PACKAGE / "curator",
                "3.12.13",
                timeout_seconds=2,
            )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["candidate_execution_error"])
        self.assertTrue(all(value is False for value in result["checks"].values()))
        self.assertEqual(result["candidate_worker_stdout"], "partial output")
        start.assert_called_once()
        execute.assert_called_once()

    def test_unsafe_collected_candidate_path_is_invalid_patch(self):
        with tempfile.TemporaryDirectory(prefix="candidate-patch-invalid-") as temporary:
            defect = Path(temporary) / "defect"
            defect.mkdir()
            (defect / "source.py").write_text("def retrieve(): pass\n", encoding="utf-8")

            result = _evaluate_candidate_changes(
                defect,
                [{"path": "../escape.py", "action": "add", "content_base64": ""}],
                image_id="fixture-image",
                admitted_task=SimpleNamespace(
                    evaluator_directory=TASK_PACKAGE / "curator",
                    runtime_version="3.12.13",
                ),
                timeout_seconds=1,
            )

        self.assertEqual(result["status"], "invalid_patch")
        self.assertIn("Invalid candidate path", result["error"])

    def test_canonical_runner_environment_exception_is_not_invalid_patch(self):
        with tempfile.TemporaryDirectory(prefix="candidate-evaluator-error-") as temporary:
            defect = Path(temporary) / "defect"
            defect.mkdir()
            (defect / "source.py").write_text("def retrieve(): pass\n", encoding="utf-8")
            with patch(
                "agent_eval_harness.attempt.run_canonical_checks",
                side_effect=EnvironmentFailure("Docker evaluator unavailable"),
            ):
                result = _evaluate_candidate_changes(
                    defect,
                    [],
                    image_id="fixture-image",
                    admitted_task=SimpleNamespace(
                        evaluator_directory=TASK_PACKAGE / "curator",
                        runtime_version="3.12.13",
                    ),
                    timeout_seconds=1,
                )

        self.assertEqual(result["status"], "error")
        self.assertIn("Docker evaluator unavailable", result["error"])


if __name__ == "__main__":
    unittest.main()

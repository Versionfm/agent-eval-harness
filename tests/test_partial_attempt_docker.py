"""Docker-backed scenarios for failure, recovery, and partial-attempt evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from dataclasses import replace

from agent_eval_harness.attempt import (
    AdmittedTask,
    AttemptBudgets,
    ModelConfig,
    ModelResponse,
    ScriptedModel,
    ToolCall,
    attempt_and_evaluate,
)
from agent_eval_harness.model import RetryableProviderError


DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
SOURCE_REPOSITORY = Path(os.environ.get(
    "ML_TUTOR_REPOSITORY", "/home/francisco/prompt-engineering-group-project"
))
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for Docker scenarios",
)
class PartialAttemptDockerTests(unittest.TestCase):
    def setUp(self):
        self.task = AdmittedTask.from_evidence(
            Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY
        )

    def test_tool_error_can_recover_and_budget_stop_still_evaluates_complete_patch(self):
        repair = json.loads(
            (REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json").read_text()
        )
        model = ScriptedModel([
            ModelResponse(tool_calls=(ToolCall("apply_patch", {
                "path": repair["path"], "old_text": "no such text", "new_text": "wrong"
            }, "failed-patch"),)),
            ModelResponse(tool_calls=(
                ToolCall("apply_patch", {
                    "path": repair["path"], "old_text": repair["before"],
                    "new_text": repair["after"],
                }, "repair"),
                ToolCall("apply_patch", {
                    "path": "notes/recovered-after-error.txt",
                    "content": "A new file survives the model-call budget stop.\n",
                }, "add-recovery-note"),
                ToolCall("run_shell", {
                    "command": "python -c 'print(\"<script>\" + \"x\" * 512)'"
                }, "large-output"),
            )),
        ])

        with tempfile.TemporaryDirectory(prefix="partial-recovery-") as temporary:
            artifacts = Path(temporary) / "attempt"
            result = attempt_and_evaluate(
                admitted_task=self.task,
                model=model,
                model_config=ModelConfig(provider="scripted", requested_model="recovery-fixture"),
                budgets=AttemptBudgets(
                    max_model_calls=2, shell_timeout_seconds=10, tool_output_limit_bytes=128
                ),
                artifact_directory=artifacts,
            )

            tools = [event for event in result["trace"] if event["type"] == "tool"]
            self.assertEqual(result["termination_reason"], "model_call_budget")
            self.assertEqual(result["functional_verdict"], "success")
            self.assertEqual([event["tool_name"] for event in tools], [
                "apply_patch", "apply_patch", "apply_patch", "run_shell"
            ])
            self.assertEqual(tools[0]["status"], "error")
            self.assertEqual(tools[0]["result"]["error_category"], "patch_rejected")
            self.assertEqual(tools[1]["status"], "ok")
            self.assertEqual(tools[2]["status"], "ok")
            self.assertTrue(tools[3]["model_visible_result"]["truncated"])
            self.assertIn("output truncated", tools[3]["model_visible_result"]["output"])
            self.assertEqual(len(tools[3]["result"]["output"]), 521)
            self.assertEqual(tools[3]["result"]["output_artifact"], "tool-results/event-0007.txt")
            self.assertEqual(
                (artifacts / tools[3]["result"]["output_artifact"]).read_text(),
                tools[3]["result"]["output"],
            )
            self.assertEqual(result["metadata"]["model_call_count"], 2)
            self.assertTrue(all(result["evaluation"]["checks"].values()))
            self.assertIn("notes/recovered-after-error.txt", result["candidate"]["changed_files"])
            report = (artifacts / "report.html").read_text()
            self.assertIn("success", report)
            self.assertIn("&lt;script&gt;", report)
            self.assertNotIn("<script>", report)
            self.assertIn("Model-visible output was truncated", report)
            self.assertIn("Cost unavailable", report)
            self.assertIn("Qualitative review pending", report)
            self.assertTrue((artifacts / "trace.jsonl").is_file())

    def test_command_timeout_is_a_tool_error_the_agent_can_recover_from(self):
        repair = json.loads(
            (REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json").read_text()
        )
        model = ScriptedModel([
            ModelResponse(tool_calls=(ToolCall("run_shell", {
                "command": "python -c 'import time; print(\"before-timeout\", flush=True); time.sleep(3)'"
            }, "slow-shell"),)),
            ModelResponse(tool_calls=(ToolCall("apply_patch", {
                "path": repair["path"], "old_text": repair["before"],
                "new_text": repair["after"],
            }, "recover-after-timeout"),)),
            ModelResponse(content="The repair is complete."),
        ])

        with tempfile.TemporaryDirectory(prefix="timeout-recovery-") as temporary:
            result = attempt_and_evaluate(
                admitted_task=self.task,
                model=model,
                model_config=ModelConfig(provider="scripted", requested_model="timeout-fixture"),
                budgets=AttemptBudgets(
                    max_model_calls=3, shell_timeout_seconds=1, tool_output_limit_bytes=4096
                ),
                artifact_directory=Path(temporary) / "attempt",
            )

        tools = [event for event in result["trace"] if event["type"] == "tool"]
        self.assertEqual(tools[0]["status"], "error")
        self.assertEqual(tools[0]["result"]["error_category"], "command_timeout")
        self.assertIn("before-timeout", tools[0]["result"]["output"])
        self.assertEqual(tools[1]["status"], "ok")
        self.assertEqual(result["termination_reason"], "agent_completed")
        self.assertEqual(result["functional_verdict"], "success")

    def test_context_budget_stops_before_request_and_keeps_an_evaluable_attempt(self):
        model = ScriptedModel([ModelResponse(content="This response must not be requested.")])

        with tempfile.TemporaryDirectory(prefix="context-exhaustion-") as temporary:
            result = attempt_and_evaluate(
                admitted_task=self.task,
                model=model,
                model_config=ModelConfig(provider="scripted", requested_model="context-fixture"),
                budgets=AttemptBudgets(max_model_calls=2, max_context_bytes=100),
                artifact_directory=Path(temporary) / "attempt",
            )

        self.assertEqual(result["termination_reason"], "context_budget")
        self.assertEqual(model.requests, [])
        self.assertGreater(result["metadata"]["context_bytes_at_stop"], 100)
        self.assertEqual(result["functional_verdict"], "failure")
        self.assertEqual(result["failure_category"], "canonical_check_failure")
        self.assertEqual(result["evaluation"]["status"], "completed")
        self.assertFalse(result["evaluation"]["checks"]["title_retrieval"])

    def test_attempt_deadline_bounds_a_blocking_model_request_and_keeps_partial_result(self):
        class BlockingProvider:
            def __init__(self):
                self.requests = []

            def complete(self, request):
                self.requests.append(request)
                time.sleep(10)
                return ModelResponse(content="Too late")

        model = BlockingProvider()

        with tempfile.TemporaryDirectory(prefix="deadline-exhaustion-") as temporary:
            result = attempt_and_evaluate(
                admitted_task=self.task,
                model=model,
                model_config=ModelConfig(provider="controlled", requested_model="blocking-fixture"),
                budgets=AttemptBudgets(
                    max_model_calls=2, attempt_deadline_seconds=6,
                    cleanup_timeout_seconds=1, evaluation_timeout_seconds=15,
                ),
                artifact_directory=Path(temporary) / "attempt",
            )

        self.assertEqual(result["termination_reason"], "attempt_deadline")
        self.assertEqual(len(model.requests), 1)
        self.assertLess(result["metadata"]["attempt_duration_seconds"], 8)
        self.assertEqual(result["evaluation"]["status"], "completed")
        self.assertEqual(result["functional_verdict"], "failure")
        timed_out = [event for event in result["trace"] if event.get("type") == "model"]
        self.assertEqual(timed_out[-1]["status"], "timeout")

    def test_transient_provider_retry_counts_as_a_request_and_is_visible(self):
        repair = json.loads(
            (REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json").read_text()
        )

        class TransientThenRepair:
            def __init__(self):
                self.requests = []
                self.calls = 0

            def complete(self, request):
                self.requests.append(request)
                self.calls += 1
                if self.calls == 1:
                    raise RetryableProviderError("controlled temporary provider failure")
                if self.calls == 2:
                    return ModelResponse(tool_calls=(ToolCall("apply_patch", {
                        "path": repair["path"], "old_text": repair["before"],
                        "new_text": repair["after"],
                    }, "repair-after-retry"),))
                return ModelResponse(content="The repair is complete.")

        model = TransientThenRepair()
        with tempfile.TemporaryDirectory(prefix="provider-retry-") as temporary:
            result = attempt_and_evaluate(
                admitted_task=self.task,
                model=model,
                model_config=ModelConfig(provider="controlled", requested_model="retry-fixture"),
                budgets=AttemptBudgets(
                    max_model_calls=3, max_provider_retries=1,
                    provider_retry_delay_seconds=0.05,
                ),
                artifact_directory=Path(temporary) / "attempt",
            )

        model_events = [event for event in result["trace"] if event["type"] == "model"]
        self.assertEqual(result["termination_reason"], "agent_completed")
        self.assertEqual(result["functional_verdict"], "success")
        self.assertEqual(result["metadata"]["model_call_count"], 3)
        self.assertEqual(result["metadata"]["retry_count"], 1)
        self.assertEqual(model_events[0]["status"], "error")
        self.assertTrue(model_events[0]["retrying"])
        self.assertEqual([event["model_call"] for event in model_events], [1, 2, 3])

    def test_unrecoverable_provider_failure_keeps_and_evaluates_prior_patch(self):
        repair = json.loads(
            (REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json").read_text()
        )

        class RepairThenProviderFailure:
            def __init__(self):
                self.calls = 0

            def complete(self, request):
                self.calls += 1
                if self.calls == 1:
                    return ModelResponse(tool_calls=(ToolCall("apply_patch", {
                        "path": repair["path"], "old_text": repair["before"],
                        "new_text": repair["after"],
                    }, "repair-before-failure"),))
                raise RuntimeError("controlled unrecoverable provider failure")

        with tempfile.TemporaryDirectory(prefix="provider-failure-") as temporary:
            result = attempt_and_evaluate(
                admitted_task=self.task,
                model=RepairThenProviderFailure(),
                model_config=ModelConfig(provider="controlled", requested_model="failure-fixture"),
                budgets=AttemptBudgets(max_model_calls=3),
                artifact_directory=Path(temporary) / "attempt",
            )

        self.assertEqual(result["termination_reason"], "provider_error")
        self.assertEqual(result["functional_verdict"], "success")
        self.assertEqual(result["candidate"]["changed_files"], [repair["path"]])
        failed_call = [event for event in result["trace"] if event.get("type") == "model"][-1]
        self.assertEqual(failed_call["error_category"], "provider_error")
        self.assertFalse(failed_call["retrying"])

    def test_attempt_deadline_bounds_blocking_shell_and_container_cleanup(self):
        model = ScriptedModel([ModelResponse(tool_calls=(ToolCall("run_shell", {
            "command": "python -c 'import time; time.sleep(30)'"
        }, "blocking-shell"),))])

        with tempfile.TemporaryDirectory(prefix="shell-deadline-") as temporary:
            result = attempt_and_evaluate(
                admitted_task=self.task,
                model=model,
                model_config=ModelConfig(provider="scripted", requested_model="shell-deadline"),
                budgets=AttemptBudgets(
                    max_model_calls=2, shell_timeout_seconds=60,
                    attempt_deadline_seconds=6, cleanup_timeout_seconds=1,
                    evaluation_timeout_seconds=15,
                ),
                artifact_directory=Path(temporary) / "attempt",
            )

        tool = next(event for event in result["trace"] if event.get("type") == "tool")
        self.assertEqual(result["termination_reason"], "attempt_deadline")
        self.assertEqual(tool["result"]["error_category"], "attempt_deadline")
        self.assertLess(result["metadata"]["attempt_duration_seconds"], 8)
        self.assertEqual(result["evaluation"]["status"], "completed")

    def test_interruption_keeps_a_patch_made_before_the_provider_stopped(self):
        repair = json.loads(
            (REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json").read_text()
        )

        class InterruptedAfterRepair:
            def __init__(self):
                self.calls = 0

            def complete(self, request):
                self.calls += 1
                if self.calls == 1:
                    return ModelResponse(tool_calls=(ToolCall("apply_patch", {
                        "path": repair["path"], "old_text": repair["before"],
                        "new_text": repair["after"],
                    }, "repair-before-interruption"),))
                raise KeyboardInterrupt()

        with tempfile.TemporaryDirectory(prefix="interrupted-attempt-") as temporary:
            artifacts = Path(temporary) / "attempt"
            try:
                result = attempt_and_evaluate(
                    admitted_task=self.task,
                    model=InterruptedAfterRepair(),
                    model_config=ModelConfig(
                        provider="controlled", requested_model="interrupt-fixture"
                    ),
                    budgets=AttemptBudgets(max_model_calls=3),
                    artifact_directory=artifacts,
                )
            except KeyboardInterrupt:
                self.fail("the attempt API propagated interruption instead of retaining artifacts")
            self.assertTrue((artifacts / "trace.jsonl").is_file())
            self.assertTrue((artifacts / "candidate.patch").is_file())

        self.assertEqual(result["termination_reason"], "interrupted")
        self.assertEqual(result["functional_verdict"], "success")
        self.assertEqual(result["candidate"]["status"], "collected")

    def test_invalid_patch_and_evaluator_environment_failure_have_distinct_verdicts(self):
        symlink_model = ScriptedModel([
            ModelResponse(tool_calls=(ToolCall("run_shell", {
                "command": "ln -s /etc/passwd unsafe-link"
            }, "create-unsafe-link"),)),
            ModelResponse(content="Done."),
        ])
        missing_evaluator = replace(
            self.task, evaluator_directory=Path("/tmp/agent-eval-missing-evaluator")
        )

        with tempfile.TemporaryDirectory(prefix="failure-classification-") as temporary:
            invalid_patch = attempt_and_evaluate(
                admitted_task=self.task,
                model=symlink_model,
                model_config=ModelConfig(provider="scripted", requested_model="symlink-fixture"),
                budgets=AttemptBudgets(max_model_calls=3),
                artifact_directory=Path(temporary) / "invalid-patch",
            )
            environment_error = attempt_and_evaluate(
                admitted_task=missing_evaluator,
                model=ScriptedModel([ModelResponse(content="No changes." )]),
                model_config=ModelConfig(provider="scripted", requested_model="env-fixture"),
                budgets=AttemptBudgets(max_model_calls=2),
                artifact_directory=Path(temporary) / "environment-error",
            )

        self.assertEqual(invalid_patch["termination_reason"], "agent_completed")
        self.assertEqual(invalid_patch["functional_verdict"], "failure")
        self.assertEqual(invalid_patch["failure_category"], "invalid_patch")
        self.assertEqual(invalid_patch["candidate"]["status"], "unavailable")
        self.assertEqual(environment_error["functional_verdict"], "invalid_environment")
        self.assertEqual(environment_error["failure_category"], "evaluation_environment_error")
        self.assertEqual(environment_error["evaluation"]["status"], "error")

    def test_harness_setup_failure_is_distinct_and_marks_candidate_unavailable(self):
        unavailable_source = replace(
            self.task, source_repository=Path("/tmp/agent-eval-missing-source")
        )
        model = ScriptedModel([ModelResponse(content="This request must not run.")])

        with tempfile.TemporaryDirectory(prefix="harness-failure-") as temporary:
            result = attempt_and_evaluate(
                admitted_task=unavailable_source,
                model=model,
                model_config=ModelConfig(provider="scripted", requested_model="setup-fixture"),
                budgets=AttemptBudgets(max_model_calls=2),
                artifact_directory=Path(temporary) / "attempt",
            )

        self.assertEqual(result["termination_reason"], "harness_error")
        self.assertEqual(result["functional_verdict"], "invalid_environment")
        self.assertEqual(result["failure_category"], "harness_environment_failure")
        self.assertEqual(result["candidate"]["status"], "unavailable")
        self.assertEqual(model.requests, [])


if __name__ == "__main__":
    unittest.main()

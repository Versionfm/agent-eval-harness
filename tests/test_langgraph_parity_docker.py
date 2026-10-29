"""Docker-backed scripted parity checks for the explicit loop and LangGraph."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from agent_eval_harness.bench.attempt import (
    DEFAULT_SOURCE_REPOSITORY,
    AdmittedTask,
    AttemptBudgets,
    attempt_and_evaluate,
)
from agent_eval_harness.harness.model import (
    ModelConfig,
    ModelResponse,
    RequestBudgetExceeded,
    ScriptedModel,
    ToolCall,
)


DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
SOURCE_REPOSITORY = DEFAULT_SOURCE_REPOSITORY
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for Docker parity",
)
class LangGraphParityDockerTests(unittest.TestCase):
    def setUp(self):
        self.task = AdmittedTask.from_evidence(
            Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY
        )

    def _repair_model(self) -> ScriptedModel:
        repair = json.loads(
            (REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json").read_text()
        )
        return ScriptedModel([
            ModelResponse(
                tool_calls=(ToolCall("read_file", {"path": "app/source.py"}, "read-1"),),
                reasoning_fields={"reasoning_content": "Inspect retrieval before editing."},
                usage={"prompt_tokens": 21, "completion_tokens": 4},
            ),
            ModelResponse(tool_calls=(ToolCall(
                "search_text", {"query": "def retrieve"}, "search-1"
            ),)),
            ModelResponse(tool_calls=(ToolCall("apply_patch", {
                "path": repair["path"], "old_text": repair["before"],
                "new_text": repair["after"],
            }, "patch-1"),)),
            ModelResponse(content="The title-only retrieval repair is complete."),
        ])

    def test_correct_repair_runs_through_graph_and_is_independently_evaluated(self):
        python_model = self._repair_model()
        graph_model = self._repair_model()
        with tempfile.TemporaryDirectory(prefix="langgraph-repair-") as temporary:
            common = {
                "admitted_task": self.task,
                "model_config": ModelConfig(provider="scripted", requested_model="fixture-model"),
                "budgets": AttemptBudgets(max_model_calls=5, shell_timeout_seconds=10),
            }
            python_result = attempt_and_evaluate(
                **common,
                model=python_model,
                artifact_directory=Path(temporary) / "python",
            )
            graph_result = attempt_and_evaluate(
                **common,
                model=graph_model,
                artifact_directory=Path(temporary) / "graph",
                orchestrator="langgraph",
            )
            for artifact_directory in (Path(temporary) / "python", Path(temporary) / "graph"):
                self.assertTrue((artifact_directory / "result.json").is_file())
                self.assertTrue((artifact_directory / "report.html").is_file())
            graph_report = (Path(temporary) / "graph" / "report.html").read_text()
            self.assertIn("Graph node steps", graph_report)
            self.assertIn("Graph limit source", graph_report)

        self.assertEqual(python_result["termination_reason"], "agent_completed")
        self.assertEqual(graph_result["termination_reason"], "agent_completed")
        self.assertEqual(python_result["functional_verdict"], "success")
        self.assertEqual(graph_result["functional_verdict"], "success")
        self.assertEqual(python_result["metadata"]["model_call_count"], 4)
        self.assertEqual(graph_result["metadata"]["model_call_count"], 4)
        self.assertEqual(graph_result["metadata"]["orchestrator"], "langgraph")
        self.assertEqual(graph_result["metadata"]["graph_step_count"], 7)
        self.assertEqual(graph_result["metadata"]["graph_step_limit"], 11)
        self.assertEqual(
            graph_result["metadata"]["graph_step_limit_source"],
            "derived_from_model_call_budget",
        )
        self.assertEqual(python_result["candidate"]["files"], graph_result["candidate"]["files"])
        self.assertEqual(
            [event["tool_name"] for event in python_result["trace"] if event["type"] == "tool"],
            ["read_file", "search_text", "apply_patch"],
        )
        self.assertEqual(
            [event["tool_name"] for event in graph_result["trace"] if event["type"] == "tool"],
            ["read_file", "search_text", "apply_patch"],
        )
        self.assertEqual(
            [request.messages for request in python_model.requests],
            [request.messages for request in graph_model.requests],
        )
        self.assertIn("reasoning_content", graph_model.requests[1].messages[2])
        self.assertEqual(
            graph_model.requests[1].messages[2]["reasoning_content"],
            "Inspect retrieval before editing.",
        )
        self.assertTrue(all(python_result["evaluation"]["checks"].values()))
        self.assertTrue(all(graph_result["evaluation"]["checks"].values()))

    def test_tool_error_recovery_and_model_budget_preserve_the_same_partial_patch(self):
        repair = json.loads(
            (REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json").read_text()
        )

        def model():
            return ScriptedModel([
                ModelResponse(tool_calls=(ToolCall("apply_patch", {
                    "path": repair["path"], "old_text": "this text is absent",
                    "new_text": "incorrect replacement",
                }, "rejected-edit"),)),
                ModelResponse(tool_calls=(
                    ToolCall("apply_patch", {
                        "path": repair["path"], "old_text": repair["before"],
                        "new_text": repair["after"],
                    }, "recovery-edit"),
                    ToolCall("apply_patch", {
                        "path": "notes/recovered-at-budget-stop.txt",
                        "content": "This new file is part of the collected patch.\n",
                    }, "partial-note"),
                )),
            ])

        python_model = model()
        graph_model = model()
        with tempfile.TemporaryDirectory(prefix="langgraph-recovery-") as temporary:
            common = {
                "admitted_task": self.task,
                "model_config": ModelConfig(provider="scripted", requested_model="recovery-fixture"),
                "budgets": AttemptBudgets(max_model_calls=2, shell_timeout_seconds=10),
            }
            python_result = attempt_and_evaluate(
                **common, model=python_model, artifact_directory=Path(temporary) / "python"
            )
            graph_result = attempt_and_evaluate(
                **common,
                model=graph_model,
                artifact_directory=Path(temporary) / "graph",
                orchestrator="langgraph",
            )

        for result in (python_result, graph_result):
            self.assertEqual(result["termination_reason"], "model_call_budget")
            self.assertEqual(result["functional_verdict"], "success")
            self.assertIn("notes/recovered-at-budget-stop.txt", result["candidate"]["changed_files"])
            self.assertTrue(all(result["evaluation"]["checks"].values()))
            tools = [event for event in result["trace"] if event["type"] == "tool"]
            self.assertEqual(
                [event["tool_name"] for event in tools],
                ["apply_patch", "apply_patch", "apply_patch"],
            )
            self.assertEqual(tools[0]["result"]["error_category"], "patch_rejected")
            self.assertEqual(tools[1]["status"], "ok")
            self.assertEqual(tools[2]["status"], "ok")
            self.assertEqual(result["metadata"]["model_call_count"], 2)
        self.assertEqual(
            [request.messages for request in python_model.requests],
            [request.messages for request in graph_model.requests],
        )

    def test_graph_step_budget_is_separate_and_evaluates_a_partial_repair(self):
        repair = json.loads(
            (REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json").read_text()
        )

        def model():
            return ScriptedModel([
                ModelResponse(tool_calls=(ToolCall("apply_patch", {
                    "path": repair["path"], "old_text": repair["before"],
                    "new_text": repair["after"],
                }, "repair"),)),
                ModelResponse(content="The repair is complete."),
            ])

        python_model = model()
        graph_model = model()
        with tempfile.TemporaryDirectory(prefix="langgraph-step-budget-") as temporary:
            common = {
                "admitted_task": self.task,
                "model_config": ModelConfig(provider="scripted", requested_model="step-budget-fixture"),
                "budgets": AttemptBudgets(max_model_calls=5, max_graph_steps=2),
            }
            python_result = attempt_and_evaluate(
                **common, model=python_model, artifact_directory=Path(temporary) / "python"
            )
            graph_result = attempt_and_evaluate(
                **common,
                model=graph_model,
                artifact_directory=Path(temporary) / "graph",
                orchestrator="langgraph",
            )

        self.assertEqual(python_result["termination_reason"], "agent_completed")
        self.assertEqual(python_result["metadata"]["model_call_count"], 2)
        self.assertEqual(graph_result["termination_reason"], "graph_step_budget")
        self.assertEqual(graph_result["metadata"]["model_call_count"], 1)
        self.assertEqual(graph_result["metadata"]["graph_step_count"], 2)
        self.assertEqual(graph_result["metadata"]["graph_step_limit"], 2)
        self.assertEqual(
            graph_result["metadata"]["graph_step_limit_source"],
            "configured_graph_only_budget",
        )
        self.assertEqual(graph_result["functional_verdict"], "success")
        self.assertIn("app/source.py", graph_result["candidate"]["changed_files"])
        self.assertTrue(all(graph_result["evaluation"]["checks"].values()))

    def test_provider_spending_budget_stop_is_shared_and_never_retried(self):
        class SpendLimitedModel:
            def __init__(self):
                self.requests = []

            def complete(self, request):
                self.requests.append(request)
                raise RequestBudgetExceeded("controlled synthetic spend cap")

            def accounting_snapshot(self):
                return {"status": "within_limit", "remaining_usd": "0.000000"}

        python_model = SpendLimitedModel()
        graph_model = SpendLimitedModel()
        with tempfile.TemporaryDirectory(prefix="langgraph-spend-budget-") as temporary:
            common = {
                "admitted_task": self.task,
                "model_config": ModelConfig(provider="controlled", requested_model="spend-fixture"),
                "budgets": AttemptBudgets(max_model_calls=5, max_provider_retries=1),
            }
            python_result = attempt_and_evaluate(
                **common, model=python_model, artifact_directory=Path(temporary) / "python"
            )
            graph_result = attempt_and_evaluate(
                **common,
                model=graph_model,
                artifact_directory=Path(temporary) / "graph",
                orchestrator="langgraph",
            )

        for result, model in ((python_result, python_model), (graph_result, graph_model)):
            self.assertEqual(result["termination_reason"], "spending_budget")
            self.assertEqual(result["metadata"]["model_call_count"], 1)
            self.assertEqual(result["metadata"]["retry_count"], 0)
            self.assertEqual(len(model.requests), 1)
            model_event = next(event for event in result["trace"] if event["type"] == "model")
            self.assertEqual(model_event["status"], "budget_stopped")
            self.assertEqual(model_event["error_category"], "spending_budget")

    def test_provider_accounting_and_output_limit_stop_are_shared(self):
        class OutputLimitedModel:
            def __init__(self):
                self.requests = []

            def complete(self, request):
                self.requests.append(request)
                return ModelResponse(
                    tool_calls=(ToolCall("read_file", {"path": "app/source.py"}, "must-not-run"),),
                    usage={
                        "prompt_tokens": 100,
                        "completion_tokens": 1024,
                        "provider_finish_reason": "length",
                        "billing": {
                            "estimated_cost": {
                                "status": "estimated", "amount": 0.001, "currency": "USD",
                            },
                            "reported_cost": {
                                "status": "unavailable", "amount": None, "currency": "USD",
                            },
                        },
                    },
                    observed_model="fixture-observed-v1",
                )

            def run_metadata(self):
                return {"provider_endpoint": "https://example.invalid/v1"}

            def accounting_snapshot(self):
                return {"status": "within_limit", "remaining_usd": "0.010000"}

        results = []
        with tempfile.TemporaryDirectory(prefix="langgraph-provider-output-limit-") as temporary:
            for orchestrator in ("python-loop", "langgraph"):
                model = OutputLimitedModel()
                result = attempt_and_evaluate(
                    admitted_task=self.task,
                    model=model,
                    model_config=ModelConfig(
                        provider="controlled", requested_model="output-limit-fixture"
                    ),
                    budgets=AttemptBudgets(max_model_calls=3),
                    artifact_directory=Path(temporary) / orchestrator,
                    orchestrator=orchestrator,
                )
                results.append((result, model))

        for result, model in results:
            self.assertEqual(result["termination_reason"], "provider_output_limit")
            self.assertEqual(result["metadata"]["model_call_count"], 1)
            self.assertEqual(result["metadata"]["observed_models"], ["fixture-observed-v1"])
            self.assertEqual(result["metadata"]["provider_endpoint"], "https://example.invalid/v1")
            self.assertEqual(result["metadata"]["spend_budget"]["status"], "within_limit")
            self.assertEqual(result["metadata"]["cost"]["estimated"]["amount"], 0.001)
            self.assertEqual(result["metadata"]["cost"]["reported"]["status"], "unavailable")
            self.assertEqual(
                [event for event in result["trace"] if event["type"] == "tool"], []
            )
            self.assertEqual(len(model.requests), 1)
        self.assertEqual(
            results[0][0]["metadata"]["cost"], results[1][0]["metadata"]["cost"]
        )



if __name__ == "__main__":
    unittest.main()

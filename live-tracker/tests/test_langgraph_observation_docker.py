"""Docker parity: observation on/off and both orchestrators, through attempt_and_evaluate.

Each scenario runs four real attempts (python-loop and langgraph, observed and unobserved).
Model-visible requests, ordered tool results, candidate files and verdicts must match.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_eval_harness.bench.attempt import AdmittedTask, AttemptBudgets, attempt_and_evaluate
from agent_eval_harness.harness.model import ModelConfig, ModelResponse, RequestBudgetExceeded, ScriptedModel, ToolCall
from live_tracker.reader import read_attempt_history
from live_tracker.recorder import AttemptRecorder


DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
SOURCE_REPOSITORY = Path(os.environ.get(
    "ML_TUTOR_REPOSITORY", "/home/francisco/prompt-engineering-group-project"
))
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATORS = ("python-loop", "langgraph")


class SpendLimitedModel:
    def __init__(self):
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        raise RequestBudgetExceeded("controlled synthetic spend cap")

    def accounting_snapshot(self):
        return {"status": "within_limit", "remaining_usd": "0.000000"}


def _repair():
    return json.loads((REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json").read_text())


def _repair_model():
    repair = _repair()
    return ScriptedModel([
        ModelResponse(
            tool_calls=(ToolCall("read_file", {"path": "app/source.py"}, "read-1"),),
            reasoning_fields={"reasoning_content": "Inspect retrieval before editing."},
            usage={"prompt_tokens": 21, "completion_tokens": 4},
        ),
        ModelResponse(tool_calls=(ToolCall("search_text", {"query": "def retrieve"}, "search-1"),)),
        ModelResponse(tool_calls=(ToolCall("apply_patch", {
            "path": repair["path"], "old_text": repair["before"], "new_text": repair["after"],
        }, "patch-1"),)),
        ModelResponse(content="The title-only retrieval repair is complete."),
    ])


def _recovery_model():
    repair = _repair()
    return ScriptedModel([
        ModelResponse(tool_calls=(ToolCall("apply_patch", {
            "path": repair["path"], "old_text": "this text is absent", "new_text": "incorrect replacement",
        }, "rejected-edit"),)),
        ModelResponse(tool_calls=(
            ToolCall("apply_patch", {
                "path": repair["path"], "old_text": repair["before"], "new_text": repair["after"],
            }, "recovery-edit"),
            ToolCall("apply_patch", {
                "path": "notes/recovered-at-budget-stop.txt",
                "content": "This new file is part of the collected patch.\n",
            }, "partial-note"),
        )),
    ])


# scenario name -> (model factory, budgets, expected termination reason)
SCENARIOS = {
    "repair": (_repair_model, AttemptBudgets(max_model_calls=5, shell_timeout_seconds=10), "agent_completed"),
    "tool_error_then_model_budget": (
        _recovery_model, AttemptBudgets(max_model_calls=2, shell_timeout_seconds=10), "model_call_budget",
    ),
    "spend_budget": (
        SpendLimitedModel, AttemptBudgets(max_model_calls=5, max_provider_retries=1), "spending_budget",
    ),
}


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for Docker attempts",
)
class LangGraphObservationDockerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = AdmittedTask.from_evidence(Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY)

    def _run_all(self, scenario):
        make_model, budgets, _ = SCENARIOS[scenario]
        runs = {}
        with tempfile.TemporaryDirectory(prefix=f"langgraph-observe-{scenario}-") as temporary:
            for orchestrator in ORCHESTRATORS:
                for observed in (False, True):
                    label = f"{orchestrator}-{'observed' if observed else 'unobserved'}"
                    directory = Path(temporary) / label
                    model = make_model()
                    kwargs = {"event_sink": AttemptRecorder(directory)} if observed else {}
                    result = attempt_and_evaluate(
                        admitted_task=self.task,
                        model=model,
                        model_config=ModelConfig(provider="scripted", requested_model=f"{scenario}-fixture"),
                        budgets=budgets,
                        artifact_directory=directory,
                        orchestrator=orchestrator,
                        **kwargs,
                    )
                    events = read_attempt_history(directory).events if observed else []
                    runs[label] = (result, model, events)
        return runs

    def _assert_parity(self, runs, scenario):
        _, _, expected_reason = SCENARIOS[scenario]
        reference_result, reference_model, _ = runs["python-loop-unobserved"]
        for label, (result, model, _) in runs.items():
            with self.subTest(run=label):
                self.assertEqual(result["termination_reason"], expected_reason)
                self.assertEqual(
                    [request.messages for request in model.requests],
                    [request.messages for request in reference_model.requests],
                )
                self.assertEqual(
                    [event["model_visible_result"] for event in result["trace"] if event["type"] == "tool"],
                    [event["model_visible_result"] for event in reference_result["trace"] if event["type"] == "tool"],
                )
                self.assertEqual(result["candidate"]["files"], reference_result["candidate"]["files"])
                self.assertEqual(result["evaluation"]["checks"], reference_result["evaluation"]["checks"])
                self.assertEqual(result["functional_verdict"], reference_result["functional_verdict"])

    def _assert_observed_history(self, runs):
        for orchestrator in ORCHESTRATORS:
            result, _, events = runs[f"{orchestrator}-observed"]
            types = [event["type"] for event in events]
            self.assertEqual(types[0], "attempt_started")
            self.assertEqual(types[-1], "attempt_finished")
            self.assertEqual([event["sequence"] for event in events], list(range(1, len(events) + 1)))
            self.assertEqual(
                sum(1 for event in events if event["type"] == "model.start"),
                result["metadata"]["model_call_count"],
            )
            if orchestrator == "python-loop":
                self.assertIn("phase.enter", types)
                self.assertNotIn("node.enter", types)
                continue
            # LangGraph: every actual graph node is recorded where it executed, and resolved.
            enters = [event for event in events if event["type"] == "node.enter"]
            outcomes = {event["operation_id"] for event in events if event["type"] == "node.outcome"}
            self.assertEqual(
                [event["operation_id"] for event in enters],
                [f"graph-step-{index}" for index in range(1, len(enters) + 1)],
            )
            self.assertEqual(len(enters), result["metadata"]["graph_step_count"])
            self.assertTrue(all(event["operation_id"] in outcomes for event in enters))
            routes = [event["data"] for event in events if event["type"] == "route.decision"]
            self.assertEqual(routes[-1]["next"], "end")
            self.assertEqual(routes[-1]["reason"], result["termination_reason"])
            self.assertEqual(
                [event["data"]["graph_step_count"] for event in events if event["type"] == "state"],
                list(range(1, len(enters) + 1)),
            )

    def test_repair_is_identical_with_and_without_observation_for_both_orchestrators(self):
        self._assert_parity(self._run_all("repair"), "repair")
        self._assert_observed_history(self._run_all("repair"))

    def test_tool_error_recovery_then_model_budget_is_identical_with_and_without_observation(self):
        runs = self._run_all("tool_error_then_model_budget")
        self._assert_parity(runs, "tool_error_then_model_budget")
        self._assert_observed_history(runs)

    def test_spend_budget_stop_is_identical_with_and_without_observation(self):
        runs = self._run_all("spend_budget")
        self._assert_parity(runs, "spend_budget")
        self._assert_observed_history(runs)


if __name__ == "__main__":
    unittest.main()

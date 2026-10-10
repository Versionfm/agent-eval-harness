import json
import os
from pathlib import Path
import tempfile
import unittest

from agent_eval_harness.bench.attempt import (
    AdmittedTask,
    AttemptBudgets,
    ModelConfig,
    ModelResponse,
    ScriptedModel,
    ToolCall,
    attempt_and_evaluate,
)


DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPOSITORY = Path(os.environ.get(
    "ML_TUTOR_REPOSITORY", "/home/francisco/prompt-engineering-group-project"
))


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for Docker attempt",
)
class ScriptedAttemptDockerTests(unittest.TestCase):
    def test_scripted_repair_runs_in_task_container_and_is_freshly_evaluated(self):
        evidence = json.loads(Path(ADMISSION_EVIDENCE).read_text(encoding="utf-8"))
        self.assertEqual(evidence["assessment"]["status"], "admitted")
        repair = json.loads(
            (REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json").read_text()
        )
        added_test = '''import unittest
from app.source import retrieve


class TitleRelevanceTests(unittest.TestCase):
    def test_title_only_match_beats_unrelated_first_section(self):
        sections = [
            {"id": "decoy", "title": "Graph Output", "text": "Tensor logging only."},
            {"id": "target", "title": "Weight Decay", "text": "A synthetic passage."},
        ]
        self.assertEqual(retrieve("WHAT IS WEIGHT DECAY?", sections, k=1)[0]["id"], "target")
'''
        scripted = ScriptedModel([
            ModelResponse(
                tool_calls=(ToolCall("read_file", {"path": "app/source.py"}, "read-1"),),
                reasoning_fields={"reasoning_content": "Inspect the retrieval path first."},
                usage={"prompt_tokens": 11, "completion_tokens": 3},
            ),
            ModelResponse(tool_calls=(ToolCall(
                "search_text", {"query": "def retrieve"}, "search-1"
            ),)),
            ModelResponse(tool_calls=(ToolCall("apply_patch", {
                "path": repair["path"], "old_text": repair["before"],
                "new_text": repair["after"],
            }, "patch-1"),)),
            ModelResponse(tool_calls=(ToolCall("apply_patch", {
                "path": "tests/test_title_retrieval.py", "content": added_test,
            }, "patch-2"),)),
            ModelResponse(tool_calls=(ToolCall(
                "run_shell", {
                    "command": "python -m unittest tests.test_source tests.test_tutor tests.test_title_retrieval"
                }, "shell-1"
            ),)),
            ModelResponse(content="The title-only retrieval repair is complete."),
        ])

        with tempfile.TemporaryDirectory(prefix="scripted-attempt-") as temporary:
            artifacts = Path(temporary) / "attempt"
            result = attempt_and_evaluate(
                admitted_task=AdmittedTask.from_evidence(
                    Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY
                ),
                model=scripted,
                model_config=ModelConfig(provider="scripted", requested_model="fixture-model"),
                budgets=AttemptBudgets(max_model_calls=10, shell_timeout_seconds=30),
                artifact_directory=artifacts,
            )
            diagnostic = {
                "harness_error": result.get("harness_error"),
                "tools": [
                    {
                        "name": event.get("tool_name"),
                        "status": event.get("status"),
                        "error": event.get("result", {}).get("error"),
                        "output": event.get("result", {}).get("output", "")[:500],
                    }
                    for event in result["trace"] if event.get("type") == "tool"
                ],
                "candidate": result.get("candidate", {}).get("changed_files"),
                "evaluation": result.get("evaluation"),
            }

            self.assertEqual(result["termination_reason"], "agent_completed", diagnostic)
            self.assertEqual(result["functional_verdict"], "success", diagnostic)
            self.assertEqual(
                [event["tool_name"] for event in result["trace"] if event["type"] == "tool"],
                ["read_file", "search_text", "apply_patch", "apply_patch", "run_shell"],
            )
            self.assertIn(
                "reasoning_content",
                scripted.requests[1].messages[2],
                "provider reasoning must survive into the follow-up request",
            )
            self.assertEqual(
                scripted.requests[1].messages[2]["reasoning_content"],
                "Inspect the retrieval path first.",
            )
            self.assertIn("tests/test_title_retrieval.py", result["candidate"]["changed_files"])
            task_repository = Path(result["metadata"]["attempt_repository"])
            self.assertTrue((task_repository / "AGENTS.md").is_file())
            self.assertTrue((task_repository / "tests/test_source.py").is_file())
            self.assertTrue((task_repository / "source/sections.jsonl").is_file())
            self.assertFalse((task_repository / "curator").exists())
            observed = result["attempt_container_configuration"]["observed"]
            self.assertEqual(
                observed["image_id"], result["metadata"]["task_image_evidence"]["image_id"]
            )
            self.assertTrue(
                result["metadata"]["task_image_evidence"]["dockerfile_sha256"]
            )
            self.assertEqual(observed["network_mode"], "none")
            self.assertTrue(observed["root_filesystem_read_only"])
            self.assertEqual([mount["destination"] for mount in observed["mounts"]], ["/task"])
            self.assertFalse(observed["mounts"][0]["read_only"])
            self.assertTrue(all(result["evaluation"]["checks"].values()))
            self.assertEqual(result["evaluation"]["container_configuration"]["network_mode"], "none")
            self.assertFalse(
                result["evaluation"]["container_configuration"][
                    "credentials_or_container_socket_mounted"
                ]
            )
            for name in ("metadata.json", "trace.jsonl", "candidate.patch", "checks.json", "report.html"):
                self.assertTrue((artifacts / name).is_file(), name)
            report = (artifacts / "report.html").read_text(encoding="utf-8")
            self.assertIn("Cost unavailable", report)
            self.assertIn("Qualitative review pending", report)
            self.assertIn("TitleRelevanceTests", report)

    def test_incorrect_and_test_only_changes_do_not_pass_canonical_evaluation(self):
        incorrect = ScriptedModel([
            ModelResponse(tool_calls=(ToolCall("apply_patch", {
                "path": "app/source.py",
                "old_text": 'docs = [_terms(s["text"]) for s in sections]',
                "new_text": 'docs = [_terms(s["text"] + " ") for s in sections]',
            }, "wrong-edit"),)),
            ModelResponse(content="The retrieval code has been updated."),
        ])
        false_test = '''import unittest


class FalseConfidenceTest(unittest.TestCase):
    def test_title_retrieval_is_fixed(self):
        self.assertTrue(True)
'''
        test_only = ScriptedModel([
            ModelResponse(tool_calls=(ToolCall("apply_patch", {
                "path": "tests/test_false_confidence.py", "content": false_test,
            }, "test-only-edit"),)),
            ModelResponse(tool_calls=(ToolCall("run_shell", {
                "command": "python -m unittest tests.test_false_confidence"
            }, "local-test"),)),
            ModelResponse(content="The new local test passes."),
        ])

        with tempfile.TemporaryDirectory(prefix="attempt-verdicts-") as temporary:
            common = {
                "admitted_task": AdmittedTask.from_evidence(
                    Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY
                ),
                "model_config": ModelConfig(provider="scripted", requested_model="fixture-model"),
                "budgets": AttemptBudgets(max_model_calls=5, shell_timeout_seconds=30),
            }
            wrong_result = attempt_and_evaluate(
                **common, model=incorrect, artifact_directory=Path(temporary) / "wrong"
            )
            test_result = attempt_and_evaluate(
                **common, model=test_only, artifact_directory=Path(temporary) / "test-only"
            )

        self.assertEqual(wrong_result["termination_reason"], "agent_completed")
        self.assertEqual(wrong_result["functional_verdict"], "failure")
        self.assertIn("app/source.py", wrong_result["candidate"]["changed_files"])
        self.assertFalse(any(path.startswith("tests/") for path in wrong_result["candidate"]["changed_files"]))
        self.assertEqual(test_result["termination_reason"], "agent_completed")
        self.assertEqual(test_result["functional_verdict"], "failure")
        self.assertEqual(test_result["candidate"]["changed_files"], ["tests/test_false_confidence.py"])
        local_test = next(
            event for event in test_result["trace"]
            if event.get("type") == "tool" and event.get("tool_name") == "run_shell"
        )
        self.assertEqual(local_test["status"], "ok")
        self.assertCountEqual(
            [check for check, passed in test_result["evaluation"]["checks"].items() if not passed],
            ["title_retrieval", "title_context", "input_order_independence"],
        )


if __name__ == "__main__":
    unittest.main()

"""Run the inspectable, offline scripted title-retrieval repair attempt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from agent_eval_harness.bench.attempt import (
    AdmittedTask,
    AttemptBudgets,
    DEFAULT_ADMISSION_EVIDENCE,
    DEFAULT_SOURCE_REPOSITORY,
    DEFAULT_TASK_PACKAGE,
    ORCHESTRATION_ROOT,
    REPOSITORY_ROOT,
    attempt_and_evaluate,
)
from agent_eval_harness.harness.model import ModelConfig, ModelResponse, ScriptedModel, ToolCall


DEFAULT_OUTPUT = (
    ORCHESTRATION_ROOT / "evidence" / "issue-3" / "scripted-repair"
)
ADDED_TEST = '''import unittest
from app.source import retrieve


class ScriptedTitleRetrievalTests(unittest.TestCase):
    def test_title_only_match_beats_unrelated_first_section(self):
        sections = [
            {"id": "decoy", "title": "Graph Output", "text": "Tensor logging only."},
            {"id": "target", "title": "Weight Decay", "text": "A synthetic passage."},
        ]
        self.assertEqual(retrieve("WHAT IS WEIGHT DECAY?", sections, k=1)[0]["id"], "target")
'''


def make_scripted_model() -> ScriptedModel:
    repair = json.loads(
        (DEFAULT_TASK_PACKAGE / "curator" / "repair.json").read_text(encoding="utf-8")
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
            "path": repair["path"], "old_text": repair["before"], "new_text": repair["after"],
        }, "patch-1"),)),
        ModelResponse(tool_calls=(ToolCall("apply_patch", {
            "path": "tests/test_scripted_title_retrieval.py", "content": ADDED_TEST,
        }, "new-test-1"),)),
        ModelResponse(tool_calls=(ToolCall("run_shell", {
            "command": (
                "python -m unittest tests.test_source tests.test_tutor "
                "tests.test_scripted_title_retrieval"
            ),
        }, "shell-1"),)),
        ModelResponse(content="The title-only retrieval repair is complete."),
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-evidence", type=Path, default=DEFAULT_ADMISSION_EVIDENCE)
    parser.add_argument("--source-repository", type=Path, default=DEFAULT_SOURCE_REPOSITORY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    try:
        result = attempt_and_evaluate(
            admitted_task=AdmittedTask.from_evidence(
                args.admission_evidence, source_repository=args.source_repository
            ),
            model=make_scripted_model(),
            model_config=ModelConfig(
                provider="scripted", requested_model="scripted-title-repair-v1"
            ),
            budgets=AttemptBudgets(max_model_calls=10, shell_timeout_seconds=60),
            artifact_directory=args.output_dir,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    summary = {
        "termination_reason": result["termination_reason"],
        "functional_verdict": result["functional_verdict"],
        "duration_seconds": result["duration_seconds"],
        "model_call_count": result["metadata"].get("model_call_count"),
        "changed_files": result["candidate"]["changed_files"],
        "checks": result["evaluation"].get("checks", {}),
        "artifact_directory": str(args.output_dir.expanduser().resolve()),
        "report": str(args.output_dir.expanduser().resolve() / "report.html"),
        "task_image_evidence": result["metadata"].get("task_image_evidence"),
        "error": result.get("harness_error", result["evaluation"].get("error")),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if result["functional_verdict"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())

"""Run an offline failure/recovery attempt and preserve its partial-at-budget result."""

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
    ORCHESTRATION_ROOT / "evidence" / "issue-4" / "tool-recovery"
)


def make_scripted_model() -> ScriptedModel:
    repair = json.loads(
        (DEFAULT_TASK_PACKAGE / "curator" / "repair.json").read_text(encoding="utf-8")
    )
    return ScriptedModel([
        ModelResponse(tool_calls=(ToolCall("apply_patch", {
            "path": repair["path"],
            "old_text": "this exact text is intentionally absent",
            "new_text": "incorrect replacement",
        }, "rejected-edit"),)),
        ModelResponse(tool_calls=(
            ToolCall("apply_patch", {
                "path": repair["path"],
                "old_text": repair["before"],
                "new_text": repair["after"],
            }, "recovery-edit"),
            ToolCall("apply_patch", {
                "path": "notes/recovered-at-budget-stop.txt",
                "content": "This new file is part of the collected patch.\n",
            }, "new-partial-file"),
            ToolCall("run_shell", {
                "command": "python -c 'print(\"<untrusted-output>\" + \"x\" * 512)'"
            }, "large-output"),
        )),
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-evidence", type=Path, default=DEFAULT_ADMISSION_EVIDENCE)
    parser.add_argument("--source-repository", type=Path, default=DEFAULT_SOURCE_REPOSITORY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--max-model-calls", type=int, default=2,
        help="configurable demonstration proposal; two calls show recovery then budget stop",
    )
    parser.add_argument(
        "--tool-output-limit-bytes", type=int, default=128,
        help="configurable demonstration proposal for model-visible tool output",
    )
    args = parser.parse_args(argv)

    try:
        result = attempt_and_evaluate(
            admitted_task=AdmittedTask.from_evidence(
                args.admission_evidence, source_repository=args.source_repository
            ),
            model=make_scripted_model(),
            model_config=ModelConfig(
                provider="scripted", requested_model="failure-recovery-v1"
            ),
            budgets=AttemptBudgets(
                max_model_calls=args.max_model_calls,
                tool_output_limit_bytes=args.tool_output_limit_bytes,
            ),
            artifact_directory=args.output_dir,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    summary = {
        "termination_reason": result["termination_reason"],
        "functional_verdict": result["functional_verdict"],
        "failure_category": result.get("failure_category"),
        "model_call_count": result["metadata"].get("model_call_count"),
        "retry_count": result["metadata"].get("retry_count"),
        "changed_files": result["candidate"]["changed_files"],
        "checks": result["evaluation"].get("checks", {}),
        "artifact_directory": str(args.output_dir.expanduser().resolve()),
        "report": str(args.output_dir.expanduser().resolve() / "report.html"),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if result["functional_verdict"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())

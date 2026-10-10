"""CLI · run inspectable offline parity scenarios through Python and LangGraph."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

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
from agent_eval_harness.bench.admission import task_package_evidence
from agent_eval_harness.harness.model import ModelConfig, ModelResponse, ScriptedModel, ToolCall


DEFAULT_OUTPUT = (
    ORCHESTRATION_ROOT / "evidence" / "issue-6" / "langgraph-parity"
)


def _repair() -> dict[str, Any]:
    return json.loads((DEFAULT_TASK_PACKAGE / "curator" / "repair.json").read_text(encoding="utf-8"))


def _correct_scenario() -> tuple[list[ModelResponse], AttemptBudgets]:
    repair = _repair()
    responses = [
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
    ]
    return responses, AttemptBudgets(max_model_calls=5, shell_timeout_seconds=10)


def _recovery_scenario() -> tuple[list[ModelResponse], AttemptBudgets]:
    repair = _repair()
    responses = [
        ModelResponse(tool_calls=(ToolCall("apply_patch", {
            "path": repair["path"], "old_text": "this exact text is intentionally absent",
            "new_text": "incorrect replacement",
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
    ]
    return responses, AttemptBudgets(max_model_calls=2, shell_timeout_seconds=10)


def _graph_step_budget_scenario() -> tuple[list[ModelResponse], AttemptBudgets]:
    repair = _repair()
    responses = [
        ModelResponse(tool_calls=(ToolCall("apply_patch", {
            "path": repair["path"], "old_text": repair["before"], "new_text": repair["after"],
        }, "repair"),)),
        ModelResponse(content="The repair is complete."),
    ]
    return responses, AttemptBudgets(max_model_calls=5, max_graph_steps=2)


def _tool_actions(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": event["tool_name"],
            "call_id": event["tool_call_id"],
            "arguments": event["arguments"],
            "status": event["status"],
        }
        for event in result["trace"]
        if event.get("type") == "tool"
    ]


def _run_attempt(
    *,
    task: AdmittedTask,
    responses: list[ModelResponse],
    budgets: AttemptBudgets,
    artifact_directory: Path,
    orchestrator: str,
) -> tuple[dict[str, Any], ScriptedModel]:
    model = ScriptedModel(responses)
    result = attempt_and_evaluate(
        admitted_task=task,
        model=model,
        model_config=ModelConfig(provider="scripted", requested_model="parity-fixture-v1"),
        budgets=budgets,
        artifact_directory=artifact_directory,
        orchestrator=orchestrator,
    )
    return result, model


def _comparison(
    python_result: dict[str, Any],
    python_model: ScriptedModel,
    graph_result: dict[str, Any],
    graph_model: ScriptedModel,
    *,
    expected_termination: str,
    expected_step_budget: bool = False,
) -> dict[str, Any]:
    python_requests = [request.messages for request in python_model.requests]
    graph_requests = [request.messages for request in graph_model.requests]
    common_prefix = min(len(python_requests), len(graph_requests))
    checks = {
        "common_model_request_prefix_matches": python_requests[:common_prefix] == graph_requests[:common_prefix],
        "tool_actions_match": _tool_actions(python_result) == _tool_actions(graph_result),
        "canonical_checks_match": (
            python_result["evaluation"].get("checks") == graph_result["evaluation"].get("checks")
        ),
        "both_canonical_evaluations_pass": (
            all(python_result["evaluation"].get("checks", {}).values())
            and all(graph_result["evaluation"].get("checks", {}).values())
        ),
        "harness_provenance_matches": (
            python_result["metadata"].get("harness_revision")
            == graph_result["metadata"].get("harness_revision")
            and python_result["metadata"].get("dependency_versions")
            == graph_result["metadata"].get("dependency_versions")
        ),
    }
    if expected_step_budget:
        checks.update({
            "graph_stops_on_its_node_budget": graph_result["termination_reason"] == "graph_step_budget",
            "python_loop_does_not_consume_graph_budget": python_result["termination_reason"] == "agent_completed",
            "partial_graph_candidate_passes": graph_result["functional_verdict"] == "success",
        })
    else:
        checks.update({
            "model_request_histories_match": python_requests == graph_requests,
            "termination_matches": python_result["termination_reason"] == graph_result["termination_reason"],
            "model_call_count_matches": (
                python_result["metadata"]["model_call_count"]
                == graph_result["metadata"]["model_call_count"]
            ),
            "termination_matches_scenario": (
                python_result["termination_reason"] == expected_termination
                and graph_result["termination_reason"] == expected_termination
            ),
            "functional_verdict_matches": (
                python_result["functional_verdict"] == graph_result["functional_verdict"]
            ),
        })
    return {
        "checks": checks,
        "python_loop": {
            "termination_reason": python_result["termination_reason"],
            "functional_verdict": python_result["functional_verdict"],
            "model_call_count": python_result["metadata"]["model_call_count"],
            "graph_step_count": None,
            "artifact_directory": str(Path(python_result["metadata"]["attempt_repository"]).parent),
            "tool_actions": _tool_actions(python_result),
            "harness_revision": python_result["metadata"].get("harness_revision"),
            "dependency_versions": python_result["metadata"].get("dependency_versions"),
        },
        "langgraph": {
            "termination_reason": graph_result["termination_reason"],
            "functional_verdict": graph_result["functional_verdict"],
            "model_call_count": graph_result["metadata"]["model_call_count"],
            "graph_step_count": graph_result["metadata"].get("graph_step_count"),
            "graph_step_limit": graph_result["metadata"].get("graph_step_limit"),
            "graph_step_limit_source": graph_result["metadata"].get("graph_step_limit_source"),
            "artifact_directory": str(Path(graph_result["metadata"]["attempt_repository"]).parent),
            "tool_actions": _tool_actions(graph_result),
            "harness_revision": graph_result["metadata"].get("harness_revision"),
            "dependency_versions": graph_result["metadata"].get("dependency_versions"),
        },
    }


def run_experiment(task: AdmittedTask, output_directory: Path) -> dict[str, Any]:
    if output_directory.exists():
        raise ValueError(f"Experiment output already exists: {output_directory}")
    output_directory.mkdir(parents=True)
    scenarios = {
        "correct": (_correct_scenario(), "agent_completed", False),
        "error-recovery-budget": (_recovery_scenario(), "model_call_budget", False),
        "graph-step-budget": (_graph_step_budget_scenario(), "graph_step_budget", True),
    }
    task_package = task.evaluator_directory.parent
    manifest = json.loads((task_package / "manifest.json").read_text(encoding="utf-8"))
    task_fingerprint = task_package_evidence(task_package, manifest)
    experiment: dict[str, Any] = {
        "schema_version": "1",
        "task_id": task.task_id,
        "task_version": task.task_version,
        "source_revision": task.source_revision,
        "acceptance_check_version": task.acceptance_check_version,
        "task_identity": task_fingerprint["identity"],
        "task_package_sha256": task_fingerprint["sha256"],
        "model": "scripted parity fixture; no live inference",
        "scenarios": {},
        "attempt_provenance": {},
    }
    for scenario, ((responses, budgets), expected_termination, expected_step_budget) in scenarios.items():
        python_result, python_model = _run_attempt(
            task=task,
            responses=responses,
            budgets=budgets,
            artifact_directory=output_directory / scenario / "python-loop",
            orchestrator="python-loop",
        )
        graph_result, graph_model = _run_attempt(
            task=task,
            responses=responses,
            budgets=budgets,
            artifact_directory=output_directory / scenario / "langgraph",
            orchestrator="langgraph",
        )
        comparison = _comparison(
            python_result,
            python_model,
            graph_result,
            graph_model,
            expected_termination=expected_termination,
            expected_step_budget=expected_step_budget,
        )
        experiment["scenarios"][scenario] = comparison
        experiment["attempt_provenance"][scenario] = {
            "python-loop": {
                "harness_revision": comparison["python_loop"]["harness_revision"],
                "dependency_versions": comparison["python_loop"]["dependency_versions"],
            },
            "langgraph": {
                "harness_revision": comparison["langgraph"]["harness_revision"],
                "dependency_versions": comparison["langgraph"]["dependency_versions"],
            },
        }

    experiment["passed"] = all(
        all(scenario["checks"].values()) for scenario in experiment["scenarios"].values()
    )
    (output_directory / "comparison.json").write_text(
        json.dumps(experiment, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return experiment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-evidence", type=Path, default=DEFAULT_ADMISSION_EVIDENCE)
    parser.add_argument("--source-repository", type=Path, default=DEFAULT_SOURCE_REPOSITORY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        task = AdmittedTask.from_evidence(
            args.admission_evidence, source_repository=args.source_repository
        )
        result = run_experiment(task, args.output_dir.expanduser().resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "passed": result["passed"],
        "scenarios": result["scenarios"],
        "comparison": str(args.output_dir.expanduser().resolve() / "comparison.json"),
    }, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

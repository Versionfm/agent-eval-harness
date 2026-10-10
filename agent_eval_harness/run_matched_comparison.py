"""Run one bounded, matched Python-loop and LangGraph comparison."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import sys
from typing import Any, Callable

from agent_eval_harness.attempt import (
    AdmittedTask,
    AttemptBudgets,
    DEFAULT_ADMISSION_EVIDENCE,
    DEFAULT_SOURCE_REPOSITORY,
    ModelConfig,
    ORCHESTRATION_ROOT,
    REPOSITORY_ROOT,
    _dependency_versions,
    _harness_provenance,
    attempt_and_evaluate,
)
from agent_eval_harness.admission import task_package_evidence
from agent_eval_harness.compare_report import build_comparison_report
from agent_eval_harness.deepseek import (
    DEFAULT_BASE_URL,
    PRICING_SOURCE_CHECKED_AT,
    PRICING_SOURCE_URL,
    DeepSeekModelAdapter,
    JsonTransport,
    SpendBudget,
    _max_request_cost_usd,
)
from agent_eval_harness.deepseek_smoke import (
    load_credential_file,
    run_smoke,
    write_smoke_artifact,
)
from agent_eval_harness.observation import AttemptEventSink


DEFAULT_PARITY_EVIDENCE = (
    ORCHESTRATION_ROOT / "evidence" / "issue-6" / "langgraph-parity" / "comparison.json"
)
DEFAULT_OUTPUT = ORCHESTRATION_ROOT / "evidence" / "issue-8" / "matched-comparison"
DEFAULT_SHARED_BUDGET_USD = 1.00
DEFAULT_SMOKE_BUDGET_USD = 0.10
DEFAULT_ATTEMPT_BUDGET_USD = 0.30
DEFAULT_MAX_MODEL_CALLS = 10
DEFAULT_MAX_CONTEXT_BYTES = 128 * 1024
DEFAULT_ATTEMPT_DEADLINE_SECONDS = 600.0
DEFAULT_SHELL_TIMEOUT_SECONDS = 60
DEFAULT_MAX_OUTPUT_TOKENS = 2048
SMOKE_MAX_OUTPUT_TOKENS = 512
REQUIRED_PARITY_SCENARIOS = {"correct", "error-recovery-budget", "graph-step-budget"}
REQUIRED_PARITY_CHECKS = {
    "correct": {
        "common_model_request_prefix_matches",
        "tool_actions_match",
        "canonical_checks_match",
        "both_canonical_evaluations_pass",
        "harness_provenance_matches",
        "model_request_histories_match",
        "termination_matches",
        "model_call_count_matches",
        "termination_matches_scenario",
        "functional_verdict_matches",
    },
    "error-recovery-budget": {
        "common_model_request_prefix_matches",
        "tool_actions_match",
        "canonical_checks_match",
        "both_canonical_evaluations_pass",
        "harness_provenance_matches",
        "model_request_histories_match",
        "termination_matches",
        "model_call_count_matches",
        "termination_matches_scenario",
        "functional_verdict_matches",
    },
    "graph-step-budget": {
        "common_model_request_prefix_matches",
        "tool_actions_match",
        "canonical_checks_match",
        "both_canonical_evaluations_pass",
        "harness_provenance_matches",
        "graph_stops_on_its_node_budget",
        "python_loop_does_not_consume_graph_budget",
        "partial_graph_candidate_passes",
    },
}
PROVIDER_OR_HARNESS_TERMINATIONS = {
    "provider_error", "harness_error", "interrupted"
}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_parity_evidence(path: Path, task: AdmittedTask) -> dict[str, Any]:
    evidence = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(evidence, dict) or evidence.get("passed") is not True:
        raise ValueError("scripted parity evidence must record passed: true")
    if evidence.get("task_id") != task.task_id:
        raise ValueError("scripted parity evidence belongs to a different task")
    if evidence.get("source_revision") != task.source_revision:
        raise ValueError("scripted parity evidence uses a different source revision")
    task_package = task.evaluator_directory.parent
    manifest = json.loads((task_package / "manifest.json").read_text(encoding="utf-8"))
    fingerprint = task_package_evidence(task_package, manifest)
    if (
        evidence.get("task_version") != task.task_version
        or evidence.get("acceptance_check_version") != task.acceptance_check_version
        or evidence.get("task_identity") != fingerprint["identity"]
        or evidence.get("task_package_sha256") != fingerprint["sha256"]
    ):
        raise ValueError("scripted parity evidence uses a different task fingerprint or check version")
    scenarios = evidence.get("scenarios")
    if not isinstance(scenarios, dict) or not REQUIRED_PARITY_SCENARIOS <= set(scenarios):
        raise ValueError("scripted parity evidence is missing a required scenario")
    for name in sorted(REQUIRED_PARITY_SCENARIOS):
        checks = scenarios[name].get("checks") if isinstance(scenarios[name], dict) else None
        if (not isinstance(checks, dict)
                or not REQUIRED_PARITY_CHECKS[name] <= set(checks)
                or any(value is not True for value in checks.values())):
            raise ValueError(f"scripted parity evidence has failed or missing checks in {name}")
        attempts = evidence.get("attempt_provenance", {}).get(name)
        if not isinstance(attempts, dict):
            raise ValueError(f"scripted parity evidence is missing attempt provenance in {name}")
        python_provenance = attempts.get("python-loop")
        graph_provenance = attempts.get("langgraph")
        if not isinstance(python_provenance, dict) or not isinstance(graph_provenance, dict):
            raise ValueError(f"scripted parity evidence is missing an orchestrator provenance in {name}")
        dependencies = python_provenance.get("dependency_versions")
        if (
            not isinstance(dependencies, dict) or not dependencies
            or any(not isinstance(key, str) or not key or not isinstance(value, str) or not value
                   for key, value in dependencies.items())
            or dependencies != graph_provenance.get("dependency_versions")
            or dependencies != _dependency_versions()
        ):
            raise ValueError(f"scripted parity evidence has mismatched dependency provenance in {name}")
        harness = python_provenance.get("harness_revision")
        if (
            not isinstance(harness, dict)
            or harness != graph_provenance.get("harness_revision")
            or harness != _harness_provenance()
        ):
            raise ValueError(f"scripted parity evidence has mismatched harness provenance in {name}")
    return evidence


def _validate_budget_limits(
    *,
    shared_budget_usd: float,
    smoke_budget_usd: float,
    attempt_budget_usd: float,
    max_model_calls: int,
    max_context_bytes: int,
    attempt_deadline_seconds: float,
    shell_timeout_seconds: int,
    max_output_tokens: int,
) -> AttemptBudgets:
    amounts = {
        "shared budget": shared_budget_usd,
        "smoke budget": smoke_budget_usd,
        "per-attempt budget": attempt_budget_usd,
    }
    for label, amount in amounts.items():
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError(f"{label} must be finite and positive")
    if shared_budget_usd + 1e-12 < smoke_budget_usd + 2 * attempt_budget_usd:
        raise ValueError("shared budget must cover the smoke and both per-attempt ceilings")
    if not 1 <= max_output_tokens <= 8192:
        raise ValueError("max_output_tokens must be from 1 to 8192")
    # Necessary condition for admission: one request reserving its full output limit must fit each stage.
    for label, stage_usd, output_tokens in (
        ("smoke", smoke_budget_usd, SMOKE_MAX_OUTPUT_TOKENS),
        ("per-attempt", attempt_budget_usd, max_output_tokens),
    ):
        if stage_usd + 1e-12 < _max_request_cost_usd(0, output_tokens):
            raise ValueError(
                f"{label} budget cannot admit one request at the {output_tokens}-token output limit"
            )
    return AttemptBudgets(
        max_model_calls=max_model_calls,
        shell_timeout_seconds=shell_timeout_seconds,
        attempt_deadline_seconds=attempt_deadline_seconds,
        max_context_bytes=max_context_bytes,
        max_provider_retries=1,
        provider_retry_delay_seconds=0,
        cleanup_timeout_seconds=5,
        evaluation_timeout_seconds=90,
    )


def _assert_outside(path: Path, roots: tuple[Path, ...], *, label: str) -> None:
    resolved = path.expanduser().resolve()
    if any(resolved == root or root in resolved.parents for root in roots):
        raise ValueError(f"{label} must be outside the harness and pinned source repositories")


def _attempt_is_measurement(result: dict[str, Any]) -> tuple[bool, str | None]:
    termination = result.get("termination_reason")
    evaluation = result.get("evaluation") or {}
    if termination in PROVIDER_OR_HARNESS_TERMINATIONS:
        return False, f"attempt_terminated_{termination}"
    if result.get("functional_verdict") == "invalid_environment":
        return False, "attempt_environment_invalid"
    if evaluation.get("status") == "invalid_patch":
        if (
            result.get("functional_verdict") == "failure"
            and result.get("failure_category") == "invalid_patch"
        ):
            return True, None
        return False, "invalid_patch_verdict_inconsistent"
    if evaluation.get("status") != "completed":
        return False, "canonical_evaluation_incomplete"
    if result.get("functional_verdict") not in {"success", "failure"}:
        return False, "functional_verdict_unavailable"
    return True, None


def _configuration_matches(python_result: dict[str, Any], graph_result: dict[str, Any]) -> tuple[bool, list[str]]:
    left = python_result.get("metadata", {})
    right = graph_result.get("metadata", {})
    fields = (
        ("task_id", "task id"),
        ("task_version", "task version"),
        ("task_identity", "task identity"),
        ("task_package_sha256", "task package fingerprint"),
        ("source_revision", "source revision"),
        ("acceptance_check_version", "acceptance checks"),
        ("provider", "provider"),
        ("requested_model", "requested model"),
        ("provider_endpoint", "provider endpoint"),
        ("model_settings", "model settings"),
        ("dependency_versions", "dependency versions"),
        ("harness_revision", "harness revision"),
        ("budgets", "attempt budgets"),
        ("pricing_source_url", "pricing source"),
        ("pricing_source_checked_at", "pricing source date"),
        ("initial_context_sha256", "initial effective context"),
        ("observed_models", "observed model"),
    )
    mismatches = []
    for key, label in fields:
        left_value, right_value = left.get(key), right.get(key)
        if key == "dependency_versions":
            left_valid = (
                isinstance(left_value, dict) and bool(left_value)
                and all(isinstance(name, str) and name and isinstance(version, str) and version
                        for name, version in left_value.items())
            )
            right_valid = (
                isinstance(right_value, dict) and bool(right_value)
                and all(isinstance(name, str) and name and isinstance(version, str) and version
                        for name, version in right_value.items())
            )
            if not left_valid or not right_valid or left_value != right_value:
                mismatches.append(label)
            continue
        if key == "harness_revision":
            def valid_revision(value: Any) -> bool:
                if not isinstance(value, dict):
                    return False
                commit = value.get("commit")
                state = value.get("working_tree")
                fingerprint = value.get("working_tree_sha256")
                if not isinstance(commit, str) or not commit or state not in {"clean", "dirty"}:
                    return False
                if state == "dirty":
                    return isinstance(fingerprint, str) and len(fingerprint) == 64
                return fingerprint is None

            if not valid_revision(left_value) or not valid_revision(right_value):
                mismatches.append(label)
                continue
        if (left_value in (None, "", []) or right_value in (None, "", [])
                or left_value != right_value):
            mismatches.append(label)
    python_image = left.get("task_image_evidence") or {}
    graph_image = right.get("task_image_evidence") or {}
    for key, label in (
        ("dockerfile_sha256", "task environment recipe"),
        ("runtime_version", "task runtime"),
    ):
        if (not python_image.get(key) or not graph_image.get(key)
                or python_image.get(key) != graph_image.get(key)):
            mismatches.append(label)
    return not mismatches, mismatches


def _attempt_summary(
    result: dict[str, Any], artifact_directory: Path, *, valid: bool, invalid_reason: str | None
) -> dict[str, Any]:
    return {
        "status": "completed",
        "artifact_directory": str(artifact_directory),
        "termination_reason": result.get("termination_reason"),
        "recorded_attempt_verdict": result.get("functional_verdict"),
        "agent_repair_assessment": result.get("functional_verdict") if valid else "not_assessed",
        "evaluation_status": (result.get("evaluation") or {}).get("status"),
        "model_call_count": (result.get("metadata") or {}).get("model_call_count"),
        "failure_category": result.get("failure_category"),
        "valid_measurement": valid,
        "invalid_reason": invalid_reason,
    }


def _render_run_status(experiment: dict[str, Any]) -> str:
    reason = html.escape(str(experiment.get("explanation", "")))
    status = html.escape(str(experiment.get("status", "invalid_measurement")))
    raw_execution_mode = str(experiment.get("execution_mode", "unknown"))
    execution_mode = html.escape(raw_execution_mode)
    run_notice = (
        "Controlled transport fixture: synthetic provider responses were used; no live provider "
        "inference occurred, and this does not satisfy live ticket acceptance."
        if raw_execution_mode == "controlled_transport"
        else "Live HTTPS transport was selected; successful live measurement and review remain pending."
        if raw_execution_mode == "live_https"
        else "Execution mode could not be determined from the run manifest."
    )
    escaped_notice = html.escape(run_notice)
    rows = []
    for name, attempt in experiment.get("attempts", {}).items():
        link = ""
        if attempt.get("status") == "completed":
            link = f'<a href="{html.escape(name)}/report.html">Open attempt report</a>'
        rows.append(
            "<tr><th>" + html.escape(name) + "</th><td>" +
            html.escape(str(attempt.get("status"))) + "</td><td>" +
            html.escape(str(attempt.get("termination_reason", "unavailable"))) +
            "</td><td>" + html.escape(str(attempt.get("agent_repair_assessment", "not_assessed"))) +
            "</td><td>" + link + "</td></tr>"
        )
    attempt_rows = "".join(rows) or '<tr><td colspan="5">No attempts started.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Matched comparison status</title><style>
body{{font:15px/1.55 system-ui,sans-serif;color:#1c2936;background:#edf1f5;margin:0;padding:28px}}
main{{max-width:1000px;margin:0 auto;background:white;padding:24px;border:1px solid #d5dde6;border-radius:12px}}
h1{{margin-top:0}}.status{{display:inline-block;border-radius:18px;padding:3px 11px;background:#fef3c7;color:#713f12;font-weight:700}}
table{{width:100%;border-collapse:collapse;margin-top:18px}}th,td{{text-align:left;border-bottom:1px solid #e3e9ef;padding:9px;vertical-align:top}}
a{{color:#075985}}p{{overflow-wrap:anywhere}}
</style></head><body><main><h1>No valid measurement</h1>
<p>Run status: <span class="status">{status}</span></p><p>Execution mode: <code>{execution_mode}</code>.</p><p>{escaped_notice}</p><p>{reason}</p>
<p>A provider or environment failure is recorded as an invalid measurement. It is not an agent repair failure.</p>
<table><thead><tr><th>Orchestrator</th><th>Run state</th><th>Termination</th><th>Agent repair assessment</th><th>Artifacts</th></tr></thead>
<tbody>{attempt_rows}</tbody></table>
<p>See <a href="experiment.json">experiment.json</a> and <a href="run-plan.json">run-plan.json</a> for machine-readable status and budgets.</p>
</main></body></html>"""


def _finish_invalid(
    root: Path,
    *,
    status: str,
    failure_class: str,
    explanation: str,
    shared_budget: SpendBudget,
    smoke_artifact: Path | None,
    attempts: dict[str, dict[str, Any]],
    completed_at: str,
    execution_mode: str,
) -> dict[str, Any]:
    experiment = {
        "schema_version": "1",
        "status": status,
        "measurement_state": "invalid",
        "valid_measurement": False,
        "failure_class": failure_class,
        "execution_mode": execution_mode,
        "measurement_kind": (
            "controlled_fixture" if execution_mode == "controlled_transport" else "live_https"
        ),
        "live_measurement": False,
        "live_acceptance_status": (
            "pending_live_provider_run_and_human_review"
            if execution_mode == "controlled_transport"
            else "pending_successful_live_measurement_and_human_review"
        ),
        "explanation": explanation,
        "agent_failure_assessment": "not_assessed_due_to_provider_or_environment_failure",
        "agent_attempts": (
            "not_started" if all(item.get("status") == "not_started" for item in attempts.values())
            else "partial"
        ),
        "attempts": attempts,
        "smoke_artifact": str(smoke_artifact) if smoke_artifact else None,
        "shared_spend_budget": shared_budget.snapshot(),
        "completed_at": completed_at,
    }
    _write_json(root / "experiment.json", experiment)
    (root / "report.html").write_text(_render_run_status(experiment), encoding="utf-8")
    return experiment


def run_matched_comparison(
    *,
    admission_evidence: Path,
    parity_evidence: Path,
    source_repository: Path,
    credential_file: Path,
    artifact_directory: Path,
    shared_budget_usd: float = DEFAULT_SHARED_BUDGET_USD,
    smoke_budget_usd: float = DEFAULT_SMOKE_BUDGET_USD,
    attempt_budget_usd: float = DEFAULT_ATTEMPT_BUDGET_USD,
    max_model_calls: int = DEFAULT_MAX_MODEL_CALLS,
    max_context_bytes: int = DEFAULT_MAX_CONTEXT_BYTES,
    attempt_deadline_seconds: float = DEFAULT_ATTEMPT_DEADLINE_SECONDS,
    shell_timeout_seconds: int = DEFAULT_SHELL_TIMEOUT_SECONDS,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    transport: JsonTransport | None = None,
    event_sink_factory: Callable[[str, Path], AttemptEventSink] | None = None,
    attempt_finished: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    """Validate prerequisites, smoke the provider, then run the two matched attempts.

    ``transport`` is the provider HTTP boundary and permits deterministic fixture runs.
    The normal command leaves it unset and uses the bounded HTTPS transport.
    ``event_sink_factory(orchestrator, directory)`` may supply an observer for that attempt;
    ``attempt_finished(orchestrator, directory)`` runs once the attempt directory exists, before
    the comparison is built, so an observer can project its final records. Both are optional and
    leave unobserved behavior unchanged.
    """
    execution_mode = "live_https" if transport is None else "controlled_transport"
    task = AdmittedTask.from_evidence(
        admission_evidence,
        source_repository=source_repository,
    )
    parity = _validate_parity_evidence(parity_evidence, task)
    budgets = _validate_budget_limits(
        shared_budget_usd=shared_budget_usd,
        smoke_budget_usd=smoke_budget_usd,
        attempt_budget_usd=attempt_budget_usd,
        max_model_calls=max_model_calls,
        max_context_bytes=max_context_bytes,
        attempt_deadline_seconds=attempt_deadline_seconds,
        shell_timeout_seconds=shell_timeout_seconds,
        max_output_tokens=max_output_tokens,
    )
    root = artifact_directory.expanduser().resolve()
    if root.exists():
        raise ValueError(f"Matched comparison artifact directory already exists: {root}")
    harness_root = REPOSITORY_ROOT.resolve()
    source_root = task.source_repository.resolve()
    _assert_outside(root, (harness_root, source_root), label="artifact directory")
    credential_path = credential_file.expanduser().resolve()
    _assert_outside(credential_path, (harness_root, source_root), label="credential file")

    root.mkdir(parents=True)
    started_at = _utc_now()
    shared_budget = SpendBudget(shared_budget_usd, name="smoke-plus-matched-attempts")
    model_config = ModelConfig(
        provider="deepseek",
        requested_model="deepseek-flash",
        settings={
            "thinking": "enabled",
            "reasoning_effort": "low",
            "max_output_tokens": max_output_tokens,
        },
    )
    run_plan = {
        "schema_version": "1",
        "status": "configured_before_provider_call",
        "execution_mode": execution_mode,
        "started_at": started_at,
        "task_id": task.task_id,
        "source_revision": task.source_revision,
        "admission_evidence": str(task.admission_evidence_path),
        "scripted_parity_evidence": str(parity_evidence.expanduser().resolve()),
        "provider": "deepseek",
        "endpoint": f"{DEFAULT_BASE_URL}/chat/completions",
        "requested_model": "deepseek-flash",
        "expected_observed_model": "DeepSeek-V4.1-Flash",
        "model_settings": dict(model_config.settings),
        "smoke": {
            "max_output_tokens": SMOKE_MAX_OUTPUT_TOKENS,
            "timeout_seconds": 20,
            "max_retries_per_turn": 1,
            "budget_usd": smoke_budget_usd,
        },
        "attempt_budgets": dict(budgets.__dict__),
        "attempt_output_budget_usd_each": attempt_budget_usd,
        "shared_budget_usd": shared_budget_usd,
        "budget_calibration_status": "experimental_proposal_not_benchmark_accepted",
        "budget_note": (
            "Ceilings are recorded for this first bounded comparison; they are not accepted "
            "benchmark settings or evidence of calibration across repeated runs."
        ),
        "pricing_source_url": PRICING_SOURCE_URL,
        "pricing_source_checked_at": PRICING_SOURCE_CHECKED_AT,
        "credential_source": "private file, read by the outer harness",
        "fresh_baseline_policy": "attempt_and_evaluate prepares a new defective copy per orchestrator",
    }
    _write_json(root / "run-plan.json", run_plan)

    attempts: dict[str, dict[str, Any]] = {
        "python-loop": {"status": "not_started"},
        "langgraph": {"status": "not_started"},
    }
    try:
        api_key = load_credential_file(credential_path)
    except Exception as exc:
        smoke_directory = root / "smoke"
        smoke_directory.mkdir()
        smoke_path = smoke_directory / "smoke.json"
        _write_json(smoke_path, {
            "status": "not_run",
            "error_category": type(exc).__name__,
            "error": "The private credential file could not be read.",
            "provider": "deepseek",
            "account_access": "unverified",
            "completed_at": _utc_now(),
        })
        return _finish_invalid(
            root,
            status="preflight_failed",
            failure_class="credential_preflight",
            explanation="The private credential file was unavailable; no provider call or agent attempt started.",
            shared_budget=shared_budget,
            smoke_artifact=smoke_path,
            attempts=attempts,
            completed_at=_utc_now(),
            execution_mode=execution_mode,
        )

    smoke_budget = SpendBudget(smoke_budget_usd, name="DeepSeek smoke", parent=shared_budget)
    smoke_adapter = DeepSeekModelAdapter(
        api_key=api_key,
        transport=transport,
        spend_budget=smoke_budget,
    )
    smoke = run_smoke(
        adapter=smoke_adapter,
        timeout_seconds=20,
        max_output_tokens=SMOKE_MAX_OUTPUT_TOKENS,
        max_retries=1,
    )
    smoke_path = write_smoke_artifact(smoke, root / "smoke")
    if smoke.get("status") != "passed":
        return _finish_invalid(
            root,
            status="preflight_failed",
            failure_class="provider_preflight",
            explanation=(
                "The bounded provider smoke did not complete its tool-call continuation; "
                "neither repair attempt started. This is not an agent repair failure."
            ),
            shared_budget=shared_budget,
            smoke_artifact=smoke_path,
            attempts=attempts,
            completed_at=_utc_now(),
            execution_mode=execution_mode,
        )

    attempt_summary: dict[str, dict[str, Any]] = {
        "python-loop": {"status": "not_started"},
        "langgraph": {"status": "not_started"},
    }
    results: dict[str, dict[str, Any]] = {}
    for orchestrator in ("python-loop", "langgraph"):
        attempt_budget = SpendBudget(
            attempt_budget_usd,
            name=f"{orchestrator} repair attempt",
            parent=shared_budget,
        )
        model = DeepSeekModelAdapter(
            api_key=api_key,
            transport=transport,
            spend_budget=attempt_budget,
        )
        directory = root / orchestrator
        sink = event_sink_factory(orchestrator, directory) if event_sink_factory else None
        result: dict[str, Any] | None = None
        try:
            result = attempt_and_evaluate(
                admitted_task=task,
                model=model,
                model_config=model_config,
                budgets=budgets,
                artifact_directory=directory,
                orchestrator=orchestrator,
                event_sink=sink,
            )
        except KeyboardInterrupt:
            result = None
        finally:
            if attempt_finished is not None and directory.is_dir():
                attempt_finished(orchestrator, directory)
        if result is None:
            return _finish_invalid(
                root,
                status="invalid_measurement",
                failure_class="interrupted_attempt",
                explanation=(
                    f"The {orchestrator} attempt was interrupted. Partial attempt artifacts "
                    "were retained where the attempt boundary could collect them."
                ),
                shared_budget=shared_budget,
                smoke_artifact=smoke_path,
                attempts=attempt_summary,
                completed_at=_utc_now(),
                execution_mode=execution_mode,
            )
        results[orchestrator] = result
        valid, invalid_reason = _attempt_is_measurement(result)
        attempt_summary[orchestrator] = _attempt_summary(
            result,
            directory,
            valid=valid,
            invalid_reason=invalid_reason,
        )
        if not valid:
            return _finish_invalid(
                root,
                status="invalid_measurement",
                failure_class=(
                    "provider_attempt" if result.get("termination_reason") == "provider_error"
                    else "attempt_environment"
                ),
                explanation=(
                    f"The {orchestrator} attempt did not produce a valid evaluated measurement "
                    f"({invalid_reason}). It is not counted as an agent repair failure and the "
                    "remaining matched attempt was skipped."
                ),
                shared_budget=shared_budget,
                smoke_artifact=smoke_path,
                attempts=attempt_summary,
                completed_at=_utc_now(),
                execution_mode=execution_mode,
            )

    python_result = results["python-loop"]
    graph_result = results["langgraph"]
    matched, mismatches = _configuration_matches(python_result, graph_result)
    report_path: Path | None = None
    report_error: str | None = None
    try:
        report_path = build_comparison_report(
            root / "python-loop",
            root / "langgraph",
            root / "report.html",
            run_notice=(
                "Controlled transport fixture: this deterministic pair used synthetic provider responses; "
                "no live provider inference occurred and this does not satisfy live ticket acceptance."
                if execution_mode == "controlled_transport"
                else "Live HTTPS transport was selected. Qualitative review and ticket acceptance remain pending."
            ),
        )
    except Exception as exc:
        report_error = type(exc).__name__

    valid_measurement = matched and report_path is not None
    agent_failures = {
        name: (result.get("functional_verdict") == "failure")
        for name, result in results.items()
    }
    experiment = {
        "schema_version": "1",
        "status": "completed" if valid_measurement else (
            "configuration_mismatch" if not matched else "report_failed"
        ),
        "measurement_state": "valid" if valid_measurement else "invalid",
        "valid_measurement": valid_measurement,
        "execution_mode": execution_mode,
        "measurement_kind": (
            "controlled_fixture" if execution_mode == "controlled_transport" else "live_https"
        ),
        "live_measurement": execution_mode == "live_https" and valid_measurement,
        "live_acceptance_status": (
            "pending_live_provider_run_and_human_review"
            if execution_mode == "controlled_transport"
            else "pending_human_review" if valid_measurement
            else "pending_successful_live_measurement_and_human_review"
        ),
        "failure_class": None if valid_measurement else (
            "configuration_mismatch" if not matched else "report_generation"
        ),
        "configuration_match": matched,
        "configuration_mismatches": mismatches,
        "agent_failure_assessment": "completed_attempts_evaluated",
        "agent_attempts": "both_completed",
        "agent_failures": agent_failures,
        "task_id": task.task_id,
        "source_revision": task.source_revision,
        "started_at": started_at,
        "completed_at": _utc_now(),
        "provider": "deepseek",
        "requested_model": "deepseek-flash",
        "expected_observed_model": "DeepSeek-V4.1-Flash",
        "smoke_artifact": str(smoke_path),
        "attempts": attempt_summary,
        "report": str(report_path) if report_path else None,
        "report_error_category": report_error,
        "budget_limits_usd": {
            "smoke": smoke_budget_usd,
            "each_repair_attempt": attempt_budget_usd,
            "shared_total": shared_budget_usd,
        },
        "budget_calibration_status": run_plan["budget_calibration_status"],
        "shared_spend_budget": shared_budget.snapshot(),
        "usage_by_orchestrator": {
            name: result.get("metadata", {}).get("usage_by_call", [])
            for name, result in results.items()
        },
        "limitations": [
            "One task and one attempt per orchestrator do not establish reliable rankings.",
            "Live generated patches may differ; compare their traces and independent checks.",
            "These cost ceilings are experimental proposals, not accepted benchmark settings.",
        ],
    }
    _write_json(root / "experiment.json", experiment)
    if not valid_measurement:
        (root / "report.html").write_text(_render_run_status(experiment), encoding="utf-8")
    return experiment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-file", type=Path, required=True,
                        help="private plain-text DeepSeek key; read only by the outer harness")
    parser.add_argument("--admission-evidence", type=Path, default=DEFAULT_ADMISSION_EVIDENCE)
    parser.add_argument("--parity-evidence", type=Path, default=DEFAULT_PARITY_EVIDENCE)
    parser.add_argument("--source-repository", type=Path, default=DEFAULT_SOURCE_REPOSITORY)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--shared-budget-usd", type=float, default=DEFAULT_SHARED_BUDGET_USD)
    parser.add_argument("--smoke-budget-usd", type=float, default=DEFAULT_SMOKE_BUDGET_USD)
    parser.add_argument("--attempt-budget-usd", type=float, default=DEFAULT_ATTEMPT_BUDGET_USD)
    parser.add_argument("--max-model-calls", type=int, default=DEFAULT_MAX_MODEL_CALLS)
    parser.add_argument("--max-context-bytes", type=int, default=DEFAULT_MAX_CONTEXT_BYTES)
    parser.add_argument("--attempt-deadline-seconds", type=float,
                        default=DEFAULT_ATTEMPT_DEADLINE_SECONDS)
    parser.add_argument("--shell-timeout-seconds", type=int, default=DEFAULT_SHELL_TIMEOUT_SECONDS)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    args = parser.parse_args(argv)
    try:
        result = run_matched_comparison(
            admission_evidence=args.admission_evidence,
            parity_evidence=args.parity_evidence,
            source_repository=args.source_repository,
            credential_file=args.credential_file,
            artifact_directory=args.artifact_dir,
            shared_budget_usd=args.shared_budget_usd,
            smoke_budget_usd=args.smoke_budget_usd,
            attempt_budget_usd=args.attempt_budget_usd,
            max_model_calls=args.max_model_calls,
            max_context_bytes=args.max_context_bytes,
            attempt_deadline_seconds=args.attempt_deadline_seconds,
            shell_timeout_seconds=args.shell_timeout_seconds,
            max_output_tokens=args.max_output_tokens,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": result["status"],
        "valid_measurement": result["valid_measurement"],
        "agent_failure_assessment": result["agent_failure_assessment"],
        "artifact_directory": str(args.artifact_dir.expanduser().resolve()),
        "report": str(args.artifact_dir.expanduser().resolve() / "report.html"),
        "experiment": str(args.artifact_dir.expanduser().resolve() / "experiment.json"),
    }, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if result["valid_measurement"] else 2


if __name__ == "__main__":
    sys.exit(main())

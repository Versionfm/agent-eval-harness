"""Run one coding-agent attempt through the shared Python or LangGraph lifecycle."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Mapping

from agent_eval_harness.environment import (
    DockerTaskContainer,
    EnvironmentFailure,
    build_task_environment,
    prepare_defective_repository,
    run_canonical_checks,
)
from agent_eval_harness.admission import task_package_evidence
from agent_eval_harness.capture import CaptureLimits, RepositoryCapture
from agent_eval_harness.model import (
    ModelAdapter,
    ModelConfig,
    ModelRequest,
    ModelResponse,
    RequestBudgetExceeded,
    RetryableProviderError,
    ScriptedModel,
    ToolCall,
)
from agent_eval_harness.observation import (
    NULL_EVENT_SINK, AttemptEventSink, EventRecordingError, json_artifact,
)
from agent_eval_harness.paths import orchestration_root
from agent_eval_harness.report import render_attempt_report

# Stable facade imports: callers and existing experiments keep the attempt.py seam.
from agent_eval_harness.builtins import apply_patch as container_apply_patch
from agent_eval_harness.builtins import read_file as container_read_file
from agent_eval_harness.builtins import run_shell as container_run_shell
from agent_eval_harness.builtins import search_text as container_search_text
from agent_eval_harness.context import (
    _assistant_message, _context_size_bytes, _json_copy, _json_default,
    _tool_output_for_model,
)
from agent_eval_harness.evaluation import (
    _apply_candidate_changes, _candidate_changes, _candidate_diff,
    _finalize_evaluation, _materialize_snapshot, _safe_candidate_path,
    _snapshot_repository, collect_candidate,
    evaluate_candidate_changes as _evaluate_candidate_changes_impl,
)
from agent_eval_harness.loop import (
    ModelCallDeadlineExceeded, _complete_with_deadline, _request_model_turn,
    run_python_loop,
)
from agent_eval_harness.persistence import (
    _collect_artifacts, _record, _timestamp,
)
from agent_eval_harness.prompt import build_initial_context as _initial_context
from agent_eval_harness.provenance import (
    _dependency_versions, _harness_provenance,
)
from agent_eval_harness.tools import (
    TOOL_DEFINITIONS, _classify_tool_result, _dispatch_tool,
    execute_tool_turn as _execute_tool_turn,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATION_ROOT = orchestration_root(REPOSITORY_ROOT)
DEFAULT_TASK_PACKAGE = REPOSITORY_ROOT / "tasks" / "ml_tutor_retrieval"
DEFAULT_ADMISSION_EVIDENCE = (
    ORCHESTRATION_ROOT / "evidence" / "issue-2" / "admission.json"
)
DEFAULT_SOURCE_REPOSITORY = Path("/home/francisco/prompt-engineering-group-project")


@dataclass(frozen=True)
class AttemptBudgets:
    """Configurable calibration proposals for one attempt, not benchmark defaults."""

    max_model_calls: int = 30
    shell_timeout_seconds: int = 60
    tool_output_limit_bytes: int = 16 * 1024
    attempt_deadline_seconds: float = 600
    max_context_bytes: int = 128 * 1024
    max_provider_retries: int = 1
    provider_retry_delay_seconds: float = 0
    cleanup_timeout_seconds: float = 5
    evaluation_timeout_seconds: float = 90
    max_graph_steps: int | None = None

    def __post_init__(self) -> None:
        if self.max_model_calls < 1:
            raise ValueError("max_model_calls must be positive")
        if self.shell_timeout_seconds < 1:
            raise ValueError("shell_timeout_seconds must be positive")
        if self.tool_output_limit_bytes < 128:
            raise ValueError("tool_output_limit_bytes must be at least 128")
        if self.attempt_deadline_seconds <= 0:
            raise ValueError("attempt_deadline_seconds must be positive")
        if self.max_context_bytes < 1:
            raise ValueError("max_context_bytes must be positive")
        if self.max_provider_retries < 0:
            raise ValueError("max_provider_retries cannot be negative")
        if self.provider_retry_delay_seconds < 0:
            raise ValueError("provider_retry_delay_seconds cannot be negative")
        if self.cleanup_timeout_seconds <= 0:
            raise ValueError("cleanup_timeout_seconds must be positive")
        if self.evaluation_timeout_seconds <= 0:
            raise ValueError("evaluation_timeout_seconds must be positive")
        if self.max_graph_steps is not None and self.max_graph_steps < 1:
            raise ValueError("max_graph_steps must be positive")


@dataclass(frozen=True)
class AdmittedTask:
    task_id: str
    task_version: str
    source_revision: str
    acceptance_check_version: str
    task_identity: dict[str, Any]
    task_package_sha256: str
    source_repository: Path
    image: str
    runtime_version: str
    public_task_path: Path
    defect_mutation_path: Path
    evaluator_directory: Path
    dockerfile_path: Path
    expected_base_image: str
    admission_evidence_path: Path

    @classmethod
    def from_evidence(
        cls,
        evidence_path: Path = DEFAULT_ADMISSION_EVIDENCE,
        *,
        source_repository: Path = DEFAULT_SOURCE_REPOSITORY,
        task_package: Path = DEFAULT_TASK_PACKAGE,
    ) -> "AdmittedTask":
        evidence_path = evidence_path.expanduser().resolve()
        task_package = task_package.expanduser().resolve()
        source_repository = source_repository.expanduser().resolve()
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if evidence.get("assessment", {}).get("status") != "admitted":
            raise ValueError("attempts require task evidence with an admitted assessment")
        manifest = json.loads((task_package / "manifest.json").read_text(encoding="utf-8"))
        if evidence.get("source_revision") != manifest.get("source", {}).get("revision"):
            raise ValueError("admission evidence and task manifest pin different source revisions")
        current_package = task_package_evidence(task_package, manifest)
        if evidence.get("task_package") != current_package:
            raise ValueError(
                "admission evidence does not bind the current task identity and package contents; "
                "rerun task admission before attempting this package"
            )
        environment = evidence.get("environment_evidence") or {}
        image = environment.get("image_tag")
        image_id = environment.get("image_id")
        if not isinstance(image, str) or not image or not isinstance(image_id, str):
            raise ValueError("admission evidence does not identify a prepared Docker image")
        return cls(
            task_id=manifest["task_id"],
            task_version=manifest["task_version"],
            source_revision=manifest["source"]["revision"],
            acceptance_check_version=manifest["acceptance_check_version"],
            task_identity=current_package["identity"],
            task_package_sha256=current_package["sha256"],
            source_repository=source_repository,
            image=image,
            runtime_version=manifest["environment"]["runtime"].removeprefix("Python "),
            public_task_path=task_package / manifest["files"]["public_task"],
            defect_mutation_path=task_package / manifest["files"]["defect_mutation"],
            evaluator_directory=task_package / "curator",
            dockerfile_path=task_package / manifest["files"]["dockerfile"],
            expected_base_image=manifest["environment"]["image"],
            admission_evidence_path=evidence_path,
        )


def _finalize_accounting(
    result: dict[str, Any], model: ModelAdapter, model_call_count: int,
    usage_records: list[dict[str, Any]], trace: list[dict[str, Any]],
) -> None:
    metadata = result["metadata"]
    metadata["model_call_count"] = model_call_count
    metadata["retry_count"] = metadata.get("retry_count", 0)
    metadata["usage_by_call"] = usage_records
    metadata["observed_models"] = _observed_models(usage_records)
    metadata["cost"] = _cost_summary(usage_records, trace)
    snapshotter = getattr(model, "accounting_snapshot", None)
    if callable(snapshotter):
        try:
            metadata["spend_budget"] = snapshotter()
        except Exception as exc:
            metadata["spend_budget"] = {
                "status": "unavailable",
                "error_category": "accounting_snapshot_error",
                "error": f"{type(exc).__name__}: {exc}",
            }


def _cost_summary(usage_records: list[dict[str, Any]], trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize provider evidence without turning missing usage into charges."""
    model_events = [event for event in trace if event.get("type") == "model"]
    request_events = [
        event for event in model_events if event.get("status") != "budget_stopped"
    ]
    billing_records = [
        usage.get("billing") for usage in usage_records
        if isinstance(usage, dict) and isinstance(usage.get("billing"), dict)
    ]
    if not billing_records:
        unavailable = {"status": "unavailable", "amount": None, "currency": "USD"}
        return {"reported": dict(unavailable), "estimated": dict(unavailable)}

    known_estimates = []
    known_reports = []
    for billing in billing_records:
        estimate = billing.get("estimated_cost", {})
        if (isinstance(estimate, dict) and estimate.get("status") == "estimated"
                and isinstance(estimate.get("amount"), (int, float))):
            known_estimates.append(float(estimate["amount"]))
        report = billing.get("reported_cost", {})
        if (isinstance(report, dict) and report.get("status") == "reported"
                and isinstance(report.get("amount"), (int, float))):
            known_reports.append(float(report["amount"]))

    missing = max(0, len(request_events) - len(known_estimates))
    if known_estimates:
        estimated = {
            "status": "partial" if missing else "estimated",
            "amount": round(sum(known_estimates), 12),
            "currency": "USD",
            "missing_usage_calls": missing,
            "request_count": len(request_events),
        }
    else:
        estimated = {
            "status": "unavailable", "amount": None, "currency": "USD",
            "missing_usage_calls": len(request_events),
            "request_count": len(request_events),
        }

    missing_reports = max(0, len(request_events) - len(known_reports))
    if known_reports:
        reported = {
            "status": "partial" if missing_reports else "reported",
            "amount": round(sum(known_reports), 12),
            "currency": "USD",
            "missing_charge_calls": missing_reports,
            "request_count": len(request_events),
        }
    else:
        reported = {
            "status": "unavailable", "amount": None, "currency": "USD",
            "missing_charge_calls": len(request_events),
            "request_count": len(request_events),
        }
    return {"reported": reported, "estimated": estimated}


def _observed_models(usage_records: list[dict[str, Any]]) -> list[str]:
    models = []
    for usage in usage_records:
        model_name = usage.get("observed_model") if isinstance(usage, dict) else None
        if isinstance(model_name, str) and model_name and model_name not in models:
            models.append(model_name)
    return models


def _selected_point_state(
    messages: list[dict[str, Any]], model_call_count: int, *, budgets: Any,
    usage_records: list[dict[str, Any]], trace: list[dict[str, Any]],
) -> dict[str, Any]:
    """Budget, context and accounting facts known from history so far (observer copy only)."""
    usage_totals: dict[str, float] = {}
    for usage in usage_records:
        for key, value in usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage_totals[key] = usage_totals.get(key, 0) + value
    cost = _cost_summary(usage_records, trace)
    return {
        "model_calls": model_call_count,
        "max_model_calls": budgets.max_model_calls,
        "context_bytes": _context_size_bytes(messages),
        "max_context_bytes": budgets.max_context_bytes,
        "tool_result_messages": sum(1 for message in messages if message.get("role") == "tool"),
        "tool_output_limit_bytes": budgets.tool_output_limit_bytes,
        "attempt_deadline_seconds": budgets.attempt_deadline_seconds,
        "usage_totals": usage_totals,
        "estimated_cost": cost["estimated"],
        "reported_cost": cost["reported"],
    }


def _evaluate_candidate_changes(
    defect_repository: Path,
    changes: list[dict[str, Any]],
    *,
    image_id: str,
    admitted_task: AdmittedTask,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Evaluate a candidate while preserving the historical attempt.py seam."""
    return _evaluate_candidate_changes_impl(
        defect_repository, changes, image_id=image_id, admitted_task=admitted_task,
        timeout_seconds=timeout_seconds, canonical_check_runner=run_canonical_checks,
    )


def attempt_and_evaluate(
    *,
    admitted_task: AdmittedTask,
    model: ModelAdapter,
    model_config: ModelConfig,
    budgets: AttemptBudgets,
    artifact_directory: Path,
    orchestrator: str = "python-loop",
    event_sink: AttemptEventSink | None = None,
    capture_limits: CaptureLimits | None = None,
) -> dict[str, Any]:
    """Execute an explicit tool loop, capture its patch, and score a fresh defect copy.

    An optional event_sink observes phases or graph nodes and routing, model/tool
    starts and outcomes, and selected-point state. Mandatory emits are synchronous:
    if one raises, no further node, model or tool operation runs. An observed attempt
    also records bounded repository changes after mutating tools (capture_limits).
    """
    sink: AttemptEventSink = NULL_EVENT_SINK if event_sink is None else event_sink
    artifact_directory = artifact_directory.expanduser().resolve()
    if artifact_directory.exists():
        raise ValueError(f"Artifact destination already exists: {artifact_directory}")
    if REPOSITORY_ROOT == artifact_directory or REPOSITORY_ROOT in artifact_directory.parents:
        raise ValueError("attempt artifacts must be outside the harness Git repository")
    artifact_directory.parent.mkdir(parents=True, exist_ok=True)
    if admitted_task.source_repository == artifact_directory or admitted_task.source_repository in artifact_directory.parents:
        raise ValueError("attempt artifacts must be outside the pinned source repository")
    if orchestrator not in {"python-loop", "langgraph"}:
        raise ValueError("orchestrator must be 'python-loop' or 'langgraph'")

    task_repository = artifact_directory / "task-repository"
    trace: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "termination_reason": "harness_error",
        "functional_verdict": "invalid_environment",
        "duration_seconds": 0.0,
        "trace": trace,
        "candidate": {"status": "unavailable", "changed_files": [], "files": [], "patch": ""},
        "evaluation": {"status": "error", "checks": {}, "error": "evaluation not run"},
        "initial_context": [],
        "metadata": {
            "schema_version": "1",
            "task_id": admitted_task.task_id,
            "task_version": admitted_task.task_version,
            "source_revision": admitted_task.source_revision,
            "acceptance_check_version": admitted_task.acceptance_check_version,
            "task_identity": _json_copy(admitted_task.task_identity),
            "task_package_sha256": admitted_task.task_package_sha256,
            "requested_model": model_config.requested_model,
            "provider": model_config.provider,
            "model_settings": _json_copy(dict(model_config.settings)),
            "orchestrator": orchestrator,
            "budgets": _json_copy(budgets.__dict__),
            "budget_calibration_status": "configurable_proposal",
            "budget_calibration_note": (
                "Numeric values are configurable proposals; calibrate before benchmark comparisons."
            ),
            "started_at": _timestamp(),
            "admission_evidence": str(admitted_task.admission_evidence_path),
            "task_container_image": admitted_task.image,
            "admission_recorded_image_id": json.loads(
                admitted_task.admission_evidence_path.read_text(encoding="utf-8")
            ).get("environment_evidence", {}).get("image_id"),
            "runtime_version": admitted_task.runtime_version,
            "harness_revision": _harness_provenance(),
            "dependency_versions": _dependency_versions(),
            "cost": {"status": "unavailable", "amount": None, "currency": None},
            "qualitative_review": {"status": "pending"},
        },
    }
    provider_metadata = getattr(model, "run_metadata", None)
    if callable(provider_metadata):
        try:
            result["metadata"].update(_json_copy(provider_metadata()))
        except Exception as exc:
            result["metadata"]["provider_metadata_error"] = (
                f"{type(exc).__name__}: {exc}"
            )
    started = time.monotonic()
    attempt_deadline = started + budgets.attempt_deadline_seconds
    work_deadline = attempt_deadline - budgets.cleanup_timeout_seconds
    defect_baseline: dict[str, tuple[bytes, int]] = {}
    attempt_container: DockerTaskContainer | None = None
    repository_capture: RepositoryCapture | None = None
    model_call_count = 0
    usage_records = []
    harness_error: str | None = None

    try:
        image_evidence = build_task_environment(
            admitted_task.dockerfile_path,
            admitted_task.dockerfile_path.parent,
            expected_base_image=admitted_task.expected_base_image,
            expected_python_version=admitted_task.runtime_version,
            deadline=work_deadline,
        )
        image_evidence["admission_image_id"] = result["metadata"]["admission_recorded_image_id"]
        result["metadata"]["task_image_evidence"] = image_evidence
        with tempfile.TemporaryDirectory(prefix="agent-eval-fresh-defect-") as scratch:
            defect_repository = Path(scratch) / "defect-repository"
            prepare_defective_repository(
                admitted_task.source_repository,
                admitted_task.source_revision,
                admitted_task.defect_mutation_path,
                defect_repository,
                deadline=work_deadline,
            )
            defect_baseline = _snapshot_repository(defect_repository)
            shutil.copytree(defect_repository, task_repository)
            attempt_container = DockerTaskContainer(image_evidence["image_id"], task_repository)
            attempt_container.start(
                timeout_seconds=budgets.attempt_deadline_seconds, deadline=work_deadline
            )
            result["attempt_container_configuration"] = attempt_container.configuration
            result["metadata"]["attempt_repository"] = str(task_repository)
            if sink is not NULL_EVENT_SINK:
                repository_capture = RepositoryCapture(
                    attempt_container, task_repository, defect_baseline, capture_limits,
                )
            sink.emit("attempt_started", {
                "task_id": admitted_task.task_id, "orchestrator": orchestrator,
                "requested_model": model_config.requested_model, "provider": model_config.provider,
                "budgets": _json_copy(budgets.__dict__),
            })

            messages = _initial_context(admitted_task, task_repository)
            result["initial_context"] = copy.deepcopy(messages)
            result["metadata"]["initial_context_sha256"] = hashlib.sha256(
                json.dumps(
                    messages,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            _record(
                trace,
                "initial_context",
                status="ready",
                message_count=len(messages),
                tool_definitions=TOOL_DEFINITIONS,
                messages=messages,
            )
            sink.emit(
                "initial_context", {"message_count": len(messages), "tool_definitions": TOOL_DEFINITIONS},
                {"messages.json": json_artifact(messages)},
            )

            def snapshot_state(
                current_messages: list[dict[str, Any]], current_count: int
            ) -> dict[str, Any]:
                return _selected_point_state(
                    current_messages, current_count, budgets=budgets,
                    usage_records=usage_records, trace=trace,
                )

            snapshot = None if sink is NULL_EVENT_SINK else snapshot_state
            termination = "harness_error"
            if orchestrator == "langgraph":
                from agent_eval_harness.langgraph_attempt import run_attempt_graph

                graph_step_limit = (
                    budgets.max_graph_steps
                    if budgets.max_graph_steps is not None
                    else 2 * budgets.max_model_calls + 1
                )

                def graph_model_step(state: dict[str, Any]) -> dict[str, Any]:
                    graph_messages = list(state["messages"])
                    previous_count = len(graph_messages)
                    response, calls, stop_reason = _request_model_turn(
                        messages=graph_messages,
                        model=model,
                        model_config=model_config,
                        budgets=budgets,
                        work_deadline=work_deadline,
                        trace=trace,
                        result=result,
                        usage_records=usage_records,
                        model_call_count=state["model_call_count"],
                        event_sink=sink,
                    )
                    return {
                        "messages": graph_messages[previous_count:],
                        "model_response": response,
                        "model_call_count": calls,
                        "termination_reason": stop_reason,
                    }

                def graph_tool_step(state: dict[str, Any]) -> dict[str, Any]:
                    graph_messages = list(state["messages"])
                    previous_count = len(graph_messages)
                    response = state["model_response"]
                    if response is None:
                        raise RuntimeError("tool node requires a model response")
                    stop_reason = _execute_tool_turn(
                        response=response,
                        messages=graph_messages,
                        model_call_count=state["model_call_count"],
                        container=attempt_container,
                        budgets=budgets,
                        work_deadline=work_deadline,
                        trace=trace,
                        event_sink=sink,
                        repository_capture=repository_capture,
                    )
                    return {
                        "messages": graph_messages[previous_count:],
                        "model_response": response,
                        "model_call_count": state["model_call_count"],
                        "termination_reason": stop_reason,
                    }

                graph_state = run_attempt_graph(
                    initial_messages=messages,
                    model_step=graph_model_step,
                    tool_step=graph_tool_step,
                    max_graph_steps=graph_step_limit,
                    event_sink=sink,
                    snapshot=snapshot,
                )
                messages = graph_state["messages"]
                model_call_count = graph_state["model_call_count"]
                termination = graph_state["termination_reason"] or "graph_step_budget"
                result["metadata"]["graph_step_count"] = graph_state["graph_step_count"]
                result["metadata"]["graph_step_limit"] = graph_step_limit
                result["metadata"]["graph_step_limit_source"] = (
                    "configured_graph_only_budget"
                    if budgets.max_graph_steps is not None
                    else "derived_from_model_call_budget"
                )
                if termination == "graph_step_budget":
                    _record(
                        trace, "termination", reason=termination,
                        graph_steps=graph_state["graph_step_count"],
                        max_graph_steps=graph_step_limit,
                        model_calls=model_call_count,
                    )
            else:
                def request_python_turn(
                    current_messages: list[dict[str, Any]], current_count: int
                ) -> tuple[ModelResponse | None, int, str | None]:
                    return _request_model_turn(
                        messages=current_messages,
                        model=model,
                        model_config=model_config,
                        budgets=budgets,
                        work_deadline=work_deadline,
                        trace=trace,
                        result=result,
                        usage_records=usage_records,
                        model_call_count=current_count,
                        event_sink=sink,
                    )

                def execute_python_turn(
                    response: ModelResponse,
                    current_messages: list[dict[str, Any]],
                    current_count: int,
                ) -> str | None:
                    return _execute_tool_turn(
                        response=response,
                        messages=current_messages,
                        model_call_count=current_count,
                        container=attempt_container,
                        budgets=budgets,
                        work_deadline=work_deadline,
                        trace=trace,
                        event_sink=sink,
                        repository_capture=repository_capture,
                    )

                termination, model_call_count = run_python_loop(
                    messages,
                    request_model=request_python_turn,
                    execute_tools=execute_python_turn,
                    event_sink=sink,
                    snapshot=snapshot,
                )

            result["termination_reason"] = termination
            result["attempt_container_configuration"] = attempt_container.configuration
            cleanup_timeout = min(
                budgets.cleanup_timeout_seconds,
                max(0.01, attempt_deadline - time.monotonic()),
            )
            attempt_container.close(timeout_seconds=cleanup_timeout)
            attempt_container = None
            result["metadata"]["attempt_duration_seconds"] = round(
                time.monotonic() - started, 6
            )

            try:
                result["candidate"] = collect_candidate(task_repository, defect_baseline)
                changes = result["candidate"]["files"]
            except EnvironmentFailure as exc:
                changes = []
                result["candidate"] = {
                    "status": "unavailable",
                    "changed_files": [],
                    "files": [],
                    "patch": "",
                    "collection_error": str(exc),
                }
                _record(
                    trace, "patch_collection", status="unavailable",
                    error_category="invalid_patch", error=str(exc),
                )
                result["evaluation"] = {
                    "status": "invalid_patch", "checks": {}, "error": str(exc)
                }
            else:
                _record(
                    trace,
                    "patch_collection",
                    status="completed",
                    changed_files=result["candidate"]["changed_files"],
                    change_count=len(changes),
                )

            if result["candidate"]["status"] == "collected":
                evaluation = _evaluate_candidate_changes(
                    defect_repository,
                    changes,
                    image_id=image_evidence["image_id"],
                    admitted_task=admitted_task,
                    timeout_seconds=budgets.evaluation_timeout_seconds,
                )
                _finalize_evaluation(result, evaluation, trace)
            elif result["candidate"].get("status") == "unavailable":
                _finalize_evaluation(result, result["evaluation"], trace)
    except KeyboardInterrupt as exc:
        result["termination_reason"] = "interrupted"
        result["functional_verdict"] = "invalid_environment"
        result["failure_category"] = "interrupted_before_evaluation"
        result["evaluation"] = {
            "status": "error", "checks": {},
            "error": "Attempt interrupted before evaluation completed.",
        }
        _record(
            trace, "interruption", status="interrupted",
            error=f"{type(exc).__name__}: {exc}",
        )
    except EventRecordingError as exc:
        # A mandatory record failed: no further operation ran; the candidate is recovered in cleanup.
        harness_error = f"{type(exc).__name__}: {exc}"
        result["harness_error"] = harness_error
        result["recording"] = {"status": "failed", "error": str(exc)}
        result["termination_reason"] = "harness_error"
        result["failure_category"] = "recording_failure"
        result["functional_verdict"] = "invalid_environment"
        result["evaluation"] = {"status": "error", "checks": {}, "error": harness_error}
        _record(trace, "harness_error", status="error", error=harness_error)
    except Exception as exc:
        harness_error = f"{type(exc).__name__}: {exc}"
        result["harness_error"] = harness_error
        if time.monotonic() >= work_deadline:
            result["termination_reason"] = "attempt_deadline"
            result["failure_category"] = "environment_setup_deadline"
            _record(trace, "termination", reason="attempt_deadline", error=harness_error)
        else:
            result["termination_reason"] = "harness_error"
            result["failure_category"] = "harness_environment_failure"
            _record(trace, "harness_error", status="error", error=harness_error)
        result["functional_verdict"] = "invalid_environment"
        result["evaluation"] = {"status": "error", "checks": {}, "error": harness_error}
    finally:
        if attempt_container is not None:
            try:
                remaining = attempt_deadline - time.monotonic()
                attempt_container.close(
                    timeout_seconds=max(
                        0.001, min(budgets.cleanup_timeout_seconds, remaining)
                    )
                )
            except Exception as exc:
                cleanup_error = f"{type(exc).__name__}: {exc}"
                result.setdefault("cleanup_error", cleanup_error)
                _record(trace, "cleanup_error", status="error", error=cleanup_error)
        _finalize_accounting(result, model, model_call_count, usage_records, trace)
        if repository_capture is not None:
            result["metadata"]["repository_capture"] = repository_capture.summary()
        result["metadata"].setdefault(
            "attempt_duration_seconds", round(time.monotonic() - started, 6)
        )
        candidate = result.get("candidate", {})
        if (
            candidate.get("status") == "unavailable"
            and not candidate.get("collection_error")
            and task_repository.is_dir()
            and defect_baseline
        ):
            try:
                result["candidate"] = collect_candidate(task_repository, defect_baseline)
                changes = result["candidate"]["files"]
                _record(
                    trace, "patch_collection", status="completed_during_cleanup",
                    changed_files=result["candidate"]["changed_files"],
                    change_count=len(changes),
                )
                image_evidence = result["metadata"].get("task_image_evidence")
                if image_evidence:
                    with tempfile.TemporaryDirectory(prefix="agent-eval-recovered-evaluator-") as scratch:
                        defective = Path(scratch) / "defect-repository"
                        _materialize_snapshot(defective, defect_baseline)
                        evaluation = _evaluate_candidate_changes(
                            defective,
                            changes,
                            image_id=image_evidence["image_id"],
                            admitted_task=admitted_task,
                            timeout_seconds=budgets.evaluation_timeout_seconds,
                        )
                    _finalize_evaluation(result, evaluation, trace)
            except EnvironmentFailure as exc:
                evaluation = {"status": "invalid_patch", "checks": {}, "error": str(exc)}
                result["candidate"] = {
                    "status": "unavailable", "changed_files": [], "files": [],
                    "patch": "", "collection_error": str(exc),
                }
                _record(trace, "patch_collection", status="unavailable",
                        error_category="invalid_patch", error=str(exc))
                _finalize_evaluation(result, evaluation, trace)
        result["duration_seconds"] = round(time.monotonic() - started, 6)
        result["metadata"]["duration_seconds"] = result["duration_seconds"]
        result["metadata"]["finished_at"] = _timestamp()
        try:
            sink.emit(
                "attempt_finished", {
                    "termination_reason": result["termination_reason"],
                    "functional_verdict": result["functional_verdict"],
                    "failure_category": result.get("failure_category"),
                    "changed_files": result["candidate"].get("changed_files", []),
                    "checks": result["evaluation"].get("checks", {}),
                },
                {"candidate.patch": result["candidate"].get("patch", "").encode("utf-8")},
            )
        except EventRecordingError as exc:
            # The result is still returned; an earlier failure keeps its own message.
            result.setdefault("recording", {"status": "failed", "error": str(exc)})
        _collect_artifacts(result, artifact_directory)
    return result

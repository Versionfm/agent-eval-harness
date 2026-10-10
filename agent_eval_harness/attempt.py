"""Run one explicit scripted coding-agent loop and evaluate its patch."""

from __future__ import annotations

import base64
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import difflib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import time
from typing import Any, Mapping
import uuid

from agent_eval_harness.environment import (
    DockerTaskContainer,
    EnvironmentFailure,
    apply_patch as container_apply_patch,
    build_task_environment,
    prepare_defective_repository,
    read_file as container_read_file,
    run_canonical_checks,
    run_shell as container_run_shell,
    search_text as container_search_text,
)
from agent_eval_harness.model import (
    ModelAdapter,
    ModelConfig,
    ModelRequest,
    ModelResponse,
    ScriptedModel,
    ToolCall,
)
from agent_eval_harness.report import render_attempt_report


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASK_PACKAGE = REPOSITORY_ROOT / "tasks" / "ml_tutor_retrieval"
DEFAULT_ADMISSION_EVIDENCE = (
    REPOSITORY_ROOT.parents[1] / "orchestration" / "evidence" / "issue-2" / "admission.json"
)
DEFAULT_SOURCE_REPOSITORY = Path("/home/francisco/prompt-engineering-group-project")


@dataclass(frozen=True)
class AttemptBudgets:
    """Initial small set of execution limits; later tickets can extend this contract."""

    max_model_calls: int = 30
    shell_timeout_seconds: int = 60
    tool_output_limit_bytes: int = 16 * 1024

    def __post_init__(self) -> None:
        if self.max_model_calls < 1:
            raise ValueError("max_model_calls must be positive")
        if self.shell_timeout_seconds < 1:
            raise ValueError("shell_timeout_seconds must be positive")
        if self.tool_output_limit_bytes < 128:
            raise ValueError("tool_output_limit_bytes must be at least 128")


@dataclass(frozen=True)
class AdmittedTask:
    task_id: str
    task_version: str
    source_revision: str
    acceptance_check_version: str
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


TOOL_DEFINITIONS: dict[str, dict[str, str]] = {
    "read_file": {"description": "Read a UTF-8 file from the task repository. Arguments: path."},
    "search_text": {"description": "Search repository text, case-insensitively. Arguments: query."},
    "apply_patch": {
        "description": "Create a file with path/content, or replace one exact old_text match with new_text."
    },
    "run_shell": {
        "description": "Run a shell command from the task repository root. Arguments: command."
    },
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


def _tool_output_for_model(output: str, limit: int) -> tuple[str, bool]:
    encoded = output.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return output, False
    marker = "\n...[output truncated; full output is retained in the attempt trace]"
    prefix = encoded[:max(0, limit - len(marker.encode()))].decode("utf-8", errors="ignore")
    return prefix + marker, True


def _initial_context(task: AdmittedTask, task_repository: Path) -> list[dict[str, str]]:
    public_task = task.public_task_path.read_text(encoding="utf-8")
    instructions_path = task_repository / "AGENTS.md"
    instructions = instructions_path.read_text(encoding="utf-8") if instructions_path.is_file() else ""
    files = sorted(
        path.relative_to(task_repository).as_posix()
        for path in task_repository.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(task_repository).parts
    )
    file_map = "\n".join(f"- {path}" for path in files[:100])
    if len(files) > 100:
        file_map += f"\n- ... and {len(files) - 100} more tracked files"
    system = (
        "You are a coding agent working on a bug-repair task. Use repository tools to inspect, "
        "edit, and run checks. The task environment contains a writable pinned repository. "
        "The task repository is the only mounted host directory.\n\n"
        "Available tools:\n" + "\n".join(
            f"- {name}: {details['description']}" for name, details in TOOL_DEFINITIONS.items()
        )
    )
    user = (
        f"Task description:\n{public_task}\n\n"
        "Repository instructions (AGENTS.md):\n"
        f"{instructions or '(No AGENTS.md found.)'}\n\n"
        "Repository file map:\n" + file_map
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _assistant_message(response: ModelResponse) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": response.content,
        "tool_calls": [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(dict(call.arguments), ensure_ascii=False, sort_keys=True),
                },
            }
            for call in response.tool_calls
        ],
    }
    for key, value in response.reasoning_fields.items():
        if key not in {"role", "content", "tool_calls"}:
            message[key] = _json_copy(value)
    return message


def _dispatch_tool(
    container: DockerTaskContainer,
    call: ToolCall,
    budgets: AttemptBudgets,
) -> dict[str, Any]:
    args = dict(call.arguments)
    if call.name == "read_file":
        if not isinstance(args.get("path"), str):
            return {"status": "error", "output": "", "error": "path must be text", "exit_code": None}
        return container_read_file(container, args["path"])
    if call.name == "search_text":
        if not isinstance(args.get("query"), str):
            return {"status": "error", "output": "", "error": "query must be text", "exit_code": None}
        return container_search_text(container, args["query"])
    if call.name == "apply_patch":
        return container_apply_patch(container, args)
    if call.name == "run_shell":
        command = args.get("command")
        if not isinstance(command, str):
            return {"status": "error", "output": "", "error": "command must be text", "exit_code": None}
        return container_run_shell(container, command, budgets.shell_timeout_seconds)
    return {"status": "error", "output": "", "error": f"unknown tool: {call.name}", "exit_code": None}


def _snapshot_repository(root: Path) -> dict[str, tuple[bytes, int]]:
    snapshot = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise EnvironmentFailure(f"Cannot collect a candidate containing a symbolic link: {path.relative_to(root)}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/"):
            continue
        mode = 0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644
        snapshot[relative] = (path.read_bytes(), mode)
    return snapshot


def _candidate_changes(
    baseline: Mapping[str, tuple[bytes, int]], current: Mapping[str, tuple[bytes, int]]
) -> list[dict[str, Any]]:
    changes = []
    for path in sorted(set(baseline) | set(current)):
        old = baseline.get(path)
        new = current.get(path)
        if old == new:
            continue
        if new is None:
            changes.append({"path": path, "action": "delete"})
        else:
            changes.append({
                "path": path,
                "action": "add" if old is None else "modify",
                "mode": new[1],
                "content_base64": base64.b64encode(new[0]).decode("ascii"),
            })
    return changes


def _candidate_diff(
    changes: list[dict[str, Any]], baseline: Mapping[str, tuple[bytes, int]]
) -> str:
    parts = []
    for change in changes:
        path = change["path"]
        old = baseline.get(path)
        new = None if change["action"] == "delete" else base64.b64decode(change["content_base64"])
        old_bytes = old[0] if old else b""
        try:
            old_text = old_bytes.decode("utf-8")
            new_text = new.decode("utf-8") if new is not None else ""
        except UnicodeDecodeError:
            parts.append(f"Binary file {path} changed.\n")
            continue
        from_name = f"a/{path}" if old is not None else "/dev/null"
        to_name = f"b/{path}" if new is not None else "/dev/null"
        diff = difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=from_name,
            tofile=to_name,
        )
        parts.extend(diff)
    return "".join(parts)


def _safe_candidate_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise EnvironmentFailure(f"Invalid candidate path: {value!r}")
    if path.parts[0] == ".git":
        raise EnvironmentFailure("Candidate changes cannot contain Git metadata")
    return path


def _apply_candidate_changes(repository: Path, changes: list[dict[str, Any]]) -> None:
    for change in changes:
        relative = _safe_candidate_path(change["path"])
        target = repository.joinpath(*relative.parts)
        if change["action"] == "delete":
            if target.is_symlink():
                raise EnvironmentFailure(f"Cannot delete through a symbolic link: {relative}")
            if target.exists():
                target.unlink()
            continue
        if any(parent.is_symlink() for parent in [target, *target.parents] if parent != repository.parent):
            raise EnvironmentFailure(f"Candidate path crosses a symbolic link: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(change["content_base64"]))
        target.chmod(change.get("mode", 0o644))


def _collect_artifacts(result: dict[str, Any], artifact_directory: Path) -> None:
    artifact_directory.mkdir(parents=True, exist_ok=True)
    metadata = result.get("metadata", {})
    (artifact_directory / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    (artifact_directory / "trace.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n"
                for event in result.get("trace", [])),
        encoding="utf-8",
    )
    candidate = result.get("candidate", {"changed_files": [], "files": [], "patch": ""})
    (artifact_directory / "candidate.patch").write_text(candidate.get("patch", ""), encoding="utf-8")
    (artifact_directory / "candidate-files.json").write_text(
        json.dumps(candidate.get("files", []), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifact_directory / "checks.json").write_text(
        json.dumps(result.get("evaluation", {}), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifact_directory / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    (artifact_directory / "report.html").write_text(render_attempt_report(result), encoding="utf-8")


def _record(trace: list[dict[str, Any]], event_type: str, **data: Any) -> dict[str, Any]:
    event = {"event_id": len(trace) + 1, "type": event_type, "timestamp": _timestamp(), **data}
    trace.append(event)
    return event


def attempt_and_evaluate(
    *,
    admitted_task: AdmittedTask,
    model: ModelAdapter,
    model_config: ModelConfig,
    budgets: AttemptBudgets,
    artifact_directory: Path,
    orchestrator: str = "python-loop",
) -> dict[str, Any]:
    """Execute an explicit tool loop, capture its patch, and score a fresh defect copy."""
    artifact_directory = artifact_directory.expanduser().resolve()
    if artifact_directory.exists():
        raise ValueError(f"Artifact destination already exists: {artifact_directory}")
    if REPOSITORY_ROOT == artifact_directory or REPOSITORY_ROOT in artifact_directory.parents:
        raise ValueError("attempt artifacts must be outside the harness Git repository")
    artifact_directory.parent.mkdir(parents=True, exist_ok=True)
    if admitted_task.source_repository == artifact_directory or admitted_task.source_repository in artifact_directory.parents:
        raise ValueError("attempt artifacts must be outside the pinned source repository")
    if orchestrator != "python-loop":
        raise ValueError("ticket #3 provides the python-loop orchestrator")

    task_repository = artifact_directory / "task-repository"
    trace: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "termination_reason": "harness_error",
        "functional_verdict": "invalid_environment",
        "duration_seconds": 0.0,
        "trace": trace,
        "candidate": {"changed_files": [], "files": [], "patch": ""},
        "evaluation": {"status": "error", "checks": {}, "error": "evaluation not run"},
        "initial_context": [],
        "metadata": {
            "schema_version": "1",
            "task_id": admitted_task.task_id,
            "task_version": admitted_task.task_version,
            "source_revision": admitted_task.source_revision,
            "acceptance_check_version": admitted_task.acceptance_check_version,
            "requested_model": model_config.requested_model,
            "provider": model_config.provider,
            "model_settings": _json_copy(dict(model_config.settings)),
            "orchestrator": orchestrator,
            "budgets": _json_copy(budgets.__dict__),
            "started_at": _timestamp(),
            "admission_evidence": str(admitted_task.admission_evidence_path),
            "task_container_image": admitted_task.image,
            "admission_recorded_image_id": json.loads(
                admitted_task.admission_evidence_path.read_text(encoding="utf-8")
            ).get("environment_evidence", {}).get("image_id"),
            "runtime_version": admitted_task.runtime_version,
            "cost": {"status": "unavailable", "amount": None, "currency": None},
            "qualitative_review": {"status": "pending"},
        },
    }
    started = time.monotonic()
    defect_baseline: dict[str, tuple[bytes, int]] = {}
    attempt_container: DockerTaskContainer | None = None
    model_call_count = 0
    usage_records = []
    harness_error: str | None = None

    try:
        image_evidence = build_task_environment(
            admitted_task.dockerfile_path,
            admitted_task.dockerfile_path.parent,
            expected_base_image=admitted_task.expected_base_image,
            expected_python_version=admitted_task.runtime_version,
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
            )
            defect_baseline = _snapshot_repository(defect_repository)
            shutil.copytree(defect_repository, task_repository)
            attempt_container = DockerTaskContainer(image_evidence["image_id"], task_repository)
            attempt_container.start()
            result["attempt_container_configuration"] = attempt_container.configuration
            result["metadata"]["attempt_repository"] = str(task_repository)

            messages = _initial_context(admitted_task, task_repository)
            result["initial_context"] = copy.deepcopy(messages)
            _record(
                trace,
                "initial_context",
                status="ready",
                message_count=len(messages),
                tool_definitions=TOOL_DEFINITIONS,
                messages=messages,
            )

            termination = "harness_error"
            while True:
                if model_call_count >= budgets.max_model_calls:
                    termination = "model_call_budget"
                    _record(trace, "termination", reason=termination, model_calls=model_call_count)
                    break
                request = ModelRequest(messages=copy.deepcopy(messages), config=model_config)
                model_call_count += 1
                call_started = time.monotonic()
                try:
                    response = model.complete(request)
                    if not isinstance(response, ModelResponse):
                        raise TypeError("model adapter must return ModelResponse")
                except Exception as exc:
                    duration = time.monotonic() - call_started
                    _record(
                        trace,
                        "model",
                        model_call=model_call_count,
                        status="error",
                        duration_seconds=round(duration, 6),
                        request_messages=request.messages,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    termination = "provider_error"
                    break
                duration = time.monotonic() - call_started
                usage = _json_copy(dict(response.usage))
                usage_records.append(usage)
                response_payload = {
                    "content": response.content,
                    "reasoning_fields": _json_copy(dict(response.reasoning_fields)),
                    "tool_calls": [
                        {"name": call.name, "arguments": _json_copy(dict(call.arguments)), "call_id": call.call_id}
                        for call in response.tool_calls
                    ],
                    "usage": usage,
                    "observed_model": response.observed_model,
                }
                _record(
                    trace,
                    "model",
                    model_call=model_call_count,
                    status="ok",
                    duration_seconds=round(duration, 6),
                    request_messages=request.messages,
                    response=response_payload,
                )
                messages.append(_assistant_message(response))
                if not response.tool_calls:
                    termination = "agent_completed"
                    _record(trace, "termination", reason=termination, model_calls=model_call_count)
                    break
                for index, call in enumerate(response.tool_calls, 1):
                    tool_started = time.monotonic()
                    tool_id = call.call_id or f"call-{model_call_count}-{index}"
                    try:
                        tool_result = _dispatch_tool(attempt_container, call, budgets)
                    except Exception as exc:
                        tool_result = {
                            "status": "error", "output": "",
                            "error": f"{type(exc).__name__}: {exc}", "exit_code": None,
                        }
                    duration = time.monotonic() - tool_started
                    tool_result["duration_seconds"] = round(duration, 6)
                    visible_output, truncated = _tool_output_for_model(
                        str(tool_result.get("output", "")), budgets.tool_output_limit_bytes
                    )
                    visible = {
                        "status": tool_result.get("status"),
                        "output": visible_output,
                        "error": tool_result.get("error"),
                        "truncated": truncated,
                    }
                    _record(
                        trace,
                        "tool",
                        tool_name=call.name,
                        tool_call_id=tool_id,
                        arguments=_json_copy(dict(call.arguments)),
                        status=tool_result.get("status"),
                        duration_seconds=round(duration, 6),
                        result=tool_result,
                        model_visible_result=visible,
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "name": call.name,
                        "content": json.dumps(visible, ensure_ascii=False, sort_keys=True),
                    })

            result["termination_reason"] = termination
            result["metadata"]["model_call_count"] = model_call_count
            result["metadata"]["usage_by_call"] = usage_records
            result["attempt_container_configuration"] = attempt_container.configuration
            attempt_container.close()
            attempt_container = None

            current = _snapshot_repository(task_repository)
            changes = _candidate_changes(defect_baseline, current)
            patch_text = _candidate_diff(changes, defect_baseline)
            result["candidate"] = {
                "changed_files": [change["path"] for change in changes],
                "files": changes,
                "patch": patch_text,
            }
            _record(
                trace,
                "patch_collection",
                status="completed",
                changed_files=result["candidate"]["changed_files"],
                change_count=len(changes),
            )

            with tempfile.TemporaryDirectory(prefix="agent-eval-fresh-evaluator-") as evaluator_scratch:
                evaluation_repository = Path(evaluator_scratch) / "task-repository"
                shutil.copytree(defect_repository, evaluation_repository)
                _apply_candidate_changes(evaluation_repository, changes)
                evaluation = run_canonical_checks(
                    image_evidence["image_id"],
                    evaluation_repository,
                    admitted_task.evaluator_directory,
                    admitted_task.runtime_version,
                )
            result["evaluation"] = evaluation
            if evaluation.get("status") != "completed":
                result["functional_verdict"] = "invalid_environment"
            elif evaluation.get("checks") and all(value is True for value in evaluation["checks"].values()):
                result["functional_verdict"] = "success"
            else:
                result["functional_verdict"] = "failure"
            _record(
                trace,
                "evaluation",
                status=evaluation.get("status"),
                functional_verdict=result["functional_verdict"],
                checks=evaluation.get("checks", {}),
                error=evaluation.get("error"),
                container_configuration=evaluation.get("container_configuration", {}),
            )
    except Exception as exc:
        harness_error = f"{type(exc).__name__}: {exc}"
        result["harness_error"] = harness_error
        result["termination_reason"] = "harness_error"
        result["functional_verdict"] = "invalid_environment"
        result["evaluation"] = {"status": "error", "checks": {}, "error": harness_error}
        _record(trace, "harness_error", status="error", error=harness_error)
    finally:
        if attempt_container is not None:
            try:
                attempt_container.close()
            except Exception as exc:
                cleanup_error = f"{type(exc).__name__}: {exc}"
                result.setdefault("cleanup_error", cleanup_error)
                _record(trace, "cleanup_error", status="error", error=cleanup_error)
        result["duration_seconds"] = round(time.monotonic() - started, 6)
        result["metadata"]["duration_seconds"] = result["duration_seconds"]
        result["metadata"]["finished_at"] = _timestamp()
        _collect_artifacts(result, artifact_directory)
    return result

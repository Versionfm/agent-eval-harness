"""Bench · candidate snapshot, patch validation, and evaluator-owned verdict mapping."""

from __future__ import annotations

import base64
import difflib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from typing import TYPE_CHECKING, Any, Callable, Mapping

from agent_eval_harness.bench.admission import CHECK_IDS
from agent_eval_harness.bench.environment import run_canonical_checks
from agent_eval_harness.harness.permissions import EnvironmentFailure
from agent_eval_harness.harness.hooks import NULL_EVENT_SINK, AttemptEventSink
from agent_eval_harness.harness.persistence import _record_final

if TYPE_CHECKING:
    from agent_eval_harness.bench.attempt import AdmittedTask


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


def _materialize_snapshot(
    repository: Path, snapshot: Mapping[str, tuple[bytes, int]]
) -> None:
    repository.mkdir(parents=True, exist_ok=False)
    for relative_name, (content, mode) in snapshot.items():
        relative = _safe_candidate_path(relative_name)
        target = repository.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(mode)


def _finalize_evaluation(
    result: dict[str, Any], evaluation: dict[str, Any], trace: list[dict[str, Any]],
    sink: AttemptEventSink = NULL_EVENT_SINK,
) -> str | None:
    """Apply the same evaluator-to-verdict mapping on normal and recovery paths; returns the failure category."""
    result["evaluation"] = evaluation
    checks = evaluation.get("checks")
    if evaluation.get("status") == "invalid_patch":
        verdict, category = "failure", "invalid_patch"
    elif (
        evaluation.get("status") != "completed"
        or not isinstance(checks, Mapping)
        or set(checks) != set(CHECK_IDS)
        or any(type(value) is not bool for value in checks.values())
    ):
        verdict, category = "invalid_environment", "evaluation_environment_error"
    elif evaluation.get("candidate_execution_error"):
        verdict, category = "failure", "candidate_execution_error"
    elif all(checks.values()):
        verdict, category = "success", None
    else:
        verdict, category = "failure", "canonical_check_failure"
    result["functional_verdict"] = verdict
    result["failure_category"] = category
    _record_final(
        trace, sink, "evaluation",
        status=evaluation.get("status"),
        failure_category=category,
        functional_verdict=verdict,
        checks=checks if isinstance(checks, Mapping) else {},
        error=evaluation.get("error"),
        container_configuration=evaluation.get("container_configuration", {}),
    )
    return category


def evaluate_candidate_changes(
    defect_repository: Path,
    changes: list[dict[str, Any]],
    *,
    image_id: str,
    admitted_task: AdmittedTask,
    timeout_seconds: float,
    canonical_check_runner: Callable[..., dict[str, Any]] = run_canonical_checks,
) -> dict[str, Any]:
    """Apply a collected candidate, then run the canonical evaluator.

    Unsafe candidate paths are candidate failures. Failures while staging the
    evaluator or running its Docker worker are environment errors, so an
    unavailable canonical result cannot be scored as a repair failure.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="agent-eval-candidate-evaluator-") as scratch:
            evaluation_repository = Path(scratch) / "task-repository"
            shutil.copytree(defect_repository, evaluation_repository)
            try:
                _apply_candidate_changes(evaluation_repository, changes)
            except EnvironmentFailure as exc:
                return {"status": "invalid_patch", "checks": {}, "error": str(exc)}
            return canonical_check_runner(
                image_id,
                evaluation_repository,
                admitted_task.evaluator_directory,
                admitted_task.runtime_version,
                timeout_seconds=timeout_seconds,
            )
    except Exception as exc:
        return {
            "status": "error",
            "checks": {},
            "error": f"Candidate evaluator staging or execution failed: {type(exc).__name__}: {exc}",
        }


def collect_candidate(repository: Path, baseline: Mapping[str, tuple[bytes, int]]) -> dict[str, Any]:
    """Capture one attempt repository as the complete candidate patch record."""
    changes = _candidate_changes(baseline, _snapshot_repository(repository))
    return {
        "status": "collected",
        "changed_files": [change["path"] for change in changes],
        "files": changes,
        "patch": _candidate_diff(changes, baseline),
    }

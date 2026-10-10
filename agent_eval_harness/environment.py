"""Disposable task and independent evaluator containers."""

from __future__ import annotations

import io
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import time
from typing import Any
import uuid

from agent_eval_harness.permissions import (
    candidate_evaluator_configuration,
    observed_task_container_configuration,
    runtime_probe_security_flags,
    task_container_configuration,
    task_container_create_flags,
    task_container_policy_error,
)


class EnvironmentFailure(RuntimeError):
    """Docker setup or evaluator failures that are not task failures."""


class CommandTimeout(EnvironmentFailure):
    """A bounded command timed out; keep any output captured before it stopped."""

    def __init__(
        self, message: str, *, stdout: str = "", stderr: str = "", timeout_seconds: float
    ):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.timeout_seconds = timeout_seconds


def _bounded_timeout(max_seconds: float, deadline: float | None) -> float:
    if deadline is None:
        return max_seconds
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise EnvironmentFailure("Attempt deadline reached before the environment operation")
    return min(max_seconds, remaining)


def build_task_environment(
    dockerfile: Path,
    context_directory: Path,
    *,
    expected_base_image: str,
    expected_python_version: str,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Build offline and resolve the resulting local tag to an immutable image ID."""
    dockerfile = dockerfile.resolve()
    context_directory = context_directory.resolve()
    dockerfile_bytes = dockerfile.read_bytes()
    dockerfile_text = dockerfile_bytes.decode("utf-8")
    if f"FROM {expected_base_image}" not in dockerfile_text:
        raise EnvironmentFailure("Task Dockerfile does not use the manifest's pinned base image")
    # Each worktree/run gets a stable reference that another local run cannot retag
    # while this attempt still needs its image for independent evaluation.
    tag = f"agent-eval-harness/ml-tutor-attempt:{uuid.uuid4().hex}"
    build = _run(
        [
            "docker", "build", "--network=none", "--pull=false", "--tag", tag,
            "--file", str(dockerfile), str(context_directory),
        ],
        timeout=_bounded_timeout(300, deadline),
    )
    build_output = _require_success(build, "Offline task image build")
    image_id = _require_success(
        _run(["docker", "image", "inspect", "--format", "{{.Id}}", tag],
             timeout=_bounded_timeout(30, deadline)),
        "Task image inspection",
    )
    server_version = _require_success(
        _run(["docker", "version", "--format", "{{.Server.Version}}"],
             timeout=_bounded_timeout(30, deadline)),
        "Docker server version query",
    )
    runtime = _require_success(
        _runtime_probe(image_id, deadline=deadline),
        "Prepared Python runtime probe",
    )
    if runtime != expected_python_version:
        raise EnvironmentFailure(
            f"Prepared Python runtime was {runtime}; expected {expected_python_version}"
        )
    return {
        "image_tag": tag,
        "image_id": image_id,
        "admission_image_id": None,
        "runtime_version": runtime,
        "docker_server_version": server_version,
        "dockerfile_sha256": hashlib.sha256(dockerfile_bytes).hexdigest(),
        "build_network": "none",
        "build_pull": False,
        "build_status": "passed",
        "build_output_excerpt": (build_output + "\n" + (build.stderr or ""))[-1200:],
    }


def _runtime_probe(image_id: str, *, deadline: float | None) -> subprocess.CompletedProcess:
    name = f"agent-eval-runtime-{uuid.uuid4().hex}"
    command = [
        "docker", "run", "--rm", "--name", name, "--pull=never",
        *runtime_probe_security_flags(),
        image_id, "python", "-c", "import platform; print(platform.python_version())",
    ]
    try:
        return _run(command, timeout=_bounded_timeout(60, deadline))
    except EnvironmentFailure:
        _force_remove_container(name)
        raise


def _run(
    command: list[str], *, timeout: float, input_text: str | None = None, text: bool = True
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=text,
            input=input_text,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise EnvironmentFailure(f"Required command is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        def as_text(value: str | bytes | None) -> str:
            if value is None:
                return ""
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace")
            return value
        raise CommandTimeout(
            f"Command timed out after {timeout}s: {command[0]}",
            stdout=as_text(exc.stdout),
            stderr=as_text(exc.stderr),
            timeout_seconds=timeout,
        ) from exc


def _require_success(result: subprocess.CompletedProcess, label: str) -> str:
    if result.returncode != 0:
        detail = result.stderr or result.stdout or "no command output"
        raise EnvironmentFailure(
            f"{label} failed with exit code {result.returncode}: {detail.strip()[-2000:]}"
        )
    return result.stdout.strip()


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("repository paths must be relative and stay inside the task repository")
    if path.parts[0] == ".git":
        raise ValueError("the task repository does not expose Git metadata")
    return path


def prepare_defective_repository(
    source_repository: Path,
    revision: str,
    mutation_path: Path,
    destination: Path,
    *,
    deadline: float | None = None,
) -> None:
    """Archive the pinned full repository and apply only the admitted mutation."""
    source_repository = source_repository.expanduser().resolve()
    check = _run(
        ["git", "-C", str(source_repository), "cat-file", "-e", f"{revision}^{{commit}}"],
        timeout=_bounded_timeout(30, deadline),
    )
    _require_success(check, "Pinned source revision lookup")
    archive = _run(
        ["git", "-C", str(source_repository), "archive", "--format=tar", revision],
        timeout=_bounded_timeout(120, deadline),
        text=False,
    )
    if archive.returncode != 0:
        _require_success(archive, "Pinned full source archive")

    destination.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
            bundle.extractall(path=destination, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise EnvironmentFailure(f"Could not extract pinned source revision: {exc}") from exc

    mutation = json.loads(mutation_path.read_text(encoding="utf-8"))
    relative = _safe_relative_path(mutation["path"])
    target = destination.joinpath(*relative.parts)
    if target.is_symlink() or not target.is_file():
        raise EnvironmentFailure(f"Admitted mutation target is missing: {relative}")
    source = target.read_text(encoding="utf-8")
    before = mutation["before"]
    if source.count(before) != 1:
        raise EnvironmentFailure(
            f"Admitted mutation expected one match in {relative}; found {source.count(before)}"
        )
    target.write_text(source.replace(before, mutation["after"], 1), encoding="utf-8")

    required = ("AGENTS.md", "app/source.py", "app/tutor.py", "tests/test_source.py")
    missing = [name for name in required if not (destination / name).is_file()]
    if missing:
        raise EnvironmentFailure(f"Pinned repository is missing expected files: {missing!r}")
    if (destination / ".git").exists() or (destination / "curator").exists():
        raise EnvironmentFailure("Task preparation included Git metadata or curator files")


def _docker_command(command: list[str], *, timeout: float, input_text: str | None = None):
    return _run(command, timeout=timeout, input_text=input_text)


def _force_remove_container(container_ref: str, *, timeout_seconds: float = 10) -> None:
    """Synchronously stop and remove one container created by this harness."""
    try:
        result = _run(
            ["docker", "rm", "--force", container_ref], timeout=timeout_seconds
        )
    except EnvironmentFailure as exc:
        raise EnvironmentFailure(
            f"Could not stop timed-out container {container_ref}: {exc}"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no Docker output").strip()
        if "no such container" not in detail.casefold():
            raise EnvironmentFailure(
                f"Could not stop timed-out container {container_ref}: {detail[-1000:]}"
            )


class DockerTaskContainer:
    """One writable, network-isolated container for a single coding-agent attempt."""

    def __init__(
        self, image: str, task_repository: Path, *, task_mount_read_only: bool = False
    ):
        self.image = image
        self.task_repository = task_repository.resolve()
        self.task_mount_read_only = task_mount_read_only
        self.container_id: str | None = None
        self.configuration = task_container_configuration(
            task_mount_read_only=task_mount_read_only
        )

    def start(self, *, timeout_seconds: float = 60, deadline: float | None = None) -> None:
        if self.container_id is not None:
            raise EnvironmentFailure("Task container has already been started")
        created = _docker_command(
            [
                "docker", "create", "--pull=never", "--name", f"agent-eval-{uuid.uuid4().hex}",
                *task_container_create_flags(
                    self.task_repository,
                    task_mount_read_only=self.task_mount_read_only,
                ),
                self.image,
                "python", "-c", "import time; time.sleep(86400)",
            ],
            timeout=_bounded_timeout(min(60, timeout_seconds), deadline),
        )
        self.container_id = _require_success(created, "Task container creation")
        started = _docker_command(
            ["docker", "start", self.container_id],
            timeout=_bounded_timeout(min(30, timeout_seconds), deadline),
        )
        _require_success(started, "Task container startup")
        self.configuration["observed"] = self.inspect_configuration(
            timeout_seconds=timeout_seconds, deadline=deadline
        )

    def inspect_configuration(
        self, *, timeout_seconds: float = 30, deadline: float | None = None
    ) -> dict[str, Any]:
        if self.container_id is None:
            raise EnvironmentFailure("Task container is not running")
        inspected = _docker_command(
            ["docker", "inspect", self.container_id],
            timeout=_bounded_timeout(min(30, timeout_seconds), deadline),
        )
        payload = json.loads(_require_success(inspected, "Task container inspection"))[0]
        observed = observed_task_container_configuration(payload)
        policy_error = task_container_policy_error(
            observed, task_mount_read_only=self.task_mount_read_only
        )
        if policy_error:
            raise EnvironmentFailure(policy_error)
        return observed

    def close(self, *, timeout_seconds: float = 30) -> None:
        if self.container_id is not None:
            _docker_command(
                ["docker", "rm", "--force", self.container_id], timeout=timeout_seconds
            )
            self.container_id = None

    def exec(
        self,
        command: list[str],
        *,
        timeout: float,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess:
        if self.container_id is None:
            # A prior timed-out command removed the entire container to ensure
            # its descendants could not mutate the mounted repository later.
            self.start(timeout_seconds=max(30, min(timeout, 60)))
        interactive = ["-i"] if input_text is not None else []
        try:
            return _docker_command(
                ["docker", "exec", *interactive, "--workdir", "/task", self.container_id, *command],
                timeout=timeout,
                input_text=input_text,
            )
        except CommandTimeout:
            timed_out_id = self.container_id
            if timed_out_id is not None:
                _force_remove_container(timed_out_id)
                self.container_id = None
            raise


def run_canonical_checks(
    image: str,
    candidate_repository: Path,
    evaluator_directory: Path,
    expected_python_version: str,
    *,
    timeout_seconds: float = 90,
) -> dict[str, Any]:
    """Run candidate probes in isolation, then assert their observations here.

    The candidate worker has only a read-only task mount. The evaluator's
    canonical code runs in the outer harness after the worker exits, so imports,
    stdout writes, and process termination in candidate code cannot print or
    choose a functional verdict.
    """
    configuration = candidate_evaluator_configuration()
    checker_path = evaluator_directory.resolve() / "checks.py"
    if checker_path.is_symlink() or not checker_path.is_file():
        return {
            "status": "error", "checks": {},
            "error": f"Canonical evaluator checks are unavailable: {checker_path}",
            "container_configuration": configuration,
        }
    try:
        spec = importlib.util.spec_from_file_location(
            f"agent_eval_canonical_checks_{hashlib.sha256(str(checker_path).encode()).hexdigest()[:12]}",
            checker_path,
        )
        if spec is None or spec.loader is None:
            raise EnvironmentFailure("Could not load evaluator-owned canonical checks")
        evaluator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(evaluator)
        container = DockerTaskContainer(
            image, candidate_repository, task_mount_read_only=True
        )
        worker_timeout: CommandTimeout | None = None
        try:
            try:
                container.start(timeout_seconds=min(60, timeout_seconds))
            except EnvironmentFailure as exc:
                return {
                    "status": "error", "checks": {},
                    "error": f"Candidate evaluator worker could not start: {exc}",
                    "container_configuration": configuration,
                }
            try:
                worker_result = container.exec(
                    ["python", "-"], timeout=timeout_seconds,
                    input_text=evaluator.PROBE_SCRIPT,
                )
            except CommandTimeout as exc:
                worker_timeout = exc
            except EnvironmentFailure as exc:
                return {
                    "status": "error", "checks": {},
                    "error": f"Candidate evaluator worker execution failed: {exc}",
                    "container_configuration": configuration,
                }
        finally:
            container.close(timeout_seconds=min(30, timeout_seconds))

        if worker_timeout is not None:
            payload = {
                "worker_status": "candidate_error",
                "error": f"candidate probe timed out after {worker_timeout.timeout_seconds}s",
            }
            evaluated = evaluator.evaluate_observations(
                payload, expected_python_version=expected_python_version
            )
            evaluated["candidate_worker_stdout"] = worker_timeout.stdout[-2000:]
            evaluated["candidate_worker_stderr"] = worker_timeout.stderr[-2000:]
            evaluated["container_configuration"] = configuration
            return evaluated
    except EnvironmentFailure as exc:
        return {"status": "error", "checks": {}, "error": str(exc), "container_configuration": configuration}
    marker = "__AGENT_EVAL_OBSERVATIONS__"
    records = [line[len(marker):] for line in worker_result.stdout.splitlines()
               if line.startswith(marker)]
    if worker_result.returncode != 0 or len(records) != 1:
        detail = (worker_result.stderr or worker_result.stdout or
                  "candidate worker did not return one observation record").strip()
        payload = {
            "worker_status": "candidate_error",
            "error": detail[-2000:],
        }
    else:
        try:
            payload = json.loads(records[0])
        except json.JSONDecodeError as exc:
            payload = {
                "worker_status": "candidate_error",
                "error": f"candidate worker returned malformed observations: {exc}",
            }
    if not isinstance(payload, dict):
        payload = {"worker_status": "candidate_error", "error": "candidate result was not an object"}
    try:
        evaluated = evaluator.evaluate_observations(
            payload, expected_python_version=expected_python_version
        )
    except Exception as exc:
        return {
            "status": "error", "checks": {},
            "error": f"Evaluator assertion failed: {type(exc).__name__}: {exc}",
            "container_configuration": configuration,
        }
    evaluated["container_configuration"] = configuration
    if worker_result.stderr:
        evaluated["candidate_worker_stderr"] = worker_result.stderr[-2000:]
    return evaluated

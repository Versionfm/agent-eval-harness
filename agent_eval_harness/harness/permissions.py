"""Container isolation policy shared by task setup and evaluator workers."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import time
from typing import Any
import uuid


ATTEMPT_TMPFS = "/tmp:rw,noexec,nosuid,mode=1777,size=64m"
RUNTIME_PROBE_TMPFS = "/tmp:rw,noexec,nosuid,mode=1777,size=16m"


def runtime_probe_security_flags() -> list[str]:
    """Return the runtime-probe restrictions without its image or command."""
    return [
        "--network=none",
        "--read-only",
        "--tmpfs", RUNTIME_PROBE_TMPFS,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=64",
    ]


def task_container_configuration(*, task_mount_read_only: bool) -> dict[str, Any]:
    """Describe the policy applied to an attempt or candidate-observation worker."""
    return {
        "network_mode": "none",
        "root_filesystem_read_only": True,
        "tmpfs": ATTEMPT_TMPFS,
        "capabilities_dropped": "ALL",
        "no_new_privileges": True,
        "pids_limit": 128,
        "workdir": "/task",
        "task_mount_target": "/task",
        "task_mount_read_only": task_mount_read_only,
        "evaluator_mount_present": False,
        "other_mounts": [],
        "canonical_evaluator_present": False,
        "credentials_or_container_socket_mounted": False,
    }


def task_container_create_flags(
    task_repository: Path,
    *,
    task_mount_read_only: bool,
    uid: int | None = None,
    gid: int | None = None,
) -> list[str]:
    """Build Docker create flags for the one task mount and fixed isolation policy."""
    user = f"{os.getuid() if uid is None else uid}:{os.getgid() if gid is None else gid}"
    mount = f"type=bind,source={task_repository},target=/task"
    if task_mount_read_only:
        mount += ",readonly"
    return [
        "--network=none",
        "--read-only",
        "--tmpfs", ATTEMPT_TMPFS,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=128",
        "--user", user,
        "--mount", mount,
        "--workdir", "/task",
        "--env", "PYTHONPATH=/task",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
    ]


def observed_task_container_configuration(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract effective Docker settings needed to validate the task worker."""
    host = payload.get("HostConfig", {})
    mounts = [
        {
            "destination": mount.get("Destination"),
            "read_only": not bool(mount.get("RW")),
            "source": mount.get("Source"),
        }
        for mount in payload.get("Mounts", [])
    ]
    env_keys = sorted(
        entry.split("=", 1)[0]
        for entry in payload.get("Config", {}).get("Env", [])
        if "=" in entry
    )
    return {
        "image_id": payload.get("Image"),
        "network_mode": host.get("NetworkMode"),
        "root_filesystem_read_only": bool(host.get("ReadonlyRootfs")),
        "capabilities_dropped": host.get("CapDrop", []),
        "security_options": host.get("SecurityOpt", []),
        "pids_limit": host.get("PidsLimit"),
        "mounts": mounts,
        "environment_variable_names": env_keys,
        "user": payload.get("Config", {}).get("User"),
    }


def task_container_policy_error(
    observed: dict[str, Any], *, task_mount_read_only: bool
) -> str | None:
    """Return the first failed isolation assertion from the established policy."""
    if observed["network_mode"] != "none" or not observed["root_filesystem_read_only"]:
        return "Task container inspection did not confirm network/root isolation"
    mounts = observed["mounts"]
    if (
        len(mounts) != 1
        or mounts[0]["destination"] != "/task"
        or mounts[0]["read_only"] != task_mount_read_only
    ):
        return "Task container does not have the expected task-repository mount"
    if any("docker.sock" in str(mount.get("source")) for mount in mounts):
        return "Engine socket appeared in the task container mounts"
    return None


def candidate_evaluator_configuration() -> dict[str, Any]:
    """Describe the read-only candidate observation worker's visible mounts."""
    return {
        "network_mode": "none",
        "root_filesystem_read_only": True,
        "task_mount_read_only": True,
        "evaluator_mount_present": False,
        "credentials_or_container_socket_mounted": False,
    }


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

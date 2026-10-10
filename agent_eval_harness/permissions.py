"""Container isolation policy shared by task setup and evaluator workers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


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

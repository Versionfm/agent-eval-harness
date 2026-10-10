"""Bench · fingerprint the harness checkout and runtime used for an attempt."""

from __future__ import annotations

import hashlib
import importlib.metadata
import platform
from pathlib import Path
import subprocess
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _harness_provenance() -> dict[str, Any]:
    """Describe the exact harness checkout used by every orchestration route."""
    try:
        commit = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain=v1", "-z"],
            check=True, capture_output=True, timeout=5,
        ).stdout
        diff = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "diff", "HEAD", "--binary"],
            check=True, capture_output=True, timeout=5,
        ).stdout
        digest = hashlib.sha256(diff)
        untracked = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "ls-files", "--others", "--exclude-standard", "-z"],
            check=True, capture_output=True, timeout=5,
        ).stdout
        for relative in sorted(filter(None, untracked.split(b"\0"))):
            path = REPOSITORY_ROOT / relative.decode("utf-8", errors="surrogateescape")
            if path.is_file() and not path.is_symlink():
                digest.update(relative + b"\0" + path.read_bytes())
        return {
            "commit": commit,
            "working_tree": "dirty" if status else "clean",
            "working_tree_sha256": digest.hexdigest() if status else None,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "commit": None,
            "working_tree": "unavailable",
            "working_tree_sha256": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _dependency_versions() -> dict[str, str]:
    versions = {"python-runtime": platform.python_version()}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if isinstance(name, str) and name:
            versions[name.casefold().replace("_", "-")] = distribution.version
    return dict(sorted(versions.items()))


harness_provenance = _harness_provenance
dependency_versions = _dependency_versions

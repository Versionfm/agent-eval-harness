"""Admission rules for evaluator-owned task evidence."""

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path


CHECK_IDS = (
    "title_retrieval",
    "title_context",
    "body_relevance",
    "case_normalization",
    "top_k_limit",
    "input_immutable",
    "full_context_bypass",
    "history_mode",
    "input_order_independence",
)
TITLE_RELEVANCE_FAILURES = (
    "title_retrieval",
    "title_context",
    "input_order_independence",
)
VARIANT_NAMES = ("baseline", "defect", "repair")


def task_package_evidence(task_package: Path, manifest: Mapping) -> dict:
    """Fingerprint task identity and every curator/public/environment input."""
    task_package = task_package.expanduser().resolve()
    file_hashes = {}
    for path in sorted(task_package.rglob("*")):
        if path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Task package contains a non-regular file: {path}")
        relative = path.relative_to(task_package).as_posix()
        if "__pycache__" in Path(relative).parts or relative.endswith(".pyc"):
            continue
        file_hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    identity = {
        "task_id": manifest.get("task_id"),
        "task_version": manifest.get("task_version"),
        "acceptance_check_version": manifest.get("acceptance_check_version"),
        "source_revision": manifest.get("source", {}).get("revision"),
        "acceptance_check_ids": list(manifest.get("acceptance_check_ids", [])),
    }
    canonical = json.dumps(
        {"identity": identity, "files": file_hashes},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return {
        "identity": identity,
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "file_sha256": file_hashes,
    }


def assess_admission(runs: Mapping[str, Mapping]) -> dict:
    """Classify baseline, defect, and repair runs from canonical check evidence."""
    invalid_runs = []
    for name in VARIANT_NAMES:
        run = runs.get(name)
        if run is None or run.get("status") != "completed":
            invalid_runs.append(name)
            continue
        checks = run.get("checks")
        if (
            not isinstance(checks, Mapping)
            or set(checks) != set(CHECK_IDS)
            or any(type(value) is not bool for value in checks.values())
        ):
            invalid_runs.append(name)

    if invalid_runs:
        return {
            "status": "invalid_environment",
            "invalid_runs": invalid_runs,
            "reasons": [f"Missing or incomplete evaluator run: {name}" for name in invalid_runs],
        }

    failed = {
        name: [check_id for check_id in CHECK_IDS if runs[name]["checks"][check_id] is not True]
        for name in VARIANT_NAMES
    }
    expected = {
        "baseline": [],
        "defect": list(TITLE_RELEVANCE_FAILURES),
        "repair": [],
    }
    reasons = []
    for name in VARIANT_NAMES:
        if failed[name] != expected[name]:
            reasons.append(
                f"{name} failed checks {failed[name]!r}; expected {expected[name]!r}"
            )

    return {
        "status": "admitted" if not reasons else "rejected",
        "defect_failed_checks": failed["defect"],
        "reasons": reasons,
    }

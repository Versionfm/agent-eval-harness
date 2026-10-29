"""CLI · prepare and run the admission experiment for a task package (default: the ML Tutor task)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from typing import Any
import uuid

from agent_eval_harness.bench.admission import (
    VARIANT_NAMES, assess_admission, task_package_evidence,
)
from agent_eval_harness.bench.attempt import DEFAULT_TASK_PACKAGE
from agent_eval_harness.bench.environment import run_canonical_checks, task_build_network
from agent_eval_harness.harness.permissions import _force_remove_container
from agent_eval_harness.bench.paths import orchestration_root


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = orchestration_root(REPOSITORY_ROOT) / "evidence" / "issue-2"
TMPFS_CONFIGURATION = "/tmp:rw,noexec,nosuid,mode=1777,size=16m"
CONTAINER_CONFIGURATION = {
    "network_mode": "none",
    "root_filesystem_read_only": True,
    "tmpfs": TMPFS_CONFIGURATION,
    "capabilities_dropped": "ALL",
    "no_new_privileges": True,
    "pids_limit": 64,
    "mounts": [
        {"source_role": "task_repository", "target": "/task", "read_only": True},
    ],
    "evaluator_mount_present": False,
    "canonical_assertions_run_by": "outer harness process",
    "credentials_or_container_socket_mounted": False,
}


class EnvironmentFailure(RuntimeError):
    """A setup or evaluator problem that must not be scored as a task failure."""


def _display_path(path: Path) -> str:
    """Repository-relative for packages inside this repository, absolute otherwise."""
    try:
        return str(path.relative_to(REPOSITORY_ROOT))
    except ValueError:
        return str(path)


def _run(
    command: list[str], *, timeout: int = 120, cwd: Path | None = None, text: bool = True
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=text,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise EnvironmentFailure(f"Required command is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise EnvironmentFailure(f"Command timed out after {timeout}s: {command[0]}") from exc


def _require_success(result: subprocess.CompletedProcess, label: str) -> str:
    if result.returncode != 0:
        detail = result.stderr or result.stdout or "no command output"
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        detail = detail.strip()
        raise EnvironmentFailure(f"{label} failed with exit code {result.returncode}: {detail[-2000:]}")
    return result.stdout.strip()


def _load_manifest(task_package: Path) -> dict[str, Any]:
    manifest = json.loads((task_package / "manifest.json").read_text(encoding="utf-8"))
    check_ids = manifest.get("acceptance_check_ids")
    expected = manifest.get("expected_defect_failures")
    paths = manifest.get("source", {}).get("paths")
    if not check_ids or not all(isinstance(check_id, str) for check_id in check_ids):
        raise ValueError("Manifest acceptance_check_ids must be a non-empty list of strings.")
    if not expected or not set(expected) <= set(check_ids):
        raise ValueError("Manifest expected_defect_failures must be a non-empty subset of acceptance_check_ids.")
    if not paths or not all(isinstance(path, str) for path in paths):
        raise ValueError("Manifest source.paths must be a non-empty list of repository paths.")
    try:
        task_build_network(manifest.get("environment", {}))
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc
    return manifest


def _open_directories(root: Path) -> None:
    for directory in (root, *(path for path in root.rglob("*") if path.is_dir())):
        os.chmod(directory, 0o755)


def _archive_variant(
    source_repository: Path, revision: str, paths: list[str], destination: Path
) -> None:
    check = _run(["git", "-C", str(source_repository), "cat-file", "-e", f"{revision}^{{commit}}"])
    _require_success(check, "Pinned source revision lookup")
    archive = _run(
        ["git", "-C", str(source_repository), "archive", "--format=tar", revision, *paths],
        text=False,
    )
    if archive.returncode != 0:
        _require_success(archive, "Pinned source archive")
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
            bundle.extractall(path=destination, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise EnvironmentFailure(f"Could not extract pinned source revision: {exc}") from exc
    present = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    if not set(paths) <= present:
        raise EnvironmentFailure(f"Pinned archive is missing task files: {sorted(set(paths) - present)!r}")
    _open_directories(destination)


def _apply_mutation(task_copy: Path, spec_path: Path) -> None:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    target = task_copy / spec["path"]
    source = target.read_text(encoding="utf-8")
    before = spec["before"]
    if source.count(before) != 1:
        raise EnvironmentFailure(
            f"Curator mutation {spec_path.name} expected one source match; found {source.count(before)}."
        )
    target.write_text(source.replace(before, spec["after"], 1), encoding="utf-8")


def prepare_variants(
    source_repository: Path, output_dir: Path, manifest: dict[str, Any], task_package: Path
) -> dict[str, Path]:
    variants_root = output_dir / "variants"
    if variants_root.exists():
        shutil.rmtree(variants_root)
    variants_root.mkdir(parents=True)
    os.chmod(variants_root, 0o755)

    variants = {name: variants_root / name for name in VARIANT_NAMES}
    _archive_variant(
        source_repository, manifest["source"]["revision"], manifest["source"]["paths"], variants["baseline"]
    )
    shutil.copytree(variants["baseline"], variants["defect"])
    _open_directories(variants["defect"])
    _apply_mutation(variants["defect"], task_package / manifest["files"]["defect_mutation"])
    shutil.copytree(variants["defect"], variants["repair"])
    _open_directories(variants["repair"])
    _apply_mutation(variants["repair"], task_package / manifest["files"]["known_repair"])
    return variants


def _build_environment(manifest: dict[str, Any], task_package: Path) -> dict[str, str]:
    # Avoid retagging an admission image that another worktree is evaluating.
    image_tag = f"agent-eval-harness/task-admission:{uuid.uuid4().hex}"
    dockerfile = task_package / manifest["files"]["dockerfile"]
    build_network = task_build_network(manifest["environment"])
    build = _run([
        "docker", "build", f"--network={build_network}", "--pull=false", "--tag", image_tag,
        "--file", str(dockerfile), str(dockerfile.parent),
    ], timeout=600 if build_network != "none" else 120)
    build_output = _require_success(build, "Docker environment build")
    image_id = _require_success(
        _run(["docker", "image", "inspect", "--format", "{{.Id}}", image_tag]),
        "Docker image inspection",
    )
    docker_version = _require_success(
        _run(["docker", "version", "--format", "{{.Server.Version}}"]),
        "Docker server version query",
    )
    probe_name = f"agent-eval-admission-runtime-{os.getpid()}-{os.urandom(4).hex()}"
    try:
        probe = _run([
            "docker", "run", "--rm", "--name", probe_name, "--pull=never",
            "--network=none", "--read-only", "--tmpfs",
            "/tmp:rw,noexec,nosuid,mode=1777,size=16m", image_tag, "python", "-c",
            "import platform; print(platform.python_version())",
        ])
    except EnvironmentFailure:
        _force_remove_container(probe_name)
        raise
    version = _require_success(probe, "Prepared Python runtime probe")
    expected_version = manifest["environment"]["runtime"].removeprefix("Python ")
    if version != expected_version:
        raise EnvironmentFailure(f"Prepared Python runtime was {version}; expected {expected_version}.")
    return {
        "image_tag": image_tag,
        "image_id": image_id,
        "runtime_version": version,
        "docker_server_version": docker_version,
        "dockerfile_sha256": hashlib.sha256(
            dockerfile.read_bytes()
        ).hexdigest(),
        "build": (
            "passed with Docker build network disabled" if build_network == "none"
            else f"passed with Docker build network {build_network}"
        ),
        "build_output": (build_output + "\n" + (build.stderr or "")).strip()[-1000:],
    }


def _run_canonical_checks(
    image_tag: str, task_copy: Path, evaluator_directory: Path, check_version: str,
    expected_python_version: str,
) -> dict[str, Any]:
    result = run_canonical_checks(
        image_tag,
        task_copy,
        evaluator_directory,
        expected_python_version,
        timeout_seconds=60,
    )
    result["check_version"] = check_version
    if "container_configuration" not in result:
        result["container_configuration"] = CONTAINER_CONFIGURATION
    return result


def _invalid_runs(message: str) -> dict[str, dict[str, Any]]:
    return {name: {"status": "error", "checks": {}, "error": message} for name in VARIANT_NAMES}


def run_admission(
    source_repository: Path, output_dir: Path, task_package: Path = DEFAULT_TASK_PACKAGE
) -> dict[str, Any]:
    source_repository = source_repository.expanduser().resolve()
    task_package = task_package.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir == REPOSITORY_ROOT or REPOSITORY_ROOT in output_dir.parents:
        raise ValueError("Admission output must be outside the Git repository.")
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest(task_package)
    result: dict[str, Any] = {
        "schema_version": "1",
        "task_id": manifest["task_id"],
        "task_version": manifest["task_version"],
        "acceptance_check_version": manifest["acceptance_check_version"],
        "source_revision": manifest["source"]["revision"],
        "task_package": task_package_evidence(task_package, manifest),
        "task_package_path": str(task_package),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": _display_path(task_package / "manifest.json"),
        "public_task": _display_path(task_package / manifest["files"]["public_task"]),
        "output_directory": str(output_dir),
        "environment": dict(manifest["environment"]),
        "container_configuration": CONTAINER_CONFIGURATION,
    }

    try:
        variants = prepare_variants(source_repository, output_dir, manifest, task_package)
        environment = _build_environment(manifest, task_package)
        evaluator_directory = (task_package / manifest["files"]["acceptance_checks"]).parent
        runs = {
            name: _run_canonical_checks(
                environment["image_tag"], path, evaluator_directory,
                manifest["acceptance_check_version"],
                manifest["environment"]["runtime"].removeprefix("Python "),
            )
            for name, path in variants.items()
        }
        result["environment_evidence"] = environment
        result["variant_paths"] = {name: str(path) for name, path in variants.items()}
    except (EnvironmentFailure, OSError, KeyError, json.JSONDecodeError) as exc:
        result["environment_error"] = f"{type(exc).__name__}: {exc}"
        runs = _invalid_runs(result["environment_error"])

    result["runs"] = runs
    result["assessment"] = assess_admission(
        runs, manifest["acceptance_check_ids"], manifest["expected_defect_failures"]
    )
    return result


def render_summary(result: dict[str, Any]) -> str:
    status = result["assessment"]["status"]
    classes = {"admitted": "good", "rejected": "bad", "invalid_environment": "unknown"}
    check_rows = []
    check_ids = result["task_package"]["identity"]["acceptance_check_ids"]
    for check_id in check_ids:
        cells = [f"<th scope=\"row\">{html.escape(check_id)}</th>"]
        for name in VARIANT_NAMES:
            run = result["runs"].get(name, {})
            check_map = run.get("checks", {})
            if run.get("status") != "completed":
                label, state = "ENV ERROR", "unknown"
            elif check_map.get(check_id) is True:
                label, state = "PASS", "good"
            else:
                label, state = "FAIL", "bad"
            message = run.get("messages", {}).get(check_id, run.get("error", ""))
            cells.append(
                f"<td class=\"{state}\"><strong>{label}</strong>"
                f"<small>{html.escape(str(message))}</small></td>"
            )
        check_rows.append("<tr>" + "".join(cells) + "</tr>")

    reasons = result["assessment"].get("reasons", [])
    reasons_html = "".join(f"<li>{html.escape(str(reason))}</li>" for reason in reasons)
    if not reasons_html and status == "admitted":
        reasons_html = "<li>Baseline and known repair pass; the introduced defect fails only the expected checks.</li>"
    source = html.escape(str(result.get("source_revision", "unavailable")))
    runtime = html.escape(str(result.get("environment", {}).get("runtime", "unavailable")))
    image_id = html.escape(str(result.get("environment_evidence", {}).get("image_id", "unavailable")))
    docker_version = html.escape(
        str(result.get("environment_evidence", {}).get("docker_server_version", "unavailable"))
    )
    environment_error = result.get("environment_error")
    error_html = (
        f"<p class=\"error\">{html.escape(str(environment_error))}</p>" if environment_error else ""
    )
    rows = "\n".join(check_rows)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Task admission</title>
  <style>
    :root {{ color-scheme: light; font: 15px/1.5 system-ui, sans-serif; color: #202c38; background: #f4f6f8; }}
    body {{ max-width: 980px; margin: 32px auto; padding: 0 20px; }}
    main {{ background: white; padding: 28px; border: 1px solid #d9e0e7; border-radius: 12px; }}
    h1 {{ margin: 0 0 6px; font-size: 1.6rem; }}
    .badge {{ display: inline-block; padding: 3px 10px; border-radius: 99px; font-weight: 700; text-transform: uppercase; }}
    .good {{ color: #14532d; background: #dcfce7; }} .bad {{ color: #991b1b; background: #fee2e2; }}
    .unknown {{ color: #713f12; background: #fef3c7; }}
    dl {{ display: grid; grid-template-columns: 150px 1fr; gap: 5px 16px; }} dt {{ color: #526170; }} dd {{ margin: 0; overflow-wrap: anywhere; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }} th, td {{ border-bottom: 1px solid #e5eaf0; padding: 9px; text-align: left; vertical-align: top; }}
    thead th {{ background: #f4f6f8; }} td small {{ display: block; margin-top: 3px; color: #526170; font-weight: 400; }}
    .error {{ color: #991b1b; }} ul {{ padding-left: 22px; }}
    @media (max-width: 700px) {{ main {{ padding: 18px; }} table {{ font-size: 12px; }} th, td {{ padding: 6px 4px; }} dl {{ grid-template-columns: 1fr; }} dd {{ margin-bottom: 6px; }} }}
  </style>
</head>
<body>
<main>
  <h1>Task admission: {html.escape(result.get('task_id', 'unknown'))}</h1>
  <p><span class="badge {classes.get(status, 'unknown')}">{html.escape(status.replace('_', ' '))}</span></p>
  <dl>
    <dt>Task</dt><dd>{html.escape(result.get('task_id', 'unknown'))} v{html.escape(result.get('task_version', 'unknown'))}</dd>
    <dt>Source revision</dt><dd><code>{source}</code></dd>
    <dt>Acceptance checks</dt><dd>{html.escape(str(result.get('acceptance_check_version', 'unknown')))}</dd>
    <dt>Runtime</dt><dd>{runtime}</dd>
    <dt>Docker server</dt><dd>{docker_version}</dd>
    <dt>Docker image ID</dt><dd><code>{image_id}</code></dd>
    <dt>Isolation</dt><dd>Candidate worker has a read-only task mount and no evaluator mount; canonical assertions run in the outer harness after it exits. Container networking is disabled; container root is read-only; no credentials or Docker socket are mounted.</dd>
    <dt>Generated</dt><dd>{html.escape(result.get('generated_at', 'unknown'))}</dd>
  </dl>
  {error_html}
  <h2>Canonical check evidence</h2>
  <table>
    <thead><tr><th>Behavior</th><th>Baseline</th><th>Introduced defect</th><th>Known repair</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <h2>Admission decision</h2>
  <ul>{reasons_html}</ul>
</main>
</body>
</html>
"""


def write_artifacts(result: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "admission.json"
    html_path = output_dir / "summary.html"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    html_path.write_text(render_summary(result), encoding="utf-8")
    return json_path, html_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", type=Path, required=True,
                        help="Local Git checkout of the task's source repository, containing the pinned commit.")
    parser.add_argument("--task-package", type=Path, default=DEFAULT_TASK_PACKAGE,
                        help="Task package directory with manifest.json (default: the ML Tutor task).")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Directory for JSON, HTML, and prepared variants (default: {DEFAULT_OUTPUT}).")
    args = parser.parse_args(argv)

    try:
        result = run_admission(args.source_repository, args.output_dir, args.task_package)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    json_path, html_path = write_artifacts(result, args.output_dir.expanduser().resolve())
    print(json.dumps({
        "status": result["assessment"]["status"],
        "json": str(json_path),
        "html": str(html_path),
        "assessment": result["assessment"],
    }, sort_keys=True))
    return {"admitted": 0, "rejected": 1, "invalid_environment": 2}.get(
        result["assessment"]["status"], 2
    )


if __name__ == "__main__":
    sys.exit(main())

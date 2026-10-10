"""Prepare and run the pinned ML Tutor task admission experiment."""

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

from agent_eval_harness.admission import CHECK_IDS, VARIANT_NAMES, assess_admission


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TASK_ROOT = REPOSITORY_ROOT / "tasks" / "ml_tutor_retrieval"
MANIFEST_PATH = TASK_ROOT / "manifest.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT.parents[1] / "orchestration" / "evidence" / "issue-2"
VARIANT_PATHS = ("app/__init__.py", "app/source.py", "app/tutor.py")
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
        {"source_role": "canonical_evaluator", "target": "/evaluator", "read_only": True},
    ],
    "credentials_or_container_socket_mounted": False,
}


class EnvironmentFailure(RuntimeError):
    """A setup or evaluator problem that must not be scored as a task failure."""


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


def _load_manifest() -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("acceptance_check_ids") != list(CHECK_IDS):
        raise EnvironmentFailure("Manifest acceptance check IDs do not match the canonical check runner.")
    return manifest


def _archive_variant(source_repository: Path, revision: str, destination: Path) -> None:
    check = _run(["git", "-C", str(source_repository), "cat-file", "-e", f"{revision}^{{commit}}"])
    _require_success(check, "Pinned source revision lookup")
    archive = _run(
        ["git", "-C", str(source_repository), "archive", "--format=tar", revision, *VARIANT_PATHS],
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
    if present != set(VARIANT_PATHS):
        raise EnvironmentFailure(f"Pinned archive had unexpected task files: {sorted(present)!r}")
    for directory in (destination, destination / "app"):
        os.chmod(directory, 0o755)


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


def prepare_variants(source_repository: Path, output_dir: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    variants_root = output_dir / "variants"
    if variants_root.exists():
        shutil.rmtree(variants_root)
    variants_root.mkdir(parents=True)
    os.chmod(variants_root, 0o755)

    variants = {name: variants_root / name for name in VARIANT_NAMES}
    _archive_variant(source_repository, manifest["source"]["revision"], variants["baseline"])
    shutil.copytree(variants["baseline"], variants["defect"])
    os.chmod(variants["defect"], 0o755)
    os.chmod(variants["defect"] / "app", 0o755)
    _apply_mutation(variants["defect"], TASK_ROOT / "curator" / "defect.json")
    shutil.copytree(variants["defect"], variants["repair"])
    os.chmod(variants["repair"], 0o755)
    os.chmod(variants["repair"] / "app", 0o755)
    _apply_mutation(variants["repair"], TASK_ROOT / "curator" / "repair.json")
    return variants


def _build_environment(manifest: dict[str, Any]) -> dict[str, str]:
    image_tag = "agent-eval-harness/ml-tutor-admission:1.0.0"
    build = _run([
        "docker", "build", "--network=none", "--pull=false", "--tag", image_tag,
        "--file", str(TASK_ROOT / "environment" / "Dockerfile"),
        str(TASK_ROOT / "environment"),
    ])
    build_output = _require_success(build, "Offline Docker environment build")
    image_id = _require_success(
        _run(["docker", "image", "inspect", "--format", "{{.Id}}", image_tag]),
        "Docker image inspection",
    )
    docker_version = _require_success(
        _run(["docker", "version", "--format", "{{.Server.Version}}"]),
        "Docker server version query",
    )
    version = _require_success(
        _run([
            "docker", "run", "--rm", "--pull=never", "--network=none", "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,mode=1777,size=16m",
            image_tag, "python", "-c", "import platform; print(platform.python_version())",
        ]),
        "Prepared Python runtime probe",
    )
    expected_version = manifest["environment"]["runtime"].removeprefix("Python ")
    if version != expected_version:
        raise EnvironmentFailure(f"Prepared Python runtime was {version}; expected {expected_version}.")
    return {
        "image_tag": image_tag,
        "image_id": image_id,
        "runtime_version": version,
        "docker_server_version": docker_version,
        "dockerfile_sha256": hashlib.sha256(
            (TASK_ROOT / "environment" / "Dockerfile").read_bytes()
        ).hexdigest(),
        "build": "passed with Docker build network disabled",
        "build_output": (build_output + "\n" + (build.stderr or "")).strip()[-1000:],
    }


def _run_canonical_checks(
    image_tag: str, task_copy: Path, check_version: str, expected_python_version: str
) -> dict[str, Any]:
    command = [
        "docker", "run", "--rm", "--pull=never", "--network=none", "--read-only",
        "--tmpfs", TMPFS_CONFIGURATION,
        "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=64",
        "--mount", f"type=bind,source={task_copy.resolve()},target=/task,readonly",
        "--mount", f"type=bind,source={(TASK_ROOT / 'curator').resolve()},target=/evaluator,readonly",
        "--workdir", "/task",
        "--env", "PYTHONPATH=/task",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        image_tag, "python", "/evaluator/checks.py",
    ]
    result = _run(command, timeout=60)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no evaluator output").strip()
        return {"status": "error", "checks": {}, "error": detail[-2000:]}
    try:
        payload = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "checks": {},
            "error": f"Canonical runner returned invalid JSON: {exc}",
            "stdout": result.stdout[-2000:],
        }
    if payload.get("python_version") != expected_python_version:
        return {
            "status": "error", "checks": {},
            "error": f"Check runner used Python {payload.get('python_version')!r}.",
        }
    payload["check_version"] = check_version
    payload["container_configuration"] = CONTAINER_CONFIGURATION
    return payload


def _invalid_runs(message: str) -> dict[str, dict[str, Any]]:
    return {name: {"status": "error", "checks": {}, "error": message} for name in VARIANT_NAMES}


def run_admission(source_repository: Path, output_dir: Path) -> dict[str, Any]:
    source_repository = source_repository.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir == REPOSITORY_ROOT or REPOSITORY_ROOT in output_dir.parents:
        raise ValueError("Admission output must be outside the Git repository.")
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest()
    result: dict[str, Any] = {
        "schema_version": "1",
        "task_id": manifest["task_id"],
        "task_version": manifest["task_version"],
        "acceptance_check_version": manifest["acceptance_check_version"],
        "source_revision": manifest["source"]["revision"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(MANIFEST_PATH.relative_to(REPOSITORY_ROOT)),
        "public_task": str((TASK_ROOT / manifest["files"]["public_task"]).relative_to(REPOSITORY_ROOT)),
        "output_directory": str(output_dir),
        "environment": dict(manifest["environment"]),
        "container_configuration": CONTAINER_CONFIGURATION,
    }

    try:
        variants = prepare_variants(source_repository, output_dir, manifest)
        environment = _build_environment(manifest)
        runs = {
            name: _run_canonical_checks(
                environment["image_tag"], path, manifest["acceptance_check_version"],
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
    result["assessment"] = assess_admission(runs)
    return result


def render_summary(result: dict[str, Any]) -> str:
    status = result["assessment"]["status"]
    classes = {"admitted": "good", "rejected": "bad", "invalid_environment": "unknown"}
    check_rows = []
    check_ids = list(CHECK_IDS)
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
        reasons_html = "<li>Baseline and known repair pass; the introduced defect fails only the title-relevance checks.</li>"
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
  <title>ML Tutor task admission</title>
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
  <h1>ML Tutor retrieval task admission</h1>
  <p><span class="badge {classes.get(status, 'unknown')}">{html.escape(status.replace('_', ' '))}</span></p>
  <dl>
    <dt>Task</dt><dd>{html.escape(result.get('task_id', 'unknown'))} v{html.escape(result.get('task_version', 'unknown'))}</dd>
    <dt>Source revision</dt><dd><code>{source}</code></dd>
    <dt>Acceptance checks</dt><dd>{html.escape(str(result.get('acceptance_check_version', 'unknown')))}</dd>
    <dt>Runtime</dt><dd>{runtime}</dd>
    <dt>Docker server</dt><dd>{docker_version}</dd>
    <dt>Docker image ID</dt><dd><code>{image_id}</code></dd>
    <dt>Isolation</dt><dd>Network disabled; read-only task and evaluator mounts; read-only container root; no credentials or Docker socket mounted.</dd>
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
                        help="Local ML Tutor Git checkout containing the pinned commit.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Directory for JSON, HTML, and prepared variants (default: {DEFAULT_OUTPUT}).")
    args = parser.parse_args(argv)

    try:
        result = run_admission(args.source_repository, args.output_dir)
    except ValueError as exc:
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

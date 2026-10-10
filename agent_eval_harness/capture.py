"""Observed-only, bounded capture of repository changes after potentially mutating tools.

A capture describes the task repository relative to the attempt's starting state. It is
taken only when an event sink is attached, never writes to the repository, and never changes
a tool result, a model-visible message or the canonical candidate collection.

Settlement (when a capture is allowed to describe the repository):
- the container was force-removed after a shell timeout: every process in it is gone;
- apply_patch returned: its edit process has exited;
- run_shell returned: a return alone does not prove that background writers finished, so a
  read-only probe lists live processes in the container. PID 1 (the idle sleeper) and zombies
  are not counted. A live process makes the capture `unsettled`; the probe never signals anything.
A probe that does not finish within the time limit is a declared omission (`time_limit`); a
probe that fails for another reason is `unavailable`. Neither changes the tool's semantics.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import stat
import time
from typing import Any, Mapping

from agent_eval_harness.environment import CommandTimeout, DockerTaskContainer, EnvironmentFailure, _run
from agent_eval_harness.evaluation import _candidate_changes
from agent_eval_harness.observation import json_artifact


SCHEMA = "agent-eval-harness/repository-capture"
SCHEMA_VERSION = 1
MUTATING_TOOLS = frozenset({"apply_patch", "run_shell"})
ARTIFACT_ROLE = "capture.json"

# Read-only process listing, run inside the task container with `python -c`.
PROBE = """
import json, os
me = os.getpid()
live = []
for name in os.listdir('/proc'):
    if not name.isdigit() or int(name) in (1, me):
        continue
    try:
        fields = open(f'/proc/{name}/stat').read().rsplit(')', 1)[1].split()
        command = open(f'/proc/{name}/cmdline', 'rb').read().replace(b'\\0', b' ').decode(errors='replace').strip()
    except OSError:
        continue
    if fields[0] == 'Z' or int(fields[1]) == me:
        continue
    live.append({'pid': int(name), 'state': fields[0], 'command': command})
print(json.dumps({'complete': True, 'live': live}, sort_keys=True))
"""


# ponytail: limits are calibrated once on the scripted workloads (live-tracker/README.md) and
# passed explicitly; an adaptive limit would make two runs of the same script capture differently.
# Calibrated: the pinned task repository reads as 1.85 MB per capture; captures took 14-190 ms.
@dataclass(frozen=True)
class CaptureLimits:
    max_seconds: float = 2.0
    max_total_bytes: int = 4 * 1024 * 1024
    max_preview_bytes: int = 4 * 1024

    def __post_init__(self) -> None:
        if self.max_seconds <= 0:
            raise ValueError("max_seconds must be positive")
        if self.max_total_bytes < 1:
            raise ValueError("max_total_bytes must be positive")
        if self.max_preview_bytes < 1:
            raise ValueError("max_preview_bytes must be positive")


class _Omitted(Exception):
    """A declared bounded omission: the capture stopped at a positive limit."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _bounded_snapshot(root: Path, *, deadline: float, max_bytes: int) -> dict[str, tuple[bytes, int]]:
    """The same files and modes as evaluation._snapshot_repository, stopped at the limits."""
    snapshot: dict[str, tuple[bytes, int]] = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if time.monotonic() > deadline:
            raise _Omitted("time_limit")
        if path.is_symlink():
            raise EnvironmentFailure(f"symbolic link in the repository: {path.relative_to(root)}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/"):
            continue
        status = path.stat()
        total += status.st_size
        if total > max_bytes:
            raise _Omitted("byte_limit")
        mode = 0o755 if status.st_mode & stat.S_IXUSR else 0o644
        snapshot[relative] = (path.read_bytes(), mode)
    return snapshot


def _text(content: bytes | None) -> str | None:
    if content is None:
        return ""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _side(content: bytes | None) -> dict[str, Any] | None:
    if content is None:
        return None
    return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


class RepositoryCapture:
    """Describes the task repository after one tool operation; one instance per observed attempt."""

    def __init__(
        self,
        container: DockerTaskContainer,
        repository: Path,
        baseline: Mapping[str, tuple[bytes, int]],
        limits: CaptureLimits | None = None,
    ):
        self.container = container
        self.repository = repository
        self.baseline = baseline
        self.limits = limits or CaptureLimits()
        self.status_counts: dict[str, int] = {}
        self.capture_seconds = 0.0

    def observe(self, tool_name: str) -> tuple[dict[str, Any], dict[str, bytes]]:
        """Return (event data, artifacts) for one dispatched mutating tool. Never raises for capture faults."""
        started = time.monotonic()
        deadline = started + self.limits.max_seconds
        data: dict[str, Any] = {"tool_name": tool_name, "limits": asdict(self.limits)}
        artifacts: dict[str, bytes] = {}
        try:
            settlement = self._settle(tool_name, deadline)
            data["settlement"] = settlement
            if settlement["status"] == "settled":
                content, artifacts = self._describe(tool_name, settlement, deadline)
                data.update(content)
            elif settlement["status"] == "unknown":
                data.update(status="omitted", reason="time_limit")
            else:
                data.update(status=settlement["status"], reason=settlement.get("reason"))
        except _Omitted as omitted:
            data.update(status="omitted", reason=omitted.reason)
        except Exception as exc:
            data.update(status="error", reason=f"{type(exc).__name__}: {exc}")
        data["capture_seconds"] = round(time.monotonic() - started, 6)
        self.capture_seconds += data["capture_seconds"]
        self.status_counts[data["status"]] = self.status_counts.get(data["status"], 0) + 1
        return data, artifacts

    def summary(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "limits": asdict(self.limits),
            "captures": sum(self.status_counts.values()),
            "status_counts": dict(sorted(self.status_counts.items())),
            "capture_seconds": round(self.capture_seconds, 6),
        }

    def _settle(self, tool_name: str, deadline: float) -> dict[str, Any]:
        if self.container.container_id is None:
            return {"status": "settled", "method": "container_removed",
                    "reason": "the shell timed out and its container was force-removed"}
        if tool_name == "apply_patch":
            return {"status": "settled", "method": "apply_patch_returned",
                    "reason": "the edit process has exited"}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"status": "unknown", "method": "process_probe",
                    "reason": "no time left in the capture limit to probe"}
        try:
            completed = _run(
                ["docker", "exec", self.container.container_id, "python", "-c", PROBE],
                timeout=remaining,
            )
        except CommandTimeout:
            return {"status": "unknown", "method": "process_probe",
                    "reason": "the probe did not finish within the capture limit"}
        except EnvironmentFailure as exc:
            return {"status": "unavailable", "method": "process_probe", "reason": f"probe failed: {exc}"}
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "no output").strip()
            return {"status": "unavailable", "method": "process_probe",
                    "reason": f"probe exited with {completed.returncode}: {detail[-300:]}"}
        try:
            report = json.loads(completed.stdout)
        except ValueError:
            return {"status": "unavailable", "method": "process_probe", "reason": "probe output was not JSON"}
        if not isinstance(report, dict) or report.get("complete") is not True:
            return {"status": "unavailable", "method": "process_probe", "reason": "probe did not complete"}
        if report.get("live"):
            return {"status": "unsettled", "method": "process_probe",
                    "reason": "processes were still alive after the shell returned",
                    "live_processes": report["live"]}
        return {"status": "settled", "method": "process_probe",
                "reason": "no process besides PID 1 and the probe was alive"}

    def _describe(
        self, tool_name: str, settlement: dict[str, Any], deadline: float
    ) -> tuple[dict[str, Any], dict[str, bytes]]:
        current = _bounded_snapshot(self.repository, deadline=deadline, max_bytes=self.limits.max_total_bytes)
        changes: list[dict[str, Any]] = []
        full: list[dict[str, Any]] = []
        totals = {"files": 0, "additions": 0, "deletions": 0, "binary_files": 0}
        for change in _candidate_changes(self.baseline, current):
            path = change["path"]
            before = self.baseline[path][0] if path in self.baseline else None
            after = current[path][0] if path in current else None
            before_text, after_text = _text(before), _text(after)
            entry: dict[str, Any] = {
                "path": path, "action": change["action"], "before": _side(before), "after": _side(after),
            }
            full_diff = None
            totals["files"] += 1
            if before_text is None or after_text is None:
                entry.update(kind="binary", additions=None, deletions=None, preview=None, preview_truncated=None)
                totals["binary_files"] += 1
            else:
                old_lines = before_text.splitlines(keepends=True)
                new_lines = after_text.splitlines(keepends=True)
                additions = deletions = 0
                for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines).get_opcodes():
                    if tag in ("replace", "delete"):
                        deletions += i2 - i1
                    if tag in ("replace", "insert"):
                        additions += j2 - j1
                diff = "".join(difflib.unified_diff(
                    old_lines, new_lines,
                    fromfile=f"a/{path}" if path in self.baseline else "/dev/null",
                    tofile=f"b/{path}" if path in current else "/dev/null",
                ))
                diff_bytes = diff.encode("utf-8")
                limit = self.limits.max_preview_bytes
                entry.update(
                    kind="text", additions=additions, deletions=deletions,
                    preview=diff_bytes[:limit].decode("utf-8", errors="replace"),
                    preview_truncated=len(diff_bytes) > limit,
                )
                full_diff = diff
                totals["additions"] += additions
                totals["deletions"] += deletions
            changes.append(entry)
            # The artifact repeats each event entry and adds the full text diff (text files only).
            full.append(dict(entry, diff=full_diff) if full_diff is not None else dict(entry))
        content = {
            "status": "captured",
            "reason": None,
            "totals": totals,
            "bytes_read": sum(len(file_content) for file_content, _ in current.values()),
            "changes": changes,
        }
        artifact = json_artifact({
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "tool_name": tool_name,
            "settlement": settlement, "changes": full,
        })
        return content, {ARTIFACT_ROLE: artifact}

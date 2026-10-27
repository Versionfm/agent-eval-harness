"""05 · Built-in primitives — the concrete repository tools, run inside the disposable task container."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from agent_eval_harness.harness.permissions import (
    CommandTimeout, DockerTaskContainer, EnvironmentFailure, _safe_relative_path,
)


def _tool_result(
    result: subprocess.CompletedProcess,
    *,
    timed_out: str | None = None,
) -> dict[str, Any]:
    output = result.stdout or ""
    if result.stderr:
        output += ("\n" if output else "") + result.stderr
    code = result.returncode
    status = "ok" if code == 0 and timed_out is None else "error"
    error = timed_out or (None if code == 0 else f"command exited with status {code}")
    return {"status": status, "output": output, "error": error, "exit_code": code}


def _tool_environment_error(exc: EnvironmentFailure) -> dict[str, Any]:
    if isinstance(exc, CommandTimeout):
        result = _tool_result(
            subprocess.CompletedProcess([], None, stdout=exc.stdout, stderr=exc.stderr),
            timed_out=str(exc),
        )
        result["error_category"] = "command_timeout"
        result["retryable"] = False
        return result
    return {
        "status": "error", "output": "", "error": str(exc), "exit_code": None,
        "error_category": "environment_failure", "retryable": False,
    }


def _python_exec(container: DockerTaskContainer, script: str, args: list[str] = (), *, input_text: str | None = None,
                 timeout: float = 30) -> dict[str, Any]:
    try:
        result = container.exec(["python", "-c", script, *args], timeout=timeout, input_text=input_text)
    except EnvironmentFailure as exc:
        return _tool_environment_error(exc)
    return _tool_result(result)


def read_file(container: DockerTaskContainer, path: str, *, timeout: float = 30) -> dict[str, Any]:
    relative = _safe_relative_path(path)
    script = (
        "from pathlib import Path; import sys; root=Path('/task').resolve(); "
        "p=(root/sys.argv[1]).resolve(); "
        "assert root == p or root in p.parents, 'path leaves task repository'; "
        "assert p.is_file(), 'file does not exist'; sys.stdout.write(p.read_text(encoding='utf-8'))"
    )
    return _python_exec(container, script, [relative.as_posix()], timeout=timeout)


def search_text(container: DockerTaskContainer, query: str, *, timeout: float = 30) -> dict[str, Any]:
    if not query:
        return {"status": "error", "output": "", "error": "search query cannot be empty", "exit_code": None}
    script = r"""
from pathlib import Path
import sys
root = Path('/task').resolve()
query = sys.argv[1].casefold()
for path in sorted(root.rglob('*')):
    if path.is_symlink() or not path.is_file() or '.git' in path.relative_to(root).parts:
        continue
    try:
        text = path.read_text(encoding='utf-8')
    except (UnicodeError, OSError):
        continue
    for number, line in enumerate(text.splitlines(), 1):
        if query in line.casefold():
            print(f'{path.relative_to(root).as_posix()}:{number}:{line}')
"""
    return _python_exec(container, script, [query], timeout=timeout)


def apply_patch(
    container: DockerTaskContainer, arguments: dict[str, Any], *, timeout: float = 30
) -> dict[str, Any]:
    try:
        relative = _safe_relative_path(str(arguments["path"]))
        if "content" in arguments and "old_text" not in arguments:
            if not isinstance(arguments["content"], str):
                raise ValueError("content must be text")
            operation = "create"
        elif all(key in arguments for key in ("old_text", "new_text")):
            if not isinstance(arguments["old_text"], str) or not isinstance(arguments["new_text"], str):
                raise ValueError("old_text and new_text must be text")
            operation = "replace"
        else:
            raise ValueError("provide content to create a file, or old_text and new_text to edit one")
    except (KeyError, ValueError, TypeError) as exc:
        return {
            "status": "error", "output": "", "error": str(exc), "exit_code": None,
            "error_category": "patch_rejected", "retryable": False,
        }

    payload = dict(arguments, path=relative.as_posix(), operation=operation)
    script = r"""
from pathlib import Path
import json, sys
data = json.load(sys.stdin)
root = Path('/task').resolve()
target = root.joinpath(*data['path'].split('/'))
if target.is_symlink():
    raise ValueError('symbolic-link edits are not supported')
if root not in target.parent.resolve().parents and target.parent.resolve() != root:
    raise ValueError('path leaves task repository')
if data['operation'] == 'create':
    if target.exists():
        raise FileExistsError(data['path'])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data['content'], encoding='utf-8')
    print(f"created {data['path']}")
else:
    if not target.is_file():
        raise FileNotFoundError(data['path'])
    text = target.read_text(encoding='utf-8')
    count = text.count(data['old_text'])
    if count != 1:
        raise ValueError(f"expected one old_text match, found {count}")
    target.write_text(text.replace(data['old_text'], data['new_text'], 1), encoding='utf-8')
    print(f"updated {data['path']}")
"""
    try:
        result = container.exec(
            ["python", "-c", script], timeout=timeout, input_text=json.dumps(payload)
        )
    except EnvironmentFailure as exc:
        return _tool_environment_error(exc)
    return _tool_result(result)


def run_shell(container: DockerTaskContainer, command: str, timeout: float) -> dict[str, Any]:
    if not isinstance(command, str) or not command.strip():
        return {"status": "error", "output": "", "error": "shell command cannot be empty", "exit_code": None}
    try:
        result = container.exec(["/bin/sh", "-lc", command], timeout=timeout)
    except EnvironmentFailure as exc:
        return _tool_environment_error(exc)
    return _tool_result(result)

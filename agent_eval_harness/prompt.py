"""Build the initial system and task messages shown to the coding model."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_eval_harness.attempt import AdmittedTask


def _initial_context(task: AdmittedTask, task_repository: Path) -> list[dict[str, str]]:
    from agent_eval_harness.tools import TOOL_DEFINITIONS

    public_task = task.public_task_path.read_text(encoding="utf-8")
    instructions_path = task_repository / "AGENTS.md"
    instructions = instructions_path.read_text(encoding="utf-8") if instructions_path.is_file() else ""
    files = sorted(
        path.relative_to(task_repository).as_posix()
        for path in task_repository.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(task_repository).parts
    )
    root_files = [path for path in files if "/" not in path]
    selected = list(root_files[:10])
    for directory, allowance in (("app/", 30), ("src/", 20), ("tests/", 30)):
        selected.extend([path for path in files if path.startswith(directory)][:allowance])
    selected = list(dict.fromkeys(selected))[:100]
    selected_set = set(selected)
    remaining = [path for path in files if path not in selected_set]
    selected.extend(remaining[: max(0, 100 - len(selected))])
    file_map = "\n".join(f"- {path}" for path in selected)
    omitted = [path for path in files if path not in set(selected)]
    if omitted:
        counts: dict[str, int] = {}
        for path in omitted:
            area = path.split("/", 1)[0] if "/" in path else "(root)"
            counts[area] = counts.get(area, 0) + 1
        common_areas = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:8]
        summary = ", ".join(f"{area} ({count})" for area, count in common_areas)
        file_map += (
            f"\n- ... and {len(omitted)} more files"
            f"\nAdditional file counts by area: {summary}"
        )
    system = (
        "You are a coding agent working on a bug-repair task. Use repository tools to inspect, "
        "edit, and run checks. The task environment contains a writable pinned repository. "
        "The task repository is the only mounted host directory.\n\n"
        "Available tools:\n" + "\n".join(
            f"- {name}: {details['description']}" for name, details in TOOL_DEFINITIONS.items()
        )
    )
    user = (
        f"Task description:\n{public_task}\n\n"
        "Repository instructions (AGENTS.md):\n"
        f"{instructions or '(No AGENTS.md found.)'}\n\n"
        "Repository file map:\n" + file_map
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


build_initial_context = _initial_context

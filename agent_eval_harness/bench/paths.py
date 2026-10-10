"""Resolve external learning artifacts beside either a checkout or managed worktree."""

from pathlib import Path


def orchestration_root(repository_root: Path) -> Path:
    """Find the shared ``work/orchestration`` directory for this repo checkout."""
    repository_root = repository_root.expanduser().resolve()
    for parent in repository_root.parents:
        candidate = parent / "work" / "orchestration"
        if candidate.is_dir():
            return candidate
    # Keep the established layout as the fallback when the workspace artifacts
    # have not been created yet.
    return repository_root.parents[1] / "work" / "orchestration"

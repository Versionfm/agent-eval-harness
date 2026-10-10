"""Enforce the layout rule in AGENTS.md: layer folders, harness components, module headers and imports.

Offline and stdlib only. Adding a harness file means updating HARNESS_HEADERS here on purpose.
"""

import ast
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "agent_eval_harness"
PACKAGE = REPOSITORY / PACKAGE_NAME
LAYERS = ("harness", "bench", "reports", "cli")

# The harness folder holds exactly these files. Each numbered component (and each model adapter)
# must start its module docstring with the given header. 04 subagents is a known gap: no file, no placeholder.
HARNESS_HEADERS = {
    "loop.py": "01 · ",
    "graph.py": "01 · ",
    "context.py": "02 · ",
    "tools.py": "03 · ",
    "builtins.py": "05 · ",
    "persistence.py": "06 · ",
    "prompt.py": "07 · ",
    "hooks.py": "08 · ",
    "permissions.py": "09 · ",
    "model.py": "Model adapter · ",
    "deepseek.py": "Model adapter · ",
}

LAYER_HEADERS = {
    "bench": "Bench · ",
    "reports": "Reports · ",
    "cli": "CLI · ",
}

# The layers each layer may import. Anything else inside agent_eval_harness is a violation.
ALLOWED_IMPORTS = {
    "harness": {"harness"},
    "reports": {"reports", "harness"},
    "bench": {"bench", "harness", "reports"},
    "cli": {"cli", "bench", "harness", "reports"},
}


def _python_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*.py") if "__pycache__" not in path.parts)


def _relative(path: Path) -> str:
    return path.relative_to(REPOSITORY).as_posix()


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _header_problems(path: Path, prefix: str) -> list[str]:
    docstring = ast.get_docstring(_parse(path), clean=False)
    if docstring is None:
        return [f"{_relative(path)}: has no module docstring; it must start with '{prefix}'"]
    first_line = docstring.split("\n", 1)[0]
    if not first_line.startswith(prefix):
        return [f"{_relative(path)}: module docstring must start with '{prefix}' (first line: {first_line!r})"]
    return []


def _layer_of(parts: tuple[str, ...]) -> str | None:
    if len(parts) > 1 and parts[0] == PACKAGE_NAME and parts[1] in LAYERS:
        return parts[1]
    return None


def _imported_modules(path: Path) -> list[tuple[int, tuple[str, ...]]]:
    """Every import in the module, including TYPE_CHECKING and function-level ones, as absolute dotted names."""
    package = path.relative_to(REPOSITORY).with_suffix("").parts[:-1]
    found = []
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, tuple(alias.name.split("."))) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            start = package[: len(package) - (node.level - 1)] if node.level else ()
            base = start + (tuple(node.module.split(".")) if node.module else ())
            found.append((node.lineno, base))
            if base == (PACKAGE_NAME,):
                # "from agent_eval_harness import bench" names a layer through its alias.
                found.extend((node.lineno, base + (alias.name,)) for alias in node.names)
    return found


class LayoutRuleTests(unittest.TestCase):
    def test_package_root_holds_only_the_layer_folders(self):
        names = {path.name for path in PACKAGE.iterdir() if path.name != "__pycache__"}
        expected = {"__init__.py", *LAYERS}
        problems = []
        if names - expected:
            problems.append(
                f"{PACKAGE_NAME}/ holds unexpected entries {sorted(names - expected)}; "
                f"only __init__.py and the layer folders {list(LAYERS)} belong at the top (AGENTS.md)."
            )
        if expected - names:
            problems.append(f"{PACKAGE_NAME}/ is missing {sorted(expected - names)} (AGENTS.md).")
        self._fail_with(problems)

    def test_harness_holds_exactly_the_expected_components(self):
        names = {path.name for path in (PACKAGE / "harness").iterdir() if path.name != "__pycache__"}
        expected = {"__init__.py", *HARNESS_HEADERS}
        problems = []
        if names - expected:
            problems.append(
                f"{PACKAGE_NAME}/harness/ holds unexpected files {sorted(names - expected)}. "
                "Only numbered components and model adapters belong here; 04 subagents is a known gap, "
                "so do not add a placeholder. A new file needs an entry in HARNESS_HEADERS in tests/test_layout.py."
            )
        if expected - names:
            problems.append(f"{PACKAGE_NAME}/harness/ is missing {sorted(expected - names)}.")
        self._fail_with(problems)

    def test_each_harness_component_starts_with_its_number(self):
        problems = []
        for name, prefix in HARNESS_HEADERS.items():
            path = PACKAGE / "harness" / name
            if path.is_file():
                problems.extend(_header_problems(path, prefix))
        self._fail_with(problems)

    def test_every_bench_reports_and_cli_module_starts_with_its_layer(self):
        problems = _header_problems(PACKAGE / "harness" / "__init__.py", "Harness · ")
        for layer, prefix in LAYER_HEADERS.items():
            for path in _python_files(PACKAGE / layer):
                problems.extend(_header_problems(path, prefix))
        self._fail_with(problems)

    def test_import_direction_follows_the_layers(self):
        problems = []
        for layer in LAYERS:
            for path in _python_files(PACKAGE / layer):
                for line, target in _imported_modules(path):
                    target_layer = _layer_of(target)
                    if target_layer is None or target_layer in ALLOWED_IMPORTS[layer]:
                        continue
                    problems.append(
                        f"{_relative(path)}:{line} imports {'.'.join(target)}. Rule broken: {layer}/ may import "
                        f"only {', '.join(sorted(ALLOWED_IMPORTS[layer]))} (AGENTS.md, import direction)."
                    )
        self._fail_with(problems)

    def _fail_with(self, problems: list[str]) -> None:
        if problems:
            self.fail("\n".join(problems))


if __name__ == "__main__":
    unittest.main()

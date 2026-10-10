# Agent instructions

## Layout rule

`agent_eval_harness/` has four layers. Every module belongs to exactly one.

- `harness/` is the agent. It holds the numbered components and the model adapters, and nothing else:
  01 loop and graph, 02 context, 03 tools, 05 builtins, 06 persistence, 07 prompt, 08 hooks,
  09 permissions, plus `model.py` and `deepseek.py`. 04 subagents is a known gap. Do not add a placeholder.
- `bench/` runs the agent on a task and grades it: attempt lifecycle, task environments, candidate capture and evaluation, artifacts.
- `reports/` renders saved evidence as HTML. It imports nothing from `bench/` or `cli/`.
- `cli/` holds runnable commands. Nothing in the package imports it except `cli/`.

Import direction: `cli` may import every layer. `bench` may import `harness` and `reports`.
`harness` imports only `harness`. `reports` imports no `bench` or `cli` module.
This includes `TYPE_CHECKING` and function-level imports.

Every module, new or changed, starts its docstring with its layer or component on the first line:

- `01 · While loop — ...`, `02 · Context management — ...`, and so on in `harness/`.
- `Model adapter · ...` for `model.py` and `deepseek.py`.
- `Bench · ...`, `Reports · ...`, `CLI · ...` in the other layers.

Adding a harness file means updating the expected set in `tests/test_layout.py` on purpose, in the same change.
Do not add top-level modules to `agent_eval_harness/`. Put new code in the layer it belongs to.

Run `python3 -m unittest tests.test_layout` to check these rules. The component map is `docs/COMPONENT_MAP.md`.

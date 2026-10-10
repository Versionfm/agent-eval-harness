# Component map

This map follows one attempt from its public command through the model, tools, independent checks, and saved report. The layout follows the learning sketch: `harness/` holds the agent, with one file per numbered component. The other layers keep evaluation, reports and commands apart from the agent. The rule is in [AGENTS.md](../AGENTS.md), and `tests/test_layout.py` enforces it.

## Annotated tree

```text
agent_eval_harness/
├── harness/                  THE AGENT: numbered components and model adapters
│   ├── loop.py               # 01 · while loop
│   ├── graph.py              # 01 · the same loop as a LangGraph
│   ├── context.py            # 02 · context management
│   ├── tools.py              # 03 · tools registry
│   │                         # 04 · subagents: not built (known gap)
│   ├── builtins.py           # 05 · built-in primitives
│   ├── persistence.py        # 06 · session records
│   ├── prompt.py             # 07 · system prompt assembly
│   ├── hooks.py              # 08 · hooks
│   ├── permissions.py        # 09 · permissions & safety
│   ├── model.py              # model adapter · contract and scripted adapter
│   └── deepseek.py           # model adapter · DeepSeek
├── bench/                    RUNS THE AGENT ON A TASK AND GRADES IT
│   ├── attempt.py            # attempt lifecycle facade
│   ├── environment.py        # task image, defect copy, canonical checks
│   ├── evaluation.py         # candidate snapshot and verdict
│   ├── capture.py            # repository capture (a post-tool hook)
│   ├── artifacts.py          # attempt directory writer
│   ├── admission.py          # task admission evidence
│   ├── provenance.py         # harness and runtime fingerprint
│   └── paths.py              # external artifact locations
├── reports/                  RENDERERS: import nothing from bench or cli
│   ├── report.py             # one attempt as HTML
│   └── compare_report.py     # side-by-side comparison as HTML
└── cli/                      COMMANDS: may import every layer
    ├── run_scripted_attempt.py
    ├── run_deepseek_attempt.py
    ├── run_failure_recovery.py
    ├── run_langgraph_parity.py
    ├── run_matched_comparison.py
    ├── deepseek_smoke.py
    └── admit.py

tasks/ml_tutor_retrieval/     public/task.md, manifest.json, curator/, environment/Dockerfile
tests/                        unit and Docker integration checks
```

Each folder's `__init__.py` names its layer in its docstring. The root holds only `__init__.py` and the four folders.

## The nine components

| # | Component | File | What it holds | Status |
| --- | --- | --- | --- | --- |
| 01 | While loop | `harness/loop.py`, `harness/graph.py` | Bounded model requests and the explicit Python loop. `graph.py` runs the same loop as a LangGraph. | Implemented |
| 02 | Context management | `harness/context.py` | Message encoding, provider continuation fields, bounded tool output, size measurements | Implemented |
| 03 | Tools registry | `harness/tools.py` | Tool definitions, validation, ordered dispatch, model-visible results | Implemented |
| 04 | Subagents | none | Nothing. It is a known gap, listed here and in AGENTS.md. No file and no placeholder. | Not built |
| 05 | Built-in primitives | `harness/builtins.py` | `read_file`, `search_text`, `apply_patch` and `run_shell`, run inside the task container | Implemented |
| 06 | Session records | `harness/persistence.py` | Ordered trace records, kept in memory. `bench/artifacts.py` writes the saved files. The live tracker's recorder writes `events.jsonl`, the durable JSONL log. | Partial: no checkpoint or resume |
| 07 | System prompt assembly | `harness/prompt.py` | Initial system and task messages, the task repository's `AGENTS.md`, the file map | Implemented |
| 08 | Hooks | `harness/hooks.py`, `harness/tools.py` | The event sink, plus pre and post tool hooks. Repository capture is a post hook. | Implemented |
| 09 | Permissions & safety | `harness/permissions.py` | Container isolation policy and the disposable task container, `DockerTaskContainer` | Implemented |
| | Model adapters | `harness/model.py`, `harness/deepseek.py` | Provider-neutral request and response contract with a scripted adapter; direct DeepSeek adapter with spend budgeting | Implemented |

## Hooks (08)

The event sink (`AttemptEventSink` in `harness/hooks.py`) describes what happened; the recorder decides sequence numbers, storage and durability. Tool hooks run around each call in `execute_tool_turn`:

```python
PreToolHook = Callable[[ToolCall], str | None]                  # a reason blocks the call; None allows it
PostToolHook = Callable[[ToolCall, dict[str, Any], str], None]  # (call, full tool result, operation_id); observes only

@dataclass(frozen=True)
class ToolHooks:
    pre: tuple[PreToolHook, ...] = ()
    post: tuple[PostToolHook, ...] = ()

NO_TOOL_HOOKS = ToolHooks()
def block_tools(names: Iterable[str], reason: str) -> PreToolHook: ...   # e.g. a read-only attempt
```

- Pre hooks run in order after `tool.start`. The first reason blocks the call. The call is not dispatched, and the model sees an error result in the same shape as the invalid-argument results, with `error_category: "blocked_by_hook"`, `retryable: False` and the text `blocked by hook: <reason>`. `tool.outcome` and the trace record follow as for any error, and the attempt continues.
- Post hooks run in order after the `tool.outcome` of a dispatched call, and never for a blocked call. An exception from a hook propagates, so an `EventRecordingError` still stops the attempt.
- Repository capture is a post hook built in `bench/attempt.py`. For the mutating tools in `MUTATING_TOOLS` (defined in `harness/tools.py`), it calls `RepositoryCapture.observe` and emits `tool.capture` under the tool's operation id.
- `attempt_and_evaluate(..., tool_hooks=NO_TOOL_HOOKS)` runs the caller's hooks first and appends the capture hook. The Python loop and the LangGraph run pass the same hooks.

## Layers and the import rule

- `harness/` is the agent. It imports only `harness/`.
- `bench/` runs one attempt on a task and grades it. It imports `bench/`, `harness/` and `reports/`.
- `reports/` renders saved evidence. It imports no `bench/` or `cli/` module.
- `cli/` holds the runnable commands. It may import every layer. Nothing imports `cli/` except `cli/` and tests.

The direction is `cli → bench → (reports, harness)`. The rule covers `TYPE_CHECKING` and function-level imports too. The live tracker (`live-tracker/src/live_tracker`) is outside the package and imports `cli.run_matched_comparison`; that is allowed.

## One request, one tool call, one verdict

1. [`run_scripted_attempt.main`](../agent_eval_harness/cli/run_scripted_attempt.py) loads the admitted task, scripted model, model configuration, budgets, and artifact destination. It calls [`attempt_and_evaluate`](../agent_eval_harness/bench/attempt.py), the public facade used by the other runners too.
2. The facade verifies the artifact destination, records task, provider and budget metadata, and collects provenance ([`bench/provenance.py`](../agent_eval_harness/bench/provenance.py)). It builds the pinned container image and prepares a fresh defect copy ([`bench/environment.py`](../agent_eval_harness/bench/environment.py)). [`_initial_context`](../agent_eval_harness/harness/prompt.py) reads the public task, the task repository's `AGENTS.md`, the repository file map, and the tool descriptions. [`_assistant_message`](../agent_eval_harness/harness/context.py) preserves provider-specific reasoning fields when a response becomes conversation history.
3. For the Python implementation, [`run_python_loop`](../agent_eval_harness/harness/loop.py) alternates model requests and tool turns. [`_request_model_turn`](../agent_eval_harness/harness/loop.py) checks the deadline, model-call and context budgets, applies the provider retry policy, records usage, and preserves the provider response. LangGraph calls the same request and tool functions through its explicit state and conditional edges ([`harness/graph.py`](../agent_eval_harness/harness/graph.py) holds the routing; its node functions are in `bench/attempt.py`).
4. [`execute_tool_turn`](../agent_eval_harness/harness/tools.py) handles calls in response order, runs the pre and post tool hooks, limits the result sent back to the model, and records the complete result for later persistence. [`_dispatch_tool`](../agent_eval_harness/harness/tools.py) validates tool arguments and selects a concrete implementation in [`builtins.py`](../agent_eval_harness/harness/builtins.py). For example, [`apply_patch`](../agent_eval_harness/harness/builtins.py) performs the edit through the disposable task container.
5. When the attempt stops, [`collect_candidate`](../agent_eval_harness/bench/evaluation.py) snapshots the task repository into the candidate patch record. [`evaluate_candidate_changes`](../agent_eval_harness/bench/evaluation.py) applies that patch to a fresh defective copy and calls [`run_canonical_checks`](../agent_eval_harness/bench/environment.py). Candidate code runs in a network-isolated worker with a read-only candidate mount and no evaluator mount. It returns observations; the outer harness loads `curator/checks.py`, evaluates those observations, and [`_finalize_evaluation`](../agent_eval_harness/bench/evaluation.py) maps the canonical checks to a functional verdict. Candidate output cannot select the checks or verdict.
6. [`_collect_artifacts`](../agent_eval_harness/bench/artifacts.py) writes metadata, ordered trace, full tool outputs, patch, checks, result JSON, and the HTML rendered by [`render_attempt_report`](../agent_eval_harness/reports/report.py). The trace it writes is built in memory by [`harness/persistence.py`](../agent_eval_harness/harness/persistence.py). This is trace and result persistence; it does not checkpoint the live conversation for resume.

The evaluator separation has two roles: the candidate worker observes candidate behavior, and curator-owned assertions run in the outer harness. The [container policy](../agent_eval_harness/harness/permissions.py) and the [disposable task container](../agent_eval_harness/harness/permissions.py) make that arrangement inspectable in code and artifacts.

## Python loop and LangGraph

| Concern | Explicit Python loop | LangGraph implementation |
| --- | --- | --- |
| State | Local `messages`, `model_call_count`, response and stop reason inside `attempt_and_evaluate` | [`AttemptGraphState`](../agent_eval_harness/harness/graph.py), with a message-list reducer and per-turn replacement fields |
| Model request | [`run_python_loop`](../agent_eval_harness/harness/loop.py) calls the shared request step | `graph_model_step` in [`bench/attempt.py`](../agent_eval_harness/bench/attempt.py) calls the same `_request_model_turn` |
| Tool execution | The loop calls the shared ordered tool executor | `graph_tool_step` in [`bench/attempt.py`](../agent_eval_harness/bench/attempt.py) calls the same `execute_tool_turn` |
| Routing and stop | The `while` loop repeats until a model, provider, deadline, or budget stop | [`run_attempt_graph`](../agent_eval_harness/harness/graph.py) wires `START`, the model and tool nodes, conditional edges through `route_after_node`, and `END`, with a graph-step cap |
| Evaluation and artifacts | Shared attempt lifecycle after the loop | Same shared attempt lifecycle after graph invocation |

The graph is a second orchestration implementation, not a second tool or evaluation stack. Graph-node limits remain separate from model-call budgets. The harness adds no checkpoint saver or automatic context compaction.

## Reading and checkpoint sequence

1. Read [`model.py`](../agent_eval_harness/harness/model.py) and [`deepseek.py`](../agent_eval_harness/harness/deepseek.py). Check the contract and controlled transport behavior with `python3 -m unittest tests.test_deepseek_provider tests.test_report_cost -v`.
2. Read [`prompt.py`](../agent_eval_harness/harness/prompt.py), [`context.py`](../agent_eval_harness/harness/context.py), [`tools.py`](../agent_eval_harness/harness/tools.py), and [`builtins.py`](../agent_eval_harness/harness/builtins.py). In a scripted attempt trace, find the `initial_context`, `model`, and ordered `tool` events; compare each full result with its bounded model-visible result.
3. Read [`loop.py`](../agent_eval_harness/harness/loop.py) and [`graph.py`](../agent_eval_harness/harness/graph.py). Create `.venv` and install `requirements-langgraph.txt` as shown in the README, then run `.venv/bin/python -m agent_eval_harness.cli.run_langgraph_parity --admission-evidence /path/to/admission.json --source-repository /path/to/prompt-engineering-group-project --output-dir /path/to/parity`; checkpoint the machine-checked stop, candidate, and verdict comparisons in `comparison.json`.
4. Read [`permissions.py`](../agent_eval_harness/harness/permissions.py), [`bench/environment.py`](../agent_eval_harness/bench/environment.py), and `tasks/ml_tutor_retrieval/curator/checks.py`. In the attempt report, inspect the observed container configuration and confirm that check results come from the outer evaluator.
5. Read [`bench/evaluation.py`](../agent_eval_harness/bench/evaluation.py), [`bench/provenance.py`](../agent_eval_harness/bench/provenance.py), [`harness/persistence.py`](../agent_eval_harness/harness/persistence.py), [`bench/artifacts.py`](../agent_eval_harness/bench/artifacts.py), and [`reports/report.py`](../agent_eval_harness/reports/report.py). Inspect one saved result directory from `metadata.json` through `trace.jsonl`, `candidate.patch`, `checks.json`, `result.json`, and `report.html`.
6. Run the fast repository checks with `python3 -m unittest discover -s tests`, and the layout rule alone with `python3 -m unittest tests.test_layout`. Docker integration checks need `AGENT_EVAL_DOCKER_INTEGRATION=1`, `ML_TUTOR_ADMISSION_EVIDENCE`, and `ML_TUTOR_REPOSITORY`; see the corresponding command in the README.

This implementation is larger than a 400-line teaching sketch because the runnable path also includes independently owned acceptance checks, image and container isolation, deadlines and retry/spend accounting, candidate path validation, task and harness provenance, ordered trace/artifact output, and report semantics. The extra code implements behavior that the learning map describes. It adds no subagents and no session resume.

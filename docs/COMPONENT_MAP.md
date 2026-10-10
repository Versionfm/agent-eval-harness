# Component map

This map follows one attempt from its public command through the model, tools, independent checks, and saved report. The layout follows the learning sketch while keeping each module attached to work the harness already performs.

## Annotated tree

```text
agent_eval_harness/
  attempt.py              Public attempt facade, budgets, admitted-task loading,
                          lifecycle, shared evaluation and final accounting
  loop.py                 Explicit Python request/tool transitions and stop rules
  langgraph_attempt.py    Equivalent StateGraph wiring over the same request/tool steps
  prompt.py               Initial system/task messages, repository instructions and file map
  context.py              Message serialization, provider fields, bounded output and context size
  tools.py                Tool registry, ordered dispatch, result classification and visible output
  builtins.py             read_file, search_text, apply_patch and run_shell inside the task container
  permissions.py          Docker isolation flags, effective-configuration parsing and assertions
  environment.py          Image build, repository preparation, container lifecycle and probe execution
  model.py                Provider-neutral request/response/tool contracts and scripted adapter
  deepseek.py             Direct provider transport, parsing, retry classification and spend accounting
  evaluation.py           Candidate snapshot/diff/path checks, staging and evaluator verdict mapping
  admission.py            Task identity evidence and admission assessment
  provenance.py            Harness revision/dirty fingerprint and installed dependency versions
  persistence.py          Ordered trace events and attempt artifact writing
  report.py               Single-attempt HTML report rendering
  run_scripted_attempt.py Existing offline end-to-end demonstration
  run_langgraph_parity.py Deterministic comparison of Python and LangGraph implementations
  compare_report.py       HTML comparison of saved attempts

tasks/ml_tutor_retrieval/
  public/task.md          Model-visible repair request
  manifest.json           Pinned task identity, source, checks and environment
  curator/                Mutation, known repair and evaluator-owned checks
  environment/Dockerfile  Pinned task runtime image recipe

tests/                    Existing unit and Docker integration checks
```

`attempt.py` keeps its historical imports, including `attempt_and_evaluate`, `AdmittedTask`, `AttemptBudgets`, and evaluation helpers used by callers and tests. It owns the attempt lifecycle; it delegates cohesive work to the modules above. The [explicit loop](../agent_eval_harness/loop.py#L227) and [LangGraph](../agent_eval_harness/langgraph_attempt.py#L26) are both readable implementations over the same model-request and tool-execution behavior.

## One request, one tool call, one verdict

1. [`run_scripted_attempt.main`](../agent_eval_harness/run_scripted_attempt.py#L69) loads the admitted task, scripted model, model configuration, budgets, and artifact destination. It calls [`attempt_and_evaluate`](../agent_eval_harness/attempt.py#L286), the public facade used by the other runners too.
2. The facade verifies the artifact destination, records task/provider/budget metadata and provenance, builds the pinned container image, and prepares a fresh defect copy. [`_initial_context`](../agent_eval_harness/prompt.py#L12) reads the public task, task-repository `AGENTS.md`, repository file map, and tool descriptions. [`_assistant_message`](../agent_eval_harness/context.py#L38) preserves provider-specific reasoning fields when a response becomes conversation history.
3. For the Python implementation, [`run_python_loop`](../agent_eval_harness/loop.py#L227) alternates model requests and tool turns. [`_request_model_turn`](../agent_eval_harness/loop.py#L48) checks deadline, model-call and context budgets, applies the provider retry policy, records usage, and preserves the provider response. LangGraph calls the same request and tool functions through its explicit state and conditional edges.
4. [`execute_tool_turn`](../agent_eval_harness/tools.py#L67) handles calls in response order, limits the result sent back to the model, and records the complete result for later persistence. [`_dispatch_tool`](../agent_eval_harness/tools.py#L24) validates tool arguments and selects a concrete implementation in `builtins.py`; for example, [`apply_patch`](../agent_eval_harness/builtins.py#L85) performs the edit through the disposable task container.
5. When the attempt stops, [`collect_candidate`](../agent_eval_harness/evaluation.py#L196) snapshots the task repository into the candidate patch record. [`evaluate_candidate_changes`](../agent_eval_harness/evaluation.py#L158) applies that patch to a fresh defective copy and calls [`run_canonical_checks`](../agent_eval_harness/environment.py#L334). Candidate code runs in a network-isolated worker with a read-only candidate mount and no evaluator mount. It returns observations; the outer harness loads `curator/checks.py`, evaluates those observations, and [`_finalize_evaluation`](../agent_eval_harness/evaluation.py#L123) maps the canonical checks to a functional verdict. Candidate output cannot select the checks or verdict.
6. [`_collect_artifacts`](../agent_eval_harness/persistence.py#L24) writes metadata, ordered trace, full tool outputs, patch, checks, result JSON, and the HTML rendered by [`render_attempt_report`](../agent_eval_harness/report.py#L75). This is trace and result persistence; it does not checkpoint the live conversation for resume.

The evaluator separation has two roles: the candidate worker observes candidate behavior, and curator-owned assertions run in the outer harness. The [container policy](../agent_eval_harness/permissions.py#L14) and [Docker lifecycle](../agent_eval_harness/environment.py#L244) make that arrangement inspectable in code and artifacts.

## Python loop and LangGraph

| Concern | Explicit Python loop | LangGraph implementation |
| --- | --- | --- |
| State | Local `messages`, `model_call_count`, response and stop reason inside `attempt_and_evaluate` | [`AttemptGraphState`](../agent_eval_harness/langgraph_attempt.py#L13), with a message-list reducer and per-turn replacement fields |
| Model request | [`run_python_loop`](../agent_eval_harness/loop.py#L227) calls the shared request step | `graph_model_step` in [`attempt.py`](../agent_eval_harness/attempt.py#L421) calls the same `_request_model_turn` |
| Tool execution | The loop calls the shared ordered tool executor | `graph_tool_step` in [`attempt.py`](../agent_eval_harness/attempt.py#L442) calls the same `_execute_tool_turn` |
| Routing and stop | The `while` loop repeats until a model, provider, deadline, or budget stop | [`run_attempt_graph`](../agent_eval_harness/langgraph_attempt.py#L26) wires `START`, model/tool nodes, conditional edges, and `END` with a graph-step cap |
| Evaluation and artifacts | Shared attempt lifecycle after the loop | Same shared attempt lifecycle after graph invocation |

The graph is a second orchestration implementation, not a second tool or evaluation stack. Graph-node limits remain separate from model-call budgets. The harness adds no checkpoint saver or automatic context compaction.

## Screenshot item mapping

| Sketch item | Status | Current location |
| --- | --- | --- |
| `loop.py` | Implemented | `loop.py` owns the explicit Python transitions and shared request budget/retry policy. |
| `context.py` | Implemented | `context.py` serializes messages, preserves provider fields, and measures/bounds model-visible context. |
| `tools.py` | Implemented | `tools.py` owns tool definitions, dispatch, ordering, error categories and bounded results. |
| `subagents.py` | Planned | No subagent execution exists in this task. |
| `builtins.py` | Implemented | `builtins.py` contains the four concrete repository tools, run through `DockerTaskContainer`. |
| `persistence.py` | Partial | Attempt trace and artifacts are written; session checkpoint/resume is planned. |
| `prompt.py` | Implemented | `prompt.py` builds the initial instructions and file map. |
| `hooks.py` | Planned | No hook lifecycle exists in this task. |
| `permissions.py` | Implemented | `permissions.py` holds the container isolation policy and the validation used by `environment.py`. |
| `model.py` | Implemented | `model.py` defines the shared contract; `deepseek.py` is the concrete direct-provider adapter. |
| `demo/tests` | Implemented through existing files | `run_scripted_attempt.py` is the end-to-end demo, the ML Tutor task package is its disposable example, and `tests/` contains the checks. There is no duplicate `demo/` implementation. |

## Reading and checkpoint sequence

1. Read [`model.py`](../agent_eval_harness/model.py) and [`deepseek.py`](../agent_eval_harness/deepseek.py). Check the contract and controlled transport behavior with `python3 -m unittest tests.test_deepseek_provider tests.test_report_cost -v`.
2. Read [`prompt.py`](../agent_eval_harness/prompt.py), [`context.py`](../agent_eval_harness/context.py), [`tools.py`](../agent_eval_harness/tools.py), and [`builtins.py`](../agent_eval_harness/builtins.py). In a scripted attempt trace, find the `initial_context`, `model`, and ordered `tool` events; compare each full result with its bounded model-visible result.
3. Read [`loop.py`](../agent_eval_harness/loop.py) and [`langgraph_attempt.py`](../agent_eval_harness/langgraph_attempt.py). Create `.venv` and install `requirements-langgraph.txt` as shown in the README, then run `.venv/bin/python -m agent_eval_harness.run_langgraph_parity --admission-evidence /path/to/admission.json --source-repository /path/to/prompt-engineering-group-project --output-dir /path/to/parity`; checkpoint the machine-checked stop, candidate, and verdict comparisons in `comparison.json`.
4. Read [`permissions.py`](../agent_eval_harness/permissions.py), [`environment.py`](../agent_eval_harness/environment.py), and `tasks/ml_tutor_retrieval/curator/checks.py`. In the attempt report, inspect the observed container configuration and confirm that check results come from the outer evaluator.
5. Read [`evaluation.py`](../agent_eval_harness/evaluation.py), [`provenance.py`](../agent_eval_harness/provenance.py), [`persistence.py`](../agent_eval_harness/persistence.py), and [`report.py`](../agent_eval_harness/report.py). Inspect one saved result directory from `metadata.json` through `trace.jsonl`, `candidate.patch`, `checks.json`, `result.json`, and `report.html`.
6. Run the fast repository checks with `python3 -m unittest discover -s tests`. Docker integration checks need `AGENT_EVAL_DOCKER_INTEGRATION=1`, `ML_TUTOR_ADMISSION_EVIDENCE`, and `ML_TUTOR_REPOSITORY`; see the corresponding command in the README.

This implementation is larger than a 400-line teaching sketch because the runnable path also includes independently owned acceptance checks, image and container isolation, deadlines and retry/spend accounting, candidate path validation, task and harness provenance, ordered trace/artifact output, and report semantics. The extra code implements behavior that the learning map describes; it does not add hooks, subagents, or session resume.

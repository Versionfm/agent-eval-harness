# Workbench walkthrough

This walks the Python call chain that the workbench observes, what each event records, and the selected-point experiment. Reproduce the observed attempt first (requires Docker and the admitted task environment):

```bash
PYTHONPATH=live-tracker/src python -m live_tracker.run_scripted --scenario workbench \
  --admission-evidence <admission.json> --source-repository /path/to/prompt-engineering-group-project
# prints "viewer: http://127.0.0.1:8765/"
```

## Call chain

Every step below is a real function. The sink publishes the event before the step runs (starts) or before the attempt advances (outcomes).

1. `agent_eval_harness.attempt:attempt_and_evaluate` emits `attempt_started` and `initial_context`, then hands control to the loop.
2. `agent_eval_harness.loop:run_python_loop` runs one loop step per model turn:
   - `phase.enter` (`phase: model_request`, `source: agent_eval_harness.loop:_request_model_turn`)
   - `agent_eval_harness.loop:_request_model_turn` checks the deadline, model-call and context budgets, then calls the provider. It emits `model.start` (`model-N`, with the full request as `request.json`) before the call and `model.outcome` (`model-N`, with the response as `response.json`) after it.
   - `state` (`after_phase: model_request`) snapshots budgets, context size, call counts, usage and cost after the response is recorded.
   - `phase.enter` (`phase: tool_execution`, `source: agent_eval_harness.tools:execute_tool_turn`), only when the model asked for tools.
   - `agent_eval_harness.tools:execute_tool_turn` emits `tool.start` (`tool-N-I`, parent `model-N`) before each dispatch and `tool.outcome` after it. The model-visible output and the full output (`output.txt`) are recorded separately.
   - `state` (`after_phase: tool_execution`) after the tool results are in the conversation.
3. The loop stops on a stop reason. `attempt_finished` carries the termination, checks and verdict.

The live tracker never reads the harness's in-memory trace. It reads only `events.jsonl` and linked artifacts. The inspector shows what a provider exposes as `reasoning_content`, labelled as such; it does not show any other internal reasoning.

## Events added in #13

| type | data | notes |
|---|---|---|
| `phase.enter` | `phase`, `loop_step`, `source` (module:function) | `source` must be a registered identity (`GET /api/sources?identity=`) |
| `state` | `model_calls`, `max_model_calls`, `context_bytes`, `max_context_bytes`, `tool_result_messages`, `tool_output_limit_bytes`, `attempt_deadline_seconds`, `usage_totals`, `estimated_cost`, `reported_cost`, `loop_step`, `after_phase` | computed from history only; no observer data enters `messages` |

Missing data is labelled, never invented: an absent `usage.prompt_tokens` appears as `not recorded`, and cost stays `unavailable` unless the provider adapter reported it.

## Selected-point versus final state

The workbench shows, for any selected event, the newest `state` event at or before that sequence. Later events never contribute. The experiment below comes from a real Docker run of the `workbench` scenario (`live-tracker/experiments/selected_point.py`, which asserts that the first tool selection does not already know the later context or call counts):

```bash
PYTHONPATH=live-tracker/src python live-tracker/experiments/selected_point.py <attempt-directory>
```

| selected | event | model calls | context bytes | tool result messages | state from |
|---:|---|---:|---:|---:|---|
| #5 | model.outcome model-1 | None / None | None | None | none |
| #9 | tool.outcome tool-1-1 | 1 / 4 | 8002 | 0 | #6 |
| #13 | model.outcome model-2 | 1 / 4 | 24605 | 1 | #10 |
| #17 | tool.outcome tool-2-1 | 2 / 4 | 24955 | 1 | #14 |
| #19 | tool.outcome tool-2-2 | 2 / 4 | 24955 | 1 | #14 |
| #23 | model.outcome model-3 | 2 / 4 | 28357 | 3 | #20 |
| #25 | attempt_finished (final state, #24) | 3 / 4 | 28494 | 3 | #24 |

Reading the table: selecting `model-1`'s outcome shows no state, because no state event has been recorded yet. Selecting `tool-1-1` shows one completed model call and 8002 context bytes, not the 28494 bytes the attempt finishes with. Final totals and checks belong to `attempt_finished`.

## Components and source navigation

The component map (left pane) lists the registered components. Selecting one shows its responsibility, its registered source function (file and line range) and the function's text. Phase and graph-node events link to the same registered record. Only identities in `live_tracker.sources.REGISTERED_SOURCES` resolve; the server never serves an arbitrary path.

## LangGraph source walkthrough (#15)

The LangGraph orchestrator runs the same model and tool functions as the Python loop. What differs is who decides the next step: the graph's edges instead of a `while` loop.

| Concern | Python loop (`loop.py`) | LangGraph (`langgraph_attempt.py`) |
|---|---|---|
| Control flow | `run_python_loop`: `while`, one `phase.enter` per phase | `StateGraph` with nodes `model_request` and `tool_execution` and conditional edges |
| Model turn | `_request_model_turn` (budgets, retries, `model.start`/`model.outcome`) | same function, called from the `model_request` node (`graph_model_step` in `attempt.py`) |
| Tool turn | `execute_tool_turn` (`tool.start`/`tool.outcome`) | same function, called from the `tool_execution` node (`graph_tool_step` in `attempt.py`) |
| Step counting | none; the model-call budget is the only bound | `counted` wraps each node: `graph_step_count` +1 per node run; separate cap `graph_step_limit` (`max_graph_steps` or `2 * max_model_calls + 1`) |
| Routing | `run_python_loop` checks the stop reason and `response.tool_calls` | `route_after_node`: stop reason, then no model response or no tool calls, then the graph-step cap, else the other node |
| Snapshot | `state` after each phase (`_selected_point_state`) | `state` after each node, with the same function and `after_node`, `graph_step_count` |

Graph state (`AttemptGraphState`): `messages` uses the `operator.add` reducer, so each node returns only the messages it appended and the reducer concatenates them in order; `model_response`, `model_call_count`, `graph_step_count` and `termination_reason` are replaced by each node's update. Observer data never enters `messages`.

Recorded events for one graph step (for example graph step 2, a tool node):

1. `node.enter` (`operation_id: graph-step-2`, `node: tool_execution`, `graph_step_count: 2`, `source`). Recorded before the node runs, so a failed write stops the node.
2. `tool.start` / `tool.outcome` (`tool-N-I`, parent `model-N`), exactly as in the Python loop.
3. `node.outcome` (same operation id, with `termination_reason` when the node set one). A node that raised has no outcome; the workbench shows it as `unresolved` after the attempt finishes, never as completed.
4. `state` (`after_node: tool_execution`, `graph_step_count`), built from the merged messages.
5. `route.decision` (`after_node`, `next`, `reason`, `graph_step_count`, `max_graph_steps`, `source`). `next` is `end` when the graph stops; `reason` is `tool_calls`, `tool_results`, `no_tool_calls`, `no_model_response`, `graph_step_budget`, or the stop reason (for example `agent_completed`, `spending_budget`).

Graph steps and model calls differ. The four-response repair script runs seven graph steps (four model nodes and three tool nodes) and four model calls. The model-call budget and the graph-step cap are separate budgets, and `graph_step_budget` appears only when the graph cap stops the run.

Registered sources: `route_after_node`, plus the shared `_request_model_turn` and `execute_tool_turn` that the two node components point at.

## No-provider experiment and overhead

```bash
# LangGraph attempt, scripted model: the same workbench scenario as the Python loop.
PYTHONPATH=live-tracker/src python -m live_tracker.run_scripted --orchestrator langgraph --scenario workbench \
  --admission-evidence <admission.json> --source-repository /path/to/prompt-engineering-group-project

# Observed versus unobserved wall time per orchestrator (no provider; alternating order).
PYTHONPATH=.:live-tracker/src python live-tracker/experiments/observation_overhead.py \
  --admission-evidence <admission.json> --source-repository /path/to/prompt-engineering-group-project --repeats 3
```

## Known limits

- Provider reasoning is shown only as the `reasoning_content` field the provider returned.
- The timeline shows state and phase events in the same sequence as the harness's calls. The LangGraph orchestrator is observed through node and router events (#15); the two orchestrators differ in those events, not in the model/tool events.
- The inspector shows a bounded presentation excerpt (2000 characters) of long output, labelled as an excerpt; the complete output is the linked artifact.

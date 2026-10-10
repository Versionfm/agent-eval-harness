# Coding-agent harness and evaluation design

Status: active implementation design. Tickets #2–#4 admitted the ML Tutor task, ran the explicit loop, and preserved partial attempts; ticket #6 adds a deterministic LangGraph parity experiment on 2026-10-10. The matched live-provider comparison remains a separate checkpoint. Interview decisions are recorded in [design-interview.md](design-interview.md).

## Purpose and first milestone

Learn how a coding-agent harness works, how LangGraph expresses the same workflow, and how to evaluate attempts independently. Produce reproducible evidence for a portfolio and research project.

The first milestone exercises the complete path on one meaningful retrieval repair task from `Versionfm/prompt-engineering-group-project`: prepare task, execute agent, capture activity, collect patch, evaluate independently, and render a clean report. An unsuccessful agent attempt is still a valid result if the measurement is trustworthy.

Read-only source inspection pinned candidate revision `6890d9eae6ebd2967553eaf5a0c5753c26322182`. The proposed task is a lost-title-evidence regression in `app/source.py::retrieve`, checked both at retrieval output and at `app/tutor.py::answer` context construction. The public symptom is that a section relevant by title is skipped even though unrelated sections are returned. Curator-only defect and known-repair details stay outside the task container.

Independent synthetic cases cover title-only relevance, reordered irrelevant sections, body relevance, case normalization, top-k limits, source input immutability, and full-context bypass. Retain existing history/mode behavior checks. Do not add unrelated empty-corpus behavior to this task. Ticket #2 admitted the task: the pinned baseline and known repair passed all nine checks, while the introduced title-text defect failed title retrieval, tutor-context construction, and input-order independence. Detailed machine-readable and HTML evidence is generated outside the repository by the admission command.

## Components and ownership

| Component | Responsibility |
| --- | --- |
| Task preparation | Pin repository revision and environment; define the defect, public task description, independent checks, and known repair. |
| Model adapter | Call the configured provider, preserve provider-specific conversation fields, normalize responses and usage, and log bounded retries. |
| Repository tools | Read files, search text, apply patches, and execute shell commands inside the task container. |
| Context builder | Construct initial messages and retain tool history within a measured context budget. |
| Agent orchestrator | Choose the next model/tool step, update state, enforce limits, and record why execution ends. |
| Trace recorder | Persist ordered events and artifact references independently of agent-writable files. |
| Evaluator | Apply the candidate patch to a fresh defective baseline and run canonical checks and selected regression tests. |
| Report renderer | Present verdict, activity, diff, resource use, and separate qualitative review. |

Shared interfaces remain small: a model response contains content, available reasoning fields, tool requests, usage, and provider identity; a tool result contains output/artifact references, status, timing, and errors; an attempt result contains termination reason, patch, trace, and metadata. The public attempt boundary is `attempt_and_evaluate`, with `AdmittedTask`, `ModelConfig`, `AttemptBudgets`, and an artifact destination as inputs. Ticket #3 implements its explicit `python-loop` route with a scripted model adapter.

The task container has full read/write access to its repository, prepared dependencies, and no network. It receives neither model credentials nor evaluator checks. Shell commands start at the repository root. The outer harness handles model requests and owns traces. No host filesystem or container-engine socket is mounted into the task container.

Docker 29.1.3 and the digest-pinned Python 3.12.13 image were verified during ticket #2. The environment built with Docker networking disabled; separate baseline, defect, and repair candidate workers ran with networking disabled and a read-only task-repository mount. Candidate code never receives the evaluator directory or check IDs: the outer harness evaluates worker observations against evaluator-owned assertions after the worker exits. Each variant produces canonical check evidence. The admission run does not represent a coding-agent attempt or a live-model call.

Ticket #3 archives the full pinned source repository, applies the admitted defect outside agent control, and gives a writable copy to a disposable container. Its model/tool loop and ordered history live in `agent_eval_harness/attempt.py`; provider contracts and the scripted adapter live in `model.py`; task and evaluator containers live in `environment.py`. The task container is inspected to confirm it has only the writable repository mount. The evaluator applies the complete collected file changes to a separate fresh defective copy. The runnable checkpoint is `python -m agent_eval_harness.run_scripted_attempt` and its report is stored outside the Git repository.

Ticket #4 extends the same high-level `attempt_and_evaluate` path. Configurable limits cover model requests, serialized context bytes, command time, the attempt deadline, bounded provider retries, cleanup, and canonical evaluation. Values are recorded as proposals until calibrated; the retry count includes failed requests, and retry delay contributes to elapsed time. The attempt deadline is enforced across environment setup, blocking model calls, repository tools, and container cleanup. It reserves a configured cleanup window. Canonical evaluation has a separate timeout after agent execution stops so a working partial patch can still receive a verdict. A timed-out Docker command force-removes its exact task container before the timeout returns; a subsequent tool starts a clean container on the same working repository, preventing late descendants from mutating it. A model request carries the current remaining time for future provider adapters; the generic synchronous wrapper bounds harness waiting, while an adapter with an HTTP transport should also apply that timeout to its request.

Ticket #6 adds `orchestrator="langgraph"` beside the default `python-loop` at this same public seam. Both routes call the same model-turn helper and ordered tool-execution helper, then share task-container setup, context construction, tracing, patch collection, independent evaluation, and report artifacts. The LangGraph-only module defines `AttemptGraphState`, including an additive message reducer; wraps the shared functions as `model_request` and `tool_execution` nodes; and routes through conditional edges to the next node or `END`. `START` enters the model node. The compiled graph is invoked without a checkpointer or a prebuilt agent factory. The explicit Python loop owns those same transitions with a `while` branch. `graph_step_count` measures graph nodes, while `model_call_count` measures requests; these are not interchangeable. With no explicit graph-only cap, the node limit is `2 * max_model_calls + 1` and the LangGraph recursion limit is one greater, enough for one model and one tool node per permitted request plus the final model node that observes the shared request cap. If a graph-only cap is configured for a demonstration, its source and effective limit are recorded in metadata and the trace.

Tool failures return status, output, error category, retryability, and exit status to the model. Requests in one response run sequentially in their declared order. The model sees bounded output with an explicit truncation marker; the full output is written to a separate attempt artifact and referenced from the trace. An interruption, provider failure, deadline, or budget stop still closes the task container, snapshots available files (including additions), and evaluates the patch. If collection is impossible, the candidate status explicitly says `unavailable`. Patch collection/application errors, canonical check failures, and environment failures have separate categories, while termination remains independent from functional verdict.

## Comparable orchestration

Both implementations will use identical tasks, prompts, adapter, tools, context policy, budgets, and evaluator. The initial graph will execute the same sequence of model calls and ordered tool calls as the explicit loop.

| Explicit Python | LangGraph counterpart | What to inspect |
| --- | --- | --- |
| `messages`, current response, request count, node count, termination | `AttemptGraphState` with an additive reducer for message updates | State meaning remains harness-defined; messages append while per-turn values replace prior ones. |
| `_request_model_turn(...)` | `model_request` node | It invokes the same configured adapter and preserves provider reasoning fields; LangGraph does not choose our model or prompt. |
| `_execute_tool_turn(...)` | `tool_execution` node | It dispatches repository tools sequentially, bounds visible output, and records identical trace events. |
| `while` stop/continue checks | Conditional edges after each node | A response with tools routes to tool execution; completed, stopped, or budget-limited state routes to `END`. |
| Enter the loop and exit it | `START`, `END`, and `StateGraph.compile()/invoke()` | LangGraph supplies graph execution; the harness still defines work, budgets, trace, and outcomes. |

Use explicit nodes first rather than a prebuilt agent factory. Demonstrate checkpoint persistence and resume later, after orchestration parity, so their effects can be measured separately. Local traces are retained in both implementations; LangGraph checkpoints are a distinct concept from trace recording and model prompt caching.

LangGraph is pinned at `1.2.14` in `requirements-langgraph.txt`; the complete resolved dependency set is pinned there for repeatable installation. The runnable comparison is `python -m agent_eval_harness.run_langgraph_parity`; it writes paired attempt artifacts and `comparison.json` outside the repository. References checked on 2026-10-10: [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence), and [LangGraph on PyPI](https://pypi.org/project/langgraph/).

## Initial model and context

Direct DeepSeek API, model `deepseek-flash` (currently DeepSeek-V4.1-Flash), thinking enabled at low effort. Record requested identifier, observed model identifier, endpoint, settings, and run date. Do not claim an immutable model snapshot unless the provider supports one.

Preserve exposed provider reasoning fields required for subsequent tool calls; do not flatten them away in the adapter or LangGraph state. A deterministic fixture conversation tests this round trip before live execution. See [DeepSeek thinking/tool-call requirements](https://api-docs.deepseek.com/guides/thinking_mode/).

Initial context consists of the public task description, repository instructions, a short file map, and tool definitions. The agent discovers relevant source using tools. Keep shared prefixes stable when practical. Begin without automatic compaction; reaching the context budget ends the attempt explicitly and retains its artifacts.

Proposed calibration defaults: 30 model calls, 10 minutes per attempt, 60 seconds per shell command, and 8,192 output tokens per response. Limit tool results presented to the model to 16 KiB each, with a truncation marker and full output retained as an artifact. Determine the conservative context threshold and cost ceiling during the smoke-run setup; record effective settings for both implementations. Retries count against elapsed time and request accounting. Calibrate these values before benchmark claims.

## Task validity and scoring

Pin the repository SHA, task definition, dependency environment, defect patch, known repair, and acceptance-check version. Use small synthetic inputs and fake tutor model responses; the coding agent's DeepSeek request is the only intended live model call.

Before admitting a task, demonstrate:

1. Clean source passes baseline and canonical behavior checks.
2. The introduced defect fails the intended behavior check.
3. The known repair restores it and preserves neighboring behavior.

The public task describes symptoms and desired behavior, not the defect patch or answer. Keep solution artifacts and canonical checks outside agent access. Existing task tests remain editable. Collect the final patch including new files; apply only repository changes to a fresh defective baseline, without importing container state or agent-modified dependencies into evaluation.

Functional verdicts distinguish success, repair failure, and invalid evaluation/environment. Canonical check failures and candidate import, syntax, runtime, or probe-timeout errors are repair failures; candidate execution errors produce false canonical checks with retained error evidence. The `invalid_patch` failure category means changes could not be safely collected or applied to the fresh defective baseline; the candidate may be marked `unavailable`, and no assertion that canonical checks failed is implied. Docker/evaluator startup or assertion-runner failures are `invalid_environment`, not repair failures. Execution termination independently distinguishes agent completion, budget stop, provider error, and harness error. Agent completion is not a successful repair verdict.

Codex qualitative review is a separate recorded activity, based on task, observable trace, diff, and test evidence. Review diagnosis, tool use, patch quality, and failure explanation. Initial reports may show review as pending until this chat supplies it; no automatic judge or recurring reviewer is implied.

Use scripted model responses to test equivalent tool sequencing, state transitions, and termination in both orchestrators. Live attempts can diverge because model generation is stochastic; report that rather than demanding identical patches.

## Artifacts and HTML report

Each attempt produces metadata, JSONL trace, candidate patch, check results, and local HTML. Admission evidence binds task identity, source revision, check IDs, and every task-package file fingerprint; changing task content requires new admission. Attempt metadata records installed dependency versions and the harness commit plus dirty working-tree fingerprint. `python -m agent_eval_harness.compare_report` consumes two recorded attempt directories and writes a side-by-side HTML report without invoking a model, rerunning a task, or evaluating a candidate. It flags missing or mismatched task, source, task-image Dockerfile/runtime basis, provider/model, settings, dependency versions, harness revision, budgets, and pricing-source metadata. Mutable image tags and recorded image IDs are shown separately for audit. It compares token/cache use and model/tool latency separately from charges and estimates, because cache warmth and pricing periods can change money figures. Keep generated artifacts ignored by Git by default. Never include credentials or authorization headers in traces.

The report leads with task, implementation, functional verdict, termination reason, duration, and cost. Use a readable responsive layout with clear typography, restrained colors, and expandable long payloads; initial and model-visible request context are collapsed by default. Show an event timeline with links to exposed reasoning, model-visible and full tool outputs, unified diff, and canonical check results. Escape untrusted trace content and show whether outputs were truncated.

Record input/output tokens, cached/uncached input when exposed, reasoning usage when exposed, model and tool duration, retries, and pricing timestamp. Distinguish reported charges from estimates and unavailable metrics. Compare token/latency behavior separately from cost because cache warmth and peak pricing can differ between runs. Qualitative review is a separate, attempt-bound record validated against task, orchestrator, source revision, and start time. No record means pending; the renderer cannot synthesize a review or alter executable results. See [the review record contract](REVIEW_RECORD.md).

## Extension path

After the first measured attempt and parity demonstration, introduce one harness change at a time: context compaction, recovery policies, checkpoints/resume, or task-specific context selection. Then expand to multiple tasks, repeated attempts, more hosted models, a locally validated model, and a second repository. These use the same task/attempt/evaluator boundaries rather than a separate demonstration pathway.

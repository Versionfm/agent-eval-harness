# Coding-agent harness and evaluation design

Status: active implementation design. Ticket #2 admitted the ML Tutor task and ticket #3 ran its first scripted repair on 2026-10-10; remaining slices retain their learning checkpoints. Interview decisions are recorded in [design-interview.md](design-interview.md).

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

Docker 29.1.3 and the digest-pinned Python 3.12.13 image were verified during ticket #2. The environment built with Docker networking disabled; separate baseline, defect, and repair containers ran with networking disabled, read-only task/evaluator mounts, and no mounted credentials or container socket. Each variant produced canonical check evidence. The ticket #2 admission run did not represent a coding-agent attempt or a live-model call.

Ticket #3 archives the full pinned source repository, applies the admitted defect outside agent control, and gives a writable copy to a disposable container. Its model/tool loop and ordered history live in `agent_eval_harness/attempt.py`; provider contracts and the scripted adapter live in `model.py`; task and evaluator containers live in `environment.py`. The task container is inspected to confirm it has only the writable repository mount. The evaluator applies the complete collected file changes to a separate fresh defective copy. The runnable checkpoint is `python -m agent_eval_harness.run_scripted_attempt` and its report is stored outside the Git repository.

## Comparable orchestration

Both implementations will use identical tasks, prompts, adapter, tools, context policy, budgets, and evaluator. The initial graph will execute the same sequence of model calls and ordered tool calls as the explicit loop.

| Explicit Python | LangGraph counterpart | What to inspect |
| --- | --- | --- |
| Attempt state object | State schema | Which information survives each step. |
| Call-model function | Model node | A node runs our function; it does not choose a model or prompt for us. |
| Tool dispatch function | Tool-execution node | How tool requests become actions and structured results. |
| Branch in the loop | Conditional edge | How the next node is selected. |
| Updating messages and counters | State updates and reducers | Whether updates replace or accumulate existing values. |
| Starting/stopping the loop | START/END and compiled graph | How the workflow is entered and terminated. |

Use explicit nodes first rather than a prebuilt agent factory. Demonstrate checkpoint persistence and resume later, after orchestration parity, so their effects can be measured separately. Local traces are retained in both implementations; LangGraph checkpoints are a distinct concept from trace recording and model prompt caching.

References checked on 2026-10-10: [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence).

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

Functional verdicts distinguish success, failing checks, and invalid evaluation/environment failure. Execution termination independently distinguishes agent completion, budget stop, provider error, and harness error. Agent completion is not a successful repair verdict.

Codex qualitative review is a separate recorded activity, based on task, observable trace, diff, and test evidence. Review diagnosis, tool use, patch quality, and failure explanation. Initial reports may show review as pending until this chat supplies it; no automatic judge or recurring reviewer is implied.

Use scripted model responses to test equivalent tool sequencing, state transitions, and termination in both orchestrators. Live attempts can diverge because model generation is stochastic; report that rather than demanding identical patches.

## Artifacts and HTML report

Each attempt produces metadata, JSONL trace, candidate patch, check results, and local HTML. Keep generated artifacts ignored by Git by default. Never include credentials or authorization headers in traces.

The report leads with task, implementation, functional verdict, termination reason, duration, and cost. Use a readable single-column layout with a comparison view, clear typography, restrained colors, and expandable long payloads. Show an event timeline, exposed reasoning, commands/results, unified diff, acceptance results, and separate qualitative review. Escape untrusted trace content and show whether outputs were truncated.

Record input/output tokens, cached/uncached input when exposed, reasoning usage when exposed, model and tool duration, retries, and pricing timestamp. Distinguish reported charges from estimates and unavailable metrics. Compare token/latency behavior separately from cost because cache warmth and peak pricing can differ between runs.

## Extension path

After the first measured attempt and parity demonstration, introduce one harness change at a time: context compaction, recovery policies, checkpoints/resume, or task-specific context selection. Then expand to multiple tasks, repeated attempts, more hosted models, a locally validated model, and a second repository. These use the same task/attempt/evaluator boundaries rather than a separate demonstration pathway.

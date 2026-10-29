# Agent Eval Harness

This repository is a learning project for coding-agent harness engineering and independent evaluation. The harness admits a reproducible ML Tutor retrieval task and runs coding-agent repairs through disposable environments and independent evaluation. Both explicit Python and LangGraph implementations have completed a matched live DeepSeek pair; see the [live findings and reproduction guide](docs/MATCHED_RUN.md).

The task pins `Versionfm/prompt-engineering-group-project` at `6890d9eae6ebd2967553eaf5a0c5753c26322182`. Its public description is separate from the curator-owned defect, known repair, and canonical checks. The checks use synthetic sections and an injected fake tutor response.

The admission runner creates three disposable source copies, builds a digest-pinned Python 3.12.13 environment without network access, and probes each variant in a separate container. A probe worker has no network, one read-only task mount, and no curator evaluator, credentials, or container socket. It returns observations; the outer harness loads the curator checks and decides each result. The runner produces machine-readable evidence and a small HTML summary. Setup and evaluator errors are reported as `invalid_environment`; behavior mismatches are `rejected`.

## Requirements

- Python 3.12. The core package uses only the standard library.
- LangGraph for the LangGraph orchestrator and its tests: `pip install -r requirements-langgraph.txt`.
- Docker, with the digest-pinned base image from `tasks/ml_tutor_retrieval/environment/Dockerfile` cached locally, for admission, attempts and every `*_docker` test.
- A local checkout of `Versionfm/prompt-engineering-group-project` at the pinned commit. That repository is private, so ask for access. Commands take `--source-repository`; otherwise the default is `ML_TUTOR_REPOSITORY`, then `../prompt-engineering-group-project` next to this repository.
- A DeepSeek API key in a private text file, only for the live provider runs.
- For the live-tracker browser tests: `pip install playwright` and a system Chrome. Node is needed only to rebuild `live-tracker/web/dist/`, which is committed.

The fast offline tests need none of the optional pieces except LangGraph: `python3 -m unittest discover -s tests`.

## Layout

The package has four layers. `harness/` is the agent: the numbered components and the model adapters. `bench/` runs the agent on a task and grades it. `reports/` renders saved evidence. `cli/` holds the runnable commands. The rule is in [AGENTS.md](AGENTS.md), and `python3 -m unittest tests.test_layout` checks it. The [component map](docs/COMPONENT_MAP.md) lists each file with its component number and status.

## Run the admission experiment

Provide a local ML Tutor checkout containing the pinned commit:

```bash
python3 -m agent_eval_harness.cli.admit \
  --source-repository /path/to/prompt-engineering-group-project
```

The command needs a local Docker daemon and a cached copy of the pinned base image. It does not fetch the repository or install dependencies. By default, it writes `admission.json`, `summary.html`, and the prepared baseline/defect/repair copies to `../../orchestration/evidence/issue-2/`, outside the Git repository.

Run the fast admission-outcome tests with:

```bash
python3 -m unittest discover -s tests
```

To run the full Docker admission integration test as well, set `AGENT_EVAL_DOCKER_INTEGRATION=1` and `ML_TUTOR_REPOSITORY` to the local checkout path.

The retrieval call chain is `app.tutor.answer` → `app.source.retrieve` → `_terms(title + text)` and BM25 ranking. In top-k mode, `answer` formats those selected sections into the system context passed to the injected chat callable. The checks observe both the retrieval result and that tutor context, then verify neighboring behavior.

## Run the scripted repair attempt

The explicit Python loop now drives a complete attempt with a scripted model adapter. It reads and searches the full pinned repository, edits the retrieval code, adds a regression test, runs the focused repository tests in a writable task container, captures the complete candidate patch, and evaluates it in a new container. No hosted model request is made.

Run it with the locally admitted task evidence and pinned ML Tutor checkout:

```bash
python3 -m agent_eval_harness.cli.run_scripted_attempt \
  --admission-evidence /path/to/issue-2/admission.json \
  --source-repository /path/to/prompt-engineering-group-project \
  --output-dir /path/to/scripted-attempt
```

The command rebuilds the task image from the manifest's digest-pinned Dockerfile with Docker networking disabled, probes Python 3.12.13, and then uses the resolved image ID. The agent container has one writable mount at `/task`, no network, no evaluator mount, and no credentials or Docker socket. After collecting the patch, the harness stages it on a fresh defective copy and starts a read-only candidate worker to gather observations. The worker does not receive curator checks; the outer harness loads those checks and maps the observations to the canonical verdict.

The explicit `while` loop in `harness/loop.py` advances shared model-request and ordered tool-execution steps. Conversation messages carry through the attempt, provider retries and time limits are enforced for each request, and the next request receives the time remaining before the attempt deadline. Tool errors return to the model as structured results. Tool output sent to the model is bounded and marked when truncated; the full output remains in `tool-results/` and the trace. Numeric limits are configurable calibration proposals, not benchmark settings. See the [component map](docs/COMPONENT_MAP.md) for the call path and the Python-to-LangGraph mapping.

The functional verdict stays independent of the termination reason: a completed attempt can fail canonical checks, and a budget-stopped repair can pass them. Provider and tool timeouts, context exhaustion, retries, and interruptions leave traces and candidate artifacts when the harness can collect them. Invalid patches, canonical check failures, and environment failures have separate categories. The evaluator has its own bounded timeout so it can score a partial candidate after agent execution stops. Scripted runs have unavailable cost; direct-provider runs separate reported charges, token-based estimates, missing usage, and conservative spend reservations. Qualitative review stays pending until a reviewer records it.

The generated `metadata.json`, `trace.jsonl`, `candidate.patch`, `candidate-files.json`, `checks.json`, `result.json`, and `report.html` live in the artifact destination, outside the Git repository. The default scripted repair command saves its checkpoint under `../../orchestration/evidence/issue-3/scripted-repair/`.

Run the complete Docker attempt tests by setting `AGENT_EVAL_DOCKER_INTEGRATION=1`, `ML_TUTOR_ADMISSION_EVIDENCE`, and `ML_TUTOR_REPOSITORY` before `python3 -m unittest tests.test_scripted_attempt_docker -v`.

## Run the bounded DeepSeek attempt

The direct adapter calls `https://api.deepseek.com/chat/completions` with `deepseek-flash`, thinking enabled at low effort, and at most 20,000 output tokens. It preserves `reasoning_content` in follow-up tool requests, normalizes tool calls and cache usage, and applies `ModelRequest.timeout_seconds` at the blocking HTTP transport. The credential file is read by the outer Python process; the task container receives no API key.

Run the combined smoke and repair command only after creating a private text file containing the API key. The smoke uses at most 512 output tokens and must complete one provider-selected `search_text` call plus a follow-up response before the repair starts. It does not force `tool_choice`, and it never edits a repository or executes a shell command. Both stages stop before sending any request whose conservative peak-rate reservation would exceed its local or shared USD ceiling:

```bash
python3 -m agent_eval_harness.cli.run_deepseek_attempt \
  --credential-file /path/to/private/deepseek-api-key.txt \
  --admission-evidence /path/to/issue-2/admission.json \
  --source-repository /path/to/prompt-engineering-group-project \
  --artifact-dir /path/to/issue-5-deepseek
```

The command defaults to USD 1.00 shared for the smoke and repair, USD 0.10 for the smoke, and USD 0.30 for the repair attempt. Each request reserves peak uncached input plus its maximum output cost before HTTP; retries consume a fresh reservation, and missing usage leaves the worst-case reservation in place. Known usage is estimated from the current pricing snapshot and the request's UTC peak/off-peak band. The HTML report keeps provider-reported charges separate from estimates and shows missing usage explicitly. The official price page is mutable, so the artifact records its source, checked date, and per-request pricing timestamp.

To run the smoke by itself, without starting a repair:

```bash
python3 -m agent_eval_harness.cli.deepseek_smoke \
  --credential-file /path/to/private/deepseek-api-key.txt \
  --artifact-dir /path/to/issue-5-smoke
```

The provider fixtures can be run offline with `python3 -m unittest tests.test_deepseek_provider tests.test_report_cost -v`. Docker-backed fixtures exercise the same public attempt-and-evaluation boundary when `AGENT_EVAL_DOCKER_INTEGRATION=1`, `ML_TUTOR_ADMISSION_EVIDENCE`, and `ML_TUTOR_REPOSITORY` are set; they do not need provider credentials.

## Run the failure and recovery checkpoint

This offline scripted attempt first requests an exact patch that cannot match. The tool returns an error to the model, which corrects the patch on its next turn. It then adds a new file and runs a command with a long result. The two-call proposal ends the attempt before a final model response; the independent evaluator still checks the collected patch.

```bash
python3 -m agent_eval_harness.cli.run_failure_recovery \
  --admission-evidence /path/to/issue-2/admission.json \
  --source-repository /path/to/prompt-engineering-group-project \
  --output-dir /path/to/failure-recovery
```

The expected outcome is `termination_reason: model_call_budget` with `functional_verdict: success`, the added file in `candidate.patch`, and all canonical checks passing. Open `report.html`, then inspect the failed and recovered tool events in `trace.jsonl`, the truncation marker in the model-visible result, and its full output file under `tool-results/`. The budgets in this command are demonstration proposals that can be changed with `--max-model-calls` and `--tool-output-limit-bytes`; neither the scripted run nor these values represent live-model calibration.

## Compare the Python loop and LangGraph

LangGraph is pinned with its complete resolved Python dependency set in
`requirements-langgraph.txt`. Install it in a repository-local environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-langgraph.txt
```

Run the deterministic comparison with the locally admitted task evidence and
the same pinned ML Tutor checkout. This uses scripted responses and makes no
hosted model request; it does require Docker for the task and evaluator
containers.

```bash
.venv/bin/python -m agent_eval_harness.cli.run_langgraph_parity \
  --admission-evidence /path/to/issue-2/admission.json \
  --source-repository /path/to/prompt-engineering-group-project \
  --output-dir /path/to/langgraph-parity
```

The command runs correct-repair, tool-error/recovery with a shared model-call
budget stop, and a deliberately smaller graph-node budget. It writes separate
attempt directories for `python-loop` and `langgraph`, including each
`report.html`, `trace.jsonl`, and candidate patch, plus `comparison.json` with
the machine-checked parity results. Read `comparison.json` first, then inspect
the paired reports and traces. Graph node steps are counted separately from
model requests. By default the graph limit is derived as
`2 * max_model_calls + 1` (a model node and tool node per call, plus the final
node that observes the common request limit); an optional
`max_graph_steps` budget is recorded as a graph-only demonstration limit.
The compiled graph's recursion limit is set above that effective node limit so
LangGraph's default recursion guard cannot stop a parity run early.

The mapping and framework boundary are documented in
[the design](docs/DESIGN.md). This initial graph uses explicit state, model and
tool nodes, a message reducer, conditional routing, and START/END. It adds no
checkpoint persistence or automatic context compaction.

## Run the matched Python-loop and LangGraph comparison

The bounded matched-run coordinator validates admitted-task and scripted-parity
evidence, runs the provider smoke check first, and then uses one shared spend
ledger for a fresh attempt under each orchestrator. It keeps provider or
environment failures separate from valid repair outcomes. The exact reproduction
command, artifact map, architecture walkthrough, and learning checkpoint are in
[the matched-run guide](docs/MATCHED_RUN.md). The live comparison still needs a
private credential-file path and a separate review of its actual attempt artifacts.

## Render a side-by-side report from saved attempts

The comparison renderer reads existing attempt artifacts and performs no model
request, task execution, or evaluation. It shows configuration match flags,
verdicts and stop reasons, token/cache use, model and tool latency, reported and
estimated cost, event evidence, the candidate diff, canonical checks, and a
separate qualitative review. Long request context and event payloads are
collapsed by default. Missing fields remain marked unavailable.

For example, compare the recorded successful control attempts without rerunning
the parity experiment:

```bash
python3 -m agent_eval_harness.reports.compare_report \
  --python-loop /path/to/langgraph-parity/correct/python-loop \
  --langgraph /path/to/langgraph-parity/correct/langgraph \
  --output /path/to/issue-7/comparison.html
```

The report links to each attempt's metadata, trace, candidate patch, check
results, and retained tool outputs. Configuration dimensions with missing
metadata are marked unavailable; differing values are marked mismatched. A
pair with mismatched task, source, provider/model, settings, or budgets must not
be presented as a controlled comparison. Environment matching uses the
recorded task-image Dockerfile hash and runtime; mutable tags and recorded image
IDs are shown separately for audit. Missing dependency versions remain
unavailable. Token and latency differences are shown separately from money
because cache warmth and pricing periods affect cost.

To show a completed review, pass one separate JSON review record for each
attempt. The record is validated against the attempt's task, implementation,
source revision, and start timestamp. Without a record the report says that
qualitative review is pending. See [the review record contract](docs/REVIEW_RECORD.md).

See the [design interview](docs/design-interview.md), [published specification](docs/SPEC.md), [implementation design](docs/DESIGN.md), [learning sequence](docs/LEARNING_PLAN.md), [component map](docs/COMPONENT_MAP.md), and [ticket breakdown](docs/TICKETS.md) for the broader project.

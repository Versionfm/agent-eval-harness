# Agent Eval Harness

This repository is a learning project for coding-agent harness engineering and independent evaluation. The implemented slices admit a reproducible ML Tutor retrieval task and run a complete scripted repair through a disposable coding-agent environment and independent evaluator.

The task pins `Versionfm/prompt-engineering-group-project` at `6890d9eae6ebd2967553eaf5a0c5753c26322182`. Its public description is separate from the curator-owned defect, known repair, and canonical checks. The checks use synthetic sections and an injected fake tutor response.

The admission runner creates three disposable source copies, builds a digest-pinned Python 3.12.13 environment without network access, and runs the canonical checks in separate containers. Each check container has no network, a read-only task mount, and a separate read-only evaluator mount. The runner produces machine-readable evidence and a small HTML summary. Setup and evaluator errors are reported as `invalid_environment`; behavior mismatches are `rejected`.

## Run the admission experiment

Provide a local ML Tutor checkout containing the pinned commit:

```bash
python3 -m agent_eval_harness.admit \
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
python3 -m agent_eval_harness.run_scripted_attempt \
  --admission-evidence /path/to/issue-2/admission.json \
  --source-repository /path/to/prompt-engineering-group-project \
  --output-dir /path/to/scripted-attempt
```

The command rebuilds the task image from the manifest's digest-pinned Dockerfile with Docker networking disabled, probes Python 3.12.13, and then uses the resolved image ID. The agent container has one writable mount at `/task`, no network, no evaluator mount, and no credentials or Docker socket. The evaluator receives a separate fresh copy of the defective repository plus the canonical checks on read-only mounts.

The explicit loop keeps conversation messages, model requests, provider retries, and time limits in attempt state. Tool requests execute in response order. Errors return to the model as structured results, and each new request receives the time remaining before the attempt deadline. Tool output sent to the model is bounded and marked when truncated; the full output remains in `tool-results/` and the trace. Numeric limits are configurable calibration proposals, not benchmark settings.

The functional verdict stays independent of the termination reason: a completed attempt can fail canonical checks, and a budget-stopped repair can pass them. Provider and tool timeouts, context exhaustion, retries, and interruptions leave traces and candidate artifacts when the harness can collect them. Invalid patches, canonical check failures, and environment failures have separate categories. The evaluator has its own bounded timeout so it can score a partial candidate after agent execution stops. Cost remains unavailable for scripted runs and qualitative review stays pending until a reviewer records it.

The generated `metadata.json`, `trace.jsonl`, `candidate.patch`, `candidate-files.json`, `checks.json`, `result.json`, and `report.html` live in the artifact destination, outside the Git repository. The default scripted repair command saves its checkpoint under `../../orchestration/evidence/issue-3/scripted-repair/`.

Run the complete Docker attempt tests by setting `AGENT_EVAL_DOCKER_INTEGRATION=1`, `ML_TUTOR_ADMISSION_EVIDENCE`, and `ML_TUTOR_REPOSITORY` before `python3 -m unittest tests.test_scripted_attempt_docker -v`.

## Run the failure and recovery checkpoint

This offline scripted attempt first requests an exact patch that cannot match. The tool returns an error to the model, which corrects the patch on its next turn. It then adds a new file and runs a command with a long result. The two-call proposal ends the attempt before a final model response; the independent evaluator still checks the collected patch.

```bash
python3 -m agent_eval_harness.run_failure_recovery \
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
.venv/bin/python -m agent_eval_harness.run_langgraph_parity \
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

See the [design interview](docs/design-interview.md), [published specification](docs/SPEC.md), [implementation design](docs/DESIGN.md), [learning sequence](docs/LEARNING_PLAN.md), and [ticket breakdown](docs/TICKETS.md) for the broader project.

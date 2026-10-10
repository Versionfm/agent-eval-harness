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

The explicit loop keeps the conversation messages and model-call count in attempt state. Each response either completes the attempt or provides ordered tool calls; tool results are appended to history for the next request. Provider reasoning fields such as `reasoning_content` remain on the assistant message sent with that follow-up. The current budget contract covers model calls, shell command time, and tool-output size; broader deadline and recovery policies are a later slice.

The returned functional verdict is independent of the termination reason: a completed attempt can still fail canonical checks. The report shows exposed model/tool activity, the diff, checks, and environment evidence. Cost remains unavailable for the scripted provider and qualitative review stays pending until a reviewer records it.

The generated `metadata.json`, `trace.jsonl`, `candidate.patch`, `candidate-files.json`, `checks.json`, `result.json`, and `report.html` live in the artifact destination, outside the Git repository. The default command saves the runnable learning checkpoint under `../../orchestration/evidence/issue-3/scripted-repair/`.

Run the complete Docker attempt tests by setting `AGENT_EVAL_DOCKER_INTEGRATION=1`, `ML_TUTOR_ADMISSION_EVIDENCE`, and `ML_TUTOR_REPOSITORY` before `python3 -m unittest tests.test_scripted_attempt_docker -v`.

See the [design interview](docs/design-interview.md), [published specification](docs/SPEC.md), [implementation design](docs/DESIGN.md), [learning sequence](docs/LEARNING_PLAN.md), and [ticket breakdown](docs/TICKETS.md) for the broader project.

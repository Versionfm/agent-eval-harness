# Agent Eval Harness

This repository is a learning project for coding-agent harness engineering and independent evaluation. The first implemented slice admits one reproducible ML Tutor retrieval task before any agent attempt or live model call.

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

The next learning checkpoint is to inspect the task manifest, the three-run evidence, and the HTML summary before expanding the harness into model/tool attempts.

See the [design interview](docs/design-interview.md), [published specification](docs/SPEC.md), [implementation design](docs/DESIGN.md), [learning sequence](docs/LEARNING_PLAN.md), and [ticket breakdown](docs/TICKETS.md) for the broader project.

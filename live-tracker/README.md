# Live tracker

Dedicated home for live observation and recorded playback of harness attempts. Specification: [issue #10](https://github.com/Versionfm/agent-eval-harness/issues/10). Status: tickets [#11](https://github.com/Versionfm/agent-eval-harness/issues/11) (one scripted Python attempt observed live) and [#13](https://github.com/Versionfm/agent-eval-harness/issues/13) (the workbench: component map, timeline and inspector) implemented. Playback, legacy adapters, reconnect/recovery hardening and the LangGraph integration are deferred to #12, #14–#18. The call chain and the selected-point experiment are in [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md).

## Open the workbench on a controlled attempt

`--scenario workbench` runs a scripted attempt that exercises every inspector field: a shell output over the model-visible limit containing `<script>` markup, a failing and a succeeding read in one model turn, and a completion with no usage. Use the default `--scenario read` for the one-read attempt described below.

```bash
PYTHONPATH=live-tracker/src python -m live_tracker.run_scripted --scenario workbench \
  --admission-evidence <admission.json> --source-repository /path/to/prompt-engineering-group-project
```

## Reproduce the observed scripted attempt

Requires Docker and the admitted task environment (see the harness README). Starts the loopback viewer, then runs a scripted model → `read_file` → completion attempt in the real task container, recording every event:

```bash
PYTHONPATH=live-tracker/src python -m live_tracker.run_scripted \
  --admission-evidence <admission.json bound to the current task package> \
  --source-repository /path/to/prompt-engineering-group-project
# prints "viewer: http://127.0.0.1:8765/"; open it while the attempt runs. Ctrl+C stops the viewer.
```

Tests (Docker tests need `AGENT_EVAL_DOCKER_INTEGRATION=1`, `ML_TUTOR_ADMISSION_EVIDENCE` and `ML_TUTOR_REPOSITORY`; the browser test uses the system Chrome, `channel="chrome"`):

```bash
PYTHONPATH=live-tracker/src python -m unittest discover -s live-tracker/tests -t live-tracker/tests
```

The compiled client is committed in `web/dist/`. To rebuild after editing `web/src/timeline.ts`: `cd live-tracker/web && npm install && npm run build`.

## Event boundary

The harness publishes through an optional `event_sink` (`agent_eval_harness/observation.py`) passed to `attempt_and_evaluate`. Without it, behavior is unchanged. The sink receives `attempt_started`, `initial_context`, `model.start`/`model.outcome` (`model-N`), `tool.start`/`tool.outcome` (`tool-N-I`, parent `model-N`) and `attempt_finished` (with the candidate patch). The recorder owns sequence, timestamps, elapsed time and artifact digests. Starts are emitted before the provider or tool call, outside its exception handling, so a failed start stops the attempt before any further operation. Outcomes and artifacts are written and fsynced before the event is appended. Observer data never enters model messages.

Final `result.json` and `report.html` are still written from the in-memory trace after the attempt, next to the append-only `events.jsonl`; the log is never rewritten.

## Implemented in #11 versus deferred

- Implemented: the sink contract on the Python loop; durable recorder with contiguous sequences and content-addressed artifacts; reader that ignores only an unterminated final record and raises on corruption; loopback server (`/`, `/static`, `/api/attempts`, events with `after`, confined artifacts, SSE with `Last-Event-ID` resume); minimal TypeScript timeline; the scripted runner; observation-on/off parity test; system-Chrome browser test.
- Implemented in #13: `phase.enter` (module:function source identity) and `state` events from the Python loop, registered source identities with `/api/sources`, the workbench (component map, timeline, inspector with selected-point state and labelled excerpts), the `workbench` scripted scenario and a system-Chrome acceptance test against a Docker attempt (`tests/test_timeline_browser_docker.py`, which keeps its #11 file name).
- Deferred: LangGraph observation (#15; passing a sink with `langgraph` is refused), mutation capture (#16), recording-failure recovery scenarios and bounded slow-consumer buffering (#12), legacy recording adapters and playback controls (#14), SSE connection hardening (#17), and provider streaming. Evaluation and report phases are not yet phase events.

Read the [published tickets](docs/TICKETS.md), [specification](docs/SPEC.md), [design](docs/DESIGN.md), [learning sequence](docs/LEARNING_PLAN.md) and [decision interview](../docs/observability-interview.md). The disposable [layout prototype](../../harness-viewer-prototype.html?variant=A) is outside the production source tree. Its original builder/template and verdict are captured on local branch `prototype/live-tracker-layout` at `0024ce6243b62b31b2f6121758d2bbb0e9a44bb0`; this throwaway branch has not been pushed.

## Planned source layout

```text
live-tracker/
├── README.md
├── docs/
│   ├── DESIGN.md
│   └── LEARNING_PLAN.md
├── src/live_tracker/       # Python package: recorder, readers, server, integration
├── web/                   # TypeScript, HTML and CSS client
└── tests/                 # Recording, delivery, UI and integration verification
```

Source directories are created by their implementation tickets; #11 adds the recorder, reader, server, runner and client.

## Boundary

- `agent_eval_harness/` continues to own model/tool execution, both orchestrators, budgets, task environments and independent evaluation.
- `live-tracker/` owns incremental recording, reading/recovery, legacy adaptation, loopback delivery and the browser interface.
- A narrow injected event sink lets harness stages publish observable events. Instrumentation remains next to the stages it describes; browser/server imports stay out of the harness.
- Reports and playback read the same authoritative history. Integration adapts evidence to the existing report renderer without creating a second attempt runner or a separate UI-only log.
- Generated attempt evidence remains in configured evidence directories, separate from tracker source.

Python imports use `live_tracker`; `live-tracker` is the folder name. No move or rename of the existing harness code is required.

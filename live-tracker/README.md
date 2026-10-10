# Live tracker

Dedicated home for live observation and recorded playback of harness attempts. Specification: [issue #10](https://github.com/Versionfm/agent-eval-harness/issues/10). Status: ticket [#11](https://github.com/Versionfm/agent-eval-harness/issues/11) implemented (one scripted Python attempt observed live); ticket [#12](https://github.com/Versionfm/agent-eval-harness/issues/12) adds interrupted-recording and recorder-failure handling. Playback, legacy adapters, the LangGraph integration and slow-consumer buffering are deferred to #13–#18.

## Reproduce the recovery behaviors (no provider, no Docker)

```bash
PYTHONPATH=live-tracker/src python -m live_tracker.recovery_demo
# prints each synthetic recording's state (complete, interrupted, failed, open, corrupt) and exits 0 when all match
```

Scenarios: a clean recording; a process death partway through an outcome line (torn tail, no marker); a recorder failure whose marker is saved; a failure where storage also refuses the marker; a damaged middle record.

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

## Recording failure and recovery

- A mandatory write (artifact, event append or fsync) that fails raises `EventRecordingError` to the harness. The harness runs no further model or tool operation, closes the task container, and recovers and scores the candidate that exists. The result carries `recording: {status: "failed", error}`, `termination_reason: harness_error`, and the verdict from that canonical evaluation. Recording status, termination and verdict are reported separately.
- The recorder then refuses every later event and tries to save `recording-failure.json` (atomic write). If storage refuses the marker, the error still reaches the caller and the marker is not claimed to exist; the saved prefix stays incomplete.
- The reader (`read_attempt_history`) never writes. It reports one `state`: `complete` (finish recorded), `failed` (marker present), `interrupted` (torn final record: bytes after the last newline are not verified), `open` (no finish, no marker, no torn tail), `corrupt` (problems listed with sequence numbers, such as malformed JSON, schema or sequence mismatch, identity conflicts, missing or damaged artifacts). Damaged records are never skipped: a structural problem ends the verified prefix, and an artifact problem is marked on its event.
- Unresolved operations (a `*.start` without its outcome) are listed; the browser labels them `unresolved`, or `awaiting outcome` while the attempt is open.
- Served as `recording` on `/api/attempts` and `/api/attempts/<id>/events`, and as a `recording-status` SSE frame. The browser shows a banner with the state.
- A recorder never resumes an existing log (`FileExistsError`).

### Supported crash-recovery conditions

Guarantees are for process crashes (an exception, an interrupted or killed Python process) on a local filesystem where a completed `fsync` is durable:

- An artifact is fsynced and renamed into place before the event that references it is appended, and an event is fsynced before `emit` returns. The start record of an operation is durable before the model or tool call starts.
- A record whose append and fsync completed before the crash is readable; the final unterminated record is reported as interrupted, never as evidence.
- Recovery is reading only. To continue, start a new attempt; nothing is resumed or re-executed.

Not claimed: power loss, kernel or hardware faults, filesystems or network mounts without fsync durability, or concurrent writers other than the one recorder. Measured overhead is out of scope for this ticket.

Fault injection goes through the recorder boundary: `FaultyStorage(kind, event_type, occurrence=, tear=, fail_marker=)` replaces the durable storage. The Docker tests (`tests/test_recording_faults_docker.py`) inject failures into real scripted attempts and check that no later model or tool operation runs.

## Implemented in #11 versus deferred

- Implemented: the sink contract on the Python loop; durable recorder with contiguous sequences and content-addressed artifacts; reader that ignores only an unterminated final record and raises on corruption; loopback server (`/`, `/static`, `/api/attempts`, events with `after`, confined artifacts, SSE with `Last-Event-ID` resume); minimal TypeScript timeline; the scripted runner; observation-on/off parity test; system-Chrome browser test.
- Implemented in #12: torn-tail, unresolved-operation, damaged-record and recorder-failure states in the reader, server and browser; the harness stop-on-recording-failure with separate recording status; the no-provider demo; fault-injection tests through real attempts; the Chrome recovery test.
- Deferred: LangGraph observation (#15; passing a sink with `langgraph` is refused), mutation capture (#16), bounded slow-consumer buffering and SSE cursor rules (#17, the stream still polls the full log), legacy recording adapters and playback controls (#13/#14), the layout/inspector beyond the minimal timeline, provider streaming, and a recording-status line in the static HTML report (the report shows only the harness error).

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

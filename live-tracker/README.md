# Live tracker

Dedicated home for live observation and recorded playback of harness attempts. Specification: [issue #10](https://github.com/Versionfm/agent-eval-harness/issues/10). Status: tickets [#11](https://github.com/Versionfm/agent-eval-harness/issues/11) (one scripted Python attempt observed live), [#12](https://github.com/Versionfm/agent-eval-harness/issues/12) (interrupted recordings and recorder-failure handling), [#13](https://github.com/Versionfm/agent-eval-harness/issues/13) (the workbench: component map, timeline and inspector), [#15](https://github.com/Versionfm/agent-eval-harness/issues/15) (LangGraph node, router and state transitions through the same sink and workbench) and [#17](https://github.com/Versionfm/agent-eval-harness/issues/17) (reconnect, catch-up, bounded delivery and lag) [#16](https://github.com/Versionfm/agent-eval-harness/issues/16) (repository changes after mutating tools) and [#14](https://github.com/Versionfm/agent-eval-harness/issues/14) (playback, legacy adapter, final results and projected report) implemented. The live comparison pair (#18) is deferred. The call chain and the selected-point experiment are in [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md).

## Reproduce the recovery behaviors (no provider, no Docker)

```bash
PYTHONPATH=live-tracker/src python -m live_tracker.recovery_demo
# prints each synthetic recording's state (complete, interrupted, failed, open, corrupt) and exits 0 when all match
```

Scenarios: a clean recording; a process death partway through an outcome line (torn tail, no marker); a recorder failure whose marker is saved; a failure where storage also refuses the marker; a damaged middle record.
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

## Reconnect, catch-up and lag (#17)

No-provider demonstration (no Docker, no model; run from the repository root, takes a few seconds). A scripted recorder appends 41 events while three raw SSE observers read the loopback stream: one reconnects, one resumes from an earlier cursor so the server re-sends events, and one stops reading past the stall timeout and is disconnected:

```bash
PYTHONPATH=live-tracker/src python -m live_tracker.delivery_demo
```

Expected output ends with `delivery demo passed: no gaps, duplicates deduplicated, slow observer resumed from disk` (the script asserts this and exits non-zero otherwise).

Delivery design:

- SSE ids are `<attempt_id>:<sequence>`. A cursor comes from `Last-Event-ID` or `?after=`; the larger one wins. A cursor for another attempt or a malformed one is refused with HTTP 409, a non-integer `after` with 400, and a cursor beyond the latest recorded sequence with 409. The same rules apply to `/events`. Refusals are never reinterpreted.
- Catch-up and live share one source: each stream reads the saved log, so history and live events come from the same committed sequence and nothing is lost while the recorder appends.
- Each connection has its own writer thread and a bounded buffer of 256 frames (`BUFFER_EVENTS`). The reader offers frames and waits up to 5 s (`STALL_SECONDS`) for room; if the buffer stays full, only that socket is cut. The recorder never waits on the server, and the observer resumes from disk with its last cursor.
- Keepalive comments every 2 s detect a departed browser; the stream asks for a reconnect after 500 ms.
- A `head` frame reports the latest recorded sequence, so the browser can show lag. A `recording-status` frame (#12) follows each batch of events and carries the recording state.
- The browser ledger (`web/src/connection.ts`) dedupes by sequence: the same bytes again are silent. Missing sequences are shown as gap rows. A different payload for a displayed sequence, another attempt, or an unknown schema is shown as a conflict, and the feed stops. The state is shown as `live`, `reconnecting`, `refused`, `conflict`, `recording-error` or `finished`. Lag is the latest reported sequence minus the displayed one; while the stream is down the browser polls `/api/attempts` each second, and the detail line says whether the viewer answered.

Tests (`PYTHONPATH=live-tracker/src python -m unittest discover -s live-tracker/tests -t live-tracker/tests`):

- `test_delivery.py`: cursor refusals, history-to-live handoff while the recorder appends, a stalled observer cut and resumed from disk, a departed viewer that does not affect recording, and the `head` frame.
- `test_reconnect_browser.py`: system Chrome (`channel="chrome"`). The viewer process is killed and restarted on the same port while events continue. The page must show `reconnecting`, then catch up to exactly sequences 1 to 11 with no duplicate or gap rows.
- `test_client_ledger.py`: the compiled ledger under Node, with literal expected results for duplicates, gaps and conflicts. It is skipped if `node` is not on the path.
- `test_viewer_detach_docker.py` (Docker): a real scripted attempt in the task container; the viewer is closed while the attempt is running, and the attempt must still finish with contiguous events and `result.json`.

Known ceilings (deliberate): the stream re-reads the whole log each 0.2 s tick (`# ponytail:` in `server.py`; an incremental byte-offset tail is the upgrade). Buffers count frames, not bytes; events carry previews while large payloads are artifacts. Lag while disconnected uses the list endpoint, not a head endpoint.

## Event boundary

The harness publishes through an optional `event_sink` (`agent_eval_harness/observation.py`) passed to `attempt_and_evaluate`. Without it, behavior is unchanged. The sink receives `attempt_started`, `initial_context`, `model.start`/`model.outcome` (`model-N`), `tool.start`/`tool.outcome` (`tool-N-I`, parent `model-N`) and `attempt_finished` (with the candidate patch). The recorder owns sequence, timestamps, elapsed time and artifact digests. Starts are emitted before the provider or tool call, outside its exception handling, so a failed start stops the attempt before any further operation. Outcomes and artifacts are written and fsynced before the event is appended. Observer data never enters model messages.

Final `result.json` is still written from the in-memory trace after the attempt, next to the append-only `events.jsonl`; the log is never rewritten. For observed attempts `report.html` is then rendered from the log and linked artifacts (see Playback and final results below).

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

## LangGraph node transitions (#15)

The same sink and workbench observe `orchestrator="langgraph"`. Each graph node is recorded where it runs: `node.enter` before the node (`operation_id` `graph-step-N`, `node`, `graph_step_count`, `source`), `node.outcome` after it, a `state` snapshot with `after_node`, and a `route.decision` (`next`, `reason`) from the router. Model and tool events are the shared ones. A node that raised has no outcome and shows as `unresolved` once the attempt finishes. Graph steps are not model calls, and the graph-step cap is unchanged. Source walkthrough: [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md#langgraph-source-walkthrough-15).

No-provider reproduction (Docker and the admitted task; the scripted model is finite):

```bash
PYTHONPATH=live-tracker/src python -m live_tracker.run_scripted --orchestrator langgraph --scenario workbench \
  --admission-evidence <admission.json> --source-repository /path/to/prompt-engineering-group-project
```

Tests: `test_langgraph_observation_docker.py` runs repair, tool-error-then-model-budget and spend-budget attempts for both orchestrators, observed and unobserved, and asserts identical model-visible requests, ordered tool results, candidate files and verdicts. `test_timeline_browser_docker.py` checks the LangGraph node rows, component counts, router and node source links in system Chrome. The offline checks are `tests/test_langgraph_observation.py` and `test_sources.py`.

Observation overhead (no provider, scripted `workbench` scenario, observed and unobserved runs alternating):

```bash
PYTHONPATH=.:live-tracker/src python live-tracker/experiments/observation_overhead.py \
  --admission-evidence <admission.json> --source-repository /path/to/prompt-engineering-group-project --repeats 3
```

Measured once with 3 repeats (Docker, `workbench` scenario, both attempts `agent_completed/failure`, which is expected for a scripted non-repair). Mean attempt wall time: python-loop 2.60 s observed vs 2.68 s unobserved; langgraph 2.53 s observed vs 2.67 s unobserved. The observed runs were not slower; the spread between runs (about 2.4 to 3.2 s) is larger than any difference, so no overhead is distinguishable at this size. Time inside `emit` (record, fsync, artifact writes) was 0.06 s per attempt for python-loop (25 emits, 2.4 MB recorded) and 0.07 s for langgraph (35 emits, 2.3 MB). The snapshot computation is outside `emit` and is not timed separately. These are small scripted attempts; larger attempts were not measured.

## Playback and final results (#14)

Zero-cost inspection of the preserved first live pair (no provider key, no Docker). It registers the two legacy directories read-only and serves them on loopback:

```bash
PYTHONPATH=live-tracker/src python -m live_tracker.playback \
  --legacy <evidence>/live-first-2026-10-10/python-loop --legacy <evidence>/live-first-2026-10-10/langgraph
# prints "playback: http://127.0.0.1:8766/". Ctrl+C stops it. Saved attempts register the same way with --recording <attempt-directory>.
```

- **Two modes, always labelled.** A running attempt is *live*: the stream is followed and the selection stays on the newest event until you step away; "Follow latest" resumes. A completed, interrupted, failed or legacy recording is *saved*: its recorded events load once, and play/pause, speed, previous/next and scrub move through them. Playback reads evidence only. It never calls a model, a tool, a repository command or a provider, and it never appends or resumes.
- **Legacy adapter** (`live_tracker/legacy.py`). It reads `trace.jsonl` and `tool-results/` without writing, and it maps each record to the viewer's event shape using the recorded `event_id` as the sequence. Labelled *not recorded*: attempt start and finish, operation starts (so no waiting or unresolved state), Python phases, graph nodes and routing, selected-point state, elapsed time, intermediate captures and the recording status. Labelled *derived*: the output digests, computed now from the current bytes, and the output links added after the run. Labelled *inline*: model responses carried in the trace. Nothing is re-timed or invented; the bytes are checked against `artifact-sha256.json` in tests.
- **Final results.** The panel (`/api/attempts/<id>/final`) shows termination, verdict, failure category, recording status, Codex review, canonical checks and the candidate patch from the finish record. It does not change with the selection. The review is read from `review.json` at view time: the run records it as pending, and a complete `review.json` makes it completed.
- **Report projection.** `/api/attempts/<id>/report` renders the harness report from the log and linked artifacts, not from the in-memory result, and shows the recording and review status. Observed runs also save `report.html` this way. `test_playback_browser_docker.py` asserts that the viewer and the report agree on response content, reasoning, tool arguments, retained output, accounting, verdict, checks and patch. The viewer shows the first 2000 characters of retained output and the report shows all of it.
- **Why playback is not resumption.** Playback replays what was recorded and re-executes nothing. Resuming an agent would need the provider context rebuilt, a fresh paid model call, and tools run again against the repository. The recorder refuses to resume an existing log for that reason. A selection at event N shows only the state recorded by then; final totals are never used for earlier state. An interrupted recording stops at its verified prefix, and an unmatched start stays unresolved rather than counting as success.

Tests (the browser acceptance builds three Docker attempts: complete, torn final record and refused mandatory write, then opens them with the legacy pair in system Chrome):

```bash
AGENT_EVAL_DOCKER_INTEGRATION=1 ML_TUTOR_ADMISSION_EVIDENCE=<admission.json> ML_TUTOR_REPOSITORY=<prompt-engineering-group-project> \
  PYTHONPATH=live-tracker/src python -m unittest discover -s live-tracker/tests -t live-tracker/tests
```


## Repository changes after mutating tools (#16)

Observed attempts only. After each `apply_patch` or `run_shell` that was dispatched, the harness emits `tool.capture` linked to the tool operation (`parent_operation_id` = `tool-N-I`). It describes the task repository relative to the attempt's starting repository: text diffs with additions and deletions, added and deleted files, and binary files as metadata only (path, sizes, sha256). The complete text diffs are in the linked `capture.json`; the event carries bounded previews. Captures never change the tool result, the model-visible messages or the canonical candidate, which is still collected by `collect_candidate` at the end. Unobserved attempts take no capture code path.

Statuses, each labelled apart in the inspector:

- `captured`: changes shown, with settlement.
- `unsettled`: a process was still alive after the shell returned. No snapshot is taken and no change is shown; the live processes are listed.
- `unavailable`: the settlement probe failed (not a limit), so no change is shown.
- `omitted` with `byte_limit` or `time_limit`: a declared bounded omission. Not a failure.
- `error`: the capture itself failed (for example a symbolic link in the repository). Not a limit and not a tool result.

Settlement, the rule for when a capture may describe the repository:

- Shell timed out and the container was force-removed: settled, because every process in it is gone.
- `apply_patch` returned: settled, because its edit process has exited (no probe, as specified).
- `run_shell` returned: not settled by return alone. A read-only probe (`python -c`, reading `/proc`) runs in the container and lists processes that are alive. PID 1 (the idle sleeper), zombies and the probe are not counted. Any other live process makes the capture `unsettled`. The probe signals nothing and does not change the tool's semantics. If it does not finish within the time limit, the capture is an `omitted` `time_limit`.

Limits, passed as `CaptureLimits` and recorded in every `tool.capture` event and in `metadata.repository_capture`:

| limit | value | reason |
| --- | --- | --- |
| `max_seconds` (probe and snapshot together) | 2.0 | Captures measured 14 to 191 ms on the pinned repository (about 10x headroom). |
| `max_total_bytes` (repository content read per capture) | 4 MiB | The pinned task repository reads as 1.85 MB per capture (measured on all five captures), about 2.2x headroom. |
| `max_preview_bytes` (diff preview per file) | 4 KiB | Scripted diffs are under 100 bytes, so this is a display choice, not a measured value. |

Demo (no provider; Docker and the admitted task required). Partial mutation (successful patch, failing shell that changes two files, deletion, binary write, shell that writes then times out), then byte-limit, time-limit and settlement cases. It asserts each expectation and exits non-zero on a mismatch:

```bash
PYTHONPATH=live-tracker/src python -m live_tracker.capture_demo \
  --admission-evidence <admission.json> --source-repository /path/to/prompt-engineering-group-project
# ends with "capture demo passed: ..."
```

Settlement cases, and a caveat about the wording in the ticket. The literal writer `sh -c '(sleep 2; echo x > late.txt) &'` is settled, not unsettled: `docker exec` waits for the shell's output pipe, which the background `sleep` inherits, so the shell returns only after the writer exits. The probe confirms nothing is alive and the change is captured. The detached form `sh -c '(sleep 2; echo y > detached.txt) >/dev/null 2>&1 &'` returns at once with the writer alive, so it is the case that shows `unsettled`. Both are in the demo and `test_repository_capture_docker.py`.

Tests:

- `tests/test_repository_capture.py` (offline): text and binary descriptions, counts, previews, the linked artifact facts, settlement rules with a canned probe, the time-limit and probe-failure paths, byte-limit omission and symbolic-link error.
- `live-tracker/tests/test_repository_capture_docker.py` (Docker): mutations linked to their tools and matching the files on disk; observed and unobserved parity of model-visible messages, candidate files and checks; the LangGraph tool node captures the same as the Python loop; background writers.
- `live-tracker/tests/test_repository_capture_browser_docker.py` (Docker, system Chrome `channel="chrome"`): the inspector shows the captured change for the patch, with its `capture.json` link.
- The workbench browser and LangGraph tests now expect the `tool.capture` after the shell outcome.

Overhead (no provider, Docker, `mutations` scenario, 3 repeats, observed and unobserved alternating, 5 captures per attempt):

```bash
PYTHONPATH=.:live-tracker/src python live-tracker/experiments/observation_overhead.py \
  --admission-evidence <admission.json> --source-repository <prompt-engineering-group-project> \
  --scenario mutations --repeats 3
```

- Capture time per attempt (summed `capture_seconds`): 0.49 s python-loop and 0.55 s LangGraph, about 0.1 s per capture.
- Recording time per attempt (time inside `emit`, including the capture events): 0.13 s python-loop and 0.15 s LangGraph.
- Wall time, observed versus unobserved: python-loop 7.16 s versus 7.95 s; LangGraph 7.71 s versus 6.48 s. The attempts ranged from 6.2 to 10.0 s, so these differences are within run-to-run noise. Three repeats cannot separate the observed overhead from it, and the capture cost is about 0.1 s per capture. Larger repeats were not measured.

Doubts and deferred items:

- `apply_patch` is settled by its return, as specified. A background writer started by an earlier shell that is still running could therefore appear in an `apply_patch` capture. The capture is then not settled in the strict sense, and the final candidate is still canonical.
- A capture that is not settled by a probe (for example a timed-out probe) is `omitted`, not `unsettled`, because the time limit, not a live process, stopped it.
- Recording failure during a `tool.capture` write follows the same mandatory-emit path as `tool.outcome` (#12): no further operation runs. A dedicated fault-injection test for this event is deferred.
- The inspector shows previews and the link to `capture.json`; a full repository view and a diff view across tools are deferred.

## Implemented in #11 versus deferred

- Implemented: the sink contract on the Python loop; durable recorder with contiguous sequences and content-addressed artifacts; reader that ignores only an unterminated final record and raises on corruption; loopback server (`/`, `/static`, `/api/attempts`, events with `after`, confined artifacts, SSE with `Last-Event-ID` resume); minimal TypeScript timeline; the scripted runner; observation-on/off parity test; system-Chrome browser test.
- Implemented in #13: `phase.enter` (module:function source identity) and `state` events from the Python loop, registered source identities with `/api/sources`, the workbench (component map, timeline, inspector with selected-point state and labelled excerpts), the `workbench` scripted scenario and a system-Chrome acceptance test against a Docker attempt (`tests/test_timeline_browser_docker.py`, which keeps its #11 file name).
- Implemented in #12: torn-tail, unresolved-operation, damaged-record and recorder-failure states in the reader, server and browser; the harness stop-on-recording-failure with separate recording status; the no-provider demo; fault-injection tests through real attempts; the Chrome recovery test.
- Implemented in #17: cursor refusals, catch-up and handoff, client dedupe and gaps, bounded per-connection buffering with slow-consumer disconnect, connection state and lag (see above).
- Implemented in #15: `node.enter`, `node.outcome`, `route.decision` and graph `state` events from `run_attempt_graph`; the LangGraph component entries (model node, tool node, router) with registered source links; `run_scripted --orchestrator langgraph`; the LangGraph Docker parity, browser and overhead checks described above. The sink is no longer refused for `langgraph`.
- Implemented in #14: playback controls for saved recordings, the read-only legacy adapter for the first live pair, the final-results panel separate from the selected point, the report projected from the log with recording and Codex review status, the playback server mode and its no-provider proof, and browser parity tests (see below).
- Implemented in #16: bounded repository capture after `apply_patch` and `run_shell` (see the section below), the `tool.capture` event, the inspector's capture section, the no-provider demo and the Docker, browser and overhead checks.
- Deferred: provider streaming, evaluation and report phase events, and the comparison desk (#18).

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

# Live tracker

Dedicated home for live observation and recorded playback of harness attempts. Specification: [issue #10](https://github.com/Versionfm/agent-eval-harness/issues/10). Status: tickets [#11](https://github.com/Versionfm/agent-eval-harness/issues/11) (one scripted Python attempt observed live) and [#17](https://github.com/Versionfm/agent-eval-harness/issues/17) (reconnect, catch-up, bounded delivery and lag) implemented. Recorder failure semantics (#12), playback, legacy adapters and the LangGraph integration are deferred to the other tickets in #10.

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
- A `head` frame reports the latest recorded sequence, so the browser can show lag.
- The browser ledger (`web/src/connection.ts`) dedupes by sequence: the same bytes again are silent. Missing sequences are shown as gap rows. A different payload for a displayed sequence, another attempt, or an unknown schema is shown as a conflict, and the feed stops. The state is shown as `live`, `reconnecting`, `refused`, `conflict`, `recording-error` or `finished`. Lag is the latest reported sequence minus the displayed one; while the stream is down the browser polls `/api/attempts` each second, and the detail line says whether the viewer answered.

Tests (`PYTHONPATH=live-tracker/src python -m unittest discover -s live-tracker/tests -t live-tracker/tests`):

- `test_delivery.py`: cursor refusals, history-to-live handoff while the recorder appends, a stalled observer cut and resumed from disk, a departed viewer that does not affect recording, and the `head` frame.
- `test_reconnect_browser.py`: system Chrome (`channel="chrome"`). The viewer process is killed and restarted on the same port while events continue. The page must show `reconnecting`, then catch up to exactly sequences 1 to 11 with no duplicate or gap rows.
- `test_client_ledger.py`: the compiled ledger under Node, with literal expected results for duplicates, gaps and conflicts. It is skipped if `node` is not on the path.
- `test_viewer_detach_docker.py` (Docker): a real scripted attempt in the task container; the viewer is closed while the attempt is running, and the attempt must still finish with contiguous events and `result.json`.

Known ceilings (deliberate): the stream re-reads the whole log each 0.2 s tick (`# ponytail:` in `server.py`; an incremental byte-offset tail is the upgrade, deferred because `reader.py` belongs to #12). Buffers count frames, not bytes; events carry previews while large payloads are artifacts. Lag while disconnected uses the list endpoint, not a head endpoint.

## Event boundary

The harness publishes through an optional `event_sink` (`agent_eval_harness/observation.py`) passed to `attempt_and_evaluate`. Without it, behavior is unchanged. The sink receives `attempt_started`, `initial_context`, `model.start`/`model.outcome` (`model-N`), `tool.start`/`tool.outcome` (`tool-N-I`, parent `model-N`) and `attempt_finished` (with the candidate patch). The recorder owns sequence, timestamps, elapsed time and artifact digests. Starts are emitted before the provider or tool call, outside its exception handling, so a failed start stops the attempt before any further operation. Outcomes and artifacts are written and fsynced before the event is appended. Observer data never enters model messages.

Final `result.json` and `report.html` are still written from the in-memory trace after the attempt, next to the append-only `events.jsonl`; the log is never rewritten.

## Implemented in #11 versus deferred

- Implemented: the sink contract on the Python loop; durable recorder with contiguous sequences and content-addressed artifacts; reader that ignores only an unterminated final record and raises on corruption; loopback server (`/`, `/static`, `/api/attempts`, events with `after`, confined artifacts, SSE with `Last-Event-ID` resume); minimal TypeScript timeline; the scripted runner; observation-on/off parity test; system-Chrome browser test.
- Implemented in #17: cursor refusals, catch-up and handoff, client dedupe and gaps, bounded per-connection buffering with slow-consumer disconnect, connection state and lag (see above).
- Deferred: LangGraph observation (#15; passing a sink with `langgraph` is refused), mutation capture (#16), recording-failure recovery scenarios (#12), legacy recording adapters and playback controls (#13/#14), the layout/inspector beyond the minimal timeline, and provider streaming.

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

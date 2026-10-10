# Live tracker

Dedicated home for live observation and recorded playback of harness attempts. Specification: [issue #10](https://github.com/Versionfm/agent-eval-harness/issues/10). Status: tickets [#11](https://github.com/Versionfm/agent-eval-harness/issues/11) (one scripted Python attempt observed live), [#13](https://github.com/Versionfm/agent-eval-harness/issues/13) (the workbench: component map, timeline and inspector), [#15](https://github.com/Versionfm/agent-eval-harness/issues/15) (LangGraph node, router and state transitions through the same sink and workbench) and [#17](https://github.com/Versionfm/agent-eval-harness/issues/17) (reconnect, catch-up, bounded delivery and lag) implemented. Recorder failure semantics (#12), mutation capture (#16), playback and legacy adapters (#14) are deferred to the other tickets in #10. The call chain and the selected-point experiment are in [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md).

## Open the workbench on a controlled attempt

`--scenario workbench` runs a scripted attempt that exercises every inspector field: a shell output over the model-visible limit containing `<script>` markup, a failing and a succeeding read in one model turn, and a completion with no usage. Use the default `--scenario read` for the one-read attempt described below.

```bash
PYTHONPATH=live-tracker/src python -m live_tracker.run_scripted --scenario workbench \
  --admission-evidence <admission.json> --source-repository /path/to/prompt-engineering-group-project
```
>
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

## Implemented in #11 versus deferred

- Implemented: the sink contract on the Python loop; durable recorder with contiguous sequences and content-addressed artifacts; reader that ignores only an unterminated final record and raises on corruption; loopback server (`/`, `/static`, `/api/attempts`, events with `after`, confined artifacts, SSE with `Last-Event-ID` resume); minimal TypeScript timeline; the scripted runner; observation-on/off parity test; system-Chrome browser test.
- Implemented in #13: `phase.enter` (module:function source identity) and `state` events from the Python loop, registered source identities with `/api/sources`, the workbench (component map, timeline, inspector with selected-point state and labelled excerpts), the `workbench` scripted scenario and a system-Chrome acceptance test against a Docker attempt (`tests/test_timeline_browser_docker.py`, which keeps its #11 file name).
- Implemented in #17: cursor refusals, catch-up and handoff, client dedupe and gaps, bounded per-connection buffering with slow-consumer disconnect, connection state and lag (see above).
- Implemented in #15: `node.enter`, `node.outcome`, `route.decision` and graph `state` events from `run_attempt_graph`; the LangGraph component entries (model node, tool node, router) with registered source links; `run_scripted --orchestrator langgraph`; the LangGraph Docker parity, browser and overhead checks described above. The sink is no longer refused for `langgraph`.
- Deferred: mutation capture (#16), recording-failure recovery scenarios (#12), legacy recording adapters and playback controls (#14), and provider streaming. Evaluation and report phases are not yet phase events. The report is not yet re-rendered from the log (#14).

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

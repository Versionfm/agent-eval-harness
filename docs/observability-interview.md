# Live inspection and playback design interview

Status: Q29–Q48 confirmed, with the Q48 ceiling amended to USD 0.10 total (ten cents; interpretation of the user’s “0.10 cents” based on the comparison with a two-cent run). The user invoked to-spec after the shared-understanding checkpoint; the first-stage specification is published as [issue #10](https://github.com/Versionfm/agent-eval-harness/issues/10) with `ready-for-agent`. Production implementation remains subsequent work. The user requested that both [extension ideas](OBSERVABILITY_IDEAS.md) be saved and grilled with documentation. Saving the ideas does not confirm the recommendations below.

## Established context

- This is a personal harness-engineering and evaluation learning project.
- Maintain explicit Python and LangGraph implementations for comparison.
- Canonical checks determine functional verdicts; Codex review stays separate.
- Preserve actual observable evidence and distinguish it from unavailable internal model reasoning.
- The first live pair and its exact-artifact Codex reviews are complete.

## Design tree

1. Delivery boundary: event viewer/replay first, or include token streaming in the same milestone?
   - Unblocks streaming contract, partial-response semantics and implementation slices.
2. Viewer authority: observe, or also control attempts?
   - Unblocks run launching, cancellation, breakpoints and lifecycle ownership.
3. Primary learning surface: architecture/state transitions, conversation, or terminal?
   - Unblocks layout, source links, inspection detail and comparison navigation.
4. Meaning of replay: review existing evidence, or execute/resume work?
   - Unblocks recording completeness, playback fidelity and compatibility with historical traces.

Subsequent frontiers will settle storage, event identity/order, lifecycle completeness, observer failure behavior, provider chunks, accounting, comparison overhead, artifact compatibility and acceptance evidence. Do not treat unresolved branches as defaults.

## Round 1: Q29–Q32 — confirmed

### Q29: Delivery boundary

Confirmed: first deliver incremental recording plus live/replay UI; token streaming is the next separate milestone through the same event pipeline.

### Q30: Viewer authority

Confirmed: begin with an observer. Launch attempts with the existing CLI. Playback controls affect playback only; starting/cancelling actual attempts can be a separately designed extension.

### Q31: Primary learning surface

Confirmed: show a component/execution map beside a chronological timeline, with tool/model/diff/state inspection. Make Python stages and LangGraph nodes visibly comparable and connect them to their source functions.

### Q32: Meaning of replay

Confirmed: playback of saved observable evidence, without model calls, tool execution or agent resume. Support existing saved attempts while labeling details they did not capture; richer new recordings can add operation-start, chunk and intermediate-change information.

## User follow-ups

- Q31: The user wants to see the proposed interface and know the implementation languages. A disposable HTML mockup is appropriate before selecting the layout.
- Q32: The viewer must expose report evidence, including which tools were called. Confirmed capability requirement: tool names, arguments, call IDs, outputs, errors, durations and truncation, plus model output/exposed reasoning, usage, final diff, independent checks and separate Codex review. Historical recordings must label information they did not capture.

## Mockup

Artifact: `/home/francisco/Documents/Codex/2026-10-10/d/outputs/harness-viewer-prototype.html`.

Three structurally different layouts share the same saved first-live-pair evidence and are selected with `?variant=A`, `?variant=B` or `?variant=C`:

- A: component map, timeline and inspector in three columns (recommended).
- B: execution path above a guided reading/inspection layout.
- C: two attempt lanes with one shared evidence inspector; event indexes are not causal alignment.

The mockup is plain HTML/CSS/JavaScript, works from one file and makes no provider/tool calls. It displays final attempt totals as final totals, not state at an earlier selected event. It omits repeated full model-request history and excerpts long outputs, with original trace/output links. Node highlights are derived from recorded event types, not claimed recorded graph-node transitions. It is not the production viewer or a live connection.

Automated visual inspection was blocked by the browser policy for local file URLs. Static data/embedded-script checks are separate from visual acceptance; the user selected A as the default and C for comparison in Q34. This choice does not claim automated visual QA.

## Round 2: Q33–Q36 — confirmed

### Q33: Implementation languages

Confirmed: keep recording and the local server in Python; build a small TypeScript browser client with HTML/CSS. Start without a frontend framework unless the chosen UI warrants it. TypeScript can discriminate event payloads by event type. The current throwaway mockup uses JavaScript for easy single-file review.

### Q34: Layout selection

Confirmed: A as the default learning workspace, with C as a later comparison view. The user accepted this layout recommendation.

### Q35: Recording authority

Confirmed: one versioned append-only attempt event log feeding live viewing, recorded playback and final reporting. Preserve the original report/artifact evidence and expose missing or incomplete data explicitly; avoid a separate UI-only event history. Choose serialization/storage details in the next frontier.

### Q36: Code-change visibility

Confirmed: preserve the final canonical candidate patch and capture intermediate repository changes after successful patch or shell tools that may write files. Show the observed post-tool changes with their event association; do not claim continuous observation of every filesystem write. Measure collection overhead separately.

## Round 3: Q37–Q40 — confirmed

### Q37: Observation and recording failure

Confirmed: closing or disconnecting the browser does not stop the attempt. Failure to write mandatory evidence stops further agent work at the next safe boundary, retains available evidence, and marks the recording incomplete. Recording failure is not an agent repair failure; any independently established functional verdict remains a separate fact.

### Q38: Recording storage

Confirmed: append events to a versioned JSONL log in each attempt directory, retaining large payloads, tool outputs and intermediate changes as linked artifacts. Keep existing recordings readable through an explicit legacy adapter; do not rewrite historical evidence or invent unavailable start/chunk events. SQLite can be reconsidered when cross-run querying justifies it.

### Q39: Live delivery

Confirmed: Python serves the viewer on loopback and sends events over server-sent events (SSE), using recorded event identifiers for reconnect/catch-up. Disk evidence is authoritative; the browser connection is replaceable. Confirm ordering, reconnect gaps and slow-consumer semantics after this choice.

### Q40: Changes from failed tools

Confirmed: capture post-tool changes after potentially mutating tools even when their exit/status indicates an error or timeout. A failed shell command can already have changed files. Only compare against a settled task state after the tool/timeout cleanup boundary; do not claim a consistent snapshot while a command can still write. This extends Q36 to failed and timed-out tools as well.

## Round 4: Q41–Q44 — confirmed

### Q41: Event identity and reconnect integrity

Confirmed: identify the attempt and give its events a strictly increasing sequence, with an operation ID connecting start/end/result events. Order by sequence, not wall-clock timestamps. The viewer deduplicates reconnect delivery, catches up from the saved log and shows a gap or incompatible schema explicitly rather than silently skipping it. Timestamps and monotonic elapsed measurements retain their separate display/timing roles.

### Q42: Interrupted recordings

Confirmed: preserve the original bytes and expose the last verified complete prefix. A partial trailing record or an operation start with no recorded end means incomplete evidence; it does not establish successful completion or the repair verdict. Middle corruption is shown as a recording error instead of being silently skipped. Reading an old interrupted recording does not append events, resume an attempt or rerun its tools. Set the precise flush/sync and atomic-artifact protocol in the implementation design against this recovery contract.

### Q43: State and architecture fidelity

Confirmed: record actual Python phase and LangGraph node transitions plus the context size, request/retry counts, elapsed time and spending accounting available at that point. Recorded playback derives the selected-point state from those records; final totals, checks and review stay visibly separate. Historical logs without transitions or intermediate state keep their unavailable/derived labels rather than using final metadata to fabricate earlier state. Model-request and tool-start/end events make waiting versus completion observable in stage one, before provider-token streaming.

### Q44: Verification evidence

Confirmed: validate the viewer using both existing live attempt recordings and controlled/scripted runs of both orchestrators. Check displayed tool/model payloads, report consistency, intermediate changes from successful/failed/timed-out tools, reconnect duplicates/gaps, browser disconnection, recorder failure and interrupted logs. Compare identical scripted inputs with observation enabled/disabled to verify model-visible messages, tool results, candidate changes and canonical verdicts are preserved; measure recording/snapshot overhead separately. A small live demonstration can follow deterministic acceptance without relying on stochastic success as proof of correctness.

## Round 5: Q45–Q48 — confirmed

### Q45: Durability boundary

Confirmed: save and sync an operation-start record before invoking a model or tool; save linked payloads atomically before recording their references; save and sync the operation outcome before advertising it as recorded. Recover the verified prefix after a process crash, and report missing or corrupt evidence explicitly. Filesystem and hardware durability remain environmental prerequisites, not a guarantee inferred from the browser. Batch lightweight display/state notifications between these boundaries and measure sync overhead. Future token chunks need a separate durability policy.

### Q46: Slow observers

Confirmed: keep browser delivery independent of agent execution, with bounded per-connection buffering. Disconnect a slow consumer when its buffer fills and let it reconnect/catch up from the authoritative log. Show connection status and how far the displayed event sequence trails the latest available sequence. Do not silently lose durable events or make tool execution wait for a browser to consume them. Mandatory disk recording remains synchronous at its agreed boundaries.

### Q47: Intermediate snapshot scope and cost

Confirmed: capture text changes and file additions/deletions relative to the starting repository; represent binary changes with metadata rather than embedding binary contents. Apply explicit size/time limits to intermediate captures and label omitted, failed or unsettled captures with their reason. Preserve the existing final canonical candidate collection and its verdict semantics separately. A successful shell exit alone does not prove background writers have stopped; capture only when the tool environment establishes a settled boundary, otherwise record the unavailable observation without claiming a consistent snapshot. Measure recording/snapshot time separately while keeping it inside actual attempt wall time. Numeric limits are calibrated before the paid demonstration, with any intentional omissions visible under the declared recording contract.

### Q48: Live-demonstration budget

Confirmed: after deterministic acceptance, run one fresh matched Python/LangGraph pair against the same task/provider configuration, with a combined estimated-cost ceiling of USD 0.10 total (ten cents) including any required smoke request and existing bounded attempt limits. Keep all failures and accounting, without automatically buying extra attempts to obtain a pleasing result. Use saved/scripted evidence for fault injection. The user accepted this acceptance plan with the lower ceiling; no paid demonstration runs during design preparation; token streaming has a separate later acceptance plan.

## Physical separation — user instruction after Q48

Create `live-tracker/` in this repository for the observation implementation. Keep its recorder, server, browser client, compatibility readers and tests outside `agent_eval_harness/`. Harness event instrumentation is the minimal necessary integration seam; it must not import the browser/server or hand execution ownership to them. Shared recording feeds reporting through that seam rather than copying the current lifecycle into a second runner. See [the folder boundary](../live-tracker/README.md).

## Updated design frontier

Q29–Q48 settle the first-stage viewer decisions. The [concrete design](../live-tracker/docs/DESIGN.md) and [learning sequence](../live-tracker/docs/LEARNING_PLAN.md) summarize the accepted scope, physical separation and verification. The user proceeded to specification through to-spec; see the [specification](../live-tracker/docs/SPEC.md). Production implementation remains subsequent work. Numeric snapshot limits and exact API details are measured/specification work under the accepted limits policy. Provider-token chunk assembly, interrupted streams, retries and accounting are the separate second milestone, not silently resolved by the first-stage design.

## Glossary and ADR status

The glossary distinguishes Live viewer, Recorded playback, Attempt event log, Intermediate candidate diff, Incomplete recording, Attempt operation and Recorded attempt state. ADR 0004 records the observer boundary; ADR 0005 records shared history and the mandatory recording boundary. Decisions through Q48 and the folder separation are accepted. These documents describe planned extensions, not implemented viewer behavior.

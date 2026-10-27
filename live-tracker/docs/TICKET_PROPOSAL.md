# Live tracker ticket proposal

Status: user-approved and published as issues #11–#18; bodies, labels and 12 native dependencies verified. No implementation started. See the [published ticket index](TICKETS.md). Parent: [specification #10](https://github.com/Versionfm/agent-eval-harness/issues/10).

The first slice includes the smallest compatible event-boundary prefactor and a working path through execution, storage, delivery and UI. No separate backend-only or frontend-only foundation ticket is needed. The implementation base must contain the existing harness implementation; merging its original PR is outside this breakdown.

All tickets keep tracker implementation separate, use existing domain vocabulary and accepted observation boundaries, and include a learning walkthrough/repeatable experiment. Once implementation is authorized, each ticket is assigned to a Luna subagent with xhigh effort; the root coordinates integration/review.

## T1: Follow one scripted Python attempt in the browser

**Blocked by:** None (can start immediately on the existing harness base)

**What it delivers:** Run a small scripted Python attempt through the existing lifecycle and watch its model/read-tool starts and outcomes appear in a minimal browser timeline, backed by saved evidence.

### Acceptance criteria

- [ ] Keep all recorder/server/client implementation in the dedicated live-tracker component; introduce only an optional injected event sink at the existing attempt entry point and shared lifecycle. Existing unobserved callers stay compatible; no browser/server imports or duplicate runner enter the harness.
- [ ] Demonstrate a finite scripted model → repository read tool → model completion attempt in the actual task environment, with its independent canonical evaluation retained. This slice requires no paid model request or successful repair.
- [ ] Persist one versioned immutable JSONL history with attempt identity, contiguous sequence, operation identities, UTC timestamps and monotonic elapsed time. Save/sync starts before dispatch and outcomes before delivery; save linked payloads atomically before referencing them.
- [ ] Show the running attempt and its model/tool starts and outcomes in a minimal TypeScript client served by a Python loopback server, including a basic SSE subscription. Evidence retrieval is confined to registered roots and content is rendered safely.
- [ ] The result and basic final report consume the same history/artifacts; final collection does not rewrite the log. Retain recorded tool/model payloads and canonical final artifacts for the supported scenario.
- [ ] Verify controlled observation-on/off equivalence for model-visible messages/results, candidate and canonical verdict with timing headroom. No recording failure permits a subsequent operation; comprehensive recovery scenarios follow in ticket 2.
- [ ] Provide one-command reproduction, explain the event boundary and show what is implemented versus deferred. The original harness implementation must be present in the base; do not merge its PR as part of this ticket.

## T2: Inspect interrupted attempts and stop safely on recording failure

**Blocked by:** T1

**What it delivers:** Open useful evidence from an interrupted or damaged attempt and see recording errors honestly, while mandatory recorder failure prevents further agent work.

### Acceptance criteria

- [ ] Expose the verified complete prefix of a torn trailing record without rewriting source bytes; show incomplete recording and unresolved operations through the public reader, server and browser.
- [ ] Validate schema, attempt identity, sequence and linked artifact size/digest. Show middle corruption, missing/damaged artifacts, gaps, conflicting event identities and unsupported schemas explicitly; do not skip them silently.
- [ ] Fault-inject start, artifact, outcome write/sync failures through the recorder boundary. Verify the next model/tool operation does not run, safe cleanup occurs and available candidate/evaluation facts remain separate.
- [ ] When storage cannot persist a failure marker, return the available error to the caller and leave the saved prefix incomplete; do not claim a marker was saved.
- [ ] Keep recording completeness, termination reason and functional verdict distinct in the reader/UI/report. Reading never appends, resumes or executes tools.
- [ ] Exercise public behavior with scripted attempts and temporary evidence, including the durability ordering established in ticket 1. Document supported process-crash recovery conditions without claiming universal power-loss guarantees.
- [ ] Provide a repeatable interrupted-write and recorder-failure learning demonstration with no provider requests.

## T3: Inspect Python phases, model calls and tool evidence in the workbench

**Blocked by:** T1

**What it delivers:** Use layout A to connect actual Python execution phases with chronological events and inspect detailed model/tool evidence and state at the selected point.

### Acceptance criteria

- [ ] Build the component map, timeline and inspector as the primary production layout, using a small TypeScript/HTML/CSS client. The prototype is design evidence rather than production code to promote wholesale.
- [ ] Record actual Python phase transitions and source-function identities where execution occurs; component selection navigates to the registered source function and explains its responsibility.
- [ ] Inspect model content, provider-exposed reasoning, requests/retries and tool names, arguments, call IDs, status, errors and duration. Do not imply access to hidden reasoning.
- [ ] Display exact model-visible output separately from retained full output; label truncation and presentation excerpts and provide bounded artifact access to the full evidence.
- [ ] Derive selected-point context size, counts, elapsed time, budgets, usage and available estimated/reported accounting only from records available by that point. Final totals/checks/reviews remain later facts.
- [ ] Keep observer data out of the model conversation and preserve provider continuation fields. Match displayed evidence to retained event/artifact identities.
- [ ] Exercise real browser navigation and evidence inspection on controlled attempts, including long/untrusted text, missing fields and legible layouts. Static scripts or endpoint health alone do not establish browser acceptance.
- [ ] Provide a walkthrough of the model/tool/phase call chain and an experiment demonstrating selected-point versus final state.

## T4: Play back new and legacy attempts with matching report evidence

**Blocked by:** T2, T3

**What it delivers:** Open a completed or interrupted recording, step or play through it, and compare its evidence with the final report—including the original live pair without rewriting it.

### Acceptance criteria

- [ ] Provide play/pause, speed, stepping and event selection/scrubbing, distinguishing recorded playback from live following.
- [ ] Read the original first-live-pair recordings through an explicit legacy adapter. Preserve original bytes; label unavailable starts/nodes/snapshots and derived highlights instead of fabricating telemetry.
- [ ] Carry verified-prefix and recording-error semantics from ticket 2 into playback. Playback never appends, resumes, invokes providers or executes repository tools; verify with those boundaries disabled.
- [ ] Show final canonical candidate patch, checks, termination, functional verdict and pending/completed Codex review independently of historical selected-point state.
- [ ] Generate new final report projections from the authoritative history and linked artifacts; assert viewer/report parity for response/reasoning, tool arguments/results, accounting and final evidence.
- [ ] Exercise real browser playback controls against saved new, legacy and interrupted fixtures. All excerpt/missing/derived labels and artifact links remain truthful.
- [ ] Provide a repeatable zero-cost inspection demonstration using preserved live evidence, and explain why playback is different from agent resumption.

## T5: Follow actual LangGraph nodes through the same workbench

**Blocked by:** T3

**What it delivers:** Run the LangGraph counterpart and inspect its actual model/tool node transitions beside the Python component meanings through the same recorder and workbench.

### Acceptance criteria

- [ ] Use the existing LangGraph workflow and the same injected event boundary; do not introduce a second runner, prebuilt agent factory or LangGraph-only UI history.
- [ ] Record actual node entry/outcome, stage/source identity and relevant selected-point state. Separate graph steps from model calls; unresolved node operations are not rendered as completed.
- [ ] The shared workbench displays recorded LangGraph transitions, model/tool evidence and source links rather than infer them from final totals or generic event types.
- [ ] Run actual Docker-backed scripted repair, tool-error recovery and budget-stop scenarios for both orchestrators, asserting the established model-visible continuation, ordered tool and candidate/verdict parity.
- [ ] Check LangGraph observation enabled/disabled through the same high-level attempt seam. Preserve its existing graph-step semantics and budgets; expose observation overhead separately.
- [ ] Provide a source walkthrough connecting graph state, nodes, reducers and routing to the explicit Python responsibilities, with a repeatable no-provider experiment. The later comparison desk is not required.

## T6: Inspect repository changes after successful and failed tools

**Blocked by:** T2, T3

**What it delivers:** Select a potentially mutating tool event and see the bounded repository changes it left, including failed/timed-out operations, without confusing them with the final evaluated patch.

### Acceptance criteria

- [ ] Capture text changes and additions/deletions relative to the attempt starting state at an established settled tool boundary, and associate the observation with the operation identity.
- [ ] Include successful, failed and timed-out mutations; binary changes show metadata rather than embedded contents.
- [ ] A shell return alone does not prove background writers are settled. Show an unavailable/unsettled capture when settlement cannot be established; do not change tool semantics by killing extra work to manufacture a snapshot.
- [ ] Configure positive capture time/size and preview limits, calibrate and record effective values, and show intentional omissions or collection failures with reasons in the inspector.
- [ ] Use the artifact-integrity and mandatory recording failure behavior from ticket 2. Distinguish declared bounded omissions from failure to save mandatory evidence.
- [ ] Preserve final canonical candidate collection and verdict semantics independently. Verify mutations through actual repository effects and observation-on/off candidate/check parity.
- [ ] Measure capture/recording overhead separately while retaining actual attempt wall time. Provide a repeatable partial-mutation and limit/settlement demonstration without provider requests.

## T7: Reconnect and catch up without slowing the attempt

**Blocked by:** T1

**What it delivers:** Close, reconnect or lag the live viewer while the attempt continues, with disk-backed catch-up, visible connection status and bounded delivery memory.

### Acceptance criteria

- [ ] Bind SSE event identifiers/cursors to attempt and sequence. Catch up from disk without a gap during the history/live handoff while recording continues.
- [ ] Deduplicate reconnect deliveries and expose gaps, conflicting identity/schema and incompatible cursors rather than silently manufacturing continuity.
- [ ] Bound per-connection buffering; disconnect a slow consumer when full and permit disk-backed reconnection. Browser consumption never blocks model/tool work.
- [ ] Show connection state and lag against the latest available sequence in the browser. Closing/disconnecting the viewer does not stop the attempt.
- [ ] Test the public HTTP/SSE boundary and actual browser disconnection/reconnection, including continuing recorded activity and a slow consumer. Synchronous mandatory disk boundaries remain independent.
- [ ] Provide a repeatable no-provider demonstration of reconnect, duplicate delivery and a deliberately slow observer.

## T8: Demonstrate both trackers under the ten-cent shared ceiling

**Blocked by:** T4, T5, T6, T7

**What it delivers:** Launch one fresh matched Python/LangGraph pair through the existing coordinator, observe and replay both attempts, and retain acceptance/accounting evidence under a combined ten-cent estimated ceiling.

### Acceptance criteria

- [ ] Integrate tracker observation into the existing CLI/matched coordinator without duplicating execution or moving UI code into the harness; use the established event sink for both attempts.
- [ ] Before paid execution, pass required deterministic, actual Docker and browser checks covering both orchestrators, playback/report fidelity, intermediate changes, reconnect/lag, recorder failure and interrupted evidence. Docker integration acceptance is not satisfied by skipped tests.
- [ ] Run recording-failure and interrupted-node cases through both orchestrators, consolidating the earlier slice evidence. Preserve controlled model-visible/candidate/verdict parity and report actual deadline/overhead effects honestly.
- [ ] Set the combined estimated budget to USD 0.10 including any required smoke request, both attempts, retries and pending reservations, with compatible per-stage limits. Offline tests prove a request that cannot fit is refused.
- [ ] Verify current provider pricing/configuration at preflight, then run at most one fresh matched pair with identical task/model settings and bounded attempts. Retain budget stops and failures; do not buy replacement attempts.
- [ ] Retain requested/observed model identities, effective budgets/settings, pricing provenance, usage, estimated versus available billed cost, overhead measurements, canonical outcomes and separate Codex reviews.
- [ ] Show the real live workbench and saved playback of both attempts, with no fabricated telemetry. Repair success is an observed outcome, not proof of viewer correctness or an orchestrator ranking.
- [ ] Provide reproducible commands and a learning walkthrough labeling implemented, deterministic-tested, browser-verified and live-demonstrated behavior separately. Keep token streaming and comparison layout C for later work.

## Dependency frontier

Initially T1 is ready. After T1, T2, T3 and T7 can proceed independently. T4 needs the recovery reader from T2 and workbench from T3; T5 needs the workbench; T6 needs recovery/artifact-failure behavior and the inspector. T8 waits for completed playback/report, LangGraph, mutation and reconnect work. Transitive edges are omitted.

## Publication completed

Published one GitHub issue per approved ticket in dependency order with `ready-for-agent`, native blocking links and explicit blocker references. Parent issue #10 was not edited, closed or given native sub-issues. Publishing does not authorize implementation.

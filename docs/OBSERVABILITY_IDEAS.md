# Live inspection and recorded playback

Saved on 10 October 2026 at the user's request. These are planned extensions to the completed first measurement milestone. Q29–Q48 confirm the delivery order, observer authority, architecture/timeline learning surface, playback meaning, Python/TypeScript languages, layout A with comparison C, one shared event history, and intermediate diffs; JSONL/artifact storage, local SSE delivery and observer/recorder failure separation are also confirmed; event identity/order, interrupted-record recovery, actual state transitions and verification requirements are confirmed. Operation-boundary durability, bounded slow-consumer handling and explicit intermediate snapshot limits are accepted. The live-demonstration ceiling is USD 0.10 total (ten cents), interpreting the user’s wording using their two-cent-run comparison. The [design interview](observability-interview.md) records the accepted decisions and shared-understanding checkpoint.

## Idea 1: Local interface for live viewing and replay

Build a readable interface that follows an attempt as it executes and can later play back its recorded observable events. Use the same evidence for both explicit Python orchestration and LangGraph, preserving separate functional verdicts, termination reasons and Codex reviews.

Candidate views include an activity timeline, current execution stage or graph node, model responses and exposed reasoning, tool arguments/results/errors, context and budget information, code changes and independent checks. Playback could provide play/pause, speed and event-by-event stepping without new provider requests or tool execution. It is distinct from resuming an agent or rerunning a task.

The current harness already records observable model responses, tool calls/results, event IDs, timestamps and final artifacts. In `agent_eval_harness/persistence.py`, recording appends to an in-memory trace; artifact collection writes `trace.jsonl` at the end. Model and tool events are recorded after the operation returns. A live interface therefore needs incremental recording and explicit operation-start events. Existing recordings do not contain token arrival timing, continuous shell output or intermediate file snapshots; playback must not invent those details.

Learning value: event lifecycles, persistence, observation boundaries, failure handling and evidence shared across orchestrators. Trade-offs to resolve: control authority, viewer complexity, logging overhead, record completeness and behavior when observation or storage fails.

## Idea 2: Stream model output into the same interface and recording

Extend the provider boundary so observable output can appear as it arrives, including provider-exposed reasoning where available. Preserve response assembly, tool-call identifiers/arguments, finish reasons, continuation fields, accounting, deadlines and retries. A partially received tool call must not be treated as an executable complete call.

Learning value: provider streaming, partial responses, cancellation and the distinction between graph progress and model-token progress. Trade-offs to resolve: chunk granularity, interrupted streams, evidence retention and the amount of provider-specific detail exposed by the shared model interface.

Candidate implementation order: establish durable event recording and live/replay inspection first, then add provider token streaming. The user confirmed this delivery order in Q29. The first stage is an observer launched alongside CLI attempts (Q30), using an architecture map with a timeline/inspector (Q31), with evidence playback rather than execution/resume (Q32). A disposable design mockup precedes production implementation.

## Current evidence to inspect

The first real pair is preserved outside Git at `../evidence/live-first-2026-10-10/` (next to the repository). Python passed nine canonical checks after a one-line repair, then stopped at its output limit. LangGraph passed six checks and reached its call limit without saving a patch. These are useful playback examples, not orchestrator rankings.

The first UI could teach directly from those records while making their recording limits visible. Future runs could provide richer observation through the same attempt/evaluator boundaries.

## Confirmed implementation direction

Python owns recording and the local server; a small TypeScript/HTML/CSS client presents the evidence, initially without a frontend framework. Layout A is the default learning workspace and layout C is the comparison view. One versioned append-only attempt event history feeds the viewer, playback and final report. Preserve final candidate patches and add observed intermediate changes after potentially mutating tools; this includes tools that fail or time out after execution has been stopped. Browser disconnects do not stop attempts; mandatory recording failures stop further work at a safe boundary and mark the evidence incomplete. JSONL events and linked artifacts are the agreed storage, with local SSE for live delivery.

Recorded events use an attempt identity and strictly increasing sequence, with operation identities linking start and outcome. Reconnect deduplicates against that history and exposes gaps. Interrupted logs preserve their original bytes and expose their verified prefix; unresolved operations do not establish success. New recordings capture actual Python phases/LangGraph nodes and selected-point state; old logs retain unavailable/derived labels. Controlled tests must establish evidence fidelity and observation-on/off parity before a small paid demonstration. These are confirmed requirements through Q48, not completed implementation.

The observation implementation has its own [live-tracker folder](../live-tracker/README.md); only narrow event-emission integration belongs in the harness. The [first-stage design](../live-tracker/docs/DESIGN.md) and [learning sequence](../live-tracker/docs/LEARNING_PLAN.md) were accepted through the user’s to-spec invocation; the [first-stage specification](https://github.com/Versionfm/agent-eval-harness/issues/10) is published with `ready-for-agent`. No production tracker code or new provider calls have been added.

# First-stage live tracker design

Status: Q29–Q48 and the dedicated-folder boundary accepted. The user invoked to-spec after reviewing the shared-understanding checkpoint; the specification is published as [issue #10](https://github.com/Versionfm/agent-eval-harness/issues/10) with `ready-for-agent`. This is not a production implementation or approved implementation ticket breakdown. The budget wording is interpreted as **USD 0.10 total (ten cents)**, based on the user's comparison with a two-cent run.

## Purpose and delivery boundary

Make harness composition and actual execution inspectable while learning explicit Python orchestration beside LangGraph. First deliver durable incremental recording, a local observer and recorded playback. Provider-token streaming follows as a separate milestone; stage one displays model results after response completion and does not promise continuous terminal output.

The CLI launches attempts. The viewer observes them; play/pause, speed and stepping control saved evidence playback. Closing the browser has no effect on attempt execution.

## Ownership and code placement

All tracker implementation lives under `live-tracker/`: the Python `src/live_tracker/` package, TypeScript/HTML/CSS `web/`, and tracker tests. Begin without a frontend framework. The existing harness retains its lifecycle, tools, model adapter, independent checks and budget decisions. A narrow injected event sink carries events out of those execution stages; the harness does not import the viewer server or browser code.

The recorder is separate code but participates synchronously in evidence boundaries. Failure to save mandatory evidence stops new agent work at the next safe boundary. This is distinct from a slow browser, a repair failure or an independently established functional verdict. Do not fork or duplicate the Python/LangGraph loops to add observation.

## Learning interface

Layout A is the default: component map, chronological timeline and evidence inspector. Show actual recorded Python phases and LangGraph node transitions with links to their source functions. Layout C is a later comparison view; two event indexes do not establish causal alignment or equivalent steps.

The inspector exposes the same evidence as reporting: tool names, arguments, IDs, model-visible results, retained full outputs, errors, durations and truncation; model responses and provider-exposed reasoning; context size, usage, available accounting and budgets; intermediate changes; final candidate patch, canonical checks and separate Codex review. Do not claim access to all internal model reasoning.

Selected-point state is supported by events recorded up to that point. Final totals, checks and reviews are separate later facts. Legacy recordings explicitly identify missing or derived data. Large evidence can be opened through linked artifacts, with any displayed excerpt labeled.

## One history, three consumers

Record one versioned append-only JSONL history per attempt with linked large payloads. The live viewer, playback and report consume this authority. Each event has an attempt identity, strictly increasing sequence, type and time; an operation identity connects starts and outcomes. Sequence orders events; wall-clock timestamps and monotonic elapsed values serve distinct timing purposes.

Save and sync operation starts before invoking a model/tool. Save linked artifacts atomically before referencing them, then save and sync outcomes before advertising them as recorded. Lightweight state/display notifications may be batched between these boundaries. Measure durability overhead; filesystem/hardware behavior constrains crash durability. Future token chunks need their own policy.

Readers preserve source bytes. An interrupted trailing record leaves a verified complete prefix; missing operation outcomes remain unresolved. Middle corruption, missing artifacts, gaps and unsupported schemas are explicit recording errors. Opening evidence never appends, resumes an attempt or reruns tools. A legacy adapter reads original completed logs without rewriting or inventing their missing starts/transitions.

## Live delivery

A Python loopback server serves the compiled browser client and SSE events. Reconnect catches up from the saved log; the client deduplicates sequence IDs and exposes gaps. Per-connection buffering is bounded. Disconnect a consumer that cannot keep up and recover from disk; show connection status and lag. Browser consumption does not block model/tool execution. Disk recording keeps its synchronous mandatory boundaries.

## Observed code changes

After potentially mutating tools, capture changes relative to the starting repository for successful, failed and timed-out outcomes once execution is settled. Include text diffs and file additions/deletions; binary changes receive metadata rather than embedded contents. A successful shell exit does not prove background writers are stopped: if the environment cannot establish a settled boundary, record the observation as unavailable rather than claim a consistent snapshot.

Intermediate captures have explicit size/time limits calibrated during deterministic work. Label intentional omissions, unsettled state and collection failures; distinguish allowed bounded observations from unexpected mandatory recording failures. Preserve final canonical candidate collection and verdict semantics. Collection overhead is measured separately and remains inside actual attempt wall time; observation does not create extra execution time.

## Acceptance evidence

Use original live recordings plus controlled/scripted attempts of both orchestrators. Verify tool/model details and report consistency; successful/failed/timed-out mutation evidence; ordering, reconnect duplicate/gap handling, lag and browser closure; recorder write failures, interrupted logs and corrupt/missing evidence. Legacy readers preserve original bytes and honest unavailable labels.

With identical scripted inputs, observation enabled/disabled must preserve model-visible messages, tool results, candidate changes and canonical verdicts. Record observation and snapshot overhead independently. Exercise the real browser interface and both execution integrations; renderer snapshots or endpoint reachability alone do not establish these behaviors.

After deterministic acceptance, demonstrate one fresh matched Python/LangGraph pair under a **combined USD 0.10 estimated-cost ceiling**, including any required provider smoke request, with identical task/model configuration and bounded attempts. Include pending-request estimates and retries in shared cost admission; if the remaining estimate cannot accommodate a request, stop rather than overspend the agreed estimate. Record pricing, estimated/available billed usage and every failure. Do not automatically purchase extra attempts to improve outcomes. This is an estimated-cost guard, not a claim that the provider's eventual bill is precisely known in advance. No paid calls run during this design preparation.

## Separate next milestone

Provider-token streaming will reuse the event pipeline but requires its own design of chunks, response/tool-call assembly, exposed reasoning, interrupted streams, retries, deadlines and accounting. Partially received tool arguments are never executable complete calls. Stage one does not silently settle those contracts.

## Confirmation checkpoint

The user proceeded to specification through to-spec. See the [specification](SPEC.md) for the accepted integration and acceptance contracts. Implementation tickets and production work remain subsequent steps; numeric capture limits are calibrated under the accepted policy.

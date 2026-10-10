## Problem Statement

The learner can inspect a completed harness report but cannot follow an attempt as it runs. Current traces are accumulated in memory and saved at final artifact collection, and model/tool events describe completed operations. They do not establish operation starts, actual Python phase or LangGraph node transitions, selected-point state or intermediate repository changes.

This makes it difficult to understand what each harness component owns, what the model requested, which tools executed, what changed and where execution is waiting. A crash can also leave less useful evidence than a completed report. The learner wants live observation and recorded playback without mixing viewer code into the harness, changing agent behavior or paying for reruns merely to inspect evidence.

## Solution

Build a dedicated live-tracker component with a Python incremental recorder and local server, plus a small TypeScript/HTML/CSS browser interface. Use the accepted component workbench layout: execution map, chronological timeline and evidence inspector. Show the explicit Python implementation and the LangGraph counterpart through the same evidence contract, while retaining their actual distinct transitions.

CLI-launched attempts publish observable events through a narrow injected sink. One versioned append-only attempt event log and its linked artifacts feed live viewing, recorded playback and final reporting. Playback uses saved evidence without model calls, tools or agent resumption. The interface exposes the report's tool/model evidence, selected-point state, intermediate changes and separate final patch/check/review results, with honest labels for historical omissions and incomplete recordings.

Deliver recording and live/replay inspection first. Provider-token streaming and the later comparison layout are separate extensions. After deterministic and browser acceptance, demonstrate one fresh matched Python/LangGraph pair under a combined USD 0.10 estimated-cost ceiling, including any necessary provider smoke request.

## User Stories

1. As a learner, I want the viewer code grouped separately from harness code, so that I can understand each component's purpose and dependencies.
2. As a learner, I want a component map beside the attempt timeline, so that I can connect execution activity with the harness architecture.
3. As a learner, I want actual Python phase transitions displayed, so that I can follow the explicit loop's control flow.
4. As a learner, I want actual LangGraph node transitions displayed, so that I can see what the graph executes behind the scenes.
5. As a learner, I want source-function links for components and transitions, so that I can inspect the code responsible for an event.
6. As a learner, I want the two orchestrators to share evidence meanings, so that I can compare composition without confusing graph steps with model calls.
7. As an observer, I want model and tool starts shown before their outcomes, so that I can distinguish waiting from completed work.
8. As an observer, I want each operation's start and outcome linked, so that I can follow its lifecycle through interleaved events.
9. As an observer, I want events ordered by sequence, so that clock changes do not reorder recorded activity.
10. As an observer, I want timestamps and elapsed durations explained separately, so that I can interpret timing correctly.
11. As an observer, I want tool names and call identifiers visible, so that I know exactly which tool was requested and executed.
12. As an observer, I want tool arguments inspectable, so that I understand the action taken on the task repository.
13. As an observer, I want tool outcomes and errors visible, so that I can understand unsuccessful actions and recovery.
14. As an observer, I want tool durations visible when recorded, so that I can identify slow operations.
15. As an observer, I want model-visible tool output separated from retained full output, so that I know what information the model received.
16. As an observer, I want truncation and display excerpts labeled, so that a shortened presentation is not mistaken for complete evidence.
17. As an observer, I want recorded model responses inspectable, so that I can understand their explanations and requested actions.
18. As an observer, I want provider-exposed reasoning inspectable when available, so that I can review observable reasoning without assuming hidden thinking is accessible.
19. As an observer, I want model-request and retry evidence visible, so that failed and repeated requests remain part of the attempt history.
20. As an observer, I want context size and request counts at the selected point, so that I can understand how the attempt approaches its limits.
21. As an observer, I want available usage, accounting and budgets at the selected point, so that I can relate activity to resource consumption.
22. As an observer, I want estimated cost, reported charges and unavailable accounting distinguished, so that the display does not invent financial precision.
23. As an observer, I want final totals separated from earlier state, so that playback does not imply information was available before it was recorded.
24. As a learner, I want intermediate text changes linked to mutating tools, so that I can see how the candidate develops.
25. As a learner, I want additions and deletions represented, so that intermediate evidence is not restricted to modifications of existing files.
26. As a learner, I want binary changes represented by metadata, so that their presence is visible without overwhelming the inspector.
27. As a learner, I want changes captured after tools that fail or time out, so that partial mutations do not disappear behind an error status.
28. As a learner, I want unsettled or omitted observations labeled, so that I do not mistake an incomplete snapshot for a consistent repository state.
29. As an evaluator, I want the final canonical candidate patch retained separately, so that intermediate observations do not redefine the evaluated repair.
30. As an evaluator, I want canonical checks and functional verdicts visible, so that agent-declared completion is not mistaken for repair success.
31. As a reviewer, I want termination reason, recording completeness and Codex review separated, so that different outcomes remain independently assessable.
32. As a reviewer, I want the viewer and final report to use the same evidence, so that their explanations do not diverge.
33. As a reader, I want a clean, legible interface with expandable detail, so that long tool output does not obscure the attempt's structure.
34. As a reader, I want artifact links to retrieve the retained evidence, so that I can inspect more than the inline preview.
35. As a reader, I want untrusted response and tool text rendered as content, so that inspecting evidence does not execute it in the browser.
36. As a playback user, I want play, pause, speed, stepping and event selection, so that I can study a saved attempt at my own pace.
37. As a playback user, I want playback to make no model or tool calls, so that reviewing an attempt neither spends money nor changes a repository.
38. As a playback user, I want existing first-live-pair recordings readable, so that I can learn from evidence already collected.
39. As a playback user, I want unavailable or derived legacy fields identified, so that the viewer does not invent historical starts, transitions or snapshots.
40. As a playback user, I want original recording bytes preserved, so that opening evidence does not rewrite its history.
41. As an observer, I want to close the browser without stopping the attempt, so that observation is independent of execution.
42. As an observer, I want reconnect to catch up from disk, so that a temporary disconnection does not lose recorded work.
43. As an observer, I want duplicate delivery deduplicated, so that reconnect does not display the same event twice.
44. As an observer, I want gaps and unsupported schemas made explicit, so that incomplete evidence is not silently accepted as complete.
45. As an observer, I want connection status and viewing lag visible, so that I know whether the screen is current.
46. As an operator, I want slow browsers handled with bounded buffering, so that observation does not block execution or consume unbounded memory.
47. As an operator, I want operation starts saved before execution, so that a crash can still establish which action was about to run.
48. As an operator, I want linked evidence saved before its event reference is published, so that the viewer does not advertise artifacts that were never saved.
49. As an operator, I want recorder failures to stop new agent work at a safe boundary, so that execution does not continue silently without mandatory evidence.
50. As a reader, I want the verified prefix of an interrupted recording inspectable, so that useful evidence survives an incomplete final write.
51. As a reader, I want unresolved operations to remain unresolved, so that missing outcomes are not interpreted as success.
52. As a reader, I want middle corruption and missing required artifacts reported, so that broken evidence is not silently skipped.
53. As an experimenter, I want observation-on/off parity checks, so that the tracker does not change model-visible messages, tool results, candidate changes or canonical verdicts under controlled inputs.
54. As an experimenter, I want recording and snapshot overhead measured separately, so that I can explain the cost of observation while retaining actual attempt wall time.
55. As an experimenter, I want scripted fault scenarios, so that verifying recovery and delivery does not require paid model requests.
56. As an experimenter, I want one bounded fresh live pair after deterministic acceptance, so that I can inspect the real integration within a ten-cent estimated budget.
57. As an experimenter, I want unsuccessful live outcomes retained without automatic extra attempts, so that the demonstration remains honest and spending stays bounded.
58. As a learner, I want a component walkthrough and repeatable experiment per implementation slice, so that I learn the design rather than merely receive working software.

## Implementation Decisions

- Keep the recorder, evidence readers, legacy adapter, local server, browser client and tracker tests in the dedicated live-tracker component. The harness continues to own both orchestrators, model/tool execution, budgets, task environments, candidate collection and independent evaluation. Do not duplicate the attempt runner or move browser/server code into the harness.
- Use a Python observation package and a small TypeScript client with HTML/CSS, initially without a frontend framework. Serve compiled client assets locally; playback and the installed viewer must not require a runtime CDN or provider access.
- Extend the existing high-level `attempt_and_evaluate` entry point with an optional injected observation/event sink. Existing callers remain valid. CLI composition supplies the recorder; actual stages publish events through this one integration boundary. The harness must not depend on server/browser imports. Thread this boundary through the existing shared model/tool lifecycle and actual graph transitions rather than introducing parallel execution paths.
- The accepted seam expectations are controlled observation-on/off parity and one authoritative history, confirmed in Q35, Q43 and Q44 and the folder-separation decision. Use the same high-level attempt entry point for both orchestrators; transport and reader tests complement it without replacing attempt-level acceptance.
- Preserve existing no-tracker behavior for callers that do not opt in. An observed attempt uses one authoritative event history; its in-memory result and final report are projections of that history and associated final artifacts. Do not maintain independently ordered UI evidence or overwrite the append-only history during final artifact collection.
- Define a versioned event envelope carrying schema identity/version, attempt identity, contiguous sequence beginning at one, event type, UTC timestamp and monotonic elapsed measurement. Operation records carry an operation identity; nested operations can refer to their parent. Provider tool-call IDs remain separate identifiers. A single per-attempt publisher owns ordering, and committed events are immutable.
- Record attempt lifecycle, actual Python phase and LangGraph node transitions, model-request start/outcome, tool start/outcome, provider retries, selected-point context/budget/accounting state, intermediate-capture status and final artifact/check availability. Preserve error and termination information. A graph step is not a model-call count. Completion and final review are not inferred from the model's prose.
- Retain model response content, required provider continuation fields, exposed reasoning, tool arguments, full retained results and exact model-visible results without adding observer text to the model conversation. Large payloads are linked artifacts with relative identities, byte counts and content digests; any preview is explicitly labeled. Exclude credentials and authorization headers from all recorded evidence.
- Use versioned append-only JSONL with linked artifacts per attempt, outside task-repository control and outside tracked source. New recording schemas have an explicit reader compatibility policy. Historical trace formats are read through an adapter, preserving original bytes and labeling missing or derived fields rather than manufacturing new events.
- Save and sync operation starts before invoking a model/tool. Write linked payloads atomically and establish their durable availability before committing referencing events. Save and sync outcomes before advertising them as recorded. Lightweight state notifications may be batched between these boundaries. Measure overhead and document the supported filesystem/process-crash recovery conditions; do not claim universal protection against hardware or power failures.
- A failed mandatory recording boundary prevents the next model/tool operation and initiates safe cleanup. Preserve whatever evidence remains available and surface recording failure independently of the functional verdict. If storage itself cannot accept a failure marker, do not claim that marker was saved: the reader detects the incomplete prefix, while the caller receives the available error status.
- Recovery validates schema, attempt identity, sequence, artifact integrity and complete records. A torn final record leaves a readable verified prefix and an incomplete status. An unmatched start leaves an unresolved operation. Middle corruption, conflicting duplicate identities, sequence gaps or missing required artifacts produce visible errors rather than silent skipping. Reading never appends, executes tools or resumes an attempt.
- Serve registered attempt evidence and the compiled interface on loopback. Provide an attempt summary, ordered event history/catch-up, bounded artifact retrieval and an SSE subscription. Serve only registered evidence/source resources; resolve artifact references within their authorized roots. Render evidence text safely and keep the interface observational.
- SSE event identifiers bind the attempt and sequence. Catch up from the saved log on reconnect, reject an incompatible cursor and deduplicate previously displayed events. A history/live handoff must not lose committed events. The client shows explicit gaps, connection state and available sequence lag rather than filling missing evidence with assumptions.
- Bound each connection's delivery buffer. Disconnect a slow consumer when it fills and reconnect from authoritative disk evidence. Browser disconnection or slow consumption never cancels the attempt and never blocks model/tool execution; synchronous mandatory disk recording retains its separate role.
- Build layout A as the first-stage component workbench: map, timeline and inspector. Link actual recorded stages to their source functions and explain component responsibilities. Model/tool starts make waiting observable; model content appears after completed non-streaming responses in this stage. The throwaway prototype establishes layout direction, not production architecture or complete telemetry.
- Provide saved-evidence play/pause, speed, step and scrub/select controls. Live following and historical selection remain distinguishable. Derive selected-point state from available events at or before selection; present final totals, final canonical checks and later Codex reviews as separate facts. Never substitute final metadata for missing earlier state.
- Preserve report evidence parity: tool identifiers/arguments, response and exposed reasoning, model-visible versus full output, errors, durations, truncation, usage and available cost, candidate patch, checks and separate review. Viewer and report resolve the same event/artifact identities. Available, missing, incomplete, derived and excerpted evidence have distinct labels.
- Capture intermediate changes relative to the attempt's starting repository after potentially mutating tools, including successful, failed and timed-out outcomes. Include text changes and additions/deletions; retain binary-change metadata rather than binary contents. Keep final canonical candidate collection and evaluation semantics independent of these observations.
- A returned shell command does not by itself establish that background writers are settled. Use an established tool/environment settlement boundary for a consistent capture; otherwise record an unavailable/unsettled observation. Do not kill additional background work merely to manufacture a snapshot if that would change existing agent/tool behavior.
- Configure explicit positive capture time/size limits and preview limits; calibrate and record their numeric values during deterministic acceptance before the paid demonstration. Report bounded omissions, unsettled state and capture errors with reasons. Intentional omissions allowed by the declared recording contract differ from unexpected inability to save mandatory evidence. Preserve final canonical collection limits and verdict semantics.
- Measure recording, synchronization, delivery and snapshot overhead separately while retaining actual attempt wall time. Do not extend existing deadlines automatically to hide observation costs. Parity comparisons use controlled inputs with sufficient timing headroom; observed deadline changes and overhead are reported honestly.
- Reuse the existing matched-comparison coordinator and shared spend ledger for one fresh Python/LangGraph pair after deterministic acceptance. Apply a combined USD 0.10 estimated ceiling covering smoke, both attempts, retries and pending request reservations. Configure compatible per-stage ceilings within it; do not reuse larger defaults accidentally. If an estimate cannot fit, retain a budget-stop outcome rather than add attempts or exceed the configured estimate. Record effective model settings, pricing provenance, usage and estimated versus available billed cost.
- Treat live repair success as an observed task outcome, not proof of tracker correctness or a ranking between orchestrators. Retain both attempts and failure evidence. Token streaming and the comparison desk remain subsequent work through the same observation boundary.

## Testing Decisions

- A good test asserts externally observable behavior: model-visible requests/results, emitted and saved evidence, recovered prefixes, served events, rendered information, collected candidates and canonical verdicts. Avoid checks tied to private helpers, exact internal class layouts, cosmetic markup or framework internals.
- Prefer the existing `attempt_and_evaluate` seam with an admitted task, scripted model, budgets and artifact destination, adding the event sink for observed runs. Run both actual orchestrators and compare observation enabled/disabled on the same scripted inputs. Exclude timestamps and new observation records from equality while preserving ordered model-visible messages, tool results, candidate changes and functional verdicts.
- Prior art includes existing Docker-backed scripted repair and LangGraph parity tests, partial-attempt and evaluator-failure cases, matched-comparison tests, cost-reservation tests and report rendering tests. Extend these behavior patterns rather than introducing a replacement runner. Required Docker integration acceptance must execute, not pass through skips.
- Test the recorder/reader through public append/read behavior in temporary evidence directories: start before dispatch, artifact availability before reference publication, successful outcome visibility, immutable records, interrupted trailing writes, unmatched starts, mid-log corruption, missing/damaged artifacts, sequence gaps and schema incompatibility. Fault-inject mandatory writes/syncs and verify no subsequent operation executes; distinguish an error returned to the caller from a failure marker that could not be saved.
- Prove new Python phases and LangGraph nodes are recorded where execution occurs. Exercise model/tool errors and bounded retries, budget termination, evaluation and cleanup. Verify instrumentation does not alter provider continuation fields or model-visible truncation.
- Test intermediate mutations from successful, failed and timed-out tools through actual repository effects, including additions/deletions and binary metadata. Assert unsettled/background-write cases and size/time omissions are explicit. Check final canonical patch/verdict parity independently of intermediate captures.
- Use preserved existing live recordings to check legacy reading, evidence/report fidelity and honest unavailable/derived labels. Verify byte preservation on open and playback. Build small synthetic interrupted/corrupt fixtures for fault cases; do not purchase model calls for fault injection.
- Exercise server/client behavior through the public HTTP/SSE interface: catch-up while events continue, reconnect with duplicate deliveries, gaps, invalid cursors, slow consumers, browser closure and bounded resource use. Verify closing or lagging the observer does not stop an attempt. Assert only registered evidence/artifacts are served and untrusted content is displayed safely.
- Verify the real browser workbench: component/source navigation, chronological selection, model/tool evidence, full versus visible output, playback controls, selected-point state, final result separation, missing/error states and readable layouts. Test playback with provider/tool boundaries disabled to prove it makes no such calls. Endpoint reachability and static script checks alone are insufficient browser acceptance.
- Verify viewer/report consistency against the same event/artifact identities and retain pending versus completed Codex review distinctions. Separately record deterministic test evidence, Docker integration, browser verification and the later live demonstration.
- Measure enabled/disabled recording and capture overhead on repeatable scripted workloads. Record limits and timings rather than inventing a performance threshold. Include effective capture settings in reproduction notes.
- Only after those checks pass, perform one fresh matched live pair with the shared USD 0.10 estimate guard, preserving smoke, requests, retries, accounting and unsuccessful outcomes. Test cost admission offline first, including refusing a request that cannot fit. No additional paid attempts are automatically allowed to replace failures.

## Out of Scope

- Provider-token streaming, partial response/tool-call assembly and streaming retry semantics in this first stage; they require the separate second-milestone design.
- Continuous terminal output and continuous observation of every filesystem write.
- Agent launch/cancel/pause controls in the UI, breakpoints, checkpoints, resume and tool/model re-execution during playback.
- Layout C's comparison desk in first-stage acceptance; retain it as the accepted later view without implying event-index causal alignment.
- SQLite indexing, cross-run analytics, multi-user hosting, remote exposure or a generic observability platform.
- A mandatory frontend framework, framework agent factories or duplication of existing attempt lifecycles.
- Access to hidden model reasoning, fabricated historical telemetry or claims that exposed reasoning proves the model's internal causal process.
- Changing canonical task checks, scoring criteria, model behavior, repository tool semantics or the original ML Tutor application to accommodate observation.
- Automatic qualitative judging, fabricated completed reviews, scheduled runs, statistical orchestrator/model rankings and automatic extra paid attempts.
- Implementation, provider calls, merging the original harness PR, pushing the design branch or closing existing milestone issues as part of publishing this specification.

## Further Notes

- The user accepted Q29–Q48 and then invoked to-spec, authorizing synthesis and publication without another interview. The inherited test-seam check is satisfied by the accepted event sink, actual-transition fidelity and observation-on/off acceptance requirements; this spec preserves those expectations.
- The user wrote “0.10 cents” while comparing with a two-cent prior run. The documented interpretation is USD 0.10 total, or ten cents, replacing the earlier USD 1 proposal. The guard constrains estimates/reservations; it is not a guarantee of an exactly known eventual provider bill. Verify current pricing during implementation preflight, not through paid calls during specification work.
- Respect the existing domain glossary and the ADRs separating observation from execution and sharing one attempt history across viewing/reporting. Incomplete recording, termination reason, functional verdict and Codex review remain separate.
- The existing runtime is on the first-milestone integration branch, with the original harness [PR #9](https://github.com/Versionfm/agent-eval-harness/pull/9) awaiting review. Establish a base containing that implementation before executing this extension; creating this issue does not merge it.
- The layout A prototype was selected for the workbench; C was selected for a later comparison view. It uses saved live evidence and derived highlights, not a live connection or recorded graph transitions. Automated visual inspection of that local-file prototype was blocked by browser policy; the user's selection and static validation are separate from production browser acceptance. Do not bypass that policy restriction.
- Deliver implementation in understandable slices with a component explanation, concrete event/data call chain, repeatable experiment and inspection checkpoint. Retain the user's requested Luna subagents with xhigh effort per implementation ticket once implementation is authorized. This parent specification does not itself approve a ticket breakdown or start implementation.
- Prototype primary-source capture: local branch `prototype/live-tracker-layout`, commit `0024ce6243b62b31b2f6121758d2bbb0e9a44bb0`. It preserves the original builder/template and the A-default/C-later verdict outside the production branch. This branch has not been pushed; no run evidence or credentials were committed with it. The specification is self-contained and does not require access to that local branch.

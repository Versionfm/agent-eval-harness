# Live tracker learning sequence

Status: learning sequence accompanies the accepted design and [published specification](https://github.com/Versionfm/agent-eval-harness/issues/10). No production slices have been implemented or tested. When implementation is approved, retain the user's preference for Luna subagents with xhigh effort per ticket, with the root agent coordinating integration and review.

| Slice | Learn by building | Evidence to inspect |
| --- | --- | --- |
| 1. Event boundary | Define events and inject a sink without handing attempt execution to the viewer. | Follow one Python phase and one LangGraph node to their actual source functions; compare scripted observation on/off. |
| 2. Incremental recorder | Sequence operations, save linked artifacts and enforce durable boundaries. | Inspect an attempt while it is running; interrupt writes and recover only the verified prefix. |
| 3. Evidence reader | Adapt older logs and derive state at a selected event. | Open the original first live pair; missing starts/nodes stay unavailable and final results stay separate. |
| 4. Loopback delivery | Serve saved history and deliver new events over SSE. | Disconnect, reconnect, duplicate delivery and slow-consumer cases; disk remains authoritative. |
| 5. Component workbench | Build layout A with map/timeline/inspector and playback controls. | Inspect full versus model-visible tool output, exposed reasoning, source links and selected-point state in the browser. |
| 6. Mutation observations | Associate bounded repository changes with tool outcomes. | Compare successful/error/timeout mutations; see explicit omitted or unsettled captures and measured overhead. |
| 7. Shared reporting and acceptance | Verify viewer/report fidelity and both orchestrator integrations. | Match canonical final patch/checks/review evidence; confirm controlled parity and recording failure behavior. |
| 8. Bounded live demonstration | Run one matched pair after deterministic acceptance. | Trace actual model/tool activity and accounting under USD 0.10 total estimated ceiling, without treating stochastic repair success as viewer proof. |

These are the conceptual learning slices. The user approved a vertical implementation breakdown; see the [eight published tickets](TICKETS.md) for scope and actual blocking edges. The later comparison layout C and provider-token streaming expand the same observation boundary after the first-stage workbench is established.

For each slice, provide a short walkthrough of what the component owns, why its boundary exists, the concrete event/data call chain, and a small experiment the user can repeat. Keep implemented behavior, deterministic evidence, browser verification and live demonstration labeled separately.

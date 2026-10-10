// Workbench entry point (layout A): component map, chronological timeline and inspector.
// The saved history plus SSE feed one attempt. Evidence is written with textContent only.
import { buildComponentMap, updateComponentCounts } from "./components.js";
import { el } from "./dom.js";
import { Inspector } from "./inspector.js";
import { COMPONENTS, componentOf } from "./model.js";
const timeline = document.getElementById("timeline");
const status = document.getElementById("status");
const components = document.getElementById("components");
const banner = el("p", "note");
banner.id = "recording";
banner.setAttribute("role", "status");
banner.hidden = true;
status.after(banner);
let attemptId = "";
let inspector;
const events = [];
const rows = new Map();
let lastSequence = 0;
let selectedSequence = null;
let activeComponent = null;
let recording = null;
function describeRecording(next) {
    const first = next.problems[0];
    switch (next.state) {
        case "corrupt":
            return `Recording is corrupt (${next.problems.length} problem${next.problems.length === 1 ? "" : "s"}; first: ${first?.detail ?? "unknown"}). Damaged records are listed, not skipped.`;
        case "failed":
            return `Recording failed while writing ${next.failure?.failed_event_type ?? "an event"}: ${next.failure?.error ?? "unknown error"}. The attempt stopped before its next operation.`;
        case "interrupted":
            return `Recording is incomplete: the final record was cut off (${next.torn_tail_bytes} bytes not verified).`;
        case "open":
            return "The attempt has not recorded its finish: it is still running, or it stopped without a final record.";
        default:
            return "";
    }
}
// Start records without an outcome: awaiting while the attempt is open, unresolved once it stopped.
function labelOperations() {
    const pending = new Set(recording?.unresolved_operations ?? []);
    const label = recording?.state === "open" ? "awaiting outcome" : "unresolved";
    timeline.querySelectorAll("li[data-operation]").forEach((row) => {
        const state = row.querySelector(".operation-state");
        if (state) {
            state.textContent = pending.has(row.dataset.operation ?? "") ? label : "";
        }
    });
}
function applyRecording(next) {
    recording = next;
    const text = describeRecording(next);
    banner.textContent = text;
    banner.hidden = text === "";
    labelOperations();
}
function describe(event) {
    const data = event.data;
    switch (event.type) {
        case "attempt_started":
            return `attempt started for ${data.task_id} (${data.orchestrator})`;
        case "initial_context":
            return `initial context with ${data.message_count} messages`;
        case "phase.enter":
            return `phase ${data.phase} (loop step ${data.loop_step})`;
        case "state":
            return `state: ${data.model_calls ?? "?"} model calls, ${data.context_bytes ?? "?"} context bytes`;
        case "model.start":
            return `model call ${data.model_call} started with ${data.message_count} messages`;
        case "model.outcome":
            return `model call ${data.model_call} ${data.status}` + (data.error ? `: ${data.error}` : "");
        case "tool.start":
            return `${data.tool_name} started`;
        case "tool.outcome":
            return `${data.tool_name} ${data.status}` + (data.result?.error ? `: ${data.result.error}` : "");
        case "attempt_finished":
            return `attempt ${data.termination_reason}; verdict ${data.functional_verdict}`;
        default:
            return event.type;
    }
}
function buildRow(event) {
    const row = el("li");
    row.dataset.type = event.type;
    row.dataset.sequence = String(event.sequence);
    const button = el("button", "row");
    button.type = "button";
    button.append(el("span", "sequence", `#${event.sequence}`), el("span", "kind", event.type), el("span", "text", describe(event)));
    if (event.operation_id) {
        button.append(el("code", "", event.operation_id));
    }
    if (event.operation_id && event.type.endsWith(".start")) {
        row.dataset.operation = event.operation_id;
        button.append(el("span", "operation-state"));
    }
    button.addEventListener("click", () => selectEvent(event.sequence));
    row.append(button);
    return row;
}
function render(event) {
    if (event.sequence <= lastSequence) {
        return; // duplicate from reconnect or history overlap
    }
    if (lastSequence > 0 && event.sequence > lastSequence + 1) {
        const gap = el("li", "gap", `missing events ${lastSequence + 1} to ${event.sequence - 1}`);
        timeline.append(gap);
    }
    lastSequence = event.sequence;
    events.push(event);
    const row = buildRow(event);
    rows.set(event.sequence, row);
    timeline.append(row);
    labelOperations();
    updateComponentCounts(components, events);
}
function markRows() {
    for (const event of events) {
        const row = rows.get(event.sequence);
        if (!row) {
            continue;
        }
        row.classList.toggle("selected", event.sequence === selectedSequence);
        row.classList.toggle("match", activeComponent !== null && componentOf(event) === activeComponent);
    }
}
function selectEvent(sequence) {
    selectedSequence = sequence;
    activeComponent = null;
    markRows();
    const event = events.find((item) => item.sequence === sequence);
    if (event) {
        void inspector.showEvent(events, event);
    }
}
function selectComponent(id) {
    const component = COMPONENTS.find((item) => item.id === id);
    if (!component) {
        return;
    }
    activeComponent = id;
    markRows();
    const count = events.filter((event) => componentOf(event) === id).length;
    void inspector.showComponent(component, count);
}
function follow() {
    const source = new EventSource(`/api/attempts/${encodeURIComponent(attemptId)}/stream?after=${lastSequence}`);
    source.onopen = () => {
        status.textContent = "live";
    };
    source.addEventListener("attempt-event", (message) => {
        const event = JSON.parse(message.data);
        // Keep the inspector on the newest event only while the reader has not chosen another one.
        const trackingLatest = selectedSequence === null || selectedSequence === lastSequence;
        render(event);
        if (trackingLatest) {
            selectEvent(event.sequence);
        }
        if (event.type === "attempt_finished") {
            source.close();
            status.textContent = "finished";
        }
    });
    source.addEventListener("recording-status", (message) => {
        const next = JSON.parse(message.data);
        applyRecording(next);
        if (next.state === "failed" || next.state === "corrupt") {
            source.close();
            status.textContent = "recording stopped";
        }
    });
    source.onerror = () => {
        status.textContent = source.readyState === EventSource.CLOSED ? "closed" : "reconnecting";
    };
}
async function start() {
    const attempts = (await (await fetch("/api/attempts")).json());
    if (attempts.length === 0) {
        status.textContent = "no attempts registered";
        return;
    }
    attemptId = attempts[0].attempt_id;
    inspector = new Inspector(attemptId, document.getElementById("inspector"), document.getElementById("state"), document.getElementById("evidence"));
    buildComponentMap(components, selectComponent);
    const history = (await (await fetch(`/api/attempts/${encodeURIComponent(attemptId)}/events?after=0`)).json());
    history.events.forEach((event) => render(event));
    applyRecording(history.recording);
    if (events.length > 0) {
        selectEvent(events[events.length - 1].sequence);
    }
    if (history.events.some((event) => event.type === "attempt_finished")) {
        status.textContent = "finished";
        return;
    }
    if (history.recording.state === "failed" || history.recording.state === "corrupt") {
        status.textContent = "recording stopped";
        return;
    }
    follow();
}
start().catch((error) => {
    status.textContent = `failed to load timeline: ${String(error)}`;
});

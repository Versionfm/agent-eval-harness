// Minimal timeline client: one attempt, rendered from the saved history plus SSE.
// Evidence is written with textContent only; links are built from validated paths.
const ARTIFACT_PATH = /^artifacts\/[0-9a-f]{64}$/;
const timeline = document.getElementById("timeline");
const status = document.getElementById("status");
const banner = document.createElement("p");
banner.id = "recording";
banner.setAttribute("role", "status");
banner.hidden = true;
status.after(banner);
let attemptId = "";
let lastSequence = 0;
let recording = null;
function describe(event) {
    const data = event.data;
    switch (event.type) {
        case "attempt_started":
            return `attempt started for ${data.task_id} (${data.orchestrator})`;
        case "initial_context":
            return `initial context with ${data.message_count} messages`;
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
// Start records without an outcome are labelled: awaiting while live, unresolved once the recording stopped.
function labelOperations() {
    const pending = new Set(recording?.unresolved_operations ?? []);
    const label = recording?.state === "open" ? "awaiting outcome" : "unresolved";
    timeline.querySelectorAll("li[data-operation]").forEach((row) => {
        const state = row.querySelector(".operation-state");
        const unresolved = pending.has(row.dataset.operation ?? "");
        if (state) {
            state.textContent = unresolved ? label : "";
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
function render(event) {
    if (event.sequence <= lastSequence) {
        return; // duplicate from reconnect or history overlap
    }
    if (lastSequence > 0 && event.sequence > lastSequence + 1) {
        const gap = document.createElement("li");
        gap.className = "gap";
        gap.textContent = `missing events ${lastSequence + 1} to ${event.sequence - 1}`;
        timeline.append(gap);
    }
    lastSequence = event.sequence;
    const row = document.createElement("li");
    row.dataset.type = event.type;
    const sequence = document.createElement("span");
    sequence.className = "sequence";
    sequence.textContent = `#${event.sequence}`;
    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = event.type;
    const text = document.createElement("span");
    text.textContent = describe(event);
    row.append(sequence, kind, text);
    if (event.operation_id) {
        const operation = document.createElement("code");
        operation.textContent = event.operation_id;
        row.append(operation);
    }
    if (event.operation_id && event.type.endsWith(".start")) {
        row.dataset.operation = event.operation_id;
        const state = document.createElement("span");
        state.className = "operation-state";
        row.append(state);
    }
    for (const artifact of event.artifacts) {
        if (!ARTIFACT_PATH.test(artifact.path)) {
            continue;
        }
        const link = document.createElement("a");
        link.href = `/api/attempts/${encodeURIComponent(attemptId)}/artifacts/${artifact.path}`;
        link.textContent = `${artifact.role} (${artifact.bytes} bytes)`;
        row.append(link);
    }
    timeline.append(row);
    labelOperations();
}
function follow() {
    const source = new EventSource(`/api/attempts/${encodeURIComponent(attemptId)}/stream?after=${lastSequence}`);
    source.onopen = () => {
        status.textContent = "live";
    };
    source.addEventListener("attempt-event", (message) => {
        const event = JSON.parse(message.data);
        render(event);
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
    const history = (await (await fetch(`/api/attempts/${encodeURIComponent(attemptId)}/events?after=0`)).json());
    history.events.forEach(render);
    applyRecording(history.recording);
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
export {};

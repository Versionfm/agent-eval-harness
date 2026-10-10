// Minimal timeline client: one attempt, rendered from the saved history plus SSE.
// Evidence is written with textContent only; links are built from validated paths.
const ARTIFACT_PATH = /^artifacts\/[0-9a-f]{64}$/;
const timeline = document.getElementById("timeline");
const status = document.getElementById("status");
let attemptId = "";
let lastSequence = 0;
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
    source.addEventListener("recording-error", () => {
        source.close();
        status.textContent = "recording error: evidence is incomplete";
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
    if (history.events.some((event) => event.type === "attempt_finished")) {
        status.textContent = "finished";
        return;
    }
    follow();
}
start().catch((error) => {
    status.textContent = `failed to load timeline: ${String(error)}`;
});
export {};

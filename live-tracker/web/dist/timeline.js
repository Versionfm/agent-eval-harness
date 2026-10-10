// Minimal timeline client: one attempt, rendered from the SSE stream (history, then live).
// Evidence is written with textContent only; links are built from validated paths.
import { follow } from "./connection.js";
const ARTIFACT_PATH = /^artifacts\/[0-9a-f]{64}$/;
const timeline = document.getElementById("timeline");
const status = document.getElementById("status");
const detail = document.getElementById("detail");
const lag = document.getElementById("lag");
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
function addGap(from, to) {
    const gap = document.createElement("li");
    gap.className = "gap";
    gap.textContent = `missing events ${from} to ${to}`;
    timeline.append(gap);
}
function renderEvent(attemptId, event) {
    const row = document.createElement("li");
    row.dataset.type = event.type;
    row.dataset.sequence = String(event.sequence);
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
function onAccepted(attemptId, event, accepted) {
    if (accepted.kind === "duplicate") {
        return; // redelivered after a reconnect: already displayed
    }
    if (accepted.kind === "conflict") {
        const row = document.createElement("li");
        row.className = "conflict";
        row.textContent = `evidence conflict: ${accepted.message}`;
        timeline.append(row);
        return;
    }
    if (accepted.gap) {
        addGap(accepted.gap[0], accepted.gap[1]);
    }
    renderEvent(attemptId, event);
}
function onProgress(progress) {
    status.textContent = progress.state;
    status.dataset.state = progress.state;
    detail.textContent = progress.detail;
    const behind = Math.max(progress.latest - progress.displayed, 0);
    lag.textContent = `displayed #${progress.displayed} · latest #${progress.latest} · lag ${behind}`;
}
async function start() {
    const attempts = (await (await fetch("/api/attempts")).json());
    if (attempts.length === 0) {
        status.textContent = "no attempts registered";
        return;
    }
    const attemptId = attempts[0].attempt_id;
    follow(attemptId, {
        onAccepted: (event, accepted) => onAccepted(attemptId, event, accepted),
        onProgress,
    });
}
start().catch((error) => {
    status.textContent = `failed to load timeline: ${String(error)}`;
});

// Workbench entry point (layout A): component map, chronological timeline and inspector.
// The saved history plus SSE feed one attempt (connection.ts owns delivery). Evidence is written with textContent only.

import { buildComponentMap, updateComponentCounts } from "./components.js";
import { Accepted, Progress, Recording, follow } from "./connection.js";
import { el } from "./dom.js";
import { Inspector } from "./inspector.js";
import { COMPONENTS, TrackerEvent, componentOf } from "./model.js";

const timeline = document.getElementById("timeline") as HTMLOListElement;
const status = document.getElementById("status") as HTMLElement;
const detail = document.getElementById("detail") as HTMLElement;
const lag = document.getElementById("lag") as HTMLElement;
const components = document.getElementById("components") as HTMLElement;
const banner = el("p", "note");
banner.id = "recording";
banner.setAttribute("role", "status");
banner.hidden = true;
status.after(banner);

let inspector: Inspector;
const events: TrackerEvent[] = [];
const rows = new Map<number, HTMLLIElement>();
let lastSequence = 0;
let selectedSequence: number | null = null;
let activeComponent: string | null = null;
let recording: Recording | null = null;

function describeRecording(next: Recording): string {
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
function labelOperations(): void {
  const pending = new Set(recording?.unresolved_operations ?? []);
  const label = recording?.state === "open" ? "awaiting outcome" : "unresolved";
  timeline.querySelectorAll<HTMLLIElement>("li[data-operation]").forEach((row) => {
    const state = row.querySelector(".operation-state");
    if (state) {
      state.textContent = pending.has(row.dataset.operation ?? "") ? label : "";
    }
  });
}

function applyRecording(next: Recording): void {
  recording = next;
  const text = describeRecording(next);
  banner.textContent = text;
  banner.hidden = text === "";
  labelOperations();
}

function describe(event: TrackerEvent): string {
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

function buildRow(event: TrackerEvent): HTMLLIElement {
  const row = el("li");
  row.dataset.type = event.type;
  row.dataset.sequence = String(event.sequence);
  const button = el("button", "row");
  button.type = "button";
  button.append(
    el("span", "sequence", `#${event.sequence}`),
    el("span", "kind", event.type),
    el("span", "text", describe(event)),
  );
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

// Only accepted events reach the timeline: duplicates are dropped by the ledger, gaps and conflicts are explicit rows.
function onAccepted(event: TrackerEvent, accepted: Accepted): void {
  if (accepted.kind === "duplicate") {
    return;
  }
  if (accepted.kind === "conflict") {
    timeline.append(el("li", "conflict", `evidence conflict: ${accepted.message}`));
    return;
  }
  if (accepted.gap) {
    timeline.append(el("li", "gap", `missing events ${accepted.gap[0]} to ${accepted.gap[1]}`));
  }
  // Keep the inspector on the newest event only while the reader has not chosen another one.
  const trackingLatest = selectedSequence === null || selectedSequence === lastSequence;
  lastSequence = event.sequence;
  events.push(event);
  const row = buildRow(event);
  rows.set(event.sequence, row);
  timeline.append(row);
  labelOperations();
  updateComponentCounts(components, events);
  if (trackingLatest) {
    selectEvent(event.sequence);
  }
}

function onProgress(progress: Progress): void {
  status.textContent = progress.state;
  status.dataset.state = progress.state;
  detail.textContent = progress.detail;
  const behind = Math.max(progress.latest - progress.displayed, 0);
  lag.textContent = `displayed #${progress.displayed} · latest #${progress.latest} · lag ${behind}`;
}

function markRows(): void {
  for (const event of events) {
    const row = rows.get(event.sequence);
    if (!row) {
      continue;
    }
    row.classList.toggle("selected", event.sequence === selectedSequence);
    row.classList.toggle("match", activeComponent !== null && componentOf(event) === activeComponent);
  }
}

function selectEvent(sequence: number): void {
  selectedSequence = sequence;
  activeComponent = null;
  markRows();
  const event = events.find((item) => item.sequence === sequence);
  if (event) {
    void inspector.showEvent(events, event);
  }
}

function selectComponent(id: string): void {
  const component = COMPONENTS.find((item) => item.id === id);
  if (!component) {
    return;
  }
  activeComponent = id;
  markRows();
  const count = events.filter((event) => componentOf(event) === id).length;
  void inspector.showComponent(component, count);
}

async function start(): Promise<void> {
  const attempts = (await (await fetch("/api/attempts")).json()) as { attempt_id: string }[];
  if (attempts.length === 0) {
    status.textContent = "no attempts registered";
    return;
  }
  const attemptId = attempts[0].attempt_id;
  inspector = new Inspector(
    attemptId,
    document.getElementById("inspector") as HTMLElement,
    document.getElementById("state") as HTMLElement,
    document.getElementById("evidence") as HTMLElement,
  );
  buildComponentMap(components, selectComponent);
  follow(attemptId, { onAccepted, onProgress, onRecording: applyRecording });
}

start().catch((error: unknown) => {
  status.textContent = `failed to load timeline: ${String(error)}`;
});

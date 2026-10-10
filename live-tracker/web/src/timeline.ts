// Workbench entry point (layout A): component map, chronological timeline and inspector.
// The saved history plus SSE feed one attempt. Evidence is written with textContent only.

import { buildComponentMap, updateComponentCounts } from "./components.js";
import { el } from "./dom.js";
import { Inspector } from "./inspector.js";
import { COMPONENTS, TrackerEvent, componentOf } from "./model.js";

const timeline = document.getElementById("timeline") as HTMLOListElement;
const status = document.getElementById("status") as HTMLElement;
const components = document.getElementById("components") as HTMLElement;

let attemptId = "";
let inspector: Inspector;
const events: TrackerEvent[] = [];
const rows = new Map<number, HTMLLIElement>();
let lastSequence = 0;
let selectedSequence: number | null = null;
let activeComponent: string | null = null;

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
  button.addEventListener("click", () => selectEvent(event.sequence));
  row.append(button);
  return row;
}

function render(event: TrackerEvent): void {
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
  updateComponentCounts(components, events);
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

function follow(): void {
  const source = new EventSource(
    `/api/attempts/${encodeURIComponent(attemptId)}/stream?after=${lastSequence}`
  );
  source.onopen = () => {
    status.textContent = "live";
  };
  source.addEventListener("attempt-event", (message) => {
    const event = JSON.parse((message as MessageEvent).data) as TrackerEvent;
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
  source.addEventListener("recording-error", () => {
    source.close();
    status.textContent = "recording error: evidence is incomplete";
  });
  source.onerror = () => {
    status.textContent = source.readyState === EventSource.CLOSED ? "closed" : "reconnecting";
  };
}

async function start(): Promise<void> {
  const attempts = (await (await fetch("/api/attempts")).json()) as { attempt_id: string }[];
  if (attempts.length === 0) {
    status.textContent = "no attempts registered";
    return;
  }
  attemptId = attempts[0].attempt_id;
  inspector = new Inspector(
    attemptId,
    document.getElementById("inspector") as HTMLElement,
    document.getElementById("state") as HTMLElement,
    document.getElementById("evidence") as HTMLElement,
  );
  buildComponentMap(components, selectComponent);
  const history = (await (await fetch(`/api/attempts/${encodeURIComponent(attemptId)}/events?after=0`)).json()) as {
    events: TrackerEvent[];
  };
  history.events.forEach((event) => render(event));
  if (events.length > 0) {
    selectEvent(events[events.length - 1].sequence);
  }
  if (history.events.some((event) => event.type === "attempt_finished")) {
    status.textContent = "finished";
    return;
  }
  follow();
}

start().catch((error: unknown) => {
  status.textContent = `failed to load timeline: ${String(error)}`;
});

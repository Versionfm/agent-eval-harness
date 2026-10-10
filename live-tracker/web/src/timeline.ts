// Workbench entry point (layout A): component map, chronological timeline, inspector, final results and playback.
// Two modes, always labelled. Saved recordings load once and are played back with the controls; a live
// attempt is followed over the stream, and the selection follows the newest event only until the reader moves
// away. connection.ts owns live delivery. Evidence is written with textContent only.

import { WorkflowMap } from "./components.js";
import { Accepted, Progress, Recording, follow } from "./connection.js";
import { el } from "./dom.js";
import { renderFinal } from "./final.js";
import { Inspector } from "./inspector.js";
import { COMPONENTS, OPERATION_STARTS, TrackerEvent, categoryOf, componentsOf } from "./model.js";
import { Playback } from "./playback.js";

const timeline = document.getElementById("timeline") as HTMLOListElement;
const status = document.getElementById("status") as HTMLElement;
const detail = document.getElementById("detail") as HTMLElement;
const lag = document.getElementById("lag") as HTMLElement;
const components = document.getElementById("components") as HTMLElement;
const workflowMap = new WorkflowMap(components, selectComponent);
const modeLine = document.getElementById("mode") as HTMLElement;
const reportLink = document.getElementById("report-link") as HTMLAnchorElement;
const finalPanel = document.getElementById("final") as HTMLElement;
const controls = {
  play: document.getElementById("play") as HTMLButtonElement,
  previous: document.getElementById("previous") as HTMLButtonElement,
  next: document.getElementById("next") as HTMLButtonElement,
  speed: document.getElementById("speed") as HTMLSelectElement,
  scrub: document.getElementById("scrub") as HTMLInputElement,
  position: document.getElementById("position") as HTMLElement,
  follow: document.getElementById("follow") as HTMLButtonElement,
};
const banner = document.getElementById("recording") as HTMLElement;
const filters = document.getElementById("filters") as HTMLElement;
const attemptSelect = document.getElementById("attempt-select") as HTMLSelectElement;

let inspector: Inspector;
let playback: Playback;
let mode: "live" | "saved" = "live";
const events: TrackerEvent[] = [];
const rows = new Map<number, HTMLLIElement>();
let lastSequence = 0;
let selectedIndex = -1;
let activeComponent: string | null = null;
let recording: Recording | null = null;

// Recording completeness is shown apart from the verdict and termination reason.
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
    case "complete":
      return `Recording complete: ${next.verified_events} events verified.`;
    case "legacy":
      return "Legacy first-live-pair trace, read only. Attempt starts and finishes, operation starts, Python phases, graph nodes, selected-point state and intermediate captures were not recorded, so none are shown. Fields marked derived were computed now from the saved bytes.";
    default:
      return "";
  }
}

function applyRecording(next: Recording): void {
  recording = next;
  const text = describeRecording(next);
  banner.textContent = text;
  banner.dataset.state = next.state;
  banner.hidden = text === "";
  markRows();
  setMode();
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
    case "node.enter":
      return `graph node ${data.node} entered (graph step ${data.graph_step_count})`;
    case "node.outcome":
      return `graph node ${data.node} finished (graph step ${data.graph_step_count})` +
        (data.termination_reason ? `; stop ${data.termination_reason}` : "");
    case "route.decision":
      return `router after ${data.after_node}: ${data.next} (${data.reason})`;
    case "state":
      return `state: ${data.model_calls ?? "?"} model calls, ${data.context_bytes ?? "?"} context bytes`;
    case "model.start":
      return `model call ${data.model_call} started with ${data.message_count} messages`;
    case "model.outcome":
      return `model call ${data.model_call} ${data.status}` + took(data) + (data.error ? `: ${data.error}` : "");
    case "tool.start":
      return `${data.tool_name} started`;
    case "tool.outcome":
      return `${data.tool_name} ${data.status}` + took(data) + (data.result?.error ? `: ${data.result.error}` : "");
    case "tool.capture":
      return `repository capture ${data.status}` + (data.reason ? ` (${data.reason})` : "");
    case "attempt_finished":
      return `attempt ${data.termination_reason}; verdict ${data.functional_verdict}`;
    default:
      return event.type;
  }
}

function took(data: Record<string, any>): string {
  return typeof data.duration_seconds === "number" ? ` in ${data.duration_seconds.toFixed(2)} s` : "";
}

// Time since the attempt started, as recorded (monotonic). Legacy records have none.
function elapsed(seconds: number | undefined): string {
  if (typeof seconds !== "number") {
    return "";
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  return `${Math.floor(seconds / 60)}m ${String(Math.floor(seconds % 60)).padStart(2, "0")}s`;
}

function buildRow(event: TrackerEvent): HTMLLIElement {
  const row = el("li");
  row.dataset.type = event.type;
  row.dataset.sequence = String(event.sequence);
  row.dataset.category = categoryOf(event.type);
  const button = el("button", "row");
  button.type = "button";
  const main = el("span", "main");
  main.append(el("span", "kind", event.type), el("span", "text", describe(event)));
  const meta = el("span", "meta");
  if (event.operation_id) {
    meta.append(el("code", "", event.operation_id));
  }
  if (OPERATION_STARTS.has(event.type)) {
    meta.append(el("span", "operation-status"));
  }
  meta.append(el("span", "elapsed", elapsed(event.elapsed_seconds)));
  button.append(el("span", "dot"), el("span", "sequence", `#${event.sequence}`), main, meta);
  button.addEventListener("click", () => selectEvent(event.sequence));
  row.append(button);
  return row;
}

// Appends a recorded event without selecting it. Callers decide what the reader sees.
function appendRow(event: TrackerEvent): void {
  events.push(event);
  lastSequence = event.sequence;
  const row = buildRow(event);
  rows.set(event.sequence, row);
  timeline.append(row);
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
  const trackingLatest = selectedIndex === -1 || selectedIndex === events.length - 1;
  appendRow(event);
  if (trackingLatest) {
    selectIndex(events.length - 1);
  } else {
    syncPlayback();
    markRows();
  }
}

function onProgress(progress: Progress): void {
  status.textContent = progress.state;
  status.dataset.state = progress.state;
  detail.textContent = progress.detail;
  const behind = Math.max(progress.latest - progress.displayed, 0);
  lag.textContent = `displayed #${progress.displayed} · latest #${progress.latest} · lag ${behind}`;
}

// A start with no recorded outcome is waiting while the attempt runs, and unresolved once it has finished.
function markRows(): void {
  // A recording that stopped without an outcome can no longer deliver one: its starts are unresolved.
  const stopped = events.some((event) => event.type === "attempt_finished")
    || ["failed", "corrupt", "interrupted"].includes(recording?.state ?? "");
  const selectedSequence = events[selectedIndex]?.sequence ?? null;
  const closed = new Set(
    events.filter((event) => event.operation_id && !OPERATION_STARTS.has(event.type))
      .map((event) => event.operation_id),
  );
  for (const event of events) {
    const row = rows.get(event.sequence);
    if (!row) {
      continue;
    }
    row.classList.toggle("selected", event.sequence === selectedSequence);
    row.classList.toggle("match", activeComponent !== null && componentsOf(event).includes(activeComponent));
    if (!OPERATION_STARTS.has(event.type)) {
      continue;
    }
    const outcome = closed.has(event.operation_id);
    const label = outcome ? "" : stopped ? "unresolved" : "waiting";
    row.classList.toggle("unresolved", label === "unresolved");
    row.classList.toggle("waiting", label === "waiting");
    row.querySelector(".operation-status")!.textContent = label;
  }
  workflowMap.update(events, selectedIndex, stopped, activeComponent);
}

function syncPlayback(): void {
  playback.sync(events.length, selectedIndex, events[selectedIndex]?.sequence);
}

// The mode line says which mode is on and whether live following is active; it never implies either.
function setMode(): void {
  modeLine.dataset.mode = mode;
  if (mode === "saved") {
    modeLine.textContent = recording?.state === "legacy"
      ? "Playback of the preserved legacy trace (read only). No model, tool or provider call is made."
      : "Playback of a saved recording. Only recorded events are shown; no model, tool or provider call is made.";
    return;
  }
  const following = events.length === 0 || selectedIndex === events.length - 1;
  modeLine.textContent = following
    ? "Live: following the newest recorded event."
    : `Live: not following. Showing #${events[selectedIndex]?.sequence ?? "?"}; Follow latest resumes.`;
}

// Keeps the selected row inside the timeline's own scroll box, without moving the page.
function revealSelected(): void {
  const row = rows.get(events[selectedIndex]?.sequence ?? -1);
  if (!row) {
    return;
  }
  const top = row.offsetTop;
  if (top < timeline.scrollTop || top + row.offsetHeight > timeline.scrollTop + timeline.clientHeight) {
    timeline.scrollTop = top - timeline.clientHeight / 2;
  }
}

function selectIndex(index: number): void {
  const event = events[index];
  if (!event) {
    return;
  }
  selectedIndex = index;
  activeComponent = null;
  markRows();
  revealSelected();
  syncPlayback();
  setMode();
  void inspector.showEvent(events, event);
}

function selectEvent(sequence: number): void {
  selectIndex(events.findIndex((item) => item.sequence === sequence));
}

function selectComponent(id: string): void {
  const component = COMPONENTS.find((item) => item.id === id);
  if (!component) {
    return;
  }
  activeComponent = id;
  markRows();
  const count = events.filter((event) => componentsOf(event).includes(id)).length;
  void inspector.showComponent(component, count);
}

// Saved recordings are read once. Every recorded event is shown; the selection starts on the last one.
async function loadSaved(attemptId: string): Promise<void> {
  mode = "saved";
  const response = await fetch(`/api/attempts/${encodeURIComponent(attemptId)}/events?after=0`);
  const body = (await response.json()) as { events: TrackerEvent[]; recording: Recording };
  applyRecording(body.recording);
  for (const event of body.events) {
    appendRow(event);
  }
  // The same status vocabulary as the live stream: a stopped recording is a recording error, not "saved".
  const stopped = body.recording.state === "failed" || body.recording.state === "corrupt";
  status.textContent = stopped ? "recording-error" : "saved";
  status.dataset.state = status.textContent;
  lag.textContent = "";
  detail.textContent = `${attemptId} · ${body.events.length} recorded events`;
  if (events.length > 0) {
    selectIndex(events.length - 1);
  }
}

async function start(): Promise<void> {
  const attempts = (await (await fetch("/api/attempts")).json()) as { attempt_id: string; mode: string }[];
  if (attempts.length === 0) {
    status.textContent = "no attempts registered";
    return;
  }
  const requested = new URLSearchParams(window.location.search).get("attempt");
  const chosen = attempts.find((item) => item.attempt_id === requested) ?? attempts[0];
  const attemptId = chosen.attempt_id;
  // Switching attempts reloads the page for that attempt, so no state carries over between recordings.
  attemptSelect.replaceChildren(...attempts.map((item) => {
    const option = el("option", "", `${item.attempt_id} · ${item.mode}`);
    option.value = item.attempt_id;
    return option;
  }));
  attemptSelect.value = attemptId;
  attemptSelect.disabled = attempts.length < 2;
  attemptSelect.addEventListener("change", () => {
    window.location.search = `?attempt=${encodeURIComponent(attemptSelect.value)}`;
  });
  inspector = new Inspector(
    attemptId,
    document.getElementById("inspector") as HTMLElement,
    document.getElementById("state") as HTMLElement,
    document.getElementById("evidence") as HTMLElement,
  );
  playback = new Playback(controls, selectIndex);
  markRows();
  reportLink.href = `/api/attempts/${encodeURIComponent(attemptId)}/report`;
  reportLink.hidden = false;
  // "Show in timeline" selects the stop step and brings the timeline into view.
  void renderFinal(finalPanel, attemptId, (sequence) => {
    selectEvent(sequence);
    document.getElementById("timeline-pane")!.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  if (chosen.mode === "saved") {
    await loadSaved(attemptId);
  } else {
    mode = "live";
    follow(attemptId, { onAccepted, onProgress, onRecording: applyRecording });
  }
  setMode();
  syncPlayback();
}

// Filters only hide rows; playback and the map still cover every recorded event.
filters.addEventListener("click", (event) => {
  const chosen = (event.target as Element).closest<HTMLButtonElement>("button[data-filter]");
  if (!chosen) {
    return;
  }
  timeline.dataset.filter = chosen.dataset.filter;
  filters.querySelectorAll("button").forEach((button) => button.setAttribute("aria-pressed", String(button === chosen)));
  revealSelected();
});

start().catch((error: unknown) => {
  status.textContent = `failed to load timeline: ${String(error)}`;
});

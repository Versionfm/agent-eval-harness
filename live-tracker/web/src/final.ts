// Final results card, the last section of the page: the finish record's facts and linked artifacts,
// independent of the selected point. It says where the agent loop stopped and where the verdict was decided,
// with the run totals (cost, calls, tokens, duration).
// Loaded once from the final endpoint; nothing here changes with the selection. Evidence uses textContent.

import { count, display, el, kv, money } from "./dom.js";
import { COMPONENTS, TrackerEvent, componentsOf } from "./model.js";

interface StopStep {
  sequence: number;
  type: string;
  operation_id: string | null;
  data: Record<string, any>;
}

export interface FinalResults {
  termination_reason: string;
  functional_verdict: string;
  failure_category: string | null;
  candidate: { status: string; changed_files: string[]; patch: string };
  checks: Record<string, boolean>;
  evaluation_error: string | null;
  recording: { status: string; error: string | null };
  review: { status: string; reviewer?: string; reviewed_at?: string; detail?: string };
  cost: { estimated: any; reported: any };
  model_calls: number | null;
  tokens: { input: number | null; output: number | null; calls_with_usage: number };
  duration_seconds: number | null;
  stop: {
    record: string;
    sequence: number;
    reason: string | null;
    step: StopStep | null;
    model_call?: number;
    loop_step?: number;
    graph_step_count?: number;
  } | null;
}

// Plain-language meaning of each termination reason the harness records.
const REASONS: Record<string, string> = {
  agent_completed: "the model answered without tool calls, so the agent finished",
  model_call_budget: "the model-call budget was used up",
  context_budget: "the conversation outgrew the context budget",
  attempt_deadline: "the attempt deadline passed",
  spending_budget: "the spending budget could not cover another call",
  provider_output_limit: "the model's response hit the output-token limit",
  provider_error: "the provider returned an error",
  graph_step_budget: "the LangGraph step budget was used up",
  interrupted: "the attempt was interrupted",
  harness_error: "the harness raised an error",
};

export function describeRecording(recording: { status: string; error: string | null }): string {
  return recording.error ? `${recording.status}: ${recording.error}` : recording.status;
}

export function describeReview(review: FinalResults["review"]): string {
  if (review.status === "completed") {
    return `completed by ${review.reviewer ?? "unknown reviewer"} at ${review.reviewed_at ?? "unknown time"}`;
  }
  return review.status;
}

// "Model request · model call 7 ok" for the recorded step, named by its map component.
function describeStep(step: StopStep): string {
  const component = componentsOf({ type: step.type, data: step.data } as TrackerEvent)[0];
  const name = COMPONENTS.find((item) => item.id === component)?.label ?? step.type;
  const data = step.data;
  const detail = step.type.startsWith("model.") ? `model call ${data.model_call} ${data.status ?? "started"}`
    : step.type.startsWith("tool.") ? `${data.tool_name} ${data.status ?? "started"}`
      : step.type === "route.decision" ? `next ${data.next} (${data.reason})`
        : step.type;
  return `${name} · ${detail}`;
}

function position(stop: NonNullable<FinalResults["stop"]>): string {
  const parts = [
    stop.model_call !== undefined ? `model call ${stop.model_call}` : "",
    stop.loop_step !== undefined ? `loop step ${stop.loop_step}` : "",
    stop.graph_step_count !== undefined ? `graph step ${stop.graph_step_count}` : "",
  ].filter(Boolean);
  return parts.length ? `Reached ${parts.join(", ")}.` : "";
}

function callout(tone: string, label: string, title: string, body: string, field: string): HTMLElement {
  const box = el("div", `callout ${tone}`);
  const titleLine = el("p", "callout-title");
  titleLine.append(el("span", "callout-label", label), el("span", "", title));
  titleLine.dataset.field = field;
  box.append(titleLine);
  if (body) {
    box.append(el("p", "note", body));
  }
  return box;
}

export async function renderFinal(panel: HTMLElement, attemptId: string, onJump: (sequence: number) => void): Promise<void> {
  const response = await fetch(`/api/attempts/${encodeURIComponent(attemptId)}/final`);
  if (!response.ok) {
    panel.textContent = `Final results unavailable (HTTP ${response.status}).`;
    return;
  }
  const final = (await response.json()) as FinalResults;
  const verdict = final.functional_verdict;
  const entries = Object.entries(final.checks);
  const failed = entries.filter(([, value]) => !value).map(([name]) => name);
  const passed = entries.length - failed.length;

  const head = el("div", "card-head");
  const badges = el("div", "badges");
  badges.append(
    el("span", `badge ${verdict === "success" ? "good" : verdict === "failure" ? "bad" : ""}`, verdict ?? "not recorded"),
    el("span", "badge", final.termination_reason ?? "termination not recorded"),
  );
  head.append(el("h2", "", "Final results"), badges);

  // Where it stopped, then where the verdict was decided.
  const path = el("div", "stop-path");
  const stop = final.stop;
  if (stop) {
    const reason = stop.reason ?? "unknown";
    const where = stop.step ? `#${stop.step.sequence} ${describeStep(stop.step)}` : `#${stop.sequence} ${stop.record}`;
    const box = callout(reason === "agent_completed" ? "good" : "bad", "Stopped at", where,
      `${reason}: ${REASONS[reason] ?? "see the stop record"}. ${position(stop)}`, "stop-step");
    const jump = el("button", "btn btn-ghost", "Show in timeline");
    jump.type = "button";
    jump.addEventListener("click", () => onJump(stop.step?.sequence ?? stop.sequence));
    box.append(jump);
    path.append(box);
  } else {
    path.append(callout("", "Stopped at", "not recorded", "No termination record is in the log yet.", "stop-step"));
  }
  if (verdict === "failure" && failed.length > 0) {
    path.append(callout("bad", "Failed at", `Independent checks · ${failed.length} of ${entries.length} failed`,
      failed.join(", "), "failed-step"));
  } else if (verdict === "failure" || final.failure_category) {
    path.append(callout("bad", "Failed at", display(final.failure_category),
      final.evaluation_error ?? final.recording.error ?? "", "failed-step"));
  }

  const totals = el("div", "tiles totals");
  kv(totals, "total cost (estimated)", money(final.cost?.estimated), "total-cost");
  kv(totals, "total cost (provider-reported)", money(final.cost?.reported), "reported-cost");
  kv(totals, "model calls", final.model_calls, "model-calls");
  kv(totals, "input tokens", count(final.tokens?.input));
  kv(totals, "output tokens", count(final.tokens?.output));
  kv(totals, "duration", typeof final.duration_seconds === "number" ? `${final.duration_seconds.toFixed(1)} s` : undefined);

  const grid = el("div", "final-grid");
  const outcome = el("div");
  outcome.append(el("h3", "", "Outcome"));
  kv(outcome, "termination", final.termination_reason, "termination");
  kv(outcome, "functional verdict", verdict, "functional-verdict");
  kv(outcome, "failure category", final.failure_category ?? "none", "failure-category");
  kv(outcome, "recording", describeRecording(final.recording), "recording");
  kv(outcome, "Codex review", describeReview(final.review), "review");
  kv(outcome, "candidate", final.candidate.status);

  const checks = el("div");
  checks.append(el("h3", "", entries.length ? `Canonical checks · ${passed} of ${entries.length} passed` : "Canonical checks"));
  if (entries.length === 0) {
    checks.append(el("p", "note", final.evaluation_error ?? "No canonical checks were recorded."));
  } else {
    const meter = el("div", "meter");
    const fill = el("span");
    fill.style.width = `${(100 * passed) / entries.length}%`;
    meter.append(fill);
    checks.append(meter);
  }
  const list = el("div", "checks");
  for (const [name, value] of entries) {
    const item = el("p", `check ${value ? "pass" : "fail"}`);
    item.append(el("span", "k", name), el("span", "sep", ": "), el("span", "v", value ? "PASS" : "FAIL"));
    list.append(item);
  }
  checks.append(list);

  const patchBox = el("div", "patch");
  patchBox.append(el("h3", "", "Candidate patch"));
  if (final.candidate.patch === "") {
    patchBox.append(el("p", "note", `No candidate patch is recorded (candidate ${final.candidate.status}).`));
  }
  const patch = el("pre", "", final.candidate.patch);
  patch.dataset.field = "candidate-patch";
  patchBox.append(patch);

  grid.append(outcome, checks, patchBox);
  panel.replaceChildren(head,
    el("p", "note", "Facts from the finish record and linked artifacts. Not the selected point's state."),
    path, totals, grid);
}

// Final results panel: the finish record's facts and linked artifacts, independent of the selected point.
// Loaded once from the final endpoint; nothing here changes with the selection. Evidence uses textContent.

import { el, kv } from "./dom.js";

export interface FinalResults {
  termination_reason: string;
  functional_verdict: string;
  failure_category: string | null;
  candidate: { status: string; changed_files: string[]; patch: string };
  checks: Record<string, boolean>;
  evaluation_error: string | null;
  recording: { status: string; error: string | null };
  review: { status: string; reviewer?: string; reviewed_at?: string; detail?: string };
}

export function describeRecording(recording: { status: string; error: string | null }): string {
  return recording.error ? `${recording.status}: ${recording.error}` : recording.status;
}

export function describeReview(review: FinalResults["review"]): string {
  if (review.status === "completed") {
    return `completed by ${review.reviewer ?? "unknown reviewer"} at ${review.reviewed_at ?? "unknown time"}`;
  }
  return review.status;
}

export async function renderFinal(panel: HTMLElement, attemptId: string): Promise<void> {
  const response = await fetch(`/api/attempts/${encodeURIComponent(attemptId)}/final`);
  if (!response.ok) {
    panel.textContent = `Final results unavailable (HTTP ${response.status}).`;
    return;
  }
  const final = (await response.json()) as FinalResults;
  const root = el("div");
  root.append(el("h2", "", "Final results"));
  root.append(el("p", "note", "Facts from the finish record and linked artifacts. Not the selected point's state."));
  kv(root, "termination", final.termination_reason, "termination");
  kv(root, "functional verdict", final.functional_verdict, "functional-verdict");
  kv(root, "failure category", final.failure_category ?? "none", "failure-category");
  kv(root, "recording", describeRecording(final.recording), "recording");
  kv(root, "Codex review", describeReview(final.review), "review");
  kv(root, "candidate", final.candidate.status);
  root.append(el("h3", "", "Canonical checks"));
  const checks = Object.entries(final.checks);
  if (checks.length === 0) {
    root.append(el("p", "note", final.evaluation_error ?? "No canonical checks were recorded."));
  }
  for (const [name, passed] of checks) {
    kv(root, name, passed ? "PASS" : "FAIL");
  }
  root.append(el("h3", "", "Candidate patch"));
  const patch = el("pre", "", final.candidate.patch);
  patch.dataset.field = "candidate-patch";
  if (final.candidate.patch === "") {
    root.append(el("p", "note", `No candidate patch is recorded (candidate ${final.candidate.status}).`));
  }
  root.append(patch);
  panel.replaceChildren(root);
}

// Final results panel: the finish record's facts and linked artifacts, independent of the selected point.
// Loaded once from the final endpoint; nothing here changes with the selection. Evidence uses textContent.
import { el, kv } from "./dom.js";
export function describeRecording(recording) {
    return recording.error ? `${recording.status}: ${recording.error}` : recording.status;
}
export function describeReview(review) {
    if (review.status === "completed") {
        return `completed by ${review.reviewer ?? "unknown reviewer"} at ${review.reviewed_at ?? "unknown time"}`;
    }
    return review.status;
}
export async function renderFinal(panel, attemptId) {
    const response = await fetch(`/api/attempts/${encodeURIComponent(attemptId)}/final`);
    if (!response.ok) {
        panel.textContent = `Final results unavailable (HTTP ${response.status}).`;
        return;
    }
    const final = (await response.json());
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

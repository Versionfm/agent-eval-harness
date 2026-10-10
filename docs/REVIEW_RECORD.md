# Qualitative review record

The comparison report can display a separate reviewer record for each saved
attempt. A record is evidence of a review performed by the named person; the
report command does not generate findings, scores, or recommendations. Without
a supplied record, the attempt stays marked `Qualitative review pending`.

Save the record outside the harness repository and pass it with
`--python-review` or `--langgraph-review`. The file must be JSON with this
shape:

```json
{
  "schema_version": "1",
  "status": "complete",
  "reviewer": "Reviewer identity",
  "reviewed_at": "2026-10-10T12:00:00Z",
  "attempt": {
    "task_id": "value copied from metadata.json",
    "orchestrator": "python-loop or langgraph",
    "source_revision": "value copied from metadata.json",
    "started_at": "exact value copied from metadata.json"
  },
  "assessment": {
    "diagnosis": "Reviewer-written findings from the recorded evidence.",
    "tool_use": "Reviewer-written findings from the recorded evidence.",
    "patch_quality": "Reviewer-written findings from the recorded evidence.",
    "failures": "Reviewer-written findings, or that no failure was observed."
  },
  "summary": "Reviewer-written conclusion limited to this attempt."
}
```

`reviewed_at` must be an ISO-8601 timestamp with a UTC designator or offset.
The four assessment fields and summary must contain reviewer-written text; the
wording is never inferred from the functional verdict. The attempt identity
must exactly match `task_id`, `orchestrator`, `source_revision`, and `started_at`
in that attempt's `metadata.json`. A mismatch, incomplete record, or invalid
timestamp stops report generation instead of silently presenting a pending or
misattributed review.

Review diagnosis, tool use, patch quality, and failure or recovery evidence
separately from executable acceptance checks. The review is descriptive and
does not change the recorded termination reason, canonical checks, failure
category, or functional verdict. A review of one scripted control does not
apply to another scenario or to a live provider attempt.

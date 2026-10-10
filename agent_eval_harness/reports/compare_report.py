"""Reports · render a local side-by-side report from saved attempt artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
import math
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import quote


_MISSING = object()
_COMPARISON_FIELDS = (
    ("Task definition", (
        "task_id", "task_version", "acceptance_check_version",
        "task_identity", "task_package_sha256",
    )),
    ("Source revision", ("source_revision",)),
    ("Task Dockerfile and runtime", (
        "task_image_evidence.dockerfile_sha256",
        "task_image_evidence.runtime_version",
    )),
    ("Provider and requested model", ("provider", "requested_model")),
    ("Provider endpoint", ("provider_endpoint",)),
    ("Observed model", ("observed_models",)),
    ("Model settings", ("model_settings",)),
    ("Orchestrator dependency versions", ("dependency_versions",)),
    ("Harness revision", ("harness_revision",)),
    ("Initial effective context", ("initial_context_sha256",)),
    ("Attempt budgets", ("budgets",)),
    ("Pricing source", ("pricing_source_url", "pricing_source_checked_at")),
)
_REVIEW_CRITERIA = (
    ("diagnosis", "Diagnosis"),
    ("tool_use", "Tool use"),
    ("patch_quality", "Patch quality"),
    ("failures", "Failures and recovery"),
)


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _load_attempt(artifact_directory: Path) -> dict[str, Any]:
    directory = artifact_directory.expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"Attempt artifact directory does not exist: {directory}")

    required = ("metadata.json", "trace.jsonl", "result.json", "candidate.patch", "checks.json")
    missing = [name for name in required if not (directory / name).is_file()]
    if missing:
        raise ValueError(f"{directory} is missing required attempt artifacts: {', '.join(missing)}")

    metadata = _read_json(directory / "metadata.json")
    result = _read_json(directory / "result.json")
    evaluation = _read_json(directory / "checks.json")
    if not isinstance(metadata, dict) or not isinstance(result, dict):
        raise ValueError(f"{directory} must contain object metadata.json and result.json")
    if not isinstance(evaluation, dict):
        raise ValueError(f"{directory}/checks.json must contain an object")

    trace: list[dict[str, Any]] = []
    with (directory / "trace.jsonl").open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{directory}/trace.jsonl:{line_number}: {exc.msg}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"{directory}/trace.jsonl:{line_number} must be a JSON object")
            trace.append(event)

    candidate = result.get("candidate", {})
    if not isinstance(candidate, dict):
        candidate = {}
    candidate = dict(candidate)
    candidate["patch"] = (directory / "candidate.patch").read_text(encoding="utf-8")
    result_metadata = result.get("metadata", {})
    if not isinstance(result_metadata, dict):
        result_metadata = {}
    return {
        **result,
        "trace": trace,
        "candidate": candidate,
        "evaluation": evaluation,
        "metadata": {**result_metadata, **metadata},
        "artifact_directory": directory,
    }


def _attempt_identity(attempt: dict[str, Any]) -> dict[str, Any]:
    metadata = attempt["metadata"]
    return {
        "task_id": metadata.get("task_id"),
        "orchestrator": metadata.get("orchestrator"),
        "source_revision": metadata.get("source_revision"),
        "started_at": metadata.get("started_at"),
    }


def _load_review(path: Path | None, attempt: dict[str, Any]) -> dict[str, Any] | None:
    if path is None:
        return None
    record = _read_json(path.expanduser().resolve())
    if not isinstance(record, dict):
        raise ValueError(f"Review record must be a JSON object: {path}")
    if record.get("schema_version") != "1" or record.get("status") != "complete":
        raise ValueError(f"Review record must declare schema_version '1' and status 'complete': {path}")
    reviewer = record.get("reviewer")
    reviewed_at = record.get("reviewed_at")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError(f"Review record needs a reviewer identity: {path}")
    if not isinstance(reviewed_at, str):
        raise ValueError(f"Review record needs an ISO-8601 reviewed_at timestamp: {path}")
    try:
        review_time = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Review record reviewed_at must be ISO-8601: {path}") from exc
    if review_time.tzinfo is None or review_time.utcoffset() is None:
        raise ValueError(f"Review record reviewed_at must include a UTC designator or offset: {path}")

    expected = _attempt_identity(attempt)
    actual = record.get("attempt")
    if not isinstance(actual, dict):
        raise ValueError(f"Review record needs an attempt identity: {path}")
    mismatches = [key for key, value in expected.items() if not value or actual.get(key) != value]
    if mismatches:
        raise ValueError(
            f"Review record does not identify this attempt ({', '.join(mismatches)}): {path}"
        )

    assessment = record.get("assessment")
    if not isinstance(assessment, dict):
        raise ValueError(f"Review record needs an assessment object: {path}")
    for key, label in _REVIEW_CRITERIA:
        value = assessment.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Review record needs written {label.lower()} findings: {path}")
    summary = record.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError(f"Review record needs a non-empty summary: {path}")
    return record


def _field_value(metadata: dict[str, Any], keys: tuple[str, ...]) -> Any:
    values = []
    for key in keys:
        value: Any = metadata
        for part in key.split("."):
            value = value.get(part, _MISSING) if isinstance(value, dict) else _MISSING
        values.append(value)
    unavailable = any(value is _MISSING or value is None or value == "" for value in values)
    if "observed_models" in keys and any(value == [] for value in values):
        unavailable = True
    if unavailable:
        return _MISSING
    if len(values) == 1:
        return values[0]
    return {key: value for key, value in zip(keys, values)}


def _same_status(left: Any, right: Any) -> str:
    if left is _MISSING or right is _MISSING:
        return "unavailable"
    return "match" if left == right else "mismatch"


def _json_text(value: Any) -> str:
    if value is _MISSING:
        return "Unavailable"
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _metric_total(records: Any, key: str) -> str:
    if not isinstance(records, list) or not records:
        return "Unavailable"
    values = [
        item[key] for item in records
        if isinstance(item, dict)
        and isinstance(item.get(key), int)
        and not isinstance(item.get(key), bool)
        and item[key] >= 0
    ]
    missing = len(records) - len(values)
    if not values:
        return f"Unavailable ({missing} calls missing)"
    total = sum(values)
    return f"{total:,}" if not missing else f"{total:,} known; {missing} calls missing"


def _usage_rows(metadata: dict[str, Any]) -> str:
    usage = metadata.get("usage_by_call")
    dimensions = (
        ("Input tokens", "prompt_tokens"),
        ("Output tokens", "completion_tokens"),
        ("Reasoning tokens", "reasoning_tokens"),
        ("Cache-hit input tokens", "prompt_cache_hit_tokens"),
        ("Cache-miss input tokens", "prompt_cache_miss_tokens"),
    )
    return "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(_metric_total(usage, key))}</dd>"
        for label, key in dimensions
    )


def _duration(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return "Unavailable"
    seconds = float(value)
    if abs(seconds) < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.2f} s"
    minutes, remaining = divmod(seconds, 60)
    return f"{int(minutes)} min {remaining:.1f} s"


def _latency_label(trace: Any, event_type: str) -> str:
    if not isinstance(trace, list):
        return "Unavailable"
    durations = [
        event["duration_seconds"] for event in trace
        if isinstance(event, dict)
        and event.get("type") == event_type
        and isinstance(event.get("duration_seconds"), (int, float))
        and not isinstance(event.get("duration_seconds"), bool)
        and math.isfinite(event["duration_seconds"])
    ]
    if not durations:
        return "Unavailable"
    return f"{_duration(sum(durations))} across {len(durations)} {event_type} events"


def _money_label(cost: Any, kind: str) -> str:
    metric = cost.get(kind) if isinstance(cost, dict) else None
    if not isinstance(metric, dict):
        return "Unavailable"
    status = str(metric.get("status", "unavailable"))
    amount = metric.get("amount")
    currency = str(metric.get("currency") or "USD")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool):
        missing = metric.get("missing_usage_calls", metric.get("missing_charge_calls", 0))
        suffix = f"; {missing} calls missing" if missing else ""
        return f"{status}: {amount:.8f} {currency}{suffix}"
    missing = metric.get("missing_usage_calls", metric.get("missing_charge_calls", 0))
    missing_label = "usage" if kind == "estimated" else "charge"
    suffix = f"; {missing} calls missing {missing_label}" if missing else ""
    return f"{status}: amount unavailable{suffix}"


def _artifact_href(attempt: dict[str, Any], report_directory: Path, relative: Any) -> str | None:
    if not isinstance(relative, str) or not relative:
        return None
    candidate = Path(relative)
    if candidate.is_absolute():
        return None
    try:
        base = attempt["artifact_directory"].resolve()
        target = (base / candidate).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if target != base and base not in target.parents:
        return None
    if not target.is_file():
        return None
    return quote(Path(os.path.relpath(target, report_directory)).as_posix(), safe="/.-_~")


def _artifact_link(attempt: dict[str, Any], report_directory: Path, relative: str, label: str) -> str:
    href = _artifact_href(attempt, report_directory, relative)
    if href is None:
        return f'<span class="unavailable">{html.escape(label)} unavailable</span>'
    return f'<a href="{html.escape(href, quote=True)}">{html.escape(label)}</a>'


def _pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _tool_call_count(trace: Any) -> str:
    if not isinstance(trace, list):
        return "Unavailable"
    return str(sum(1 for event in trace if isinstance(event, dict) and event.get("type") == "tool"))


def _pricing_evidence(metadata: dict[str, Any]) -> str:
    records = metadata.get("usage_by_call")
    if not isinstance(records, list) or not records:
        return '<p class="unavailable">Per-request pricing details unavailable.</p>'
    rows = []
    for index, usage in enumerate(records, start=1):
        billing = usage.get("billing") if isinstance(usage, dict) else None
        pricing = billing.get("pricing") if isinstance(billing, dict) else None
        if not isinstance(pricing, dict):
            rows.append(f"<li>Request {index}: pricing timestamp and rate band unavailable.</li>")
            continue
        timestamp = html.escape(str(pricing.get("pricing_timestamp_utc", "Unavailable")))
        band = html.escape(str(pricing.get("rate_band", "Unavailable")))
        checked = html.escape(str(pricing.get("source_checked_at", "Unavailable")))
        rows.append(
            f"<li>Request {index}: {timestamp}; {band} rate band; price checked {checked}.</li>"
        )
    return "<ul>" + "".join(rows) + "</ul>"


def _event_markup(
    event: dict[str, Any], attempt: dict[str, Any], report_directory: Path, prefix: str
) -> str:
    event_id = event.get("event_id", "unknown")
    anchor = html.escape(f"{prefix}-event-{event_id}", quote=True)
    event_type = str(event.get("type", "event"))
    if event_type == "model":
        title = f"Model call {event.get('model_call', '?')}"
    elif event_type == "tool":
        title = f"Tool: {event.get('tool_name', 'unknown')}"
    else:
        title = event_type.replace("_", " ").title()
    status = str(event.get("status", event.get("reason", "recorded")))
    duration = _duration(event.get("duration_seconds"))
    body: list[str] = []
    event_links: list[str] = []

    if event_type == "model":
        response = event.get("response", {})
        if isinstance(response, dict):
            content = response.get("content")
            if content is not None:
                body.append(
                    '<details><summary>Model response</summary><pre>'
                    + html.escape(str(content)) + "</pre></details>"
                )
            reasoning = response.get("reasoning_fields")
            if isinstance(reasoning, dict) and reasoning:
                reasoning_anchor = html.escape(f"{prefix}-reasoning-{event_id}", quote=True)
                event_links.append(
                    f'<a href="#{reasoning_anchor}">Open exposed reasoning</a>'
                )
                body.append(
                    f'<details id="{reasoning_anchor}"><summary>Exposed reasoning fields</summary>'
                    f"<pre>{html.escape(_pretty(reasoning))}</pre></details>"
                )
            else:
                body.append('<p class="unavailable">Exposed reasoning unavailable for this response.</p>')
            usage = response.get("usage")
            if usage:
                body.append(
                    "<details><summary>Request usage</summary><pre>"
                    + html.escape(_pretty(usage)) + "</pre></details>"
                )
            tool_calls = response.get("tool_calls")
            if tool_calls:
                body.append(
                    "<details><summary>Model tool requests</summary><pre>"
                    + html.escape(_pretty(tool_calls)) + "</pre></details>"
                )
        request = event.get("request_messages")
        if request:
            body.append(
                "<details class=\"payload\"><summary>Model-visible request context</summary><pre>"
                + html.escape(_pretty(request)) + "</pre></details>"
            )
        if event.get("error"):
            body.append(f'<p class="bad">{html.escape(str(event["error"]))}</p>')
        if event.get("retrying") is True:
            body.append('<p class="unknown">Provider request will be retried.</p>')
        if event.get("status") == "error" and not event.get("error"):
            body.append('<p class="unknown">Provider error details unavailable.</p>')
    elif event_type == "tool":
        arguments = event.get("arguments")
        if arguments is not None:
            body.append(
                "<details><summary>Tool arguments</summary><pre>"
                + html.escape(_pretty(arguments)) + "</pre></details>"
            )
        visible = event.get("model_visible_result")
        if isinstance(visible, dict):
            visible_anchor = html.escape(f"{prefix}-visible-{event_id}", quote=True)
            event_links.append(f'<a href="#{visible_anchor}">Open model-visible result</a>')
            body.append(
                f'<details id="{visible_anchor}"><summary>Exact model-visible tool result</summary><pre>'
                + html.escape(_pretty(visible)) + "</pre></details>"
            )
            if visible.get("truncated"):
                body.append('<p class="unknown">Model-visible output was truncated.</p>')
        else:
            body.append('<p class="unavailable">Model-visible tool result unavailable.</p>')
        result = event.get("result")
        if isinstance(result, dict):
            full_output = result.get("output")
            if full_output is not None:
                body.append(
                    "<details><summary>Full retained tool output</summary><pre>"
                    + html.escape(str(full_output)) + "</pre></details>"
                )
            artifact = result.get("output_artifact")
            if artifact:
                full_output_link = _artifact_link(
                    attempt, report_directory, artifact, "Open full output artifact"
                )
                event_links.append(full_output_link)
                body.append(f'<p class="artifact-link">{full_output_link}</p>')
            elif full_output is None:
                body.append('<p class="unavailable">Full retained output unavailable.</p>')
            error = result.get("error")
            if error:
                body.append(f'<p class="bad">{html.escape(str(error))}</p>')
        error = event.get("error")
        if error:
            body.append(f'<p class="bad">{html.escape(str(error))}</p>')
    else:
        payload = {key: value for key, value in event.items() if key not in {"type", "event_id"}}
        if payload:
            body.append("<pre>" + html.escape(_pretty(payload)) + "</pre>")

    if event_type == "patch_collection":
        event_links.extend((
            f'<a href="#{prefix}-diff">Open candidate diff</a>',
            _artifact_link(attempt, report_directory, "candidate.patch", "candidate.patch"),
        ))
    if event_type == "evaluation":
        event_links.extend((
            f'<a href="#{prefix}-checks">Open canonical check results</a>',
            _artifact_link(attempt, report_directory, "checks.json", "checks.json"),
        ))
    link_markup = (
        '<p class="event-links">' + " · ".join(event_links) + "</p>"
        if event_links else ""
    )

    return (
        f'<details class="event" id="{anchor}"><summary><strong>{html.escape(title)}</strong>'
        f'<span>{html.escape(status)}</span><small>{html.escape(duration)}</small></summary>'
        + link_markup + "".join(body) + "</details>"
    )


def _review_markup(review: dict[str, Any] | None) -> str:
    if review is None:
        return '<p class="unknown">Qualitative review pending.</p>'
    assessment = review["assessment"]
    rows = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(assessment[key])}</dd>"
        for key, label in _REVIEW_CRITERIA
    )
    return (
        f'<p>Reviewed by {html.escape(review["reviewer"])} on '
        f'{html.escape(review["reviewed_at"])}.</p><dl>{rows}</dl>'
        f'<p>{html.escape(review["summary"])}</p>'
    )


def _attempt_panel(
    attempt: dict[str, Any], review: dict[str, Any] | None, report_directory: Path, prefix: str
) -> str:
    metadata = attempt["metadata"]
    verdict = str(attempt.get("functional_verdict", "unavailable"))
    verdict_class = {"success": "good", "failure": "bad", "invalid_environment": "unknown"}.get(
        verdict, "unknown"
    )
    termination = str(attempt.get("termination_reason", "unavailable"))
    duration = attempt.get("duration_seconds", metadata.get("attempt_duration_seconds"))
    cost = metadata.get("cost", {})
    evaluation = attempt.get("evaluation", {})
    checks = evaluation.get("checks", {}) if isinstance(evaluation, dict) else {}
    check_rows = []
    if isinstance(checks, dict):
        for check, passed in checks.items():
            state = "PASS" if passed is True else "FAIL" if passed is False else "UNAVAILABLE"
            css = "good" if passed is True else "bad" if passed is False else "unknown"
            message = evaluation.get("messages", {}).get(check, "") if isinstance(evaluation, dict) else ""
            check_rows.append(
                f'<tr><th>{html.escape(str(check))}</th><td class="{css}">{state}</td>'
                f'<td>{html.escape(str(message))}</td></tr>'
            )
    checks_html = (
        "<table><thead><tr><th>Canonical check</th><th>Result</th><th>Evidence</th></tr></thead><tbody>"
        + "".join(check_rows) + "</tbody></table>"
        if check_rows else '<p class="unknown">Canonical check results unavailable.</p>'
    )
    events = "".join(
        _event_markup(event, attempt, report_directory, prefix)
        for event in attempt.get("trace", [])
    ) or '<p class="unknown">No trace events were recorded.</p>'
    context = attempt.get("initial_context", [])
    patch = attempt.get("candidate", {}).get("patch", "")
    if not patch:
        patch = "No candidate patch was collected."
    observed = metadata.get("observed_models")
    observed_label = ", ".join(observed) if isinstance(observed, list) and observed else "Unavailable"
    pricing = metadata.get("pricing_timestamp_utc", "Unavailable")
    retry_count = metadata.get("retry_count")
    request_count = metadata.get("model_call_count")
    graph_steps = metadata.get("graph_step_count")
    graph_limit = metadata.get("graph_step_limit")
    graph_summary = "Not applicable"
    if metadata.get("orchestrator") == "langgraph":
        graph_summary = f"{graph_steps if graph_steps is not None else 'Unavailable'} / {graph_limit if graph_limit is not None else 'Unavailable'} nodes"

    links = " · ".join((
        _artifact_link(attempt, report_directory, "metadata.json", "metadata.json"),
        _artifact_link(attempt, report_directory, "trace.jsonl", "trace.jsonl"),
        _artifact_link(attempt, report_directory, "result.json", "result.json"),
        _artifact_link(attempt, report_directory, "candidate.patch", "candidate.patch"),
        _artifact_link(attempt, report_directory, "checks.json", "checks.json"),
    ))
    return f"""
    <article class="attempt" aria-labelledby="{prefix}-heading">
      <header class="attempt-header">
        <p class="eyebrow">{html.escape(str(metadata.get('orchestrator', 'Implementation unavailable')))}</p>
        <h2 id="{prefix}-heading">{html.escape(str(metadata.get('task_id', 'Task unavailable')))}</h2>
        <p><span class="badge {verdict_class}">{html.escape(verdict.replace('_', ' '))}</span>
        <span class="termination">Ended: {html.escape(termination)}</span></p>
      </header>
      <dl class="summary">
        <dt>Task revision</dt><dd>{html.escape(str(metadata.get('source_revision', 'Unavailable')))}</dd>
        <dt>Started / finished</dt><dd>{html.escape(str(metadata.get('started_at', 'Unavailable')))} / {html.escape(str(metadata.get('finished_at', 'Unavailable')))}</dd>
        <dt>Duration</dt><dd>{html.escape(_duration(duration))}</dd>
        <dt>Reported charge</dt><dd>{html.escape(_money_label(cost, 'reported'))}</dd>
        <dt>Estimated cost</dt><dd>{html.escape(_money_label(cost, 'estimated'))}</dd>
        <dt>Model requests / retries</dt><dd>{html.escape(str(request_count if request_count is not None else 'Unavailable'))} / {html.escape(str(retry_count if retry_count is not None else 'Unavailable'))}</dd>
        <dt>Tool calls</dt><dd>{html.escape(_tool_call_count(attempt.get('trace')))}</dd>
        <dt>Model latency</dt><dd>{html.escape(_latency_label(attempt.get('trace'), 'model'))}</dd>
        <dt>Tool latency</dt><dd>{html.escape(_latency_label(attempt.get('trace'), 'tool'))}</dd>
        <dt>Observed model</dt><dd>{html.escape(observed_label)}</dd>
        <dt>Provider endpoint</dt><dd>{html.escape(str(metadata.get('provider_endpoint', 'Unavailable')))}</dd>
        <dt>Model settings</dt><dd><pre>{html.escape(_json_text(metadata.get('model_settings', _MISSING)))}</pre></dd>
        <dt>Pricing timestamp</dt><dd>{html.escape(str(pricing))}</dd>
        <dt>Pricing source</dt><dd>{html.escape(str(metadata.get('pricing_source_url', 'Unavailable')))}; checked {html.escape(str(metadata.get('pricing_source_checked_at', 'Unavailable')))}</dd>
        <dt>Per-request pricing</dt><dd><details><summary>Show pricing timestamps and rate bands</summary>{_pricing_evidence(metadata)}</details></dd>
        <dt>Graph nodes / limit</dt><dd>{html.escape(graph_summary)}</dd>
        <dt>Token use</dt><dd><dl class="nested">{_usage_rows(metadata)}</dl></dd>
      </dl>
      <h3>Recorded artifacts</h3><p class="artifact-links">{links}</p>
      <h3>Timeline</h3><div class="timeline">{events}</div>
      <h3>Initial context</h3>
      <details class="initial-context"><summary>Show {len(context) if isinstance(context, list) else 0} initial messages</summary><pre>{html.escape(_pretty(context))}</pre></details>
      <h3>Candidate diff</h3>
      <details class="candidate-diff" id="{prefix}-diff"><summary>Show unified diff</summary><pre>{html.escape(str(patch))}</pre></details>
      <h3>Canonical checks</h3><div id="{prefix}-checks">{checks_html}</div>
      <h3>Codex review</h3><section class="review">{_review_markup(review)}</section>
    </article>"""


def _outcome_card(attempt: dict[str, Any], label: str) -> str:
    metadata = attempt.get("metadata", {})
    verdict = str(attempt.get("functional_verdict", "unavailable"))
    verdict_class = {"success": "good", "failure": "bad", "invalid_environment": "unknown"}.get(
        verdict, "unknown"
    )
    termination = str(attempt.get("termination_reason", "unavailable"))
    duration = attempt.get("duration_seconds", metadata.get("attempt_duration_seconds"))
    cost = metadata.get("cost", {})
    request_count = metadata.get("model_call_count")
    retry_count = metadata.get("retry_count")
    metrics = (
        ("Duration", _duration(duration)),
        (
            "Model requests / retries",
            f"{request_count if request_count is not None else 'Unavailable'} / "
            f"{retry_count if retry_count is not None else 'Unavailable'}",
        ),
        ("Reported charge", _money_label(cost, "reported")),
        ("Estimated cost", _money_label(cost, "estimated")),
    )
    return (
        f'<article class="outcome-card" aria-label="{html.escape(label)} outcome">'
        f'<p class="eyebrow">{html.escape(label)}</p>'
        f'<h2>{html.escape(str(metadata.get("orchestrator", "Implementation unavailable")))}</h2>'
        f'<p><span class="badge {verdict_class}">{html.escape(verdict.replace("_", " "))}</span>'
        f'<span class="termination">Ended: {html.escape(termination)}</span></p>'
        '<dl class="outcome-metrics">'
        + "".join(
            f'<div><dt>{html.escape(name)}</dt><dd>{html.escape(str(value))}</dd></div>'
            for name, value in metrics
        )
        + "</dl></article>"
    )


def _image_audit(python_metadata: dict[str, Any], graph_metadata: dict[str, Any]) -> str:
    values = (
        ("Admission image tag (mutable)", "task_container_image"),
        ("Built task image tag (mutable)", "task_image_evidence.image_tag"),
        ("Admission image ID", "task_image_evidence.admission_image_id"),
        ("Built task image ID", "task_image_evidence.image_id"),
    )
    columns = []
    for label, source in (("Python loop", python_metadata), ("LangGraph", graph_metadata)):
        rows = []
        for title, key in values:
            value: Any = source
            for part in key.split("."):
                value = value.get(part, _MISSING) if isinstance(value, dict) else _MISSING
            rows.append(
                f"<dt>{html.escape(title)}</dt><dd>{html.escape(_json_text(value))}</dd>"
            )
        columns.append(
            f'<section><h3>{label}</h3><dl class="image-audit-values">{"".join(rows)}</dl></section>'
        )
    return (
        '<details class="image-audit"><summary>Image identifiers (audit)</summary>'
        '<p>Configuration parity uses the task Dockerfile SHA-256 and runtime above. '
        'Mutable tags and recorded image IDs are shown for traceability; a matching tag alone does not establish environment parity.</p>'
        f'<div class="config-value-columns">{"".join(columns)}</div></details>'
    )


def render_comparison_report(
    python_attempt: dict[str, Any],
    langgraph_attempt: dict[str, Any],
    *,
    python_review: dict[str, Any] | None = None,
    langgraph_review: dict[str, Any] | None = None,
    report_directory: Path | None = None,
    run_notice: str | None = None,
) -> str:
    """Render two recorded attempt objects with explicit configuration flags."""
    report_directory = (report_directory or Path.cwd()).expanduser().resolve()
    python_metadata = python_attempt.get("metadata", {})
    graph_metadata = langgraph_attempt.get("metadata", {})
    rows = []
    status_counts = {"match": 0, "mismatch": 0, "unavailable": 0}
    for label, keys in _COMPARISON_FIELDS:
        left_value = _field_value(python_metadata, keys)
        right_value = _field_value(graph_metadata, keys)
        status = _same_status(left_value, right_value)
        status_counts[status] += 1
        css = "good" if status == "match" else "bad" if status == "mismatch" else "unknown"
        values = (
            '<details class="config-values"><summary>View compared values</summary>'
            '<div class="config-value-columns">'
            f'<section><h3>Python loop</h3><pre>{html.escape(_json_text(left_value))}</pre></section>'
            f'<section><h3>LangGraph</h3><pre>{html.escape(_json_text(right_value))}</pre></section>'
            '</div></details>'
        )
        rows.append(
            f'<tr><th scope="row">{html.escape(label)}</th>'
            f'<td><span class="status {css}">{html.escape(status)}</span></td><td>{values}</td></tr>'
        )
    overview_items = []
    for key in ("match", "mismatch", "unavailable"):
        count = status_counts[key]
        noun = key if count == 1 or key == "unavailable" else f"{key}es"
        css = "good" if key == "match" else "bad" if key == "mismatch" else "unknown"
        overview_items.append(f'<span class="status {css}">{count} {noun}</span>')
    overview = "".join(overview_items)

    task = python_metadata.get("task_id") or graph_metadata.get("task_id") or "Recorded task comparison"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Attempt comparison · {html.escape(str(task))}</title>
  <style>
    :root {{ color-scheme: light; font: 15px/1.55 system-ui, sans-serif; color: #1c2936; background: #edf1f5; }}
    * {{ box-sizing: border-box; }} body {{ margin: 0; padding: 26px; }} main {{ max-width: 1480px; margin: 0 auto; }}
    h1 {{ margin: 0; font-size: clamp(1.5rem, 2vw, 2rem); }} h2 {{ margin: 0; font-size: 1.25rem; }} h3 {{ margin: 24px 0 8px; font-size: 1.05rem; }}
    .intro, .config, .attempt, .outcome-card {{ background: #fff; border: 1px solid #d5dde6; border-radius: 12px; box-shadow: 0 2px 8px #172b4d0a; }}
    .intro {{ padding: 18px 22px; margin-bottom: 14px; }} .intro p {{ margin: 6px 0 0; }}
    .outcome-pair {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-bottom: 14px; }}
    .outcome-card {{ min-width: 0; padding: 16px 18px; }} .outcome-card h2 {{ margin: 0; }} .outcome-card > p {{ margin: 8px 0; }}
    .outcome-metrics {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 16px; margin: 12px 0 0; }}
    .outcome-metrics div {{ min-width: 0; }} .outcome-metrics dt {{ font-size: .78rem; }} .outcome-metrics dd {{ font-size: .91rem; }}
    .config {{ padding: 16px 18px; margin-bottom: 18px; min-width: 0; }} .config h2 {{ margin-bottom: 8px; }}
    .config-overview {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 10px; }}
    .config-table-scroll {{ max-width: 100%; overflow-x: auto; }} table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; vertical-align: top; border-bottom: 1px solid #e3e9ef; padding: 8px; }}
    .config table {{ min-width: 570px; }} .config th {{ width: 180px; }} .config td:nth-child(2) {{ width: 118px; }}
    .status {{ display: inline-block; border-radius: 20px; padding: 2px 9px; font-size: .83rem; font-weight: 700; text-transform: capitalize; }}
    .config-values {{ margin: 0; }} .config-value-columns {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .config-value-columns section {{ min-width: 0; }} .config-value-columns h3 {{ margin: 8px 0 0; font-size: .9rem; }}
    .image-audit-values {{ display: grid; grid-template-columns: minmax(145px, .7fr) minmax(0, 1.3fr); gap: 5px 10px; }}
    .pair {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; align-items: start; }}
    .attempt {{ min-width: 0; overflow: hidden; }} .attempt-header {{ background: #f8fafc; padding: 18px 20px; border-bottom: 1px solid #e3e9ef; }}
    .attempt-header p {{ margin: 8px 0 0; }} .eyebrow {{ color: #526274; text-transform: uppercase; letter-spacing: .08em; font-size: .75rem; font-weight: 700; }}
    .termination {{ margin-left: 10px; color: #465567; }} .attempt > h3, .attempt > dl, .attempt > p, .attempt > details, .attempt > div, .attempt > section {{ margin-left: 20px; margin-right: 20px; }}
    .summary {{ display: grid; grid-template-columns: minmax(130px, .65fr) minmax(0, 1.35fr); gap: 5px 12px; margin-top: 16px; }}
    dt {{ color: #536477; font-weight: 600; }} dd {{ margin: 0; min-width: 0; overflow-wrap: anywhere; }} .nested {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; }}
    .badge {{ display: inline-block; border-radius: 20px; padding: 2px 10px; font-size: .83rem; font-weight: 700; text-transform: capitalize; }}
    .good {{ color: #14532d; background: #dcfce7; }} .bad {{ color: #991b1b; background: #fee2e2; }} .unknown {{ color: #713f12; background: #fef3c7; }}
    .unavailable {{ color: #6b7280; }} .artifact-links {{ line-height: 1.9; }} a {{ color: #075985; }}
    details {{ margin: 8px 0; border: 1px solid #e0e6ed; border-radius: 7px; padding: 8px 10px; min-width: 0; }}
    summary {{ cursor: pointer; font-weight: 600; }} .event summary span {{ margin-left: 10px; color: #536477; font-weight: 400; }} .event summary small {{ float: right; color: #536477; font-weight: 400; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; max-width: 100%; overflow-x: auto; margin: 8px 0 0; padding: 10px; background: #f5f7f9; border-radius: 6px; font: 12.5px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; }}
    .summary pre {{ margin: 0; }} .bad:not(.badge) {{ color: #8f1d1d; }} .review {{ padding-bottom: 20px; }}
    .event-links {{ margin: 8px 0; font-size: .88rem; }}
    @media (max-width: 760px) {{ body {{ padding: 14px; }} .pair {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 570px) {{ .outcome-pair {{ grid-template-columns: 1fr; }} .outcome-metrics, .config-value-columns {{ grid-template-columns: 1fr; }} .summary {{ grid-template-columns: 1fr; }} .summary dt {{ margin-top: 6px; }} .nested {{ grid-template-columns: 1fr; }} .attempt-header, .intro {{ padding: 16px; }} }}
  </style>
</head>
<body><main>
  <section class="intro"><h1>Python loop and LangGraph comparison</h1>
    <p>Task: <strong>{html.escape(str(task))}</strong>. Functional verdicts come from canonical checks. Termination describes why each attempt stopped.</p>
    {f'<p class="run-notice">{html.escape(run_notice)}</p>' if run_notice else ''}
    <p>Compare token counts and latency separately from money: cache warmth and pricing periods can change estimated cost. Reported charges, estimates, and unavailable values stay separate.</p>
  </section>
  <section class="outcome-pair" aria-label="Attempt outcome summary">
    {_outcome_card(python_attempt, 'Python loop')}
    {_outcome_card(langgraph_attempt, 'LangGraph')}
  </section>
  <section class="config"><h2>Configuration match</h2>
    <div class="config-overview" aria-label="Configuration status counts">{overview}</div>
    <div class="config-table-scroll" tabindex="0" aria-label="Scrollable configuration comparison">
    <table><thead><tr><th scope="col">Dimension</th><th scope="col">Status</th><th scope="col">Compared values</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table>
    </div>
    {_image_audit(python_metadata, graph_metadata)}
  </section>
  <section class="pair">
    {_attempt_panel(python_attempt, python_review, report_directory, 'python')}
    {_attempt_panel(langgraph_attempt, langgraph_review, report_directory, 'langgraph')}
  </section>
</main></body></html>
"""


def build_comparison_report(
    python_directory: Path,
    langgraph_directory: Path,
    output_path: Path,
    *,
    python_review_path: Path | None = None,
    langgraph_review_path: Path | None = None,
    run_notice: str | None = None,
) -> Path:
    """Build a report from persisted files only; this function never runs an attempt."""
    python_attempt = _load_attempt(python_directory)
    langgraph_attempt = _load_attempt(langgraph_directory)
    python_review = _load_review(python_review_path, python_attempt)
    langgraph_review = _load_review(langgraph_review_path, langgraph_attempt)
    destination = output_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_comparison_report(
        python_attempt,
        langgraph_attempt,
        python_review=python_review,
        langgraph_review=langgraph_review,
        report_directory=destination.parent,
        run_notice=run_notice,
    )
    destination.write_text(rendered, encoding="utf-8")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-loop", type=Path, required=True, help="saved Python-loop attempt directory")
    parser.add_argument("--langgraph", type=Path, required=True, help="saved LangGraph attempt directory")
    parser.add_argument("--output", type=Path, required=True, help="destination HTML file")
    parser.add_argument("--python-review", type=Path, help="validated Codex review record JSON for the Python attempt")
    parser.add_argument("--langgraph-review", type=Path, help="validated Codex review record JSON for the LangGraph attempt")
    args = parser.parse_args(argv)
    try:
        report = build_comparison_report(
            args.python_loop,
            args.langgraph,
            args.output,
            python_review_path=args.python_review,
            langgraph_review_path=args.langgraph_review,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())

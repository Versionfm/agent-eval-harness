"""Local HTML rendering for one scripted coding-agent attempt."""

from __future__ import annotations

import html
import json
import math
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote


def _pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _duration_label(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return "Unavailable"
    seconds = float(value)
    if abs(seconds) < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.2f} s"
    minutes, remaining = divmod(seconds, 60)
    return f"{int(minutes)} min {remaining:.1f} s"


def _money_label(metric: Any, *, label: str) -> str:
    if not isinstance(metric, dict):
        return f"{label} unavailable"
    status = str(metric.get("status", "unavailable"))
    amount = metric.get("amount")
    currency = str(metric.get("currency") or "USD")
    if isinstance(amount, (int, float)) and status not in {"unavailable", "missing"}:
        return f"{status}: {amount:.8f} {currency}"
    return f"{status}: amount unavailable"


def _usage_label(records: Any) -> str:
    if not isinstance(records, list) or not records:
        return "Unavailable"

    def total(key: str) -> str:
        values = [
            value[key] for value in records
            if isinstance(value, dict)
            and isinstance(value.get(key), int)
            and not isinstance(value.get(key), bool)
        ]
        if not values:
            return "unavailable"
        amount = sum(values)
        missing = len(records) - len(values)
        return f"{amount}" if not missing else f"{amount} known, {missing} missing"

    return (
        f"input {total('prompt_tokens')}; output {total('completion_tokens')}; "
        f"reasoning {total('reasoning_tokens')}; "
        f"cache hit {total('prompt_cache_hit_tokens')} / "
        f"miss {total('prompt_cache_miss_tokens')}"
    )


def _artifact_href(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = PurePosixPath(value)
    if (path.is_absolute() or "\\" in value or any(ord(char) < 32 for char in value)
            or any(part in {"", ".", ".."} for part in path.parts)):
        return None
    return html.escape(quote(path.as_posix(), safe="/"), quote=True)


def _recording_label(recording: Any) -> str:
    """Recording completeness, kept apart from the termination reason and the verdict."""
    if not isinstance(recording, dict):
        return "not observed (no attempt event log)"
    status = str(recording.get("status", "unknown"))
    error = recording.get("error")
    return f"{status}: {error}" if error else status


def _review_label(review: Any) -> str:
    if isinstance(review, dict) and review.get("status") == "completed":
        return f"Qualitative review completed by {review.get('reviewer')} at {review.get('reviewed_at')}"
    return "Qualitative review pending"


def render_attempt_report(result: dict[str, Any]) -> str:
    metadata = result.get("metadata", {})
    verdict = str(result.get("functional_verdict", "invalid_environment"))
    termination = str(result.get("termination_reason", "harness_error"))
    verdict_class = {"success": "good", "failure": "bad", "invalid_environment": "unknown"}.get(
        verdict, "unknown"
    )

    event_cards = []
    for index, event in enumerate(result.get("trace", []), 1):
        event_id = event.get("event_id")
        if not isinstance(event_id, int) or isinstance(event_id, bool) or event_id < 1:
            event_id = index
        event_anchor = f"event-{event_id}"
        payload_anchor = f"{event_anchor}-payload"
        links = []
        if event.get("type") == "model":
            links.append(
                f'<a href="#{payload_anchor}">Open reasoning and response evidence</a>'
            )
        elif event.get("type") == "tool":
            visible_anchor = f"{event_anchor}-visible"
            full_anchor = f"{event_anchor}-full-output"
            links.append(f'<a href="#{payload_anchor}">Open call arguments and result metadata</a>')
            links.append(f'<a href="#{visible_anchor}">Open model-visible result</a>')
            links.append(f'<a href="#{full_anchor}">Open full tool output</a>')
            tool_result = event.get("result", {})
            artifact = _artifact_href(
                tool_result.get("output_artifact") if isinstance(tool_result, dict) else None
            )
            if artifact:
                links.append(f'<a href="{artifact}">Open output artifact</a>')
        elif event.get("type") == "patch_collection":
            links.extend((
                '<a href="#candidate-diff">Open candidate diff</a>',
                '<a href="candidate.patch">Open candidate.patch</a>',
            ))
        elif event.get("type") == "evaluation":
            links.extend((
                '<a href="#canonical-checks">Open canonical checks</a>',
                '<a href="checks.json">Open checks.json</a>',
            ))
        event_type = html.escape(str(event.get("type", "event")))
        title = event_type.title()
        if event.get("type") == "tool":
            title = f"Tool: {event.get('tool_name', 'unknown')}"
        elif event.get("type") == "model":
            title = f"Model call {event.get('model_call', '?')}"
        headline = html.escape(title)
        status = html.escape(str(event.get("status", "recorded")))
        duration = html.escape(_duration_label(event.get("duration_seconds")))
        truncation = ""
        visible_result = event.get("model_visible_result", {})
        if isinstance(visible_result, dict) and visible_result.get("truncated"):
            output_artifact = event.get("result", {}).get("output_artifact")
            artifact = _artifact_href(output_artifact)
            artifact_link = (
                f'<a href="{artifact}">{html.escape(str(output_artifact))}</a>'
                if artifact else "unavailable"
            )
            truncation = (
                "<p class=\"unknown\">Model-visible output was truncated; full output artifact: "
                f"{artifact_link}</p>"
            )
        event_links = (
            '<p class="event-links">' + " · ".join(links) + "</p>" if links else ""
        )
        if event.get("type") == "tool":
            tool_result = event.get("result", {})
            tool_metadata = {
                key: event.get(key)
                for key in (
                    "timestamp", "tool_name", "tool_call_id", "arguments", "status",
                    "duration_seconds",
                )
            }
            tool_metadata["result"] = (
                {key: value for key, value in tool_result.items() if key != "output"}
                if isinstance(tool_result, dict) else tool_result
            )
            call_detail = (
                f'<details id="{payload_anchor}"><summary>Tool call arguments and result metadata</summary><pre>'
                + html.escape(_pretty(tool_metadata)) + "</pre></details>"
            )
            visible_detail = (
                f'<details id="{visible_anchor}"><summary>Exact model-visible result</summary><pre>'
                + html.escape(_pretty(visible_result)) + "</pre></details>"
                if isinstance(visible_result, dict) else ""
            )
            full_output = tool_result.get("output") if isinstance(tool_result, dict) else None
            full_detail = (
                f'<details id="{full_anchor}"><summary>Full retained tool output</summary><pre>'
                + html.escape(str(full_output)) + "</pre></details>"
                if full_output is not None else ""
            )
            payload_html = truncation + call_detail + visible_detail + full_detail
        else:
            payload_html = truncation + (
                f'<details id="{payload_anchor}"><summary>Recorded evidence</summary><pre>'
                + html.escape(_pretty(event)) + "</pre></details>"
            )
        event_cards.append(
            f'<details class="event" id="{event_anchor}"><summary>'
            f"<strong>{headline}</strong> <span>{status}</span> <small>{duration}</small>"
            "</summary>" + event_links + payload_html + "</details>"
        )

    evaluation = result.get("evaluation", {})
    check_rows = []
    for check_id, passed in evaluation.get("checks", {}).items():
        state = "PASS" if passed is True else "FAIL"
        css = "good" if passed is True else "bad"
        message = evaluation.get("messages", {}).get(check_id, "")
        check_rows.append(
            f"<tr><th>{html.escape(str(check_id))}</th><td class=\"{css}\">{state}</td>"
            f"<td>{html.escape(str(message))}</td></tr>"
        )
    check_table = (
        "<table><thead><tr><th>Acceptance check</th><th>Result</th><th>Evidence</th></tr></thead><tbody>"
        + "".join(check_rows)
        + "</tbody></table>"
        if check_rows
        else f"<p class=\"unknown\">{html.escape(str(evaluation.get('error', 'No evaluator result')))}</p>"
    )

    diff = str(result.get("candidate", {}).get("patch", "")) or "No repository changes were collected."
    initial_context = result.get("initial_context", [])
    cost = metadata.get("cost", {})
    estimated_cost = cost.get("estimated", {}) if isinstance(cost, dict) else {}
    reported_cost = cost.get("reported", {}) if isinstance(cost, dict) else {}
    spend_budget = metadata.get("spend_budget", {})
    if isinstance(spend_budget, dict) and spend_budget:
        reserved = spend_budget.get("reserved_or_estimated_usd", "unavailable")
        limit = spend_budget.get("limit_usd", "unavailable")
        remaining = spend_budget.get("remaining_usd", "unavailable")
        spend_label = (
            f"{reserved} USD reserved or estimated of {limit} USD; "
            f"{remaining} USD remains"
        )
    else:
        spend_label = "Unavailable"
    cost_fallback = (
        "Cost unavailable"
        if estimated_cost.get("status", "unavailable") == "unavailable"
        and reported_cost.get("status", "unavailable") == "unavailable"
        else "Reported charges and estimates are shown separately above."
    )
    metadata_rows = {
        "Task": metadata.get("task_id", "unavailable"),
        "Source revision": metadata.get("source_revision", "unavailable"),
        "Harness revision": _pretty(metadata.get("harness_revision", "unavailable")),
        "Dependency versions": _pretty(metadata.get("dependency_versions", "unavailable")),
        "Model": metadata.get("requested_model", "unavailable"),
        "Observed model": ", ".join(metadata.get("observed_models", [])) or "unavailable",
        "Provider endpoint": metadata.get("provider_endpoint", "unavailable"),
        "Model settings": _pretty(metadata.get("model_settings", {})),
        "Pricing source": metadata.get("pricing_source_url", "unavailable"),
        "Pricing checked": metadata.get("pricing_source_checked_at", "unavailable"),
        "Pricing timestamp": metadata.get("pricing_timestamp_utc", "unavailable"),
        "Orchestrator": metadata.get("orchestrator", "unavailable"),
        "Graph node steps": metadata.get("graph_step_count", "not applicable"),
        "Graph node step limit": metadata.get("graph_step_limit", "not applicable"),
        "Graph limit source": metadata.get("graph_step_limit_source", "not applicable"),
        "Termination": termination,
        "Functional verdict": verdict,
        "Failure category": result.get("failure_category", "none"),
        "Duration": _duration_label(result.get("duration_seconds")),
        "Attempt duration": _duration_label(metadata.get("attempt_duration_seconds")),
        "Model requests / retries": (
            f"{metadata.get('model_call_count', 'unavailable')} / "
            f"{metadata.get('retry_count', 'unavailable')}"
        ),
        "Candidate artifacts": result.get("candidate", {}).get("status", "unavailable"),
        "Token usage": _usage_label(metadata.get("usage_by_call", [])),
        "Reported charge": _money_label(reported_cost, label="Reported charge"),
        "Estimated cost": _money_label(estimated_cost, label="Estimated cost"),
        "USD spending ceiling": spend_label,
        "Recording": _recording_label(result.get("recording")),
        "Qualitative review": _review_label(metadata.get("qualitative_review")),
    }
    rows = "".join(
        f"<dt>{html.escape(str(key))}</dt><dd>{html.escape(str(value))}</dd>"
        for key, value in metadata_rows.items()
    )
    context_count = len(initial_context) if isinstance(initial_context, (list, dict)) else 0
    initial = (
        '<details class="initial-context"><summary>Show '
        f"{context_count} initial messages</summary><pre>"
        + html.escape(_pretty(initial_context)) + "</pre></details>"
    )
    event_html = "".join(event_cards) or "<p>No model or tool events were recorded.</p>"
    error = result.get("harness_error")
    error_html = f"<p class=\"bad\">{html.escape(str(error))}</p>" if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Coding-agent attempt report</title>
  <style>
    :root {{ color-scheme: light; font: 15px/1.55 system-ui, sans-serif; color: #1f2933; background: #f3f5f7; }}
    body {{ max-width: 1050px; margin: 28px auto; padding: 0 18px; }}
    main {{ background: #fff; border: 1px solid #d8dee5; border-radius: 12px; padding: 26px; }}
    h1 {{ margin: 0; font-size: 1.65rem; }} h2 {{ margin-top: 28px; font-size: 1.2rem; }}
    dl {{ display: grid; grid-template-columns: 190px 1fr; gap: 5px 14px; }} dt {{ color: #526170; }} dd {{ margin: 0; overflow-wrap: anywhere; }}
    .badge {{ display: inline-block; padding: 2px 10px; border-radius: 99px; font-weight: 700; }}
    .good {{ color: #14532d; background: #dcfce7; }} .bad {{ color: #991b1b; background: #fee2e2; }}
    .unknown {{ color: #713f12; background: #fef3c7; }}
    table {{ width: 100%; border-collapse: collapse; }} th, td {{ text-align: left; vertical-align: top; border-bottom: 1px solid #e5eaf0; padding: 8px; }}
    details {{ margin: 8px 0; border: 1px solid #e5eaf0; border-radius: 8px; padding: 9px 12px; }}
    summary {{ cursor: pointer; }} summary span {{ margin-left: 12px; color: #526170; }} summary small {{ float: right; color: #526170; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #f7f8fa; padding: 12px; border-radius: 6px; }}
    @media (max-width: 650px) {{ main {{ padding: 16px; }} dl {{ grid-template-columns: 1fr; }} dd {{ margin-bottom: 6px; }} }}
  </style>
</head>
<body><main>
  <h1>Coding-agent attempt</h1>
  <p><span class="badge {verdict_class}">{html.escape(verdict.replace('_', ' '))}</span></p>
  <dl>{rows}</dl>
  {error_html}
  <h2>Initial context</h2>{initial}
  <h2>Attempt timeline</h2>{event_html}
  <h2 id="candidate-diff">Candidate patch</h2><pre>{html.escape(diff)}</pre>
  <h2 id="canonical-checks">Fresh canonical evaluation</h2>{check_table}
  <p>{html.escape(cost_fallback)} {html.escape(_review_label(metadata.get("qualitative_review")))}.</p>
</main></body></html>
"""

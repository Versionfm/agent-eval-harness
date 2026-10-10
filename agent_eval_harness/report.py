"""Local HTML rendering for one scripted coding-agent attempt."""

from __future__ import annotations

import html
import json
from typing import Any


def _pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


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


def render_attempt_report(result: dict[str, Any]) -> str:
    metadata = result.get("metadata", {})
    verdict = str(result.get("functional_verdict", "invalid_environment"))
    termination = str(result.get("termination_reason", "harness_error"))
    verdict_class = {"success": "good", "failure": "bad", "invalid_environment": "unknown"}.get(
        verdict, "unknown"
    )

    event_cards = []
    for event in result.get("trace", []):
        event_type = html.escape(str(event.get("type", "event")))
        title = event_type.title()
        if event.get("type") == "tool":
            title = f"Tool: {event.get('tool_name', 'unknown')}"
        elif event.get("type") == "model":
            title = f"Model call {event.get('model_call', '?')}"
        headline = html.escape(title)
        status = html.escape(str(event.get("status", "recorded")))
        duration = html.escape(str(event.get("duration_seconds", "unavailable")))
        truncation = ""
        visible_result = event.get("model_visible_result", {})
        if visible_result.get("truncated"):
            output_artifact = event.get("result", {}).get("output_artifact", "unavailable")
            truncation = (
                "<p class=\"unknown\">Model-visible output was truncated; full output artifact: "
                f"{html.escape(str(output_artifact))}</p>"
            )
        event_cards.append(
            "<details class=\"event\"><summary>"
            f"<strong>{headline}</strong> <span>{status}</span> <small>{duration}s</small>"
            "</summary>" + truncation + "<pre>" + html.escape(_pretty(event)) + "</pre></details>"
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
        "Model": metadata.get("requested_model", "unavailable"),
        "Observed model": ", ".join(metadata.get("observed_models", [])) or "unavailable",
        "Provider endpoint": metadata.get("provider_endpoint", "unavailable"),
        "Model settings": _pretty(metadata.get("model_settings", {})),
        "Pricing source": metadata.get("pricing_source_url", "unavailable"),
        "Pricing checked": metadata.get("pricing_source_checked_at", "unavailable"),
        "Pricing timestamp": metadata.get("pricing_timestamp_utc", "unavailable"),
        "Orchestrator": metadata.get("orchestrator", "unavailable"),
        "Termination": termination,
        "Functional verdict": verdict,
        "Failure category": result.get("failure_category", "none"),
        "Duration": f"{result.get('duration_seconds', 'unavailable')} seconds",
        "Attempt duration": f"{metadata.get('attempt_duration_seconds', 'unavailable')} seconds",
        "Model requests / retries": (
            f"{metadata.get('model_call_count', 'unavailable')} / "
            f"{metadata.get('retry_count', 'unavailable')}"
        ),
        "Candidate artifacts": result.get("candidate", {}).get("status", "unavailable"),
        "Token usage": _usage_label(metadata.get("usage_by_call", [])),
        "Reported charge": _money_label(reported_cost, label="Reported charge"),
        "Estimated cost": _money_label(estimated_cost, label="Estimated cost"),
        "USD spending ceiling": spend_label,
        "Qualitative review": "Qualitative review pending",
    }
    rows = "".join(
        f"<dt>{html.escape(str(key))}</dt><dd>{html.escape(str(value))}</dd>"
        for key, value in metadata_rows.items()
    )
    initial = "<pre>" + html.escape(_pretty(initial_context)) + "</pre>"
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
  <h2>Candidate patch</h2><pre>{html.escape(diff)}</pre>
  <h2>Fresh canonical evaluation</h2>{check_table}
  <p>{html.escape(cost_fallback)} Qualitative review pending.</p>
</main></body></html>
"""

"""Run one observed matched pair: both attempts recorded live through the existing coordinator.

Usage: PYTHONPATH=live-tracker/src python -m live_tracker.run_matched --credential-file PATH
       [--artifact-dir DIR] [--port N] [--shared-budget-usd 0.10] [--smoke-budget-usd 0.01]
       [--attempt-budget-usd 0.04]
The coordinator (agent_eval_harness.cli.run_matched_comparison) still owns execution, the shared ledger,
and the comparison report. This module only attaches one recorder per attempt, projects each finished
attempt from its log, serves both attempts in the workbench, and writes live-pair.json with the
retained accounting, overhead, pricing and pending review status. The output directory must not exist
and must be outside both repositories. The viewer URLs are printed before the first provider request.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable, Mapping
import uuid

from agent_eval_harness.cli import run_matched_comparison as coordinator
from agent_eval_harness.bench.attempt import DEFAULT_ADMISSION_EVIDENCE, DEFAULT_SOURCE_REPOSITORY, ORCHESTRATION_ROOT
from agent_eval_harness.harness.deepseek import (
    PRICING_SOURCE_CHECKED_AT,
    PRICING_SOURCE_URL,
    USD_PER_MILLION_OFFPEAK,
    USD_PER_MILLION_PEAK,
    JsonTransport,
)
from agent_eval_harness.harness.hooks import AttemptEventSink
from live_tracker.projection import review_status, write_projection
from live_tracker.reader import read_attempt_history
from live_tracker.recorder import AttemptRecorder, DurableStorage
from live_tracker.server import make_server


ORCHESTRATORS = ("python-loop", "langgraph")
SCHEMA = "agent-eval-harness/live-pair"
SCHEMA_VERSION = 1
MANIFEST_NAME = "live-pair.json"
# Combined ceiling USD 0.10; the stage ceilings sum to 0.09 (smoke 0.01 plus two attempts at 0.04).
DEFAULT_SHARED_BUDGET_USD = 0.10
DEFAULT_SMOKE_BUDGET_USD = 0.01
DEFAULT_ATTEMPT_BUDGET_USD = 0.04
DEFAULT_PORT = 8765


class TimedSink:
    """Passes events to a recorder and measures the time it spends, so overhead is reported, not assumed."""

    def __init__(self, sink: AttemptEventSink):
        self.sink = sink
        self.events = 0
        self.seconds = 0.0

    def emit(self, event_type, data, artifacts=None, *, operation_id=None, parent_operation_id=None) -> None:
        started = time.perf_counter()
        self.events += 1
        try:
            self.sink.emit(event_type, data, artifacts,
                           operation_id=operation_id, parent_operation_id=parent_operation_id)
        finally:
            self.seconds += time.perf_counter() - started


def pricing_provenance() -> dict[str, Any]:
    """The rate table the adapter uses to estimate cost, with its source and check date."""
    return {
        "source_url": PRICING_SOURCE_URL,
        "source_checked_at": PRICING_SOURCE_CHECKED_AT,
        "rates_usd_per_million_tokens": {"peak": dict(USD_PER_MILLION_PEAK),
                                         "offpeak": dict(USD_PER_MILLION_OFFPEAK)},
        "peak_band_utc": "Monday to Friday, 01:00-03:59 and 06:00-09:59 UTC, outside declared holidays",
        "reported_cost_source": "not provided by the DeepSeek response; amounts are usage-based estimates",
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _usage_totals(calls: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
            "reasoning_tokens")
    totals = {key: sum(call[key] for call in calls if isinstance(call.get(key), int)) for key in keys}
    estimates = [call.get("billing", {}).get("estimated_cost", {}).get("amount") for call in calls]
    reported = [call.get("billing", {}).get("reported_cost", {}).get("status") for call in calls]
    totals["calls"] = len(calls)
    totals["estimated_cost_usd"] = (
        round(sum(estimates), 12) if calls and all(isinstance(value, (int, float)) for value in estimates)
        else "unavailable"
    )
    totals["reported_cost_usd"] = (
        "unavailable" if not calls or any(status != "available" for status in reported)
        else round(sum(call["billing"]["reported_cost"]["amount"] for call in calls), 12)
    )
    return totals


def build_manifest(
    root: Path,
    experiment: Mapping[str, Any],
    timed: Mapping[str, TimedSink],
    attempt_ids: Mapping[str, str],
    *,
    budgets: Mapping[str, Any],
) -> dict[str, Any]:
    attempts: dict[str, Any] = {}
    for orchestrator in ORCHESTRATORS:
        directory = root / orchestrator
        summary = experiment.get("attempts", {}).get(orchestrator, {"status": "not_started"})
        entry: dict[str, Any] = {
            "attempt_id": attempt_ids[orchestrator],
            "directory": str(directory),
            "status": summary.get("status"),
            "termination_reason": summary.get("termination_reason"),
            "recorded_attempt_verdict": summary.get("recorded_attempt_verdict"),
            "agent_repair_assessment": summary.get("agent_repair_assessment"),
            "valid_measurement": summary.get("valid_measurement"),
            "invalid_reason": summary.get("invalid_reason"),
            "qualitative_review": {"status": "pending"},
        }
        if directory.is_dir():
            calls = experiment.get("usage_by_orchestrator", {}).get(orchestrator, [])
            result_path = directory / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
            duration = result.get("duration_seconds")
            entry.update({
                "recording": read_attempt_history(directory).status(),
                "requested_model": experiment.get("requested_model"),
                "observed_models": sorted({call["observed_model"] for call in calls
                                           if call.get("observed_model")}),
                "usage": _usage_totals(calls),
                "duration_seconds": duration,
                "deadline": {
                    "limit_seconds": budgets["attempt_deadline_seconds"],
                    "used_fraction": round(duration / budgets["attempt_deadline_seconds"], 6)
                    if isinstance(duration, (int, float)) else None,
                    "deadline_stop": summary.get("termination_reason") == "attempt_deadline",
                },
                "qualitative_review": review_status(directory),
            })
            if orchestrator in timed:
                observer = timed[orchestrator]
                entry["overhead"] = {
                    "observer_events": observer.events,
                    "observer_seconds": round(observer.seconds, 6),
                    "share_of_attempt": round(observer.seconds / duration, 6)
                    if isinstance(duration, (int, float)) and duration > 0 else None,
                }
        attempts[orchestrator] = entry
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "completed_at": _utc_now(),
        "status": experiment.get("status"),
        "valid_measurement": experiment.get("valid_measurement"),
        "execution_mode": experiment.get("execution_mode"),
        "live_measurement": experiment.get("live_measurement"),
        "live_acceptance_status": experiment.get("live_acceptance_status"),
        "budgets_usd": {
            "combined_ceiling": budgets["shared_budget_usd"],
            "smoke": budgets["smoke_budget_usd"],
            "per_attempt": budgets["attempt_budget_usd"],
            "stage_sum": budgets["smoke_budget_usd"] + 2 * budgets["attempt_budget_usd"],
        },
        "effective_settings": {key: budgets[key] for key in (
            "max_output_tokens", "max_model_calls", "max_context_bytes", "attempt_deadline_seconds",
            "shell_timeout_seconds")},
        "pricing": pricing_provenance(),
        "shared_spend_budget": experiment.get("shared_spend_budget"),
        "attempts": attempts,
        "smoke_artifact": experiment.get("smoke_artifact"),
        "report": experiment.get("report"),
        "experiment": str(root / "experiment.json"),
    }


def run_live_pair(
    *,
    credential_file: Path,
    artifact_directory: Path,
    attempt_ids: Mapping[str, str],
    admission_evidence: Path = DEFAULT_ADMISSION_EVIDENCE,
    parity_evidence: Path = coordinator.DEFAULT_PARITY_EVIDENCE,
    source_repository: Path = DEFAULT_SOURCE_REPOSITORY,
    shared_budget_usd: float = DEFAULT_SHARED_BUDGET_USD,
    smoke_budget_usd: float = DEFAULT_SMOKE_BUDGET_USD,
    attempt_budget_usd: float = DEFAULT_ATTEMPT_BUDGET_USD,
    max_model_calls: int = coordinator.DEFAULT_MAX_MODEL_CALLS,
    max_context_bytes: int = coordinator.DEFAULT_MAX_CONTEXT_BYTES,
    attempt_deadline_seconds: float = coordinator.DEFAULT_ATTEMPT_DEADLINE_SECONDS,
    shell_timeout_seconds: int = coordinator.DEFAULT_SHELL_TIMEOUT_SECONDS,
    max_output_tokens: int = coordinator.DEFAULT_MAX_OUTPUT_TOKENS,
    storage_for: Callable[[str], DurableStorage | None] | None = None,
    transport: JsonTransport | None = None,
) -> dict[str, Any]:
    """Run the matched pair through the coordinator with one observed recorder per attempt."""
    if set(attempt_ids) != set(ORCHESTRATORS):
        raise ValueError("attempt_ids must name exactly the python-loop and langgraph attempts")
    root = Path(artifact_directory).expanduser().resolve()
    timed: dict[str, TimedSink] = {}

    def observe(orchestrator: str, directory: Path) -> TimedSink:
        storage = storage_for(orchestrator) if storage_for is not None else None
        timed[orchestrator] = TimedSink(
            AttemptRecorder(directory, attempt_id=attempt_ids[orchestrator], storage=storage)
        )
        return timed[orchestrator]

    budgets = {
        "shared_budget_usd": shared_budget_usd,
        "smoke_budget_usd": smoke_budget_usd,
        "attempt_budget_usd": attempt_budget_usd,
        "max_model_calls": max_model_calls,
        "max_context_bytes": max_context_bytes,
        "attempt_deadline_seconds": attempt_deadline_seconds,
        "shell_timeout_seconds": shell_timeout_seconds,
        "max_output_tokens": max_output_tokens,
    }
    experiment = coordinator.run_matched_comparison(
        admission_evidence=admission_evidence,
        parity_evidence=parity_evidence,
        source_repository=source_repository,
        credential_file=credential_file,
        artifact_directory=root,
        shared_budget_usd=shared_budget_usd,
        smoke_budget_usd=smoke_budget_usd,
        attempt_budget_usd=attempt_budget_usd,
        max_model_calls=max_model_calls,
        max_context_bytes=max_context_bytes,
        attempt_deadline_seconds=attempt_deadline_seconds,
        shell_timeout_seconds=shell_timeout_seconds,
        max_output_tokens=max_output_tokens,
        transport=transport,
        event_sink_factory=observe,
        # The observed result and report are projections of each attempt's log (ADR 0005).
        attempt_finished=lambda orchestrator, directory: write_projection(directory),
    )
    manifest = build_manifest(root, experiment, timed, attempt_ids, budgets=budgets)
    _write_json(root / MANIFEST_NAME, manifest)
    return manifest


def _default_directory() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ORCHESTRATION_ROOT / "evidence" / "live-tracker" / f"live-pair-{stamp}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--credential-file", type=Path, required=True,
                        help="private plain-text DeepSeek key; read only by the outer harness")
    parser.add_argument("--admission-evidence", type=Path, default=DEFAULT_ADMISSION_EVIDENCE)
    parser.add_argument("--parity-evidence", type=Path, default=coordinator.DEFAULT_PARITY_EVIDENCE)
    parser.add_argument("--source-repository", type=Path, default=DEFAULT_SOURCE_REPOSITORY)
    parser.add_argument("--artifact-dir", type=Path, default=None,
                        help="new evidence directory (default: a timestamped one in the orchestration evidence tree)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="loopback port; 0 picks a free one")
    parser.add_argument("--shared-budget-usd", type=float, default=DEFAULT_SHARED_BUDGET_USD)
    parser.add_argument("--smoke-budget-usd", type=float, default=DEFAULT_SMOKE_BUDGET_USD)
    parser.add_argument("--attempt-budget-usd", type=float, default=DEFAULT_ATTEMPT_BUDGET_USD)
    parser.add_argument("--max-model-calls", type=int, default=coordinator.DEFAULT_MAX_MODEL_CALLS)
    parser.add_argument("--max-context-bytes", type=int, default=coordinator.DEFAULT_MAX_CONTEXT_BYTES)
    parser.add_argument("--attempt-deadline-seconds", type=float,
                        default=coordinator.DEFAULT_ATTEMPT_DEADLINE_SECONDS)
    parser.add_argument("--shell-timeout-seconds", type=int, default=coordinator.DEFAULT_SHELL_TIMEOUT_SECONDS)
    parser.add_argument("--max-output-tokens", type=int, default=coordinator.DEFAULT_MAX_OUTPUT_TOKENS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = (args.artifact_dir or _default_directory()).expanduser().resolve()
    attempt_ids = {orchestrator: uuid.uuid4().hex for orchestrator in ORCHESTRATORS}
    server = make_server({attempt_ids[name]: root / name for name in ORCHESTRATORS}, port=args.port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    for name in ORCHESTRATORS:
        print(f"{name} viewer: http://127.0.0.1:{port}/?attempt={attempt_ids[name]}", flush=True)
    try:
        manifest = run_live_pair(
            credential_file=args.credential_file,
            artifact_directory=root,
            attempt_ids=attempt_ids,
            admission_evidence=args.admission_evidence,
            parity_evidence=args.parity_evidence,
            source_repository=args.source_repository,
            shared_budget_usd=args.shared_budget_usd,
            smoke_budget_usd=args.smoke_budget_usd,
            attempt_budget_usd=args.attempt_budget_usd,
            max_model_calls=args.max_model_calls,
            max_context_bytes=args.max_context_bytes,
            attempt_deadline_seconds=args.attempt_deadline_seconds,
            shell_timeout_seconds=args.shell_timeout_seconds,
            max_output_tokens=args.max_output_tokens,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        server.shutdown()
        server.server_close()
        parser.error(str(exc))
    print(json.dumps({
        "status": manifest["status"],
        "valid_measurement": manifest["valid_measurement"],
        "manifest": str(root / MANIFEST_NAME),
        "report": str(root / "report.html"),
        "attempts": {name: manifest["attempts"][name]["status"] for name in ORCHESTRATORS},
    }, indent=2, ensure_ascii=False, sort_keys=True), flush=True)
    print("Viewers stay open until Ctrl+C.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0 if manifest["valid_measurement"] else 2


if __name__ == "__main__":
    sys.exit(main())

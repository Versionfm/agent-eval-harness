"""Run a bounded DeepSeek smoke first, then one independently evaluated repair."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from agent_eval_harness.bench.attempt import (
    DEFAULT_ADMISSION_EVIDENCE,
    DEFAULT_SOURCE_REPOSITORY,
    AdmittedTask,
    AttemptBudgets,
    ModelConfig,
    attempt_and_evaluate,
)
from agent_eval_harness.harness.deepseek import (
    PRICING_SOURCE_CHECKED_AT,
    PRICING_SOURCE_URL,
    DeepSeekModelAdapter,
    SpendBudget,
)
from agent_eval_harness.cli.deepseek_smoke import (
    load_credential_file,
    run_smoke,
    write_smoke_artifact,
)


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a small live DeepSeek tool-call smoke check before a bounded repair attempt."
        )
    )
    parser.add_argument("--credential-file", type=Path, required=True,
                        help="plain-text API key file; read only by the outer harness")
    parser.add_argument("--artifact-dir", type=Path, required=True,
                        help="new directory outside the harness Git repository")
    parser.add_argument("--admission-evidence", type=Path, default=DEFAULT_ADMISSION_EVIDENCE)
    parser.add_argument("--source-repository", type=Path, default=DEFAULT_SOURCE_REPOSITORY)
    parser.add_argument("--shared-budget-usd", type=float, default=1.00,
                        help="shared USD ceiling for smoke and subsequent runs in this process")
    parser.add_argument("--smoke-budget-usd", type=float, default=0.10)
    parser.add_argument("--attempt-budget-usd", type=float, default=0.30)
    parser.add_argument("--max-model-calls", type=int, default=10)
    parser.add_argument("--max-context-bytes", type=int, default=128 * 1024)
    parser.add_argument("--attempt-deadline-seconds", type=float, default=600)
    parser.add_argument("--shell-timeout-seconds", type=int, default=60)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--request-timeout-seconds", type=float, default=60)
    args = parser.parse_args(argv)

    artifact_root = args.artifact_dir.expanduser().resolve()
    if artifact_root.exists():
        parser.error(f"artifact directory already exists: {artifact_root}")
    try:
        task = AdmittedTask.from_evidence(
            args.admission_evidence,
            source_repository=args.source_repository,
        )
        harness_root = Path(__file__).resolve().parents[2]
        if artifact_root == harness_root or harness_root in artifact_root.parents:
            parser.error("artifact directory must be outside the harness Git repository")
        source_root = task.source_repository.resolve()
        if artifact_root == source_root or source_root in artifact_root.parents:
            parser.error("artifact directory must be outside the pinned source repository")
        artifact_root.mkdir(parents=True)
        started_at = datetime.now(timezone.utc).isoformat()
        _write_json(artifact_root / "run-plan.json", {
            "status": "configured_before_provider_call",
            "started_at": started_at,
            "provider": "deepseek",
            "endpoint": "https://api.deepseek.com/chat/completions",
            "requested_model": "deepseek-flash",
            "expected_observed_model": "DeepSeek-V4.1-Flash",
            "pricing_source_url": PRICING_SOURCE_URL,
            "pricing_source_checked_at": PRICING_SOURCE_CHECKED_AT,
            "pricing_timestamp_utc": started_at,
            "thinking": "enabled",
            "reasoning_effort": "low",
            "smoke": {
                "max_output_tokens": 512,
                "timeout_seconds": min(args.request_timeout_seconds, 20),
                "max_retries_per_turn": 1,
                "max_budget_usd": args.smoke_budget_usd,
            },
            "repair_attempt": {
                "max_output_tokens": args.max_output_tokens,
                "max_model_calls": args.max_model_calls,
                "max_context_bytes": args.max_context_bytes,
                "attempt_deadline_seconds": args.attempt_deadline_seconds,
                "shell_timeout_seconds": args.shell_timeout_seconds,
                "max_provider_retries": 1,
                "cleanup_timeout_seconds": 5,
                "evaluation_timeout_seconds": 90,
                "max_budget_usd": args.attempt_budget_usd,
            },
            "shared_budget_usd": args.shared_budget_usd,
            "budgeting": (
                "Reserve peak-rate uncached input plus maximum output for each request; "
                "failed retries and missing usage retain the reservation."
            ),
        })
        api_key = load_credential_file(args.credential_file)
        shared_budget = SpendBudget(args.shared_budget_usd, name="smoke-plus-comparison")
        smoke_budget = SpendBudget(
            args.smoke_budget_usd, name="DeepSeek smoke", parent=shared_budget
        )
        smoke_adapter = DeepSeekModelAdapter(api_key=api_key, spend_budget=smoke_budget)
        smoke = run_smoke(
            adapter=smoke_adapter,
            timeout_seconds=min(args.request_timeout_seconds, 20),
            max_output_tokens=512,
            max_retries=1,
        )
        smoke_artifact = write_smoke_artifact(smoke, artifact_root / "smoke")
        if smoke.get("status") != "passed":
            _write_json(artifact_root / "experiment.json", {
                "status": "smoke_failed",
                "smoke_artifact": str(smoke_artifact),
                "shared_spend_budget": shared_budget.snapshot(),
            })
            print(f"DeepSeek smoke did not pass; repair attempt skipped. Artifact: {smoke_artifact}")
            return 1

        attempt_budget = SpendBudget(
            args.attempt_budget_usd, name="python-loop repair", parent=shared_budget
        )
        model = DeepSeekModelAdapter(api_key=api_key, spend_budget=attempt_budget)
        result = attempt_and_evaluate(
            admitted_task=task,
            model=model,
            model_config=ModelConfig(
                provider="deepseek",
                requested_model="deepseek-flash",
                settings={
                    "thinking": "enabled",
                    "reasoning_effort": "low",
                    "max_output_tokens": args.max_output_tokens,
                },
            ),
            budgets=AttemptBudgets(
                max_model_calls=args.max_model_calls,
                shell_timeout_seconds=args.shell_timeout_seconds,
                attempt_deadline_seconds=args.attempt_deadline_seconds,
                max_context_bytes=args.max_context_bytes,
                max_provider_retries=1,
                provider_retry_delay_seconds=0,
                cleanup_timeout_seconds=5,
                evaluation_timeout_seconds=90,
            ),
            artifact_directory=artifact_root / "attempt",
        )
        experiment = {
            "status": "completed",
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "provider": "deepseek",
            "endpoint": "https://api.deepseek.com/chat/completions",
            "requested_model": "deepseek-flash",
            "expected_observed_model": "DeepSeek-V4.1-Flash",
            "smoke_artifact": str(smoke_artifact),
            "attempt_artifact_dir": str(artifact_root / "attempt"),
            "attempt_termination_reason": result["termination_reason"],
            "attempt_functional_verdict": result["functional_verdict"],
            "shared_spend_budget": shared_budget.snapshot(),
            "budget_limits_usd": {
                "smoke": args.smoke_budget_usd,
                "repair_attempt": args.attempt_budget_usd,
                "shared": args.shared_budget_usd,
            },
        }
        _write_json(artifact_root / "experiment.json", experiment)
        print(
            f"DeepSeek attempt: {result['termination_reason']} / "
            f"{result['functional_verdict']}; artifacts: {artifact_root}"
        )
        return 0
    except Exception as exc:
        artifact_root.mkdir(parents=True, exist_ok=True)
        _write_json(artifact_root / "experiment-error.json", {
            "status": "error",
            "error_category": type(exc).__name__,
            "error": str(exc),
            "provider": "deepseek",
            "requested_model": "deepseek-flash",
        })
        print(f"DeepSeek attempt did not complete: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

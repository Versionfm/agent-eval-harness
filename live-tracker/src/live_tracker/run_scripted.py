"""Run a scripted attempt through either orchestrator and serve its live timeline.

Usage: PYTHONPATH=live-tracker/src python -m live_tracker.run_scripted [--port N]
       [--orchestrator python-loop|langgraph] [--scenario read|workbench]
The viewer URL is printed before the attempt starts. The server keeps running
after the attempt finishes so the saved timeline can be inspected; Ctrl+C stops it.
No provider is contacted: the model is a finite script.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any
import uuid

from agent_eval_harness.attempt import (
    DEFAULT_ADMISSION_EVIDENCE, DEFAULT_SOURCE_REPOSITORY, ORCHESTRATION_ROOT,
    AdmittedTask, AttemptBudgets, attempt_and_evaluate,
)
from agent_eval_harness.model import ModelConfig, ModelResponse, ScriptedModel, ToolCall
from agent_eval_harness.observation import AttemptEventSink
from live_tracker.reader import read_attempt_history
from live_tracker.projection import write_report
from live_tracker.recorder import AttemptRecorder
from live_tracker.server import make_server


def read_then_complete_model() -> ScriptedModel:
    """Finite script: one repository read, then a completion with no repair."""
    return ScriptedModel([
        ModelResponse(
            tool_calls=(ToolCall("read_file", {"path": "app/source.py"}, "read-1"),),
            reasoning_fields={"reasoning_content": "Inspect the retrieval path before answering."},
            usage={"prompt_tokens": 11, "completion_tokens": 3},
        ),
        ModelResponse(content="I inspected the retrieval path and am stopping without a repair."),
    ])


def workbench_model() -> ScriptedModel:
    """Finite script that exercises every inspector field: truncated markup output, a failing
    and a succeeding read in one turn, then a completion whose usage is not recorded."""
    probe = "printf '<script>window.trackerProbe = true</script>\\n'; head -c 20000 /dev/zero | tr '\\0' x"
    return ScriptedModel([
        ModelResponse(
            tool_calls=(ToolCall("run_shell", {"command": probe}, "shell-1"),),
            reasoning_fields={"reasoning_content": "Probe the shell output before reading files."},
            usage={"prompt_tokens": 11, "completion_tokens": 9},
        ),
        ModelResponse(
            tool_calls=(
                ToolCall("read_file", {"path": "app/missing.py"}, "read-missing"),
                ToolCall("read_file", {"path": "app/source.py"}, "read-source"),
            ),
            reasoning_fields={"reasoning_content": "The first read failed; read the source file."},
            usage={"prompt_tokens": 40, "completion_tokens": 7},
        ),
        ModelResponse(content="The shell output was truncated and the source file was read; stopping without a repair."),
    ])


SCENARIOS = {"read": read_then_complete_model, "workbench": workbench_model}


def run_attempt(
    *,
    admission_evidence: Path,
    source_repository: Path,
    output_dir: Path,
    model: ScriptedModel | None = None,
    event_sink: AttemptEventSink | None = None,
    scenario: str = "read",
    orchestrator: str = "python-loop",
) -> dict[str, Any]:
    result = attempt_and_evaluate(
        admitted_task=AdmittedTask.from_evidence(admission_evidence, source_repository=source_repository),
        model=model or SCENARIOS[scenario](),
        model_config=ModelConfig(provider="scripted", requested_model="scripted-read-then-complete-v1"),
        budgets=AttemptBudgets(max_model_calls=4, shell_timeout_seconds=60),
        artifact_directory=output_dir,
        orchestrator=orchestrator,
        event_sink=event_sink,
    )
    if event_sink is not None:
        # The observed report is projected from the log, replacing the in-memory render.
        write_report(output_dir)
    return result


def _default_output_directory() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ORCHESTRATION_ROOT / "evidence" / "live-tracker" / f"scripted-read-{stamp}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--admission-evidence", type=Path, default=DEFAULT_ADMISSION_EVIDENCE)
    parser.add_argument("--source-repository", type=Path, default=DEFAULT_SOURCE_REPOSITORY)
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="new evidence directory (default: a timestamped one in the orchestration evidence tree)")
    parser.add_argument("--port", type=int, default=8765, help="loopback port; 0 picks a free one")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="read",
                        help="scripted model: read (one read, then complete) or workbench (every inspector field)")
    parser.add_argument("--orchestrator", choices=["python-loop", "langgraph"], default="python-loop",
                        help="explicit Python loop or the LangGraph workflow (same events, node transitions)")
    args = parser.parse_args(argv)

    output_dir = (args.output_dir or _default_output_directory()).expanduser().resolve()
    attempt_id = uuid.uuid4().hex
    recorder = AttemptRecorder(output_dir, attempt_id=attempt_id)
    server = make_server({attempt_id: output_dir}, port=args.port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"viewer: http://127.0.0.1:{server.server_address[1]}/", flush=True)
    try:
        result = run_attempt(
            admission_evidence=args.admission_evidence, source_repository=args.source_repository,
            output_dir=output_dir, event_sink=recorder, scenario=args.scenario,
            orchestrator=args.orchestrator,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        server.shutdown()
        parser.error(str(exc))
    summary = {
        "attempt_id": attempt_id,
        "termination_reason": result["termination_reason"],
        "functional_verdict": result["functional_verdict"],
        "model_call_count": result["metadata"].get("model_call_count"),
        "changed_files": result["candidate"]["changed_files"],
        "checks": result["evaluation"].get("checks", {}),
        "artifact_directory": str(output_dir),
        "error": result.get("harness_error", result["evaluation"].get("error")),
        # Recording completeness is reported apart from the termination reason and verdict.
        "recording": read_attempt_history(output_dir).status(),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0 if result["functional_verdict"] in {"success", "failure"} else 1


if __name__ == "__main__":
    sys.exit(main())

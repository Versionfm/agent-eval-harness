"""Measure observation overhead per orchestrator: observed versus unobserved wall time.

The model is a finite script, so no provider is contacted. Requires Docker and the admitted task:
  PYTHONPATH=.:live-tracker/src python live-tracker/experiments/observation_overhead.py \
    --admission-evidence <admission.json> --source-repository <prompt-engineering-group-project> \
    [--scenario workbench] [--repeats 3]

Observed and unobserved runs alternate in order, so drift affects both. Wall time is the whole
attempt. Time inside the sink's emit calls (record, fsync and artifact writes) is reported
separately; the snapshot computation runs outside emit, so it is part of the wall-time difference only.
"""

import argparse
import json
from pathlib import Path
import statistics
import tempfile
import time
from typing import Any

from live_tracker.reader import read_attempt_history
from live_tracker.recorder import AttemptRecorder
from live_tracker.run_scripted import SCENARIOS, run_attempt


class TimedSink:
    """Forwards to the recorder and accumulates the time each emit takes."""

    def __init__(self, recorder: AttemptRecorder):
        self.recorder = recorder
        self.emit_seconds = 0.0
        self.emit_count = 0

    def emit(self, *args: Any, **kwargs: Any) -> None:
        started = time.perf_counter()
        try:
            return self.recorder.emit(*args, **kwargs)
        finally:
            self.emit_seconds += time.perf_counter() - started
            self.emit_count += 1


def _directory_bytes(directory: Path) -> int:
    return sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--admission-evidence", type=Path, required=True)
    parser.add_argument("--source-repository", type=Path, required=True)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="workbench")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)

    runs: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="observation-overhead-") as temporary:
        for repeat in range(args.repeats):
            for orchestrator in ("python-loop", "langgraph"):
                order = (False, True) if repeat % 2 == 0 else (True, False)
                for observed in order:
                    label = f"{repeat}-{orchestrator}-{'observed' if observed else 'unobserved'}"
                    directory = Path(temporary) / label
                    sink = TimedSink(AttemptRecorder(directory)) if observed else None
                    started = time.perf_counter()
                    result = run_attempt(
                        admission_evidence=args.admission_evidence,
                        source_repository=args.source_repository,
                        output_dir=directory,
                        event_sink=sink,
                        scenario=args.scenario,
                        orchestrator=orchestrator,
                    )
                    wall = time.perf_counter() - started
                    runs.append({
                        "orchestrator": orchestrator,
                        "observed": observed,
                        "wall_seconds": round(wall, 4),
                        "termination_reason": result["termination_reason"],
                        "functional_verdict": result["functional_verdict"],
                        "events": len(read_attempt_history(directory).events) if observed else 0,
                        "emit_seconds": round(sink.emit_seconds, 4) if sink else 0.0,
                        "emit_count": sink.emit_count if sink else 0,
                        "recorded_bytes": _directory_bytes(directory) if observed else 0,
                    })

    summary = {}
    for orchestrator in ("python-loop", "langgraph"):
        off = [run["wall_seconds"] for run in runs if run["orchestrator"] == orchestrator and not run["observed"]]
        on = [run for run in runs if run["orchestrator"] == orchestrator and run["observed"]]
        mean_off, mean_on = statistics.mean(off), statistics.mean(run["wall_seconds"] for run in on)
        summary[orchestrator] = {
            "unobserved_mean_seconds": round(mean_off, 4),
            "observed_mean_seconds": round(mean_on, 4),
            "difference_seconds": round(mean_on - mean_off, 4),
            "difference_percent": round(100 * (mean_on - mean_off) / mean_off, 2),
            "emit_mean_seconds": round(statistics.mean(run["emit_seconds"] for run in on), 4),
            "events_per_attempt": on[0]["events"],
            "emits_per_attempt": on[0]["emit_count"],
            "recorded_kib_per_attempt": round(on[0]["recorded_bytes"] / 1024, 1),
            "outcomes": sorted({f"{run['termination_reason']}/{run['functional_verdict']}" for run in runs
                                if run["orchestrator"] == orchestrator}),
        }
    print(json.dumps({"scenario": args.scenario, "repeats": args.repeats, "summary": summary,
                      "runs": runs}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

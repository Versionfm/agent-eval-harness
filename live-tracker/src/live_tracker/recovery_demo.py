"""No-provider demonstration of interrupted writes and recorder failure.

Usage: PYTHONPATH=live-tracker/src python -m live_tracker.recovery_demo [--output-dir NEW_DIR]

Writes synthetic attempt recordings (no model, no Docker, no provider request),
reads each back with the public reader, prints what it reports, and checks the
expected recording state. Exit status 0 means every expectation held.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

from agent_eval_harness.observation import EventRecordingError
from live_tracker.reader import read_attempt_history
from live_tracker.recorder import AttemptRecorder, FaultyStorage


def _model_turn(recorder: AttemptRecorder) -> None:
    recorder.emit("attempt_started", {"task_id": "demo", "orchestrator": "python-loop"})
    recorder.emit("model.start", {"model_call": 1}, {"request.json": b'[{"role":"user"}]'},
                  operation_id="model-1")


def _complete(directory: Path) -> None:
    recorder = AttemptRecorder(directory)
    _model_turn(recorder)
    recorder.emit("model.outcome", {"status": "ok"}, {"response.json": b'{"content":"done"}'},
                  operation_id="model-1")
    recorder.emit("attempt_finished", {"termination_reason": "agent_completed"})


def _crash_mid_append(directory: Path) -> None:
    # The process dies partway through the outcome line and no marker can be written.
    recorder = AttemptRecorder(directory, storage=FaultyStorage(
        "log", "model.outcome", tear=True, fail_marker=True))
    _model_turn(recorder)
    recorder.emit("model.outcome", {"status": "ok"}, operation_id="model-1")


def _recorder_failure(directory: Path) -> None:
    # Storage refuses the outcome; the marker is saved and the recorder refuses later events.
    recorder = AttemptRecorder(directory, storage=FaultyStorage("log", "model.outcome"))
    _model_turn(recorder)
    recorder.emit("model.outcome", {"status": "ok"}, operation_id="model-1")


def _marker_refused(directory: Path) -> None:
    recorder = AttemptRecorder(directory, storage=FaultyStorage(
        "log", "model.outcome", fail_marker=True))
    _model_turn(recorder)
    recorder.emit("model.outcome", {"status": "ok"}, operation_id="model-1")


def _damaged_middle(directory: Path) -> None:
    _complete(directory)
    log = directory / "events.jsonl"
    lines = log.read_bytes().split(b"\n")
    lines[1] = b"%% damaged %%"
    log.write_bytes(b"\n".join(lines))


SCENARIOS = {
    "complete": (_complete, {"state": "complete", "verified_events": 4}),
    "crash_mid_append": (_crash_mid_append, {"state": "interrupted", "unresolved_operations": ["model-1"]}),
    "recorder_failure": (_recorder_failure, {"state": "failed", "unresolved_operations": ["model-1"]}),
    "marker_refused": (_marker_refused, {"state": "open", "unresolved_operations": ["model-1"]}),
    "damaged_middle": (_damaged_middle, {"state": "corrupt", "verified_events": 1}),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="new directory for the synthetic recordings (default: a temporary one)")
    args = parser.parse_args(argv)
    default_root = Path(tempfile.mkdtemp(prefix="live-recovery-demo-")) / "recordings"
    root = (args.output_dir or default_root).expanduser().resolve()
    if root.exists():
        parser.error(f"output directory must not exist: {root}")
    print(f"recordings: {root}")

    failures = []
    for name, (write, expected) in SCENARIOS.items():
        directory = root / name
        error = None
        try:
            write(directory)
        except EventRecordingError as exc:
            error = str(exc)
        history = read_attempt_history(directory)
        summary = {"scenario": name, "error_returned_to_caller": error, **history.status()}
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        for key, value in expected.items():
            if summary.get(key) != value:
                failures.append(f"{name}: {key} expected {value!r}, got {summary.get(key)!r}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("all recording states matched the expected outcomes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

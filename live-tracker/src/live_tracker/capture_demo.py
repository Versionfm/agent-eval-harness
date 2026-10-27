"""No-provider demo of repository capture (#16): partial mutation, limits and settlement.

Runs scripted attempts in the real task container (Docker and the admitted task are required; no
model provider is contacted). Each case prints what the inspector would show for its tool
captures and asserts the expected facts. Exit status is non-zero if any expectation fails.

  PYTHONPATH=live-tracker/src python -m live_tracker.capture_demo \
    [--admission-evidence <admission.json>] [--source-repository <prompt-engineering-group-project>]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile
from typing import Any

from agent_eval_harness.bench.attempt import DEFAULT_ADMISSION_EVIDENCE, DEFAULT_SOURCE_REPOSITORY
from agent_eval_harness.bench.capture import CaptureLimits
from live_tracker.reader import read_attempt_history
from live_tracker.recorder import AttemptRecorder
from live_tracker.run_scripted import run_attempt


def _observed(root: Path, name: str, *, scenario: str, limits: CaptureLimits | None,
              admission: Path, source: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    directory = root / name
    result = run_attempt(
        admission_evidence=admission, source_repository=source, output_dir=directory,
        event_sink=AttemptRecorder(directory), scenario=scenario, capture_limits=limits,
    )
    history = read_attempt_history(directory)
    if history.state != "complete":
        raise SystemExit(f"{name}: recording state is {history.state}, expected complete")
    captures = [event for event in history.events if event["type"] == "tool.capture"]
    return result, captures


def _show(name: str, captures: list[dict[str, Any]]) -> None:
    print(f"[{name}]")
    for event in captures:
        data = event["data"]
        settlement = data["settlement"]
        line = (f"  {event['parent_operation_id']} {data['tool_name']}: status={data['status']}"
                f" settlement={settlement['status']} via {settlement['method']}")
        if data.get("reason"):
            line += f" reason={data['reason']}"
        print(line)
        for change in data.get("changes", []):
            if change["kind"] == "binary":
                print(f"      {change['action']} {change['path']} (binary, {change['after']['bytes']} bytes, metadata only)")
            else:
                print(f"      {change['action']} {change['path']} +{change['additions']} -{change['deletions']}")
        for process in settlement.get("live_processes", []):
            print(f"      alive after return: pid {process['pid']} {process['command']}")


def _expect(condition: bool, message: str, failures: list[str]) -> None:
    print(("  ok: " if condition else "  FAIL: ") + message)
    if not condition:
        failures.append(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--admission-evidence", type=Path, default=DEFAULT_ADMISSION_EVIDENCE)
    parser.add_argument("--source-repository", type=Path, default=DEFAULT_SOURCE_REPOSITORY)
    args = parser.parse_args(argv)
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="capture-demo-") as temporary:
        root = Path(temporary)
        common = {"admission": args.admission_evidence, "source": args.source_repository}

        print("Case 1: partial mutation (successful patch, failing shell, deletion, binary, timed-out shell)")
        mutated, captures = _observed(root, "mutations", scenario="mutations", limits=None, **common)
        _show("mutations", captures)
        by_operation = {event["parent_operation_id"]: event["data"] for event in captures}
        _expect(by_operation["tool-1-1"]["status"] == "captured"
                and by_operation["tool-1-1"]["settlement"]["method"] == "apply_patch_returned",
                "patch capture is settled at apply_patch return", failures)
        _expect(by_operation["tool-2-1"]["settlement"]["method"] == "process_probe"
                and by_operation["tool-2-1"]["status"] == "captured",
                "failing shell is captured after a live-process probe found nothing alive", failures)
        _expect(by_operation["tool-5-1"]["settlement"]["method"] == "container_removed",
                "timed-out shell is settled by container removal", failures)
        unobserved = run_attempt(
            admission_evidence=args.admission_evidence, source_repository=args.source_repository,
            output_dir=root / "unobserved", scenario="mutations",
        )
        _expect(unobserved["candidate"]["files"] == mutated["candidate"]["files"]
                and unobserved["evaluation"]["checks"] == mutated["evaluation"]["checks"],
                "observed and unobserved attempts have the same candidate files and checks", failures)

        print("Case 2: byte limit (declared omission, not a failure)")
        _, captures = _observed(root, "byte-limit", scenario="mutations",
                                limits=CaptureLimits(max_total_bytes=1024), **common)
        _show("byte-limit", captures)
        _expect(all(event["data"]["status"] == "omitted" and event["data"]["reason"] == "byte_limit"
                    for event in captures) and len(captures) == 5,
                "every capture is omitted for byte_limit", failures)

        print("Case 3: time limit (probe and snapshot stop at the limit)")
        _, captures = _observed(root, "time-limit", scenario="mutations",
                                limits=CaptureLimits(max_seconds=0.001), **common)
        _show("time-limit", captures)
        _expect(all(event["data"]["status"] == "omitted" and event["data"]["reason"] == "time_limit"
                    for event in captures) and len(captures) == 5,
                "every capture is omitted for time_limit", failures)

        print("Case 4: settlement (literal writer waited for by the shell; detached writer still alive)")
        _, captures = _observed(root, "background", scenario="background", limits=None, **common)
        _show("background", captures)
        by_operation = {event["parent_operation_id"]: event["data"] for event in captures}
        _expect(by_operation["tool-1-1"]["settlement"]["status"] == "settled",
                "literal writer: the shell return waited for it, so the capture is settled", failures)
        _expect(by_operation["tool-2-1"]["status"] == "unsettled" and "changes" not in by_operation["tool-2-1"],
                "detached writer: capture is unsettled and shows no change", failures)

    if failures:
        print(f"capture demo failed: {len(failures)} expectation(s) not met")
        return 1
    print("capture demo passed: partial mutation captured, limits and settlement labelled, candidate unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Docker seams for repository capture (#16): real scripted attempts through the recorder.

Mutations, partial failures, a timed-out shell, a binary file, a deletion and background writers
run in the real task container. Expected values are literal facts of the script, not recomputed.
"""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_eval_harness.bench.attempt import DEFAULT_SOURCE_REPOSITORY
from live_tracker.reader import read_attempt_history
from live_tracker.recorder import AttemptRecorder
from live_tracker.run_scripted import background_model, mutations_model, run_attempt


DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
SOURCE_REPOSITORY = DEFAULT_SOURCE_REPOSITORY


def _captures(events):
    """Each tool.capture event keyed by the tool operation it is linked to."""
    return {event["parent_operation_id"]: event for event in events if event["type"] == "tool.capture"}


def _by_path(capture):
    return {change["path"]: change for change in capture["data"].get("changes", [])}


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for Docker attempts",
)
class RepositoryCaptureDockerTests(unittest.TestCase):
    def test_mutations_are_captured_linked_to_their_tool_and_match_the_repository(self):
        with tempfile.TemporaryDirectory(prefix="capture-docker-") as temporary:
            directory = Path(temporary) / "observed"
            observed_model = mutations_model()
            observed = run_attempt(
                admission_evidence=Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY,
                output_dir=directory, model=observed_model, event_sink=AttemptRecorder(directory),
                scenario="mutations",
            )
            history = read_attempt_history(directory)
            self.assertEqual(history.state, "complete")
            events = history.events
            captures = _captures(events)
            # Operations: tool-1-1 patch, tool-2-1 failing shell, tool-3-1 unlink, tool-4-1 binary,
            # tool-5-1 timed-out shell.
            self.assertEqual(sorted(captures), ["tool-1-1", "tool-2-1", "tool-3-1", "tool-4-1", "tool-5-1"])
            for operation_id, capture in captures.items():
                outcome = next(event for event in events
                               if event["type"] == "tool.outcome" and event["operation_id"] == operation_id)
                self.assertLess(outcome["sequence"], capture["sequence"])
                self.assertEqual(capture["data"]["status"], "captured", capture["data"])

            patch = captures["tool-1-1"]["data"]
            self.assertEqual(patch["settlement"]["method"], "apply_patch_returned")
            self.assertEqual(_by_path(captures["tool-1-1"])["notes/added.txt"]["action"], "add")
            self.assertEqual(_by_path(captures["tool-1-1"])["notes/added.txt"]["additions"], 1)

            # Relative to the attempt start: the note created by the patch is still an add (two lines now).
            failing = _by_path(captures["tool-2-1"])
            self.assertEqual(captures["tool-2-1"]["data"]["settlement"]["method"], "process_probe")
            self.assertEqual((failing["notes/added.txt"]["action"], failing["notes/added.txt"]["additions"]), ("add", 2))
            self.assertEqual((failing["app/source.py"]["action"], failing["app/source.py"]["additions"]), ("modify", 1))

            self.assertEqual(_by_path(captures["tool-3-1"])["docs/slides_outline.md"]["action"], "delete")
            self.assertGreater(_by_path(captures["tool-3-1"])["docs/slides_outline.md"]["deletions"], 0)

            binary = _by_path(captures["tool-4-1"])["notes/blob.bin"]
            self.assertEqual((binary["kind"], binary["preview"], binary["additions"]), ("binary", None, None))
            self.assertEqual(binary["after"]["bytes"], 4)
            self.assertEqual(binary["after"]["sha256"], hashlib.sha256(b"\xff\xfe\x00\x01").hexdigest())

            timed = captures["tool-5-1"]["data"]
            self.assertEqual(timed["settlement"]["method"], "container_removed")
            self.assertEqual(_by_path(captures["tool-5-1"])["notes/timed.txt"]["action"], "add")
            self.assertEqual(
                next(event for event in events if event["type"] == "tool.outcome"
                     and event["operation_id"] == "tool-5-1")["data"]["result"]["error_category"],
                "command_timeout",
            )

            # Actual repository effects on disk match what the capture reported.
            repository = directory / "task-repository"
            blob = (repository / "notes" / "blob.bin").read_bytes()
            self.assertEqual(hashlib.sha256(blob).hexdigest(), binary["after"]["sha256"])
            self.assertEqual((repository / "notes" / "timed.txt").read_text(), "partial\n")
            self.assertFalse((repository / "docs" / "slides_outline.md").exists())

            full = json.loads((directory / captures["tool-2-1"]["artifacts"][0]["path"]).read_bytes())
            self.assertEqual(full["tool_name"], "run_shell")
            self.assertEqual(observed["termination_reason"], "agent_completed")

    def test_observation_on_and_off_keep_candidate_checks_and_model_visible_messages(self):
        with tempfile.TemporaryDirectory(prefix="capture-parity-") as temporary:
            root = Path(temporary)
            unobserved_model = mutations_model()
            unobserved = run_attempt(
                admission_evidence=Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY,
                output_dir=root / "unobserved", model=unobserved_model, scenario="mutations",
            )
            observed_model = mutations_model()
            observed = run_attempt(
                admission_evidence=Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY,
                output_dir=root / "observed", model=observed_model, scenario="mutations",
                event_sink=AttemptRecorder(root / "observed"),
            )
            self.assertEqual(
                [request.messages for request in observed_model.requests],
                [request.messages for request in unobserved_model.requests],
            )
            self.assertEqual(observed["candidate"]["files"], unobserved["candidate"]["files"])
            self.assertEqual(observed["evaluation"]["checks"], unobserved["evaluation"]["checks"])
            self.assertEqual(
                (observed["termination_reason"], observed["functional_verdict"]),
                (unobserved["termination_reason"], unobserved["functional_verdict"]),
            )
            self.assertEqual(
                observed["metadata"]["repository_capture"]["status_counts"], {"captured": 5},
            )

    def test_langgraph_tool_node_captures_the_same_mutations_as_the_python_loop(self):
        with tempfile.TemporaryDirectory(prefix="capture-langgraph-") as temporary:
            root = Path(temporary)
            python_loop = run_attempt(
                admission_evidence=Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY,
                output_dir=root / "python-loop", model=mutations_model(), scenario="mutations",
                event_sink=AttemptRecorder(root / "python-loop"),
            )
            graph = run_attempt(
                admission_evidence=Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY,
                output_dir=root / "langgraph", model=mutations_model(), scenario="mutations",
                event_sink=AttemptRecorder(root / "langgraph"), orchestrator="langgraph",
            )
            graph_captures = _captures(read_attempt_history(root / "langgraph").events)
            self.assertEqual(sorted(graph_captures), ["tool-1-1", "tool-2-1", "tool-3-1", "tool-4-1", "tool-5-1"])
            self.assertEqual(
                {key: value["data"]["status"] for key, value in graph_captures.items()},
                {"tool-1-1": "captured", "tool-2-1": "captured", "tool-3-1": "captured",
                 "tool-4-1": "captured", "tool-5-1": "captured"},
            )
            self.assertEqual(
                {key: _by_path(value) for key, value in graph_captures.items()},
                {key: _by_path(value) for key, value in _captures(
                    read_attempt_history(root / "python-loop").events).items()},
            )
            self.assertEqual(graph["candidate"]["files"], python_loop["candidate"]["files"])

    def test_background_writer_is_settled_only_when_the_shell_return_waited_for_it(self):
        with tempfile.TemporaryDirectory(prefix="capture-background-") as temporary:
            directory = Path(temporary) / "attempt"
            run_attempt(
                admission_evidence=Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY,
                output_dir=directory, model=background_model(), event_sink=AttemptRecorder(directory),
                scenario="background",
            )
            captures = _captures(read_attempt_history(directory).events)
            # The literal form keeps the shell's output pipe open, so docker exec returns only after
            # the writer exits: the probe finds nothing alive and the capture is settled.
            self.assertEqual(captures["tool-1-1"]["data"]["status"], "captured")
            self.assertEqual(captures["tool-1-1"]["data"]["settlement"]["status"], "settled")
            self.assertEqual(_by_path(captures["tool-1-1"])["late.txt"]["action"], "add")
            # The detached form returns at once while its writer sleeps: unsettled, no diff shown.
            detached = captures["tool-2-1"]["data"]
            self.assertEqual((detached["status"], detached["settlement"]["status"]), ("unsettled", "unsettled"))
            self.assertIn("sleep 2", [process["command"] for process in detached["settlement"]["live_processes"]])
            self.assertNotIn("changes", detached)


if __name__ == "__main__":
    unittest.main()

"""Reader rules for review fixes on #10: legacy reading is explicit, graph nodes pair like model and tool calls.

A directory is read as a preserved legacy trace only when it is registered as one. A directory without
an event log is never reinterpreted from a trace file that a projection may have written next to it.
"""

import json
import tempfile
import unittest
from pathlib import Path

from agent_eval_harness.observation import EventRecordingError
from live_tracker.legacy import LEGACY_FORMAT
from live_tracker.reader import read_attempt_history
from live_tracker.recorder import AttemptRecorder, FaultyStorage


class ExplicitFormatTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="live-reader-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def _projection_trace(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "trace.jsonl").write_text(
            json.dumps({"event_id": 1, "type": "termination", "timestamp": "t", "reason": "agent_completed"}) + "\n",
            encoding="utf-8",
        )

    def test_a_failed_first_append_with_a_failed_marker_is_not_read_as_legacy(self):
        directory = self.root / "marker-refused"
        self._projection_trace(directory)
        recorder = AttemptRecorder(directory, storage=FaultyStorage("log", "attempt_started", fail_marker=True))
        with self.assertRaises(EventRecordingError):
            recorder.emit("attempt_started", {})
        history = read_attempt_history(directory)
        self.assertEqual(history.format, "agent-eval-harness/attempt-events")
        self.assertEqual(history.state, "empty", "nothing was recorded and no marker was saved")

    def test_a_failed_first_append_with_a_saved_marker_reads_as_failed(self):
        directory = self.root / "marker-saved"
        self._projection_trace(directory)
        recorder = AttemptRecorder(directory, storage=FaultyStorage("log", "attempt_started"))
        with self.assertRaises(EventRecordingError):
            recorder.emit("attempt_started", {})
        self.assertEqual(read_attempt_history(directory).state, "failed")

    def test_a_registered_legacy_trace_is_read_by_the_adapter(self):
        directory = self.root / "legacy"
        self._projection_trace(directory)
        history = read_attempt_history(directory, format=LEGACY_FORMAT)
        self.assertEqual(history.state, "legacy")
        self.assertEqual(history.format, LEGACY_FORMAT)
        self.assertEqual([event["type"] for event in history.events], ["termination"])


class OperationPairingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="live-reader-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "attempt"

    def test_a_graph_node_without_an_outcome_is_unresolved(self):
        recorder = AttemptRecorder(self.directory)
        recorder.emit("attempt_started", {})
        recorder.emit("node.enter", {"node": "model_request"}, operation_id="graph-step-1")
        recorder.emit("node.enter", {"node": "tool_execution"}, operation_id="graph-step-2")
        recorder.emit("node.outcome", {"node": "tool_execution"}, operation_id="graph-step-2")
        history = read_attempt_history(self.directory)
        self.assertEqual(history.unresolved_operations, ["graph-step-1"])
        self.assertEqual(history.state, "open")

    def test_a_graph_node_started_twice_is_an_identity_conflict(self):
        recorder = AttemptRecorder(self.directory)
        recorder.emit("attempt_started", {})
        recorder.emit("node.enter", {"node": "model_request"}, operation_id="graph-step-1")
        recorder.emit("node.enter", {"node": "model_request"}, operation_id="graph-step-1")
        history = read_attempt_history(self.directory)
        self.assertEqual([problem["kind"] for problem in history.problems], ["identity_conflict"])
        self.assertEqual(history.state, "corrupt")


if __name__ == "__main__":
    unittest.main()

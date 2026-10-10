import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from agent_eval_harness.observation import EventRecordingError
from live_tracker.reader import read_attempt_history
from live_tracker.recorder import AttemptRecorder, FaultyStorage


class AttemptRecorderTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self):
        self._temporary.cleanup()

    def test_torn_final_record_leaves_a_verified_prefix_and_is_reported_as_interrupted(self):
        attempt_dir = self.root / "attempt"
        recorder = AttemptRecorder(attempt_dir)
        recorder.emit("attempt_started", {"task_id": "t"})
        recorder.emit("model.start", {"model_call": 1}, {"request.json": b'[{"role":"user"}]'},
                      operation_id="model-1")

        log = attempt_dir / "events.jsonl"
        with log.open("ab") as handle:
            handle.write(b'{"schema":"agent-eval')
        before = log.read_bytes()

        history = read_attempt_history(attempt_dir)
        self.assertEqual(history.state, "interrupted")
        self.assertEqual([event["sequence"] for event in history.events], [1, 2])
        self.assertEqual(history.torn_tail_bytes, len(b'{"schema":"agent-eval'))
        self.assertEqual(history.unresolved_operations, ["model-1"])
        self.assertEqual(history.problems, [])
        self.assertEqual(log.read_bytes(), before, "reading must not rewrite the source bytes")

    def test_damaged_records_are_reported_and_never_skipped(self):
        attempt_dir = self.root / "attempt"
        recorder = AttemptRecorder(attempt_dir)
        recorder.emit("attempt_started", {"task_id": "t"})
        recorder.emit("model.start", {"model_call": 1}, {"request.json": b"request"}, operation_id="model-1")
        recorder.emit("model.outcome", {"status": "ok"}, operation_id="model-1")
        recorder.emit("attempt_finished", {"functional_verdict": "failure"})
        log = attempt_dir / "events.jsonl"
        lines = log.read_bytes().split(b"\n")

        # A damaged artifact is reported on its event but the record itself stays visible.
        artifact = attempt_dir / f"artifacts/{hashlib.sha256(b'request').hexdigest()}"
        artifact.write_bytes(b"tampered")
        history = read_attempt_history(attempt_dir)
        self.assertEqual(history.state, "corrupt")
        self.assertEqual([problem["kind"] for problem in history.problems], ["damaged_artifact"])
        self.assertEqual(history.events[1]["artifacts"][0]["integrity"], "damaged")
        self.assertEqual(len(history.events), 4)
        artifact.write_bytes(b"request")

        # Missing artifacts are visible in the same way.
        artifact.unlink()
        history = read_attempt_history(attempt_dir)
        self.assertEqual([problem["kind"] for problem in history.problems], ["missing_artifact"])
        artifact.write_bytes(b"request")

        # Middle corruption ends the verified prefix at the last good record.
        lines[1] = b"not json"
        log.write_bytes(b"\n".join(lines))
        history = read_attempt_history(attempt_dir)
        self.assertEqual(history.state, "corrupt")
        self.assertEqual([event["sequence"] for event in history.events], [1])
        self.assertEqual(history.problems[0]["kind"], "malformed")
        self.assertEqual(history.problems[0]["sequence"], 2)

        # A missing record is a sequence gap, not a silent renumbering.
        log.write_bytes(b"\n".join([lines[0], *lines[2:]]))
        history = read_attempt_history(attempt_dir)
        self.assertEqual(history.problems[0]["kind"], "sequence_gap")
        self.assertEqual(len(history.events), 1)

    def test_identity_schema_and_operation_conflicts_are_problems(self):
        attempt_dir = self.root / "attempt"
        recorder = AttemptRecorder(attempt_dir, attempt_id="a1")
        recorder.emit("attempt_started", {})
        recorder.emit("model.start", {}, operation_id="model-1")
        log = attempt_dir / "events.jsonl"
        original = log.read_bytes().split(b"\n")

        other = json.loads(original[1])
        other["attempt_id"] = "other"
        log.write_bytes(b"\n".join([original[0], json.dumps(other).encode(), b""]))
        self.assertEqual(read_attempt_history(attempt_dir).problems[0]["kind"], "identity_conflict")

        unsupported = json.loads(original[1])
        unsupported["schema_version"] = 99
        log.write_bytes(b"\n".join([original[0], json.dumps(unsupported).encode(), b""]))
        self.assertEqual(read_attempt_history(attempt_dir).problems[0]["kind"], "unsupported_schema")

        duplicate = json.loads(original[1])
        duplicate["sequence"] = 3
        log.write_bytes(b"\n".join([original[0], original[1], json.dumps(duplicate).encode(), b""]))
        self.assertEqual(read_attempt_history(attempt_dir).problems[0]["kind"], "identity_conflict")

    def test_a_recorder_never_resumes_an_existing_log(self):
        attempt_dir = self.root / "attempt"
        AttemptRecorder(attempt_dir).emit("attempt_started", {})
        with self.assertRaises(FileExistsError):
            AttemptRecorder(attempt_dir)

    def test_failed_mandatory_write_stops_the_recorder_and_saves_a_marker(self):
        attempt_dir = self.root / "attempt"
        storage = FaultyStorage("log", "model.outcome")
        recorder = AttemptRecorder(attempt_dir, storage=storage)
        recorder.emit("attempt_started", {})
        recorder.emit("model.start", {}, operation_id="model-1")
        with self.assertRaises(EventRecordingError) as raised:
            recorder.emit("model.outcome", {"status": "ok"}, operation_id="model-1")
        self.assertIn("marker was saved", str(raised.exception))
        log_before = (attempt_dir / "events.jsonl").read_bytes()

        # Later mandatory events are refused without touching the saved prefix.
        with self.assertRaises(EventRecordingError):
            recorder.emit("attempt_finished", {})
        self.assertEqual((attempt_dir / "events.jsonl").read_bytes(), log_before)

        history = read_attempt_history(attempt_dir)
        self.assertEqual(history.state, "failed")
        self.assertEqual(history.failure["failed_event_type"], "model.outcome")
        self.assertEqual(history.unresolved_operations, ["model-1"])

    def test_storage_that_refuses_the_marker_leaves_the_prefix_incomplete_and_says_so(self):
        attempt_dir = self.root / "attempt"
        recorder = AttemptRecorder(attempt_dir, storage=FaultyStorage("log", "model.outcome", fail_marker=True))
        recorder.emit("attempt_started", {})
        recorder.emit("model.start", {}, operation_id="model-1")
        with self.assertRaises(EventRecordingError) as raised:
            recorder.emit("model.outcome", {}, operation_id="model-1")
        self.assertIn("no failure marker could be saved", str(raised.exception))
        self.assertFalse((attempt_dir / "recording-failure.json").exists())
        history = read_attempt_history(attempt_dir)
        self.assertEqual(history.state, "open")
        self.assertEqual(history.unresolved_operations, ["model-1"])

    def test_torn_write_during_a_failed_append_reads_as_failed_with_the_tail_counted(self):
        attempt_dir = self.root / "attempt"
        recorder = AttemptRecorder(attempt_dir, storage=FaultyStorage("log", "tool.outcome", tear=True))
        recorder.emit("attempt_started", {})
        with self.assertRaises(EventRecordingError):
            recorder.emit("tool.outcome", {}, operation_id="tool-1-1")
        history = read_attempt_history(attempt_dir)
        self.assertEqual(history.state, "failed")
        self.assertGreater(history.torn_tail_bytes, 0)
        self.assertEqual([event["sequence"] for event in history.events], [1])

    def test_mandatory_artifacts_are_durable_before_the_event_that_references_them(self):
        attempt_dir = self.root / "attempt"
        storage = FaultyStorage("never", "never")
        recorder = AttemptRecorder(attempt_dir, storage=storage)
        recorder.emit("model.start", {}, {"request.json": b"request"}, operation_id="model-1")
        recorder.emit("model.outcome", {}, {"response.json": b"response"}, operation_id="model-1")
        self.assertEqual(
            storage.calls,
            [("artifact", "model.start"), ("log", "model.start"),
             ("artifact", "model.outcome"), ("log", "model.outcome")],
        )


if __name__ == "__main__":
    unittest.main()

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from live_tracker.reader import RecordingError, read_attempt_events
from live_tracker.recorder import AttemptRecorder


class AttemptRecorderTests(unittest.TestCase):
    def test_records_contiguous_envelopes_with_linked_artifacts_and_torn_tail_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            attempt_dir = Path(temporary) / "attempt"
            recorder = AttemptRecorder(attempt_dir)
            recorder.emit("attempt_started", {"task_id": "t"})
            recorder.emit(
                "model.start", {"model_call": 1}, {"request.json": b'[{"role":"user"}]'},
                operation_id="model-1",
            )
            recorder.emit("model.outcome", {"status": "ok"}, operation_id="model-1", parent_operation_id=None)

            events = read_attempt_events(attempt_dir)
            self.assertEqual([event["sequence"] for event in events], [1, 2, 3])
            self.assertEqual({event["attempt_id"] for event in events}, {recorder.attempt_id})
            self.assertEqual(events[1]["operation_id"], "model-1")
            self.assertNotIn("operation_id", events[0])
            self.assertEqual(events[0]["schema"], "agent-eval-harness/attempt-events")
            self.assertEqual(events[0]["schema_version"], 1)

            [artifact] = events[1]["artifacts"]
            self.assertEqual(artifact["role"], "request.json")
            self.assertEqual(artifact["bytes"], len(b'[{"role":"user"}]'))
            self.assertEqual(artifact["sha256"], hashlib.sha256(b'[{"role":"user"}]').hexdigest())
            self.assertEqual((attempt_dir / artifact["path"]).read_bytes(), b'[{"role":"user"}]')

            # An interrupted final record leaves the verified prefix readable and is not a gap.
            with (attempt_dir / "events.jsonl").open("ab") as log:
                log.write(b'{"schema":"agent-eval')
            self.assertEqual(len(read_attempt_events(attempt_dir)), 3)

            # Corruption before the tail is a recording error, never silently skipped.
            lines = (attempt_dir / "events.jsonl").read_bytes().split(b"\n")
            lines[1] = b"not json"
            (attempt_dir / "events.jsonl").write_bytes(b"\n".join(lines))
            with self.assertRaises(RecordingError):
                read_attempt_events(attempt_dir)


if __name__ == "__main__":
    unittest.main()

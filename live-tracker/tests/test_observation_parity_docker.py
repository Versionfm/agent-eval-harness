import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_eval_harness.reports.compare_report import _load_attempt
from agent_eval_harness.harness.hooks import json_artifact
from live_tracker.reader import read_attempt_history
from live_tracker.recorder import AttemptRecorder
from live_tracker.run_scripted import read_then_complete_model, run_attempt


DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
SOURCE_REPOSITORY = Path(os.environ.get(
    "ML_TUTOR_REPOSITORY", "/home/francisco/prompt-engineering-group-project"
))


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for Docker attempt",
)
class ObservationParityDockerTests(unittest.TestCase):
    def test_observation_on_and_off_preserve_model_visible_and_canonical_outcomes(self):
        with tempfile.TemporaryDirectory(prefix="live-parity-") as temporary:
            root = Path(temporary)
            unobserved_model = read_then_complete_model()
            unobserved = run_attempt(
                admission_evidence=Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY,
                output_dir=root / "unobserved", model=unobserved_model,
            )
            observed_directory = root / "observed"
            observed_model = read_then_complete_model()
            observed = run_attempt(
                admission_evidence=Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY,
                output_dir=observed_directory, model=observed_model,
                event_sink=AttemptRecorder(observed_directory),
            )

            self.assertEqual(
                [request.messages for request in observed_model.requests],
                [request.messages for request in unobserved_model.requests],
            )
            self.assertEqual(
                [event["model_visible_result"] for event in observed["trace"] if event["type"] == "tool"],
                [event["model_visible_result"] for event in unobserved["trace"] if event["type"] == "tool"],
            )
            self.assertEqual(observed["candidate"]["files"], unobserved["candidate"]["files"])
            self.assertEqual(observed["evaluation"]["checks"], unobserved["evaluation"]["checks"])
            self.assertEqual(
                (observed["termination_reason"], observed["functional_verdict"]),
                (unobserved["termination_reason"], unobserved["functional_verdict"]),
            )
            self.assertEqual(observed["termination_reason"], "agent_completed")
            self.assertIn(observed["functional_verdict"], {"failure", "success"})

            history = read_attempt_history(observed_directory)
            self.assertEqual(history.state, "complete")
            # The projection written after the run is what the comparison loader reads.
            attempt = _load_attempt(observed_directory)
            self.assertEqual(attempt["functional_verdict"], observed["functional_verdict"])
            self.assertEqual(attempt["candidate"]["status"], "collected")
            self.assertEqual(attempt["evaluation"]["checks"], observed["evaluation"]["checks"])
            events = history.events
            self.assertEqual(
                [event["type"] for event in events],
                ["attempt_started", "initial_context", "phase.enter", "model.start", "model.outcome",
                 "state", "phase.enter", "tool.start", "tool.outcome", "state",
                 "phase.enter", "model.start", "model.outcome", "termination", "state",
                 "patch_collection", "evaluation", "attempt_finished"],
            )
            self.assertEqual(
                [event["operation_id"] for event in events if "operation_id" in event],
                ["model-1", "model-1", "tool-1-1", "tool-1-1", "model-2", "model-2"],
            )
            request_artifact = events[3]["artifacts"][0]
            self.assertEqual(
                (observed_directory / request_artifact["path"]).read_bytes(),
                json_artifact(observed_model.requests[0].messages),
            )
            for event in events:
                for artifact in event["artifacts"]:
                    content = (observed_directory / artifact["path"]).read_bytes()
                    self.assertEqual(hashlib.sha256(content).hexdigest(), artifact["sha256"])


if __name__ == "__main__":
    unittest.main()

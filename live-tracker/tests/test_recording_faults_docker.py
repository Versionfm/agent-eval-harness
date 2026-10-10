import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_eval_harness import tools
from agent_eval_harness.environment import DockerTaskContainer
from live_tracker.reader import read_attempt_history
from live_tracker.recorder import AttemptRecorder, FaultyStorage
from live_tracker.run_scripted import read_then_complete_model, run_attempt


DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
SOURCE_REPOSITORY = Path(os.environ.get(
    "ML_TUTOR_REPOSITORY", "/home/francisco/prompt-engineering-group-project"
))

# (fault, scripted model requests that were sent, tool dispatches, expected unresolved, marker saved)
CASES = {
    "initial context artifact": (("artifact", "initial_context", 1, {}), 0, 0, [], True),
    "first model start": (("log", "model.start", 1, {}), 0, 0, [], True),
    "second model start after a tool": (("log", "model.start", 2, {}), 1, 1, [], True),
    "tool start": (("log", "tool.start", 1, {}), 1, 0, [], True),
    "tool outcome artifact": (("artifact", "tool.outcome", 1, {}), 1, 1, ["tool-1-1"], True),
    "model outcome torn with no marker": (
        ("log", "model.outcome", 1, {"tear": True, "fail_marker": True}), 1, 0, ["model-1"], False,
    ),
    "model outcome with marker": (("log", "model.outcome", 1, {}), 1, 0, ["model-1"], True),
}


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for Docker attempts",
)
class RecordingFaultDockerTests(unittest.TestCase):
    def test_a_failed_mandatory_write_stops_further_work_and_cleans_up(self):
        for name, (fault, requests, dispatches, unresolved, marker_saved) in CASES.items():
            with self.subTest(fault=name), tempfile.TemporaryDirectory(prefix="live-fault-") as temporary:
                kind, event_type, occurrence, options = fault
                output = Path(temporary) / "attempt"
                storage = FaultyStorage(kind, event_type, occurrence=occurrence, **options)
                recorder = AttemptRecorder(output, storage=storage)
                model = read_then_complete_model()
                dispatch = mock.patch.object(tools, "_dispatch_tool", wraps=tools._dispatch_tool)
                close = mock.patch.object(DockerTaskContainer, "close", autospec=True,
                                          side_effect=DockerTaskContainer.close)
                with dispatch as dispatched, close as closed:
                    result = run_attempt(
                        admission_evidence=Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY,
                        output_dir=output, model=model, event_sink=recorder,
                    )

                self.assertEqual(len(model.requests), requests, "no model request after the failed record")
                self.assertEqual(dispatched.call_count, dispatches, "no tool dispatch after the failed record")
                # Evaluator probes close their own containers too; only the attempt's must close.
                attempt_closes = [call for call in closed.call_args_list
                                  if call.args[0].task_repository == output.resolve() / "task-repository"]
                self.assertEqual(len(attempt_closes), 1, "the attempt's task container is closed")
                self.assertEqual(result["recording"]["status"], "failed")
                self.assertIn("recording failed at", result["recording"]["error"])
                self.assertEqual(
                    "marker was saved" in result["recording"]["error"], marker_saved,
                )
                self.assertEqual(result["termination_reason"], "harness_error")
                # The candidate is still collected and scored during cleanup; its verdict stays a
                # canonical fact, distinct from the recording status.
                self.assertEqual(result["candidate"]["status"], "collected")
                self.assertEqual(result["evaluation"]["status"], "completed")
                self.assertIn(result["functional_verdict"], {"success", "failure"})

                history = read_attempt_history(output)
                self.assertEqual(history.unresolved_operations, unresolved)
                self.assertNotIn("attempt_finished", [event["type"] for event in history.events])
                self.assertEqual(history.state, "failed" if marker_saved else
                                 ("interrupted" if history.torn_tail_bytes else "open"))

    def test_a_failure_after_the_finish_keeps_termination_and_verdict_facts_separate(self):
        with tempfile.TemporaryDirectory(prefix="live-fault-") as temporary:
            output = Path(temporary) / "attempt"
            recorder = AttemptRecorder(output, storage=FaultyStorage("log", "attempt_finished"))
            result = run_attempt(
                admission_evidence=Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY,
                output_dir=output, event_sink=recorder,
            )
            self.assertEqual(result["termination_reason"], "agent_completed")
            self.assertIn(result["functional_verdict"], {"failure", "success"})
            self.assertEqual(result["recording"]["status"], "failed")
            self.assertEqual(read_attempt_history(output).state, "failed")
            self.assertTrue((output / "result.json").is_file(), "final artifacts are still written")


if __name__ == "__main__":
    unittest.main()

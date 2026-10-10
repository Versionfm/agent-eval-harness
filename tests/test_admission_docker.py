import os
from pathlib import Path
import tempfile
import unittest

from agent_eval_harness.admit import run_admission


DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
SOURCE_REPOSITORY = os.environ.get("ML_TUTOR_REPOSITORY")


@unittest.skipUnless(
    DOCKER_INTEGRATION and SOURCE_REPOSITORY,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_REPOSITORY to run Docker admission",
)
class DockerAdmissionOutcomeTests(unittest.TestCase):
    def test_pinned_baseline_defect_and_repair_produce_an_admitted_outcome(self):
        with tempfile.TemporaryDirectory(prefix="ml-tutor-admission-test-") as temporary:
            result = run_admission(Path(SOURCE_REPOSITORY), Path(temporary) / "evidence")

        self.assertEqual(result["assessment"]["status"], "admitted", result["assessment"])
        self.assertEqual(
            result["runs"]["defect"]["checks"]["title_retrieval"], False
        )
        self.assertEqual(
            result["runs"]["defect"]["checks"]["title_context"], False
        )
        self.assertEqual(
            result["runs"]["baseline"]["checks"]["title_retrieval"], True
        )
        self.assertEqual(
            result["runs"]["repair"]["checks"]["title_context"], True
        )
        self.assertCountEqual(
            [check for check, passed in result["runs"]["defect"]["checks"].items() if not passed],
            ["title_retrieval", "title_context", "input_order_independence"],
        )
        self.assertTrue(all(result["runs"]["baseline"]["checks"].values()))
        self.assertTrue(all(result["runs"]["repair"]["checks"].values()))
        self.assertEqual(result["container_configuration"]["network_mode"], "none")
        self.assertTrue(result["container_configuration"]["root_filesystem_read_only"])
        self.assertFalse(result["container_configuration"]["credentials_or_container_socket_mounted"])


if __name__ == "__main__":
    unittest.main()

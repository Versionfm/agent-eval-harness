import unittest
from pathlib import Path

from agent_eval_harness.loop import MODEL_PHASE_SOURCE, TOOL_PHASE_SOURCE
from live_tracker.sources import REGISTERED_SOURCES, resolve_source


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class SourceRegistryTests(unittest.TestCase):
    def test_registered_identity_resolves_to_its_file_and_function_lines(self):
        loop_text = (REPOSITORY_ROOT / "agent_eval_harness" / "loop.py").read_text(encoding="utf-8")
        expected_line = next(
            number for number, line in enumerate(loop_text.splitlines(), 1)
            if line.startswith("def _request_model_turn(")
        )

        source = resolve_source("agent_eval_harness.loop:_request_model_turn")

        self.assertEqual(source["file"], "agent_eval_harness/loop.py")
        self.assertEqual(source["line"], expected_line)
        self.assertTrue(source["text"].startswith("def _request_model_turn("))
        self.assertTrue(source["responsibility"])

    def test_phase_identities_emitted_by_the_loop_are_registered(self):
        self.assertIn(MODEL_PHASE_SOURCE, REGISTERED_SOURCES)
        self.assertIn(TOOL_PHASE_SOURCE, REGISTERED_SOURCES)
        self.assertEqual(resolve_source(TOOL_PHASE_SOURCE)["file"], "agent_eval_harness/tools.py")

    def test_unregistered_or_missing_identities_are_refused(self):
        for identity in ("os:system", "agent_eval_harness.loop:_missing", "../../etc/passwd", "nocolon"):
            with self.subTest(identity=identity):
                with self.assertRaises(KeyError):
                    resolve_source(identity)


if __name__ == "__main__":
    unittest.main()

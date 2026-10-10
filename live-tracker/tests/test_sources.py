import unittest
from pathlib import Path

from agent_eval_harness.harness.loop import MODEL_PHASE_SOURCE, TOOL_PHASE_SOURCE
from live_tracker.sources import LEGACY_IDENTITIES, REGISTERED_SOURCES, resolve_source


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class SourceRegistryTests(unittest.TestCase):
    def test_registered_identity_resolves_to_its_file_and_function_lines(self):
        loop_text = (REPOSITORY_ROOT / "agent_eval_harness" / "harness" / "loop.py").read_text(encoding="utf-8")
        expected_line = next(
            number for number, line in enumerate(loop_text.splitlines(), 1)
            if line.startswith("def _request_model_turn(")
        )

        source = resolve_source("agent_eval_harness.harness.loop:_request_model_turn")

        self.assertEqual(source["file"], "agent_eval_harness/harness/loop.py")
        self.assertEqual(source["line"], expected_line)
        self.assertTrue(source["text"].startswith("def _request_model_turn("))
        self.assertTrue(source["responsibility"])

    def test_identities_recorded_before_the_layout_move_resolve_to_the_same_source(self):
        for old, new in LEGACY_IDENTITIES.items():
            with self.subTest(identity=old):
                self.assertIn(new, REGISTERED_SOURCES)
                self.assertEqual(resolve_source(old), resolve_source(new))
        router = resolve_source("agent_eval_harness.langgraph_attempt:route_after_node")
        self.assertEqual(router["file"], "agent_eval_harness/harness/graph.py")
        self.assertTrue(router["text"].startswith("def route_after_node("))

    def test_phase_identities_emitted_by_the_loop_are_registered(self):
        self.assertIn(MODEL_PHASE_SOURCE, REGISTERED_SOURCES)
        self.assertIn(TOOL_PHASE_SOURCE, REGISTERED_SOURCES)
        self.assertEqual(resolve_source(TOOL_PHASE_SOURCE)["file"], "agent_eval_harness/harness/tools.py")

    def test_langgraph_node_and_router_identities_emitted_by_the_graph_are_registered(self):
        from agent_eval_harness.harness.graph import NODE_SOURCES, ROUTER_SOURCE

        for identity in [*NODE_SOURCES.values(), ROUTER_SOURCE]:
            with self.subTest(identity=identity):
                self.assertIn(identity, REGISTERED_SOURCES)
                self.assertTrue(resolve_source(identity)["text"].startswith("def "))

    def test_unregistered_or_missing_identities_are_refused(self):
        for identity in ("os:system", "agent_eval_harness.harness.loop:_missing", "../../etc/passwd", "nocolon"):
            with self.subTest(identity=identity):
                with self.assertRaises(KeyError):
                    resolve_source(identity)


if __name__ == "__main__":
    unittest.main()

"""Legacy first-live-pair playback (#14): read-only adapter, preserved bytes, honest labels.

The pair lives in the preserved evidence tree, outside this repository. The tests read it through
the public history reader and never write to it.
"""

import hashlib
import json
import os
import unittest
from pathlib import Path

from live_tracker.legacy import LEGACY_FORMAT
from live_tracker.reader import read_attempt_history


LEGACY_ROOT = Path(os.environ.get(
    "LIVE_FIRST_EVIDENCE",
    "/home/francisco/Documents/Codex/2026-10-10/d/outputs/evidence/live-first-2026-10-10",
))
PAIR = ("python-loop", "langgraph")
NEW_ONLY_TYPES = {
    "attempt_started", "attempt_finished", "model.start", "tool.start", "phase.enter",
    "node.enter", "node.outcome", "route.decision", "state",
}


def _tree_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


@unittest.skipUnless(LEGACY_ROOT.is_dir(), f"preserved first live pair not found at {LEGACY_ROOT}")
class LegacyPlaybackTests(unittest.TestCase):
    def test_reading_the_first_live_pair_changes_no_byte(self):
        before = _tree_digests(LEGACY_ROOT)
        for name in PAIR:
            history = read_attempt_history(LEGACY_ROOT / name, format=LEGACY_FORMAT)
            self.assertEqual(history.state, "legacy")
        self.assertEqual(_tree_digests(LEGACY_ROOT), before)

    def test_preserved_bytes_still_match_the_recorded_manifest(self):
        manifest = json.loads((LEGACY_ROOT / "artifact-sha256.json").read_text(encoding="utf-8"))
        checked = [rel for rel in manifest if rel.split("/", 1)[0] in PAIR]
        for name in PAIR:
            self.assertTrue(any(rel.startswith(f"{name}/") for rel in checked), name)
        for rel in checked:
            with self.subTest(file=rel):
                digest = hashlib.sha256((LEGACY_ROOT / rel).read_bytes()).hexdigest()
                self.assertEqual(digest, manifest[rel])

    def test_legacy_history_fabricates_no_starts_phases_nodes_or_state(self):
        for name in PAIR:
            with self.subTest(pair=name):
                history = read_attempt_history(LEGACY_ROOT / name, format=LEGACY_FORMAT)
                types = {event["type"] for event in history.events}
                self.assertFalse(types & NEW_ONLY_TYPES, types & NEW_ONLY_TYPES)
                status = history.status()
                self.assertEqual(status["format"], "legacy-trace")
                for label in ("attempt_started", "operation starts", "phase.enter", "node transitions",
                              "state", "elapsed_seconds", "recording status"):
                    self.assertIn(label, status["labels"]["unavailable"])
                self.assertEqual([event["sequence"] for event in history.events],
                                 list(range(1, len(history.events) + 1)))
                for event in history.events:
                    self.assertTrue(event["legacy"])
                    self.assertIsNone(event["elapsed_seconds"])
                    self.assertIn("elapsed_seconds", event["labels"]["unavailable"])

    def test_recorded_counts_match_the_legacy_trace(self):
        counts = {}
        for name in PAIR:
            history = read_attempt_history(LEGACY_ROOT / name, format=LEGACY_FORMAT)
            counts[name] = (
                sum(event["type"] == "model.outcome" for event in history.events),
                sum(event["type"] == "tool.outcome" for event in history.events),
            )
        self.assertEqual(counts, {"python-loop": (8, 15), "langgraph": (10, 14)})

    def test_tool_outputs_link_to_preserved_files_with_derived_digests_labelled(self):
        history = read_attempt_history(LEGACY_ROOT / "python-loop", format=LEGACY_FORMAT)
        tools = [event for event in history.events if event["type"] == "tool.outcome"]
        self.assertTrue(tools)
        for event in tools:
            with self.subTest(sequence=event["sequence"]):
                (artifact,) = [item for item in event["artifacts"] if item["role"] == "output.txt"]
                file = LEGACY_ROOT / "python-loop" / artifact["path"]
                self.assertEqual(artifact["sha256"], hashlib.sha256(file.read_bytes()).hexdigest())
                self.assertEqual(artifact["bytes"], file.stat().st_size)
                self.assertEqual(artifact["integrity"], "ok")
                self.assertIn("output.txt sha256 computed from current bytes", event["labels"]["derived"])
                self.assertIn("operation_id", event["labels"]["unavailable"])
                self.assertNotIn("output", event["data"]["result"], "full output stays in its artifact")

    def test_model_response_is_inline_and_labelled_as_recorded_in_the_trace(self):
        history = read_attempt_history(LEGACY_ROOT / "langgraph", format=LEGACY_FORMAT)
        model = next(event for event in history.events if event["type"] == "model.outcome")
        trace_line = next(
            json.loads(line) for line in (LEGACY_ROOT / "langgraph" / "trace.jsonl").read_text().splitlines()
            if json.loads(line).get("event_id") == model["sequence"]
        )
        self.assertEqual(model["data"]["response"], trace_line["response"])
        self.assertIn("response inline in legacy trace", model["labels"]["inline"])
        self.assertEqual(model["artifacts"], [])


if __name__ == "__main__":
    unittest.main()

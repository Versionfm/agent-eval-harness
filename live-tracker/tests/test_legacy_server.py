"""Legacy playback through the public HTTP interface (#14): events, linked outputs, bounded stream."""

import hashlib
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from live_tracker.legacy import LEGACY_FORMAT
from live_tracker.server import make_server


LEGACY_ROOT = Path(os.environ.get(
    "LIVE_FIRST_EVIDENCE",
    str(Path(__file__).resolve().parents[3] / "evidence" / "live-first-2026-10-10"),
))


@unittest.skipUnless(LEGACY_ROOT.is_dir(), "preserved first live pair not found")
class LegacyServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = LEGACY_ROOT / "python-loop"
        server = make_server({"legacy-python-loop": self.directory}, port=0,
                             formats={"legacy-python-loop": LEGACY_FORMAT})
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as response:
            return response.status, response.headers, response.read()

    def test_events_are_served_as_labelled_legacy_history(self):
        _, _, body = self._get("/api/attempts/legacy-python-loop/events?after=0")
        payload = json.loads(body)
        self.assertEqual(payload["recording"]["state"], "legacy")
        self.assertEqual(payload["recording"]["format"], "legacy-trace")
        self.assertEqual(len(payload["events"]), 27)
        self.assertEqual(payload["events"][0]["type"], "initial_context")

    def test_linked_tool_output_is_the_preserved_file(self):
        _, _, body = self._get("/api/attempts/legacy-python-loop/artifacts/tool-results/event-0003.txt")
        self.assertEqual(hashlib.sha256(body).hexdigest(),
                         hashlib.sha256((self.directory / "tool-results/event-0003.txt").read_bytes()).hexdigest())

    def test_artifacts_outside_the_registered_root_are_refused(self):
        for path in ("/api/attempts/legacy-python-loop/artifacts/../langgraph/result.json",
                     "/api/attempts/legacy-python-loop/artifacts/%2e%2e/langgraph/result.json"):
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as raised:
                self._get(path)
            self.assertIn(raised.exception.code, {403, 404})

    def test_stream_of_a_legacy_history_ends_after_its_events(self):
        with urllib.request.urlopen(self.base + "/api/attempts/legacy-python-loop/stream?after=0",
                                    timeout=10) as response:
            body = response.read().decode("utf-8")
        self.assertEqual(body.count("event: attempt-event"), 27)
        self.assertIn("event: recording-status", body)


if __name__ == "__main__":
    unittest.main()

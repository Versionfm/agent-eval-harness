"""Playback endpoints (#14) over loopback HTTP: mode, final results, and the projected report."""

import html
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from attempt_fixtures import CHECKS, PATCH, RESPONSE, record_attempt
from live_tracker.server import make_server


LEGACY_ROOT = Path(os.environ.get(
    "LIVE_FIRST_EVIDENCE",
    "/home/francisco/Documents/Codex/2026-10-10/d/outputs/evidence/live-first-2026-10-10",
))


class PlaybackServerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="live-playback-server-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.finished = self.root / "finished"
        record_attempt(self.finished)
        self.unfinished = self.root / "unfinished"
        record_attempt(self.unfinished, finish=False)
        attempts = {"finished": self.finished, "unfinished": self.unfinished}
        if LEGACY_ROOT.is_dir():
            attempts["legacy"] = LEGACY_ROOT / "python-loop"
        server = make_server(attempts, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as response:
            return response.headers, response.read()

    def test_a_saved_recording_is_played_back_and_an_open_one_is_followed_live(self):
        _, body = self._get("/api/attempts")
        modes = {item["attempt_id"]: item["mode"] for item in json.loads(body)}
        self.assertEqual(modes["finished"], "saved")
        self.assertEqual(modes["unfinished"], "live")

    def test_final_results_are_the_finish_record_facts(self):
        _, body = self._get("/api/attempts/finished/final")
        final = json.loads(body)
        self.assertEqual(final["functional_verdict"], "failure")
        self.assertEqual(final["termination_reason"], "agent_completed")
        self.assertEqual(final["candidate"]["patch"], PATCH)
        self.assertEqual(final["checks"], CHECKS)
        self.assertEqual(final["recording"]["status"], "complete")
        self.assertEqual(final["review"]["status"], "pending")

    def test_report_is_projected_from_the_log_and_served_with_a_restrictive_policy(self):
        headers, body = self._get("/api/attempts/finished/report")
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn(RESPONSE, html.unescape(body.decode("utf-8")))

    @unittest.skipUnless(LEGACY_ROOT.is_dir(), "preserved first live pair not found")
    def test_legacy_final_results_and_report_show_the_completed_review(self):
        _, body = self._get("/api/attempts/legacy/final")
        final = json.loads(body)
        self.assertEqual(final["functional_verdict"], "success")
        self.assertEqual(final["recording"]["status"], "legacy")
        self.assertEqual(final["review"]["status"], "completed")
        _, report = self._get("/api/attempts/legacy/report")
        self.assertIn("Qualitative review completed by Codex root orchestrator", report.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()

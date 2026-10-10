"""Loopback server rules for review fixes on #10: streams end after a finished recording; artifacts are allowlisted."""

import http.client
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from attempt_fixtures import FULL_OUTPUT, record_attempt
from live_tracker.reader import read_attempt_history
from live_tracker.server import make_server


class ServerReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="live-server-review-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "attempt"
        record_attempt(self.directory)
        # Files that exist beside the log but that no verified event references.
        (self.directory / "result.json").write_text("{}", encoding="utf-8")
        (self.directory / "task-repository").mkdir()
        (self.directory / "task-repository" / "secret.txt").write_text("not evidence", encoding="utf-8")
        self.server = make_server({"att": self.directory}, port=0)
        self.addCleanup(self.server.server_close)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def _get(self, path: str) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(connection.close)
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read()

    def _read_stream_until_closed(self, path: str, seconds: float = 10.0) -> tuple[bytes, bool]:
        """Read an SSE body for at most `seconds`; keepalive frames keep a live stream busy, so it may never time out."""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=1)
        self.addCleanup(sock.close)
        sock.sendall(f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n".encode("ascii"))
        chunks, deadline = [], time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                return b"".join(chunks), True
            chunks.append(chunk)
        return b"".join(chunks), False

    def test_a_stream_opened_after_the_attempt_finished_ends_after_its_status_frame(self):
        latest = read_attempt_history(self.directory).events[-1]["sequence"]
        body, closed = self._read_stream_until_closed(f"/api/attempts/att/stream?after={latest}")
        self.assertTrue(closed, "the server keeps streaming a finished attempt")
        text = body.decode("utf-8")
        self.assertIn("event: recording-status", text)
        self.assertIn('"state": "complete"', text)
        self.assertNotIn("event: attempt-event", text, "nothing is newer than the cursor")

    def test_only_artifacts_referenced_by_verified_events_are_served(self):
        history = read_attempt_history(self.directory)
        output = next(event for event in history.events if event["type"] == "tool.outcome")["artifacts"][0]
        status, body = self._get(f"/api/attempts/att/artifacts/{output['path']}")
        self.assertEqual(status, 200)
        self.assertEqual(body.decode("utf-8"), FULL_OUTPUT)

        for path in ("result.json", "task-repository/secret.txt", "metadata.json"):
            with self.subTest(path=path):
                status, _ = self._get(f"/api/attempts/att/artifacts/{path}")
                self.assertEqual(status, 404)

    def test_the_projected_report_is_served_in_place_of_the_file_on_disk(self):
        (self.directory / "report.html").write_text("stale file on disk", encoding="utf-8")
        status, body = self._get("/api/attempts/att/artifacts/report.html")
        self.assertEqual(status, 200)
        self.assertNotIn(b"stale file on disk", body)
        self.assertIn(b"<html", body.lower())


if __name__ == "__main__":
    unittest.main()

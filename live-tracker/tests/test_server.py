import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from live_tracker.recorder import AttemptRecorder
from live_tracker.server import make_server


class LoopbackServerTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        root = Path(self._temporary.name)
        self.attempt_dir = root / "attempt"
        self.secret = root / "secret.txt"
        self.secret.write_text("outside the registered root", encoding="utf-8")
        recorder = AttemptRecorder(self.attempt_dir, attempt_id="att1")
        recorder.emit("attempt_started", {"task_id": "t"})
        recorder.emit("tool.start", {"tool_name": "read_file"}, {"output.txt": b"full output"},
                      operation_id="tool-1-1")
        recorder.emit("attempt_finished", {"functional_verdict": "failure"})
        self.attempt_id = recorder.attempt_id
        self.server = make_server({self.attempt_id: self.attempt_dir}, port=0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._temporary.cleanup()

    def _get(self, path, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, response.getheader("Content-Type"), body

    def test_lists_events_after_a_cursor_and_serves_only_registered_artifacts(self):
        status, _, body = self._get("/api/attempts")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)[0]["attempt_id"], self.attempt_id)

        status, _, body = self._get(f"/api/attempts/{self.attempt_id}/events?after=1")
        self.assertEqual(status, 200)
        self.assertEqual([event["sequence"] for event in json.loads(body)["events"]], [2, 3])

        artifact = json.loads(self._get(f"/api/attempts/{self.attempt_id}/events")[2])["events"][1]["artifacts"][0]
        status, _, body = self._get(f"/api/attempts/{self.attempt_id}/artifacts/{artifact['path']}")
        self.assertEqual((status, body), (200, b"full output"))

        escapes = [
            f"/api/attempts/{self.attempt_id}/artifacts/../../secret.txt",
            f"/api/attempts/{self.attempt_id}/artifacts/..%2F..%2Fsecret.txt",
            f"/api/attempts/{self.attempt_id}/artifacts/{self.secret.resolve()}",
            "/api/attempts/unregistered/events",
        ]
        for path in escapes:
            with self.subTest(path=path):
                self.assertIn(self._get(path)[0], {403, 404})

    def test_stream_replays_from_last_event_id_with_contiguous_ids_and_closes_when_finished(self):
        status, content_type, body = self._get(
            f"/api/attempts/{self.attempt_id}/stream",
            {"Last-Event-ID": f"{self.attempt_id}:1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/event-stream")
        frames = [frame for frame in body.decode("utf-8").split("\n\n") if frame.strip()]
        self.assertEqual(
            [frame.splitlines()[0] for frame in frames],
            [f"id: {self.attempt_id}:2", f"id: {self.attempt_id}:3"],
        )
        self.assertIn("attempt_finished", frames[-1])


    def test_serves_only_registered_source_identities(self):
        identity = "agent_eval_harness.loop:run_python_loop"
        status, content_type, body = self._get(f"/api/sources?identity={identity}")
        self.assertEqual((status, content_type), (200, "application/json; charset=utf-8"))
        source = json.loads(body)
        self.assertEqual(source["file"], "agent_eval_harness/loop.py")
        self.assertTrue(source["text"].startswith("def run_python_loop("))

        for query in ("identity=os:system", "identity=../../secret.txt", "identity="):
            with self.subTest(query=query):
                self.assertEqual(self._get(f"/api/sources?{query}")[0], 404)


if __name__ == "__main__":
    unittest.main()

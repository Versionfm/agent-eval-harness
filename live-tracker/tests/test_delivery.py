"""Public HTTP/SSE delivery boundary: cursors, handoff, reconnect and slow observers."""

import http.client
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from live_tracker.recorder import AttemptRecorder
from live_tracker.server import make_server


BLOB = "x" * (1 << 20)  # 1 MiB per event: a stalled socket cannot absorb the whole attempt


def get(port, path, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    connection.request("GET", path, headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, body


def parse_frames(text):
    """Complete SSE frames only; a trailing partial frame is dropped, comment keepalives are ignored."""
    frames = []
    for block in text.split("\n\n")[:-1]:
        frame = {}
        for line in block.splitlines():
            if line and not line.startswith(":"):
                name, _, value = line.partition(": ")
                frame[name] = value
        if "event" in frame:  # the retry: preamble is not an event frame
            frames.append(frame)
    return frames


def sequences(frames):
    return [int(frame["id"].rpartition(":")[2]) for frame in frames if "id" in frame]


def serve(test, directory, attempt_id, **options):
    server = make_server({attempt_id: directory}, port=0, **options)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def stop():
        server.shutdown()
        server.server_close()

    test.addCleanup(stop)
    return server.server_address[1]


class DeliveryTestCase(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.directory = Path(self._temporary.name) / "attempt"
        self.recorder = AttemptRecorder(self.directory, attempt_id="att1")
        for index in range(3):
            self.recorder.emit("model.start", {"model_call": index})
        self.port = serve(self, self.directory, self.recorder.attempt_id)


class CursorTests(DeliveryTestCase):
    def test_rejects_cursors_for_another_attempt_or_beyond_the_latest_sequence(self):
        attempt = "/api/attempts/att1"
        for path, headers, expected in [
            (f"{attempt}/stream", {"Last-Event-ID": "other-attempt:1"}, 409),
            (f"{attempt}/stream", {"Last-Event-ID": "att1:99"}, 409),
            (f"{attempt}/stream?after=99", {}, 409),
            (f"{attempt}/events?after=99", {}, 409),
            (f"{attempt}/stream", {"Last-Event-ID": "att1:not-a-number"}, 409),
            (f"{attempt}/events?after=-1", {}, 400),
        ]:
            with self.subTest(path=path, headers=headers):
                status, body = get(self.port, path, headers)
                self.assertEqual(status, expected, body)
                self.assertIn("error", json.loads(body))


class HandoffTests(DeliveryTestCase):
    def test_history_then_live_stream_loses_nothing_while_the_recorder_keeps_appending(self):
        total = 200

        def record():
            for index in range(total):
                self.recorder.emit("model.start", {"model_call": index + 3})
                time.sleep(0.002)
            self.recorder.emit("attempt_finished", {"functional_verdict": "success"})

        # Subscribe while the recorder is appending, so the catch-up and live phases overlap.
        writer = threading.Thread(target=record)
        writer.start()
        status, body = get(self.port, "/api/attempts/att1/stream?after=0")
        writer.join()
        self.assertEqual(status, 200)
        frames = parse_frames(body.decode("utf-8"))
        self.assertEqual(sequences(frames), list(range(1, total + 5)))


class SlowObserverTests(unittest.TestCase):
    def test_stalled_observer_is_disconnected_and_resumes_from_disk_without_gaps(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name) / "attempt"
        recorder = AttemptRecorder(directory, attempt_id="att2")
        port = serve(self, directory, "att2", buffer_events=4, stall_seconds=0.5)

        # A consumer that connects and then stops reading, with a tiny receive window.
        slow = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(slow.close)
        slow.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        slow.connect(("127.0.0.1", port))
        slow.sendall(b"GET /api/attempts/att2/stream HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")

        # The recorder must keep appending at full speed while the observer is stalled.
        started = time.monotonic()
        for index in range(16):
            recorder.emit("tool.outcome", {"index": index, "blob": BLOB}, operation_id=f"tool-{index}")
        recorder.emit("attempt_finished", {"functional_verdict": "success"})
        self.assertLess(time.monotonic() - started, 60, "recording must not wait on the observer")

        # The observer stays stalled well past the stall timeout, then drains what the server sent.
        time.sleep(2)
        slow.settimeout(30)
        received = b""
        while chunk := slow.recv(65536):
            received += chunk
        first_frames = parse_frames(received.split(b"\r\n\r\n", 1)[1].decode("utf-8"))
        self.assertTrue(first_frames, "the observer should receive a prefix before disconnection")
        self.assertNotIn("attempt_finished", received.decode("utf-8"))
        last = sequences(first_frames)[-1]
        self.assertLess(last, 17)

        # Reconnecting from the last displayed cursor catches up from disk: no gap, no duplicate.
        status, body = get(port, "/api/attempts/att2/stream", {"Last-Event-ID": f"att2:{last}"})
        self.assertEqual(status, 200)
        resumed = parse_frames(body.decode("utf-8"))
        self.assertEqual(sequences(first_frames + resumed), list(range(1, 18)))


class ViewerDepartureTests(DeliveryTestCase):
    def test_a_viewer_that_leaves_mid_stream_does_not_affect_recording(self):
        viewer = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        viewer.sendall(b"GET /api/attempts/att1/stream HTTP/1.1\r\nHost: x\r\n\r\n")
        viewer.recv(4096)  # the viewer reads the start of the stream, then disappears
        viewer.close()
        for index in range(5):
            self.recorder.emit("model.start", {"model_call": index + 3})  # must not raise or block
        self.recorder.emit("attempt_finished", {"functional_verdict": "success"})
        status, body = get(self.port, "/api/attempts/att1/events")
        self.assertEqual(status, 200)
        self.assertEqual([event["sequence"] for event in json.loads(body)["events"]], list(range(1, 10)))


class HeadTests(DeliveryTestCase):
    def test_the_stream_reports_the_latest_recorded_sequence_for_lag(self):
        self.recorder.emit("attempt_finished", {"functional_verdict": "success"})
        status, body = get(self.port, "/api/attempts/att1/stream?after=0")
        self.assertEqual(status, 200)
        heads = [json.loads(frame["data"]) for frame in parse_frames(body.decode("utf-8"))
                 if frame["event"] == "head"]
        self.assertEqual(heads[-1], {"latest_sequence": 4})


if __name__ == "__main__":
    unittest.main()

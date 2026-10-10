"""No-provider demonstration of live delivery: reconnect, duplicate delivery and a slow observer.

Usage (from the repository root): PYTHONPATH=live-tracker/src python -m live_tracker.delivery_demo
A scripted recorder appends events to a temporary attempt while three raw SSE observers read the
loopback stream. The reconnecting observer drops and resumes from its cursor. The duplicate observer
resumes from an earlier cursor, so the server re-sends events and the observer dedupes by sequence.
The slow observer stops reading past the stall timeout, gets disconnected, and resumes from disk.
No model, tool or Docker is involved. The script ends with assertions and exits non-zero on failure.
"""

from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

from live_tracker.recorder import AttemptRecorder
from live_tracker.server import make_server


ATTEMPT = "demo"
EVENTS = 40
PAYLOAD = "x" * (256 * 1024)  # large enough that a stalled socket cannot absorb the whole attempt


def connect(port: int, last_id: int | None = None) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=30)
    request = f"GET /api/attempts/{ATTEMPT}/stream HTTP/1.1\r\nHost: 127.0.0.1\r\n"
    if last_id is not None:
        request += f"Last-Event-ID: {ATTEMPT}:{last_id}\r\n"
    sock.sendall((request + "\r\n").encode("ascii"))
    return sock


def read_sequences(sock: socket.socket, limit: int | None = None):
    """Yield (sequence, type) for each attempt event until EOF or `limit` events were read."""
    buffer = b""
    headers_read = False
    delivered = 0
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return
        buffer += chunk
        if not headers_read:
            if b"\r\n\r\n" not in buffer:
                continue
            _, buffer = buffer.split(b"\r\n\r\n", 1)
            headers_read = True
        while b"\n\n" in buffer:
            block, buffer = buffer.split(b"\n\n", 1)
            if not block.startswith(b"id: "):
                continue  # retry and head control frames
            payload = next(line[6:] for line in block.split(b"\n") if line.startswith(b"data: "))
            yield int(block.split(b"\n", 1)[0].rpartition(b":")[2]), json.loads(payload)["type"]
            delivered += 1
            if limit is not None and delivered == limit:
                return


def report(name: str, deliveries: list[int], connections: int, disconnections: int) -> dict:
    unique = sorted(set(deliveries))
    duplicates = len(deliveries) - len(unique)
    print(f"{name}: {len(unique)} unique, {duplicates} duplicates deduplicated by sequence, "
          f"{connections} connections, {disconnections} disconnected before finish", flush=True)
    return {"unique": unique, "duplicates": duplicates, "disconnections": disconnections}


def reconnecting_observer(port: int, result: dict) -> None:
    deliveries, connections, cursor, finished = [], 0, None, False
    while not finished:
        connections += 1
        sock = connect(port, cursor)
        for sequence, kind in read_sequences(sock, limit=10):
            deliveries.append(sequence)
            cursor = sequence
            finished = kind == "attempt_finished"
        sock.close()  # the observer drops its connection and reconnects from its cursor
    result["reconnecting"] = report("reconnecting observer", deliveries, connections, 0)


def duplicate_observer(port: int, result: dict) -> None:
    deliveries, connections = [], 1
    sock = connect(port)
    for sequence, _ in read_sequences(sock, limit=15):
        deliveries.append(sequence)
    sock.close()
    # Resume from an earlier cursor on purpose: the server re-sends 6..15 and the observer dedupes.
    connections += 1
    sock = connect(port, last_id=5)
    finished = False
    for sequence, kind in read_sequences(sock):
        deliveries.append(sequence)
        finished = finished or kind == "attempt_finished"
    sock.close()
    result["duplicate"] = report("duplicate observer", deliveries, connections, 0)


def slow_observer(port: int, result: dict) -> None:
    deliveries, connections, disconnections = [], 1, 0
    sock = connect(port)
    time.sleep(2)  # stop reading well past the server's stall timeout
    last, finished = 0, False
    for sequence, kind in read_sequences(sock):
        deliveries.append(sequence)
        last = sequence
        finished = kind == "attempt_finished"
    sock.close()
    if not finished:
        disconnections += 1  # the server cut the stalled connection before the attempt finished
        connections += 1
        sock = connect(port, last_id=last)
        for sequence, _ in read_sequences(sock):
            deliveries.append(sequence)
        sock.close()
    result["slow"] = report("slow observer", deliveries, connections, disconnections)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="live-delivery-demo-") as temporary:
        directory = Path(temporary) / "attempt"
        recorder = AttemptRecorder(directory, attempt_id=ATTEMPT)
        server = make_server({ATTEMPT: directory}, port=0, buffer_events=4, stall_seconds=0.5)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        result: dict = {}
        observers = [
            threading.Thread(target=reconnecting_observer, args=(port, result)),
            threading.Thread(target=duplicate_observer, args=(port, result)),
            threading.Thread(target=slow_observer, args=(port, result)),
        ]
        try:
            for observer in observers:
                observer.start()
            time.sleep(0.2)
            started = time.monotonic()
            for call in range(1, EVENTS + 1):
                recorder.emit("tool.outcome", {"index": call, "blob": PAYLOAD}, operation_id=f"tool-{call}")
            recorder.emit("attempt_finished", {"functional_verdict": "success"})
            print(f"recorder: {EVENTS + 1} events appended in {time.monotonic() - started:.2f}s "
                  "while observers were connected and one was stalled", flush=True)
            for observer in observers:
                observer.join(timeout=120)
        finally:
            server.shutdown()
            server.server_close()

        expected = list(range(1, EVENTS + 2))
        for name in ("reconnecting", "duplicate", "slow"):
            assert result[name]["unique"] == expected, (name, result[name]["unique"])
        assert result["duplicate"]["duplicates"] >= 10, "duplicate delivery was not exercised"
        assert result["slow"]["disconnections"] >= 1, "the stalled observer was not disconnected"
        print("delivery demo passed: no gaps, duplicates deduplicated, slow observer resumed from disk")
        return 0


if __name__ == "__main__":
    sys.exit(main())

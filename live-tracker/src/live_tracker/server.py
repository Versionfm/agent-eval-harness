"""Loopback HTTP server: compiled client, attempt history API, and SSE delivery."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import socket
import threading
import time
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlsplit

from live_tracker.projection import final_results, render_report
from live_tracker.reader import read_attempt_history
from live_tracker.sources import resolve_source


WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8"}
# ponytail: SSE re-reads the whole log each tick; an incremental byte-offset tail is the upgrade.
POLL_SECONDS = 0.2
# Per-connection delivery limits: frames waiting for one socket, and how long a full buffer may stall.
BUFFER_EVENTS = 256
STALL_SECONDS = 5.0
KEEPALIVE_SECONDS = 2.0
_END = object()


class _Refused(Exception):
    """A request the tracker answers with an explicit HTTP error rather than guessing."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class _Stalled(Exception):
    """The observer's buffer stayed full: its connection is cut, the attempt is not."""


class _Gone(Exception):
    """The observer's writer has stopped: the browser left or the socket failed."""


class _Observer:
    """One SSE connection: a bounded frame buffer drained by a writer thread that owns the socket."""

    def __init__(self, handler: BaseHTTPRequestHandler, buffer_events: int, stall_seconds: float):
        self.handler = handler
        self.stall_seconds = stall_seconds
        self.frames: queue.Queue = queue.Queue(maxsize=buffer_events)
        self.gone = threading.Event()
        self.writer = threading.Thread(target=self._drain, daemon=True)

    def offer(self, frame: Any) -> None:
        """Hand a frame to the writer; a buffer that stays full blocks only this connection's reader."""
        if self.gone.is_set():
            raise _Gone()
        try:
            self.frames.put(frame, timeout=self.stall_seconds)
        except queue.Full:
            raise _Stalled() from None

    def _drain(self) -> None:
        try:
            while True:
                try:
                    frame = self.frames.get(timeout=KEEPALIVE_SECONDS)
                except queue.Empty:
                    frame = ": keepalive\n\n"  # comment frame: a write to a departed browser fails here
                if frame is _END:
                    return
                self.handler.wfile.write(frame.encode("utf-8"))
                self.handler.wfile.flush()
        except OSError:
            pass
        finally:
            self.gone.set()


def _sse(data: Mapping[str, Any], *, event: str = "attempt-event", event_id: str | None = None) -> str:
    lines = [f"id: {event_id}"] if event_id else []
    lines += [f"event: {event}", f"data: {json.dumps(data, ensure_ascii=False, sort_keys=True)}"]
    return "\n".join(lines) + "\n\n"


class _TrackerHandler(BaseHTTPRequestHandler):
    attempts: dict[str, Path] = {}
    buffer_events = BUFFER_EVENTS
    stall_seconds = STALL_SECONDS

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        segments = [unquote(segment) for segment in url.path.split("/")]
        if url.path in {"/", "/index.html"}:
            return self._static("index.html")
        if len(segments) >= 3 and segments[1] == "static":
            return self._static("/".join(segments[2:]))
        if url.path == "/api/attempts":
            return self._json([self._summary(item) for item in self.attempts.items()])
        if url.path == "/api/sources":
            return self._source(url.query)
        if len(segments) >= 5 and segments[1:3] == ["api", "attempts"]:
            directory = self.attempts.get(segments[3])
            if directory is None:
                return self._json({"error": "unknown attempt"}, 404)
            action = segments[4]
            if action == "events" and len(segments) == 5:
                return self._events(segments[3], directory, url.query)
            if action == "stream" and len(segments) == 5:
                return self._stream(segments[3], directory, url.query)
            if action == "final" and len(segments) == 5:
                return self._final(directory)
            if action == "report" and len(segments) == 5:
                return self._report(directory)
            if action == "artifacts" and len(segments) >= 6:
                return self._artifact(directory, "/".join(segments[5:]))
        self._json({"error": "not found"}, 404)

    def _source(self, query: str) -> None:
        identity = parse_qs(query).get("identity", [""])[0]
        try:
            return self._json(resolve_source(identity))
        except (KeyError, ValueError):
            return self._json({"error": "unregistered source identity"}, 404)

    def _summary(self, item: tuple[str, Path]) -> dict[str, Any]:
        attempt_id, directory = item
        history = read_attempt_history(directory)
        return {
            "attempt_id": attempt_id,
            "event_count": len(history.events),
            "finished": bool(history.events) and history.events[-1]["type"] == "attempt_finished",
            "recording": history.status(),
            # Live means the recording may still grow; anything else is replayed as saved evidence.
            "mode": "live" if history.state in {"empty", "open"} else "saved",
            "format": history.format,
        }

    def _cursor(self, attempt_id: str, query: str, latest: int) -> int:
        """Resume point from ?after= and Last-Event-ID; an incompatible cursor is refused, not reinterpreted."""
        raw = parse_qs(query).get("after", ["0"])[0]
        if not raw.isdigit():
            raise _Refused(400, "after must be a non-negative integer")
        cursor = int(raw)
        header = self.headers.get("Last-Event-ID", "")
        if header:
            owner, _, number = header.rpartition(":")
            if owner != attempt_id or not number.isdigit():
                raise _Refused(409, f"Last-Event-ID {header!r} is not a cursor for attempt {attempt_id}")
            cursor = max(cursor, int(number))
        if cursor > latest:
            raise _Refused(409, f"cursor {cursor} is beyond the latest recorded sequence {latest}")
        return cursor

    def _events(self, attempt_id: str, directory: Path, query: str) -> None:
        history = read_attempt_history(directory)
        try:
            after = self._cursor(attempt_id, query, history.events[-1]["sequence"] if history.events else 0)
        except _Refused as exc:
            return self._json({"error": str(exc)}, exc.status)
        self._json({
            "events": [event for event in history.events if event["sequence"] > after],
            "recording": history.status(),
        })

    def _stream(self, attempt_id: str, directory: Path, query: str) -> None:
        history = read_attempt_history(directory)
        try:
            sent = self._cursor(attempt_id, query, history.events[-1]["sequence"] if history.events else 0)
        except _Refused as exc:
            return self._json({"error": str(exc)}, exc.status)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(b"retry: 500\n\n")
        self.wfile.flush()
        observer = _Observer(self, self.buffer_events, self.stall_seconds)
        observer.writer.start()
        reported = None
        last_status = None
        try:
            while True:
                history = read_attempt_history(directory)
                finished = False
                for event in history.events:
                    if event["sequence"] <= sent:
                        continue
                    sent = event["sequence"]
                    observer.offer(_sse(event, event_id=f"{attempt_id}:{sent}"))
                    finished = event["type"] == "attempt_finished"
                # Recording status follows the events it describes, so a client can close after them.
                status = history.status()
                if status != last_status:
                    last_status = status
                    observer.offer(_sse(status, event="recording-status"))
                head = history.events[-1]["sequence"] if history.events else 0
                if head != reported:
                    reported = head
                    observer.offer(_sse({"latest_sequence": head}, event="head"))
                # A preserved legacy trace never grows: its stream ends once its events are sent.
                if finished or history.state in {"corrupt", "failed", "legacy"}:
                    break
                if observer.gone.is_set():
                    return
                time.sleep(POLL_SECONDS)
            observer.offer(_END)
        except _Stalled:
            # A full buffer means this observer cannot keep up: cut its socket, never the recorder.
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        except _Gone:
            pass
        observer.writer.join()

    def _final(self, directory: Path) -> None:
        try:
            return self._json(final_results(directory))
        except (OSError, ValueError, KeyError) as exc:
            return self._json({"error": f"final results unavailable: {exc}"}, 500)

    def _report(self, directory: Path) -> None:
        try:
            body = render_report(directory).encode("utf-8")
        except (OSError, ValueError, KeyError) as exc:
            return self._json({"error": f"report unavailable: {exc}"}, 500)
        # The projected report holds recorded model and tool text: it may not run script or fetch anything.
        self._send(200, "text/html; charset=utf-8", body, {
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        })

    def _artifact(self, directory: Path, relative: str) -> None:
        root = directory.resolve()
        target = (root / relative).resolve()
        if root not in target.parents:
            return self._json({"error": "artifact is outside the registered root"}, 403)
        if not target.is_file():
            return self._json({"error": "artifact not found"}, 404)
        self._send(200, "text/plain; charset=utf-8", target.read_bytes(),
                   {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    def _static(self, relative: str) -> None:
        target = (WEB_ROOT / relative).resolve()
        suffix = target.suffix
        if WEB_ROOT not in target.parents or suffix not in STATIC_TYPES or not target.is_file():
            return self._json({"error": "not found"}, 404)
        self._send(200, STATIC_TYPES[suffix], target.read_bytes(), {"X-Content-Type-Options": "nosniff"})

    def _json(self, payload: Any, status: int = 200) -> None:
        self._send(status, "application/json; charset=utf-8",
                   json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
                   {"Cache-Control": "no-store"})

    def _send(self, status: int, content_type: str, body: bytes, headers: Mapping[str, str]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


def make_server(
    attempts: Mapping[str, Path], *, host: str = "127.0.0.1", port: int = 0,
    buffer_events: int = BUFFER_EVENTS, stall_seconds: float = STALL_SECONDS,
) -> ThreadingHTTPServer:
    """Serve registered attempt directories on loopback only."""
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("the live tracker serves loopback addresses only")
    registry = {attempt_id: Path(path).expanduser().resolve() for attempt_id, path in attempts.items()}
    handler = type("TrackerHandler", (_TrackerHandler,), {
        "attempts": registry, "buffer_events": buffer_events, "stall_seconds": stall_seconds,
    })
    return _Server((host, port), handler)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

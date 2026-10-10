"""Loopback HTTP server: compiled client, attempt history API, and SSE delivery."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import time
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlsplit

from live_tracker.reader import RecordingError, read_attempt_events


WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8"}
# ponytail: SSE polls the whole log each tick, fine for one local attempt; a seek index is the upgrade.
POLL_SECONDS = 0.2


class _TrackerHandler(BaseHTTPRequestHandler):
    attempts: dict[str, Path] = {}

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
        if len(segments) >= 5 and segments[1:3] == ["api", "attempts"]:
            directory = self.attempts.get(segments[3])
            if directory is None:
                return self._json({"error": "unknown attempt"}, 404)
            action = segments[4]
            if action == "events" and len(segments) == 5:
                return self._events(directory, url.query)
            if action == "stream" and len(segments) == 5:
                return self._stream(segments[3], directory, url.query)
            if action == "artifacts" and len(segments) >= 6:
                return self._artifact(directory, "/".join(segments[5:]))
        self._json({"error": "not found"}, 404)

    def _summary(self, item: tuple[str, Path]) -> dict[str, Any]:
        attempt_id, directory = item
        try:
            events = read_attempt_events(directory)
        except RecordingError as exc:
            return {"attempt_id": attempt_id, "recording_error": str(exc)}
        return {
            "attempt_id": attempt_id,
            "event_count": len(events),
            "finished": bool(events) and events[-1]["type"] == "attempt_finished",
        }

    def _events(self, directory: Path, query: str) -> None:
        try:
            after = int(parse_qs(query).get("after", ["0"])[0])
            events = read_attempt_events(directory)
        except ValueError:
            return self._json({"error": "after must be an integer"}, 400)
        except RecordingError as exc:
            return self._json({"error": str(exc)}, 500)
        self._json({"events": [event for event in events if event["sequence"] > after]})

    def _stream(self, attempt_id: str, directory: Path, query: str) -> None:
        sent = int(parse_qs(query).get("after", ["0"])[0] or 0)
        resume = self.headers.get("Last-Event-ID", "")
        if resume.startswith(f"{attempt_id}:") and resume.split(":", 1)[1].isdigit():
            sent = max(sent, int(resume.split(":", 1)[1]))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                try:
                    events = read_attempt_events(directory)
                except RecordingError as exc:
                    self._frame(f"event: recording-error\ndata: {json.dumps({'error': str(exc)})}\n\n")
                    return
                for event in events:
                    if event["sequence"] <= sent:
                        continue
                    sent = event["sequence"]
                    self._frame(
                        f"id: {attempt_id}:{sent}\nevent: attempt-event\n"
                        f"data: {json.dumps(event, ensure_ascii=False, sort_keys=True)}\n\n"
                    )
                    if event["type"] == "attempt_finished":
                        return
                time.sleep(POLL_SECONDS)
        except (BrokenPipeError, ConnectionResetError):
            # A departed browser never affects the attempt; the recorder keeps writing.
            return

    def _frame(self, text: str) -> None:
        self.wfile.write(text.encode("utf-8"))
        self.wfile.flush()

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
    attempts: Mapping[str, Path], *, host: str = "127.0.0.1", port: int = 0
) -> ThreadingHTTPServer:
    """Serve registered attempt directories on loopback only."""
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("the live tracker serves loopback addresses only")
    registry = {attempt_id: Path(path).expanduser().resolve() for attempt_id, path in attempts.items()}
    handler = type("TrackerHandler", (_TrackerHandler,), {"attempts": registry})
    return _Server((host, port), handler)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

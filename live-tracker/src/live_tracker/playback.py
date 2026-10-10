"""Playback server for saved recordings: new attempt logs and preserved legacy traces.

It registers each directory read-only and builds no provider, model, tool, container or attempt
object, so reviewing a recording cannot spend money or touch a repository.

Usage: PYTHONPATH=live-tracker/src python -m live_tracker.playback --recording DIR [--legacy DIR] [--port N]
Legacy example (the preserved first live pair, zero cost):
  PYTHONPATH=live-tracker/src python -m live_tracker.playback \
    --legacy <evidence>/live-first-2026-10-10/python-loop --legacy <evidence>/live-first-2026-10-10/langgraph
The viewer URL is printed; Ctrl+C stops the server.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Iterable

from live_tracker.legacy import LEGACY_FORMAT
from live_tracker.recorder import SCHEMA
from live_tracker.server import make_server


def registry(recordings: Iterable[Path] = (), legacy: Iterable[Path] = ()) -> dict[str, tuple[Path, str]]:
    """Attempt identities with their declared formats; a path that is not a directory is refused."""
    attempts: dict[str, tuple[Path, str]] = {}
    for kind, paths, fmt in (("recording", recordings, SCHEMA), ("legacy", legacy, LEGACY_FORMAT)):
        for path in paths:
            directory = Path(path).expanduser().resolve()
            if not directory.is_dir():
                raise ValueError(f"not a saved recording directory: {directory}")
            identity = f"{kind}-{directory.name}"
            if identity in attempts:
                raise ValueError(f"two recordings are both named {identity}")
            attempts[identity] = (directory, fmt)
    if not attempts:
        raise ValueError("register at least one saved recording with --recording or --legacy")
    return attempts


def make_playback_server(*, recordings: Iterable[Path] = (), legacy: Iterable[Path] = (), port: int = 0):
    attempts = registry(recordings, legacy)
    return make_server({identity: directory for identity, (directory, _) in attempts.items()},
                       formats={identity: fmt for identity, (_, fmt) in attempts.items()}, port=port)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recording", type=Path, action="append", default=[],
                        help="a completed, interrupted or failed attempt directory (repeatable)")
    parser.add_argument("--legacy", type=Path, action="append", default=[],
                        help="a preserved legacy trace directory (repeatable; read-only)")
    parser.add_argument("--port", type=int, default=8766, help="loopback port; 0 picks a free one")
    args = parser.parse_args(argv)
    try:
        server = make_playback_server(recordings=args.recording, legacy=args.legacy, port=args.port)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"playback: http://127.0.0.1:{server.server_address[1]}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

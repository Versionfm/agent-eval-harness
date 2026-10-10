"""Playback mode (#14): saved recordings, new and legacy, with every provider, container and tool boundary blocked.

The blocks are patched in-process, and a subprocess proves the playback server never imports the
provider, container, tool or attempt modules at all.
"""

import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from attempt_fixtures import record_attempt
from live_tracker.playback import make_playback_server


LEGACY_ROOT = Path(os.environ.get(
    "LIVE_FIRST_EVIDENCE",
    "/home/francisco/Documents/Codex/2026-10-10/d/outputs/evidence/live-first-2026-10-10",
))
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_MODULES = {
    "agent_eval_harness.attempt", "agent_eval_harness.deepseek", "agent_eval_harness.environment",
    "agent_eval_harness.tools", "agent_eval_harness.loop", "agent_eval_harness.langgraph_attempt",
    "agent_eval_harness.builtins", "agent_eval_harness.evaluation", "agent_eval_harness.admit",
}
BOUNDARIES = [
    ("agent_eval_harness.model", "ScriptedModel", "complete"),
    ("agent_eval_harness.deepseek", "DeepSeekModelAdapter", "complete"),
    ("agent_eval_harness.deepseek", "UrllibJsonTransport", "post_json"),
    ("agent_eval_harness.deepseek", None, "urlopen"),
    ("agent_eval_harness.environment", "DockerTaskContainer", "exec"),
    ("agent_eval_harness.tools", None, "_dispatch_tool"),
    ("agent_eval_harness.tools", None, "execute_tool_turn"),
    ("agent_eval_harness.loop", None, "_request_model_turn"),
]


def _digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def _fetch(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=10) as response:
        return response.read()


class PlaybackModeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="live-playback-mode-")
        self.addCleanup(temporary.cleanup)
        self.recording = Path(temporary.name) / "recording"
        record_attempt(self.recording)

    def _serve(self, recordings, legacy):
        server = make_playback_server(recordings=recordings, legacy=legacy, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_saved_recordings_play_back_with_every_provider_container_and_tool_boundary_blocked(self):
        legacy = [LEGACY_ROOT / "python-loop"] if LEGACY_ROOT.is_dir() else []
        patches = []
        for module, cls, name in BOUNDARIES:
            owner = importlib.import_module(module)
            if cls:
                owner = getattr(owner, cls)
            patches.append(mock.patch.object(owner, name, side_effect=AssertionError(
                f"playback must not call {module} {cls or ''} {name}")))
        mocks = [patch.start() for patch in patches]
        for patch in patches:
            self.addCleanup(patch.stop)
        before = _digests(self.recording)
        legacy_before = _digests(legacy[0]) if legacy else {}
        base = self._serve([self.recording], legacy)
        attempts = json.loads(_fetch(base, "/api/attempts"))
        self.assertEqual(len(attempts), 1 + len(legacy))
        for item in attempts:
            events = json.loads(_fetch(base, f"/api/attempts/{item['attempt_id']}/events?after=0"))["events"]
            self.assertTrue(events)
            self.assertIn("functional_verdict", json.loads(
                _fetch(base, f"/api/attempts/{item['attempt_id']}/final")))
            self.assertIn(b"<!doctype html>", _fetch(base, f"/api/attempts/{item['attempt_id']}/report"))
        for boundary in mocks:
            self.assertEqual(boundary.call_count, 0)
        self.assertEqual(_digests(self.recording), before, "playback never appends, resumes or rewrites")
        if legacy:
            self.assertEqual(_digests(legacy[0]), legacy_before)

    def test_playback_server_imports_no_provider_container_tool_or_attempt_module(self):
        legacy = str(LEGACY_ROOT / "python-loop") if LEGACY_ROOT.is_dir() else ""
        code = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "from live_tracker.playback import make_playback_server\n"
            "server = make_playback_server(recordings=[Path(sys.argv[1])], "
            "legacy=[Path(sys.argv[2])] if sys.argv[2] else [], port=0)\n"
            "server.server_close()\n"
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith('agent_eval_harness'))))\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code, str(self.recording), legacy],
            cwd=REPOSITORY_ROOT, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PYTHONPATH": str(REPOSITORY_ROOT / "live-tracker" / "src")},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        loaded = set(json.loads(completed.stdout.strip().splitlines()[-1]))
        self.assertFalse(loaded & FORBIDDEN_MODULES, loaded & FORBIDDEN_MODULES)

    @unittest.skipUnless(LEGACY_ROOT.is_dir(), "preserved first live pair not found")
    def test_the_documented_zero_cost_command_serves_the_preserved_pair(self):
        """The command in live-tracker/README.md: no provider key, no Docker, no byte written."""
        pair = LEGACY_ROOT / "python-loop"
        before = _digests(pair)
        process = subprocess.Popen(
            [sys.executable, "-m", "live_tracker.playback", "--legacy", str(pair), "--port", "0"],
            cwd=REPOSITORY_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, "PYTHONPATH": str(REPOSITORY_ROOT / "live-tracker" / "src")},
        )
        self.addCleanup(lambda: (process.kill(), process.communicate(timeout=10)))
        announcement = process.stdout.readline()
        self.assertTrue(announcement.startswith("playback: http://127.0.0.1:"), announcement)
        base = announcement.split("playback: ", 1)[1].strip().rstrip("/")
        attempts = json.loads(_fetch(base, "/api/attempts"))
        self.assertEqual([item["attempt_id"] for item in attempts], ["legacy-python-loop"])
        events = json.loads(_fetch(base, "/api/attempts/legacy-python-loop/events?after=0"))["events"]
        self.assertEqual(len(events), 27)
        self.assertEqual(_digests(pair), before, "the documented command writes nothing")


if __name__ == "__main__":
    unittest.main()

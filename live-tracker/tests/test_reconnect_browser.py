"""System-Chrome test: the viewer process dies and restarts while the attempt keeps recording.

No provider, Docker or tool is involved: the recorder appends scripted events directly.
"""

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

from live_tracker.recorder import AttemptRecorder


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LIVE_SOURCE = REPOSITORY_ROOT / "live-tracker" / "src"
ATTEMPT_ID = "att3"
VIEWER = (
    "import sys; from pathlib import Path; from live_tracker.server import make_server; "
    f"make_server({{{ATTEMPT_ID!r}: Path(sys.argv[1])}}, port=int(sys.argv[2])).serve_forever()"
)


def _reap(process):
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ReconnectBrowserTests(unittest.TestCase):
    def start_viewer(self, directory, port):
        process = subprocess.Popen(
            [sys.executable, "-c", VIEWER, str(directory), str(port)],
            env=dict(os.environ, PYTHONPATH=str(LIVE_SOURCE)),
        )
        self.addCleanup(_reap, process)
        deadline = time.monotonic() + 20
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/attempts", timeout=2).close()
                return process
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)

    def test_browser_shows_reconnect_and_catches_up_without_gaps_or_duplicates(self):
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory(prefix="live-reconnect-") as temporary:
            directory = Path(temporary) / "attempt"
            recorder = AttemptRecorder(directory, attempt_id=ATTEMPT_ID)
            for call in range(1, 6):
                recorder.emit("model.start", {"model_call": call}, operation_id=f"model-{call}")
            port = free_port()
            viewer = self.start_viewer(directory, port)
            state = "#status"

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome")
                try:
                    page = browser.new_page()
                    page.goto(f"http://127.0.0.1:{port}/")
                    page.wait_for_function(
                        "document.querySelectorAll('#timeline li[data-sequence]').length === 5"
                        f" && document.querySelector(\"{state}\").dataset.state === 'live'",
                        timeout=20_000,
                    )

                    # The viewer dies while the attempt keeps recording.
                    viewer.kill()
                    viewer.wait()
                    page.wait_for_function(
                        f"document.querySelector(\"{state}\").dataset.state === 'reconnecting'", timeout=20_000
                    )
                    for call in range(6, 11):
                        recorder.emit("model.start", {"model_call": call}, operation_id=f"model-{call}")

                    # The viewer comes back on the same port and the browser resumes from its cursor.
                    viewer = self.start_viewer(directory, port)
                    page.wait_for_function(
                        "document.querySelectorAll('#timeline li[data-sequence]').length === 10"
                        f" && document.querySelector(\"{state}\").dataset.state === 'live'",
                        timeout=30_000,
                    )
                    recorder.emit("attempt_finished", {"functional_verdict": "success"})
                    page.wait_for_function(
                        f"document.querySelector(\"{state}\").dataset.state === 'finished'", timeout=20_000
                    )
                    sequences = page.eval_on_selector_all(
                        "#timeline li[data-sequence]", "items => items.map(item => Number(item.dataset.sequence))"
                    )
                    gap_rows = page.eval_on_selector_all("#timeline li.gap", "items => items.length")
                    lag_text = page.inner_text("#lag")
                finally:
                    browser.close()

            self.assertEqual(sequences, list(range(1, 12)))
            self.assertEqual(gap_rows, 0)
            self.assertIn("lag 0", lag_text)


if __name__ == "__main__":
    unittest.main()

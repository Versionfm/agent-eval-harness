"""Closing the browser viewer mid-attempt does not stop the Docker scripted attempt.

Runs a real scripted attempt in the admitted task container. The system-Chrome viewer is closed
while the attempt is still running; the attempt must still reach attempt_finished and its artifacts.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LIVE_SOURCE = REPOSITORY_ROOT / "live-tracker" / "src"
DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
SOURCE_REPOSITORY = os.environ.get(
    "ML_TUTOR_REPOSITORY", "/home/francisco/prompt-engineering-group-project"
)


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for the detach attempt",
)
class ViewerDetachDockerTests(unittest.TestCase):
    def test_closing_the_viewer_mid_attempt_does_not_stop_the_attempt(self):
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory(prefix="live-detach-") as temporary:
            output = Path(temporary) / "attempt"
            command = [
                sys.executable, "-m", "live_tracker.run_scripted",
                "--admission-evidence", ADMISSION_EVIDENCE,
                "--source-repository", SOURCE_REPOSITORY,
                "--output-dir", str(output), "--port", "0",
            ]
            process = subprocess.Popen(
                command, cwd=REPOSITORY_ROOT, env=dict(os.environ, PYTHONPATH=str(LIVE_SOURCE)),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            try:
                first_line = process.stdout.readline()
                self.assertTrue(first_line.startswith("viewer: "), first_line)
                url = first_line.removeprefix("viewer: ").strip()
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="chrome")
                    try:
                        page = browser.new_page()
                        page.goto(url)
                        page.wait_for_selector('li[data-type="model.start"]', timeout=240_000)
                    finally:
                        browser.close()  # the viewer goes away while the attempt is still running

                log = output / "events.jsonl"
                closed_mid_attempt = not any(
                    '"attempt_finished"' in line for line in log.read_text(encoding="utf-8").splitlines()
                )
                self.assertTrue(closed_mid_attempt, "the viewer must close before the attempt finishes")

                # With no viewer attached, the attempt still runs to its own end.
                deadline = time.monotonic() + 900
                finished = False
                while time.monotonic() < deadline and not finished:
                    if log.is_file():
                        finished = any(
                            json.loads(line)["type"] == "attempt_finished"
                            for line in log.read_text(encoding="utf-8").splitlines()
                        )
                    time.sleep(1)
                self.assertTrue(finished, "the attempt must finish without the viewer")
                while not (output / "result.json").is_file() and time.monotonic() < deadline:
                    time.sleep(0.5)
                self.assertTrue((output / "result.json").is_file())
                events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
                self.assertEqual([event["sequence"] for event in events], list(range(1, len(events) + 1)))
                self.assertEqual(events[-1]["type"], "attempt_finished")
            finally:
                process.terminate()
                process.wait(timeout=60)
                process.stdout.close()


if __name__ == "__main__":
    unittest.main()

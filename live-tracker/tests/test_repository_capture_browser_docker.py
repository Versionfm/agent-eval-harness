"""Browser assertion for repository capture (#16): the inspector shows a capture for a mutating tool.

Runs the scripted `mutations` attempt through run_scripted in a Docker task container, opens the
viewer in system Chrome (channel="chrome"), selects the patch's tool outcome, and checks that the
inspector shows its captured repository change with the full-capture link.
"""

import os
from contextlib import contextmanager
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
    "ML_TUTOR_REPOSITORY", str(REPOSITORY_ROOT.parent / "prompt-engineering-group-project")
)


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for the browser attempt",
)
class RepositoryCaptureBrowserDockerTests(unittest.TestCase):
    @contextmanager
    def _viewer(self):
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory(prefix="capture-browser-") as temporary:
            output = Path(temporary) / "attempt"
            command = [
                sys.executable, "-m", "live_tracker.run_scripted",
                "--admission-evidence", ADMISSION_EVIDENCE,
                "--source-repository", SOURCE_REPOSITORY,
                "--output-dir", str(output), "--port", "0", "--scenario", "mutations",
            ]
            environment = dict(os.environ, PYTHONPATH=str(LIVE_SOURCE))
            process = subprocess.Popen(
                command, cwd=REPOSITORY_ROOT, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            try:
                first_line = process.stdout.readline()
                self.assertTrue(first_line.startswith("viewer: "), first_line)
                url = first_line.removeprefix("viewer: ").strip()
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="chrome")
                    try:
                        page = browser.new_page(viewport={"width": 1280, "height": 900})
                        page_errors = []
                        page.on("pageerror", lambda error: page_errors.append(str(error)))
                        page.goto(url)
                        page.wait_for_selector('#timeline li[data-type="attempt_finished"]', timeout=240_000)
                        yield page
                        self.assertEqual(page_errors, [])
                    finally:
                        browser.close()
            finally:
                deadline = time.monotonic() + 120
                while not (output / "result.json").is_file() and time.monotonic() < deadline:
                    time.sleep(0.5)
                process.terminate()
                process.wait(timeout=30)
                process.stdout.close()

    def test_inspector_shows_the_capture_of_a_mutating_tool(self):
        with self._viewer() as page:
            page.locator('#timeline li[data-type="tool.outcome"]').nth(0).locator("button").click()
            capture = page.locator('#inspector section.capture[data-capture-status="captured"]')
            capture.wait_for(timeout=10_000)
            text = capture.inner_text()
            self.assertIn("Repository changes after this tool", text)
            self.assertIn("notes/added.txt", text)
            self.assertIn("apply_patch_returned", text)
            self.assertTrue(capture.locator('a[data-artifact="capture.json"]').count() == 1)


if __name__ == "__main__":
    unittest.main()

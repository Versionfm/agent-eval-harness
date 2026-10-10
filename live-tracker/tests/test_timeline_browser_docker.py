import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.parse import urljoin


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LIVE_SOURCE = REPOSITORY_ROOT / "live-tracker" / "src"
DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
SOURCE_REPOSITORY = os.environ.get(
    "ML_TUTOR_REPOSITORY", "/home/francisco/prompt-engineering-group-project"
)


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for the browser attempt",
)
class TimelineBrowserDockerTests(unittest.TestCase):
    def test_system_chrome_timeline_shows_model_and_tool_starts_and_outcomes(self):
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory(prefix="live-browser-") as temporary:
            output = Path(temporary) / "attempt"
            command = [
                sys.executable, "-m", "live_tracker.run_scripted",
                "--admission-evidence", ADMISSION_EVIDENCE,
                "--source-repository", SOURCE_REPOSITORY,
                "--output-dir", str(output), "--port", "0",
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
                        page = browser.new_page()
                        page.goto(url)
                        page.wait_for_selector('li[data-type="attempt_finished"]', timeout=240_000)
                        types = page.eval_on_selector_all(
                            "#timeline li[data-type]", "items => items.map(item => item.dataset.type)"
                        )
                        status = page.inner_text("#status")
                        href = page.get_attribute('li[data-type="tool.outcome"] a', "href")
                        artifact = page.request.get(urljoin(url, href))
                        artifact_text = artifact.text()
                    finally:
                        browser.close()
            finally:
                # The finish event is recorded before final artifacts are written; wait for them.
                deadline = time.monotonic() + 120
                while not (output / "result.json").is_file() and time.monotonic() < deadline:
                    time.sleep(0.5)
                process.terminate()
                process.wait(timeout=30)
                process.stdout.close()

            self.assertEqual(status, "finished")
            self.assertEqual(
                types,
                ["attempt_started", "initial_context", "model.start", "model.outcome",
                 "tool.start", "tool.outcome", "model.start", "model.outcome", "attempt_finished"],
            )
            self.assertEqual(artifact.status, 200)
            self.assertTrue(artifact_text.strip(), "linked tool output must be retrievable")
            self.assertTrue((output / "events.jsonl").is_file())
            self.assertTrue((output / "result.json").is_file())


if __name__ == "__main__":
    unittest.main()

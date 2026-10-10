import tempfile
import threading
import unittest
from pathlib import Path

from live_tracker.recorder import AttemptRecorder, FaultyStorage
from live_tracker.server import make_server


def _failed_recording(directory: Path) -> str:
    recorder = AttemptRecorder(directory, storage=FaultyStorage("log", "tool.outcome"))
    recorder.emit("attempt_started", {"task_id": "t", "orchestrator": "python-loop"})
    recorder.emit("tool.start", {"tool_name": "read_file"}, operation_id="tool-1-1")
    try:
        recorder.emit("tool.outcome", {"status": "ok"}, operation_id="tool-1-1")
    except Exception:
        pass
    return recorder.attempt_id


def _interrupted_recording(directory: Path) -> str:
    recorder = AttemptRecorder(directory, storage=FaultyStorage("log", "model.outcome", tear=True,
                                                               fail_marker=True))
    recorder.emit("attempt_started", {"task_id": "t", "orchestrator": "python-loop"})
    recorder.emit("model.start", {"model_call": 1}, operation_id="model-1")
    try:
        recorder.emit("model.outcome", {"status": "ok"}, operation_id="model-1")
    except Exception:
        pass
    return recorder.attempt_id


class RecoveryBrowserTests(unittest.TestCase):
    def _serve(self, attempt_id: str, directory: Path):
        server = make_server({attempt_id: directory}, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}/"

    def test_system_chrome_shows_failed_and_interrupted_recordings_and_unresolved_operations(self):
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory(prefix="live-recovery-browser-") as temporary:
            root = Path(temporary)
            failed_dir, interrupted_dir = root / "failed", root / "interrupted"
            failed_id = _failed_recording(failed_dir)
            interrupted_id = _interrupted_recording(interrupted_dir)
            failed_url = self._serve(failed_id, failed_dir)
            interrupted_url = self._serve(interrupted_id, interrupted_dir)

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome")
                try:
                    page = browser.new_page()
                    page.goto(failed_url)
                    page.wait_for_selector("#recording:not([hidden])", timeout=30_000)
                    failed_banner = page.inner_text("#recording")
                    failed_status = page.inner_text("#status")
                    failed_label = page.inner_text('li[data-operation="tool-1-1"] .operation-state')
                    page.goto(interrupted_url)
                    page.wait_for_selector('li[data-operation="model-1"] .operation-state', timeout=30_000)
                    page.wait_for_function(
                        "document.querySelector('#recording') && "
                        "document.querySelector('#recording').textContent.includes('incomplete')",
                        timeout=30_000,
                    )
                    interrupted_banner = page.inner_text("#recording")
                    interrupted_label = page.inner_text('li[data-operation="model-1"] .operation-state')
                finally:
                    browser.close()

            self.assertIn("Recording failed while writing tool.outcome", failed_banner)
            self.assertIn("OSError: injected log append failure for tool.outcome", failed_banner)
            self.assertEqual(failed_status, "recording-error")
            self.assertEqual(failed_label, "unresolved")
            self.assertIn("Recording is incomplete", interrupted_banner)
            self.assertEqual(interrupted_label, "unresolved")


if __name__ == "__main__":
    unittest.main()

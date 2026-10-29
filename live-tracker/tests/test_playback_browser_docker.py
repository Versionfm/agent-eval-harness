"""Browser acceptance for saved playback (#14) in system Chrome, against Docker attempts and the legacy pair.

Fixtures: a complete new attempt, an interrupted one (torn final record) and a failed one (refused
mandatory write), all produced by the real harness in Docker, plus the preserved legacy pair. Every
expected value is read from the saved files directly, not from the code under test.
"""

import hashlib
import html
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from agent_eval_harness.bench.attempt import DEFAULT_SOURCE_REPOSITORY
from attempt_fixtures import build_docker_fixtures
from live_tracker.playback import make_playback_server


DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
SOURCE_REPOSITORY = DEFAULT_SOURCE_REPOSITORY
LEGACY_ROOT = Path(os.environ.get(
    "LIVE_FIRST_EVIDENCE",
    str(Path(__file__).resolve().parents[3] / "evidence" / "live-first-2026-10-10"),
))
# The viewer's presentation limit for retained output (inspector.ts EXCERPT_CHARS).
EXCERPT_CHARS = 2000


def _events(directory: Path) -> list[dict]:
    """The verified prefix only: bytes after the last newline are a torn append, not a record."""
    text = (directory / "events.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text[: text.rfind("\n") + 1].splitlines()]


def _artifact(directory: Path, event: dict, role: str) -> bytes:
    (artifact,) = [item for item in event["artifacts"] if item["role"] == role]
    return (directory / artifact["path"]).read_bytes()


def _tree_digests(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read()


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for the playback browser acceptance",
)
class PlaybackBrowserDockerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls.temporary = tempfile.TemporaryDirectory(prefix="live-playback-browser-")
        cls.fixtures = build_docker_fixtures(Path(cls.temporary.name), Path(ADMISSION_EVIDENCE),
                                             SOURCE_REPOSITORY)
        legacy = [LEGACY_ROOT / "python-loop", LEGACY_ROOT / "langgraph"] if LEGACY_ROOT.is_dir() else []
        cls.server = make_playback_server(recordings=list(cls.fixtures.values()), legacy=legacy, port=0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.temporary.cleanup()

    def _open(self, attempt_id: str):
        page = self.browser.new_page()
        errors: list[str] = []
        requests: list[tuple[str, str]] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append((request.method, request.url)))
        page.goto(f"{self.base}/?attempt={attempt_id}")
        page.wait_for_selector("#mode[data-mode]", timeout=30_000)
        page.wait_for_selector("#final [data-field]", timeout=30_000)
        self.addCleanup(page.close)
        self.addCleanup(lambda: self.assertEqual(errors, [], "viewer raised no page errors"))
        return page, requests

    def _field(self, page, name: str) -> str:
        return page.locator(f'[data-field="{name}"]').first.text_content() or ""

    def _select(self, page, sequence: int) -> None:
        page.click(f'li[data-sequence="{sequence}"] button.row')
        page.wait_for_function(
            "(n) => document.querySelector('li.selected')?.dataset.sequence === String(n)",
            arg=str(sequence), timeout=10_000,
        )

    def _position(self, page) -> int:
        return int((page.text_content("#position") or "").split("#")[1].split()[0])

    def test_new_recording_plays_back_with_controls_and_truthful_final_results(self):
        directory = self.fixtures["new-attempt"]
        events = _events(directory)
        final = next(event for event in events if event["type"] == "attempt_finished")
        page, requests = self._open("recording-new-attempt")
        self.assertEqual(page.get_attribute("#mode", "data-mode"), "saved")
        self.assertIn("Playback", page.text_content("#mode"))
        for control in ("#play", "#previous", "#next", "#speed", "#scrub", "#follow"):
            self.assertEqual(page.locator(control).count(), 1, control)
        # The final panel shows the finish record's facts, never the selected point's state.
        self.assertEqual(self._field(page, "functional-verdict"), final["data"]["functional_verdict"])
        self.assertEqual(self._field(page, "termination"), final["data"]["termination_reason"])
        self.assertIn("complete", self._field(page, "recording"))
        self.assertIn("pending", self._field(page, "review"))
        self.assertEqual(self._field(page, "candidate-patch"),
                         _artifact(directory, final, "candidate.patch").decode("utf-8"))

        total = len(events)
        self._select(page, 1)
        page.click("#next")
        self.assertEqual(self._position(page), 2)
        page.click("#previous")
        self.assertEqual(self._position(page), 1)
        page.select_option("#speed", "4")
        page.click("#play")
        page.wait_for_function("() => document.querySelector('#play').textContent.includes('Pause')")
        page.wait_for_function(
            "() => Number(document.querySelector('#position').textContent.match(/#(\\d+)/)[1]) >= 3",
            timeout=20_000,
        )
        page.click("#play")
        paused_at = self._position(page)
        time.sleep(1.5)
        self.assertEqual(self._position(page), paused_at, "pause stops playback")
        self.assertLessEqual(paused_at, total)
        self.assertTrue(all(method == "GET" for method, _ in requests), requests)
        for _, url in requests:
            path = urlsplit(url).path
            self.assertTrue(path == "/" or path.startswith(("/api/", "/static/")), url)

    def test_new_recording_viewer_matches_the_projected_report_for_every_evidence_kind(self):
        directory = self.fixtures["new-attempt"]
        events = _events(directory)
        model = next(event for event in events if event["type"] == "model.outcome" and event["data"]["model_call"] == 1)
        tool_start = next(event for event in events if event["type"] == "tool.start")
        tool = next(event for event in events if event["type"] == "tool.outcome")
        final = next(event for event in events if event["type"] == "attempt_finished")
        response = json.loads(_artifact(directory, model, "response.json"))
        full_output = _artifact(directory, tool, "output.txt").decode("utf-8")
        raw_report = _fetch(f"{self.base}/api/attempts/recording-new-attempt/report").decode("utf-8")
        report = html.unescape(raw_report)

        page, _ = self._open("recording-new-attempt")
        self._select(page, model["sequence"])
        reasoning = response["reasoning_fields"].get("reasoning_content", "")
        # A null field is shown as "not recorded", never as an empty or invented value.
        content = response["content"]
        self.assertEqual(self._field(page, "response-content"), content if content is not None else "not recorded")
        if content is not None:
            self.assertIn(content, report)
        self.assertEqual(self._field(page, "reasoning"), reasoning or "not recorded")
        self.assertEqual(self._field(page, "prompt-tokens"), str(response["usage"]["prompt_tokens"]))
        if reasoning:
            self.assertIn(reasoning, report)

        self._select(page, tool_start["sequence"])
        arguments = json.dumps(tool_start["data"]["arguments"]["command"])[1:-1]
        self.assertIn(arguments, self._field(page, "tool-arguments"))
        self.assertIn(arguments, report)

        self._select(page, tool["sequence"])
        shown = full_output[:EXCERPT_CHARS]
        self.assertEqual(self._field(page, "full-output"), shown)
        self.assertIn(shown, report, "the report keeps the complete retained output")
        self.assertIn("presentation excerpt", page.text_content("#inspector"))

        # Accounting as the report states it: a call without a recorded count is "missing", never zero.
        usages = [json.loads(_artifact(directory, event, "response.json")).get("usage", {})
                  for event in events if event["type"] == "model.outcome"
                  and any(item["role"] == "response.json" for item in event["artifacts"])]

        def total(key: str) -> str:
            values = [usage[key] for usage in usages if isinstance(usage.get(key), int)]
            missing = len(usages) - len(values)
            return str(sum(values)) + (f" known, {missing} missing" if missing else "")

        self.assertIn(f"input {total('prompt_tokens')}; output {total('completion_tokens')}", report)

        self.assertEqual(self._field(page, "functional-verdict"), final["data"]["functional_verdict"])
        self.assertIn(f"Functional verdict</dt><dd>{final['data']['functional_verdict']}</dd>", raw_report)

        # Final evidence: the same canonical checks and patch in the viewer and in the report.
        patch = _artifact(directory, final, "candidate.patch").decode("utf-8")
        if patch:
            self.assertIn(html.escape(patch), raw_report)
        else:
            self.assertIn("No repository changes were collected.", raw_report)
        for name, passed in final["data"]["checks"].items():
            state = "PASS" if passed is True else "FAIL"
            css = "good" if passed is True else "bad"
            self.assertIn(f"{name}: {state}", page.text_content("#final"))
            self.assertIn(f'<th>{name}</th><td class="{css}">{state}</td>', raw_report)

        # The final panel is the finish record's facts, unchanged by the selected point.
        final_before = page.text_content("#final")
        self._select(page, 1)
        self.assertEqual(page.text_content("#final"), final_before)

        # Every linked artifact serves exactly the bytes its recorded digest names.
        self._select(page, tool["sequence"])
        for link in page.locator("#evidence a[data-artifact]").all():
            role = link.get_attribute("data-artifact")
            recorded = next(item for item in tool["artifacts"] if item["role"] == role)
            served = _fetch(f"{self.base}{link.get_attribute('href')}")
            self.assertEqual(hashlib.sha256(served).hexdigest(), recorded["sha256"], role)

    def test_interrupted_recording_labels_the_torn_record_and_leaves_its_start_unresolved(self):
        directory = self.fixtures["interrupted-attempt"]
        page, _ = self._open("recording-interrupted-attempt")
        self.assertEqual(page.get_attribute("#mode", "data-mode"), "saved")
        self.assertIn("incomplete", page.text_content("#recording"))
        self.assertEqual(page.text_content('li[data-type="model.start"] .operation-status'), "unresolved")
        self.assertEqual(self._field(page, "functional-verdict"), "not recorded")
        self.assertEqual(self._field(page, "recording").split(":")[0].strip(), "interrupted")
        self.assertEqual(page.locator("li[data-sequence]").count(), len(_events(directory)))

    def test_failed_recording_reports_the_write_error_apart_from_the_verdict(self):
        page, _ = self._open("recording-failed-attempt")
        self.assertIn("Recording failed while writing tool.outcome", page.text_content("#recording"))
        self.assertEqual(self._field(page, "functional-verdict"), "not recorded")
        recording = self._field(page, "recording")
        self.assertIn("failed", recording)
        self.assertIn("injected log append failure for tool.outcome", recording)

    @unittest.skipUnless(LEGACY_ROOT.is_dir(), "preserved first live pair not found")
    def test_legacy_pair_plays_back_read_only_with_unavailable_and_derived_labels(self):
        before = _tree_digests(LEGACY_ROOT)
        page, requests = self._open("legacy-python-loop")
        self.assertEqual(page.get_attribute("#mode", "data-mode"), "saved")
        self.assertIn("Legacy", page.text_content("#recording"))
        trace = [json.loads(line) for line in
                 (LEGACY_ROOT / "python-loop" / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        model = next(record for record in trace if record["type"] == "model")
        self._select(page, model["event_id"])
        self.assertEqual(self._field(page, "response-content"), model["response"]["content"])
        self.assertIn("operation starts", page.text_content("#inspector"))
        self.assertIn("unavailable", page.text_content("#state"))

        tool = next(record for record in trace if record["type"] == "tool")
        self._select(page, tool["event_id"])
        output_link = page.get_attribute('a[data-artifact="output.txt"]', "href")
        self.assertTrue(output_link.endswith(tool["result"]["output_artifact"]), output_link)
        preserved = (LEGACY_ROOT / "python-loop" / tool["result"]["output_artifact"]).read_text(encoding="utf-8")
        self.assertEqual(self._field(page, "full-output"), preserved[:EXCERPT_CHARS])

        final = json.loads((LEGACY_ROOT / "python-loop" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(self._field(page, "functional-verdict"), final["functional_verdict"])
        self.assertIn("completed", self._field(page, "review"))
        self.assertTrue(all(method == "GET" for method, _ in requests), requests)
        page.close()
        self.assertEqual(_tree_digests(LEGACY_ROOT), before, "playing the legacy pair changes no byte")


if __name__ == "__main__":
    unittest.main()

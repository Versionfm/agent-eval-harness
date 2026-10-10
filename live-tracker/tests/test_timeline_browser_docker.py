"""Browser acceptance for the workbench (ticket #13, extended by #15) against controlled Docker attempts.

The file keeps its #11 name. Each test launches run_scripted, opens the viewer in system Chrome
and checks what a learner sees for one orchestrator: the Python phases, or the LangGraph nodes,
routing and source links recorded where they executed.
"""

from contextlib import contextmanager
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

COMPONENTS = [
    "attempt", "python-loop", "model-request", "tool-execution",
    "graph-model-node", "graph-tool-node", "graph-router",
]

EXPECTED_TYPES = [
    "attempt_started", "initial_context",
    # turn 1: model request, then one shell tool call and its repository capture (#16)
    "phase.enter", "model.start", "model.outcome", "state",
    "phase.enter", "tool.start", "tool.outcome", "tool.capture", "state",
    # turn 2: one failing read and one succeeding read in the same model response
    "phase.enter", "model.start", "model.outcome", "state",
    "phase.enter", "tool.start", "tool.outcome", "tool.start", "tool.outcome", "state",
    # turn 3: completion
    "phase.enter", "model.start", "model.outcome", "state",
    "attempt_finished",
]

# The same three model turns and two tool turns, as the LangGraph workflow records them.
EXPECTED_GRAPH_TYPES = [
    "attempt_started", "initial_context",
    # graph step 1: model_request, then the router sends the tool call to tool_execution
    "node.enter", "model.start", "model.outcome", "node.outcome", "state", "route.decision",
    # graph step 2: the shell tool call and its repository capture (#16)
    "node.enter", "tool.start", "tool.outcome", "tool.capture", "node.outcome", "state", "route.decision",
    # graph step 3: model_request asks for two reads, and the router sends them to tool_execution
    "node.enter", "model.start", "model.outcome", "node.outcome", "state", "route.decision",
    # graph step 4: tool_execution runs the failing and the succeeding read in order
    "node.enter", "tool.start", "tool.outcome", "tool.start", "tool.outcome", "node.outcome", "state",
    "route.decision",
    # graph step 5: completion ends the graph
    "node.enter", "model.start", "model.outcome", "node.outcome", "state", "route.decision",
    "attempt_finished",
]


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for the browser attempt",
)
class WorkbenchBrowserDockerTests(unittest.TestCase):
    @contextmanager
    def _viewer(self, orchestrator):
        """Run one scripted attempt, open it in system Chrome, and yield the loaded page."""
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory(prefix="live-browser-") as temporary:
            output = Path(temporary) / "attempt"
            command = [
                sys.executable, "-m", "live_tracker.run_scripted",
                "--admission-evidence", ADMISSION_EVIDENCE,
                "--source-repository", SOURCE_REPOSITORY,
                "--output-dir", str(output), "--port", "0", "--scenario", "workbench",
                "--orchestrator", orchestrator,
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
                        yield page, url
                        self.assertEqual(page_errors, [])
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

            self.assertTrue((output / "events.jsonl").is_file())
            self.assertTrue((output / "result.json").is_file())

    def test_system_chrome_workbench_inspects_phases_model_and_tool_evidence(self):
        with self._viewer("python-loop") as (page, url):
            self._check_timeline(page)
            self._check_component_navigation(page)
            self._check_model_evidence(page)
            self._check_tool_evidence(page, url)
            self._check_selected_point_state(page)
            self._check_source_link_from_phase(page)
            self._check_phone_layout(page)

    def test_system_chrome_workbench_shows_langgraph_node_transitions_and_router(self):
        with self._viewer("langgraph") as (page, url):
            self._check_graph_timeline(page)
            self._check_graph_component_counts(page)
            self._check_graph_router_and_node_sources(page)
            self._check_graph_model_and_tool_evidence(page, url)
            self._check_graph_selected_point_state(page)
            self._check_phone_layout(page)

    def _wait_for_inspector(self, page, expected):
        # The inspector renders after its artifacts load; wait for the expected evidence, then read it.
        page.wait_for_function(
            "text => document.querySelector('#inspector') !== null && "
            "document.querySelector('#inspector').innerText.includes(text)",
            arg=expected,
            timeout=30_000,
        )

    def _check_timeline(self, page):
        types = page.eval_on_selector_all(
            "#timeline li[data-type]", "items => items.map(item => item.dataset.type)"
        )
        self.assertEqual(types, EXPECTED_TYPES)
        self.assertEqual(page.inner_text("#status"), "finished")

    def _check_component_navigation(self, page):
        components = page.eval_on_selector_all(
            "#components button", "items => items.map(item => item.dataset.component)"
        )
        self.assertEqual(components, COMPONENTS)
        page.click('#components button[data-component="python-loop"]')
        self._wait_for_inspector(page, "Python loop: alternates")
        inspector = page.inner_text("#inspector")
        self.assertIn("agent_eval_harness/loop.py", inspector)
        self.assertIn("Python loop: alternates", inspector)
        self.assertIn("def run_python_loop(", page.inner_text("#inspector pre.source"))
        self.assertEqual(page.locator("#inspector script").count(), 0)

    def _check_model_evidence(self, page):
        page.locator('#timeline li[data-type="model.outcome"]').nth(0).locator("button").click()
        self._wait_for_inspector(page, "provider-exposed reasoning")
        inspector = page.inner_text("#inspector")
        self.assertIn("Probe the shell output before reading files.", inspector)
        self.assertIn("provider-exposed reasoning", inspector)
        self.assertIn("run_shell", inspector)
        self.assertIn("shell-1", inspector)
        self.assertIn("prompt_tokens: 11", inspector)

        page.locator('#timeline li[data-type="model.outcome"]').nth(2).locator("button").click()
        self._wait_for_inspector(page, "observed_model: not recorded")
        inspector = page.inner_text("#inspector")
        self.assertIn("observed_model: not recorded", inspector)
        self.assertIn("prompt_tokens: not recorded", inspector)

    def _check_tool_evidence(self, page, url):
        page.locator('#timeline li[data-type="tool.start"]').nth(0).locator("button").click()
        self._wait_for_inspector(page, "shell-1")
        inspector = page.inner_text("#inspector")
        self.assertIn("tool_call_id: shell-1", inspector)
        self.assertIn("arguments", inspector)
        self.assertIn("head -c 20000 /dev/zero", inspector)

        page.locator('#timeline li[data-type="tool.outcome"]').nth(0).locator("button").click()
        self._wait_for_inspector(page, "presentation excerpt")
        inspector = page.inner_text("#inspector")
        self.assertIn("shell-1", inspector)
        self.assertIn("run_shell", inspector)
        self.assertIn("duration", inspector)
        self.assertIn("model-visible output", inspector)
        self.assertIn("truncated: yes", inspector)
        self.assertIn("presentation excerpt", inspector)
        # Untrusted markup is shown as text, never created as elements.
        self.assertIn("<script>window.trackerProbe = true</script>", inspector)
        self.assertEqual(page.locator("#inspector script").count(), 0)
        self.assertIn("&lt;script&gt;", page.inner_html("#inspector"))
        href = page.get_attribute('#evidence a[data-artifact="output.txt"]', "href")
        full_output = page.request.get(urljoin(url, href)).text()
        self.assertGreater(len(full_output), 16384, "full output must be retained beyond the model-visible limit")

        page.locator('#timeline li[data-type="tool.outcome"]').nth(1).locator("button").click()
        self._wait_for_inspector(page, "read-missing")
        inspector = page.inner_text("#inspector")
        self.assertIn("read-missing", inspector)
        self.assertIn("status: error", inspector)
        self.assertIn("error:", inspector)

    def _check_selected_point_state(self, page):
        page.locator('#timeline li[data-type="state"]').nth(0).locator("button").click()
        early = page.inner_text("#state")
        self.assertIn("model calls: 1 / 4", early)
        page.locator('#timeline li[data-type="attempt_finished"]').locator("button").click()
        final = page.inner_text("#state")
        self.assertIn("model calls: 3 / 4", final)
        self.assertNotEqual(early, final)

    def _check_source_link_from_phase(self, page):
        page.locator('#timeline li[data-type="phase.enter"]').nth(1).locator("button").click()
        self._wait_for_inspector(page, "def ")
        inspector = page.inner_text("#inspector")
        self.assertIn("tool_execution", inspector)
        self.assertIn("agent_eval_harness.tools:execute_tool_turn", inspector)
        link = page.get_attribute('#inspector a[data-source]', "href")
        self.assertIn("/api/sources?identity=agent_eval_harness.tools:execute_tool_turn", link)

    def _check_graph_timeline(self, page):
        types = page.eval_on_selector_all(
            "#timeline li[data-type]", "items => items.map(item => item.dataset.type)"
        )
        self.assertEqual(types, EXPECTED_GRAPH_TYPES)
        self.assertEqual(page.inner_text("#status"), "finished")
        # Every recorded start has its outcome in a finished attempt: nothing is waiting or unresolved.
        # Starts: 5 graph node entries, 3 model requests and 3 tool calls.
        statuses = page.eval_on_selector_all(
            "#timeline .operation-status", "items => items.map(item => item.textContent)"
        )
        self.assertEqual(len(statuses), 11)
        self.assertEqual(set(statuses), {""})

    def _check_graph_component_counts(self, page):
        counts = dict(page.eval_on_selector_all(
            "#components button",
            "items => items.map(item => [item.dataset.component, item.querySelector('.count').textContent])",
        ))
        # Model node: 3 steps, each entry, outcome and state. Tool node: 2 steps. Router: 5 decisions.
        self.assertEqual(counts["graph-model-node"], "9")
        self.assertEqual(counts["graph-tool-node"], "6")
        self.assertEqual(counts["graph-router"], "5")

    def _check_graph_router_and_node_sources(self, page):
        page.click('#components button[data-component="graph-router"]')
        self._wait_for_inspector(page, "LangGraph router")
        inspector = page.inner_text("#inspector")
        self.assertIn("agent_eval_harness/langgraph_attempt.py", inspector)
        self.assertIn("def route_after_node(", page.inner_text("#inspector pre.source"))

        page.locator('#timeline li[data-type="route.decision"]').nth(0).locator("button").click()
        self._wait_for_inspector(page, "reason: tool_calls")
        inspector = page.inner_text("#inspector")
        self.assertIn("after_node: model_request", inspector)
        self.assertIn("next: tool_execution", inspector)

        page.locator('#timeline li[data-type="route.decision"]').nth(4).locator("button").click()
        self._wait_for_inspector(page, "reason: agent_completed")
        self.assertIn("next: end", page.inner_text("#inspector"))

        page.locator('#timeline li[data-type="node.enter"]').nth(1).locator("button").click()
        self._wait_for_inspector(page, "agent_eval_harness.tools:execute_tool_turn")
        inspector = page.inner_text("#inspector")
        self.assertIn("node: tool_execution", inspector)
        self.assertIn("graph_step_count: 2", inspector)
        self.assertIn("outcome: recorded at", inspector)
        link = page.get_attribute('#inspector a[data-source]', "href")
        self.assertIn("/api/sources?identity=agent_eval_harness.tools:execute_tool_turn", link)

    def _check_graph_model_and_tool_evidence(self, page, url):
        page.locator('#timeline li[data-type="model.outcome"]').nth(0).locator("button").click()
        self._wait_for_inspector(page, "provider-exposed reasoning")
        self.assertIn("Probe the shell output before reading files.", page.inner_text("#inspector"))
        page.locator('#timeline li[data-type="tool.outcome"]').nth(1).locator("button").click()
        self._wait_for_inspector(page, "read-missing")
        self.assertIn("status: error", page.inner_text("#inspector"))

    def _check_graph_selected_point_state(self, page):
        page.locator('#timeline li[data-type="state"]').nth(0).locator("button").click()
        early = page.inner_text("#state")
        self.assertIn("graph step 1, after node model_request", early)
        self.assertIn("model calls: 1 / 4", early)
        page.locator('#timeline li[data-type="attempt_finished"]').locator("button").click()
        self.assertIn("model calls: 3 / 4", page.inner_text("#state"))

    def _check_phone_layout(self, page):
        page.set_viewport_size({"width": 375, "height": 812})
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        self.assertLessEqual(overflow, 0, "no horizontal page scroll at phone width")


if __name__ == "__main__":
    unittest.main()

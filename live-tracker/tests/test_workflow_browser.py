"""System-Chrome acceptance for the execution workflow map (ticket #13) on saved fixtures.

No provider, Docker or tool is involved: the fixtures are written through the public recorder. Expected
counts, sequences and states below are literals derived by hand from attempt_fixtures.py, not from the client.
Sequences are 1-based: the timeline row #N is the event at sequence N.
"""

import tempfile
import threading
import unittest
from pathlib import Path

from attempt_fixtures import (
    record_interrupted_python_workflow,
    record_langgraph_workflow,
    record_open_python_workflow,
    record_python_workflow,
)
from live_tracker.server import make_server
from playwright.sync_api import sync_playwright


PYTHON_NODES = ["attempt", "model-request", "tool-execution", "repository-capture", "candidate", "checks", "finish"]
PYTHON_EDGES = ["start-model", "model-tool", "tool-model", "tool-capture", "model-candidate",
                "candidate-checks", "checks-finish"]
LANGGRAPH_NODES = ["attempt", "model-request", "graph-router", "tool-execution", "graph-end",
                   "candidate", "checks", "finish"]
LANGGRAPH_EDGES = ["start-model", "model-router", "router-model", "router-tool", "tool-router", "router-end",
                   "end-candidate", "candidate-checks", "checks-finish"]


class WorkflowMapBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workflow-map-")
        self.addCleanup(self.temporary.cleanup)
        self.playwright = sync_playwright().start()
        # Cleanups run last-in first-out: browsers close before Playwright stops.
        self.addCleanup(self.playwright.stop)
        self.browsers = []

    def directory(self, name: str) -> Path:
        return Path(self.temporary.name) / name

    def serve(self, directory: Path) -> str:
        server = make_server({"workflow": directory}, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}/?attempt=workflow"

    def open_page(self, directory: Path, rows: int, *, width=1280, height=900, scheme="light"):
        browser = self.playwright.chromium.launch(channel="chrome")
        self.addCleanup(browser.close)
        page = browser.new_page(viewport={"width": width, "height": height}, color_scheme=scheme)
        page.goto(self.serve(directory))
        page.wait_for_function(
            f"document.querySelectorAll('#timeline li[data-sequence]').length === {rows}"
            " && document.querySelector('#components g.wf-node') !== null",
            timeout=20_000,
        )
        return page

    def select(self, page, sequence: int) -> None:
        page.click(f'#timeline li[data-sequence="{sequence}"] button')

    def nodes(self, page) -> list[str]:
        return page.eval_on_selector_all(
            "#components g.wf-node", "items => items.map(item => item.dataset.component)"
        )

    def node(self, page, component: str) -> dict:
        return page.eval_on_selector(
            f'#components g.wf-node[data-component="{component}"]',
            "item => ({status: item.dataset.status, waiting: item.dataset.waiting,"
            " unresolved: item.dataset.unresolved, count: item.dataset.count})",
        )

    def active(self, page) -> list[str]:
        return page.eval_on_selector_all(
            "#components g.wf-node[data-status='active']", "items => items.map(item => item.dataset.component)"
        )

    def edges(self, page) -> dict[str, str]:
        return dict(page.eval_on_selector_all(
            "#components [data-edge]", "items => items.map(item => [item.dataset.edge, item.dataset.traversed])"
        ))

    def edge_ids(self, page) -> list[str]:
        return page.eval_on_selector_all("#components [data-edge]", "items => items.map(item => item.dataset.edge)")

    def match_rows(self, page) -> list[int]:
        return page.eval_on_selector_all(
            "#timeline li.match", "items => items.map(item => Number(item.dataset.sequence))"
        )

    def test_python_loop_map_draws_the_python_flow_with_recorded_counts(self):
        record_python_workflow(self.directory("python"))
        page = self.open_page(self.directory("python"), rows=19)

        self.assertEqual(page.get_attribute("#components", "data-flow"), "python-loop")
        self.assertEqual(self.nodes(page), PYTHON_NODES)
        self.assertEqual(self.edge_ids(page), PYTHON_EDGES)
        # Model: phase entries, model start and outcome, state after each model turn (seq 3-6, 12-15).
        self.assertEqual(self.node(page, "model-request")["count"], "8")
        # Tool: phase entry, start, outcome, state after the tool turn (seq 7-9, 11).
        self.assertEqual(self.node(page, "tool-execution")["count"], "4")
        self.assertEqual(self.node(page, "repository-capture")["count"], "1")
        self.assertEqual(self.node(page, "attempt")["count"], "2")
        for component in ["candidate", "checks", "finish"]:
            self.assertEqual(self.node(page, component)["count"], "1")
        self.assertEqual(self.active(page), ["finish"])

    def test_active_node_follows_the_selected_event(self):
        record_python_workflow(self.directory("python"))
        page = self.open_page(self.directory("python"), rows=19)

        self.select(page, 9)
        self.assertEqual(self.active(page), ["tool-execution"])
        self.select(page, 10)
        self.assertEqual(self.active(page), ["repository-capture"])
        self.select(page, 13)
        self.assertEqual(self.active(page), ["model-request"])
        self.select(page, 19)
        self.assertEqual(self.active(page), ["finish"])

    def test_nodes_after_the_selected_point_are_not_reached_and_edges_are_solid_only_when_traversed(self):
        record_python_workflow(self.directory("python"))
        page = self.open_page(self.directory("python"), rows=19)

        # Selected: model.start (seq 4). Only the first two events are known at this point.
        self.select(page, 4)
        self.assertEqual(self.node(page, "attempt")["status"], "reached")
        self.assertEqual(self.node(page, "model-request")["status"], "active")
        self.assertEqual(self.node(page, "model-request")["count"], "2")
        # The model outcome has not been shown yet, so the start is waiting at this point.
        self.assertEqual(self.node(page, "model-request")["waiting"], "true")
        for component in ["tool-execution", "repository-capture", "candidate", "checks", "finish"]:
            self.assertEqual(self.node(page, component)["status"], "not-reached", component)
        self.assertEqual(self.edges(page), {
            "start-model": "true", "model-tool": "false", "tool-model": "false",
            "tool-capture": "false", "model-candidate": "false",
            "candidate-checks": "false", "checks-finish": "false",
        })

        # After the tool turn: the model-to-tool edge is traversed; the loop-back is not yet.
        self.select(page, 9)
        self.assertEqual(self.node(page, "model-request")["waiting"], "false")
        self.assertEqual(self.edges(page)["model-tool"], "true")
        self.assertEqual(self.edges(page)["tool-model"], "false")
        self.assertEqual(self.node(page, "tool-execution")["count"], "3")

    def test_clicking_or_keying_a_node_highlights_its_timeline_rows(self):
        record_python_workflow(self.directory("python"))
        page = self.open_page(self.directory("python"), rows=19)

        page.click('#components g.wf-node[data-component="model-request"]')
        self.assertEqual(self.match_rows(page), [3, 4, 5, 6, 12, 13, 14, 15])
        page.wait_for_function(
            "document.querySelector('#inspector').innerText.includes('agent_eval_harness.harness.loop:_request_model_turn')",
            timeout=20_000,
        )

        page.focus('#components g.wf-node[data-component="tool-execution"]')
        page.keyboard.press("Enter")
        self.assertEqual(self.match_rows(page), [7, 8, 9, 11])
        # The inspector loads the registered source asynchronously: wait for the new identity to appear.
        page.wait_for_function(
            "document.querySelector('#inspector').innerText.includes('agent_eval_harness.harness.tools:execute_tool_turn')",
            timeout=20_000,
        )

    def test_langgraph_map_draws_routing_with_recorded_reasons(self):
        record_langgraph_workflow(self.directory("langgraph"))
        page = self.open_page(self.directory("langgraph"), rows=24)

        self.assertEqual(page.get_attribute("#components", "data-flow"), "langgraph")
        self.assertEqual(self.nodes(page), LANGGRAPH_NODES)
        self.assertEqual(self.edge_ids(page), LANGGRAPH_EDGES)
        self.assertEqual(self.node(page, "model-request")["count"], "10")
        self.assertEqual(self.node(page, "tool-execution")["count"], "5")
        self.assertEqual(self.node(page, "graph-router")["count"], "3")
        self.assertEqual(self.node(page, "graph-end")["count"], "1")
        self.assertEqual(self.active(page), ["finish"])
        self.assertEqual(set(self.edges(page).values()), {"true"})
        self.assertIn("agent_completed", page.text_content('#components [data-edge-label="router-end"]'))

        # At the first router decision only the model-to-router edge and the router-to-tool edge exist.
        self.select(page, 8)
        self.assertEqual(self.active(page), ["graph-router"])
        self.assertEqual(self.edges(page)["router-tool"], "true")
        self.assertEqual(self.edges(page)["router-end"], "false")
        self.assertEqual(self.node(page, "tool-execution")["status"], "not-reached")

    def test_start_without_outcome_is_waiting_while_live_and_unresolved_when_interrupted(self):
        record_open_python_workflow(self.directory("open"))
        page = self.open_page(self.directory("open"), rows=4)
        # The live attempt is still running: the newest start has no outcome yet.
        self.assertEqual(self.active(page), ["model-request"])
        self.assertEqual(self.node(page, "model-request")["waiting"], "true")
        self.assertEqual(self.node(page, "model-request")["unresolved"], "false")

        record_interrupted_python_workflow(self.directory("interrupted"))
        page = self.open_page(self.directory("interrupted"), rows=4)
        # The recording stopped before the outcome was written: the start is unresolved, not waiting.
        self.assertEqual(self.active(page), ["model-request"])
        self.assertEqual(self.node(page, "model-request")["unresolved"], "true")
        self.assertEqual(self.node(page, "model-request")["waiting"], "false")
        self.assertTrue(page.eval_on_selector(
            '#timeline li[data-sequence="4"]', "item => item.classList.contains('unresolved')"))

    def test_phone_width_has_no_page_scroll(self):
        record_python_workflow(self.directory("python"))
        page = self.open_page(self.directory("python"), rows=19, width=375, height=812)

        scroll = page.evaluate(
            "() => ({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth})"
        )
        self.assertLessEqual(scroll["scroll"], scroll["client"])


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace

from agent_eval_harness.bench.attempt import _initial_context
from agent_eval_harness.reports.report import render_attempt_report


class SingleAttemptReportTests(unittest.TestCase):
    def test_long_context_is_collapsed_and_missing_durations_have_no_unit(self):
        rendered = render_attempt_report({
            "functional_verdict": "failure",
            "termination_reason": "model_call_budget",
            "duration_seconds": None,
            "initial_context": [{"role": "system", "content": "Long prompt context."}],
            "trace": [
                {"event_id": 1, "type": "model", "status": "timeout"},
                {
                    "event_id": 2,
                    "type": "tool",
                    "tool_name": "run_shell",
                    "status": "error",
                    "result": {"status": "error", "output": "command failed"},
                },
            ],
            "candidate": {"status": "collected", "patch": ""},
            "evaluation": {"status": "completed", "checks": {"repair": False}},
            "metadata": {},
        })

        self.assertIn('<details class="initial-context">', rendered)
        self.assertNotIn('<details class="initial-context" open>', rendered)
        self.assertIn("Long prompt context.", rendered)
        self.assertIn("<dt>Duration</dt><dd>Unavailable</dd>", rendered)
        self.assertIn("<dt>Attempt duration</dt><dd>Unavailable</dd>", rendered)
        self.assertEqual(rendered.count("<small>Unavailable</small>"), 2)
        self.assertNotIn("Unavailable s</small>", rendered)

    def test_timeline_links_to_reasoning_tool_outputs_patch_and_checks(self):
        rendered = render_attempt_report({
            "functional_verdict": "failure",
            "termination_reason": "agent_completed",
            "trace": [
                {
                    "event_id": 1,
                    "type": "model",
                    "status": "ok",
                    "response": {
                        "reasoning_fields": {"reasoning_content": "inspect source"},
                        "content": "done",
                    },
                },
                {
                    "event_id": 2,
                    "type": "tool",
                    "tool_name": "run_shell",
                    "tool_call_id": "shell-call-7",
                    "arguments": {"command": "printf '<script>unsafe</script>'"},
                    "status": "ok",
                    "model_visible_result": {"output": "short", "truncated": True},
                    "result": {
                        "exit_code": 7,
                        "error_category": "command_failed",
                        "output": "full output <script>alert(1)</script>",
                        "output_artifact": "tool-results/event-0002.txt",
                    },
                },
                {"event_id": 3, "type": "patch_collection", "status": "completed"},
                {"event_id": 4, "type": "evaluation", "status": "completed"},
            ],
            "candidate": {"status": "collected", "patch": "diff"},
            "evaluation": {"status": "completed", "checks": {"title": False}},
            "metadata": {},
        })

        for href in (
            'href="#event-1-payload"',
            'href="#event-2-payload"',
            'href="#event-2-visible"',
            'href="#event-2-full-output"',
            'href="tool-results/event-0002.txt"',
            'href="#candidate-diff"',
            'href="#canonical-checks"',
        ):
            self.assertIn(href, rendered)
        self.assertIn("shell-call-7", rendered)
        self.assertIn("&quot;arguments&quot;", rendered)
        self.assertIn("&quot;tool_call_id&quot;", rendered)
        self.assertIn("&quot;exit_code&quot;: 7", rendered)
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertNotIn("<script>unsafe</script>", rendered)

    def test_timeline_rejects_traversal_in_artifact_links(self):
        rendered = render_attempt_report({
            "trace": [{
                "event_id": 1,
                "type": "tool",
                "tool_name": "run_shell",
                "status": "ok",
                "model_visible_result": {"truncated": True},
                "result": {"output": "large", "output_artifact": "../../secret.txt"},
            }],
            "candidate": {},
            "evaluation": {},
            "metadata": {},
        })

        self.assertNotIn('href="../../secret.txt"', rendered)
        self.assertIn("full output artifact: unavailable", rendered)

    def test_initial_file_map_keeps_source_and_tests_visible_after_asset_heavy_paths(self):
        with tempfile.TemporaryDirectory(prefix="initial-file-map-") as temporary:
            root = Path(temporary)
            (root / "app").mkdir()
            (root / "tests").mkdir()
            (root / ".github" / "assets").mkdir(parents=True)
            (root / "app" / "source.py").write_text("def retrieve(): pass\n")
            (root / "tests" / "test_source.py").write_text("def test_source(): pass\n")
            (root / "AGENTS.md").write_text("Use the public tests.\n")
            (root / "README.md").write_text("Repository overview.\n")
            for index in range(110):
                (root / ".github" / "assets" / f"image-{index:03}.svg").write_text("<svg/>")
            public_task = root / "task.md"
            public_task.write_text("Repair retrieval behavior.\n")

            messages = _initial_context(public_task, root)

        file_map = messages[1]["content"]
        self.assertIn("app/source.py", file_map)
        self.assertIn("tests/test_source.py", file_map)
        self.assertIn("Additional file counts by area: .github (", file_map)


if __name__ == "__main__":
    unittest.main()

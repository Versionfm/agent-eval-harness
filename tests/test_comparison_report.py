import json
from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest

from agent_eval_harness.compare_report import main


class RecordedComparisonReportTests(unittest.TestCase):
    def test_command_compares_saved_attempts_and_links_their_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python_attempt = root / "python-loop"
            graph_attempt = root / "langgraph"
            python_attempt.mkdir()
            graph_attempt.mkdir()
            output = root / "comparison.html"

            common_metadata = {
                "schema_version": "1",
                "task_id": "ml_tutor_retrieval",
                "task_version": "1",
                "source_revision": "abc123",
                "acceptance_check_version": "checks-v1",
                "task_container_image": "agent-eval-harness/ml-tutor-admission:1.0.0",
                "runtime_version": "3.12.13",
                "task_image_evidence": {
                    "dockerfile_sha256": "sha256:stable-task-recipe",
                    "runtime_version": "3.12.13",
                    "image_id": "sha256:unused",
                    "admission_image_id": "sha256:admission-image",
                },
                "provider": "deepseek",
                "requested_model": "deepseek-flash",
                "model_settings": {"thinking": {"type": "enabled", "effort": "low"}},
                "dependency_versions": {
                    "langgraph": "1.2.14",
                    "pydantic": "2.12.5",
                },
                "harness_revision": {
                    "commit": "deadbeef",
                    "working_tree": "dirty",
                    "working_tree_sha256": "sha256:shared-harness-tree",
                },
                "budgets": {"max_model_calls": 5},
                "usage_by_call": [{
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "reasoning_tokens": 4,
                    "prompt_cache_hit_tokens": 30,
                    "prompt_cache_miss_tokens": 70,
                }],
                "cost": {
                    "reported": {"status": "unavailable", "amount": None, "currency": "USD"},
                    "estimated": {"status": "estimated", "amount": 0.00021, "currency": "USD"},
                },
                "model_call_count": 1,
                "retry_count": 0,
                "attempt_duration_seconds": 1.25,
                "started_at": "2026-10-10T10:00:00+00:00",
            }

            def write_attempt(directory, orchestrator, verdict, termination, settings):
                metadata = {
                    **common_metadata,
                    "orchestrator": orchestrator,
                    "model_settings": settings,
                    "task_image_evidence": {
                        **common_metadata["task_image_evidence"],
                        "image_id": f"sha256:{orchestrator}-built-image",
                    },
                    "graph_step_count": 2 if orchestrator == "langgraph" else None,
                    "graph_step_limit": 11 if orchestrator == "langgraph" else None,
                }
                trace = [
                    {
                        "event_id": 1,
                        "type": "model",
                        "model_call": 1,
                        "status": "ok",
                        "duration_seconds": 0.75,
                        "response": {
                            "content": "Inspecting files.",
                            "reasoning_fields": {"reasoning_content": "Diagnosis <script>alert(1)</script>"},
                            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                            "tool_calls": [],
                        },
                    },
                    {
                        "event_id": 2,
                        "type": "tool",
                        "tool_name": "run_shell",
                        "tool_call_id": "shell-1",
                        "status": "error",
                        "duration_seconds": 0.125,
                        "arguments": {"command": "echo '<script>bad</script>'"},
                        "result": {
                            "status": "error",
                            "output": "The selected task output was truncated.",
                            "error": "command failed",
                            "output_artifact": "tool-results/event-0002.txt",
                        },
                        "model_visible_result": {
                            "status": "error",
                            "output": "The selected task output was truncated.",
                            "truncated": True,
                        },
                    },
                    {"event_id": 3, "type": "patch_collection", "status": "completed"},
                    {
                        "event_id": 4,
                        "type": "evaluation",
                        "status": "completed",
                        "checks": {"title_only_retrieval": verdict == "success"},
                    },
                    {"event_id": 5, "type": "termination", "reason": termination},
                ]
                result = {
                    "termination_reason": termination,
                    "functional_verdict": verdict,
                    "failure_category": "canonical_check_failure" if verdict == "failure" else None,
                    "duration_seconds": 1.5,
                    "initial_context": [{"role": "system", "content": "A" * 4000}],
                    "trace": trace,
                    "candidate": {
                        "status": "collected",
                        "changed_files": ["app/source.py"],
                        "patch": "--- a/app/source.py\n+++ b/app/source.py\n@@ -1 +1 @@\n-old\n+new\n",
                    },
                    "evaluation": {
                        "status": "completed",
                        "checks": {"title_only_retrieval": verdict == "success"},
                        "messages": {"title_only_retrieval": "Canonical evidence."},
                    },
                    "metadata": metadata,
                }
                (directory / "metadata.json").write_text(
                    json.dumps(metadata), encoding="utf-8"
                )
                (directory / "trace.jsonl").write_text(
                    "".join(json.dumps(event) + "\n" for event in trace), encoding="utf-8"
                )
                (directory / "result.json").write_text(
                    json.dumps(result), encoding="utf-8"
                )
                (directory / "candidate.patch").write_text(
                    result["candidate"]["patch"], encoding="utf-8"
                )
                (directory / "checks.json").write_text(
                    json.dumps(result["evaluation"]), encoding="utf-8"
                )
                tool_results = directory / "tool-results"
                tool_results.mkdir()
                (tool_results / "event-0002.txt").write_text(
                    "full retained command output", encoding="utf-8"
                )

            write_attempt(
                python_attempt, "python-loop", "success", "agent_completed",
                {"thinking": {"type": "enabled", "effort": "low"}},
            )
            write_attempt(
                graph_attempt, "langgraph", "failure", "model_call_budget",
                {"thinking": {"type": "enabled", "effort": "high"}},
            )

            self.assertEqual(main([
                "--python-loop", str(python_attempt),
                "--langgraph", str(graph_attempt),
                "--output", str(output),
            ]), 0)

            rendered = output.read_text(encoding="utf-8")
            self.assertLess(
                rendered.index('class="outcome-pair"'),
                rendered.index('<section class="config">'),
                "outcome cards should lead the report before detailed configuration",
            )
            self.assertLess(
                rendered.index('<section class="config">'),
                rendered.index('class="pair"'),
                "configuration summary should remain before the detailed timelines",
            )
            self.assertIn('class="outcome-card"', rendered)
            self.assertIn("Model requests / retries", rendered)
            self.assertIn('class="config-overview"', rendered)
            self.assertIn('class="config-table-scroll"', rendered)
            self.assertIn('<details class="config-values">', rendered)
            self.assertNotIn('<details class="config-values" open>', rendered)
            self.assertIn("Image identifiers (audit)", rendered)
            self.assertIn("sha256:python-loop-built-image", rendered)
            self.assertIn("sha256:langgraph-built-image", rendered)
            self.assertIn("Configuration match", rendered)
            self.assertRegex(
                rendered,
                r"Task Dockerfile and runtime</th><td><span class=\"status good\">match</span>",
            )
            self.assertRegex(
                rendered,
                r"Model settings</th><td><span class=\"status bad\">mismatch</span>",
            )
            self.assertRegex(
                rendered,
                r"Observed model</th><td><span class=\"status unknown\">unavailable</span>",
            )
            self.assertRegex(
                rendered,
                r"Orchestrator dependency versions</th><td><span class=\"status good\">match</span>",
            )
            self.assertRegex(
                rendered,
                r"Harness revision</th><td><span class=\"status good\">match</span>",
            )

            # A common mutable tag and differing built image IDs do not establish recipe parity.
            graph_metadata_path = graph_attempt / "metadata.json"
            graph_metadata = json.loads(graph_metadata_path.read_text(encoding="utf-8"))
            graph_metadata["task_image_evidence"]["dockerfile_sha256"] = "sha256:other-recipe"
            graph_metadata_path.write_text(json.dumps(graph_metadata), encoding="utf-8")
            mismatch_output = root / "recipe-mismatch.html"
            self.assertEqual(main([
                "--python-loop", str(python_attempt),
                "--langgraph", str(graph_attempt),
                "--output", str(mismatch_output),
            ]), 0)
            mismatch_rendered = mismatch_output.read_text(encoding="utf-8")
            self.assertRegex(
                mismatch_rendered,
                r"Task Dockerfile and runtime</th><td><span class=\"status bad\">mismatch</span>",
            )

            graph_metadata = json.loads(graph_metadata_path.read_text(encoding="utf-8"))
            graph_metadata["dependency_versions"]["langgraph"] = "different-version"
            graph_metadata["harness_revision"]["working_tree_sha256"] = "sha256:other-tree"
            graph_metadata_path.write_text(json.dumps(graph_metadata), encoding="utf-8")
            provenance_output = root / "provenance-mismatch.html"
            self.assertEqual(main([
                "--python-loop", str(python_attempt),
                "--langgraph", str(graph_attempt),
                "--output", str(provenance_output),
            ]), 0)
            provenance_rendered = provenance_output.read_text(encoding="utf-8")
            self.assertRegex(
                provenance_rendered,
                r"Orchestrator dependency versions</th><td><span class=\"status bad\">mismatch</span>",
            )
            self.assertRegex(
                provenance_rendered,
                r"Harness revision</th><td><span class=\"status bad\">mismatch</span>",
            )
            self.assertIn("Diagnosis &lt;script&gt;alert(1)&lt;/script&gt;", rendered)
            self.assertNotIn("<script>alert(1)</script>", rendered)
            self.assertIn("reasoning_content", rendered)
            self.assertIn("Model-visible output was truncated", rendered)
            self.assertIn('href="#python-reasoning-1"', rendered)
            self.assertIn('href="#python-visible-2"', rendered)
            self.assertIn('href="#python-diff"', rendered)
            self.assertIn('href="#python-checks"', rendered)
            self.assertIn("event-0002.txt", rendered)
            self.assertIn("candidate.patch", rendered)
            self.assertIn("checks.json", rendered)
            self.assertIn("Cache-hit input tokens", rendered)
            self.assertIn("Cache-miss input tokens", rendered)
            self.assertIn("Estimated cost", rendered)
            self.assertIn("Reported charge", rendered)
            self.assertIn("command failed", rendered)
            self.assertIn("Model latency", rendered)
            self.assertIn("Tool latency", rendered)
            self.assertIn("Qualitative review pending", rendered)
            self.assertIn('<details class="initial-context">', rendered)
            self.assertNotIn('<details class="initial-context" open>', rendered)
            self.assertIn("Canonical evidence.", rendered)
            self.assertIn("2 / 11 nodes", rendered)

            review = {
                "schema_version": "1",
                "status": "complete",
                "reviewer": "Fixture reviewer",
                "reviewed_at": "2026-10-10T12:00:00+00:00",
                "attempt": {
                    "task_id": "ml_tutor_retrieval",
                    "orchestrator": "python-loop",
                    "source_revision": "abc123",
                    "started_at": "2026-10-10T10:00:00+00:00",
                },
                "assessment": {
                    "diagnosis": "Fixture diagnosis evidence.",
                    "tool_use": "Fixture tool evidence.",
                    "patch_quality": "Fixture patch evidence.",
                    "failures": "Fixture failure evidence.",
                },
                "summary": "Fixture review summary.",
            }
            review_path = root / "review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            reviewed_output = root / "reviewed-comparison.html"
            self.assertEqual(main([
                "--python-loop", str(python_attempt),
                "--langgraph", str(graph_attempt),
                "--output", str(reviewed_output),
                "--python-review", str(review_path),
            ]), 0)
            reviewed = reviewed_output.read_text(encoding="utf-8")
            self.assertIn("Reviewed by Fixture reviewer", reviewed)
            self.assertIn("Fixture diagnosis evidence.", reviewed)
            self.assertIn("Qualitative review pending", reviewed)

            review["reviewed_at"] = "2026-10-10T12:00:00"
            naive_review = root / "naive-review.json"
            naive_review.write_text(json.dumps(review), encoding="utf-8")
            with self.assertRaises(SystemExit) as error, redirect_stderr(io.StringIO()):
                main([
                    "--python-loop", str(python_attempt),
                    "--langgraph", str(graph_attempt),
                    "--output", str(root / "naive-review.html"),
                    "--python-review", str(naive_review),
                ])
            self.assertEqual(error.exception.code, 2)

            review["reviewed_at"] = "2026-10-10T12:00:00+00:00"
            review["attempt"]["source_revision"] = "other-source"
            invalid_review = root / "wrong-attempt-review.json"
            invalid_review.write_text(json.dumps(review), encoding="utf-8")
            with self.assertRaises(SystemExit) as error, redirect_stderr(io.StringIO()):
                main([
                    "--python-loop", str(python_attempt),
                    "--langgraph", str(graph_attempt),
                    "--output", str(root / "invalid-review.html"),
                    "--python-review", str(invalid_review),
                ])
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

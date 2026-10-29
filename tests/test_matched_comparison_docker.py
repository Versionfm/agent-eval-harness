"""Docker-backed matched coordinator check with a controlled provider transport."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from agent_eval_harness.bench.attempt import DEFAULT_SOURCE_REPOSITORY, DEFAULT_TASK_PACKAGE
from agent_eval_harness.harness.deepseek import HttpResponse
from agent_eval_harness.cli.run_matched_comparison import (
    DEFAULT_PARITY_EVIDENCE,
    run_matched_comparison,
)


DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
SOURCE_REPOSITORY = DEFAULT_SOURCE_REPOSITORY
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class MatchedRepairTransport:
    def __init__(self):
        self.requests = []
        self.smoke_calls = 0
        self.repair = json.loads(
            (REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json")
            .read_text(encoding="utf-8")
        )

    def post_json(self, url, headers, body, timeout_seconds):
        payload = json.loads(body)
        self.requests.append({
            "url": url,
            "headers": dict(headers),
            "body": payload,
            "timeout_seconds": timeout_seconds,
        })
        messages = payload["messages"]
        if "deepseek-smoke-sentinel" in json.dumps(messages):
            self.smoke_calls += 1
            if self.smoke_calls == 1:
                message = {
                    "role": "assistant",
                    "content": "Searching the harmless smoke sentinel.",
                    "reasoning_content": "The preflight asks for one sentinel search.",
                    "tool_calls": [{
                        "id": "smoke-search",
                        "type": "function",
                        "function": {
                            "name": "search_text",
                            "arguments": '{"query":"deepseek-smoke-sentinel"}',
                        },
                    }],
                }
            else:
                message = {"role": "assistant", "content": "SMOKE_OK"}
        elif messages[-1].get("role") == "tool":
            message = {"role": "assistant", "content": "The repair is complete."}
        else:
            message = {
                "role": "assistant",
                "content": "I will apply the known title-evidence repair.",
                "reasoning_content": "This controlled response follows the same public task.",
                "tool_calls": [{
                    "id": f"repair-{len(self.requests)}",
                    "type": "function",
                    "function": {
                        "name": "apply_patch",
                        "arguments": json.dumps({
                            "path": self.repair["path"],
                            "old_text": self.repair["before"],
                            "new_text": self.repair["after"],
                        }),
                    },
                }],
            }
        return HttpResponse(200, json.dumps({
            "model": "DeepSeek-V4.1-Flash",
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 30},
        }))


class FailureAfterSmokeTransport(MatchedRepairTransport):
    def post_json(self, url, headers, body, timeout_seconds):
        payload = json.loads(body)
        if (self.smoke_calls >= 2
                and "deepseek-smoke-sentinel" not in json.dumps(payload["messages"])):
            self.requests.append({
                "url": url,
                "headers": dict(headers),
                "body": payload,
                "timeout_seconds": timeout_seconds,
            })
            return HttpResponse(400, '{"error":{"message":"fixture request rejected"}}')
        return super().post_json(url, headers, body, timeout_seconds)


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for matched Docker run",
)
class MatchedComparisonDockerTests(unittest.TestCase):
    def test_two_fresh_attempts_share_configuration_and_render_comparison(self):
        transport = MatchedRepairTransport()
        with tempfile.TemporaryDirectory(prefix="matched-comparison-") as temporary:
            root = Path(temporary)
            credential = root / "fixture-provider-key.txt"
            credential.write_text("fixture-secret-never-persist", encoding="utf-8")
            artifacts = root / "matched"

            result = run_matched_comparison(
                admission_evidence=Path(ADMISSION_EVIDENCE),
                parity_evidence=DEFAULT_PARITY_EVIDENCE,
                source_repository=SOURCE_REPOSITORY,
                credential_file=credential,
                artifact_directory=artifacts,
                transport=transport,
            )

            python_dir = artifacts / "python-loop"
            graph_dir = artifacts / "langgraph"
            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["valid_measurement"])
            self.assertTrue((python_dir / "candidate.patch").is_file())
            self.assertTrue((graph_dir / "candidate.patch").is_file())
            self.assertTrue((python_dir / "checks.json").is_file())
            self.assertTrue((graph_dir / "checks.json").is_file())
            self.assertTrue((artifacts / "report.html").is_file())
            self.assertEqual(result["agent_attempts"], "both_completed")
            self.assertEqual(result["agent_failures"], {
                "python-loop": False,
                "langgraph": False,
            })
            self.assertEqual(result["configuration_mismatches"], [])
            self.assertEqual(result["execution_mode"], "controlled_transport")
            self.assertFalse(result["live_measurement"])
            self.assertEqual(
                result["live_acceptance_status"],
                "pending_live_provider_run_and_human_review",
            )
            run_plan = json.loads((artifacts / "run-plan.json").read_text())
            self.assertEqual(run_plan["execution_mode"], "controlled_transport")

            python_result = json.loads((python_dir / "result.json").read_text())
            graph_result = json.loads((graph_dir / "result.json").read_text())
            self.assertEqual(python_result["initial_context"], graph_result["initial_context"])
            self.assertEqual(
                python_result["metadata"]["initial_context_sha256"],
                graph_result["metadata"]["initial_context_sha256"],
            )
            self.assertEqual(
                python_result["metadata"]["budgets"],
                graph_result["metadata"]["budgets"],
            )
            self.assertEqual(python_result["functional_verdict"], "success")
            self.assertEqual(graph_result["functional_verdict"], "success")
            self.assertEqual(
                python_result["metadata"]["execution_mode"], "controlled_transport"
            )
            self.assertEqual(
                graph_result["metadata"]["execution_mode"], "controlled_transport"
            )
            self.assertEqual(transport.smoke_calls, 2)
            self.assertEqual(len(transport.requests), 6)
            self.assertLessEqual(result["shared_spend_budget"]["reserved_or_estimated_usd"], 1.00)

            for directory in (artifacts,):
                for path in directory.rglob("*"):
                    if path.is_file():
                        self.assertNotIn(
                            "fixture-secret-never-persist",
                            path.read_text(encoding="utf-8", errors="replace"),
                        )
            comparison = (artifacts / "report.html").read_text(encoding="utf-8")
            self.assertIn("Initial effective context", comparison)
            self.assertIn("Controlled transport fixture", comparison)
            self.assertIn("Qualitative review pending", comparison)

    def test_provider_failure_during_attempt_is_not_an_agent_repair_failure(self):
        transport = FailureAfterSmokeTransport()
        with tempfile.TemporaryDirectory(prefix="matched-provider-error-") as temporary:
            root = Path(temporary)
            credential = root / "fixture-provider-key.txt"
            credential.write_text("fixture-secret-never-persist", encoding="utf-8")
            artifacts = root / "matched"

            result = run_matched_comparison(
                admission_evidence=Path(ADMISSION_EVIDENCE),
                parity_evidence=DEFAULT_PARITY_EVIDENCE,
                source_repository=SOURCE_REPOSITORY,
                credential_file=credential,
                artifact_directory=artifacts,
                transport=transport,
            )

            python_attempt = result["attempts"]["python-loop"]
            self.assertEqual(result["status"], "invalid_measurement")
            self.assertFalse(result["valid_measurement"])
            self.assertEqual(result["agent_failure_assessment"],
                             "not_assessed_due_to_provider_or_environment_failure")
            self.assertEqual(result["agent_attempts"], "partial")
            self.assertEqual(python_attempt["termination_reason"], "provider_error")
            self.assertEqual(python_attempt["recorded_attempt_verdict"], "failure")
            self.assertEqual(python_attempt["agent_repair_assessment"], "not_assessed")
            self.assertEqual(result["attempts"]["langgraph"]["status"], "not_started")
            status_report = (artifacts / "report.html").read_text(encoding="utf-8")
            self.assertIn("not_assessed", status_report)
            self.assertIn("not an agent repair failure", status_report)


if __name__ == "__main__":
    unittest.main()

import json
import os
from pathlib import Path
import tempfile
import unittest

from agent_eval_harness.bench.attempt import (
    AdmittedTask,
    AttemptBudgets,
    ModelConfig,
    attempt_and_evaluate,
)
from agent_eval_harness.harness.deepseek import DeepSeekModelAdapter, HttpResponse, SpendBudget


DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPOSITORY = Path(os.environ.get(
    "ML_TUTOR_REPOSITORY", "/home/francisco/prompt-engineering-group-project"
))


class FixtureTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def post_json(self, url, headers, body, timeout_seconds):
        self.requests.append({
            "url": url,
            "headers": dict(headers),
            "body": json.loads(body),
            "timeout_seconds": timeout_seconds,
        })
        return self.responses.pop(0)


def _tool_response(call_id="repair-1"):
    repair = json.loads(
        (REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json").read_text()
    )
    return HttpResponse(200, json.dumps({
        "model": "DeepSeek-V4.1-Flash",
        "choices": [{"message": {
            "role": "assistant",
            "content": "I found the retrieval defect and will repair it.",
            "reasoning_content": "The ranking code only tokenizes section text.",
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {"name": "apply_patch", "arguments": json.dumps({
                    "path": repair["path"],
                    "old_text": repair["before"],
                    "new_text": repair["after"],
                })},
            }],
        }}],
        "usage": {
            "prompt_tokens": 500,
            "completion_tokens": 70,
            "prompt_cache_hit_tokens": 100,
            "prompt_cache_miss_tokens": 400,
            "completion_tokens_details": {"reasoning_tokens": 40},
        },
    }))


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for Docker attempt",
)
class DeepSeekAttemptDockerTests(unittest.TestCase):
    def setUp(self):
        self.task = AdmittedTask.from_evidence(
            Path(ADMISSION_EVIDENCE), source_repository=SOURCE_REPOSITORY
        )

    def _run(self, transport, artifact_directory, *, spend_budget_usd=0.30):
        model = DeepSeekModelAdapter(
            api_key="fixture-secret-must-not-appear",
            transport=transport,
            spend_budget=SpendBudget(spend_budget_usd),
        )
        return model, attempt_and_evaluate(
            admitted_task=self.task,
            model=model,
            model_config=ModelConfig(
                provider="deepseek",
                requested_model="deepseek-flash",
                settings={
                    "thinking": "enabled",
                    "reasoning_effort": "low",
                    "max_output_tokens": 1024,
                },
            ),
            budgets=AttemptBudgets(
                max_model_calls=6,
                max_provider_retries=1,
                attempt_deadline_seconds=300,
                cleanup_timeout_seconds=5,
            ),
            artifact_directory=artifact_directory,
        )

    def test_retry_continuation_usage_and_missing_usage_are_recorded_in_attempt_artifacts(self):
        transport = FixtureTransport([
            HttpResponse(503, "temporary service issue"),
            _tool_response(),
            HttpResponse(200, json.dumps({
                "model": "DeepSeek-V4.1-Flash",
                "choices": [{"message": {"role": "assistant", "content": "Repair complete."}}],
            })),
        ])

        with tempfile.TemporaryDirectory(prefix="deepseek-attempt-") as temporary:
            artifacts = Path(temporary) / "attempt"
            _, result = self._run(transport, artifacts)
            self.assertTrue((artifacts / "metadata.json").is_file())
            self.assertTrue((artifacts / "trace.jsonl").is_file())
            saved = (artifacts / "result.json").read_text(encoding="utf-8")
            self.assertNotIn("fixture-secret-must-not-appear", saved)

        self.assertEqual(result["termination_reason"], "agent_completed")
        self.assertEqual(result["functional_verdict"], "success")
        self.assertEqual(result["metadata"]["model_call_count"], 3)
        self.assertEqual(result["metadata"]["retry_count"], 1)
        self.assertEqual(result["candidate"]["changed_files"], ["app/source.py"])
        self.assertEqual(transport.requests[2]["body"]["messages"][-2]["reasoning_content"],
                         "The ranking code only tokenizes section text.")
        self.assertEqual(transport.requests[2]["body"]["messages"][-1]["role"], "tool")
        self.assertEqual(transport.requests[2]["timeout_seconds"] > 0, True)
        self.assertTrue(any(event.get("retrying") for event in result["trace"]))
        self.assertEqual(result["metadata"]["cost"]["reported"]["status"], "unavailable")
        self.assertEqual(result["metadata"]["cost"]["estimated"]["status"], "partial")
        self.assertGreater(result["metadata"]["spend_budget"]["reserved_or_estimated_usd"], 0)
        self.assertEqual(result["metadata"]["usage_by_call"][0]["reasoning_tokens"], 40)

    def test_invalid_provider_request_keeps_a_previously_collected_repair(self):
        transport = FixtureTransport([
            _tool_response(call_id="repair-before-invalid-request"),
            HttpResponse(400, '{"error":{"message":"bad request"}}'),
        ])

        with tempfile.TemporaryDirectory(prefix="deepseek-invalid-request-") as temporary:
            _, result = self._run(transport, Path(temporary) / "attempt")

        self.assertEqual(result["termination_reason"], "provider_error")
        self.assertEqual(result["functional_verdict"], "success")
        self.assertEqual(result["candidate"]["changed_files"], ["app/source.py"])
        failed = [event for event in result["trace"] if event.get("type") == "model"][-1]
        self.assertEqual(failed["status"], "error")
        self.assertFalse(failed["retrying"])
        self.assertEqual(failed["error_category"], "provider_error")

    def test_attempt_stops_before_transport_when_reservation_cannot_fit(self):
        transport = FixtureTransport([HttpResponse(200, "{}")])

        with tempfile.TemporaryDirectory(prefix="deepseek-budget-stop-") as temporary:
            _, result = self._run(
                transport,
                Path(temporary) / "attempt",
                spend_budget_usd=0.000001,
            )

        self.assertEqual(result["termination_reason"], "spending_budget")
        self.assertEqual(result["functional_verdict"], "failure")
        self.assertEqual(transport.requests, [])
        stopped = [event for event in result["trace"] if event.get("type") == "model"][-1]
        self.assertEqual(stopped["status"], "budget_stopped")
        self.assertEqual(stopped["error_category"], "spending_budget")

    def test_output_limited_response_is_not_recorded_as_agent_completion(self):
        transport = FixtureTransport([HttpResponse(200, json.dumps({
            "model": "DeepSeek-V4.1-Flash",
            "choices": [{
                "finish_reason": "length",
                "message": {
                    "role": "assistant",
                    "content": "The repair requires a further inspection",
                },
            }],
            "usage": {"prompt_tokens": 400, "completion_tokens": 1024},
        }))])

        with tempfile.TemporaryDirectory(prefix="deepseek-output-limit-") as temporary:
            _, result = self._run(transport, Path(temporary) / "attempt")

        self.assertEqual(result["termination_reason"], "provider_output_limit")
        self.assertEqual(result["metadata"]["usage_by_call"][0]["provider_finish_reason"], "length")
        self.assertEqual(result["metadata"]["observed_models"], ["DeepSeek-V4.1-Flash"])
        response_event = [event for event in result["trace"] if event.get("type") == "model"][-1]
        self.assertEqual(response_event["response"]["usage"]["provider_finish_reason"], "length")
        self.assertNotIn("finish_reason", response_event["response"]["reasoning_fields"])


if __name__ == "__main__":
    unittest.main()

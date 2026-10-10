"""Docker acceptance for the observed matched pair, through the existing coordinator.

Every attempt runs real Docker tasks. The provider is a controlled transport, so no paid request is made.
Scripted parity evidence is regenerated for the current harness revision in a temporary directory, so a
stale committed comparison cannot hide or cause a failure here.
"""

import json
import os
import tempfile
import unittest
import urllib.request
from pathlib import Path

from agent_eval_harness.cli import run_matched_comparison as coordinator
from agent_eval_harness.reports.compare_report import _load_attempt
from agent_eval_harness.harness.deepseek import HttpResponse
from agent_eval_harness.cli.run_langgraph_parity import main as parity_main
from live_tracker import run_matched as pair
from live_tracker.projection import final_results
from live_tracker.reader import read_attempt_history
from live_tracker.recorder import FaultyStorage
from live_tracker.server import make_server


DOCKER_INTEGRATION = os.environ.get("AGENT_EVAL_DOCKER_INTEGRATION") == "1"
ADMISSION_EVIDENCE = os.environ.get("ML_TUTOR_ADMISSION_EVIDENCE")
SOURCE_REPOSITORY = Path(os.environ.get(
    "ML_TUTOR_REPOSITORY", "/home/francisco/prompt-engineering-group-project"
))
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATORS = ("python-loop", "langgraph")
CREDENTIAL_TEXT = "fixture-secret-never-persist"
# The repair pair makes two provider calls per attempt (apply_patch, then completion); the smoke makes two.
# An interruption at the second repair call stops the first attempt; at the fourth, the second.
INTERRUPT_AT = {"python-loop": 2, "langgraph": 4}


def _response(message):
    return HttpResponse(200, json.dumps({
        "model": "DeepSeek-V4.1-Flash",
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": 200, "completion_tokens": 30},
    }))


class PairTransport:
    """Controlled provider: a smoke tool call and continuation, then one known repair per attempt."""

    def __init__(self, interrupt_at=None):
        self.interrupt_at = interrupt_at
        self.requests = []
        self.repair_calls = 0
        self.smoke_calls = 0
        self.repair = json.loads(
            (REPOSITORY_ROOT / "tasks/ml_tutor_retrieval/curator/repair.json").read_text(encoding="utf-8")
        )

    def post_json(self, url, headers, body, timeout_seconds):
        payload = json.loads(body)
        messages = payload["messages"]
        self.requests.append(payload)
        if "deepseek-smoke-sentinel" in json.dumps(messages):
            self.smoke_calls += 1
            if self.smoke_calls == 1:
                return _response({
                    "role": "assistant",
                    "content": "Searching the harmless smoke sentinel.",
                    "reasoning_content": "The preflight asks for one sentinel search.",
                    "tool_calls": [{"id": "smoke-search", "type": "function", "function": {
                        "name": "search_text", "arguments": '{"query":"deepseek-smoke-sentinel"}'}}],
                })
            return _response({"role": "assistant", "content": "SMOKE_OK"})
        self.repair_calls += 1
        if self.interrupt_at == self.repair_calls:
            raise KeyboardInterrupt("controlled interruption of a provider call")
        if messages[-1].get("role") == "tool":
            return _response({"role": "assistant", "content": "The repair is complete."})
        return _response({
            "role": "assistant",
            "content": "I will apply the known title-evidence repair.",
            "reasoning_content": "This controlled response follows the same public task.",
            "tool_calls": [{"id": f"repair-{self.repair_calls}", "type": "function", "function": {
                "name": "apply_patch",
                "arguments": json.dumps({"path": self.repair["path"], "old_text": self.repair["before"],
                                         "new_text": self.repair["after"]}),
            }}],
        })


def _fresh_parity(root):
    """Scripted parity for the current harness revision: three scenarios, no provider call."""
    code = parity_main(["--admission-evidence", ADMISSION_EVIDENCE,
                        "--source-repository", str(SOURCE_REPOSITORY),
                        "--output-dir", str(root / "parity")])
    if code != 0:
        raise AssertionError("scripted parity prerequisite did not pass")
    return root / "parity" / "comparison.json"


def _run_pair(root, *, transport, parity, storage_for=None, observed=True):
    """One matched pair through the coordinator; observed pairs add one recorder per attempt."""
    root.mkdir(parents=True, exist_ok=True)
    credential = root / "provider-key.txt"
    credential.write_text(CREDENTIAL_TEXT, encoding="utf-8")
    common = dict(admission_evidence=Path(ADMISSION_EVIDENCE), parity_evidence=parity,
                  source_repository=SOURCE_REPOSITORY, credential_file=credential,
                  transport=transport)
    if not observed:
        experiment = coordinator.run_matched_comparison(artifact_directory=root / "artifacts", **common)
        return experiment, root / "artifacts"
    ids = {name: f"{name}-{root.name}" for name in ORCHESTRATORS}
    manifest = pair.run_live_pair(
        credential_file=credential, artifact_directory=root / "artifacts", attempt_ids=ids,
        admission_evidence=Path(ADMISSION_EVIDENCE), parity_evidence=parity,
        source_repository=SOURCE_REPOSITORY, transport=transport, storage_for=storage_for,
    )
    return manifest, root / "artifacts"


def _events(directory):
    return read_attempt_history(directory).events


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for the observed pair",
)
class ObservedPairDockerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory(prefix="live-pair-docker-")
        root = Path(cls._temporary.name)
        parity = _fresh_parity(root / "shared")
        cls.observed_transport = PairTransport()
        cls.manifest, cls.artifacts = _run_pair(
            root / "observed", transport=cls.observed_transport, parity=parity)
        cls.unobserved_transport = PairTransport()
        cls.unobserved, cls.unobserved_artifacts = _run_pair(
            root / "unobserved", transport=cls.unobserved_transport, parity=parity, observed=False,
        )

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def test_observed_pair_records_projects_and_reports_both_attempts(self):
        manifest = self.manifest
        self.assertTrue(manifest["valid_measurement"], manifest["status"])
        self.assertEqual(manifest["execution_mode"], "controlled_transport")
        self.assertFalse(manifest["live_measurement"])
        for name in ORCHESTRATORS:
            directory = self.artifacts / name
            history = read_attempt_history(directory)
            self.assertEqual(history.state, "complete")
            self.assertEqual(history.events[0]["attempt_id"], manifest["attempts"][name]["attempt_id"])
            self.assertEqual(history.events[-1]["type"], "attempt_finished")
            self.assertEqual(manifest["attempts"][name]["recording"]["state"], "complete")
            self.assertEqual(manifest["attempts"][name]["termination_reason"], "agent_completed")
            for artifact in ("result.json", "trace.jsonl", "report.html", "candidate.patch", "checks.json"):
                self.assertTrue((directory / artifact).is_file(), f"{name} {artifact}")
            projected = final_results(directory)
            self.assertEqual(projected["functional_verdict"], "success")
            attempt = _load_attempt(directory)
            self.assertEqual(attempt["candidate"]["status"], "collected")
            self.assertEqual(attempt["evaluation"]["checks"], projected["checks"])

        report = (self.artifacts / "report.html").read_text(encoding="utf-8")
        self.assertIn("Initial effective context", report)
        self.assertIn("Controlled transport fixture", report)
        self.assertIn("Qualitative review pending", report)

    def test_the_manifest_retains_budgets_pricing_usage_overhead_and_pending_reviews(self):
        manifest = self.manifest
        self.assertEqual(manifest["budgets_usd"], {
            "combined_ceiling": 0.10, "smoke": 0.01, "per_attempt": 0.04, "stage_sum": 0.09,
        })
        self.assertEqual(manifest["pricing"]["source_checked_at"], "2026-10-10")
        self.assertEqual(manifest["pricing"]["rates_usd_per_million_tokens"]["peak"]["output"], 1.20)
        for name in ORCHESTRATORS:
            entry = manifest["attempts"][name]
            self.assertEqual(entry["qualitative_review"]["status"], "pending")
            self.assertEqual(entry["usage"]["reported_cost_usd"], "unavailable")
            self.assertIsInstance(entry["usage"]["estimated_cost_usd"], float)
            self.assertGreater(entry["usage"]["calls"], 0)
            self.assertEqual(entry["overhead"]["observer_events"], len(_events(self.artifacts / name)))
            self.assertGreaterEqual(entry["overhead"]["observer_seconds"], 0.0)
            self.assertFalse(entry["deadline"]["deadline_stop"])
            self.assertLess(entry["deadline"]["used_fraction"], 1.0)
        self.assertTrue((self.artifacts / pair.MANIFEST_NAME).is_file())

    def test_the_recorded_attempts_are_served_to_the_workbench(self):
        names = {attempt_id: self.artifacts / name for name, attempt_id in (
            (name, self.manifest["attempts"][name]["attempt_id"]) for name in ORCHESTRATORS)}
        server = make_server(names)
        try:
            import threading
            threading.Thread(target=server.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{server.server_address[1]}/api/attempts"
            with urllib.request.urlopen(url, timeout=10) as response:
                listed = {item["attempt_id"] for item in json.loads(response.read())}
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(listed, set(names))

    def test_observation_leaves_model_visible_messages_candidates_and_verdicts_unchanged(self):
        self.assertEqual(
            [request["messages"] for request in self.observed_transport.requests],
            [request["messages"] for request in self.unobserved_transport.requests],
        )
        for name in ORCHESTRATORS:
            observed = self.artifacts / name
            unobserved = self.unobserved_artifacts / name
            self.assertEqual((observed / "candidate.patch").read_bytes(),
                             (unobserved / "candidate.patch").read_bytes())
            self.assertEqual(json.loads((observed / "checks.json").read_text()),
                             json.loads((unobserved / "checks.json").read_text()))
            observed_result = json.loads((observed / "result.json").read_text())
            unobserved_result = json.loads((unobserved / "result.json").read_text())
            self.assertEqual(
                [event["model_visible_result"] for event in observed_result["trace"] if event["type"] == "tool"],
                [event["model_visible_result"] for event in unobserved_result["trace"] if event["type"] == "tool"],
            )
            self.assertEqual(observed_result["functional_verdict"], unobserved_result["functional_verdict"])
            self.assertEqual(self.manifest["attempts"][name]["recorded_attempt_verdict"],
                             self.unobserved["attempts"][name]["recorded_attempt_verdict"])
        self.assertTrue(self.unobserved["valid_measurement"])

    def test_no_credential_is_persisted_in_any_saved_file(self):
        for path in self.artifacts.rglob("*"):
            if path.is_file():
                self.assertNotIn(CREDENTIAL_TEXT, path.read_text(encoding="utf-8", errors="replace"))


@unittest.skipUnless(
    DOCKER_INTEGRATION and ADMISSION_EVIDENCE,
    "set AGENT_EVAL_DOCKER_INTEGRATION=1 and ML_TUTOR_ADMISSION_EVIDENCE for the observed pair",
)
class ObservedPairFailureDockerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory(prefix="live-pair-failure-")
        cls.parity = _fresh_parity(Path(cls._temporary.name) / "shared")

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def test_a_recording_failure_stops_that_attempt_for_each_orchestrator(self):
        for target in ORCHESTRATORS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="live-pair-fault-") as temporary:
                root = Path(temporary)
                storage_for = (lambda name, target=target: FaultyStorage("log", "tool.outcome")
                               if name == target else None)
                manifest, artifacts = _run_pair(root, transport=PairTransport(), parity=self.parity,
                                                storage_for=storage_for)
                entry = manifest["attempts"][target]
                self.assertFalse(manifest["valid_measurement"])
                self.assertEqual(entry["recording"]["state"], "failed")
                self.assertTrue((artifacts / target / "recording-failure.json").is_file())
                self.assertEqual(entry["termination_reason"], "harness_error")
                history = read_attempt_history(artifacts / target)
                # The failed tool outcome leaves its tool start unresolved; a graph node around it is also open.
                self.assertIn("tool-1-1", history.unresolved_operations)
                if target == "python-loop":
                    self.assertEqual(history.unresolved_operations, ["tool-1-1"])
                # The failed record is the last one, so no later record (including attempt_finished) exists.
                self.assertNotIn("attempt_finished", [event["type"] for event in history.events])
                # Candidate collection still runs after the stop, and it stays a separate fact.
                self.assertTrue((artifacts / target / "result.json").is_file())
                if target == "langgraph":
                    self.assertEqual(manifest["attempts"]["python-loop"]["status"], "completed")
                else:
                    self.assertEqual(manifest["attempts"]["langgraph"]["status"], "not_started")

    def test_an_interrupted_provider_call_is_recorded_for_each_orchestrator(self):
        for target in ORCHESTRATORS:
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="live-pair-interrupt-") as temporary:
                root = Path(temporary)
                transport = PairTransport(interrupt_at=INTERRUPT_AT[target])
                manifest, artifacts = _run_pair(root, transport=transport, parity=self.parity)
                entry = manifest["attempts"][target]
                self.assertFalse(manifest["valid_measurement"])
                self.assertEqual(entry["termination_reason"], "interrupted")
                self.assertEqual(entry["invalid_reason"], "attempt_terminated_interrupted")
                statuses = [event["data"].get("status") for event in _events(artifacts / target)]
                self.assertIn("interrupted", statuses)
                self.assertEqual(final_results(artifacts / target)["termination_reason"], "interrupted")
                self.assertEqual(read_attempt_history(artifacts / target).state, "complete")
                if target == "langgraph":
                    self.assertEqual(manifest["attempts"]["python-loop"]["status"], "completed")
                else:
                    self.assertEqual(manifest["attempts"]["langgraph"]["status"], "not_started")


if __name__ == "__main__":
    unittest.main()

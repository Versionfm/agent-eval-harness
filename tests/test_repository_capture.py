"""Offline seams for observed repository capture (#16): RepositoryCapture.observe on a real directory.

The container boundary is the only fake: settlement that needs `docker exec` is driven through
the module's `_run` with canned process results. Expected values are literals, not recomputed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_eval_harness import capture as capture_module
from agent_eval_harness.capture import CaptureLimits, RepositoryCapture
from agent_eval_harness.environment import CommandTimeout


class FakeContainer:
    """Only container_id is read by the capture; None means the container was force-removed."""

    def __init__(self, container_id: str | None = None):
        self.container_id = container_id


def _baseline(root: Path) -> dict[str, tuple[bytes, int]]:
    from agent_eval_harness.evaluation import _snapshot_repository
    return _snapshot_repository(root)


class CaptureDescriptionTests(unittest.TestCase):
    """Slice 1: text additions, modifications, deletions, binary metadata and previews."""

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="capture-test-")
        self.root = Path(self._temporary.name) / "repo"
        self.root.mkdir()
        (self.root / "keep.txt").write_text("a\nb\nc\n", encoding="utf-8")
        (self.root / "gone.txt").write_text("old\n", encoding="utf-8")
        (self.root / "blob.bin").write_bytes(b"\xff\xfe\x00\x01")
        self.baseline = _baseline(self.root)

    def tearDown(self):
        self._temporary.cleanup()

    def _capture(self, limits: CaptureLimits | None = None):
        # container_id None: the timed-out-and-removed boundary, so no docker call is needed here.
        return RepositoryCapture(FakeContainer(None), self.root, self.baseline, limits)

    def test_text_and_binary_changes_have_counts_and_metadata_only_for_binary(self):
        (self.root / "keep.txt").write_text("a\nB\nc\nd\n", encoding="utf-8")
        (self.root / "gone.txt").unlink()
        (self.root / "added.txt").write_text("new\n", encoding="utf-8")
        (self.root / "blob.bin").write_bytes(b"\x00\xfe")

        data, artifacts = self._capture().observe("run_shell")

        self.assertEqual(data["status"], "captured")
        self.assertEqual(data["settlement"]["method"], "container_removed")
        by_path = {entry["path"]: entry for entry in data["changes"]}
        self.assertEqual(sorted(by_path), ["added.txt", "blob.bin", "gone.txt", "keep.txt"])
        self.assertEqual((by_path["keep.txt"]["action"], by_path["keep.txt"]["kind"]), ("modify", "text"))
        self.assertEqual((by_path["keep.txt"]["additions"], by_path["keep.txt"]["deletions"]), (2, 1))
        self.assertEqual((by_path["added.txt"]["action"], by_path["added.txt"]["additions"]), ("add", 1))
        self.assertEqual((by_path["gone.txt"]["action"], by_path["gone.txt"]["deletions"]), ("delete", 1))
        blob = by_path["blob.bin"]
        self.assertEqual((blob["kind"], blob["preview"], blob["additions"]), ("binary", None, None))
        self.assertEqual(blob["before"]["bytes"], 4)
        self.assertEqual(blob["after"]["sha256"], hashlib.sha256(b"\x00\xfe").hexdigest())
        self.assertEqual(data["totals"], {"files": 4, "additions": 3, "deletions": 2, "binary_files": 1})
        # The full diff is in the linked artifact, and binary content is never embedded.
        self.assertIn("capture.json", artifacts)
        self.assertNotIn(base64.b64encode(b"\x00\xfe"), artifacts["capture.json"])
        self.assertIn(b"+B", artifacts["capture.json"])
        self.assertGreater(data["capture_seconds"], 0)

    def test_linked_artifact_carries_the_same_per_file_facts_as_the_event(self):
        (self.root / "keep.txt").write_text("a\nB\nc\nd\n", encoding="utf-8")
        (self.root / "blob.bin").write_bytes(b"\x00\xfe")

        data, artifacts = self._capture().observe("apply_patch")

        full = {entry["path"]: entry for entry in json.loads(artifacts["capture.json"])["changes"]}
        self.assertEqual(full["keep.txt"]["kind"], "text")
        self.assertEqual((full["keep.txt"]["additions"], full["keep.txt"]["deletions"]), (2, 1))
        self.assertIn("+d\n", full["keep.txt"]["diff"])
        self.assertEqual(full["blob.bin"]["kind"], "binary")
        self.assertNotIn("diff", full["blob.bin"])

    def test_preview_is_bounded_per_file_and_labelled_when_truncated(self):
        (self.root / "keep.txt").write_text("a\n" + "x" * 500 + "\n", encoding="utf-8")

        data, _ = self._capture(CaptureLimits(max_preview_bytes=64)).observe("apply_patch")

        entry = data["changes"][0]
        self.assertEqual(entry["path"], "keep.txt")
        self.assertTrue(entry["preview_truncated"])
        self.assertLessEqual(len(entry["preview"].encode("utf-8")), 64)


class CaptureSettlementTests(unittest.TestCase):
    """Slice 2: settlement rules; only run_shell with a live container needs the probe."""

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="capture-settle-")
        self.root = Path(self._temporary.name) / "repo"
        self.root.mkdir()
        (self.root / "a.txt").write_text("a\n", encoding="utf-8")
        self.baseline = _baseline(self.root)

    def tearDown(self):
        self._temporary.cleanup()

    def test_apply_patch_return_is_settled_without_a_probe(self):
        with mock.patch.object(capture_module, "_run", side_effect=AssertionError("no probe")):
            data, _ = RepositoryCapture(FakeContainer("cid"), self.root, self.baseline).observe("apply_patch")
        self.assertEqual(data["settlement"]["method"], "apply_patch_returned")
        self.assertEqual(data["status"], "captured")

    def test_shell_return_with_live_background_writer_is_unsettled_and_shows_no_diff(self):
        (self.root / "late.txt").write_text("x\n", encoding="utf-8")
        probe_output = (
            '{"complete": true, "live": [{"command": "sleep 2", "pid": 42, "state": "S"}]}'
        )
        fake = subprocess.CompletedProcess([], 0, stdout=probe_output, stderr="")
        with mock.patch.object(capture_module, "_run", return_value=fake):
            data, artifacts = RepositoryCapture(FakeContainer("cid"), self.root, self.baseline).observe("run_shell")
        self.assertEqual(data["status"], "unsettled")
        self.assertEqual(data["settlement"]["live_processes"][0]["command"], "sleep 2")
        self.assertNotIn("changes", data)
        self.assertEqual(artifacts, {})

    def test_probe_that_does_not_finish_is_a_declared_time_limit_omission(self):
        with mock.patch.object(capture_module, "_run", side_effect=CommandTimeout("slow", timeout_seconds=1)):
            data, _ = RepositoryCapture(FakeContainer("cid"), self.root, self.baseline).observe("run_shell")
        self.assertEqual((data["status"], data["reason"]), ("omitted", "time_limit"))

    def test_probe_failure_is_unavailable_not_settled(self):
        fake = subprocess.CompletedProcess([], 1, stdout="", stderr="no python")
        with mock.patch.object(capture_module, "_run", return_value=fake):
            data, _ = RepositoryCapture(FakeContainer("cid"), self.root, self.baseline).observe("run_shell")
        self.assertEqual(data["status"], "unavailable")
        self.assertIn("no python", data["reason"])


class CaptureLimitTests(unittest.TestCase):
    """Slice 3: byte limit is a declared omission; a symbolic link is a capture error, not an omission."""

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="capture-limit-")
        self.root = Path(self._temporary.name) / "repo"
        self.root.mkdir()
        (self.root / "big.txt").write_bytes(b"0123456789" * 10)
        self.baseline = _baseline(self.root)

    def tearDown(self):
        self._temporary.cleanup()

    def test_total_bytes_over_limit_is_omitted_with_reason(self):
        (self.root / "big.txt").write_bytes(b"1" * 200)
        data, artifacts = RepositoryCapture(
            FakeContainer(None), self.root, self.baseline, CaptureLimits(max_total_bytes=100)
        ).observe("run_shell")
        self.assertEqual((data["status"], data["reason"]), ("omitted", "byte_limit"))
        self.assertNotIn("changes", data)
        self.assertEqual(artifacts, {})

    def test_symbolic_link_is_a_capture_error_with_its_own_status(self):
        (self.root / "link").symlink_to(self.root / "big.txt")
        data, _ = RepositoryCapture(FakeContainer(None), self.root, self.baseline).observe("run_shell")
        self.assertEqual(data["status"], "error")
        self.assertIn("symbolic link", data["reason"])

    def test_summary_counts_each_status_and_records_the_limits(self):
        capture = RepositoryCapture(FakeContainer(None), self.root, self.baseline, CaptureLimits(max_total_bytes=100))
        capture.observe("run_shell")
        summary = capture.summary()
        self.assertEqual(summary["status_counts"], {"captured": 1})
        self.assertEqual(summary["captures"], 1)
        self.assertEqual(summary["limits"]["max_total_bytes"], 100)


if __name__ == "__main__":
    unittest.main()

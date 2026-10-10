"""The per-connection tail reader agrees with a full read at every byte boundary (review fix, #10).

Each poll reads only bytes appended since the previous one, yet its verified prefix, torn tail,
problems, unresolved operations and failure must equal a from-scratch read of the same bytes.
"""

import os
import random
import shutil
import tempfile
import unittest
from pathlib import Path

from attempt_fixtures import record_attempt
from live_tracker.reader import AttemptReader, read_attempt_history


FIELDS = ("state", "events", "problems", "torn_tail_bytes", "unresolved_operations", "failure")


def _same(left, right) -> bool:
    return all(getattr(left, field) == getattr(right, field) for field in FIELDS)


class IncrementalReaderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="live-incremental-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        record_attempt(self.source)
        self.log_bytes = (self.source / "events.jsonl").read_bytes()
        self.target = self.root / "target"
        self.target.mkdir()
        shutil.copytree(self.source / "artifacts", self.target / "artifacts")

    def test_a_growing_log_matches_a_full_read_at_every_sampled_byte_boundary(self):
        rng = random.Random(10)
        cuts = sorted({0, len(self.log_bytes), *rng.sample(range(1, len(self.log_bytes)), 300)})
        reader = AttemptReader(self.target)
        for cut in cuts:
            (self.target / "events.jsonl").write_bytes(self.log_bytes[:cut])
            with self.subTest(bytes_written=cut):
                self.assertTrue(_same(reader.poll(), read_attempt_history(self.target)))
        final = reader.poll()
        self.assertEqual(final.state, "complete")
        self.assertEqual(final.torn_tail_bytes, 0)

    def test_a_log_replaced_or_truncated_under_the_reader_is_read_again_from_the_start(self):
        (self.target / "events.jsonl").write_bytes(self.log_bytes)
        reader = AttemptReader(self.target)
        self.assertEqual(reader.poll().state, "complete")

        shorter = b"\n".join(self.log_bytes.split(b"\n")[:3]) + b"\n"
        (self.target / "events.jsonl").write_bytes(shorter)
        self.assertTrue(_same(reader.poll(), read_attempt_history(self.target)))

        replacement = self.target / "replacement.tmp"
        replacement.write_bytes(self.log_bytes)
        os.replace(replacement, self.target / "events.jsonl")
        self.assertTrue(_same(reader.poll(), read_attempt_history(self.target)))

    def test_a_damaged_record_ends_the_prefix_and_later_polls_still_agree_with_a_full_read(self):
        lines = self.log_bytes.split(b"\n")
        damaged = b"\n".join(lines[:4] + [b"not json"] + lines[5:])
        (self.target / "events.jsonl").write_bytes(damaged)
        reader = AttemptReader(self.target)
        first = reader.poll()
        self.assertEqual(first.state, "corrupt")
        self.assertEqual(first.problems[0]["sequence"], 5)
        (self.target / "events.jsonl").write_bytes(damaged + b"\n" + lines[-1] + b"\n")
        self.assertTrue(_same(reader.poll(), read_attempt_history(self.target)))


if __name__ == "__main__":
    unittest.main()

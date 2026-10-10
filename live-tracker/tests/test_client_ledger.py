"""The compiled browser ledger: duplicates are silent, gaps and conflicts are explicit.

Runs the committed web/dist/connection.js under Node with literal expected results.
"""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


CONNECTION = (Path(__file__).resolve().parents[1] / "web" / "dist" / "connection.js").as_uri()
SCENARIO = """
import { Ledger } from %s;
const base = (sequence, extra = {}) => ({
  schema: "agent-eval-harness/attempt-events", schema_version: 1, attempt_id: "att",
  sequence, type: "model.start", data: { model_call: sequence }, artifacts: [], ...extra,
});
const ledger = new Ledger("att");
const results = [];
const accept = (event) => results.push(ledger.accept(event));
accept(base(1));
accept(base(1));                                   // redelivered after a reconnect
accept(base(3));                                   // sequence 2 never arrived
accept(base(3, { data: { model_call: 99 } }));     // same sequence, different bytes
accept(base(4, { attempt_id: "other" }));          // another attempt's event
accept(base(4, { schema_version: 2 }));            // unknown schema
accept(base(4));
console.log(JSON.stringify({ results, displayed: ledger.displayed }));
"""


@unittest.skipUnless(shutil.which("node"), "Node is needed to run the compiled browser ledger")
class ClientLedgerTests(unittest.TestCase):
    def test_duplicates_are_silent_and_gaps_or_conflicts_are_explicit(self):
        output = subprocess.run(
            ["node", "--input-type=module", "-e", SCENARIO % json.dumps(CONNECTION)],
            check=True, capture_output=True, text=True, timeout=60,
        ).stdout
        report = json.loads(output)
        self.assertEqual(report["results"], [
            {"kind": "new"},
            {"kind": "duplicate"},
            {"kind": "new", "gap": [2, 2]},
            {"kind": "conflict", "message": "sequence 3 conflicts with what was displayed"},
            {"kind": "conflict", "message": "event 4 belongs to another attempt"},
            {"kind": "conflict", "message": "event 4 has an unsupported schema"},
            {"kind": "new"},
        ])
        self.assertEqual(report["displayed"], 4)


if __name__ == "__main__":
    unittest.main()

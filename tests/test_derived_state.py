"""PR5: derived application_state matches the ledger fixture for every case; stored derived states are refused."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pf_lib import assessment, ledger  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "ledgers"


class DerivedStateTests(unittest.TestCase):
    def test_every_fixture_case_derives_as_expected(self):
        exports = ledger.read_ledger(FIXTURES / "exports.jsonl")
        outcomes = ledger.read_ledger(FIXTURES / "outcomes.jsonl")
        derived = ledger.derive_states(exports, outcomes)
        cases = json.loads((FIXTURES / "derived-cases.json").read_text(encoding="utf-8"))
        for item_id, expected in cases.items():
            actual = derived.get(item_id, {}).get("application_state")
            self.assertEqual(actual, expected, item_id)

    def test_pending_or_declined_exports_keep_the_stored_state(self):
        exports = ledger.read_ledger(FIXTURES / "exports.jsonl")
        derived = ledger.derive_states(exports, [])
        self.assertIsNone(derived["PF-0002"]["application_state"])
        self.assertEqual(len(derived["PF-0002"]["exports"]), 1)
        self.assertIsNone(derived["PF-0003"]["application_state"])

    def test_stored_exported_or_measured_is_a_validation_error(self):
        base = json.loads((ROOT / "tests" / "fixtures" / "assessments" / "valid-test.json").read_text(encoding="utf-8"))
        for state in ("exported", "measured"):
            doc = dict(base, application_state=state)
            errors = assessment.validate_document(doc, {"item_id": "PF-0001", "provenance_status": "verified"}, None)
            self.assertTrue(any("derive from ledgers" in e for e in errors), state)


if __name__ == "__main__":
    unittest.main()

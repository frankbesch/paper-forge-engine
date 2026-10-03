"""PR4: every assessment fixture passes or fails exactly as its filename prefix says."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pf_lib import assessment  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "assessments"
PORTFOLIO = json.loads((ROOT / "config" / "portfolio.json").read_text(encoding="utf-8"))


def load(name: str) -> tuple[dict, dict]:
    doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    metadata = {"item_id": "PF-0001", "provenance_status": doc.pop("_metadata_provenance", "verified")}
    return doc, metadata


class AssessmentFixtureTests(unittest.TestCase):
    def test_fixture_directory_covers_all_three_prefixes(self):
        names = sorted(p.name for p in FIXTURES.glob("*.json"))
        self.assertTrue(any(n.startswith("valid-") for n in names))
        self.assertTrue(any(n.startswith("invalid-") for n in names))
        self.assertTrue(any(n.startswith("gated-") for n in names))
        self.assertGreaterEqual(len(names), 15)

    def test_valid_fixtures_pass(self):
        for path in sorted(FIXTURES.glob("valid-*.json")):
            doc, metadata = load(path.name)
            errors = assessment.validate_document(doc, metadata, PORTFOLIO, path.name)
            self.assertEqual(errors, [], path.name)

    def test_invalid_fixtures_fail(self):
        for path in sorted(FIXTURES.glob("invalid-*.json")):
            doc, metadata = load(path.name)
            errors = assessment.validate_document(doc, metadata, PORTFOLIO, path.name)
            self.assertTrue(errors, f"{path.name} should fail")

    def test_gated_fixtures_fail_validation_with_a_safety_message(self):
        expectations = {
            "gated-health-apply.json": "evidence_quality >= 3",
            "gated-security-validated.json": "threat_review",
            "gated-provenance-failed.json": "failed provenance blocks Apply",
        }
        for name, needle in expectations.items():
            doc, metadata = load(name)
            errors = assessment.validate_document(doc, metadata, PORTFOLIO, name)
            self.assertTrue(any(needle in e for e in errors), (name, errors))

    def test_invalid_fixtures_name_their_rule(self):
        expectations = {
            "invalid-score-range.json": "integer 0-4",
            "invalid-missing-rationale.json": "requires a rationale",
            "invalid-derived-state.json": "derive from ledgers",
            "invalid-endeavor-key.json": "not a configured endeavor",
            "invalid-stored-priority.json": "stored score is not allowed",
            "invalid-stored-freshness-status.json": "computed at build time",
            "invalid-disposition-without-rationale.json": "disposition requires a rationale",
            "invalid-revision-history-mismatch.json": "revision - 1 entries",
            "invalid-apply-without-required-scores.json": "Apply requires evidence_quality",
        }
        for name, needle in expectations.items():
            doc, metadata = load(name)
            errors = assessment.validate_document(doc, metadata, PORTFOLIO, name)
            self.assertTrue(any(needle in e for e in errors), (name, errors))

    def test_empty_draft_is_null_scored_and_carries_active_endeavors(self):
        draft = assessment.empty_assessment("PF-0001", "Alex", "2026-09-04", ["notes", "projects"])
        self.assertEqual(draft["revision"], 1)
        self.assertIsNone(draft["disposition"]["value"])
        self.assertTrue(all(v["score"] is None for v in draft["general"].values()))
        self.assertEqual(set(draft["endeavors"]), {"notes", "projects"})
        self.assertEqual(assessment._find_forbidden(draft), [])

    def test_revise_increments_and_moves_previous_into_history(self):
        doc, _ = load("valid-test.json")
        updated = assessment.merge_draft(doc, {"disposition": {"value": "Apply", "rationale": "Test passed."}})
        revised = assessment.revise(doc, updated, "Alex", "2026-09-05", "Test passed")
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(len(revised["history"]), 1)
        self.assertEqual(revised["history"][0]["previous"]["disposition"]["value"], "Test")
        self.assertEqual(revised["disposition"]["value"], "Apply")
        metadata = {"item_id": "PF-0001", "provenance_status": "verified"}
        self.assertEqual(assessment.validate_document(revised, metadata, PORTFOLIO), [])


if __name__ == "__main__":
    unittest.main()

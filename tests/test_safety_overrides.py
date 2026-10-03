"""PR4: the builder never renders Apply for a gated item; security cannot pass validated without review."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pf_lib import assessment  # noqa: E402
from pf_lib.compute import compute_record  # noqa: E402
from pf_lib.payload import payload_record  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "assessments"


def record_for(doc: dict, provenance: str = "verified") -> dict:
    metadata = {
        "item_id": "PF-0001", "slug": "fixture-item", "kind": "note", "work_type": "note",
        "identity": {"title": "Fixture", "authors": ["A"], "year": 2026}, "sources": [],
        "route": {"selected": ["read"], "skipped": []}, "relations": [], "topics": ["Unclassified"],
        "state": {"lifecycle": "route_complete", "current_stage": None, "next_action": None, "blocker": None},
        "provenance_status": provenance, "evidence_class": "unknown", "captured_via": "manual",
    }
    return {
        "root": ROOT, "row": {"slug": "fixture-item", "number": "1", "title": "Fixture", "authors": "A", "year": "2026"},
        "paper_dir": ROOT, "metadata": metadata, "readme": "# Fixture\n", "work_documents": [],
        "assessment": doc, "slug": "fixture-item", "route_data": metadata["route"], "selected": ["read"], "skipped": [],
        "identity": metadata["identity"], "primary": {}, "topics": ["Unclassified"], "summary": "s",
        "source_href": None, "local_source_href": None, "documents": [],
    }


class SafetyOverrideTests(unittest.TestCase):
    def payload(self, name: str) -> dict:
        doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        provenance = doc.pop("_metadata_provenance", "verified")
        return payload_record(compute_record(record_for(doc, provenance), "2026-09-04"))

    def test_no_gated_fixture_renders_apply(self):
        for path in sorted(FIXTURES.glob("gated-*.json")):
            paper = self.payload(path.name)
            self.assertTrue(paper["applyBlocked"], path.name)
            self.assertNotEqual(paper["dispositionEffective"], "Apply", path.name)
            self.assertTrue(paper["blockReason"], path.name)

    def test_valid_apply_fixture_renders_apply(self):
        paper = self.payload("valid-apply.json")
        self.assertFalse(paper["applyBlocked"])
        self.assertEqual(paper["dispositionEffective"], "Apply")

    def test_security_cannot_exceed_validated_without_threat_review(self):
        doc = json.loads((FIXTURES / "gated-security-validated.json").read_text(encoding="utf-8"))
        gate = assessment.safety_gate(doc, {"item_id": "PF-0001", "provenance_status": "verified"})
        self.assertTrue(gate["blocked"])
        doc["threat_review"] = {"date": "2026-09-04", "reviewer": "Alex", "summary": "Reviewed sandbox boundary."}
        gate = assessment.safety_gate(doc, {"item_id": "PF-0001", "provenance_status": "verified"})
        self.assertFalse(gate["blocked"])

    def test_failed_provenance_blocks_regardless_of_scores(self):
        doc = json.loads((FIXTURES / "valid-apply.json").read_text(encoding="utf-8"))
        gate = assessment.safety_gate(doc, {"item_id": "PF-0001", "provenance_status": "failed"})
        self.assertTrue(gate["blocked"])
        self.assertEqual(gate["effective_disposition"], "Reject")

    def test_unassessed_item_is_not_blocked_and_has_no_disposition(self):
        gate = assessment.safety_gate(None, {"item_id": "PF-0001", "provenance_status": "verified"})
        self.assertFalse(gate["blocked"])
        self.assertIsNone(gate["effective_disposition"])


if __name__ == "__main__":
    unittest.main()

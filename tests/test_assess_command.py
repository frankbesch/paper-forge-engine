"""PR4: pf.py assess and classify write only when asked, revise with history, and never store scores."""

import argparse
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pf", REPO_ROOT / "scripts" / "pf.py")
pf = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pf)


class AssessCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        for name in ("portfolio.json", "taxonomy.json", "evidence-class-map.json"):
            shutil.copy(REPO_ROOT / "config" / name, self.root / "config" / name)
        item = self.root / "papers" / "fixture-item"
        (item / "work").mkdir(parents=True)
        self.metadata = {
            "schema_version": 1, "item_id": "PF-0001", "slug": "fixture-item", "kind": "note",
            "work_type": "quotation", "identity": {"title": "Fixture", "authors": [], "year": 2026},
            "sources": [], "route": {"name": "capture", "selected": ["read"], "skipped": []}, "artifacts": {},
            "relations": [], "state": {"lifecycle": "route_complete"}, "topics": ["Unclassified"],
            "captured_via": "manual", "provenance_status": "unverified", "evidence_class": "anecdote or opinion",
        }
        (item / "metadata.json").write_text(json.dumps(self.metadata, indent=2) + "\n")
        self.item = item

    def tearDown(self):
        self.temp.cleanup()

    def args(self, **overrides):
        values = dict(item="PF-0001", draft=None, assessor=None, date="2026-09-04", reason=None, dry_run=False)
        values.update(overrides)
        return argparse.Namespace(**values)

    def write_draft(self, extra: dict) -> Path:
        draft = {
            "disposition": {"value": "Watch", "rationale": "Promising; evidence still thin."},
            "general": {"evidence_quality": {"score": 1, "rationale": "Single anecdote."}},
            "endeavors": {"thinking": {"relevance": 3, "expected_leverage": 2, "confidence": "low", "use_case": "Frame a decision.", "suggested_next_action": "Find a second source.", "owner": "owner"}},
        }
        draft.update(extra)
        path = self.root / "draft.json"
        path.write_text(json.dumps(draft))
        return path

    def test_dry_run_without_draft_prints_null_draft_and_writes_nothing(self):
        document, errors, written = pf.assess_item(self.args(dry_run=True), self.root)
        self.assertEqual(errors, [])
        self.assertFalse(written)
        self.assertIsNone(document["disposition"]["value"])
        self.assertEqual(document["revision"], 1)
        self.assertEqual(set(document["endeavors"]), {"notes", "projects", "ai-superuser", "career", "thinking"})
        self.assertFalse((self.item / "assessment.json").exists())

    def test_draft_dry_run_validates_but_writes_nothing(self):
        document, errors, written = pf.assess_item(self.args(draft=str(self.write_draft({})), dry_run=True), self.root)
        self.assertEqual(errors, [])
        self.assertFalse(written)
        self.assertFalse((self.item / "assessment.json").exists())

    def test_draft_writes_then_revision_requires_reason_and_keeps_history(self):
        document, errors, written = pf.assess_item(self.args(draft=str(self.write_draft({}))), self.root)
        self.assertEqual(errors, [])
        self.assertTrue(written)
        stored = json.loads((self.item / "assessment.json").read_text())
        self.assertEqual(stored["revision"], 1)
        self.assertEqual(stored["disposition"]["value"], "Watch")
        with self.assertRaises(ValueError):
            pf.assess_item(self.args(draft=str(self.write_draft({"disposition": {"value": "Learn", "rationale": "Reads well."}}))), self.root)
        document, errors, written = pf.assess_item(
            self.args(draft=str(self.write_draft({"disposition": {"value": "Learn", "rationale": "Reads well."}})), reason="Second read"), self.root
        )
        self.assertEqual(errors, [])
        stored = json.loads((self.item / "assessment.json").read_text())
        self.assertEqual(stored["revision"], 2)
        self.assertEqual(stored["history"][0]["previous"]["disposition"]["value"], "Watch")
        self.assertEqual(stored["history"][0]["reason"], "Second read")
        self.assertNotIn("priority", json.dumps(stored))

    def test_assessor_flag_overrides_draft_assessor(self):
        draft = self.write_draft({"assessor": "l3-run-1"})
        document, errors, written = pf.assess_item(self.args(draft=str(draft), assessor="Alex"), self.root)
        self.assertEqual(errors, [])
        self.assertTrue(written)
        self.assertEqual(json.loads((self.item / "assessment.json").read_text())["assessor"], "Alex")
        (self.item / "assessment.json").unlink()
        document, errors, written = pf.assess_item(self.args(draft=str(draft)), self.root)
        self.assertEqual(document["assessor"], "l3-run-1")
        (self.item / "assessment.json").unlink()
        document, errors, written = pf.assess_item(self.args(draft=str(self.write_draft({}))), self.root)
        self.assertEqual(document["assessor"], "assistant with Alex review")

    def test_invalid_draft_is_reported_and_not_written(self):
        document, errors, written = pf.assess_item(self.args(draft=str(self.write_draft({"priority": 80}))), self.root)
        self.assertTrue(errors)
        self.assertFalse(written)
        self.assertFalse((self.item / "assessment.json").exists())

    def test_classify_sets_topics_and_maps_evidence_class(self):
        args = argparse.Namespace(item="PF-0001", topics=["Reusable context", "Creative work"], work_type="practitioner_guide", dry_run=False)
        changes, written = pf.classify_item(args, self.root)
        self.assertTrue(written)
        stored = json.loads((self.item / "metadata.json").read_text())
        self.assertEqual(stored["topics"], ["Reusable context", "Creative work"])
        self.assertEqual(stored["work_type"], "practitioner_guide")
        self.assertEqual(stored["evidence_class"], "practitioner guidance")
        with self.assertRaises(ValueError):
            pf.classify_item(argparse.Namespace(item="PF-0001", topics=["Unclassified", "Creative work"], work_type=None, dry_run=False), self.root)
        with self.assertRaises(ValueError):
            pf.classify_item(argparse.Namespace(item="PF-0001", topics=None, work_type="not-in-map", dry_run=False), self.root)


if __name__ == "__main__":
    unittest.main()

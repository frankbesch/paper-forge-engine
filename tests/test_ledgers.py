"""PR5: ledgers are append-only, ids monotonic, receipts validated, no absolute paths; apply/outcome commands behave."""

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pf_lib import ledger  # noqa: E402

SPEC = importlib.util.spec_from_file_location("pf", ROOT / "scripts" / "pf.py")
pf = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pf)
FIXTURES = ROOT / "tests" / "fixtures" / "ledgers"


class LedgerContractTests(unittest.TestCase):
    def test_ids_are_unique_and_monotonic(self):
        errors = []
        entries = ledger.read_ledger(FIXTURES / "exports.jsonl")
        ledger._check_ids(entries, "PFX", "exports", errors)
        self.assertEqual(errors, [])
        self.assertEqual(ledger.next_receipt_id(entries, "PFX"), "PFX-0004")
        bad = []
        ledger._check_ids(ledger.read_ledger_safely(FIXTURES / "exports-malformed.jsonl", bad), "PFX", "exports", bad)
        self.assertTrue(any("invalid JSON" in e for e in bad))
        self.assertTrue(any("duplicate receipt_id" in e for e in bad))

    def test_validate_ledgers_accepts_fixture_and_rejects_absolute_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ledger" / "exports").mkdir(parents=True)
            shutil.copy(FIXTURES / "exports.jsonl", root / "ledger" / "exports.jsonl")
            shutil.copy(FIXTURES / "outcomes.jsonl", root / "ledger" / "outcomes.jsonl")
            for i in (1, 2, 3):
                (root / "ledger" / "exports" / f"PFX-000{i}.md").write_text("package\n")
            errors = []
            ledger.validate_ledgers(root, {"PF-0001", "PF-0002", "PF-0003"}, errors)
            self.assertEqual(errors, [])
            shutil.copy(FIXTURES / "exports-absolute-path.jsonl", root / "ledger" / "exports.jsonl")
            errors = []
            ledger.validate_ledgers(root, {"PF-0001"}, errors)
            self.assertTrue(any("absolute path" in e for e in errors), errors)

    def test_live_ledgers_contain_no_absolute_paths(self):
        for name in ("exports.jsonl", "outcomes.jsonl", "intake.jsonl", "approvals.jsonl"):
            path = ROOT / "ledger" / name
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    self.assertEqual(ledger._absolute_paths(json.loads(line)) if line.strip() else [], [], name)


class _TransferFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        for name in ("portfolio.json", "taxonomy.json", "evidence-class-map.json"):
            shutil.copy(ROOT / "config" / name, self.root / "config" / name)
        (self.root / "ledger").mkdir()
        for name in ("PF-0001", "PF-0002"):
            item = self.root / "papers" / name.lower()
            (item / "work").mkdir(parents=True)
            (item / "source").mkdir()
            (item / "source/x.md").write_text("Synthetic source\n")
            source_hash = hashlib.sha256((item / "source/x.md").read_bytes()).hexdigest()
            metadata = {
                "schema_version": 1, "item_id": name, "slug": name.lower(), "kind": "article", "work_type": "practitioner_guide",
                "identity": {"title": f"Item {name}", "authors": ["A"], "year": 2026},
                "sources": [{"source_file": "source/x.md", "sha256": source_hash}], "route": {"name": "capture", "selected": ["read"], "skipped": []},
                "artifacts": {}, "relations": [], "state": {"lifecycle": "route_complete"}, "topics": ["Reusable context"],
                "captured_via": "manual", "provenance_status": "unverified", "evidence_class": "practitioner guidance",
            }
            (item / "metadata.json").write_text(json.dumps(metadata) + "\n")
        fixture = json.loads((ROOT / "tests" / "fixtures" / "assessments" / "valid-test.json").read_text())
        (self.root / "papers" / "pf-0001" / "assessment.json").write_text(json.dumps(fixture) + "\n")

    def tearDown(self):
        self.temp.cleanup()

    def apply_args(self, **overrides):
        values = dict(item="PF-0001", to="projects", recommendation="Package one procedure.", evidence_boundary="Design guidance only.",
                      confidence="medium", record_id=None, repo_path="registry/skills.md", also=None, approve=False, date="2026-09-04", dry_run=False)
        values.update(overrides)
        return argparse.Namespace(**values)


class TransferCommandTests(_TransferFixture):
    def test_unassessed_item_cannot_export(self):
        with self.assertRaises(ValueError) as caught:
            pf.apply_item(self.apply_args(item="PF-0002"), self.root)
        self.assertIn("no assessment", str(caught.exception))

    def test_dry_run_writes_nothing(self):
        receipt, package, written = pf.apply_item(self.apply_args(dry_run=True), self.root)
        self.assertFalse(written)
        self.assertEqual(receipt["receipt_id"], "PFX-0001")
        self.assertIn("PF-0001", package)
        self.assertFalse((self.root / "ledger" / "exports.jsonl").exists())

    def test_apply_then_outcome_derives_exported_and_measured(self):
        receipt, package, written = pf.apply_item(self.apply_args(), self.root)
        self.assertTrue(written)
        self.assertEqual(receipt["approval_status"], "pending")
        self.assertTrue((self.root / receipt["package"]).is_file())
        second, _, _ = pf.apply_item(self.apply_args(approve=True), self.root)
        self.assertEqual(second["receipt_id"], "PFX-0002")
        self.assertEqual(second["approval_status"], "approved")
        exports = ledger.read_ledger(self.root / "ledger" / "exports.jsonl")
        derived = ledger.derive_states(exports, [])
        self.assertEqual(derived["PF-0001"]["application_state"], "exported")
        outcome_args = argparse.Namespace(export="PFX-0002", expected="10 min saved", observed="6 min saved", method="wall clock", uncertainty="n=4",
                                          period="2026-09-05:2026-09-19", artifact=["reviews/timing.md"], assessment_draft=None, assessor=None, reason=None, date="2026-09-19", dry_run=False)
        outcome, written = pf.outcome_item(outcome_args, self.root)
        self.assertTrue(written)
        self.assertEqual(outcome["receipt_id"], "PFO-0001")
        outcomes = ledger.read_ledger(self.root / "ledger" / "outcomes.jsonl")
        derived = ledger.derive_states(exports, outcomes)
        self.assertEqual(derived["PF-0001"]["application_state"], "measured")
        errors = []
        ledger.validate_ledgers(self.root, {"PF-0001", "PF-0002"}, errors)
        self.assertEqual(errors, [])
        for line in (self.root / "ledger" / "exports.jsonl").read_text().splitlines():
            self.assertEqual(ledger._absolute_paths(json.loads(line)), [])

    def test_absolute_repo_path_and_artifact_are_refused(self):
        with self.assertRaises(ValueError):
            pf.apply_item(self.apply_args(repo_path="/Users/owner/projects/registry.md"), self.root)
        pf.apply_item(self.apply_args(), self.root)
        bad = argparse.Namespace(export="PFX-0001", expected="x", observed="y", method="m", uncertainty="u", period="2026-09-05:2026-09-06",
                                 artifact=["~/Desktop/notes.md"], assessment_draft=None, assessor=None, reason=None, date="2026-09-06", dry_run=False)
        with self.assertRaises(ValueError):
            pf.outcome_item(bad, self.root)

    def test_outcome_can_revise_the_assessment_with_history(self):
        pf.apply_item(self.apply_args(approve=True), self.root)
        draft = self.root / "draft.json"
        draft.write_text(json.dumps({"disposition": {"value": "Apply", "rationale": "Test passed; safe to apply."}, "general": {"evidence_quality": {"score": 3, "rationale": "Measured locally over 4 runs."}}}))
        args = argparse.Namespace(export="PFX-0001", expected="x", observed="y", method="m", uncertainty="u", period="2026-09-05:2026-09-19",
                                  artifact=[], assessment_draft=str(draft), assessor="Alex", reason="Outcome evidence", date="2026-09-19", dry_run=False)
        outcome, written = pf.outcome_item(args, self.root)
        self.assertEqual(outcome["assessment_change"], {"item_id": "PF-0001", "revision_before": 1, "revision_after": 2})
        stored = json.loads((self.root / "papers" / "pf-0001" / "assessment.json").read_text())
        self.assertEqual(stored["revision"], 2)
        self.assertEqual(stored["disposition"]["value"], "Apply")
        self.assertEqual(stored["history"][0]["previous"]["disposition"]["value"], "Test")


class ApproveCommandTests(_TransferFixture):
    """`pf.py approve`: decisions are appended to ledger/approvals.jsonl; export lines are never rewritten."""

    def approve_args(self, **overrides):
        values = dict(export="PFX-0001", by="Alex", decline=False, reason=None, date="2026-09-11", dry_run=False)
        values.update(overrides)
        return argparse.Namespace(**values)

    def exports_text(self):
        return (self.root / "ledger" / "exports.jsonl").read_text()

    def test_approve_derives_exported_without_a_new_export_id(self):
        pf.apply_item(self.apply_args(), self.root)
        before = self.exports_text()
        receipt, written = pf.approve_export(self.approve_args(), self.root)
        self.assertTrue(written)
        self.assertEqual(receipt["receipt_id"], "PFD-0001")
        self.assertEqual(receipt["decision"], "approved")
        self.assertEqual(self.exports_text(), before, "export ledger must not be rewritten")
        exports = ledger.read_ledger(self.root / "ledger" / "exports.jsonl")
        approvals = ledger.read_ledger(self.root / "ledger" / "approvals.jsonl")
        self.assertEqual(len(exports), 1)
        self.assertEqual(exports[0]["approval_status"], "pending")
        derived = ledger.derive_states(exports, [], approvals)
        self.assertEqual(derived["PF-0001"]["application_state"], "exported")
        self.assertEqual(derived["PF-0001"]["exports"][0]["approval_status"], "approved")
        errors = []
        ledger.validate_ledgers(self.root, {"PF-0001", "PF-0002"}, errors)
        self.assertEqual(errors, [])

    def test_decline_needs_a_reason_and_keeps_the_item_unexported(self):
        pf.apply_item(self.apply_args(), self.root)
        with self.assertRaises(ValueError):
            pf.approve_export(self.approve_args(decline=True), self.root)
        receipt, written = pf.approve_export(self.approve_args(decline=True, reason="Kit not fitted yet."), self.root)
        self.assertTrue(written)
        self.assertEqual(receipt["decision"], "declined")
        exports = ledger.read_ledger(self.root / "ledger" / "exports.jsonl")
        approvals = ledger.read_ledger(self.root / "ledger" / "approvals.jsonl")
        derived = ledger.derive_states(exports, [], approvals)
        self.assertIsNone(derived["PF-0001"]["application_state"])
        self.assertEqual(derived["PF-0001"]["exports"][0]["approval_status"], "declined")

    def test_latest_decision_wins_and_identical_repeat_is_refused(self):
        pf.apply_item(self.apply_args(), self.root)
        pf.approve_export(self.approve_args(), self.root)
        with self.assertRaises(ValueError) as caught:
            pf.approve_export(self.approve_args(), self.root)
        self.assertIn("already approved", str(caught.exception))
        second, _ = pf.approve_export(self.approve_args(decline=True, reason="Superseded after review.", date="2026-09-12"), self.root)
        self.assertEqual(second["receipt_id"], "PFD-0002")
        approvals = ledger.read_ledger(self.root / "ledger" / "approvals.jsonl")
        self.assertEqual(len(approvals), 2)
        exports = ledger.read_ledger(self.root / "ledger" / "exports.jsonl")
        self.assertEqual(ledger.derive_states(exports, [], approvals)["PF-0001"]["application_state"], None)
        third, _ = pf.approve_export(self.approve_args(date="2026-09-13"), self.root)
        self.assertEqual(third["receipt_id"], "PFD-0003")
        approvals = ledger.read_ledger(self.root / "ledger" / "approvals.jsonl")
        self.assertEqual(ledger.derive_states(exports, [], approvals)["PF-0001"]["application_state"], "exported")

    def test_dry_run_and_unknown_export(self):
        pf.apply_item(self.apply_args(), self.root)
        receipt, written = pf.approve_export(self.approve_args(dry_run=True), self.root)
        self.assertFalse(written)
        self.assertEqual(receipt["receipt_id"], "PFD-0001")
        self.assertFalse((self.root / "ledger" / "approvals.jsonl").exists())
        with self.assertRaises(ValueError):
            pf.approve_export(self.approve_args(export="PFX-0009"), self.root)

    def test_package_keeps_every_line_and_gains_a_dated_approval_section(self):
        receipt, _, _ = pf.apply_item(self.apply_args(), self.root)
        package = self.root / receipt["package"]
        before = package.read_text()
        pf.approve_export(self.approve_args(), self.root)
        after = package.read_text()
        self.assertTrue(after.startswith(before))
        self.assertIn("## Approval — 2026-09-11 (PFD-0001)", after)
        self.assertIn("**approved** by Alex", after)
        pf.approve_export(self.approve_args(decline=True, reason="Changed my mind.", date="2026-09-12"), self.root)
        final = package.read_text()
        self.assertTrue(final.startswith(after))
        self.assertIn("(PFD-0002)", final)
        self.assertIn("Reason: Changed my mind.", final)

    def test_bad_date_missing_package_and_escaping_package_are_refused(self):
        receipt, _, _ = pf.apply_item(self.apply_args(), self.root)
        with self.assertRaises(ValueError) as caught:
            pf.approve_export(self.approve_args(date="garbage"), self.root)
        self.assertIn("ISO-8601", str(caught.exception))
        package = self.root / receipt["package"]
        package.unlink()
        with self.assertRaises(ValueError) as caught:
            pf.approve_export(self.approve_args(), self.root)
        self.assertIn("ledger/exports/", str(caught.exception))
        outside = self.root / "elsewhere.md"
        outside.write_text("not a package\n")
        line = json.loads((self.root / "ledger" / "exports.jsonl").read_text())
        line["package"] = "elsewhere.md"
        (self.root / "ledger" / "exports.jsonl").write_text(json.dumps(line) + "\n")
        with self.assertRaises(ValueError):
            pf.approve_export(self.approve_args(), self.root)
        self.assertEqual(outside.read_text(), "not a package\n")
        self.assertFalse((self.root / "ledger" / "approvals.jsonl").exists())

    def test_validate_rejects_bad_approval_lines(self):
        pf.apply_item(self.apply_args(), self.root)
        path = self.root / "ledger" / "approvals.jsonl"
        cases = [
            ("export_id must reference", {"receipt_id": "PFD-0001", "export_id": "PFX-0042", "decision": "approved", "decided": "2026-09-11", "decided_by": "Alex", "reason": None}),
            ("decision must be", {"receipt_id": "PFD-0001", "export_id": "PFX-0001", "decision": "maybe", "decided": "2026-09-11", "decided_by": "Alex", "reason": None}),
            ("a decline needs a reason", {"receipt_id": "PFD-0001", "export_id": "PFX-0001", "decision": "declined", "decided": "2026-09-11", "decided_by": "Alex", "reason": None}),
            ("decided_by is required", {"receipt_id": "PFD-0001", "export_id": "PFX-0001", "decision": "approved", "decided": "2026-09-11", "decided_by": "", "reason": None}),
            ("export_id must reference", {"receipt_id": "PFD-0001", "export_id": ["PFX-0001"], "decision": "approved", "decided": "2026-09-11", "decided_by": "Alex", "reason": None}),
            ("decision must be", {"receipt_id": "PFD-0001", "export_id": "PFX-0001", "decision": ["approved"], "decided": "2026-09-11", "decided_by": "Alex", "reason": None}),
            ("unknown fields", {"receipt_id": "PFD-0001", "export_id": "PFX-0001", "decision": "approved", "decided": "2026-09-11", "decided_by": "Alex", "reason": None, "note": "x"}),
        ]
        for expected, entry in cases:
            path.write_text(json.dumps(entry) + "\n")
            errors = []
            ledger.validate_ledgers(self.root, {"PF-0001", "PF-0002"}, errors)
            self.assertTrue(any(expected in e for e in errors), (expected, errors))


if __name__ == "__main__":
    unittest.main()

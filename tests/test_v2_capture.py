"""PR1 capture metadata and declined-intake behavior."""

import argparse
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pf_v2_capture", ROOT / "scripts" / "pf.py")
pf = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pf)


class CaptureV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "papers").mkdir()
        (self.root / "templates").mkdir()
        shutil.copytree(ROOT / "templates" / "paper", self.root / "templates" / "paper")

    def tearDown(self):
        self.temp.cleanup()

    def args(self, **updates):
        values = {
            "source": None,
            "text": "dup",
            "filename": "source.txt",
            "title": "X",
            "authors": "",
            "year": None,
            "published": None,
            "retrieved": "2026-09-03",
            "url": None,
            "version": None,
            "language": "en",
            "access_scope": "test fixture",
            "kind": None,
            "work_type": "unknown",
            "route": "capture",
            "purpose": None,
            "feynman": None,
            "slug": None,
            "captured_via": "codex",
            "decline": None,
        }
        values.update(updates)
        return argparse.Namespace(**values)

    def test_capture_writes_topics_surface_and_verified_provenance(self):
        destination = pf.create_item(self.args(text="new material"), self.root)
        metadata = json.loads((destination / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["topics"], ["Unclassified"])
        self.assertEqual(metadata["captured_via"], "codex")
        self.assertEqual(metadata["provenance_status"], "verified")

    def test_capture_sets_evidence_class_from_approved_map_at_intake(self):
        shutil.copytree(ROOT / "config", self.root / "config")
        destination = pf.create_item(self.args(text="new material"), self.root)
        metadata = json.loads((destination / "metadata.json").read_text(encoding="utf-8"))
        table = pf.load_config(self.root, "evidence-class-map.json")["work_type_to_evidence_class"]
        self.assertIn(metadata["work_type"], table)
        self.assertEqual(metadata["evidence_class"], table[metadata["work_type"]])

    def test_decline_is_recorded_once_and_recalled_before_capture(self):
        args = self.args(decline="low-value")
        first, appended = pf.decline_capture(args, self.root)
        self.assertTrue(appended)
        second, appended = pf.decline_capture(args, self.root)
        self.assertFalse(appended)
        self.assertEqual(second, first)
        lines = (self.root / "ledger" / "intake.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        with self.assertRaisesRegex(FileExistsError, "declined on 2026-09-03 for low-value"):
            pf.create_item(self.args(), self.root)
        self.assertEqual(list((self.root / "papers").glob("*/metadata.json")), [])

    def test_duplicate_capture_appends_one_duplicate_decline(self):
        pf.create_item(self.args(text="kept"), self.root)
        with self.assertRaisesRegex(FileExistsError, "already exists as PF-0001"):
            pf.create_item(self.args(text="kept", title="Again", slug="again"), self.root)
        receipts = [json.loads(line) for line in (self.root / "ledger" / "intake.jsonl").read_text().splitlines()]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["reason"], "duplicate")
        self.assertEqual(receipts[0]["duplicate_of"], "PF-0001")


if __name__ == "__main__":
    unittest.main()

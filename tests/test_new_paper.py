import csv
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "new_paper.py"
SPEC = importlib.util.spec_from_file_location("new_paper", SCRIPT)
new_paper = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(new_paper)


class NewPaperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "templates").mkdir()
        shutil.copytree(REPO_ROOT / "templates" / "paper", self.root / "templates" / "paper")
        self.source = self.root / "input.pdf"
        self.source.write_bytes(b"%PDF-1.4\nminimal test fixture\n")

    def tearDown(self):
        self.temp.cleanup()

    def test_creates_traceable_workbook_and_registry(self):
        destination = new_paper.create_paper(
            root=self.root,
            source=self.source,
            title="A Useful Test",
            authors="Ada One; Ben Two",
            year=2026,
            added="2026-08-06",
        )

        self.assertEqual(destination.name, "2026-a-useful-test")
        self.assertTrue((destination / "source" / "input.pdf").exists())
        metadata = json.loads((destination / "metadata.json").read_text())
        self.assertEqual(metadata["authors"], ["Ada One", "Ben Two"])
        self.assertEqual(metadata["source_sha256"], new_paper.file_sha256(self.source))
        self.assertIn("A Useful Test", (destination / "README.md").read_text())
        self.assertNotIn("{{", (destination / "work" / "01-read.md").read_text())
        understand = (destination / "work" / "02-understand.md").read_text()
        self.assertIn("Feynman mode:", understand)
        self.assertIn("Reconstruction-to-paper delta", understand)

        with (self.root / "papers" / "index.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["status"], "read")

    def test_refuses_to_overwrite_existing_paper(self):
        kwargs = dict(
            root=self.root,
            source=self.source,
            title="Duplicate",
            authors="Ada One",
            year=2026,
        )
        new_paper.create_paper(**kwargs)
        with self.assertRaises(FileExistsError):
            new_paper.create_paper(**kwargs)

    def test_rejects_non_pdf_input(self):
        bad = self.root / "not-a-pdf.txt"
        bad.write_text("hello")
        with self.assertRaises(ValueError):
            new_paper.create_paper(
                root=self.root,
                source=bad,
                title="Bad",
                authors="Nobody",
                year=2026,
            )


if __name__ == "__main__":
    unittest.main()

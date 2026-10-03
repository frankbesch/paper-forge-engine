import argparse
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "pf.py"
SPEC = importlib.util.spec_from_file_location("pf", SCRIPT)
pf = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pf)


class PaperForgeCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "templates").mkdir()
        (self.root / "papers").mkdir()
        shutil.copytree(REPO_ROOT / "templates" / "paper", self.root / "templates" / "paper")

    def tearDown(self):
        self.temp.cleanup()

    def args(self, **overrides):
        values = dict(
            source=None,
            text="# A useful idea\n\nEvidence matters.\n",
            filename="idea.md",
            title="A Useful Idea",
            authors="Ada One",
            year=2026,
            published=None,
            retrieved="2026-08-25",
            url=None,
            version=None,
            language="en",
            access_scope="User-supplied text.",
            kind=None,
            work_type="note",
            route="capture",
            purpose=None,
            feynman=None,
            slug=None,
        )
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_capture_creates_common_schema_and_extraction(self):
        destination = pf.create_item(self.args(), self.root)
        metadata = json.loads((destination / "metadata.json").read_text())
        self.assertEqual(metadata["item_id"], "PF-0001")
        self.assertEqual(metadata["kind"], "note")
        self.assertEqual(metadata["sources"][0]["sha256"], pf.sha256(destination / "source" / "idea.md"))
        self.assertEqual(metadata["sources"][0]["extraction"]["status"], "complete")
        self.assertTrue((destination / "work" / "extracted.txt").exists())
        self.assertIn("Status: `skipped`", (destination / "work" / "02-understand.md").read_text())
        self.assertEqual(pf.validate_repository(self.root), [])

    def test_duplicate_bytes_stop_before_second_write(self):
        pf.create_item(self.args(), self.root)
        with self.assertRaises(FileExistsError):
            pf.create_item(self.args(title="Different Title", slug="different-title"), self.root)
        self.assertEqual(len(list((self.root / "papers").glob("*/metadata.json"))), 1)

    def test_occupied_slug_is_never_removed_on_failed_capture(self):
        destination = pf.create_item(self.args(), self.root)
        second = self.root / "second.md"
        second.write_text("Different bytes", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            pf.create_item(self.args(source=str(second), text=None), self.root)
        self.assertTrue(destination.exists())
        self.assertTrue((destination / "metadata.json").exists())

    def test_docx_extraction_has_paragraph_anchors(self):
        source = self.root / "sample.docx"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>Hello world</w:t></w:r></w:p></w:body></w:document>')
        text, receipt = pf.extract_source(source)
        self.assertEqual(receipt["status"], "complete")
        self.assertIn("[paragraph 1] Hello world", text)

    def test_pptx_extraction_has_slide_anchors(self):
        source = self.root / "sample.pptx"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("ppt/slides/slide1.xml", '<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><p:cSld><a:t>Opening claim</a:t></p:cSld></p:sld>')
            archive.writestr("ppt/slides/slide2.xml", '<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><p:cSld><a:t>Evidence</a:t></p:cSld></p:sld>')
        text, receipt = pf.extract_source(source)
        self.assertEqual(receipt["status"], "complete")
        self.assertIn("[slide 1] Opening claim", text)
        self.assertIn("[slide 2] Evidence", text)

    def test_xlsx_extraction_has_sheet_and_cell_anchors(self):
        source = self.root / "sample.xlsx"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("xl/sharedStrings.xml", '<sst xmlns="urn:x"><si><t>Metric</t></si></sst>')
            archive.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="urn:x"><sheetData><row><c r="A1" t="s"><v>0</v></c><c r="B1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>')
        text, receipt = pf.extract_source(source)
        self.assertEqual(receipt["status"], "complete")
        self.assertIn("[sheet 1!A1] Metric", text)
        self.assertIn("[sheet 1!B1] =1+1 -> 2", text)

    def test_arxiv_landing_page_resolves_to_pdf(self):
        canonical, download = pf.url_download_target("https://arxiv.org/abs/2608.13331")
        self.assertEqual(canonical, "https://arxiv.org/abs/2608.13331")
        self.assertEqual(download, "https://arxiv.org/pdf/2608.13331.pdf")

    def test_image_ocr_is_labeled_as_unverified(self):
        source = self.root / "sample.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\n")
        completed = mock.Mock(returncode=0, stdout=b"recognized text\n", stderr=b"")
        with mock.patch.object(pf.shutil, "which", return_value="/usr/bin/tesseract"), mock.patch.object(pf.subprocess, "run", return_value=completed):
            text, receipt = pf.extract_source(source)
        self.assertEqual(text, "recognized text\n")
        self.assertIn("not exact quotation", receipt["caveat"])

    def test_pdf_extraction_adds_page_anchors(self):
        source = self.root / "sample.pdf"
        source.write_bytes(b"%PDF-1.4\n")
        completed = mock.Mock(returncode=0, stdout=b"First page\fSecond page\f", stderr=b"")
        with mock.patch.object(pf.shutil, "which", return_value="/usr/bin/pdftotext"), mock.patch.object(pf.subprocess, "run", return_value=completed):
            text, receipt = pf.extract_source(source)
        self.assertEqual(receipt["status"], "complete")
        self.assertIn("[page 1]\nFirst page", text)
        self.assertIn("[page 2]\nSecond page", text)

    def test_query_returns_source_backed_item(self):
        pf.create_item(self.args(), self.root)
        results = pf.query_library("evidence", self.root)
        self.assertEqual(results[0]["item_id"], "PF-0001")


if __name__ == "__main__":
    unittest.main()

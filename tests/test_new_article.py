import csv
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "new_article.py"
SPEC = importlib.util.spec_from_file_location("new_article", SCRIPT)
new_article = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(new_article)


class NewArticleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "templates").mkdir()
        shutil.copytree(REPO_ROOT / "templates" / "paper", self.root / "templates" / "paper")
        self.snapshot = self.root / "article.html"
        self.snapshot.write_text("<!doctype html><title>Test article</title>")

    def tearDown(self):
        self.temp.cleanup()

    def test_creates_url_record_snapshot_and_registry(self):
        destination = new_article.create_article(
            root=self.root,
            url="https://example.com/article",
            snapshot=self.snapshot,
            title="A Web Test",
            authors="Ada One",
            year=2026,
            published="2026-06-19",
            retrieved="2026-08-06",
        )

        metadata = json.loads((destination / "metadata.json").read_text())
        self.assertEqual(metadata["canonical_url"], "https://example.com/article")
        self.assertEqual(metadata["source_sha256"], new_article.file_sha256(self.snapshot))
        self.assertTrue((destination / "source" / "article.html").exists())
        self.assertIn("https://example.com/article", (destination / "README.md").read_text())

        with (self.root / "papers" / "index.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["status"], "read")

    def test_rejects_non_http_url(self):
        with self.assertRaises(ValueError):
            new_article.create_article(
                root=self.root,
                url="file:///tmp/article.html",
                snapshot=self.snapshot,
                title="Bad URL",
                authors="Ada One",
                year=2026,
                published="2026-06-19",
            )


if __name__ == "__main__":
    unittest.main()


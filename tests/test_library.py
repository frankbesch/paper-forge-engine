import csv
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "tests" / "fixtures" / "library"


class LibraryBuildTests(unittest.TestCase):
    def test_builds_one_self_contained_html_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "library.html"
            subprocess.run(
                ["python3", str(ROOT / "scripts" / "build_library.py"), "--root", str(LIBRARY), "--output", str(output)],
                check=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            html = output.read_text(encoding="utf-8")

        self.assertIn("Paper Forge Console", html)
        self.assertIn("Grounding answers in retrieved passages", html)
        self.assertIn("Structured prompts on a classification set", html)
        self.assertIn("Relationship map", html)
        self.assertIn("Evidence-to-action portfolio", html)
        self.assertIn("evidence-ledger", html)
        self.assertIn("doc-callout", html)
        self.assertNotIn("__PAPER_FORGE_LIBRARY_DATA__", html)
        self.assertNotIn("__PAPER_FORGE_CONFIG__", html)
        self.assertNotRegex(html, r'<(?:script|link)[^>]+(?:src|href)="https?://')

    def test_embedded_registry_matches_paper_index(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "library.html"
            subprocess.run(
                ["python3", str(ROOT / "scripts" / "build_library.py"), "--root", str(LIBRARY), "--output", str(output)],
                check=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            html = output.read_text(encoding="utf-8")

        start = html.index('<script id="library-data" type="application/json">')
        start = html.index(">", start) + 1
        end = html.index("</script>", start)
        data = json.loads(html[start:end].replace("<\\/", "</"))
        with (LIBRARY / "papers" / "index.csv").open(encoding="utf-8", newline="") as stream:
            registry_count = sum(1 for _ in csv.DictReader(stream))

        self.assertEqual(registry_count, len(data))
        self.assertTrue(all(len(item["documents"]) == 8 for item in data))
        self.assertTrue(all(item["themes"] for item in data))
        self.assertTrue(all(item["kind"] for item in data))
        self.assertTrue(all("freshness" in item for item in data))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_inline_console_script_parses(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "library.html"
            script = Path(directory) / "console.js"
            subprocess.run(
                ["python3", str(ROOT / "scripts" / "build_library.py"), "--root", str(LIBRARY), "--as-of", "2026-09-04", "--output", str(output)],
                check=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            html = output.read_text(encoding="utf-8")
            script.write_text(html.rsplit("<script>", 1)[1].split("</script>", 1)[0], encoding="utf-8")
            result = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

import csv
import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "tests" / "fixtures" / "library"
# Link destinations may contain one level of balanced parentheses (CommonMark),
# e.g. source/Example_Deck_(Part_2).pptx; a bare [^)]+ would truncate them.
LINK = re.compile(r"\[[^]]*\]\(((?:[^()]|\([^()]*\))+)\)")


class RepositoryIntegrityTests(unittest.TestCase):
    def test_relative_markdown_links_resolve(self):
        missing = []
        markdown_files = [ROOT / "README.md", LIBRARY / "ACTIVE.md"]
        markdown_files.extend(
            document
            for document in (LIBRARY / "papers").glob("*/**/*.md")
            if "source" not in document.relative_to(LIBRARY / "papers").parts
        )
        for document in markdown_files:
            for target in LINK.findall(document.read_text(encoding="utf-8")):
                target = target.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                if not (document.parent / target).resolve().exists():
                    missing.append(f"{document} -> {target}")
        self.assertEqual(missing, [])

    def test_paper_sources_match_recorded_checksums(self):
        for metadata_path in (LIBRARY / "papers").glob("*/metadata.json"):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            sources = metadata.get("sources") or [{
                "source_file": metadata["source_file"],
                "sha256": metadata["source_sha256"],
            }]
            for recorded in sources:
                source = metadata_path.parent / recorded["source_file"]
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                self.assertEqual(digest, recorded["sha256"], source)

    def test_common_item_schema_is_complete_and_ids_are_unique(self):
        ids = []
        for metadata_path in (LIBRARY / "papers").glob("*/metadata.json"):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            for key in ["schema_version", "item_id", "slug", "kind", "work_type", "identity", "sources", "route", "artifacts", "relations", "state"]:
                self.assertIn(key, metadata, metadata_path)
            ids.append(metadata["item_id"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_registry_entries_have_workbooks(self):
        with (LIBRARY / "papers" / "index.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            paper = LIBRARY / "papers" / row["slug"]
            self.assertTrue((paper / "README.md").is_file(), paper)
            self.assertTrue((paper / "metadata.json").is_file(), paper)
            for number, name in enumerate(
                ["read", "understand", "analyze", "reproduce", "experiment", "extend", "discover"],
                start=1,
            ):
                self.assertTrue((paper / "work" / f"{number:02d}-{name}.md").is_file())

    def test_understand_workbooks_record_feynman_mode(self):
        template = (ROOT / "templates" / "paper" / "work" / "02-understand.md").read_text(
            encoding="utf-8"
        )
        for required in [
            "Feynman mode:",
            "Blank-sheet reconstruction — freeze before reading",
            "Reconstruction-to-paper delta",
            "Live teach-back",
            "## Sparks",
        ]:
            self.assertIn(required, template)

        # Contract: the Feynman mode is recorded when Understand is selected (DESIGN.md
        # `route`; LOOP.md together-mode table). A skipped Understand records the stage
        # reason and reopening trigger instead, either on the template's routing block
        # or in the compact form the 2026-09-17 intake wrote (Reason: / Reopening trigger:).
        for workbook in (LIBRARY / "papers").glob("*/work/02-understand.md"):
            text = workbook.read_text(encoding="utf-8")
            if "Status: `skipped`" in text:
                compact = "Reason:" in text and "Reopening trigger:" in text
                self.assertTrue("Feynman mode:" in text or compact, workbook)
            else:
                self.assertIn("Feynman mode:", text, workbook)


if __name__ == "__main__":
    unittest.main()

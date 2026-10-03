"""PR0 baseline guarantees for Paper Forge v2."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "tests" / "fixtures" / "library"
sys.path.insert(0, str(ROOT / "scripts"))

import build_library  # noqa: E402
import source_tree_hash  # noqa: E402


def build(as_of: str) -> str:
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "library.html"
        subprocess.run(
            ["python3", str(ROOT / "scripts" / "build_library.py"), "--root", str(LIBRARY), "--output", str(output), "--as-of", as_of],
            check=True, cwd=ROOT, capture_output=True, text=True,
        )
        return output.read_text(encoding="utf-8")


class TopicsTests(unittest.TestCase):
    def test_every_item_has_controlled_topics(self):
        taxonomy = json.loads((ROOT / "config" / "taxonomy.json").read_text(encoding="utf-8"))
        allowed = set(taxonomy["topics"])
        self.assertIn("Unclassified", allowed)
        for metadata_path in (LIBRARY / "papers").glob("*/metadata.json"):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            topics = metadata.get("topics")
            self.assertTrue(topics, metadata_path)
            self.assertLessEqual(set(topics), allowed, metadata_path)
            if "Unclassified" in topics:
                self.assertEqual(topics, ["Unclassified"], metadata_path)

    def test_builder_has_no_hardcoded_themes(self):
        source = (ROOT / "scripts" / "build_library.py").read_text(encoding="utf-8")
        self.assertNotIn("NAV_THEMES", source)


class DeterminismTests(unittest.TestCase):
    def test_same_inputs_and_as_of_give_identical_bytes(self):
        first = build("2026-09-02")
        second = build("2026-09-02")
        self.assertEqual(hashlib.sha256(first.encode()).hexdigest(), hashlib.sha256(second.encode()).hexdigest())
        self.assertIn('content="2026-09-02"', first)
        self.assertNotIn("__PAPER_FORGE_AS_OF__", first)


class ActiveFocusTests(unittest.TestCase):
    def test_active_focus_block_is_not_stale(self):
        text = (LIBRARY / "ACTIVE.md").read_text(encoding="utf-8")
        start = text.index(build_library.FOCUS_START)
        end = text.index(build_library.FOCUS_END) + len(build_library.FOCUS_END)
        rendered = build_library.render_active_focus(build_library.load_library(root=LIBRARY))
        self.assertEqual(text[start:end], rendered, "run: python3 scripts/build_library.py --root tests/fixtures/library --write-active")

    def test_focus_block_lists_every_item_past_read(self):
        papers = build_library.load_library(root=LIBRARY)
        rendered = build_library.render_active_focus(papers)
        for paper in papers:
            if paper["lifecycle"] == "active" and paper["currentStage"] not in (None, "read"):
                self.assertIn(f"| {paper['itemId']} |", rendered)


class SourceTreeHashTests(unittest.TestCase):
    def test_tree_hash_covers_every_recorded_source_and_is_stable(self):
        recorded = set()
        for metadata_path in (LIBRARY / "papers").glob("*/metadata.json"):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            for source in metadata.get("sources") or []:
                recorded.add((metadata_path.parent / source["source_file"]).resolve())
        files = {p.resolve() for p in source_tree_hash.source_files(LIBRARY)}
        self.assertTrue(recorded <= files, sorted(recorded - files))
        self.assertEqual(source_tree_hash.tree_hash(LIBRARY), source_tree_hash.tree_hash(LIBRARY))


if __name__ == "__main__":
    unittest.main()

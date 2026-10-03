"""PR2 unit tests for each builder layer and the golden output."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pf_lib import compute, load, normalize, payload, render, verify  # noqa: E402


class BuilderLayerTests(unittest.TestCase):
    def raw_record(self) -> dict:
        readme = """# Example

## Forge status

| Stage | Status | Artifact |
|---|---|---|
| Read | complete | work/01-read.md |

## One-paragraph synthesis

A compact summary.
"""
        metadata = {
            "item_id": "PF-9999",
            "work_type": "conceptual",
            "identity": {"title": "Example", "authors": ["A"], "year": 2026},
            "sources": [{"source_file": "source/example.pdf", "access_scope": "public"}],
            "route": {"selected": ["read"], "skipped": [stage[0] for stage in load.STAGES[1:]]},
            "topics": ["Unclassified"],
            "state": {"lifecycle": "route_complete", "current_stage": None},
        }
        work = [
            {"key": key, "label": label, "filename": filename, "content": f"# {label}\n"}
            for key, label, filename in load.STAGES
        ]
        return {
            "root": ROOT,
            "row": {"slug": "example", "number": "1", "title": "Example", "authors": "A", "year": "2026", "added": "2026-01-01"},
            "paper_dir": ROOT / "papers" / "example",
            "metadata": metadata,
            "readme": readme,
            "work_documents": work,
            "assessment": {"freshness": {"review_by": "2026-09-02"}},
        }

    def test_load_layer_reads_and_validates_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            (fixture / "config").mkdir()
            (fixture / "papers" / "example" / "work").mkdir(parents=True)
            (fixture / "config" / "taxonomy.json").write_text(json.dumps({"topics": ["Unclassified"]}))
            (fixture / "papers" / "index.csv").write_text("slug,title,authors,year,added\nexample,Example,A,2026,2026-01-01\n")
            raw = self.raw_record()
            paper = fixture / "papers" / "example"
            (paper / "metadata.json").write_text(json.dumps(raw["metadata"]))
            (paper / "README.md").write_text(raw["readme"])
            for document in raw["work_documents"]:
                (paper / "work" / document["filename"]).write_text(document["content"])
            records = load.load_repository(fixture)
        self.assertEqual(records[0]["metadata"]["item_id"], "PF-9999")

    def test_normalize_layer_unifies_record_and_excludes_audit_note(self):
        raw = self.raw_record()
        raw["readme"] += "\n<!-- pf:console-exclude:start -->secret<!-- pf:console-exclude:end -->\n"
        record = normalize.normalize_record(raw)
        self.assertEqual(record["source_href"], "papers/example/source/example.pdf")
        self.assertNotIn("secret", record["documents"][0]["content"])

    def test_compute_layer_derives_view_fields_and_freshness(self):
        record = compute.compute_record(normalize.normalize_record(self.raw_record()), "2026-09-03")
        self.assertEqual(record["route_label"], "Capture")
        self.assertEqual(record["access_label"], "Local PDF")
        self.assertEqual(record["statuses"]["read"], "complete")
        self.assertEqual(record["freshness"]["status"], "stale")

    def test_payload_layer_preserves_compact_console_contract(self):
        record = compute.compute_record(normalize.normalize_record(self.raw_record()), "2026-09-03")
        result = payload.payload_record(record)
        self.assertEqual(result["itemId"], "PF-9999")
        self.assertEqual(len(result["documents"]), 8)
        self.assertIn("freshness", result)
        self.assertEqual(result["evidenceClass"], "unknown")

    def test_render_layer_fills_template_and_active_focus(self):
        result = render.render_library("__PAPER_FORGE_AS_OF__ __PAPER_FORGE_LIBRARY_DATA__ __PAPER_FORGE_CONFIG__", [], "2026-09-03", console_config={"x": 1})
        self.assertEqual(result, '2026-09-03 [] {"x":1}')
        self.assertIn(render.FOCUS_START, render.render_active_focus([]))

    def test_render_layer_preserves_source_text_without_runtime_rewriting(self):
        result = render.render_library('__PAPER_FORGE_LIBRARY_DATA__', [{"content": "fetch('/api/x')"}], "2026-09-04")
        self.assertEqual(json.loads(result), [{"content": "fetch('/api/x')"}])

    def test_verify_layer_checks_count_links_and_offline_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            linked = root / "papers" / "example"
            linked.mkdir(parents=True)
            (linked / "README.md").write_text("ok")
            papers = [{"itemId": "PF-9999", "overviewHref": "papers/example/README.md", "localSourceHref": None, "documents": []}]
            html = render.render_library('<script id="library-data" type="application/json">__PAPER_FORGE_LIBRARY_DATA__</script>', papers, "2026-09-03")
            output = root / "library.html"
            output.write_text(html)
            self.assertEqual(len(verify.verify_built_file(output, root, 1)), 1)

    def test_end_to_end_output_matches_console_golden_hash(self):
        expected = (ROOT / "tests" / "golden" / "library.sha256").read_text().strip()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "library.html"
            subprocess.run(
                ["python3", str(ROOT / "scripts" / "build_library.py"), "--root", str(ROOT / "tests" / "fixtures" / "library"),
                 "--as-of", "2026-09-04", "--output", str(output)],
                cwd=ROOT,
                env={k: v for k, v in os.environ.items() if k not in ("QUOIN_ROOT", "PF_ROOT")},  # frozen tokens: deterministic
                check=True,
                capture_output=True,
                text=True,
            )
            import hashlib
            actual = hashlib.sha256(output.read_bytes()).hexdigest()
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()

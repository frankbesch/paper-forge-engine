"""Static state and scope tests for Paper Forge Console."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "tests" / "fixtures" / "library"
TEMPLATE = (ROOT / "ui" / "library.template.html").read_text(encoding="utf-8")


def _build() -> str:
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "library.html"
        subprocess.run(["python3", str(ROOT / "scripts" / "build_library.py"), "--root", str(LIBRARY),
                        "--as-of", "2026-09-04", "--output", str(output)], check=True, capture_output=True, text=True)
        return output.read_text(encoding="utf-8")


BUILT = _build()


class ConsoleStateTests(unittest.TestCase):
    def test_five_bounded_home_queues_are_present(self):
        for queue in ("queue-owner", "queue-act", "queue-test", "queue-review", "queue-recent"):
            self.assertIn(f'id="{queue}"', TEMPLATE)
        self.assertIn("items.slice(0, 7)", TEMPLATE)

    def test_incomplete_states_have_distinct_text(self):
        for state in ("no-match", "unassessed", "unclassified", "stale", "blocked", "missing-outcome", "failed-integrity"):
            self.assertRegex(TEMPLATE, rf"['\"]?{state}['\"]?: \[")

    def test_static_console_has_no_server_coupling(self):
        for forbidden in ("fetch(", "/api/", "action-dialog", "queue-respond", "live-state"):
            self.assertNotIn(forbidden, TEMPLATE)
        self.assertIn("/pf resume ${paper.itemId", TEMPLATE)

    def test_runtime_has_no_server_coupling(self):
        scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", BUILT, flags=re.DOTALL)
        runtime = scripts[-1]
        for forbidden in ("fetch(", "/api/", "action-dialog", "queue-respond", "live-state"):
            self.assertNotIn(forbidden, runtime)

    def test_library_rows_are_compact(self):
        self.assertIn("compactCreators(paper.authors)", TEMPLATE)
        self.assertIn("truncateText(next, 160)", TEMPLATE)
        self.assertIn('class="table-title" title="${escapeHtml(paper.title)}"', TEMPLATE)
        self.assertIn('class="next-cell" title="${escapeHtml(next)}"', TEMPLATE)
        self.assertIn('class="next-preview"', TEMPLATE)
        fixture = json.loads((ROOT / "tests" / "fixtures" / "portfolio-500" / "items.json").read_text())
        for paper in fixture:
            creators = [creator for creator in paper.get("authors", []) if creator]
            label = "Creator unknown" if not creators else (f"{creators[0]} et al." if len(creators) > 2 else ", ".join(creators))
            compact_label = label if len(label) <= 60 else label[:59].rstrip() + "…"
            next_action = paper.get("nextAction") or paper.get("blocker") or "Assess and define the next action."
            compact_next = next_action if len(next_action) <= 160 else next_action[:159].rstrip() + "…"
            self.assertLessEqual(len(compact_label), 60)
            self.assertLessEqual(len(compact_next), 160)

    def test_reader_cancel_restores_focus(self):
        self.assertIn("reader.addEventListener('cancel'", TEMPLATE)
        self.assertIn("event.preventDefault(); closeReader();", TEMPLATE)
        self.assertIn("if (readerReturnFocus?.focus) readerReturnFocus.focus();", TEMPLATE)

    def test_dynamic_map_excludes_unclassified_similarity(self):
        self.assertNotIn("const mapPositions", TEMPLATE)
        self.assertIn("const positions = new Map", TEMPLATE)
        self.assertIn("theme !== 'Unclassified'", TEMPLATE)

    def test_endeavor_page_never_infers_fit(self):
        self.assertIn("does not infer portfolio relevance from topics", TEMPLATE)
        self.assertIn("No assessed items yet.", TEMPLATE)
        for section in ("Highest priority", "Trusted foundations", "Promising tests", "Reusable methods", "Evidence gaps", "Exports", "Measured outcomes", "Stale assumptions"):
            self.assertIn(f"<h3>{section}</h3>", TEMPLATE)

    def test_library_has_twelve_filters_and_seven_sorts(self):
        filter_ids = re.findall(r'<(?:input|select) id="(search|[a-z-]+-filter)"', TEMPLATE)
        self.assertEqual(len(set(filter_ids)), 12)
        sort_markup = re.search(r'<select id="sort-select">(.*?)</select>', TEMPLATE, flags=re.DOTALL).group(1)
        sorts = re.findall(r'<option value="(?:newest|evidence|relevance|effort|stale|item-id|title)"', sort_markup)
        self.assertEqual(len(sorts), 7)

    def test_default_and_optional_columns_match_spec(self):
        for heading in ("Item ID", "Title", "Kind", "Evidence class", "Disposition", "Stage", "Next action"):
            self.assertIn(f"<th>{heading}</th>", TEMPLATE)
        for column in ("priority", "freshness", "fit"):
            self.assertIn(f'data-column="{column}"', TEMPLATE)


if __name__ == "__main__":
    unittest.main()


class AssessmentUiTests(unittest.TestCase):
    """PR4: the console exposes the assessment panels and effective dispositions."""

    def test_template_has_assessment_panels_and_endeavor_sections(self):
        template = (ROOT / "ui" / "library.template.html").read_text(encoding="utf-8")
        self.assertIn('id="assessment-panels"', template)
        self.assertIn("function renderAssessmentPanels", template)
        for key in ("priority", "foundations", "tests", "methods", "gaps", "exports", "measured", "stale"):
            self.assertIn(f'id="queue-e-{key}"', template)

    def test_home_queues_use_effective_disposition_and_exclude_blocked(self):
        template = (ROOT / "ui" / "library.template.html").read_text(encoding="utf-8")
        self.assertIn("!paper.applyBlocked && paper.dispositionEffective === 'Apply'", template)
        self.assertIn("!paper.applyBlocked && paper.dispositionEffective === 'Test'", template)
        self.assertIn("paper.applyBlocked || ['Watch', 'Reject', 'Retire', 'Hold']", template)

    def test_payload_carries_effective_disposition_and_block_reason(self):
        html = BUILT
        start = html.index('<script id="library-data" type="application/json">')
        start = html.index(">", start) + 1
        end = html.index("</script>", start)
        data = json.loads(html[start:end].replace("<\\/", "</"))
        for paper in data:
            self.assertIn("dispositionEffective", paper)
            self.assertIn("applyBlocked", paper)
            self.assertIn("blockReason", paper)
            if not paper["assessed"]:
                self.assertIsNone(paper["dispositionEffective"])
                self.assertFalse(paper["applyBlocked"])

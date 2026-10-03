"""Static route contract tests for Paper Forge Console."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "ui" / "library.template.html").read_text(encoding="utf-8")


class ConsoleRouteTests(unittest.TestCase):
    def test_primary_routes_exist(self):
        for route in ("home", "library", "maps"):
            self.assertIn(f'data-route="{route}"', TEMPLATE)

    def test_endeavor_and_item_routes_are_supported(self):
        self.assertIn("route.startsWith('endeavors/')", TEMPLATE)
        self.assertIn("path.startsWith('item/')", TEMPLATE)

    def test_legacy_item_hash_is_supported(self):
        self.assertIn("papers.some(paper => paper.slug === path)", TEMPLATE)

    def test_reader_returns_to_owning_view(self):
        self.assertIn("returnHash = routeHash()", TEMPLATE)
        self.assertIn("history.pushState(null, '', returnHash)", TEMPLATE)

    def test_library_filter_state_is_hash_encoded(self):
        self.assertIn("new URLSearchParams()", TEMPLATE)
        self.assertIn("params.set('sort', sortSelect.value)", TEMPLATE)
        self.assertIn("#view/library${params.size", TEMPLATE)


if __name__ == "__main__":
    unittest.main()

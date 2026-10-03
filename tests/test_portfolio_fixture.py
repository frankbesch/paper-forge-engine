"""Determinism checks for the seeded 500-item console fixture."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "portfolio-500" / "items.json"


class PortfolioFixtureTests(unittest.TestCase):
    def test_fixture_has_500_unique_items(self):
        items = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(len(items), 500)
        self.assertEqual(len({item["itemId"] for item in items}), 500)

    def test_generator_reproduces_committed_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                ["python3", str(ROOT / "scripts" / "generate_portfolio_fixture.py"), "--output", directory, "--as-of", "2026-09-04"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            regenerated = Path(directory) / "items.json"
            self.assertEqual(regenerated.read_bytes(), FIXTURE.read_bytes())


if __name__ == "__main__":
    unittest.main()

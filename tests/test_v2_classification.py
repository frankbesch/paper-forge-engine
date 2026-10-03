"""PR1 evidence-class mapping and gold-sheet contracts."""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "tests" / "fixtures" / "library"


class EvidenceClassMappingTests(unittest.TestCase):
    def test_every_current_work_type_maps_to_a_controlled_class(self):
        taxonomy = json.loads((ROOT / "config" / "taxonomy.json").read_text(encoding="utf-8"))
        proposal = json.loads((ROOT / "config" / "evidence-class-map.json").read_text(encoding="utf-8"))
        mapping = proposal["work_type_to_evidence_class"]
        work_types = {
            json.loads(path.read_text(encoding="utf-8"))["work_type"]
            for path in (LIBRARY / "papers").glob("*/metadata.json")
        }
        self.assertEqual(proposal["status"], "approved")
        self.assertRegex(proposal["approved_on"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(proposal["approved_by"], "Alex")
        self.assertTrue(work_types)
        self.assertLessEqual(work_types, set(mapping))
        self.assertLessEqual(set(mapping.values()), set(taxonomy["evidence_classes"]))

    def test_portfolio_uses_a_seven_day_cadence(self):
        portfolio = json.loads((ROOT / "config" / "portfolio.json").read_text(encoding="utf-8"))
        self.assertEqual(portfolio["review_cadence"]["interval_days"], 7)


if __name__ == "__main__":
    unittest.main()

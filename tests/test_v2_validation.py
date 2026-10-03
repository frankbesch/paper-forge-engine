"""PR1 validator rules for taxonomy, state, and safety."""

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validate_v2", ROOT / "scripts" / "validate_v2.py")
validate_v2 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validate_v2)


class ValidationRuleTests(unittest.TestCase):
    def metadata(self, provenance="verified"):
        return {"item_id": "PF-0001", "provenance_status": provenance}

    def test_exported_and_measured_states_are_rejected(self):
        for state in validate_v2.DERIVED_STATES:
            errors = []
            assessment = self.temp / "assessment.json"
            assessment.write_text(f'{{"item_id":"PF-0001","application_state":"{state}"}}')
            validate_v2.validate_assessment(assessment, self.metadata(), errors)
            self.assertTrue(any("derive from ledgers" in error for error in errors))

    def test_security_validation_requires_threat_review(self):
        errors = []
        assessment = self.temp / "assessment.json"
        assessment.write_text('{"item_id":"PF-0001","application_state":"validated","safety_flags":["security"]}')
        validate_v2.validate_assessment(assessment, self.metadata(), errors)
        self.assertTrue(any("threat_review" in error for error in errors))

    def test_health_apply_requires_evidence_and_human(self):
        errors = []
        assessment = self.temp / "assessment.json"
        assessment.write_text('{"item_id":"PF-0001","disposition":{"value":"Apply"},"assessor":"Claude","safety_flags":["health"],"general":{}}')
        validate_v2.validate_assessment(assessment, self.metadata(), errors)
        self.assertTrue(any("evidence_quality >= 3" in error for error in errors))
        self.assertTrue(any("human reviewer" in error for error in errors))

    def test_portfolio_requires_lowercase_export_target_keys(self):
        config = self.temp / "config"
        config.mkdir()
        portfolio = {
            "review_cadence": {"interval_days": 7},
            "allowed_export_targets": ["Notes", "Projects"],
            "endeavors": {
                key: {"active": True, "allowed_export_targets": ["Notes"]}
                for key in ("one", "two", "three", "four", "five")
            },
        }
        (config / "portfolio.json").write_text(json.dumps(portfolio), encoding="utf-8")
        errors = []
        validate_v2.validate_portfolio(self.temp, errors)
        self.assertTrue(any("lowercase keys" in error for error in errors))

    def setUp(self):
        import tempfile
        self._temporary = tempfile.TemporaryDirectory()
        self.temp = Path(self._temporary.name)

    def tearDown(self):
        self._temporary.cleanup()


if __name__ == "__main__":
    unittest.main()

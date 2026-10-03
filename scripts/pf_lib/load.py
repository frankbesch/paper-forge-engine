"""Read and validate repository records for the library builder."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .learning import validate_learning
from .ledger import approvals_path, derive_states, exports_path, outcomes_path, read_ledger


STAGES = [
    ("read", "Read", "01-read.md"),
    ("understand", "Understand", "02-understand.md"),
    ("analyze", "Analyze", "03-analyze.md"),
    ("reproduce", "Reproduce", "04-reproduce.md"),
    ("experiment", "Experiment", "05-experiment.md"),
    ("extend", "Extend", "06-extend.md"),
    ("discover", "Discover", "07-discover.md"),
]


def load_taxonomy(root: Path) -> dict:
    return json.loads((root / "config" / "taxonomy.json").read_text(encoding="utf-8"))


def load_portfolio(root: Path) -> dict:
    return json.loads((root / "config" / "portfolio.json").read_text(encoding="utf-8"))


def load_fixture(path: Path) -> list[dict]:
    """Load a generated console-payload fixture without changing live records."""
    fixture_file = path / "items.json"
    payload = json.loads(fixture_file.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit(f"{fixture_file}: expected a JSON array")
    return payload


def load_repository(root: Path) -> list[dict]:
    """Load registry rows and their referenced workbook files in registry order."""
    taxonomy = load_taxonomy(root)
    allowed_topics = set(taxonomy["topics"])
    with (root / "papers" / "index.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    exports = read_ledger(exports_path(root))
    outcomes = read_ledger(outcomes_path(root))
    approvals = read_ledger(approvals_path(root))
    derived = derive_states(exports, outcomes, approvals)
    records = []
    for number, original_row in enumerate(rows, start=1):
        row = dict(original_row)
        row["number"] = str(number)
        slug = row["slug"]
        paper_dir = root / "papers" / slug
        metadata = json.loads((paper_dir / "metadata.json").read_text(encoding="utf-8"))
        learning_errors = validate_learning(metadata)
        if learning_errors:
            raise SystemExit(f"{slug}: {'; '.join(learning_errors)}")
        readme = (paper_dir / "README.md").read_text(encoding="utf-8")
        topics = metadata.get("topics") or ["Unclassified"]
        unknown = sorted(set(topics) - allowed_topics)
        if unknown:
            raise SystemExit(f"{slug}: topics not in config/taxonomy.json: {unknown}")
        work_documents = []
        for key, label, filename in STAGES:
            path = paper_dir / "work" / filename
            work_documents.append({
                "key": key,
                "label": label,
                "filename": filename,
                "content": path.read_text(encoding="utf-8"),
            })
        assessment_path = paper_dir / "assessment.json"
        assessment = (
            json.loads(assessment_path.read_text(encoding="utf-8"))
            if assessment_path.exists()
            else None
        )
        if assessment and assessment.get("assessment_version") == 2:
            from .assessment import validate_document
            errors = validate_document(assessment, metadata, load_portfolio(root))
            if errors:
                raise SystemExit(f"{slug}: {'; '.join(errors)}")
        records.append({
            "root": root,
            "row": row,
            "paper_dir": paper_dir,
            "metadata": metadata,
            "readme": readme,
            "work_documents": work_documents,
            "assessment": assessment,
            "transfer": derived.get(metadata.get("item_id"), {"application_state": None, "exports": [], "outcomes": []}),
        })
    return records

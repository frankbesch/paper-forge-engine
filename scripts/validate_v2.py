#!/usr/bin/env python3
"""Validate Paper Forge v2 PR1 contracts and future assessment safety rules."""

from __future__ import annotations

import argparse
import os
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pf_lib import assessment as assessment_contract  # noqa: E402
from pf_lib import ledger as ledger_contract  # noqa: E402
from pf_lib import learning as learning_contract  # noqa: E402


ROOT = Path(os.environ.get("PF_ROOT") or Path(__file__).resolve().parents[1])
CAPTURE_SURFACES = {"claude-code", "claude-ai", "chatgpt", "codex", "manual"}
PROVENANCE = {"verified", "partial", "unverified", "failed"}
DECLINE_REASONS = {"duplicate", "low-value", "off-scope", "unverifiable", "already-captured"}
SAFETY_FLAGS = {"security", "health", "financial", "employment"}
STORED_STATES = {"unassessed", "candidate", "testing", "validated", "held", "retired", "rejected"}
DERIVED_STATES = {"exported", "measured"}
COMPLETE_DISPOSITIONS = {"Apply", "Test"}
REQUIRED_SCORES = {"evidence_quality", "actionability", "implementation_effort", "downside_risk"}


def load_json(path: Path, errors: list[str]) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"{path}: invalid JSON: {error}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path}: root must be an object")
        return None
    return value


def checksum_matches(metadata_path: Path, source: dict) -> bool:
    relative = source.get("source_file") or source.get("file")
    recorded = source.get("sha256")
    if not relative or not recorded:
        return False
    path = metadata_path.parent / relative
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == recorded


def disposition_value(assessment: dict) -> str | None:
    disposition = assessment.get("disposition")
    return disposition.get("value") if isinstance(disposition, dict) else disposition


def score_value(assessment: dict, key: str):
    value = (assessment.get("general") or {}).get(key)
    return value.get("score") if isinstance(value, dict) else value


def human_reviewer(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip().lower()
    return normalized not in {"ai", "claude", "claude code", "codex", "chatgpt"}


def validate_portfolio(root: Path, errors: list[str]) -> None:
    path = root / "config" / "portfolio.json"
    data = load_json(path, errors)
    if data is None:
        return
    cadence = data.get("review_cadence") or {}
    if not isinstance(cadence.get("interval_days"), int) or cadence["interval_days"] < 1:
        errors.append(f"{path}: review_cadence.interval_days must be a positive integer")
    targets = data.get("allowed_export_targets")
    if not isinstance(targets, list) or not targets or any(not isinstance(value, str) for value in targets):
        errors.append(f"{path}: allowed_export_targets must be a non-empty string list")
        targets = []
    elif any(not t or t != t.lower() for t in targets):
        errors.append(f"{path}: allowed_export_targets must be lowercase keys")
    endeavors = data.get("endeavors")
    if not isinstance(endeavors, dict) or not endeavors:
        errors.append(f"{path}: at least one endeavor is required")
        return
    for key, endeavor in endeavors.items():
        if not isinstance(endeavor, dict) or endeavor.get("active") is not True:
            errors.append(f"{path}: endeavor {key} must be active")
            continue
        if "safety_class" in endeavor:
            errors.append(f"{path}: endeavor {key} cannot define safety_class")
        allowed = endeavor.get("allowed_export_targets")
        if not isinstance(allowed, list) or not allowed or not set(allowed) <= set(targets):
            errors.append(f"{path}: endeavor {key} has invalid export targets")


def validate_assessment(path: Path, metadata: dict, errors: list[str]) -> None:
    """Full assessment contract (pf_lib.assessment). Portfolio is optional so unit tests can run in a bare temp root."""
    assessment = load_json(path, errors)
    if assessment is None:
        return
    portfolio = None
    portfolio_path = path.parents[2] / "config" / "portfolio.json" if len(path.parents) > 2 else None
    if portfolio_path and portfolio_path.is_file():
        try:
            portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            portfolio = None
    errors.extend(assessment_contract.validate_document(assessment, metadata, portfolio, str(path)))


def validate_intake(root: Path, errors: list[str]) -> None:
    path = root / "ledger" / "intake.jsonl"
    if not path.exists():
        return  # a new library has no declines yet; capture --decline creates the file
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            receipt = json.loads(line)
        except json.JSONDecodeError as error:
            errors.append(f"{path}:{number}: invalid JSON: {error.msg}")
            continue
        if not isinstance(receipt, dict):
            errors.append(f"{path}:{number}: receipt must be an object")
            continue
        if receipt.get("reason") not in DECLINE_REASONS:
            errors.append(f"{path}:{number}: invalid decline reason")
        if receipt.get("surface") not in CAPTURE_SURFACES:
            errors.append(f"{path}:{number}: invalid capture surface")
        try:
            date.fromisoformat(receipt.get("date", ""))
        except (TypeError, ValueError):
            errors.append(f"{path}:{number}: date must be ISO-8601")
        identifiers = [key for key in ("url", "content_hash") if receipt.get(key)]
        if len(identifiers) != 1:
            errors.append(f"{path}:{number}: exactly one URL or content hash is required")
        if receipt.get("content_hash") and (
            not isinstance(receipt["content_hash"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", receipt["content_hash"])
        ):
            errors.append(f"{path}:{number}: invalid content hash")


def validate_repository(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    taxonomy_path = root / "config" / "taxonomy.json"
    taxonomy = load_json(taxonomy_path, errors) or {}
    topics_allowed = set(taxonomy.get("topics") or [])
    evidence_allowed = set(taxonomy.get("evidence_classes") or [])
    validate_portfolio(root, errors)
    metadata_records = []
    item_ids = set()
    for path in sorted((root / "papers").glob("*/metadata.json")):
        metadata = load_json(path, errors)
        if metadata is None:
            continue
        metadata_records.append((path, metadata))
        errors.extend(f"{path}: {error}" for error in learning_contract.validate_learning(metadata))
        item_id = metadata.get("item_id")
        item_ids.add(item_id)
        topics = metadata.get("topics")
        if not isinstance(topics, list) or not topics or any(not isinstance(topic, str) for topic in topics):
            errors.append(f"{path}: topics must be a non-empty list")
        elif not set(topics) <= topics_allowed:
            errors.append(f"{path}: topics contains an uncontrolled value")
        elif "Unclassified" in topics and topics != ["Unclassified"]:
            errors.append(f"{path}: Unclassified must be the only topic")
        evidence_class = metadata.get("evidence_class")
        if evidence_class is not None and evidence_class not in evidence_allowed:
            errors.append(f"{path}: invalid evidence_class {evidence_class!r}")
        if metadata.get("captured_via") not in CAPTURE_SURFACES:
            errors.append(f"{path}: invalid captured_via")
        provenance = metadata.get("provenance_status")
        if provenance not in PROVENANCE:
            errors.append(f"{path}: invalid provenance_status")
        sources = metadata.get("sources") or []
        if provenance == "verified" and (not sources or not all(checksum_matches(path, source) for source in sources)):
            errors.append(f"{path}: verified provenance requires matching recorded checksums")
        relations = metadata.get("relations")
        if not isinstance(relations, list):
            errors.append(f"{path}: relations must be a list")
        assessment = path.parent / "assessment.json"
        if assessment.exists():
            validate_assessment(assessment, metadata, errors)
    for path, metadata in metadata_records:
        assessment_path = path.parent / "assessment.json"
        if assessment_path.exists():
            doc = load_json(assessment_path, errors) or {}
            recommendation = doc.get("recommendation")
            if isinstance(recommendation, dict) and isinstance(recommendation.get("applications"), list):
                for app in recommendation["applications"]:
                    if isinstance(app, dict) and isinstance(app.get("item_ids"), list):
                        for item_id in app["item_ids"]:
                            if not isinstance(item_id, str) or item_id not in item_ids:
                                errors.append(f"{assessment_path}: application references unknown item {item_id!r}")
        for relation in metadata.get("relations") or []:
            if not isinstance(relation, dict) or not relation.get("type"):
                errors.append(f"{path}: relation must have a type")
            elif (relation.get("item_id") or relation.get("target")) not in item_ids:
                errors.append(f"{path}: relation target must be a stable existing item_id")
    map_path = root / "config" / "evidence-class-map.json"
    mapping_data = load_json(map_path, errors) or {}
    mapping = mapping_data.get("work_type_to_evidence_class") or {}
    if not isinstance(mapping, dict):
        errors.append(f"{map_path}: work_type_to_evidence_class must be an object")
        mapping = {}
    work_types = {metadata.get("work_type") for _, metadata in metadata_records}
    unmapped = sorted(w for w in work_types - set(mapping) if w)
    if unmapped:
        errors.append(f"{map_path}: work types without a mapping: {unmapped}")
    if not set(mapping.values()) <= evidence_allowed:
        errors.append(f"{map_path}: mapping contains an uncontrolled evidence class")
    mapping_status = mapping_data.get("status")
    if mapping_status not in {"proposed", "approved"}:
        errors.append(f"{map_path}: status must be proposed or approved")
    missing_evidence = sum(metadata.get("evidence_class") is None for _, metadata in metadata_records)
    if mapping_status == "approved":
        for path, metadata in metadata_records:
            expected = mapping.get(metadata.get("work_type"))
            if metadata.get("evidence_class") != expected:
                errors.append(f"{path}: evidence_class does not match the approved mapping")
    elif missing_evidence:
        warnings.append(f"evidence_class deferred pending the approver's ruling: {missing_evidence} items")
    validate_intake(root, errors)
    ledger_contract.validate_ledgers(root, {i for i in item_ids if i}, errors)
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Library root (default: PF_ROOT or this repository)")
    args = parser.parse_args(argv)
    errors, warnings = validate_repository(args.root.resolve())
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"Paper Forge v2 validation: {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

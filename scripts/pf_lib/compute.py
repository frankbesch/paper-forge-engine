"""Compute view-only fields without persisting them to repository records."""

from __future__ import annotations

import datetime as dt
import re

from .assessment import safety_gate
from .load import STAGES


def route_label(selected: list[str]) -> str:
    selected_set = set(selected)
    if selected_set & {"experiment", "extend", "discover"}:
        return "Develop"
    if "reproduce" in selected_set:
        return "Verify"
    if "analyze" in selected_set:
        return "Critique"
    if "understand" in selected_set:
        return "Interpret"
    return "Capture"


def access_label(metadata: dict, primary: dict) -> str:
    if metadata.get("access_label"):
        return metadata["access_label"]
    scope = (primary.get("access_scope") or metadata.get("access_scope") or "").lower()
    source_file = primary.get("source_file") or metadata.get("source_file", "")
    if "gated" in scope:
        return "Limited access"
    if source_file.lower().endswith(".pdf"):
        return "Local PDF"
    if primary.get("canonical_url") or metadata.get("canonical_url"):
        return "Full web"
    return "Local source"


def stage_statuses(readme: str, selected: list[str], skipped: list[str]) -> dict[str, str]:
    statuses = {}
    for key, label, _ in STAGES:
        match = re.search(
            rf"^\|\s*{re.escape(label)}\s*\|\s*([a-z_]+)\s*\|",
            readme,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        if match:
            statuses[key] = match.group(1).lower()
        elif key in skipped:
            statuses[key] = "skipped"
        else:
            statuses[key] = "not_started"
    return statuses


def freshness(review_by: str | None, as_of: str) -> dict:
    as_of_date = dt.date.fromisoformat(as_of)
    if not review_by:
        return {"as_of": as_of, "review_by": None, "status": "unknown"}
    review_date = dt.date.fromisoformat(review_by)
    return {
        "as_of": as_of,
        "review_by": review_by,
        "status": "stale" if review_date < as_of_date else "current",
    }


def compute_record(record: dict, as_of: str) -> dict:
    statuses = stage_statuses(record["readme"], record["selected"], record["skipped"])
    documents = []
    for document in record["documents"]:
        computed = dict(document)
        if computed["key"] != "overview":
            computed["status"] = statuses[computed["key"]]
        documents.append(computed)
    assessment = record.get("assessment") or {}
    review_by = (assessment.get("freshness") or {}).get("review_by")
    return {
        **record,
        "route_label": route_label(record["selected"]),
        "access_label": access_label(record["metadata"], record["primary"]),
        "statuses": statuses,
        "freshness": freshness(review_by, as_of),
        "safety": safety_gate(record.get("assessment"), record["metadata"]),
        "documents": documents,
    }


def compute_records(records: list[dict], as_of: str) -> list[dict]:
    return [compute_record(record, as_of) for record in records]

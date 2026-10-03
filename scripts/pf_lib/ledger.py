"""Append-only transfer ledgers: export and outcome receipts.

Paper Forge exports evidence packages, never commands. The console reads these files and
derives `exported` and `measured`; nothing here writes to an export target.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path


EXPORT_PREFIX = "PFX"
OUTCOME_PREFIX = "PFO"
APPROVAL_PREFIX = "PFD"
DEFAULT_TARGETS = {"notes", "projects"}  # used only when config/portfolio.json names none
CONFIDENCE = {"low", "medium", "high"}
APPROVAL = {"pending", "approved", "declined"}
DECISIONS = {"approved", "declined"}
APPROVAL_FIELDS = {"receipt_id", "export_id", "decision", "decided", "decided_by", "reason"}
EXPORT_FIELDS = {
    "receipt_id", "item_ids", "target", "repo_path", "commit", "record_id", "recommendation",
    "evidence_boundary", "confidence", "exported", "approval_status", "outcome_status", "package",
}
OUTCOME_FIELDS = {
    "receipt_id", "export_id", "observation_period", "expected_outcome", "observed_outcome",
    "measurement_method", "uncertainty", "source_artifacts", "assessment_change", "recorded",
}
ABSOLUTE = re.compile(r'^(/|~|[A-Za-z]:\\|file://)')


def configured_targets(root: Path) -> set[str]:
    """Export targets from config/portfolio.json allowed_export_targets."""
    try:
        data = json.loads((root / "config" / "portfolio.json").read_text(encoding="utf-8"))
        targets = data.get("allowed_export_targets")
        if isinstance(targets, list) and targets:
            return {str(t) for t in targets}
    except (OSError, ValueError):
        pass
    return set(DEFAULT_TARGETS)


def exports_path(root: Path) -> Path:
    return root / "ledger" / "exports.jsonl"


def outcomes_path(root: Path) -> Path:
    return root / "ledger" / "outcomes.jsonl"


def approvals_path(root: Path) -> Path:
    return root / "ledger" / "approvals.jsonl"


def latest_decisions(approvals: list[dict]) -> dict[str, dict]:
    """export_id -> the last decision receipt appended for it (latest wins; nothing is rewritten)."""
    latest: dict[str, dict] = {}
    for decision in approvals:
        export_id = decision.get("export_id")
        if export_id:
            latest[export_id] = decision
    return latest


def effective_approval(export: dict, latest: dict[str, dict]) -> str:
    decision = latest.get(export.get("receipt_id"))
    if decision and decision.get("decision") in DECISIONS:
        return decision["decision"]
    return export.get("approval_status")


def with_effective_approval(exports: list[dict], approvals: list[dict]) -> list[dict]:
    """Copies of the export receipts with approval_status replaced by the effective (latest-decision) value."""
    latest = latest_decisions(approvals)
    resolved = []
    for export in exports:
        copy = dict(export)
        copy["approval_status"] = effective_approval(export, latest)
        resolved.append(copy)
    return resolved


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def next_receipt_id(entries: list[dict], prefix: str) -> str:
    highest = 0
    for entry in entries:
        match = re.fullmatch(rf"{prefix}-(\d{{4,}})", str(entry.get("receipt_id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}-{highest + 1:04d}"


def append_entry(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")


def _is_iso(value) -> bool:
    try:
        dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


def _absolute_paths(value, trail="") -> list[str]:
    found = []
    if isinstance(value, str):
        if ABSOLUTE.match(value.strip()):
            found.append(trail or "<root>")
    elif isinstance(value, dict):
        for key, child in value.items():
            found.extend(_absolute_paths(child, f"{trail}.{key}" if trail else key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_absolute_paths(child, f"{trail}[{index}]"))
    return found


def _check_ids(entries: list[dict], prefix: str, label: str, errors: list[str]) -> None:
    seen = set()
    last = 0
    for number, entry in enumerate(entries, start=1):
        receipt_id = str(entry.get("receipt_id", ""))
        match = re.fullmatch(rf"{prefix}-(\d{{4,}})", receipt_id)
        if not match:
            errors.append(f"{label}:{number}: receipt_id must look like {prefix}-0001")
            continue
        value = int(match.group(1))
        if receipt_id in seen:
            errors.append(f"{label}:{number}: duplicate receipt_id {receipt_id}")
        if value <= last:
            errors.append(f"{label}:{number}: receipt ids must increase ({receipt_id} after {prefix}-{last:04d})")
        seen.add(receipt_id)
        last = max(last, value)


def validate_ledgers(root: Path, item_ids: set[str], errors: list[str]) -> None:
    targets = configured_targets(root)
    exports = read_ledger_safely(exports_path(root), errors)
    outcomes = read_ledger_safely(outcomes_path(root), errors)
    approvals = read_ledger_safely(approvals_path(root), errors)
    label_x = "ledger/exports.jsonl"
    label_o = "ledger/outcomes.jsonl"
    label_a = "ledger/approvals.jsonl"
    _check_ids(exports, EXPORT_PREFIX, label_x, errors)
    _check_ids(outcomes, OUTCOME_PREFIX, label_o, errors)
    _check_ids(approvals, APPROVAL_PREFIX, label_a, errors)
    export_ids = set()
    for number, entry in enumerate(exports, start=1):
        export_ids.add(entry.get("receipt_id"))
        missing = sorted(EXPORT_FIELDS - set(entry))
        extra = sorted(set(entry) - EXPORT_FIELDS - {"application"})
        if missing:
            errors.append(f"{label_x}:{number}: missing {missing}")
        if extra:
            errors.append(f"{label_x}:{number}: unknown fields {extra}")
        if not isinstance(entry.get("item_ids"), list) or not entry.get("item_ids") or not set(entry["item_ids"]) <= item_ids:
            errors.append(f"{label_x}:{number}: item_ids must name existing items")
        if entry.get("target") not in targets:
            errors.append(f"{label_x}:{number}: target must be one of {sorted(targets)}")
        if entry.get("confidence") not in CONFIDENCE:
            errors.append(f"{label_x}:{number}: confidence must be low, medium, or high")
        if entry.get("approval_status") not in APPROVAL:
            errors.append(f"{label_x}:{number}: approval_status must be pending, approved, or declined")
        if not _is_iso(entry.get("exported")):
            errors.append(f"{label_x}:{number}: exported must be an ISO-8601 date")
        for field in ("recommendation", "evidence_boundary"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                errors.append(f"{label_x}:{number}: {field} is required")
        package = entry.get("package")
        if not isinstance(package, str) or not (root / package).is_file():
            errors.append(f"{label_x}:{number}: package file {package!r} is missing")
        if "application" in entry:
            from .intake import validate_application
            app = entry["application"]
            errors.extend(f"{label_x}:{number}: {e}" for e in validate_application(app, (entry.get("item_ids") or [None])[0], targets | {"paper-forge"}))
            if isinstance(app, dict) and (app.get("destination") != entry.get("target") or app.get("project_path") != entry.get("repo_path") or app.get("item_ids") != entry.get("item_ids")):
                errors.append(f"{label_x}:{number}: application routing differs from receipt")
        for where in _absolute_paths(entry):
            errors.append(f"{label_x}:{number}: absolute path in {where}")
    for number, entry in enumerate(outcomes, start=1):
        missing = sorted(OUTCOME_FIELDS - set(entry))
        extra = sorted(set(entry) - OUTCOME_FIELDS)
        if missing:
            errors.append(f"{label_o}:{number}: missing {missing}")
        if extra:
            errors.append(f"{label_o}:{number}: unknown fields {extra}")
        if not isinstance(entry.get("export_id"), str) or entry["export_id"] not in export_ids:
            errors.append(f"{label_o}:{number}: export_id must reference an existing export receipt")
        period = entry.get("observation_period")
        if not isinstance(period, dict) or not _is_iso(period.get("start")) or not _is_iso(period.get("end")):
            errors.append(f"{label_o}:{number}: observation_period needs ISO start and end")
        for field in ("expected_outcome", "observed_outcome", "measurement_method", "uncertainty"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                errors.append(f"{label_o}:{number}: {field} is required")
        if not _is_iso(entry.get("recorded")):
            errors.append(f"{label_o}:{number}: recorded must be an ISO-8601 date")
        if not isinstance(entry.get("source_artifacts"), list):
            errors.append(f"{label_o}:{number}: source_artifacts must be a list")
        for where in _absolute_paths(entry):
            errors.append(f"{label_o}:{number}: absolute path in {where}")
    for number, entry in enumerate(approvals, start=1):
        missing = sorted(APPROVAL_FIELDS - set(entry))
        extra = sorted(set(entry) - APPROVAL_FIELDS)
        if missing:
            errors.append(f"{label_a}:{number}: missing {missing}")
        if extra:
            errors.append(f"{label_a}:{number}: unknown fields {extra}")
        if not isinstance(entry.get("export_id"), str) or entry["export_id"] not in export_ids:
            errors.append(f"{label_a}:{number}: export_id must reference an existing export receipt")
        if not isinstance(entry.get("decision"), str) or entry["decision"] not in DECISIONS:
            errors.append(f"{label_a}:{number}: decision must be approved or declined")
        if not _is_iso(entry.get("decided")):
            errors.append(f"{label_a}:{number}: decided must be an ISO-8601 date")
        if not isinstance(entry.get("decided_by"), str) or not entry["decided_by"].strip():
            errors.append(f"{label_a}:{number}: decided_by is required")
        reason = entry.get("reason")
        if reason is not None and not isinstance(reason, str):
            errors.append(f"{label_a}:{number}: reason must be a string or null")
        if entry.get("decision") == "declined" and not (isinstance(reason, str) and reason.strip()):
            errors.append(f"{label_a}:{number}: a decline needs a reason")
        for where in _absolute_paths(entry):
            errors.append(f"{label_a}:{number}: absolute path in {where}")


def read_ledger_safely(path: Path, errors: list[str]) -> list[dict]:
    entries = []
    if not path.exists():
        return entries
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            errors.append(f"{path.name}:{number}: invalid JSON: {error.msg}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{path.name}:{number}: receipt must be an object")
            continue
        entries.append(value)
    return entries


def derive_states(exports: list[dict], outcomes: list[dict], approvals: list[dict] | None = None) -> dict[str, dict]:
    """item_id -> {application_state|None, exports[], outcomes[]}. None means: keep the stored state.

    Approval is the effective value: the latest PFD decision for the export, else the export's own field."""
    if approvals:
        exports = with_effective_approval(exports, approvals)
    by_item: dict[str, dict] = {}
    outcomes_by_export: dict[str, list[dict]] = {}
    for outcome in outcomes:
        outcomes_by_export.setdefault(outcome.get("export_id"), []).append(outcome)
    for export in exports:
        for item_id in export.get("item_ids") or []:
            entry = by_item.setdefault(item_id, {"application_state": None, "exports": [], "outcomes": []})
            entry["exports"].append(export)
            linked = outcomes_by_export.get(export.get("receipt_id"), [])
            entry["outcomes"].extend(linked)
            if export.get("approval_status") == "approved":
                entry["application_state"] = "measured" if linked else ("exported" if entry["application_state"] != "measured" else "measured")
    return by_item


def compact_export(export: dict, outcomes: list[dict]) -> dict:
    linked = [o for o in outcomes if o.get("export_id") == export.get("receipt_id")]
    return {
        "id": export.get("receipt_id"),
        "target": export.get("target"),
        "date": export.get("exported"),
        "approval": export.get("approval_status"),
        "recordId": export.get("record_id"),
        "package": export.get("package"),
        "recommendation": export.get("recommendation"),
        "outcomeCount": len(linked),
    }


def compact_outcome(outcome: dict) -> dict:
    period = outcome.get("observation_period") or {}
    return {
        "id": outcome.get("receipt_id"),
        "exportId": outcome.get("export_id"),
        "recorded": outcome.get("recorded"),
        "period": f"{period.get('start', '?')} to {period.get('end', '?')}",
        "observed": outcome.get("observed_outcome"),
        "uncertainty": outcome.get("uncertainty"),
        "assessmentChange": outcome.get("assessment_change"),
    }


def render_approval_note(decision: dict) -> str:
    """Dated section appended to an export package; earlier text is never rewritten (contract rule 8)."""
    lines = [
        "",
        f"## Approval — {decision['decided']} ({decision['receipt_id']})",
        "",
        f"Decision: **{decision['decision']}** by {decision['decided_by']}.",
    ]
    if decision.get("reason"):
        lines.append(f"Reason: {decision['reason']}")
    lines.append("")
    return "\n".join(lines)


def render_package(receipt: dict, items: list[dict]) -> str:
    """Source-backed export package. Every claim cites item IDs; the receiving system owns execution."""
    lines = [
        f"# Export package {receipt['receipt_id']} → {receipt['target']}",
        "",
        f"Exported {receipt['exported']} from Paper Forge commit `{receipt['commit']}`. Approval: {receipt['approval_status']}. Confidence: {receipt['confidence']}.",
        "",
        "This is an evidence package, not a command. The receiving system owns all resulting execution state; Paper Forge keeps only this receipt.",
        "",
        "## Recommendation",
        "",
        receipt["recommendation"],
        "",
        "## Evidence boundary",
        "",
        receipt["evidence_boundary"],
        "",
        "## Cited items",
        "",
    ]
    if receipt.get("application"):
        app = receipt["application"]
        lines += ["## Application", "", f"Purpose: {app['purpose']}",
            f"Artifact: {app['artifact_type']}", f"Owning path: {app['project_path']}",
            f"Success check: {app['success_check']}", f"Limits: {app['evidence_limits']}", ""]
    for item in items:
        sources = item.get("sources") or []
        digest = sources[0].get("sha256", "") if sources else ""
        title = (item.get("identity") or {}).get("title") or item.get("title") or item.get("item_id")
        assessment = item.get("_assessment") or {}
        disposition = assessment.get("disposition") or {}
        value = disposition.get("value") if isinstance(disposition, dict) else disposition
        scores = assessment.get("general") or {}
        evidence = (scores.get("evidence_quality") or {}).get("score") if isinstance(scores.get("evidence_quality"), dict) else None
        lines.append(f"- `{item.get('item_id')}` {title} — disposition {value or 'unassessed'}; evidence quality {evidence if evidence is not None else '–'}/4; sha256 `{digest[:16]}…`; workbook `papers/{item.get('slug')}/README.md`")
    lines += [
        "",
        "## Receiving-system reference",
        "",
        f"- target: `{receipt['target']}`",
        f"- repository-relative path: `{receipt['repo_path'] or '(unset)'}`",
        f"- record id: `{receipt['record_id'] or '(none yet)'}`",
        "",
        "Outcome receipts for this export are recorded with `pf.py outcome " + receipt["receipt_id"] + " …`.",
        "",
    ]
    return "\n".join(lines)

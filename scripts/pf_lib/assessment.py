"""Assessment contract: schema, validation, safety gating, and revision.

The builder never writes assessments. `pf.py assess` writes them; `validate_v2.py` checks them;
`compute.py` applies `safety_gate` so a gated item never renders as Apply.

Disposition judgment (which value fits) follows the ordered rulebook below
(ruled 2026-09-11); this module validates shape and gates only and does not encode that judgment.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path


ASSESSMENT_VERSION = 1
DIMENSIONS = [
    "evidence_quality",
    "novelty",
    "actionability",
    "durability",
    "implementation_effort",
    "downside_risk",
    "urgency",
]
DISPOSITIONS = {"Apply", "Test", "Learn", "Watch", "Reference", "Hold", "Retire", "Reject"}
CONFIDENCE = {"low", "medium", "high"}
STATUSES = {"assessed", "declined", "pending", "draft", "failed"}
SAFETY_FLAGS = {"security", "health", "financial", "employment"}
STORED_STATES = {"unassessed", "candidate", "testing", "validated", "held", "retired", "rejected"}
DERIVED_STATES = {"exported", "measured"}
COMPLETE_DISPOSITIONS = {"Apply", "Test"}
REQUIRED_SCORES = {"evidence_quality", "actionability", "implementation_effort", "downside_risk"}
ENDEAVOR_FIELDS = {"relevance", "expected_leverage", "confidence", "use_case", "suggested_next_action", "owner"}
EXTRA_OWNERS = {"owner", "paper-forge"}
TOP_LEVEL_KEYS = {
    "assessment_version", "item_id", "status", "assessed_at", "assessor", "disposition", "general",
    "endeavors", "safety_flags", "threat_review", "freshness", "application_state", "revision",
    "history", "notes", "intake", "recommendation",
}
REQUIRED_TOP_LEVEL = TOP_LEVEL_KEYS - {"threat_review", "notes", "intake", "recommendation"}
NON_HUMAN = {"ai", "claude", "claude code", "codex", "chatgpt", "agent", "assistant"}
FORBIDDEN_KEYS = {"priority", "priority_score", "score_total"}


def is_iso_date(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def human_reviewer(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return value.strip().lower() not in NON_HUMAN


def disposition_value(assessment: dict):
    disposition = assessment.get("disposition")
    return disposition.get("value") if isinstance(disposition, dict) else disposition


def score_value(assessment: dict, key: str):
    value = (assessment.get("general") or {}).get(key)
    return value.get("score") if isinstance(value, dict) else value


def empty_assessment(item_id: str, assessor: str, assessed_at: str, endeavor_keys=()) -> dict:
    """A null-scored draft. Nothing here is a judgment."""
    return {
        "assessment_version": ASSESSMENT_VERSION,
        "item_id": item_id,
        "status": "assessed",
        "assessed_at": assessed_at,
        "assessor": assessor,
        "disposition": {"value": None, "rationale": None},
        "general": {key: {"score": None, "rationale": None} for key in DIMENSIONS},
        "endeavors": {
            key: {
                "relevance": None,
                "expected_leverage": None,
                "confidence": None,
                "use_case": None,
                "suggested_next_action": None,
                "owner": None,
            }
            for key in endeavor_keys
        },
        "safety_flags": [],
        "freshness": {"as_of": assessed_at, "review_by": None},
        "application_state": "unassessed",
        "revision": 1,
        "history": [],
    }


def _find_forbidden(value, path="") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                found.append(f"{path}/{key}".lstrip("/"))
            found.extend(_find_forbidden(child, f"{path}/{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden(child, f"{path}[{index}]"))
    return found


def _is_score(value) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 4)


def validate_document(assessment: dict, metadata: dict, portfolio: dict | None, path: str = "assessment.json") -> list[str]:
    """Return every contract violation. An empty list means the document is valid."""
    errors: list[str] = []
    if not isinstance(assessment, dict):
        return [f"{path}: root must be an object"]
    unknown = sorted(set(assessment) - TOP_LEVEL_KEYS)
    if unknown:
        errors.append(f"{path}: unknown top-level keys {unknown}")
    for key in sorted(REQUIRED_TOP_LEVEL - set(assessment)):
        errors.append(f"{path}: missing {key}")
    for forbidden in _find_forbidden(assessment):
        errors.append(f"{path}: stored score is not allowed ({forbidden}); scores are computed by the console")
    if type(assessment.get("assessment_version")) is not int or assessment.get("assessment_version") not in (1, 2):
        errors.append(f"{path}: assessment_version must be 1 or 2")
    if assessment.get("item_id") != metadata.get("item_id"):
        errors.append(f"{path}: item_id differs from sibling metadata")
    status = assessment.get("status")
    if status not in STATUSES:
        errors.append(f"{path}: status must be one of {sorted(STATUSES)}")
    if not is_iso_date(assessment.get("assessed_at")):
        errors.append(f"{path}: assessed_at must be an ISO-8601 date")
    if not isinstance(assessment.get("assessor"), str) or not assessment["assessor"].strip():
        errors.append(f"{path}: assessor is required")

    disposition = assessment.get("disposition")
    value = None
    if isinstance(disposition, dict):
        value = disposition.get("value")
        if value is None:
            if status == "assessed":
                errors.append(f"{path}: an assessed item needs a disposition value")
        elif value not in DISPOSITIONS:
            errors.append(f"{path}: invalid disposition {value!r}")
        if value is not None and (not isinstance(disposition.get("rationale"), str) or not disposition["rationale"].strip()):
            errors.append(f"{path}: disposition requires a rationale")
    elif disposition is not None:
        value = disposition
        errors.append(f"{path}: disposition must be an object with value and rationale")

    general = assessment.get("general")
    if not isinstance(general, dict):
        errors.append(f"{path}: general must be an object")
        general = {}
    for key in DIMENSIONS:
        entry = general.get(key)
        if entry is None:
            errors.append(f"{path}: general.{key} is missing")
            continue
        if not isinstance(entry, dict):
            errors.append(f"{path}: general.{key} must be an object with score and rationale")
            continue
        score = entry.get("score")
        if not _is_score(score):
            errors.append(f"{path}: general.{key}.score must be an integer 0-4 or null")
        if score is not None and (not isinstance(entry.get("rationale"), str) or not entry["rationale"].strip()):
            errors.append(f"{path}: general.{key} requires a rationale when scored")
    for key in sorted(set(general) - set(DIMENSIONS)):
        errors.append(f"{path}: general.{key} is not a known dimension")

    endeavors = assessment.get("endeavors")
    if not isinstance(endeavors, dict):
        errors.append(f"{path}: endeavors must be an object")
        endeavors = {}
    known_endeavors = (portfolio or {}).get("endeavors") if portfolio else None
    for key, fit in endeavors.items():
        if known_endeavors is not None and key not in known_endeavors:
            errors.append(f"{path}: endeavors.{key} is not a configured endeavor")
        if not isinstance(fit, dict):
            errors.append(f"{path}: endeavors.{key} must be an object")
            continue
        for field in sorted(set(fit) - ENDEAVOR_FIELDS):
            errors.append(f"{path}: endeavors.{key}.{field} is not a known field")
        for field in ("relevance", "expected_leverage"):
            if not _is_score(fit.get(field)):
                errors.append(f"{path}: endeavors.{key}.{field} must be an integer 0-4 or null")
        if fit.get("confidence") is not None and fit.get("confidence") not in CONFIDENCE:
            errors.append(f"{path}: endeavors.{key}.confidence must be low, medium, or high")
        for field in ("use_case", "suggested_next_action"):
            if fit.get(field) is not None and not isinstance(fit.get(field), str):
                errors.append(f"{path}: endeavors.{key}.{field} must be text or null")
        owner = fit.get("owner")
        if owner is not None:
            allowed = set()
            if known_endeavors and isinstance(known_endeavors.get(key), dict):
                allowed = set(known_endeavors[key].get("allowed_export_targets") or [])
            if not isinstance(owner, str) or (known_endeavors is not None and owner.lower() not in allowed | EXTRA_OWNERS):
                errors.append(f"{path}: endeavors.{key}.owner must be an allowed export target, owner, or paper-forge")

    flags = assessment.get("safety_flags", [])
    if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags) or not set(flags) <= SAFETY_FLAGS:
        errors.append(f"{path}: safety_flags contains an invalid value")
        flags = []
    review = assessment.get("threat_review")
    if review is not None and (not isinstance(review, dict) or not all(review.get(k) for k in ("date", "reviewer", "summary"))):
        errors.append(f"{path}: threat_review needs date, reviewer, and summary")

    freshness = assessment.get("freshness")
    if not isinstance(freshness, dict):
        errors.append(f"{path}: freshness must be an object")
    else:
        if not is_iso_date(freshness.get("as_of")):
            errors.append(f"{path}: freshness.as_of must be an ISO-8601 date")
        if freshness.get("review_by") is not None and not is_iso_date(freshness.get("review_by")):
            errors.append(f"{path}: freshness.review_by must be an ISO-8601 date or null")
        if "status" in freshness:
            errors.append(f"{path}: freshness.status is computed at build time and must not be stored")

    state = assessment.get("application_state")
    if state in DERIVED_STATES:
        errors.append(f"{path}: {state} must derive from ledgers")
    elif state is not None and state not in STORED_STATES:
        errors.append(f"{path}: invalid application_state {state!r}")

    revision = assessment.get("revision")
    history = assessment.get("history")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        errors.append(f"{path}: revision must be a positive integer")
    if not isinstance(history, list):
        errors.append(f"{path}: history must be a list")
    else:
        if isinstance(revision, int) and len(history) != revision - 1:
            errors.append(f"{path}: history must hold revision - 1 entries")
        for index, entry in enumerate(history):
            if not isinstance(entry, dict) or not all(k in entry for k in ("revision", "date", "author", "reason", "previous")):
                errors.append(f"{path}: history[{index}] needs revision, date, author, reason, previous")
            elif not is_iso_date(entry.get("date")):
                errors.append(f"{path}: history[{index}].date must be an ISO-8601 date")

    from .intake import validate_extension
    errors.extend(f"{path}: {error}" for error in validate_extension(assessment, metadata))

    # Completeness and safety rules.
    if value in COMPLETE_DISPOSITIONS:
        for key in sorted(REQUIRED_SCORES):
            if score_value(assessment, key) is None:
                errors.append(f"{path}: {value} requires {key}")
    if value == "Apply" and ({"health", "financial"} & set(flags)):
        evidence = score_value(assessment, "evidence_quality")
        if not isinstance(evidence, int) or evidence < 3:
            errors.append(f"{path}: health or financial Apply requires evidence_quality >= 3")
        if not human_reviewer(assessment.get("assessor")):
            errors.append(f"{path}: health or financial Apply requires a named human reviewer")
    if "security" in flags and state == "validated":
        if not isinstance(review, dict) or not all(review.get(k) for k in ("date", "reviewer", "summary")):
            errors.append(f"{path}: validated security item requires a complete threat_review")
    if value == "Apply" and metadata.get("provenance_status") == "failed":
        errors.append(f"{path}: failed provenance blocks Apply")
    if value == "Reject" and state not in {None, "unassessed", "held", "retired", "rejected"}:
        errors.append(f"{path}: Reject cannot enter an application workflow")
    return errors


def safety_gate(assessment: dict | None, metadata: dict) -> dict:
    """Builder-side gate. A blocked item never renders Apply."""
    if not assessment:
        return {"blocked": False, "reason": None, "effective_disposition": None}
    value = disposition_value(assessment)
    flags = set(assessment.get("safety_flags") or [])
    state = assessment.get("application_state")
    if metadata.get("provenance_status") == "failed":
        return {"blocked": True, "reason": "Provenance failed; no action may be taken.", "effective_disposition": "Reject"}
    if assessment.get("status") in {"pending", "draft", "failed"}:
        return {"blocked": False, "reason": None, "effective_disposition": None}
    if value == "Reject":
        return {"blocked": True, "reason": "Rejected; kept for retrieval only.", "effective_disposition": "Reject"}
    if value == "Apply" and (flags & {"health", "financial"}):
        evidence = score_value(assessment, "evidence_quality")
        if not isinstance(evidence, int) or evidence < 3 or not human_reviewer(assessment.get("assessor")):
            flag = "health" if "health" in flags else "financial"
            return {"blocked": True, "reason": f"{flag.title()} application needs evidence quality 3+ and a named human reviewer.", "effective_disposition": "Blocked"}
    if "security" in flags and state == "validated":
        review = assessment.get("threat_review")
        if not isinstance(review, dict) or not all(review.get(k) for k in ("date", "reviewer", "summary")):
            return {"blocked": True, "reason": "Security-sensitive item needs a threat review before it leaves validated.", "effective_disposition": "Blocked"}
    return {"blocked": False, "reason": None, "effective_disposition": value}


def merge_draft(base: dict, draft: dict) -> dict:
    """Deep-merge a partial draft onto a base document; dict fields merge, everything else replaces."""
    result = copy.deepcopy(base)
    for key, value in draft.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_draft(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def revise(existing: dict, updated: dict, author: str, date: str, reason: str) -> dict:
    """Increment revision; move the prior values into history."""
    previous = {key: value for key, value in existing.items() if key != "history"}
    document = copy.deepcopy(updated)
    document["revision"] = int(existing.get("revision") or 1) + 1
    document["history"] = list(existing.get("history") or []) + [
        {
            "revision": int(existing.get("revision") or 1),
            "date": date,
            "author": author,
            "reason": reason,
            "previous": previous,
        }
    ]
    document["assessed_at"] = date
    document["assessor"] = author
    return document


def load_assessment(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def dump_assessment(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"

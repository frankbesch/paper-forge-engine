"""Build the compact, backward-compatible console payload."""

from __future__ import annotations

from .ledger import compact_export, compact_outcome
from .learning import read_learning


def payload_record(record: dict) -> dict:
    row = record["row"]
    metadata = record["metadata"]
    identity = record["identity"]
    primary = record["primary"]
    route = record["route_data"]
    state = metadata.get("state") or {}
    assessment = record.get("assessment") or {}
    safety = record.get("safety") or {"blocked": False, "reason": None, "effective_disposition": None}
    transfer = record.get("transfer") or {"application_state": None, "exports": [], "outcomes": []}
    stored_state = assessment.get("application_state") or "unassessed"
    application_state = transfer.get("application_state") or stored_state
    disposition = assessment.get("disposition")
    if isinstance(disposition, dict):
        disposition = disposition.get("value")
    return {
        "slug": record["slug"],
        "number": int(row.get("number") or 0),
        "itemId": metadata.get("item_id"),
        "title": identity.get("title", metadata.get("title", row["title"])),
        "authors": identity.get("authors", metadata.get("authors", row["authors"].split("; "))),
        "year": identity.get("year", metadata.get("year", row["year"])),
        "added": metadata.get("added") or metadata.get("retrieved") or row.get("added"),
        "retrieved": metadata.get("retrieved") or row.get("added"),
        "kind": metadata.get("kind") or "unknown",
        "type": metadata.get("work_type") or metadata.get("paper_type") or metadata.get("source_type") or "research artifact",
        "route": record["route_label"],
        "routeReason": route.get("reason", "No route reason recorded."),
        "selected": record["selected"],
        "skipped": record["skipped"],
        "statuses": record["statuses"],
        "access": record["access_label"],
        "accessScope": primary.get("access_scope") or metadata.get("access_scope", ""),
        "lifecycle": state.get("lifecycle"),
        "currentStage": state.get("current_stage"),
        "nextAction": state.get("next_action"),
        "blocker": state.get("blocker"),
        "feynmanMode": (read_learning(metadata)["feynman"]["mode"] or "off") if "learning" in metadata else route.get("feynman_mode"),
        "themes": record["topics"],
        "evidenceClass": metadata.get("evidence_class") or "unknown",
        "provenanceStatus": metadata.get("provenance_status") or "unverified",
        "capturedVia": metadata.get("captured_via") or "unknown",
        "relations": metadata.get("relations") or [],
        "assessed": assessment.get("status") == "assessed",
        "intake": assessment.get("intake"),
        "recommendation": assessment.get("recommendation"),
        "optionalLearning": read_learning(metadata)["feynman"],
        "assessmentNextAction": (assessment.get("intake") or {}).get("next_action") or f"Draft an assessment with pf.py intake {metadata.get('item_id')}.",
        "disposition": disposition,
        "dispositionEffective": safety["effective_disposition"] if record.get("assessment") else None,
        "applyBlocked": safety["blocked"],
        "blockReason": safety["reason"],
        "dispositionRationale": (assessment.get("disposition") or {}).get("rationale") if isinstance(assessment.get("disposition"), dict) else None,
        "assessmentStatus": assessment.get("status"),
        "assessor": assessment.get("assessor"),
        "assessedAt": assessment.get("assessed_at"),
        "revision": assessment.get("revision"),
        "historyCount": len(assessment.get("history") or []),
        "threatReview": assessment.get("threat_review"),
        "applicationState": application_state,
        "storedApplicationState": stored_state,
        "exports": [compact_export(e, transfer.get("outcomes") or []) for e in transfer.get("exports") or []],
        "outcomes": [compact_outcome(o) for o in transfer.get("outcomes") or []],
        "scores": assessment.get("general") or {},
        "endeavors": assessment.get("endeavors") or {},
        "safetyFlags": assessment.get("safety_flags") or [],
        "freshness": record["freshness"],
        "exported": application_state in {"exported", "measured"},
        "missingOutcome": application_state == "exported",
        "summary": record["summary"],
        "sourceHref": record["source_href"],
        "localSourceHref": record["local_source_href"],
        "overviewHref": f"papers/{record['slug']}/README.md",
        "documents": record["documents"],
    }


def build_payload(records: list[dict]) -> list[dict]:
    return [payload_record(record) for record in records]

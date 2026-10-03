"""Normalize v1 and v2 repository records into one internal shape."""

from __future__ import annotations

import re


CONSOLE_EXCLUDE = re.compile(
    r"\n?<!-- pf:console-exclude:start -->.*?<!-- pf:console-exclude:end -->\n?",
    flags=re.DOTALL,
)


def section(markdown: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, markdown, flags=re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def paragraph(markdown: str, heading: str) -> str:
    body = section(markdown, heading)
    lines = []
    for line in body.splitlines():
        if not line.strip() and lines:
            break
        if line.strip():
            lines.append(line.strip())
    return " ".join(lines)


def plain_text(markdown: str) -> str:
    text = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", markdown)
    text = re.sub(r"[`*_>#|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def console_markdown(markdown: str) -> str:
    """Remove explicitly marked audit-only notes from the embedded overview."""
    return CONSOLE_EXCLUDE.sub("\n", markdown).rstrip() + "\n"


def normalize_record(raw: dict) -> dict:
    row = raw["row"]
    metadata = raw["metadata"]
    readme = raw["readme"]
    slug = row["slug"]
    route = metadata.get("route", {})
    identity = metadata.get("identity") or {}
    sources = metadata.get("sources") or []
    primary = sources[0] if sources else {}
    source_file = primary.get("source_file") or metadata.get("source_file")
    local_source_href = f"papers/{slug}/{source_file}" if source_file else None
    source_href = primary.get("canonical_url") or metadata.get("canonical_url") or local_source_href
    synthesis = section(readme, "One-paragraph synthesis")
    summary = plain_text(synthesis) or plain_text(paragraph(readme, "Working judgment"))
    if not summary:
        summary = "Open the workbook for the current reading notes and evidence."
    documents = [{
        "key": "overview",
        "label": "Overview",
        "status": "reference",
        "path": f"papers/{slug}/README.md",
        "content": console_markdown(readme),
    }]
    for document in raw["work_documents"]:
        documents.append({
            "key": document["key"],
            "label": document["label"],
            "status": None,
            "path": f"papers/{slug}/work/{document['filename']}",
            "content": document["content"],
        })
    return {
        **raw,
        "slug": slug,
        "route_data": route,
        "selected": route.get("selected", []),
        "skipped": route.get("skipped", []),
        "identity": identity,
        "primary": primary,
        "topics": metadata.get("topics") or ["Unclassified"],
        "summary": summary,
        "source_href": source_href,
        "local_source_href": local_source_href,
        "documents": documents,
    }


def normalize_records(records: list[dict]) -> list[dict]:
    return [normalize_record(record) for record in records]

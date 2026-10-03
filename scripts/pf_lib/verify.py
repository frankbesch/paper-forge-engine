"""Verify built-library links, item count, and offline asset boundaries."""

from __future__ import annotations

import json
import re
from pathlib import Path


DATA_OPEN = '<script id="library-data" type="application/json">'


def embedded_payload(html: str) -> list[dict]:
    start = html.index(DATA_OPEN) + len(DATA_OPEN)
    end = html.index("</script>", start)
    return json.loads(html[start:end].replace("<\\/", "</"))


def verify_built_file(path: Path, root: Path, expected_count: int) -> list[dict]:
    html = path.read_text(encoding="utf-8")
    papers = embedded_payload(html)
    errors = []
    if len(papers) != expected_count:
        errors.append(f"expected {expected_count} items, found {len(papers)}")
    if re.search(r'<(?:script|link)[^>]+(?:src|href)="https?://', html):
        errors.append("built file references an external script or stylesheet")
    for paper in papers:
        links = [paper.get("overviewHref"), paper.get("localSourceHref")]
        links.extend(document.get("path") for document in paper.get("documents", []))
        for link in filter(None, links):
            if not (root / link).is_file():
                errors.append(f"{paper.get('itemId')}: missing local link {link}")
    if errors:
        raise ValueError("; ".join(errors))
    return papers

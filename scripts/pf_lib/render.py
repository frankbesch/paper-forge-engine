"""Render the library template and ACTIVE.md focus view."""

from __future__ import annotations

import json
from pathlib import Path


FOCUS_START = "<!-- pf:focus:start -->"
FOCUS_END = "<!-- pf:focus:end -->"


def render_library(
    template: str,
    papers: list[dict],
    as_of: str,
    template_path: Path | None = None,
    console_config: dict | None = None,
) -> str:
    payload = json.dumps(papers, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    if "__PAPER_FORGE_LIBRARY_DATA__" not in template:
        location = template_path or "template"
        raise SystemExit(f"Missing data marker in {location}")
    output = template.replace("__PAPER_FORGE_LIBRARY_DATA__", payload)
    config_payload = json.dumps(console_config or {}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    output = output.replace("__PAPER_FORGE_CONFIG__", config_payload)
    return output.replace("__PAPER_FORGE_AS_OF__", as_of)


def render_active_focus(papers: list[dict]) -> str:
    active = [paper for paper in papers if paper["lifecycle"] == "active"]
    in_progress = [paper for paper in active if paper["currentStage"] not in (None, "read")]
    at_read = [paper for paper in active if paper["currentStage"] == "read"]
    complete = [paper for paper in papers if paper["lifecycle"] == "route_complete"]
    other = [paper for paper in papers if paper["lifecycle"] not in ("active", "route_complete")]
    lines = [
        FOCUS_START,
        "Generated from `metadata.json.state` by `python3 scripts/build_library.py --write-active`. Do not edit by hand.",
        "",
        "| # | Item | Title | Stage | Next action | Blocker |",
        "|---|---|---|---|---|---|",
    ]
    for paper in sorted(in_progress, key=lambda value: value["number"]):
        cells = [
            str(paper["number"]),
            paper["itemId"] or "",
            paper["title"],
            paper["currentStage"] or "",
            paper["nextAction"] or "",
            paper["blocker"] or "none",
        ]
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |")
    if not in_progress:
        lines.append("| – | – | No item is past Read. | – | – | – |")
    lines.append("")
    lines.append(
        f"{len(at_read)} items remain at Read with lifecycle `active`; "
        f"{len(complete)} items are `route_complete`"
        + (f"; {len(other)} items carry another lifecycle" if other else "")
        + "."
    )
    lines.append(FOCUS_END)
    return "\n".join(lines)


def write_active_focus(papers: list[dict], path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if FOCUS_START not in text or FOCUS_END not in text:
        raise SystemExit(f"{path} lacks {FOCUS_START} / {FOCUS_END} markers")
    start = text.index(FOCUS_START)
    end = text.index(FOCUS_END) + len(FOCUS_END)
    updated = text[:start] + render_active_focus(papers) + text[end:]
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True

#!/usr/bin/env python3
"""Build the self-contained paper-forge library browser."""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path

from pf_lib.compute import compute_records
from pf_lib.load import STAGES, load_fixture, load_portfolio, load_repository, load_taxonomy
from pf_lib.normalize import normalize_records
from pf_lib.payload import build_payload
from pf_lib.figures import figures_html
from pf_lib.quoin import quoin_css
from pf_lib.render import FOCUS_END, FOCUS_START, render_active_focus, render_library
from pf_lib.render import write_active_focus as render_write_active_focus
from pf_lib.verify import verify_built_file


CODE = Path(__file__).resolve().parents[1]
TEMPLATE = CODE / "ui" / "library.template.html"
# The library root holds config/, papers/, ledger/, and ACTIVE.md. It defaults to
# this repository and moves with PF_ROOT or --root.
ROOT = Path(os.environ.get("PF_ROOT") or CODE).resolve()
DEFAULT_OUTPUT = ROOT / "library.html"
TAXONOMY = ROOT / "config" / "taxonomy.json"
ACTIVE = ROOT / "ACTIVE.md"
UNCLASSIFIED = "Unclassified"


def load_library(as_of: str | None = None, root: Path | None = None) -> list[dict]:
    effective_date = as_of or dt.date.today().isoformat()
    loaded = load_repository(root or ROOT)
    normalized = normalize_records(loaded)
    computed = compute_records(normalized, effective_date)
    return build_payload(computed)


def write_active_focus(papers: list[dict], path: Path = ACTIVE) -> bool:
    return render_write_active_focus(papers, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Library root (default: PF_ROOT or this repository)")
    parser.add_argument("--output", type=Path, help="Default: library.html in the library root")
    parser.add_argument(
        "--as-of",
        default=dt.date.today().isoformat(),
        help="Build date (YYYY-MM-DD) for view-only freshness fields; pin it for deterministic output",
    )
    parser.add_argument(
        "--write-active",
        action="store_true",
        help="Regenerate the ACTIVE.md focus block from metadata.json state",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        help="Build from a generated console-payload fixture instead of live records",
    )
    args = parser.parse_args()
    dt.date.fromisoformat(args.as_of)
    root = args.root.expanduser().resolve()
    args.output = args.output or root / "library.html"

    papers = load_fixture(args.fixture) if args.fixture else load_library(args.as_of, root)
    if args.write_active:
        changed = write_active_focus(papers, root / "ACTIVE.md")
        print(f"ACTIVE.md focus block {'updated' if changed else 'already current'}")
    template = TEMPLATE.read_text(encoding="utf-8")
    if "__PAPER_FORGE_QUOIN_CSS__" not in template:
        raise SystemExit(f"Missing Quoin CSS marker in {TEMPLATE}")
    template = template.replace("__PAPER_FORGE_QUOIN_CSS__", quoin_css())  #,
    template = template.replace("__PAPER_FORGE_FIGURES__", figures_html(papers, args.as_of))  #
    console_config = {"taxonomy": load_taxonomy(root), "portfolio": load_portfolio(root)}
    output = render_library(template, papers, args.as_of, TEMPLATE, console_config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    verify_built_file(args.output, root, len(papers))
    print(f"Built {args.output} with {len(papers)} artifacts")


if __name__ == "__main__":
    main()

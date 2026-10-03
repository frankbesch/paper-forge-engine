#!/usr/bin/env python3
"""Create a traceable paper-forge workbook from a PDF source."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pf


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_pdf(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ValueError(f"Not a PDF file: {path}")


def render_markdown_templates(folder: Path, replacements: dict[str, str]) -> None:
    for path in folder.rglob("*.md"):
        rendered = path.read_text(encoding="utf-8")
        for token, value in replacements.items():
            rendered = rendered.replace("{{" + token + "}}", value)
        path.write_text(rendered, encoding="utf-8")


def append_registry(root: Path, row: list[str]) -> None:
    index = root / "papers" / "index.csv"
    needs_header = not index.exists() or index.stat().st_size == 0
    with index.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        if needs_header:
            writer.writerow(["slug", "title", "authors", "year", "added", "status"])
        writer.writerow(row)


def create_paper(
    root: Path,
    source: Path,
    title: str,
    authors: str,
    year: int,
    slug: str | None = None,
    added: str | None = None,
) -> Path:
    source = source.expanduser().resolve()
    validate_pdf(source)
    args = argparse.Namespace(
        source=str(source), text=None, filename=None, title=title, authors=authors,
        year=year, published=None, retrieved=added or date.today().isoformat(),
        url=None, version=None, language="en", access_scope=None, kind="paper",
        work_type="unknown", route="capture", purpose=None, feynman=None,
        slug=slug,
    )
    return pf.create_item(args, root.resolve())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="PDF to copy into the forge")
    parser.add_argument("--title", required=True)
    parser.add_argument("--authors", required=True, help="Separate multiple authors with semicolons")
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--slug", help="Optional lower-case folder name")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = create_paper(
        root=root,
        source=args.source,
        title=args.title,
        authors=args.authors,
        year=args.year,
        slug=args.slug,
    )
    print(destination)


if __name__ == "__main__":
    main()

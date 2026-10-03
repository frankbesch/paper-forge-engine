#!/usr/bin/env python3
"""Create a traceable paper-forge workbook from a web article snapshot."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from new_paper import append_registry, file_sha256, render_markdown_templates, slugify
import pf


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Not an HTTP(S) URL: {url}")


def create_article(
    root: Path,
    url: str,
    snapshot: Path,
    title: str,
    authors: str,
    year: int,
    published: str,
    slug: str | None = None,
    retrieved: str | None = None,
) -> Path:
    validate_url(url)
    snapshot = snapshot.expanduser().resolve()
    if not snapshot.is_file():
        raise FileNotFoundError(snapshot)
    args = argparse.Namespace(
        source=str(snapshot), text=None, filename=None, title=title, authors=authors,
        year=year, published=published, retrieved=retrieved or date.today().isoformat(),
        url=url, version=None, language="en", access_scope=None, kind="article",
        work_type="unknown", route="capture", purpose=None, feynman=None,
        slug=slug,
    )
    return pf.create_item(args, root.resolve())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Canonical article URL")
    parser.add_argument("--snapshot", required=True, type=Path, help="Saved HTML source")
    parser.add_argument("--title", required=True)
    parser.add_argument("--authors", required=True, help="Separate multiple authors with semicolons")
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--published", required=True, help="Publication date, preferably YYYY-MM-DD")
    parser.add_argument("--slug", help="Optional lower-case folder name")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = create_article(
        root=root,
        url=args.url,
        snapshot=args.snapshot,
        title=args.title,
        authors=args.authors,
        year=args.year,
        published=args.published,
        slug=args.slug,
    )
    print(destination)


if __name__ == "__main__":
    main()

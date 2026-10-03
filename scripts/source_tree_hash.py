#!/usr/bin/env python3
"""Hash every preserved source byte under papers/*/source/ (migration acceptance, )."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_files(root: Path = ROOT) -> list[Path]:
    return sorted(p for p in (root / "papers").glob("*/source/**/*") if p.is_file())


def tree_hash(root: Path = ROOT) -> tuple[str, int]:
    digest = hashlib.sha256()
    files = source_files(root)
    for path in files:
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest(), len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", help="Expected tree hash; exit 1 on mismatch")
    args = parser.parse_args()
    value, count = tree_hash()
    print(f"{value}  {count} files")
    if args.check and args.check != value:
        raise SystemExit(f"source tree hash mismatch: expected {args.check}")


if __name__ == "__main__":
    main()

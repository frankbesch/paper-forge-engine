#!/usr/bin/env python3
"""Generate the deterministic 500-item console performance fixture."""

from __future__ import annotations

import argparse
import copy
import json
import random
from pathlib import Path

from build_library import ROOT, load_library
from pf_lib.load import load_portfolio, load_taxonomy


DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "portfolio-500"
SYNTHETIC = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "library"
SEED = 20260904


def score(value: int) -> dict:
    return {"score": value, "rationale": "Seeded performance fixture value."}


def build_fixture(count: int, as_of: str, root: Path = ROOT) -> list[dict]:
    source = load_library(as_of, root)
    taxonomy = load_taxonomy(root)
    endeavors = list(load_portfolio(root)["endeavors"])
    rng = random.Random(SEED)
    order = list(range(len(source)))
    rng.shuffle(order)
    dispositions = ["Apply", "Test", "Learn", "Watch", "Reference", "Hold", "Retire", "Reject"]
    stage_values = ["not_started", "in_progress", "blocked", "complete", "skipped"]
    fixture = []
    for offset in range(count):
        item = copy.deepcopy(source[order[offset % len(order)]])
        number = offset + 1
        assessed = number % 3 != 0
        endeavor = endeavors[number % len(endeavors)]
        topic = taxonomy["topics"][number % len(taxonomy["topics"])]
        item.update({
            "slug": f"fixture-{number:04d}",
            "number": number,
            "itemId": f"PX-{number:04d}",
            "title": f"{item['title']} · fixture {number:04d}",
            "retrieved": f"2026-{((number - 1) % 8) + 1:02d}-{((number - 1) % 27) + 1:02d}",
            "themes": [topic],
            "assessed": assessed,
            "disposition": dispositions[number % len(dispositions)] if assessed else None,
            "scores": {
                "evidence_quality": score(number % 5),
                "implementation_effort": score((number + 2) % 5),
            } if assessed else {},
            "endeavors": {
                endeavor: {
                    "relevance": number % 5,
                    "expected_leverage": (number + 1) % 5,
                    "confidence": ["low", "medium", "high"][number % 3],
                }
            } if assessed else {},
            "freshness": {
                "as_of": as_of,
                "review_by": "2026-08-01" if number % 4 == 0 else "2026-10-01",
                "status": "stale" if number % 4 == 0 else "current",
            } if assessed else {"as_of": as_of, "review_by": None, "status": "unknown"},
            "exported": assessed and number % 11 == 0,
            "missingOutcome": assessed and number % 22 == 0,
            "relations": [],
            "statuses": {key: stage_values[(number + index) % len(stage_values)] for index, key in enumerate(item["statuses"])},
        })
        item["documents"] = [
            {**document, "content": f"# Fixture document\n\nSeed {SEED}; item {number}.\n"}
            for document in item["documents"]
        ]
        fixture.append(item)
    return fixture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--as-of", default="2026-09-04")
    parser.add_argument("--source-root", type=Path, default=SYNTHETIC,
                        help="Library to cycle through (default: the synthetic test library)")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / "items.json"
    target.write_text(json.dumps(build_fixture(args.count, args.as_of, args.source_root.resolve()), ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Generated {target} with {args.count} items; seed={SEED}")


if __name__ == "__main__":
    main()

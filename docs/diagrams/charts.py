#!/usr/bin/env python3
"""Draw the README lifecycle picture as light and dark SVG.

Usage: python3 docs/diagrams/charts.py
Writes lifecycle-light.svg and lifecycle-dark.svg: the path of one source from
capture to the built console. It pairs with the console screenshot in
docs/screens/, captured at the same shown height by capture.mjs. Every step is
worded from the README's How it works, and main() checks each phrase is still
there. The drawing code is quoin_readme.py, a copy of the Quoin README module.
"""
from pathlib import Path

from quoin_readme import THEMES, steps

HERE = Path(__file__).resolve().parent
README = HERE.parent.parent / "README.md"

LIFECYCLE = dict(
    title="One source, capture to console",
    steps=[("Capture", "pf.py capture keeps the source byte", "for byte, with its SHA-256", "external"),
           ("Route", "how deep it goes: capture, interpret,", "critique, verify, or develop", "bus"),
           ("Workbook", "seven stages, Read to Discover", None, "backend"),
           ("Assess", "relevance and leverage per endeavor;", "Apply, Test, Hold, Retire need the approver",
            "security"),
           ("Apply", "an export package and an append-only", "receipt; never writes into the target",
            "database"),
           ("Validate", "schemas, checksums, workbooks, IDs,", "the registry order, and the ledgers", "backend"),
           ("Build", "one library.html, no network requests,", "byte-identical for the same inputs", "cloud")],
    note="The engine makes no model calls; a draft assessment comes in as JSON from any assistant.",
    desc=("pf.py capture preserves a source byte for byte with its SHA-256 and copies the workbook "
          "templates. A route sets how deep it goes: capture, interpret, critique, verify, or develop. "
          "The workbook has seven stages, Read to Discover. An assessment records relevance and leverage "
          "per endeavor; the dispositions Apply, Test, Hold, and Retire need the named approver. Apply "
          "writes an export package and an append-only receipt and never writes into the target. "
          "Validate checks schemas, checksums, workbooks, IDs, the registry order, and the ledgers. "
          "Build renders one library.html that makes no network requests and is byte-identical for the "
          "same inputs. The engine makes no model calls."),
)

# Phrases each step rests on, as the README words them.
SOURCES = ["records its SHA-256", "capture, interpret, critique,", "seven-stage workbook from",
           "Read to Discover", "relevance and leverage per endeavor", "(Apply, Test, Hold,",
           "Retire) need the named approver", "append-only receipt", "It never writes into the target",
           "checksums, workbooks, IDs, the registry order, and the ledgers", "makes no",
           "network requests", "byte-identical output", "the engine makes no model calls"]


def main():
    readme = " ".join(README.read_text().split())
    missing = [s for s in SOURCES if " ".join(s.split()) not in readme]
    assert not missing, f"README no longer says: {missing}"
    for theme, c in THEMES.items():
        (HERE / f"lifecycle-{theme}.svg").write_text(steps(LIFECYCLE, c))
    print("built lifecycle")


if __name__ == "__main__":
    main()

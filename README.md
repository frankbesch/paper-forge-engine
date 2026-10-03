# Paper Forge engine

A local research library for papers, articles, and notes. Each source is
preserved byte for byte with its checksum, gets a seven-stage workbook from
Read to Discover, and can carry a scored assessment. One command builds a
self-contained HTML console to browse, filter, and review the whole library
offline. Python standard library only.

## Status

The engine behind a working personal library of about 180 items,
published as code only, with a three-item synthetic sample library. The
tests run on the sample library: `python3 -m unittest discover -s tests`.
One console test needs Node and skips without it. Optional extractors:
`pdftotext` and `tesseract`, used when present.

## Measured results

On the sample library the build writes one `library.html` that makes no
network requests (a test checks every `script` and `link`). It runs offline
from disk. The same inputs and build date give byte-identical output; a
golden hash in `tests/golden/library.sha256` holds it.

A seeded 500-item fixture in `tests/fixtures/portfolio-500/` exercises the
console at scale. It is generated from the sample library, so it carries no
real titles or notes.

## How it works

- **Capture** (`pf.py capture`) preserves a source under
  `papers/<slug>/source/`, records its SHA-256, and copies the workbook
  templates from `templates/paper/`.
- **Routes** pick how deep a source goes: capture, interpret, critique,
  verify, or develop (all seven stages).
- **Assess** records relevance and leverage per endeavor in
  `config/portfolio.json`. Effective dispositions (Apply, Test, Hold,
  Retire) need the named approver.
- **Apply** writes an export package and an append-only receipt for a
  configured target. It never writes into the target.
- **Validate** (`pf.py validate`, `validate_v2.py`) checks schemas,
  checksums, workbooks, IDs, the registry order, and the ledgers.
- **Build** (`build_library.py`) renders the console from the library.

A library root holds `config/`, `templates/`, `papers/`, and `ledger/`.
This repository is an empty library; `--root` or `PF_ROOT` points the tools
at any other.

## Quick start

```bash
# Get the code. No dependencies.
git clone https://github.com/\
frankbesch/paper-forge-engine.git
cd paper-forge-engine

# Start a library of your own.
mkdir -p ~/my-library
cp -R config templates ~/my-library/

# Capture a source.
python3 scripts/pf.py \
  --root ~/my-library capture \
  --text "Your pasted text." \
  --filename note.txt \
  --title "A first item" \
  --captured-via manual

# Validate, then build the console.
python3 scripts/pf.py \
  --root ~/my-library validate
python3 scripts/build_library.py \
  --root ~/my-library
open ~/my-library/library.html
```

## Measured run

```bash
# The tests, on the sample library.
python3 -m unittest discover -s tests

# Build the sample library's console.
python3 scripts/build_library.py \
  --root tests/fixtures/library \
  --output /tmp/library.html
```

## Known gaps

- Model-assisted steps (drafting an assessment) take a JSON draft from any
  assistant; the engine makes no model calls itself.
- Export targets and endeavors are names in `config/portfolio.json`; the
  engine does not know what they point to.
- The console reads Quoin design tokens from a checkout named by
  `QUOIN_ROOT` when set, and draws its figures only then. Without it, it
  uses frozen tokens and leaves the figures out.

## More

- [config/](config/): taxonomy, portfolio, evidence-class map, and the
  local example.
- [templates/paper/](templates/paper/): the seven workbook stages.
- [tests/fixtures/library/](tests/fixtures/library/): the sample library.

## License

MIT. See [LICENSE](LICENSE).

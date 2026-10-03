#!/usr/bin/env python3
"""Unified Paper Forge intake, extraction, lookup, and validation CLI."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
from html.parser import HTMLParser
import json
import mimetypes
import re
import shutil
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile


# The library root holds config/, templates/, papers/, and ledger/. It defaults to
# this repository (an empty library) and moves with PF_ROOT or --root.
ROOT = Path(os.environ.get("PF_ROOT") or Path(__file__).resolve().parents[1]).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pf_lib import assessment as assessment_contract  # noqa: E402
from pf_lib import ledger as ledger_contract  # noqa: E402
from pf_lib import intake as intake_contract
from pf_lib import learning as learning_contract  # noqa: E402

STAGES = ["read", "understand", "analyze", "reproduce", "experiment", "extend", "discover"]
STAGE_LABELS = {name: name.title() for name in STAGES}
ROUTES = {
    "capture": ["read"],
    "interpret": ["read", "understand"],
    "critique": ["read", "understand", "analyze"],
    "verify": ["read", "understand", "analyze", "reproduce"],
    "develop": STAGES,
}
SUPPORTED_SUFFIXES = {
    ".pdf", ".html", ".htm", ".txt", ".md", ".docx", ".pptx", ".xlsx",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".webp",
}
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".rs", ".go", ".java", ".c", ".cpp", ".h", ".sql", ".json", ".yaml", ".yml", ".toml"}
SUPPORTED_SUFFIXES |= CODE_SUFFIXES
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
CAPTURE_SURFACES = {"claude-code", "claude-ai", "chatgpt", "codex", "manual"}
DECLINE_REASONS = {"duplicate", "low-value", "off-scope", "unverifiable", "already-captured"}


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def mime_type(path: Path) -> str:
    overrides = {
        ".md": "text/markdown",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    return overrides.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def detect_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "paper"
    if suffix in {".html", ".htm"}:
        return "article"
    if suffix in {".txt", ".md"} | CODE_SUFFIXES:
        return "note"
    if suffix in {".docx", ".pptx", ".xlsx"}:
        return "document"
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".webp"}:
        return "image"
    raise ValueError(f"Unsupported source format: {suffix or '(no extension)'}")


def source_entries(metadata: dict) -> list[dict]:
    if metadata.get("sources"):
        return list(metadata["sources"])
    if not metadata.get("source_file"):
        return []
    return [{
        "role": "primary",
        "canonical_url": metadata.get("canonical_url"),
        "source_file": metadata["source_file"],
        "sha256": metadata.get("source_sha256"),
    }]


def iter_metadata(root: Path):
    for path in sorted((root / "papers").glob("*/metadata.json")):
        yield path, json.loads(path.read_text(encoding="utf-8"))


def find_duplicate(root: Path, digest: str, canonical_url: str | None) -> str | None:
    wanted_url = normalize_url(canonical_url)
    for path, metadata in iter_metadata(root):
        for source in source_entries(metadata):
            if source.get("sha256") == digest:
                return metadata.get("item_id") or path.parent.name
            if wanted_url and normalize_url(source.get("canonical_url")) == wanted_url:
                return metadata.get("item_id") or path.parent.name
    return None


def intake_ledger(root: Path) -> Path:
    return root / "ledger" / "intake.jsonl"


def decline_key(digest: str | None, canonical_url: str | None) -> tuple[str, str] | None:
    if canonical_url:
        return "url", normalize_url(canonical_url) or canonical_url
    if digest:
        return "content_hash", digest
    return None


def iter_declines(root: Path):
    path = intake_ledger(root)
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Malformed intake ledger line {number}: {error.msg}") from error


def find_prior_decline(root: Path, digest: str | None = None, canonical_url: str | None = None) -> dict | None:
    key = decline_key(digest, canonical_url)
    if key is None:
        return None
    field, value = key
    for receipt in iter_declines(root):
        candidate = normalize_url(receipt.get(field)) if field == "url" else receipt.get(field)
        if candidate == value:
            return receipt
    return None


def append_decline(
    root: Path,
    *,
    reason: str,
    surface: str,
    declined_on: str,
    title: str,
    digest: str | None = None,
    canonical_url: str | None = None,
    duplicate_of: str | None = None,
) -> dict:
    if reason not in DECLINE_REASONS:
        raise ValueError(f"Unknown decline reason: {reason}")
    if surface not in CAPTURE_SURFACES:
        raise ValueError(f"Unknown capture surface: {surface}")
    key = decline_key(digest, canonical_url)
    if key is None:
        raise ValueError("A decline needs a canonical URL or content hash")
    field, value = key
    receipt = {
        "date": declined_on,
        "surface": surface,
        "reason": reason,
        "title": title,
        field: value,
    }
    if duplicate_of:
        receipt["duplicate_of"] = duplicate_of
    path = intake_ledger(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    return receipt


def decline_capture(args: argparse.Namespace, root: Path = ROOT) -> tuple[dict, bool]:
    if bool(args.source) == bool(args.text is not None):
        raise ValueError("Provide exactly one source path/URL or --text")
    canonical_url = args.url
    digest = None
    if args.text is not None:
        digest = hashlib.sha256(args.text.encode("utf-8")).hexdigest()
    elif re.match(r"^https?://", args.source):
        canonical_url, _ = url_download_target(args.source)
    else:
        source = Path(args.source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        digest = sha256(source)
    prior = find_prior_decline(root, digest, canonical_url)
    if prior:
        return prior, False
    receipt = append_decline(
        root,
        reason=args.decline,
        surface=args.captured_via,
        declined_on=args.retrieved or date.today().isoformat(),
        title=args.title,
        digest=digest,
        canonical_url=canonical_url,
    )
    return receipt, True


def next_item_id(root: Path) -> str:
    numbers = []
    for _, metadata in iter_metadata(root):
        match = re.fullmatch(r"PF-(\d{4,})", str(metadata.get("item_id", "")))
        if match:
            numbers.append(int(match.group(1)))
    if not numbers:
        index = root / "papers" / "index.csv"
        if index.exists():
            with index.open(encoding="utf-8-sig", newline="") as stream:
                numbers = list(range(1, sum(1 for _ in csv.DictReader(stream)) + 1))
    return f"PF-{max(numbers, default=0) + 1:04d}"


class VisibleTextParser(HTMLParser):
    hidden_tags = {"script", "style", "noscript", "svg"}
    break_tags = {"address", "article", "aside", "blockquote", "br", "div", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "li", "main", "nav", "p", "section", "table", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag in self.hidden_tags:
            self.hidden_depth += 1
        elif not self.hidden_depth and tag in self.break_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag in self.hidden_tags and self.hidden_depth:
            self.hidden_depth -= 1
        elif not self.hidden_depth and tag in self.break_tags:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if not self.hidden_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = []
        for raw in "".join(self.parts).splitlines():
            line = re.sub(r"\s+", " ", html.unescape(raw)).strip()
            if line and (not lines or line != lines[-1]):
                lines.append(line)
        return "\n".join(lines) + ("\n" if lines else "")


def extract_html(path: Path) -> tuple[str, str, str]:
    parser = VisibleTextParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return parser.text(), "html-visible-text", "Heading and extraction-line anchors; scripted content may be absent."


def xml_text(element: ET.Element) -> str:
    return " ".join((node.text or "").strip() for node in element.iter() if node.tag.endswith("}t") and (node.text or "").strip())


def extract_docx(path: Path) -> tuple[str, str, str]:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for node in root.iter():
        if node.tag.endswith("}p"):
            value = xml_text(node)
            if value:
                paragraphs.append(f"[paragraph {len(paragraphs) + 1}] {value}")
    return "\n".join(paragraphs) + ("\n" if paragraphs else ""), "docx-xml", "Paragraph anchors; pagination is renderer-dependent."


def numeric_path_key(name: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name))


def extract_pptx(path: Path) -> tuple[str, str, str]:
    lines = []
    with zipfile.ZipFile(path) as archive:
        slides = sorted((name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)), key=numeric_path_key)
        for number, name in enumerate(slides, start=1):
            root = ET.fromstring(archive.read(name))
            value = xml_text(root)
            if value:
                lines.append(f"[slide {number}] {value}")
    return "\n".join(lines) + ("\n" if lines else ""), "pptx-xml", "Slide anchors; visual relationships require rendered-slide review."


def extract_xlsx(path: Path) -> tuple[str, str, str]:
    lines = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = [xml_text(item) for item in shared_root if item.tag.endswith("}si")]
        sheets = sorted((name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)), key=numeric_path_key)
        for sheet_number, name in enumerate(sheets, start=1):
            root = ET.fromstring(archive.read(name))
            for cell in (node for node in root.iter() if node.tag.endswith("}c")):
                ref = cell.attrib.get("r", "?")
                value_node = next((node for node in cell if node.tag.endswith("}v")), None)
                formula_node = next((node for node in cell if node.tag.endswith("}f")), None)
                value = value_node.text if value_node is not None else ""
                if cell.attrib.get("t") == "s" and value and value.isdigit() and int(value) < len(shared):
                    value = shared[int(value)]
                if formula_node is not None and formula_node.text:
                    value = f"={formula_node.text}" + (f" -> {value}" if value else "")
                if value:
                    lines.append(f"[sheet {sheet_number}!{ref}] {value}")
    return "\n".join(lines) + ("\n" if lines else ""), "xlsx-xml", "Sheet-number and cell anchors; cached values may require workbook recalculation."


def run_extractor(command: list[str], method: str, caveat: str) -> tuple[str, str, str]:
    completed = subprocess.run(command, check=False, capture_output=True)
    if completed.returncode:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"{command[0]} exited {completed.returncode}")
    return completed.stdout.decode("utf-8", errors="replace"), method, caveat


def extract_source(path: Path) -> tuple[str | None, dict]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            tool = shutil.which("pdftotext")
            if not tool:
                return None, {"status": "unavailable", "method": "pdftotext", "caveat": "Install pdftotext to derive navigation text."}
            text, method, caveat = run_extractor([tool, "-layout", str(path), "-"], "pdftotext-layout", "Text extraction is a navigation aid; figures and scanned pages require visual review.")
            pages = text.split("\f")
            text = "\n\n".join(f"[page {number}]\n{page.strip()}" for number, page in enumerate(pages, start=1) if page.strip())
            if text:
                text += "\n"
        elif suffix in {".html", ".htm"}:
            text, method, caveat = extract_html(path)
        elif suffix in {".txt", ".md"} | CODE_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            method, caveat = "verbatim-text", "Line anchors refer to the preserved text source. Code is preserved, never executed."
        elif suffix == ".docx":
            text, method, caveat = extract_docx(path)
        elif suffix == ".pptx":
            text, method, caveat = extract_pptx(path)
        elif suffix == ".xlsx":
            text, method, caveat = extract_xlsx(path)
        elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".webp"}:
            tool = shutil.which("tesseract")
            if not tool:
                return None, {"status": "unavailable", "method": "tesseract", "caveat": "Install Tesseract to derive OCR text."}
            text, method, caveat = run_extractor([tool, str(path), "stdout", "--psm", "6"], "tesseract-ocr", "OCR is not exact quotation evidence until checked against the image.")
        else:
            raise ValueError(f"Unsupported source format: {suffix}")
    except (OSError, UnicodeError, RuntimeError, ET.ParseError, KeyError, zipfile.BadZipFile) as error:
        return None, {"status": "failed", "method": "format-extractor", "error": str(error), "caveat": "The original is preserved; extraction must be repaired before text-dependent work."}
    text = text.replace("\x00", "")
    return text, {"status": "complete", "method": method, "characters": len(text), "caveat": caveat}


def safe_filename(value: str, fallback: str) -> str:
    name = Path(unquote(value)).name or fallback
    name = re.sub(r"[^A-Za-z0-9._ -]+", "-", name).strip(" .")
    return name or fallback


def url_download_target(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Not an HTTP(S) URL: {url}")
    canonical = url
    if parsed.netloc.lower() in {"arxiv.org", "www.arxiv.org"} and parsed.path.startswith("/abs/"):
        paper_id = parsed.path.removeprefix("/abs/").strip("/")
        return canonical, f"https://arxiv.org/pdf/{paper_id}.pdf"
    return canonical, url


def fetch_url(url: str, destination: Path) -> tuple[str, str]:
    canonical, download_url = url_download_target(url)
    request = Request(download_url, headers={"User-Agent": "paper-forge/1.0 (+local research archive)"})
    with urlopen(request, timeout=30) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"Remote source exceeds {MAX_DOWNLOAD_BYTES} bytes")
        content_type = response.headers.get_content_type()
        data = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"Remote source exceeds {MAX_DOWNLOAD_BYTES} bytes")
        destination.write_bytes(data)
    return canonical, content_type


def render_templates(folder: Path, replacements: dict[str, str]) -> None:
    for path in folder.rglob("*.md"):
        rendered = path.read_text(encoding="utf-8")
        for token, value in replacements.items():
            rendered = rendered.replace("{{" + token + "}}", value)
        path.write_text(rendered, encoding="utf-8")


def route_metadata(route_name: str, purpose: str | None, feynman_mode: str | None) -> dict:
    selected = list(ROUTES[route_name])
    if feynman_mode not in (None, "off", "standard", "blank_sheet"):
        raise ValueError("Feynman mode must be off, standard, or blank_sheet")
    if feynman_mode in ("standard", "blank_sheet") and "understand" not in selected:
        raise ValueError("Explicit Feynman mode requires a route containing Understand")
    skipped = [stage for stage in STAGES if stage not in selected]
    return {
        "name": route_name,
        "purpose": purpose or "Preserve provenance and create a trustworthy route-ready record.",
        "selected": selected,
        "skipped": skipped,
        "reason": "Only the smallest route needed for the current purpose is selected.",
        "reopening_trigger": "Reopen when a concrete learning, decision, verification, or development need depends on this source.",
    }


def initialize_workbook(readme_path: Path, route: dict, learning: dict | None = None) -> None:
    selected = route["selected"]
    skipped = route["skipped"]
    route_lines = [
        "## Route decision",
        "",
        f"- Purpose: {route['purpose']}",
        f"- Selected route: {route['name'].title()}.",
        f"- Selected stages: {', '.join(STAGE_LABELS[s] for s in selected)}.",
        f"- Skipped stages: {', '.join(STAGE_LABELS[s] for s in skipped) or 'none'}.",
        f"- Reopening trigger: {route['reopening_trigger']}",
    ]
    readme = readme_path.read_text(encoding="utf-8")
    readme = re.sub(r"## Route decision\n.*?(?=\n## Forge status)", "\n".join(route_lines) + "\n", readme, flags=re.DOTALL)
    for stage in STAGES:
        status = "in_progress" if stage == selected[0] else ("not_started" if stage in selected else "skipped")
        readme = re.sub(rf"(\| {STAGE_LABELS[stage]} \|) [a-z_]+ (\|)", rf"\1 {status} \2", readme)
        work = readme_path.parent / "work" / f"{STAGES.index(stage) + 1:02d}-{stage}.md"
        content = work.read_text(encoding="utf-8")
        content = re.sub(r"Status: `[^`]+`", f"Status: `{status}`", content, count=1)
        if stage == "understand":
            exercise = (learning or learning_contract.new_learning())["feynman"]
            content = content.replace("{{FEYNMAN_MODE}}", exercise["mode"] or "off")
            content = content.replace("{{FEYNMAN_STATUS}}", exercise["status"])
        if stage in skipped:
            content += f"\n## Routing note\n\nSkipped because {route['reason']} Reopen when {route['reopening_trigger']}\n"
        work.write_text(content, encoding="utf-8")
    readme_path.write_text(readme, encoding="utf-8")


def rebuild_index(root: Path) -> int:
    records = []
    for path, metadata in iter_metadata(root):
        identity = metadata.get("identity", {})
        item_id = metadata.get("item_id", "")
        match = re.fullmatch(r"PF-(\d+)", item_id)
        order = int(match.group(1)) if match else 10**9
        authors = identity.get("authors", metadata.get("authors", [])) or []
        records.append((order, path.parent.name, [
            path.parent.name,
            identity.get("title", metadata.get("title", "")),
            "; ".join(authors),
            identity.get("year", metadata.get("year")) or "",
            metadata.get("added") or metadata.get("retrieved") or "",
            (metadata.get("state") or {}).get("current_stage") or (metadata.get("route", {}).get("selected") or ["read"])[-1],
        ]))
    records.sort(key=lambda record: (record[0], record[1]))
    index = root / "papers" / "index.csv"
    with index.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["slug", "title", "authors", "year", "added", "status"])
        writer.writerows(record[2] for record in records)
    return len(records)


def create_item(args: argparse.Namespace, root: Path = ROOT) -> Path:
    if bool(args.source) == bool(args.text is not None):
        raise ValueError("Provide exactly one source path/URL or --text")
    # Validate selection before downloads, duplicate ledgers, or workspace writes.
    route = route_metadata(args.route, args.purpose, args.feynman)
    learning = learning_contract.new_learning(args.feynman, date.today().isoformat())
    today = args.retrieved or date.today().isoformat()
    canonical_url = args.url
    captured_via = getattr(args, "captured_via", "claude-code")
    temp_dir = tempfile.TemporaryDirectory()
    created_destination = False
    try:
        temp_root = Path(temp_dir.name)
        if args.text is not None:
            source = temp_root / (args.filename or "pasted-text.md")
            source.write_text(args.text, encoding="utf-8")
        elif re.match(r"^https?://", args.source):
            canonical_url, download_url = url_download_target(args.source)
            prior = find_prior_decline(root, canonical_url=canonical_url)
            if prior:
                raise FileExistsError(
                    f"Source was declined on {prior['date']} for {prior['reason']} via {prior['surface']}"
                )
            parsed = urlparse(download_url)
            guessed = safe_filename(parsed.path, "snapshot.html")
            if not Path(guessed).suffix:
                guessed += ".html"
            source = temp_root / guessed
            _, content_type = fetch_url(args.source, source)
            if content_type == "application/pdf" and source.suffix.lower() != ".pdf":
                renamed = source.with_suffix(".pdf")
                source.rename(renamed)
                source = renamed
            elif content_type == "text/html" and source.suffix.lower() not in {".html", ".htm"}:
                renamed = source.with_suffix(".html")
                source.rename(renamed)
                source = renamed
        else:
            source = Path(args.source).expanduser().resolve()
            if not source.is_file():
                raise FileNotFoundError(source)
        if source.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported source format: {source.suffix or '(no extension)'}")
        if source.suffix.lower() == ".pdf" and source.read_bytes()[:5] != b"%PDF-":
            raise ValueError(f"Not a PDF file: {source}")
        digest = sha256(source)
        prior = find_prior_decline(root, digest, canonical_url)
        if prior:
            raise FileExistsError(
                f"Source was declined on {prior['date']} for {prior['reason']} via {prior['surface']}"
            )
        duplicate = find_duplicate(root, digest, canonical_url)
        if duplicate:
            append_decline(
                root,
                reason="duplicate",
                surface=captured_via,
                declined_on=today,
                title=args.title,
                digest=digest,
                canonical_url=canonical_url,
                duplicate_of=duplicate,
            )
            raise FileExistsError(f"Source already exists as {duplicate}")

        item_id = next_item_id(root)
        year_token = str(args.year) if args.year else "undated"
        slug = slugify(args.slug or f"{year_token}-{args.title}")
        destination = root / "papers" / slug
        if destination.exists():
            raise FileExistsError(f"Item already exists: {destination}")
        shutil.copytree(root / "templates" / "paper", destination)
        created_destination = True
        (destination / "source").mkdir()
        copied = destination / "source" / safe_filename(source.name, "source.bin")
        shutil.copy2(source, copied)

        authors = [value.strip() for value in (args.authors or "").split(";") if value.strip()]
        source_ref = f"[`source/{copied.name}`](source/{copied.name})"
        if canonical_url:
            source_ref = f"[canonical source]({canonical_url}); snapshot: {source_ref}"
        render_templates(destination, {
            "TITLE": args.title,
            "AUTHORS": "; ".join(authors) or "Creator unknown",
            "YEAR": str(args.year) if args.year else "date unknown",
            "SOURCE_FILE": copied.name,
            "SOURCE_SHA256": digest,
            "SOURCE_REFERENCE": source_ref,
        })
        initialize_workbook(destination / "README.md", route, learning)

        extracted_text, extraction = extract_source(copied)
        extraction_path = None
        if extracted_text is not None:
            extraction_path = "work/extracted.txt"
            (destination / extraction_path).write_text(extracted_text, encoding="utf-8")
        receipt_path = "work/extraction.json"
        (destination / receipt_path).write_text(json.dumps(extraction, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        primary = {
            "source_id": "S1",
            "role": "primary",
            "canonical_url": canonical_url,
            "source_file": f"source/{copied.name}",
            "media_type": mime_type(copied),
            "sha256": digest,
            "bytes": copied.stat().st_size,
            "retrieved": today,
            "version": args.version,
            "commit": getattr(args, "source_commit", None),
            "access_scope": args.access_scope,
            "extraction": {**extraction, "artifact": extraction_path, "receipt": receipt_path},
        }
        stages = {stage: f"work/{index + 1:02d}-{stage}.md" for index, stage in enumerate(STAGES)}
        metadata = {
            "schema_version": 1,
            "item_id": item_id,
            "slug": slug,
            "kind": args.kind or detect_kind(copied),
            "work_type": args.work_type,
            # evidence_class follows the approved map at intake (2026-09-16): a
            # capture left without it fails validate_v2 and the push gate.
            "evidence_class": evidence_class_for(args.work_type, root),
            "identity": {
                "title": args.title,
                "authors": authors,
                "year": args.year,
                "published": args.published,
                "language": args.language,
            },
            "sources": [primary],
            "route": route,
            "learning": learning,
            "artifacts": {
                "overview": "README.md",
                "stages": stages,
                "extracted_text": extraction_path,
                "extraction_receipt": receipt_path,
            },
            "relations": [],
            "topics": ["Unclassified"],
            "captured_via": captured_via,
            "provenance_status": "verified",
            "state": {
                "lifecycle": "active",
                "current_stage": route["selected"][0],
                "next_action": "Complete the selected route's current stage exit gate.",
                "blocker": None,
            },
            # Schema-v1 compatibility fields for existing readers.
            "title": args.title,
            "authors": authors,
            "year": args.year,
            "published": args.published,
            "retrieved": today,
            "source_type": mime_type(copied),
            "paper_type": args.work_type,
            "canonical_url": canonical_url,
            "source_file": primary["source_file"],
            "source_sha256": digest,
            "access_scope": args.access_scope,
        }
        (destination / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        pending = intake_contract.pending_assessment(metadata, date.today().isoformat())
        (destination / "assessment.json").write_text(assessment_contract.dump_assessment(pending), encoding="utf-8")
        rebuild_index(root)
        return destination
    except Exception:
        if created_destination and destination.exists():
            shutil.rmtree(destination)
        raise
    finally:
        temp_dir.cleanup()


def validate_repository(root: Path = ROOT) -> list[str]:
    errors = []
    ids = set()
    slugs = []
    for path, metadata in iter_metadata(root):
        slug = path.parent.name
        slugs.append(slug)
        errors.extend(f"{slug}: {error}" for error in learning_contract.validate_learning(metadata))
        if metadata.get("schema_version") != 1:
            errors.append(f"{slug}: schema_version is not 1")
        item_id = metadata.get("item_id")
        if not re.fullmatch(r"PF-\d{4,}", str(item_id or "")):
            errors.append(f"{slug}: missing or invalid item_id")
        elif item_id in ids:
            errors.append(f"{slug}: duplicate item_id {item_id}")
        ids.add(item_id)
        for source in source_entries(metadata):
            relative = source.get("source_file") or source.get("file")
            recorded = source.get("sha256")
            if not relative or not recorded:
                errors.append(f"{slug}: incomplete source provenance")
                continue
            source_path = path.parent / relative
            if not source_path.is_file():
                errors.append(f"{slug}: missing {relative}")
            elif sha256(source_path) != recorded:
                errors.append(f"{slug}: checksum mismatch for {relative}")
        for index, stage in enumerate(STAGES, start=1):
            if not (path.parent / "work" / f"{index:02d}-{stage}.md").is_file():
                errors.append(f"{slug}: missing {stage} workbook")
    index_path = root / "papers" / "index.csv"
    if index_path.exists():
        with index_path.open(encoding="utf-8-sig", newline="") as stream:
            index_slugs = [row["slug"] for row in csv.DictReader(stream)]
        ordered = []
        for path, data in iter_metadata(root):
            item = str(data.get("item_id", ""))
            number = item.removeprefix("PF-")
            if item.startswith("PF-") and number.isdigit():
                ordered.append((int(number), path.parent.name))
        expected = [slug for _, slug in sorted(ordered)]
        if index_slugs != expected:
            errors.append("papers/index.csv does not match item_id order; run rebuild-index")
    return errors


def resolve_item(value: str, root: Path = ROOT) -> tuple[Path, dict]:
    target = value.upper()
    for path, metadata in iter_metadata(root):
        if metadata.get("item_id", "").upper() == target or path.parent.name == value:
            return path.parent, metadata
    raise KeyError(f"Unknown item: {value}")


def query_library(query: str, root: Path = ROOT) -> list[dict]:
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_-]+", query) if len(term) > 1]
    results = []
    for path, metadata in iter_metadata(root):
        item_dir = path.parent
        chunks = [json.dumps(metadata.get("identity", {}), ensure_ascii=False)]
        for candidate in [item_dir / "README.md", item_dir / "work" / "extracted.txt"]:
            if candidate.exists():
                chunks.append(candidate.read_text(encoding="utf-8", errors="replace"))
        haystack = "\n".join(chunks).lower()
        score = sum(haystack.count(term) for term in terms)
        if score:
            results.append({"item_id": metadata.get("item_id"), "slug": item_dir.name, "title": (metadata.get("identity") or {}).get("title", metadata.get("title")), "score": score})
    return sorted(results, key=lambda item: (-item["score"], item["item_id"] or ""))


def load_config(root: Path, name: str) -> dict:
    return json.loads((root / "config" / name).read_text(encoding="utf-8"))


def approver_name(portfolio: dict) -> str:
    """The human whose explicit decision effective dispositions and exports need (config/portfolio.json)."""
    return str(portfolio.get("approver") or "owner")


def evidence_class_for(work_type: str | None, root: Path) -> str | None:
    """The approved evidence class for a work_type, or None when the map has no row (validate_v2 then reports it)."""
    try:
        table = load_config(root, "evidence-class-map.json").get("work_type_to_evidence_class") or {}
    except (OSError, ValueError):
        return None
    return table.get(work_type)


def assess_item(args: argparse.Namespace, root: Path = ROOT) -> tuple[dict, list[str], bool]:
    """Create or revise an assessment. Returns (document, errors, written)."""
    paper_dir, metadata = resolve_item(args.item, root)
    portfolio = load_config(root, "portfolio.json")
    today = args.date or date.today().isoformat()
    approver = approver_name(portfolio)
    assessor = args.assessor or f"assistant with {approver} review"
    path = paper_dir / "assessment.json"
    existing = assessment_contract.load_assessment(path)
    endeavor_keys = [key for key, value in (portfolio.get("endeavors") or {}).items() if value.get("active")]
    if args.draft is None:
        if existing and not args.dry_run:
            raise ValueError("an assessment exists; pass --from <draft.json> with --reason to revise it")
        document = existing or assessment_contract.empty_assessment(metadata["item_id"], assessor, today, endeavor_keys)
        return document, [], False
    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    if not isinstance(draft, dict):
        raise ValueError("draft must be a JSON object")
    base = existing or assessment_contract.empty_assessment(metadata["item_id"], assessor, today, endeavor_keys)
    if existing:
        if not args.reason:
            raise ValueError("revising an existing assessment requires --reason")
        merged = assessment_contract.merge_draft(existing, {k: v for k, v in draft.items() if k not in {"revision", "history"}})
        document = assessment_contract.revise(existing, merged, assessor, today, args.reason)
    else:
        document = assessment_contract.merge_draft(base, {k: v for k, v in draft.items() if k not in {"revision", "history"}})
        document["item_id"] = metadata["item_id"]
        document["assessed_at"] = today
        # --assessor wins over a draft's assessor field (defect found 2026-09-04); the draft value stands only when no flag is given.
        document["assessor"] = args.assessor or draft.get("assessor") or assessor
        document["revision"] = 1
        document["history"] = []
    errors = assessment_contract.validate_document(document, metadata, portfolio, str(path))
    if document.get("assessment_version") == 2 and document.get("status") == "assessed" and assessment_contract.disposition_value(document) in {"Apply", "Test", "Hold", "Retire"} and document.get("assessor") != approver:
        errors.append(f"These effective dispositions require the approver's explicit decision; record --assessor {approver} only with authorization")
    if errors or args.dry_run:
        return document, errors, False
    path.write_text(assessment_contract.dump_assessment(document), encoding="utf-8")
    return document, [], True


def intake_item(args: argparse.Namespace, root: Path = ROOT):
    """Persist an assistant draft or failure against a captured ID; never recapture or approve."""
    paper_dir, metadata = resolve_item(args.item, root)
    today = args.date or date.today().isoformat()
    existing = assessment_contract.load_assessment(paper_dir / "assessment.json")
    if existing and existing.get("status") in {"assessed", "declined"}:
        raise ValueError("Preserve existing rulings: revise through assess with an explicit reason")
    base = existing or intake_contract.pending_assessment(metadata, today)
    if not args.draft and not args.failure:
        return base, [], False
    if args.draft and args.failure:
        raise ValueError("Use --from or --failure, not both")
    if args.failure:
        update = {"status": "failed", "intake": {"failure": args.failure,
            "next_action": f"Repair assessment failure; retry pf.py intake {metadata['item_id']} --from <draft.json>."}}
    else:
        try:
            update = json.loads(Path(args.draft).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            if not args.dry_run:
                retry = argparse.Namespace(**vars(args))
                retry.draft, retry.failure = None, f"Draft could not be read: {error}"
                document, _, written = intake_item(retry, root)
                return document, [str(error)], written
            return base, [str(error)], False
        if not isinstance(update, dict):
            update = {"status": "draft", "intake": {"idea": None}}
        if update.get("status", "draft") != "draft":
            raise ValueError("intake only accepts draft judgments")
        fields = update.get("intake", {})
        if not isinstance(fields, dict):
            fields = {"idea": None}
        update = {**update, "status": "draft", "intake": {**fields, "failure": None}}
    for key in ("revision", "history", "item_id", "assessor", "assessed_at"):
        update.pop(key, None)
    document = assessment_contract.merge_draft(base, update)
    document["assessment_version"] = 2
    if existing:
        document = assessment_contract.revise(existing, document, args.assessor or "Codex", today, args.reason or "Intake assessment attempt")
    else:
        document["assessor"] = args.assessor or "Codex"
    errors = assessment_contract.validate_document(document, metadata, load_config(root, "portfolio.json"))
    if not errors:
        for app in (document.get("recommendation") or {}).get("applications", []):
            for item_id in app["item_ids"]:
                try:
                    resolve_item(item_id, root)
                except (ValueError, FileNotFoundError, KeyError) as error:
                    errors.append(str(error))
    if errors:
        if args.dry_run or args.failure:
            return document, errors, False
        retry = argparse.Namespace(**vars(args))
        retry.draft, retry.failure = None, "Rejected intake draft: " + "; ".join(errors)
        failure, _, written = intake_item(retry, root)
        return failure, errors, written
    if args.dry_run:
        return document, errors, False
    path = paper_dir / "assessment.json"
    # Atomic replacement keeps the last valid assessment if writing is interrupted.
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(assessment_contract.dump_assessment(document), encoding="utf-8")
    temporary.replace(path)
    return document, [], True


def classify_item(args: argparse.Namespace, root: Path = ROOT) -> tuple[dict, bool]:
    """Set topics and/or work_type (which fixes evidence_class through the approved map). Returns (changes, written)."""
    paper_dir, metadata = resolve_item(args.item, root)
    taxonomy = load_config(root, "taxonomy.json")
    mapping = load_config(root, "evidence-class-map.json")
    changes: dict = {}
    if args.topics:
        topics = list(dict.fromkeys(args.topics))
        unknown = sorted(set(topics) - set(taxonomy.get("topics") or []))
        if unknown:
            raise ValueError(f"topics not in config/taxonomy.json: {unknown}")
        if "Unclassified" in topics and topics != ["Unclassified"]:
            raise ValueError("Unclassified must be the only topic")
        changes["topics"] = topics
    if args.work_type:
        table = mapping.get("work_type_to_evidence_class") or {}
        if args.work_type not in table:
            raise ValueError(f"work_type {args.work_type!r} is not in the approved evidence-class map; rule the map first")
        changes["work_type"] = args.work_type
        changes["evidence_class"] = table[args.work_type]
        if "paper_type" in metadata:
            changes["paper_type"] = args.work_type
    if not changes:
        raise ValueError("nothing to classify: pass --topics and/or --work-type")
    if args.dry_run:
        return changes, False
    metadata.update(changes)
    (paper_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changes, True


def git_head(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def apply_item(args: argparse.Namespace, root: Path = ROOT) -> tuple[dict, str, bool]:
    """Produce a source-backed export package and receipt. Never writes to the target system."""
    paper_dir, metadata = resolve_item(args.item, root)
    assessment = assessment_contract.load_assessment(paper_dir / "assessment.json")
    if not assessment:
        raise ValueError(f"{metadata['item_id']} has no assessment; run `pf.py assess` before exporting")
    assessment_errors = assessment_contract.validate_document(assessment, metadata, load_config(root, "portfolio.json"))
    if assessment_errors:
        raise ValueError("Invalid assessment: " + "; ".join(assessment_errors))
    gate = assessment_contract.safety_gate(assessment, metadata)
    if gate["blocked"]:
        raise ValueError(f"{metadata['item_id']} is blocked: {gate['reason']}")
    if gate["effective_disposition"] not in {"Apply", "Test"}:
        raise ValueError(f"{metadata['item_id']} has disposition {gate['effective_disposition']!r}; only Apply or Test items export")
    if "security" in (assessment.get("safety_flags") or []) and not assessment.get("threat_review"):
        raise ValueError(f"{metadata['item_id']} is security-flagged and needs a threat_review before export")
    application = None
    proposal = getattr(args, "proposal", None)
    if proposal is not None:
        applications = (assessment.get("recommendation") or {}).get("applications", [])
        if proposal < 1 or proposal > len(applications):
            raise ValueError("--proposal must select a one-based application index")
        application = applications[proposal - 1]
        if application['destination'] != args.to:
            raise ValueError("proposal destination differs from --to")
        if set(application['item_ids']) != set([metadata['item_id']] + (args.also or [])):
            raise ValueError("proposal sources differ from item plus --also")
        if application['project_path'] != args.repo_path:
            raise ValueError("proposal project_path differs from --repo-path")
    portfolio = load_config(root, "portfolio.json")
    if args.to not in (portfolio.get("allowed_export_targets") or []):
        raise ValueError(f"target must be one of {portfolio.get('allowed_export_targets')}")
    if args.repo_path and ledger_contract.ABSOLUTE.match(args.repo_path):
        raise ValueError("repo_path must be repository-relative, never absolute")
    exports = ledger_contract.read_ledger(ledger_contract.exports_path(root))
    receipt_id = ledger_contract.next_receipt_id(exports, ledger_contract.EXPORT_PREFIX)
    today = args.date or date.today().isoformat()
    receipt = {
        "receipt_id": receipt_id,
        "item_ids": [metadata["item_id"]] + [i for i in (args.also or []) if i != metadata["item_id"]],
        "target": args.to,
        "repo_path": args.repo_path,
        "commit": git_head(root),
        "record_id": args.record_id,
        "recommendation": args.recommendation,
        "evidence_boundary": args.evidence_boundary,
        "confidence": args.confidence or "medium",
        "exported": today,
        "approval_status": "approved" if args.approve else "pending",
        "outcome_status": "none",
        "package": f"ledger/exports/{receipt_id}.md",
    }
    if application:
        receipt["application"] = application
        receipt["item_ids"] = list(application["item_ids"])
    items = []
    for item_id in receipt["item_ids"]:
        item_dir, item_metadata = resolve_item(item_id, root)
        if item_metadata.get("provenance_status") == "failed":
            raise ValueError(f"{item_id}: failed integrity blocks inclusion in an export")
        for source in source_entries(item_metadata):
            source_path = item_dir / (source.get("source_file") or source.get("file") or "")
            if not source_path.is_file() or sha256(source_path) != source.get("sha256"):
                raise ValueError(f"{item_id}: source checksum failed before export")
        item_metadata = dict(item_metadata)
        item_metadata["_assessment"] = assessment_contract.load_assessment(item_dir / "assessment.json") or {}
        items.append(item_metadata)
    package = ledger_contract.render_package(receipt, items)
    if args.dry_run:
        return receipt, package, False
    (root / receipt["package"]).parent.mkdir(parents=True, exist_ok=True)
    (root / receipt["package"]).write_text(package, encoding="utf-8")
    ledger_contract.append_entry(ledger_contract.exports_path(root), receipt)
    return receipt, package, True


def outcome_item(args: argparse.Namespace, root: Path = ROOT) -> tuple[dict, bool]:
    """Record a measured outcome against an export receipt; optionally revise the item's assessment."""
    exports = ledger_contract.read_ledger(ledger_contract.exports_path(root))
    export = next((e for e in exports if e.get("receipt_id") == args.export), None)
    if not export:
        raise ValueError(f"unknown export receipt {args.export}")
    try:
        start, end = args.period.split(":", 1)
        date.fromisoformat(start); date.fromisoformat(end)
    except (ValueError, AttributeError):
        raise ValueError("--period must be START:END with ISO dates")
    for artifact in args.artifact or []:
        if ledger_contract.ABSOLUTE.match(artifact):
            raise ValueError("source artifacts must be repository-relative paths, never absolute")
    outcomes = ledger_contract.read_ledger(ledger_contract.outcomes_path(root))
    receipt_id = ledger_contract.next_receipt_id(outcomes, ledger_contract.OUTCOME_PREFIX)
    today = args.date or date.today().isoformat()
    assessment_change = None
    if args.assessment_draft:
        item_id = export["item_ids"][0]
        paper_dir, _ = resolve_item(item_id, root)
        before = assessment_contract.load_assessment(paper_dir / "assessment.json") or {}
        if not args.dry_run:
            document, errors, written = assess_item(argparse.Namespace(item=item_id, draft=args.assessment_draft, assessor=args.assessor, date=today, reason=args.reason or f"Outcome {receipt_id}", dry_run=False), root)
            if errors:
                raise ValueError("assessment revision failed: " + "; ".join(errors))
            assessment_change = {"item_id": item_id, "revision_before": before.get("revision"), "revision_after": document["revision"]}
        else:
            assessment_change = {"item_id": item_id, "revision_before": before.get("revision"), "revision_after": (before.get("revision") or 0) + 1}
    receipt = {
        "receipt_id": receipt_id,
        "export_id": export["receipt_id"],
        "observation_period": {"start": start, "end": end},
        "expected_outcome": args.expected,
        "observed_outcome": args.observed,
        "measurement_method": args.method,
        "uncertainty": args.uncertainty,
        "source_artifacts": list(args.artifact or []),
        "assessment_change": assessment_change,
        "recorded": today,
    }
    if args.dry_run:
        return receipt, False
    ledger_contract.append_entry(ledger_contract.outcomes_path(root), receipt)
    return receipt, True


def approve_export(args: argparse.Namespace, root: Path = ROOT) -> tuple[dict, bool]:
    """Append a PFD decision receipt for an export (approve or decline). Never rewrites the export line."""
    exports = ledger_contract.read_ledger(ledger_contract.exports_path(root))
    export = next((e for e in exports if e.get("receipt_id") == args.export), None)
    if not export:
        raise ValueError(f"unknown export receipt {args.export}")
    decision = "declined" if args.decline else "approved"
    reason = (args.reason or "").strip() or None
    if decision == "declined" and not reason:
        raise ValueError("a decline needs --reason")
    if not (args.by or "").strip():
        raise ValueError("--by must name the deciding human")
    approvals = ledger_contract.read_ledger(ledger_contract.approvals_path(root))
    current = ledger_contract.effective_approval(export, ledger_contract.latest_decisions(approvals))
    if current == decision:
        raise ValueError(f"{args.export} is already {decision}; nothing to append")
    decided = args.date or date.today().isoformat()
    try:
        date.fromisoformat(decided)
    except (TypeError, ValueError):
        raise ValueError("--date must be an ISO-8601 date")
    receipt = {
        "receipt_id": ledger_contract.next_receipt_id(approvals, ledger_contract.APPROVAL_PREFIX),
        "export_id": export["receipt_id"],
        "decision": decision,
        "decided": decided,
        "decided_by": args.by.strip(),
        "reason": reason,
    }
    package_path = (root / str(export.get("package") or "")).resolve()
    exports_dir = (root / "ledger" / "exports").resolve()
    if exports_dir not in package_path.parents or not package_path.is_file():
        raise ValueError(f"{args.export} package {export.get('package')!r} must be an existing file under ledger/exports/")
    if args.dry_run:
        return receipt, False
    ledger_contract.append_entry(ledger_contract.approvals_path(root), receipt)
    with package_path.open("a", encoding="utf-8") as handle:
        handle.write(ledger_contract.render_approval_note(receipt))
    return receipt, True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture", help="Preserve one supported source and create a routed workbook")
    capture.add_argument("source", nargs="?", help="Local path or HTTP(S) URL")
    capture.add_argument("--text", help="Verbatim pasted text instead of a path or URL")
    capture.add_argument("--filename", help="Preserved filename for --text")
    capture.add_argument("--title", required=True)
    capture.add_argument("--authors", default="", help="Semicolon-separated creators when known")
    capture.add_argument("--year", type=int)
    capture.add_argument("--published")
    capture.add_argument("--retrieved")
    capture.add_argument("--url", help="Canonical URL for a local snapshot")
    capture.add_argument("--version")
    capture.add_argument("--source-commit", help="Supplied source commit identifier; recorded, not externally verified")
    capture.add_argument("--language", default="en")
    capture.add_argument("--access-scope")
    capture.add_argument("--kind", choices=["paper", "article", "toolkit", "note", "document", "image", "media"])
    capture.add_argument("--work-type", default="unknown")
    capture.add_argument("--route", choices=sorted(ROUTES), default="capture")
    capture.add_argument("--purpose")
    capture.add_argument("--feynman", choices=["off", "standard", "blank_sheet"], default="off",
                         help="Optional exercise; off by default. blank_sheet requires selection before human source exposure.")
    capture.add_argument("--slug")
    capture.add_argument("--captured-via", choices=sorted(CAPTURE_SURFACES), default="claude-code")
    capture.add_argument("--decline", choices=sorted(DECLINE_REASONS), help="Record a declined source without preserving it")

    subparsers.add_parser("rebuild-index", help="Regenerate papers/index.csv from metadata")
    subparsers.add_parser("validate", help="Validate schema, checksums, workbooks, IDs, and registry order")
    status = subparsers.add_parser("status", help="Show one item's route and state")
    status.add_argument("item")
    query = subparsers.add_parser("query", help="Run deterministic keyword search across the local library")
    query.add_argument("terms", nargs="+")
    assess = subparsers.add_parser("assess", help="Create or revise an item assessment; prints a null draft without --from")
    assess.add_argument("item")
    assess.add_argument("--from", dest="draft", help="JSON draft (partial allowed) merged onto the null draft or the existing assessment")
    assess.add_argument("--assessor", help="Recorded assessor; name a human for gated applications")
    assess.add_argument("--date", help="ISO date; defaults to today")
    assess.add_argument("--reason", help="Revision reason; required when an assessment already exists")
    assess.add_argument("--dry-run", action="store_true", help="Validate and print; write nothing")
    intake = subparsers.add_parser("intake", help="Draft or retry an assessment for an existing captured ID; no model calls")
    intake.add_argument("item")
    intake.add_argument("--from", dest="draft")
    intake.add_argument("--failure", help="Record a failed assessment attempt and preserve the captured source")
    intake.add_argument("--assessor")
    intake.add_argument("--date")
    intake.add_argument("--reason")
    intake.add_argument("--dry-run", action="store_true")
    classify = subparsers.add_parser("classify", help="Set topics and/or work_type (evidence_class follows the approved map)")
    classify.add_argument("item")
    classify.add_argument("--topics", nargs="+")
    classify.add_argument("--work-type")
    classify.add_argument("--dry-run", action="store_true")
    apply = subparsers.add_parser("apply", help="Write a source-backed export package and receipt for a configured target (never writes to it)")
    apply.add_argument("item")
    apply.add_argument("--to", required=True, help="Target key from config/portfolio.json allowed_export_targets")
    apply.add_argument("--recommendation", required=True)
    apply.add_argument("--evidence-boundary", required=True, dest="evidence_boundary")
    apply.add_argument("--confidence", choices=["low", "medium", "high"])
    apply.add_argument("--record-id", dest="record_id", help="Decision number, registry id, or row key in the target when known")
    apply.add_argument("--repo-path", dest="repo_path", help="Repository-relative path in the target; never absolute")
    apply.add_argument("--proposal", type=int, help="One-based application proposal index; destination, path, and source IDs must match")
    apply.add_argument("--also", nargs="*", help="Additional cited item ids")
    apply.add_argument("--approve", action="store_true", help="The approver's explicit approval; otherwise the receipt is pending")
    apply.add_argument("--date")
    apply.add_argument("--dry-run", action="store_true")
    approve = subparsers.add_parser("approve", help="Append the approver's approve/decline decision for an export receipt (PFD ledger; the export line is never rewritten)")
    approve.add_argument("export", help="Export receipt id, e.g. PFX-0001")
    approve.add_argument("--by", required=True, help="The deciding human, as named in config/portfolio.json approver")
    approve.add_argument("--decline", action="store_true", help="Record a decline instead of an approval (needs --reason)")
    approve.add_argument("--reason", help="Why; required for a decline, optional for an approval")
    approve.add_argument("--date")
    approve.add_argument("--dry-run", action="store_true")
    outcome = subparsers.add_parser("outcome", help="Record a measured outcome against an export receipt")
    outcome.add_argument("export", help="Export receipt id, e.g. PFX-0001")
    outcome.add_argument("--expected", required=True)
    outcome.add_argument("--observed", required=True)
    outcome.add_argument("--method", required=True)
    outcome.add_argument("--uncertainty", required=True)
    outcome.add_argument("--period", required=True, help="START:END ISO dates")
    outcome.add_argument("--artifact", action="append", help="Repository-relative artifact path (repeatable)")
    outcome.add_argument("--assessment-draft", dest="assessment_draft", help="JSON draft applied as an assessment revision")
    outcome.add_argument("--assessor")
    outcome.add_argument("--reason")
    outcome.add_argument("--date")
    outcome.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = ROOT
    if "--root" in argv:  # global: pf.py --root DIR <command> ...
        i = argv.index("--root")
        root = Path(argv[i + 1]).expanduser().resolve()
        del argv[i:i + 2]
    known = {"capture", "rebuild-index", "validate", "status", "query", "assess", "intake", "classify", "apply", "approve", "outcome"}
    if argv and argv[0] not in known and not argv[0].startswith("-"):
        argv.insert(0, "capture")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capture":
            if args.decline:
                receipt, appended = decline_capture(args, root)
                print(json.dumps({"status": "declined" if appended else "previously_declined", "appended": appended, "decline": receipt}, indent=2, ensure_ascii=False))
            else:
                destination = create_item(args, root)
                metadata = json.loads((destination / "metadata.json").read_text(encoding="utf-8"))
                print(json.dumps({"item_id": metadata["item_id"], "path": str(destination), "source": metadata["sources"][0], "route": metadata["route"]["name"], "next_action": metadata["state"]["next_action"]}, indent=2, ensure_ascii=False))
        elif args.command == "rebuild-index":
            print(f"rebuilt papers/index.csv with {rebuild_index(root)} items")
        elif args.command == "validate":
            errors = validate_repository(root)
            if errors:
                print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
                return 1
            print("Paper Forge validation passed")
        elif args.command == "status":
            _, metadata = resolve_item(args.item, root)
            print(json.dumps({"item_id": metadata.get("item_id"), "identity": metadata.get("identity"), "route": metadata.get("route"), "state": metadata.get("state")}, indent=2, ensure_ascii=False))
        elif args.command == "query":
            print(json.dumps(query_library(" ".join(args.terms), root), indent=2, ensure_ascii=False))
        elif args.command == "intake":
            document, errors, written = intake_item(args, root)
            print(json.dumps({"document": document, "errors": errors, "written": written}, indent=2, ensure_ascii=False))
            return 1 if errors else 0
        elif args.command == "assess":
            document, errors, written = assess_item(args, root)
            if errors:
                print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
                print(json.dumps(document, indent=2, ensure_ascii=False))
                return 1
            if written:
                print(json.dumps({"item_id": document["item_id"], "revision": document["revision"], "disposition": document["disposition"], "application_state": document["application_state"], "path": f"papers/{resolve_item(args.item, root)[0].name}/assessment.json"}, indent=2, ensure_ascii=False))
            else:
                print(json.dumps(document, indent=2, ensure_ascii=False))
        elif args.command == "apply":
            receipt, package, written = apply_item(args, root)
            print(json.dumps({"receipt": receipt, "written": written}, indent=2, ensure_ascii=False))
            if not written:
                print(package)
        elif args.command == "approve":
            receipt, written = approve_export(args, root)
            print(json.dumps({"receipt": receipt, "written": written}, indent=2, ensure_ascii=False))
        elif args.command == "outcome":
            receipt, written = outcome_item(args, root)
            print(json.dumps({"receipt": receipt, "written": written}, indent=2, ensure_ascii=False))
        elif args.command == "classify":
            changes, written = classify_item(args, root)
            print(json.dumps({"item_id": resolve_item(args.item, root)[1]["item_id"], "changes": changes, "written": written}, indent=2, ensure_ascii=False))
    except (FileNotFoundError, FileExistsError, ValueError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

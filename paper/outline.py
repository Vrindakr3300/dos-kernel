#!/usr/bin/env python
"""Add a real PDF outline (the bookmark/navigation tree) to the rendered paper.

Chrome headless `--print-to-pdf` renders the figures cleanly but emits **no**
document outline -- the reader's bookmark sidebar comes up empty, and a long paper
has no navigation. This step adds one, *after* render.py, by:

  1. parsing the section headings from the SAME source assemble.py renders
     (`meta.section_files()`, in the same NN_ order) -- so the outline is
     re-derived from the prose on every build, never hand-maintained;
  2. finding which physical PDF page each heading landed on, by matching the
     heading's text against pypdf's per-page text extraction (Chrome discards
     HTML anchors, so the heading TEXT is the join key, not a named destination);
  3. writing a nested outline with pypdf (h2 -> top level, h3 -> child,
     h4 -> grandchild), each bookmark pointing at the page the heading is on.

Modular contract (mirrors render.py / embed.py):
  * edit prose            -> sections/NN_*.html   (the outline follows automatically)
  * add / reorder a head  -> just add the <h2>/<h3>; it appears in the outline
  * rebuild               -> python paper/build.py   (this runs as the last PDF step)

Fail-loud, like the broken-<img> guard in build.py: if a heading cannot be located
on any page, that is reported and the build step fails rather than shipping a
silently-incomplete outline. Usage:

    python paper/outline.py                 # paper/paper.pdf, in place
    python paper/outline.py in.pdf out.pdf  # explicit
"""
from __future__ import annotations

import html
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make `import meta` work from any cwd
import meta as M  # noqa: E402

from pypdf import PdfReader, PdfWriter  # noqa: E402

# Headings up to this level become outline entries. h2 = section, h3 = subsection,
# h4 = sub-subsection (Appendix B/C go three deep). Anything deeper is body detail.
MAX_LEVEL = 4

# One <h2>..</h2> / <h3>..</h3> / <h4>..</h4> block, capturing the level digit, the
# attributes (unused -- kept for readability of the group structure) and inner HTML.
_HEADING_RE = re.compile(r"<h([2-4])\b([^>]*)>(.*?)</h\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")            # strip inner markup (<em>, <code>, ...)
_PAGEHDR_RE = re.compile(r"^\s*\d+\s*/\s*\d+\s*")  # the "N / 27" Chrome running header

# Unicode punctuation Chrome bakes into extracted text, folded to ASCII for matching.
_DASHES = "‐‑‒–—―−"          # hyphen .. minus
_SQUOTES = "‘’‚‛′"                      # curly single + prime
_DQUOTES = "“”„‟″"                      # curly double + dprime


def _label(text: str) -> str:
    """The human-readable bookmark label: strip inner markup, decode entities, and
    squeeze whitespace -- but PRESERVE source case and punctuation, so the sidebar
    reads exactly as the heading is written (e.g. 'Appendix A. DOS in plain words')."""
    text = _TAG_RE.sub("", text)            # drop <em>/<code>/... inside a heading
    text = html.unescape(text)              # &ldquo; -> curly-quote, &amp; -> &
    text = unicodedata.normalize("NFKC", text)  # also folds NBSP -> space
    return re.sub(r"\s+", " ", text).strip()


def _matchkey(text: str) -> str:
    """The page-location compare key: fold the unicode punctuation Chrome bakes in
    (curly quotes, en/em dashes) to ASCII and casefold. Case-insensitive because CSS
    text-transform / small-caps mean the RENDERED case need not match the source (the
    abstract box renders <h2>Abstract</h2> as 'ABSTRACT'); punctuation-folded because
    the PDF may encode a dash as U+2014 / U+2013 / a hyphen. Only the MATCH folds --
    the label keeps its real case (see _label). Accepts either a pre-cleaned label or
    raw page text (which still carries tags/entities)."""
    if "<" in text or "&" in text:          # raw page/heading text -- clean it first
        text = _label(text)
    else:
        text = unicodedata.normalize("NFKC", text)
    for ch in _DASHES:
        text = text.replace(ch, "-")
    for ch in _SQUOTES:
        text = text.replace(ch, "'")
    for ch in _DQUOTES:
        text = text.replace(ch, '"')
    return re.sub(r"\s+", " ", text).strip().casefold()


def _headings_from_html(src: str) -> list[tuple[int, str]]:
    """(level, label) for every h2..h{MAX_LEVEL} in one HTML string, in document order."""
    out: list[tuple[int, str]] = []
    for m in _HEADING_RE.finditer(src):
        level = int(m.group(1))
        if level > MAX_LEVEL:
            continue
        label = _label(m.group(3))
        if label:
            out.append((level, label))
    return out


def parse_headings() -> list[tuple[int, str]]:
    """(level, label) for every h2..h{MAX_LEVEL}, in render order. The label is the
    display string; page-location derives its own fold-key from it via _matchkey.

    Prefers the ASSEMBLED paper.html (M.HTML_OUT) -- it is the prose AFTER
    numbering.py has run, so a body label carries the same auto-number the reader
    sees on the page ('2. The benchmark and the three detectors'), and the headings
    are already in one document-order stream (the abstract heading first, then the
    body). assemble.py always runs before this step in build.py, so paper.html is
    present. Falls back to the raw sections/*.html fragments (un-numbered, but same
    order) if paper.html is absent -- e.g. running outline.py standalone on an old
    PDF -- so the tool still works without a fresh assemble."""
    if M.HTML_OUT.exists():
        heads = _headings_from_html(M.HTML_OUT.read_text(encoding="utf-8"))
        if heads:
            return heads
    out: list[tuple[int, str]] = []
    for f in M.section_files():
        out.extend(_headings_from_html(f.read_text(encoding="utf-8")))
    return out


def _page_texts(reader: PdfReader) -> list[str]:
    """Per-page fold-key text, with the 'N / 27' running header stripped first."""
    pages = []
    for pg in reader.pages:
        raw = pg.extract_text() or ""
        raw = _PAGEHDR_RE.sub("", raw)
        pages.append(_matchkey(raw))
    return pages


def locate_pages(labels: list[tuple[int, str]], page_texts: list[str]) -> list[int]:
    """Map each heading to its 0-based page index by text search.

    Monotonic: headings appear in document order, so the search for heading i starts
    at the page heading i-1 was found on (a later heading is never on an earlier
    page). This also disambiguates a short heading whose text recurs in the body --
    we take the first occurrence at or after the previous heading, which is the
    heading itself, not a later back-reference. Returns -1 for an unlocatable
    heading (the caller reports and fails)."""
    pages: list[int] = []
    cursor = 0
    for _level, label in labels:
        key = _matchkey(label)
        found = -1
        for i in range(cursor, len(page_texts)):
            if key in page_texts[i]:
                found = i
                break
        if found == -1:
            # looser fallback on a long prefix, in case extraction split a word at a
            # column break partway through the heading itself
            probe = key[:40]
            for i in range(cursor, len(page_texts)):
                if probe and probe in page_texts[i]:
                    found = i
                    break
        pages.append(found)
        if found != -1:
            cursor = found  # never search backwards for the next heading
    return pages


def build_outline(pdf_path: Path, out_path: Path) -> int:
    headings = parse_headings()
    if not headings:
        raise SystemExit("outline: no h2..h4 headings found in sections/ -- nothing to bookmark")

    reader = PdfReader(str(pdf_path))
    page_texts = _page_texts(reader)
    page_idx = locate_pages(headings, page_texts)

    missing = [h for (h, p) in zip(headings, page_idx) if p == -1]
    if missing:
        for _level, label in missing:
            print(f"  ! outline: heading not located on any page: {label!r}", file=sys.stderr)
        raise SystemExit(f"outline: {len(missing)} heading(s) could not be placed -- "
                         f"the PDF text did not contain them (did render.py run?)")

    writer = PdfWriter()
    writer.append(reader)  # carries pages + any existing structure

    # Walk the (level, page) list, maintaining a parent stack so h3s nest under the
    # preceding h2 and h4s under the preceding h3. parents[d] is the most recent
    # outline item added at depth d (= level-2): parents[0]=h2, parents[1]=h3.
    parents: dict[int, object] = {}
    placed = 0
    for (level, label), pidx in zip(headings, page_idx):
        depth = level - 2  # h2 -> 0, h3 -> 1, h4 -> 2
        parent = parents.get(depth - 1) if depth > 0 else None
        item = writer.add_outline_item(label, pidx, parent=parent)
        parents[depth] = item
        for deeper in [d for d in parents if d > depth]:  # invalidate stale deeper parents
            parents.pop(deeper, None)
        placed += 1

    # show the bookmarks panel when the PDF opens (UseOutlines) -- cosmetic, best-effort
    try:
        writer.page_mode = "/UseOutlines"
    except Exception:
        pass

    with open(out_path, "wb") as fh:
        writer.write(fh)
    return placed


def main() -> None:
    here = Path(__file__).resolve().parent
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "paper.pdf"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src
    src = src.resolve()
    out = out.resolve()
    if not src.exists():
        raise SystemExit(f"outline: source PDF not found: {src} (run render.py first)")

    placed = build_outline(src, out)
    pages = len(PdfReader(str(out)).pages)
    print(f"outline: {placed} bookmarks written to {out.name} ({pages} pages)")


if __name__ == "__main__":
    main()

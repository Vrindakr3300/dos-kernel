#!/usr/bin/env python
"""Assemble paper.html from the title block + per-section HTML fragments.

The build is modular: prose lives in paper/sections/NN_*.html, and everything
non-prose (title, date, figure-width registry, section order) lives in paper/meta.py.
This script only stitches — it has no content of its own. Edit prose in the fragments,
edit the title/figures in meta.py, then run `python paper/build.py` (or this + render.py).

The abstract is pulled out of the first fragment and rendered in a full-width box; the
rest flows two-column. Wide figures and wide tables are tagged to span both columns.

Section, figure, and table NUMBERS are not written in the prose — the fragments carry
stable symbolic keys (data-sec / data-fig / data-tbl) and reference them as {{sec:KEY}}
/ {{fig:KEY}} / {{tbl:KEY}}; numbering.py assigns the real numbers in document order over
the whole assembled body and substitutes them, so a reorder can never desync a number.
"""
import re

import meta as M  # paper/meta.py — the single source of truth for the build
import numbering  # the auto-numbering + cross-reference resolver (document-order)


def tag_wide_figures(html: str) -> str:
    """Add class="wide" to <figure> blocks whose <img> references a wide fig (per meta.WIDE_FIGS)."""
    def repl(m: re.Match) -> str:
        block = m.group(0)
        if any(name in block for name in M.WIDE_FIGS):
            if "class=" in block.split(">", 1)[0]:
                block = re.sub(r"(<figure[^>]*class=\")", r"\1wide ", block, count=1)
            else:
                block = block.replace("<figure", '<figure class="wide"', 1)
        return block

    return re.sub(r"<figure\b.*?</figure>", repl, html, flags=re.DOTALL)


def widen_tables(html: str) -> str:
    """Tag obviously-wide tables (>=6 columns) to span both columns for legibility."""
    def repl(m: re.Match) -> str:
        block = m.group(0)
        header = block.split("</tr>", 1)[0]
        ncols = header.count("<th")
        if ncols >= 6 and "class=" not in block.split(">", 1)[0]:
            block = block.replace("<table", '<table class="wide"', 1)
        return block

    return re.sub(r"<table\b.*?</table>", repl, html, flags=re.DOTALL)


def split_abstract(html: str) -> tuple[str, str]:
    """Split the abstract off the first fragment so it can render full-width.

    Prefers an explicit <!--ABSTRACT--> ... <!--/ABSTRACT--> marker (robust, the
    recommended form for new edits); falls back to the legacy <h2>Abstract</h2>..</p>
    heuristic so an un-marked fragment still works. Returns (abstract_html, rest_html).
    """
    m = re.search(r"<!--\s*ABSTRACT\s*-->(.*?)<!--\s*/ABSTRACT\s*-->", html, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip(), (html[: m.start()] + html[m.end():]).strip()
    m = re.search(r"(<h2>\s*Abstract\s*</h2>.*?</p>)", html, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1), html[m.end():]
    return "", html


def main() -> None:
    abstract_html = ""
    body_parts = []
    for f in M.section_files():
        html = f.read_text(encoding="utf-8")
        html = tag_wide_figures(html)
        html = widen_tables(html)
        if not abstract_html:  # the abstract lives in the first fragment that carries one
            abstract_html, html = split_abstract(html)
        body_parts.append(html)

    body = "\n".join(body_parts)
    _SPLIT = "<!--__ABSTRACT_BODY_SPLIT__-->"
    # Citations first: resolve every {{cite:KEY}} to a numbered link (off meta.REFERENCES,
    # not document order) and learn which keys were actually cited, so we can both (a) drop a
    # References section that lists exactly those works and (b) fail the build on a dead
    # reference (one declared but cited nowhere). This runs before the numbering pass so the
    # appended References <section> is numbered like any other section. We carry the sentinel
    # through the citation pass so the split is by-marker, not by-length (the link expansion
    # changes the abstract's byte length).
    combined, cited = numbering.resolve_citations(abstract_html + _SPLIT + body, M.REFERENCES)
    abstract_html, body = combined.split(_SPLIT, 1)
    references_html = numbering.render_references(M.REFERENCES, cited)
    if references_html:
        body = body + "\n" + references_html
    # Now resolve numbering over the WHOLE document in VISUAL order (abstract first — it holds
    # Figure 1 — then the body + the References section), so a {{fig:…}} in §2 can reference a
    # figure declared in §6 and the hero figure in the abstract is numbered 1. We splice the
    # two regions with the same sentinel, resolve once, then split back so each renders in its
    # own box. The resolver fails the build on a duplicate anchor or a dangling reference.
    combined = numbering.number_and_resolve(abstract_html + _SPLIT + body, M.RUN_FACTS)
    abstract_html, body = combined.split(_SPLIT, 1)

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{M.TITLE}</title>
<link rel="stylesheet" href="style.css"/>
</head>
<body>
<div class="titleblock">
  <h1>{M.TITLE}</h1>
  <p class="subtitle">{M.SUBTITLE}</p>
  <p class="byline">{M.BYLINE}</p>
  <p class="meta">{M.DATE} · Reproducible from <code>{M.REPRO_ROOT}</code> ·
     every number recomputable offline from <code>{M.REPRO_ROWS}</code></p>
</div>

<div class="abstract-wrap">
{abstract_html}
</div>

<div class="paper-body">
{body}
</div>

</body>
</html>
"""
    M.HTML_OUT.write_text(doc, encoding="utf-8")
    print(f"assembled {M.HTML_OUT}  ({len(doc)} bytes, {len(M.section_files())} sections)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Generate the arXiv LaTeX sources from the SAME prose the HTML paper is built from.

The paper has ONE source of truth: ``paper/sections/NN_*.html`` (+ ``paper/meta.py``
for the numbers). The HTML paper is assembled by ``assemble.py``; this module is its
twin for the LaTeX/arXiv rendering. It converts each ``sections/NN_*.html`` fragment to
``arxiv/sections/NN_*.tex`` by the rules documented in ``arxiv/_CONVERSION_SPEC.md`` —
deterministically, no model in the loop — so the arXiv paper can never drift from the
HTML one. Re-run it (it is part of ``build.py``) and the ``.tex`` regenerate.

WHY this kills the drift the hand-port suffered
-----------------------------------------------
The original ``arxiv/sections/*.tex`` were a one-time manual port and immediately fell
behind (a §6.4 number the HTML had corrected, a whole §6.6 the HTML had added). The fix
is the repo's own doctrine, applied to the second rendering: a derived artifact is
GENERATED, never hand-edited. The decisive single-sourcing is the fact tokens — a
``{{fact:KEY}}`` resolves to ``meta.RUN_FACTS[KEY]`` here exactly as it does in the HTML
build (``numbering.resolve_tokens``), so every live-run number lives in ONE place
(``meta.py``) and both renderings read it. Section/figure/table NUMBERS are not copied at
all: the HTML resolver assigns them in document order, and LaTeX/cleveref assigns them
from ``\\label``/``\\cref`` — each rendering numbers itself, so neither can desync.

WHAT stays hand-authored (NOT generated)
----------------------------------------
``main.tex`` (preamble, title block, ``\\input`` list, bibliography), ``refs.bib``, and
the two READMEs are scaffolding, not prose, and are left alone. Only the per-section
bodies are generated. The generated files carry a "DO NOT EDIT" banner.

    python paper/assemble_arxiv.py            # regenerate arxiv/sections/*.tex
    python paper/assemble_arxiv.py --check    # fail (exit 1) if any .tex is stale
"""
from __future__ import annotations

import argparse
import html as _html
import re
import sys
from pathlib import Path

import meta as M  # paper/meta.py — the single source of truth (RUN_FACTS, WIDE_FIGS, sections)

ARXIV_DIR = M.HERE / "arxiv"
ARXIV_SECTIONS = ARXIV_DIR / "sections"

_BANNER = (
    "% !!! GENERATED FILE - DO NOT EDIT !!!\n"
    "% Produced from paper/sections/{src} by paper/assemble_arxiv.py\n"
    "% (rules in arxiv/_CONVERSION_SPEC.md). Edit the .html source + meta.py, then\n"
    "% rerun `python paper/build.py` (or `python paper/assemble_arxiv.py`).\n"
)

NBSP = " "  # the &nbsp; glyph, used in a couple of source captions/labels


# --------------------------------------------------------------------------------------
# Inline conversion: HTML entities + tags + the {{...}} token policy.
# --------------------------------------------------------------------------------------

# HTML entity -> LaTeX.
_ENTITY = {
    "&ldquo;": "``", "&rdquo;": "''",
    "&lsquo;": "`", "&rsquo;": "'",
    "&mdash;": "---", "&ndash;": "--",
    "&minus;": "$-$",
    "&nbsp;": "~",
    "&sect;": r"\S",
    "&times;": r"$\times$",
    "&rarr;": r"$\rightarrow$",
    "&hellip;": r"\dots",
    "&Delta;": r"$\Delta$",
    "&asymp;": r"$\approx$",
    "&ge;": r"$\ge$", "&le;": r"$\le$",
    "&deg;": r"$^\circ$",
    "&middot;": r"$\cdot$",
    "&starf;": r"$\star$",
    "&amp;": r"\&",
    "&lt;": "<", "&gt;": ">",
}

# Unicode glyphs that appear directly in the UTF-8 prose, and their LaTeX forms.
_GLYPH = {
    "—": "---", "–": "--", "−": "$-$",
    "“": "``", "”": "''", "‘": "`", "’": "'",
    "…": r"\dots",
    "≈": r"$\approx$", "≥": r"$\ge$", "≤": r"$\le$",
    "×": r"$\times$", "→": r"$\rightarrow$", "§": r"\S",
    "·": r"$\cdot$", "Δ": r"$\Delta$",
    "★": r"$\star$", "☆": r"$\star$",
}


def _resolve_tokens(text: str) -> str:
    """Apply the {{...}} policy: facts -> literal value; sec/fig/tbl -> \\cref{...}.

    A reference written as "Figure&nbsp;{{fig:x}}" / "Table&nbsp;{{tbl:x}}" / "&sect;{{sec:x}}"
    collapses to a bare \\cref (cleveref supplies the word "Figure"/"section" itself). We strip
    the redundant leading label word + its nbsp first, then map each token.
    """
    text = re.sub(r"(?:Figure|Fig\.|Table|Tbl\.)\s*&nbsp;\s*(\{\{(?:fig|tbl):)", r"\1", text)
    text = re.sub(r"&sect;\s*(\{\{sec:)", r"\1", text)
    text = re.sub(rf"(?:Figure|Fig\.|Table|Tbl\.)[ {NBSP}]+(\{{\{{(?:fig|tbl):)", r"\1", text)
    text = re.sub(rf"§[ {NBSP}]*(\{{\{{sec:)", r"\1", text)

    def repl(m: re.Match) -> str:
        kind, key = m.group("kind"), m.group("key")
        if kind == "fact":
            if key not in M.RUN_FACTS:
                raise SystemExit(f"arxiv: unknown {{{{fact:{key}}}}} (not in meta.RUN_FACTS)")
            return _escape_literals(M.RUN_FACTS[key])
        label = key.replace(".", "-")
        label = ("tab:" + label) if kind == "tbl" else f"{kind}:{label}"
        return rf"\cref{{{label}}}"

    text = re.sub(r"\{\{(?P<kind>sec|fig|tbl|fact):(?P<key>[^}]+)\}\}", repl, text)

    # {{cite:KEY}} -> \cite{KEY}; the bibliography is generated from meta.REFERENCES, so an
    # unknown key here would later dangle in BibTeX — fail now, at the same boundary as a bad
    # {{fact:}}. (BibTeX cite-keys carry no LaTeX-special chars, so no escaping is needed.)
    _ref_keys = {ref.key for ref in M.REFERENCES}

    def _cite_repl(m: re.Match) -> str:
        key = m.group("key")
        if key not in _ref_keys:
            raise SystemExit(f"arxiv: unknown {{{{cite:{key}}}}} (not in meta.REFERENCES)")
        return rf"\cite{{{key}}}"

    return re.sub(r"\{\{cite:(?P<key>[^}]+)\}\}", _cite_repl, text)


_LITERAL_ESCAPE = {"%": r"\%", "#": r"\#", "&": r"\&", "_": r"\_", "$": r"\$"}


def _escape_literals(s: str) -> str:
    """Escape LaTeX-special literals in a plain-text run (used for resolved fact values)."""
    return "".join(_LITERAL_ESCAPE.get(ch, ch) for ch in s)


def _code_inner(s: str) -> str:
    r"""Escape the inside of a \code{...}: _ # $ % & { } and backslash all need handling."""
    s = _html.unescape(s)
    for ch, esc in (("\\", r"\textbackslash{}"), ("_", r"\_"), ("#", r"\#"),
                    ("$", r"\$"), ("%", r"\%"), ("&", r"\&"), ("{", r"\{"), ("}", r"\}")):
        s = s.replace(ch, esc)
    return s


# Escape %, #, and a "naked" & that come from prose; leave entity/macro forms alone.
_PROSE_SPECIALS = re.compile(
    r"(?<!\\)%"
    r"|(?<!\\)\#"
    r"|(?<!\\)&(?!nbsp;|amp;|ldquo;|rdquo;|lsquo;|rsquo;|mdash;|ndash;|minus;|sect;"
    r"|times;|rarr;|hellip;|Delta;|asymp;|ge;|le;|deg;|lt;|gt;)"
)


def _escape_prose_specials(text: str) -> str:
    text = _PROSE_SPECIALS.sub(lambda m: "\\" + m.group(0), text)
    # Bare underscores in prose (e.g. "tool_stream" written outside <code>). In text mode a
    # raw _ is a LaTeX error. \code bodies are sentinel-protected here, and the LaTeX we have
    # already emitted (\cref/\label keys are dot->hyphen, \textbf/\emph, $..$ math) carries no
    # literal underscore, so escaping every remaining bare _ is safe.
    return re.sub(r"(?<!\\)_", r"\\_", text)


def _inline(text: str, *, escape: bool = True) -> str:
    r"""Convert an inline HTML run to LaTeX: tags, entities, glyphs, quotes, literal escaping."""
    # 0a) escape a source-literal "$" (a dollar amount like $0 / $4.77) to \$ BEFORE we
    #     insert any $..$ math of our own (steps 0b/4); after this point every bare $ is ours.
    text = re.sub(r"\$(?=[\d])", r"\\$", text)

    # 0b) literal "~N" means approximately-N in the source (e.g. ~1,004); convert NOW, before
    #     &nbsp; -> ~ (step 4) makes the two indistinguishable.
    text = re.sub(r"~(?=[\d\\])", r"$\\sim$", text)

    # 1) tokens first (they may sit adjacent to label words we strip)
    text = _resolve_tokens(text)

    # 2) <code>…</code> -> \code{…} with verbatim-escaped body, sentinel-protected so later
    #    prose-escaping does not touch it.
    code_slots: list[str] = []

    def _code_repl(m: re.Match) -> str:
        code_slots.append(rf"\code{{{_code_inner(m.group(1))}}}")
        return f"\x00CODE{len(code_slots) - 1}\x00"

    text = re.sub(r"<code>(.*?)</code>", _code_repl, text, flags=re.DOTALL)

    # 3) emphasis + sub/sup
    text = re.sub(r"<strong>(.*?)</strong>", lambda m: rf"\textbf{{{m.group(1)}}}", text, flags=re.DOTALL)
    text = re.sub(r"<em>(.*?)</em>", lambda m: rf"\emph{{{m.group(1)}}}", text, flags=re.DOTALL)
    text = re.sub(r"<sub>(.*?)</sub>", lambda m: rf"$_{{{m.group(1)}}}$", text, flags=re.DOTALL)
    text = re.sub(r"<sup>(.*?)</sup>", lambda m: rf"$^{{{m.group(1)}}}$", text, flags=re.DOTALL)

    # 3b) strip incidental inline/block tags that can nest in a run (a <p> inside a
    #     <blockquote>, a stray <span>/<a>/<br>). Multi-<p> -> blank-line-separated paragraphs.
    text = re.sub(r"</p>\s*<p\b[^>]*>", "\n\n", text)
    text = re.sub(r"</?(?:span|a|br|p)\b[^>]*>", "", text)

    # 3c) straight ASCII quotes -> LaTeX curly quotes (the source mixes &ldquo;/&rdquo; with
    #     bare "double"/'single' quotes). Code bodies are already sentinel-protected.
    text = re.sub(r'(^|[\s(\[{~]|---|--)"', r"\1``", text)
    text = text.replace('"', "''")
    text = re.sub(r"(^|[\s(\[{~])'", r"\1`", text)

    # 4) entities -> LaTeX
    for ent, rep in _ENTITY.items():
        text = text.replace(ent, rep)

    # 5) escape stray literal specials in the remaining prose
    if escape:
        text = _escape_prose_specials(text)

    # 6) unicode glyphs (after literal escaping so a literal "&" in glyph output stays)
    for g, rep in _GLYPH.items():
        text = text.replace(g, rep)

    # 7) restore code slots
    for i, slot in enumerate(code_slots):
        text = text.replace(f"\x00CODE{i}\x00", slot)

    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    return text.strip()


# --------------------------------------------------------------------------------------
# Block conversion: figures, tables, lists, headings, paragraphs.
# --------------------------------------------------------------------------------------

def _strip_caption_label(cap: str, word: str) -> str:
    """Drop a leading caption label so LaTeX's \\caption supplies its own number.

    Two forms occur: the body's auto-numbered token ("Figure&nbsp;{{fig:KEY}}." /
    "Table&nbsp;{{tbl:KEY}}.") and the appendix's hand-written label ("Figure A2." /
    "Table C1."). Both are stripped; LaTeX prints "Figure N."/"Table N." itself. (The
    appendix's A/B/C numbering vs LaTeX's running number is a known submission-time
    reconciliation noted in arxiv/README.md — we match the hand-port's clean-caption choice
    rather than invent a divergent scheme.)
    """
    cap = re.sub(rf"^\s*{word}[ {NBSP}]*\{{\{{(?:fig|tbl):[^}}]+\}}\}}\.\s*", "", cap)
    cap = re.sub(rf"^\s*{word}\s+[A-C]\d+\.\s*", "", cap)
    return cap


def _convert_figure(block: str) -> str:
    """<figure data-fig=X [class=wide]><img src=figs/Y.png ...><figcaption>Z</figcaption></figure>.

    Some <figure>s wrap a <table> instead of an <img> (an HTML-layout idiom, e.g. the
    appendix reproduction tables). In LaTeX a table float is the right container, so we
    delegate those to the table converter and drop the redundant figure wrapper, folding a
    trailing <figcaption> in as the table caption if the table lacks its own <caption>.
    """
    if "<table" in block and "<img" not in block:
        tbl = re.search(r"<table\b.*?</table>", block, flags=re.DOTALL).group(0)
        if "<caption" not in tbl:
            cap_m = re.search(r"<figcaption>(.*?)</figcaption>", block, flags=re.DOTALL)
            if cap_m:
                tbl = re.sub(r"(<table\b[^>]*>)",
                             rf"\1<caption>{cap_m.group(1)}</caption>", tbl, count=1)
        return _convert_table(tbl)

    key_m = re.search(r'data-fig="([^"]+)"', block)
    img_m = re.search(r'<img\s+[^>]*src="figs/([^"]+?)(?:\.png)?"', block, flags=re.DOTALL)
    cap_m = re.search(r"<figcaption>(.*?)</figcaption>", block, flags=re.DOTALL)
    key = key_m.group(1) if key_m else "unknown"
    img = img_m.group(1) if img_m else "MISSING"
    caption = _inline(_strip_caption_label(cap_m.group(1) if cap_m else "", "Figure"))
    wide = "wide" in re.search(r"<figure[^>]*>", block).group(0)
    env = "figure*" if wide else "figure"
    width = r"\textwidth" if wide else r"\linewidth"
    return (
        f"\\begin{{{env}}}[t]\n"
        f"  \\centering\n"
        f"  \\includegraphics[width={width}]{{{img}}}\n"
        f"  \\caption{{{caption}}}\n"
        f"  \\label{{fig:{key}}}\n"
        f"\\end{{{env}}}"
    )


def _split_cells(row: str) -> list[str]:
    return [c.strip() for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, flags=re.DOTALL)]


def _convert_table(block: str) -> str:
    """<table data-tbl=X [class=wide]> [<caption>..] <thead?> rows </table> -> booktabs."""
    key_m = re.search(r'data-tbl="([^"]+)"', block)
    key = key_m.group(1) if key_m else "unknown"
    cap_m = re.search(r"<caption>(.*?)</caption>", block, flags=re.DOTALL)
    caption = _inline(_strip_caption_label(cap_m.group(1), "Table")) if cap_m else ""

    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", block, flags=re.DOTALL)
    if not rows:
        return ""
    header_is_th = "<th" in rows[0]
    header = _split_cells(rows[0]) if header_is_th else []
    body = [_split_cells(r) for r in (rows[1:] if header_is_th else rows)]
    ncol = max([len(header)] + [len(r) for r in body]) if (header or body) else 0

    def col_is_numeric(j: int) -> bool:
        vals = [r[j] for r in body if j < len(r)]
        if not vals:
            return False
        num = sum(1 for v in vals
                  if re.fullmatch(r"[\s$+\-—–]*[\d.,/%pp×x()\s]+", _html.unescape(v).strip() or "x"))
        return num >= max(1, len(vals)) * 0.6

    spec = "".join("l" if j == 0 or not col_is_numeric(j) else "r" for j in range(ncol))

    def fmt_row(cells: list[str]) -> str:
        cells = (cells + [""] * ncol)[:ncol]
        return " & ".join(_inline(c) for c in cells) + r" \\"

    lines = [r"\begin{table}[t]", r"  \centering"]
    if caption:
        lines.append(rf"  \caption{{{caption}}}")
    lines.append(rf"  \label{{tab:{key}}}")
    if "wide" in re.search(r"<table[^>]*>", block).group(0) and ncol >= 6:
        lines.append(r"  \footnotesize")
    lines.append(rf"  \begin{{tabular}}{{{spec}}}")
    lines.append(r"    \toprule")
    if header:
        lines.append("    " + fmt_row(header))
        lines.append(r"    \midrule")
    for r in body:
        lines.append("    " + fmt_row(r))
    lines.append(r"    \bottomrule")
    lines.append(r"  \end{tabular}")
    lines.append(r"\end{table}")
    return "\n".join(lines)


def _convert_list(block: str, ordered: bool) -> str:
    env = "enumerate" if ordered else "itemize"
    items = re.findall(r"<li\b[^>]*>(.*?)</li>", block, flags=re.DOTALL)
    out = [rf"\begin{{{env}}}"]
    out += [rf"  \item {_inline(it)}" for it in items]
    out.append(rf"\end{{{env}}}")
    return "\n".join(out)


def _convert_blockquote(block: str) -> str:
    inner = re.search(r"<blockquote>(.*?)</blockquote>", block, flags=re.DOTALL).group(1)
    # a blockquote may wrap a <pre> (code) — render that as verbatim, the rest as prose.
    if "<pre" in inner:
        return "\\begin{quote}\n" + _blocks_to_tex(inner) + "\n\\end{quote}"
    return "\\begin{quote}\n" + _inline(inner) + "\n\\end{quote}"


def _convert_pre(block: str) -> str:
    r"""<pre><code>…</code></pre> -> \begin{verbatim}…\end{verbatim} (content kept literally).

    verbatim takes its body byte-for-byte (no escaping), which is exactly right for shell
    commands carrying \, --, _ etc. We only unescape HTML entities the source used inside
    the code (&amp; / &lt; / &gt;) and strip the inner <code> wrapper.
    """
    inner = re.search(r"<pre\b[^>]*>(.*?)</pre>", block, flags=re.DOTALL).group(1)
    inner = re.sub(r"</?code\b[^>]*>", "", inner)
    inner = _html.unescape(inner)
    return "\\begin{verbatim}\n" + inner.strip("\n") + "\n\\end{verbatim}"


def _heading(tag: str, attrs: str, text: str) -> str:
    """h2/h3/h4 -> section/subsection/subsubsection, with a \\label if it carries data-sec."""
    key_m = re.search(r'data-sec="([^"]+)"', attrs)
    level = {"h2": "section", "h3": "subsection", "h4": "subsubsection"}.get(tag, "subsection")
    title = _inline(text)
    label = rf"\label{{sec:{key_m.group(1).replace('.', '-')}}}" if key_m else ""
    return rf"\{level}{{{title}}}{label}"


_ABSTRACT_RE = re.compile(r"<!--\s*ABSTRACT\s*-->(.*?)<!--\s*/ABSTRACT\s*-->", re.DOTALL | re.IGNORECASE)

# A <div> is a layout wrapper with no LaTeX analogue; we recurse into its contents. The
# pattern allows ONE level of nested <div> inside (enough for this corpus's endnote box).
_BLOCK_RE = re.compile(
    r"(?P<div><div\b[^>]*>(?P<dinner>(?:[^<]|<(?!/?div\b)|<div\b[^>]*>.*?</div>)*)</div>)"
    r"|(?P<figure><figure\b.*?</figure>)"
    r"|(?P<table><table\b.*?</table>)"
    r"|(?P<pre><pre\b.*?</pre>)"
    r"|(?P<ol><ol\b.*?</ol>)"
    r"|(?P<ul><ul\b.*?</ul>)"
    r"|(?P<quote><blockquote\b.*?</blockquote>)"
    r"|(?P<heading><(?P<htag>h[2-4])\b(?P<hattrs>[^>]*)>(?P<htext>.*?)</(?P=htag)>)"
    r"|(?P<para><p\b[^>]*>(?P<ptext>.*?)</p>)",
    re.DOTALL,
)


def _blocks_to_tex(html: str) -> str:
    out: list[str] = []
    for m in _BLOCK_RE.finditer(html):
        if m.group("div"):
            out.append(_blocks_to_tex(m.group("dinner")))  # recurse: a div is just a wrapper
        elif m.group("figure"):
            out.append(_convert_figure(m.group("figure")))
        elif m.group("table"):
            out.append(_convert_table(m.group("table")))
        elif m.group("pre"):
            out.append(_convert_pre(m.group("pre")))
        elif m.group("ol"):
            out.append(_convert_list(m.group("ol"), ordered=True))
        elif m.group("ul"):
            out.append(_convert_list(m.group("ul"), ordered=False))
        elif m.group("quote"):
            out.append(_convert_blockquote(m.group("quote")))
        elif m.group("heading"):
            out.append(_heading(m.group("htag"), m.group("hattrs") or "", m.group("htext")))
        elif m.group("para"):
            txt = _inline(m.group("ptext"))
            if txt:
                out.append(txt)
    return "\n\n".join(out)


def convert_section(src_html: str, *, is_first: bool) -> str:
    """Convert one section fragment's HTML body to a LaTeX body (no preamble)."""
    html = src_html
    abstract_tex = ""
    if is_first:
        m = _ABSTRACT_RE.search(html)
        if m:
            abstract_tex = "\\begin{abstract}\n" + _blocks_to_tex(m.group(1)) + "\n\\end{abstract}\n\n"
            html = html[: m.start()] + html[m.end():]
    return (abstract_tex + _blocks_to_tex(html)).strip() + "\n"


# --------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------

def _target_for(src: Path) -> Path:
    return ARXIV_SECTIONS / (src.stem + ".tex")


def render_all() -> dict[Path, str]:
    """Return {target_path: tex_content} for every section, without writing."""
    out: dict[Path, str] = {}
    for i, src in enumerate(M.section_files()):
        body = convert_section(src.read_text(encoding="utf-8"), is_first=(i == 0))
        out[_target_for(src)] = _BANNER.format(src=src.name) + "\n" + body
    return out


_REFS_BIB = ARXIV_DIR / "refs.bib"

_BIB_BANNER = (
    "% !!! GENERATED FILE - DO NOT EDIT !!!\n"
    "% Produced from paper/meta.py:REFERENCES by paper/assemble_arxiv.py (docs/264).\n"
    "% The bibliography is single-sourced in meta.REFERENCES -- the HTML build renders it as a\n"
    "% numbered References list, this build projects it to BibTeX. Edit meta.REFERENCES, then\n"
    "% rerun `python paper/build.py` (or `python paper/assemble_arxiv.py`).\n"
    "%\n"
    "% References for \"Verification Is All You Need -- But Not Where You Think\".\n"
)

# BibTeX value escaping: a handful of LaTeX specials that may appear in a title/note. We keep
# math ($\tau^2$), \url{}, and \" accents intact (the source authored them deliberately), so
# we escape only the unambiguous prose specials that are not already backslash-led, plus the
# Unicode dash/quote glyphs (so a literal — in a note becomes ---, matching the body's policy).
_BIB_ESCAPE_RE = re.compile(r"(?<!\\)([%#&_])")
_BIB_GLYPH = {"—": "---", "–": "--", "−": "$-$", "“": "``", "”": "''",
              "‘": "`", "’": "'", "…": r"\dots", "×": r"$\times$"}


def _bib_value(s: str) -> str:
    for g, rep in _BIB_GLYPH.items():
        s = s.replace(g, rep)
    return _BIB_ESCAPE_RE.sub(r"\\\1", s)


def render_bib() -> str:
    """Project meta.REFERENCES into a BibTeX file (the arXiv bibliography).

    Field order is stable (title, author, the type-specific locators, then year, url, note)
    so the generated file is deterministic and diff-friendly — the same reproducibility the
    section .tex have. `ref.bibtex` supplies/overrides the type-specific fields (journal,
    publisher, eprint, …); `entry_type` picks the @type."""
    # Fields whose value is authored as raw LaTeX/URL and must NOT be prose-escaped.
    _RAW = {"howpublished", "archivePrefix", "url"}
    out = [_BIB_BANNER]
    for ref in M.REFERENCES:
        extra = dict(ref.bibtex or {})
        fields: list[tuple[str, str]] = [
            ("title", ref.title),
            ("author", ref.authors),
        ]
        # type-specific locators first (journal/volume/pages, publisher, institution/number,
        # eprint/archivePrefix, howpublished), pulled from ref.bibtex in a stable order.
        for k in ("journal", "volume", "number", "pages", "booktitle", "publisher",
                  "institution", "eprint", "archivePrefix", "howpublished"):
            if k in extra:
                fields.append((k, extra.pop(k)))
        fields.append(("year", ref.year))
        if ref.url:
            fields.append(("url", ref.url))
        # any remaining custom fields (e.g. note) in sorted order for determinism
        for k in sorted(extra):
            fields.append((k, extra[k]))
        # escape prose specials in every field except the raw-LaTeX ones (math like
        # $\tau^2$ and \" accents survive: _bib_value only touches un-backslashed %#&_).
        body = ",\n".join(
            f"  {k:<13}= {{{v if k in _RAW else _bib_value(v)}}}" for k, v in fields
        )
        out.append(f"@{ref.entry_type}{{{ref.key},\n{body}\n}}")
    return "\n\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate arxiv/sections/*.tex from sections/*.html")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any generated .tex differs from disk (no write)")
    args = ap.parse_args()

    rendered = render_all()
    rendered[_REFS_BIB] = render_bib()  # the bibliography is a generated artifact too
    if args.check:
        stale = [p for p, c in rendered.items()
                 if not p.exists() or p.read_text(encoding="utf-8") != c]
        if stale:
            print("arxiv files STALE (regenerate with `python paper/assemble_arxiv.py`):")
            for p in stale:
                print(f"  {p.relative_to(M.REPO)}")
            sys.exit(1)
        print(f"arxiv: all {len(rendered)} generated files up to date")
        return

    ARXIV_SECTIONS.mkdir(parents=True, exist_ok=True)
    for p, content in rendered.items():
        p.write_text(content, encoding="utf-8")
    print(f"arxiv: generated {len(rendered) - 1} section .tex + refs.bib "
          f"in {ARXIV_DIR.relative_to(M.REPO)}")


if __name__ == "__main__":
    main()

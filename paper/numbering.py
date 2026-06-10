#!/usr/bin/env python
"""Auto-numbering + cross-reference resolver for the paper build.

The paper never hardcodes a section, figure, or table number. Instead every numbered
thing carries a *stable symbolic key*, and this module assigns the actual numbers in
document order at build time, then substitutes them everywhere they are referenced. The
payoff: reorder a section, drop a figure, insert a subsection — and every number (and
every cross-reference to it) updates itself, with no chance of the duplicate-"Figure 9"
or "§7.1 under §8" drift that hand-numbering invites.

THE MARKUP (what a section fragment writes)
-------------------------------------------
Declare an anchor once, on the element itself:

    <h2 data-sec="payoff">The headline: an out-of-loop referee …</h2>
    <h3 data-sec="payoff.witness">The target and the witness</h3>
    <figure data-fig="crossmodel" class="wide"> … <figcaption>Figure {{fig:crossmodel}}. …</figcaption></figure>
    <table data-tbl="detectors"><caption>Table {{tbl:detectors}}. …</caption></table>

Reference it anywhere (same or another fragment):

    … the live payoff (&sect;{{sec:payoff}}) …
    … see Fig.&nbsp;{{fig:crossmodel}} …
    … the spend was {{fact:spend_writeadmit}} …

RESOLUTION RULES
----------------
* Sections are numbered in document order. A *body* section (`data-sec` with no dot)
  gets 1, 2, 3, …; an *appendix* section (its heading text starts with "Appendix") gets
  A, B, C, …. A subsection key contains a dot (`payoff.witness`) and inherits its parent's
  number with a running minor index (6.1, 6.2, …; A.1, A.2, …). The parent must be declared
  before its children (document order guarantees this for well-formed prose).
* Figures and tables each get an independent counter in pure document order: the Nth
  <figure data-fig=…> to appear is Figure N (appendix figures continue as A1, A2, … when
  they live in an appendix section — matching the existing "Figure A1/B1" convention).
* The heading text is rewritten to carry the number ("6. The headline …") and a stable
  `id` ("sec-payoff") so in-page links work. Figures/tables get an `id` too ("fig-crossmodel").
* {{sec:KEY}} / {{fig:KEY}} / {{tbl:KEY}} / {{fact:KEY}} tokens are replaced by the number
  (or the fact string). An unknown KEY, a duplicate anchor, or a dangling reference raises —
  the build fails loudly rather than shipping a wrong or blank number.
* {{cite:KEY}} tokens are replaced by a numbered superscript link ([N]) to a generated
  References list, where N is the reference's position in meta.REFERENCES (docs/264). A
  {{cite:KEY}} with no entry in REFERENCES — or a REFERENCES entry no prose cites — raises,
  the same loud-failure discipline as a dangling {{fig:}}. The References list is rendered
  by `render_references()` and appended to the body by the assembler.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


class NumberingError(SystemExit):
    """A reference/anchor problem that must fail the build (not ship a wrong number)."""


# data-sec / data-fig / data-tbl anchor on an opening tag. Captures the tag name, the
# kind (sec|fig|tbl), the key, and the full opening-tag span so we can rewrite its id.
_ANCHOR_RE = re.compile(
    r'<(?P<tag>h[1-6]|figure|table)\b(?P<pre>[^>]*?)\sdata-(?P<kind>sec|fig|tbl)="(?P<key>[^"]+)"(?P<post>[^>]*)>',
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"\{\{(?P<kind>sec|fig|tbl|fact):(?P<key>[^}]+)\}\}")
_CITE_RE = re.compile(r"\{\{cite:(?P<key>[^}]+)\}\}")
# The visible heading number is prepended to the heading's text; figures/tables render
# their own "Figure {{fig:KEY}}." in the caption, so we only stamp an id on those.


@dataclass
class _Registry:
    sec: dict[str, str] = field(default_factory=dict)
    fig: dict[str, str] = field(default_factory=dict)
    tbl: dict[str, str] = field(default_factory=dict)

    def put(self, kind: str, key: str, value: str) -> None:
        table = getattr(self, kind)
        if key in table:
            raise NumberingError(
                f"duplicate anchor data-{kind}=\"{key}\" — every {kind} key must be unique"
            )
        table[key] = value


def _is_appendix_heading(open_tag_end: int, html: str) -> bool:
    """True if the heading text right after `open_tag_end` begins with 'Appendix'."""
    tail = html[open_tag_end:open_tag_end + 40].lstrip()
    return tail[:8].lower() == "appendix"


def assign_numbers(html: str, facts: dict[str, str]) -> tuple[str, _Registry]:
    """First pass: walk anchors in document order, assign numbers, rewrite headings + ids.

    Returns the html with headings numbered and anchors carrying ids, plus the populated
    registry the substitution pass uses. Does NOT touch {{…}} tokens yet.
    """
    reg = _Registry()
    body_n = 0            # 1, 2, 3, … for body sections
    appx_n = 0            # 0->A, 1->B, … for appendix sections
    minor: dict[str, int] = {}   # parent section number -> running subsection minor
    cur_parent_num: str | None = None
    cur_is_appendix = False
    fig_n = 0
    tbl_n = 0
    appx_fig_n = 0
    appx_tbl_n = 0

    out = []
    pos = 0
    for m in _ANCHOR_RE.finditer(html):
        out.append(html[pos:m.start()])
        tag, kind, key = m.group("tag").lower(), m.group("kind"), m.group("key")
        pre, post = m.group("pre"), m.group("post")
        # strip the data-* attr from the surviving tag; add a stable id
        clean_attrs = (pre + post).replace(f' data-{kind}="{key}"', "")

        if kind == "sec":
            if "." in key:  # subsection
                if cur_parent_num is None:
                    raise NumberingError(f"subsection data-sec=\"{key}\" appears before any parent section")
                minor[cur_parent_num] = minor.get(cur_parent_num, 0) + 1
                num = f"{cur_parent_num}.{minor[cur_parent_num]}"
            else:           # top-level section
                if _is_appendix_heading(m.end(), html):
                    num = chr(ord("A") + appx_n)
                    appx_n += 1
                    cur_is_appendix = True
                else:
                    body_n += 1
                    num = str(body_n)
                    cur_is_appendix = False
                cur_parent_num = num
            reg.put("sec", key, num)
            sec_id = f"sec-{key.replace('.', '-')}"
            # prepend the number to the heading text (Appendix headings already say
            # "Appendix B …" in prose, so for those we stamp the id only, no number prefix)
            if "." not in key and cur_is_appendix:
                new_open = f"<{tag}{clean_attrs} id=\"{sec_id}\">"
            else:
                new_open = f"<{tag}{clean_attrs} id=\"{sec_id}\">{num}. "
            out.append(new_open)
            pos = m.end()
            continue

        if kind == "fig":
            if cur_is_appendix:
                appx_fig_n += 1
                num = f"{cur_parent_num.split('.')[0]}{appx_fig_n}" if cur_parent_num else f"X{appx_fig_n}"
            else:
                fig_n += 1
                num = str(fig_n)
            reg.put("fig", key, num)
            out.append(f"<{tag}{clean_attrs} id=\"fig-{key}\">")
            pos = m.end()
            continue

        if kind == "tbl":
            if cur_is_appendix:
                appx_tbl_n += 1
                num = f"{cur_parent_num.split('.')[0]}{appx_tbl_n}" if cur_parent_num else f"X{appx_tbl_n}"
            else:
                tbl_n += 1
                num = str(tbl_n)
            reg.put("tbl", key, num)
            out.append(f"<{tag}{clean_attrs} id=\"tbl-{key}\">")
            pos = m.end()
            continue

    out.append(html[pos:])
    return "".join(out), reg


def resolve_tokens(html: str, reg: _Registry, facts: dict[str, str]) -> str:
    """Second pass: substitute every {{sec|fig|tbl|fact:KEY}} with its resolved value."""
    dangling: list[str] = []

    def repl(m: re.Match) -> str:
        kind, key = m.group("kind"), m.group("key")
        table = facts if kind == "fact" else getattr(reg, kind)
        if key not in table:
            dangling.append(f"{{{{{kind}:{key}}}}}")
            return m.group(0)
        return table[key]

    result = _TOKEN_RE.sub(repl, html)
    if dangling:
        uniq = sorted(set(dangling))
        raise NumberingError(
            "unresolved cross-references (no matching anchor/fact):\n  " + "\n  ".join(uniq)
        )
    return result


def cited_numbers(html: str, references) -> dict[str, int]:
    """Map each *cited* reference key -> its 1-based number in the rendered bibliography.

    A reference's number is its position among the **cited** entries, taken in
    `meta.REFERENCES` order (so reordering REFERENCES renumbers, but an uncited entry never
    consumes a number). This is the single source of the [N] both `resolve_citations` (the
    prose links) and `render_references` (the list) use, so they cannot desync: a draft that
    cites only a subset of REFERENCES gets a contiguous 1..k bibliography, and every prose
    [N] points at the matching entry. A {{cite:KEY}} whose KEY is not in REFERENCES is a hard
    error here (a dangling citation)."""
    valid = {ref.key for ref in (references or ())}
    seen: set[str] = set()
    dangling: list[str] = []
    for m in _CITE_RE.finditer(html):
        key = m.group("key")
        if key not in valid:
            dangling.append(f"{{{{cite:{key}}}}}")
        else:
            seen.add(key)
    if dangling:
        raise NumberingError(
            "unresolved citations (no matching key in meta.REFERENCES):\n  "
            + "\n  ".join(sorted(set(dangling)))
        )
    # number in REFERENCES order, but only the cited ones (contiguous 1..k)
    return {ref.key: i for i, ref in enumerate(
        (r for r in (references or ()) if r.key in seen), start=1)}


def resolve_citations(html: str, references) -> tuple[str, set[str]]:
    """Replace every {{cite:KEY}} with a numbered superscript link, and report cited keys.

    KEY must name an entry in `references`; its citation number is its 1-based position
    **among the cited entries** (see `cited_numbers`), so the prose [N] matches the rendered
    bibliography exactly even when REFERENCES carries works this draft does not cite. Returns
    the rewritten html and the set of keys actually cited.

    `references` empty/None ⇒ a {{cite:}} present is a hard error (nowhere to resolve); the
    html is returned unchanged when there are no citations.
    """
    numbers = cited_numbers(html, references)

    def repl(m: re.Match) -> str:
        n = numbers[m.group("key")]   # cited_numbers already validated every key
        return f'<sup class="cite"><a href="#ref-{n}">[{n}]</a></sup>'

    return _CITE_RE.sub(repl, html), set(numbers)


def render_references(references, cited: set[str] | None = None) -> str:
    """Render the References section HTML from the ordered `references` list.

    A reference list shows exactly the works the prose cites. When `cited` is given, an
    entry that nothing cites is simply *omitted* from the rendered list (not an error): the
    bibliography is a projection of what `{{cite:}}` actually invokes, so `meta.REFERENCES`
    may carry a superset (works a later draft will cite) without breaking today's build. The
    numbers stay 1-based over the *rendered* (cited) subset, matching the [N] links
    `resolve_citations` emits — both number a reference by its 1-based position in this same
    `REFERENCES` order, so dropping an uncited entry does not desync them as long as the
    rendered list is filtered the same way the [N] map is. (A `{{cite:KEY}}` with no entry in
    REFERENCES is still a hard error — that is a dangling citation, the opposite problem.)
    Returns "" when nothing is cited (the section is simply omitted)."""
    references = [r for r in (references or ()) if cited is None or r.key in cited]
    if not references:
        return ""
    items = []
    for n, ref in enumerate(references, start=1):
        locator = f"{ref.venue}, {ref.year}." if ref.venue else f"{ref.year}."
        title = f"<em>{ref.title}</em>"
        if ref.url:
            title = f'<a href="{ref.url}">{title}</a>'
        items.append(
            f'  <li id="ref-{n}"><span class="ref-n">[{n}]</span> '
            f"{ref.authors}. {title}. {locator}</li>"
        )
    # The data-sec anchor lives on the <h2> (the numbering pass only rewrites headings /
    # figures / tables), so "References" picks up the next section number in document order.
    return (
        '<section class="references">\n'
        '<h2 data-sec="references">References</h2>\n'
        '<ol class="reflist">\n' + "\n".join(items) + "\n</ol>\n</section>"
    )


def number_and_resolve(
    html: str, facts: dict[str, str] | None = None, references=None
) -> str:
    """The whole pipeline: assign numbers in document order, then resolve all tokens.

    If `references` is given, {{cite:}} tokens are resolved too (to numbered links) — but
    the References *section* is appended by the caller (assemble.py) via render_references(),
    so it lands after the body rather than wherever the last citation sits."""
    facts = facts or {}
    numbered, reg = assign_numbers(html, facts)
    resolved = resolve_tokens(numbered, reg, facts)
    if references is not None:
        resolved, _ = resolve_citations(resolved, references)
    return resolved

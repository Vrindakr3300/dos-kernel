#!/usr/bin/env python
"""One-command paper build: refresh figures -> assemble HTML -> render PDF.

    python paper/build.py             # full build (figures + html + pdf + arxiv .tex)
    python paper/build.py --no-pdf    # html (+arxiv) only (skip the Chrome render)
    python paper/build.py --no-figs   # don't re-copy figures from _results/
    python paper/build.py --no-arxiv  # skip regenerating the arxiv/ LaTeX sources

The modular pieces it orchestrates:
  * meta.py          — title, section order, figure registry, fingerprint (edit here)
  * sections/*       — the prose fragments (edit here)
  * assemble.py      — stitches sections + title block -> paper.html
  * assemble_arxiv.py— regenerates arxiv/sections/*.tex from the SAME sections + meta
                       (the arXiv paper is a generated artifact, never hand-edited)
  * render.py        — paper.html -> paper.pdf (headless Chrome)
  * outline.py       — adds the PDF bookmark outline (Chrome emits none), derived from
                       the sections/ headings; runs right after render.py

It also warns (does not fail) if the live durable-rows fingerprint has drifted from
meta.ROWS_FINGERPRINT — a guard that a refreshed paper still cites the data it was
drawn from, the same staleness discipline as `additivity.py --check`.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make `import meta` work from any cwd
import meta as M  # noqa: E402


def refresh_figures() -> int:
    """Copy every figure referenced by a section from its upstream source into figs/.

    Scans the section fragments for `figs/NAME` references, then copies NAME from the
    first FIG_SOURCE_DIR that has it. A referenced figure missing from every source is
    reported (not silently skipped) so a broken <img> is caught at build time."""
    import re

    M.FIGS_DIR.mkdir(exist_ok=True)
    referenced = set()
    for f in M.section_files():
        referenced.update(re.findall(r"figs/([\w.-]+\.(?:png|svg))", f.read_text(encoding="utf-8")))
    copied = missing = 0
    for name in sorted(referenced):
        for src_dir in M.FIG_SOURCE_DIRS:
            src = src_dir / name
            if src.exists():
                shutil.copy2(src, M.FIGS_DIR / name)
                copied += 1
                break
        else:
            if not (M.FIGS_DIR / name).exists():  # only a problem if we also lack a staged copy
                print(f"  ! figure referenced but not found in any source: {name}", file=sys.stderr)
                missing += 1
    print(f"figures: {copied} refreshed, {len(referenced)} referenced"
          + (f", {missing} MISSING" if missing else ""))
    return missing


def check_fingerprint() -> None:
    """Warn if the live durable-rows fingerprint drifts from the one the paper cites."""
    try:
        if str(M.REPO) not in sys.path:
            sys.path.insert(0, str(M.REPO))  # repo root, so `import benchmark...` resolves
        from benchmark.toolathlon.additivity import rows_fingerprint
        live = rows_fingerprint()
    except Exception as e:  # additivity import / rows file absent — non-fatal for a prose rebuild
        print(f"fingerprint: skipped ({e})")
        return
    if live != M.ROWS_FINGERPRINT:
        print(f"  ! ROWS_FINGERPRINT drift: meta says {M.ROWS_FINGERPRINT}, live CSV is {live} "
              f"— update meta.ROWS_FINGERPRINT + the reproducibility section, or regenerate the rows",
              file=sys.stderr)
    else:
        print(f"fingerprint: {live} (matches meta + the paper's reproducibility section) OK")


def run(*args: str) -> None:
    r = subprocess.run([sys.executable, *args], cwd=str(M.HERE))
    if r.returncode != 0:
        raise SystemExit(f"step failed: {' '.join(args)}")


def main(argv: list[str]) -> int:
    no_pdf = "--no-pdf" in argv
    no_figs = "--no-figs" in argv
    no_arxiv = "--no-arxiv" in argv

    if not no_figs:
        refresh_figures()
    check_fingerprint()
    run("assemble.py")
    if not no_arxiv:
        run("assemble_arxiv.py")  # regenerate the arXiv LaTeX from the same sources + meta,
                                  # so the .tex paper can never drift from the HTML one
    if not no_pdf:
        run("render.py")   # PDF first — Chrome embeds the figures at render time
        run("outline.py")  # then add the bookmark outline (Chrome emits none) — derived
                           # from the same sections/ headings; must follow render.py
    # then make the shipped HTML self-contained: inline the CSS + every figure as a
    # data: URI, so paper.html renders its images no matter how it is opened (a moved
    # copy, an HTML previewer, an inline viewer) — not only from paper/ in a browser
    # that resolves the relative figs/ path. Last step: assemble.py rewrites paper.html
    # un-inlined each run, so embedding must follow it (and render.py).
    run("embed.py")
    print("\nbuild complete:", M.HTML_OUT.name + " (self-contained)"
          + ("" if no_pdf else f" + {M.PDF_OUT.name}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

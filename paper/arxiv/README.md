# arXiv LaTeX source

A faithful LaTeX rendering of `paper/paper.html`, ready to compile and submit to arXiv.
Presentation only — every number traces to the same sources as the HTML paper
(`benchmark/toolathlon/replay_all_rows.csv` for the offline study; the
`_VERIFIED_FACTS_*.md` files for the live runs).

> **`sections/*.tex` are GENERATED — do not hand-edit them.** They are produced from the
> single source of truth (`paper/sections/*.html` + `paper/meta.py`) by
> **`paper/assemble_arxiv.py`**, which runs as part of `python paper/build.py`. This is the
> same doctrine as `paper.html`/`paper.pdf`: a derived rendering is regenerated, never
> hand-maintained, so the arXiv paper **cannot drift** from the HTML one (the drift this
> port suffered before — a stale §6.4 number, a missing §6.6 — is now structurally
> impossible). The decisive link is the fact tokens: a `{{fact:KEY}}` resolves to
> `meta.RUN_FACTS[KEY]` here exactly as in the HTML build, so every live-run number lives in
> ONE place. Section/figure/table *numbers* are never copied — cleveref assigns them from
> `\label`/`\cref`, so neither rendering can desync. To change the paper, edit the `.html`
> + `meta.py` and rerun the build; **the only hand-authored files here are `main.tex`,
> `refs.bib`, and the two `.md`** (preamble, bibliography, docs — the scaffolding the
> generator does not touch). Regenerate explicitly with `python paper/assemble_arxiv.py`;
> check for staleness in CI with `python paper/assemble_arxiv.py --check`.

## Build

No LaTeX toolchain is needed locally. Two options:

**Overleaf (easiest):** upload this `arxiv/` directory *and* the `paper/figs/`
directory (the `.tex` references figures at `../figs/`; on Overleaf either keep that
layout or drop the PNGs next to `main.tex` and the second `\graphicspath` entry
`{figs/}` will find them). Compile `main.tex` with pdfLaTeX.

**Local (if you install TeX Live / MacTeX):**
```bash
cd paper/arxiv
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

## Files
- `main.tex` — preamble, title/author block, `\input`s the 9 sections, bibliography. **Hand-authored.**
- `sections/*.tex` — one file per paper section (body only; `\input` into main). **GENERATED** by
  `paper/assemble_arxiv.py` — do not edit (edit the `.html` source instead).
- `refs.bib` — **starter** bibliography (the benchmarks used). **Hand-authored; grow it** — see below.
- `_CONVERSION_SPEC.md` — the HTML→LaTeX rules `assemble_arxiv.py` implements (the generator's spec).
- figures: referenced from `../figs/` (the same PNGs the HTML embeds).

## Verified on every generation (static checks; not a compile)
`assemble_arxiv.py` + the build guarantee these structurally; they are re-checkable on the
generated `sections/*.tex`:
- Every `\cref` resolves to a defined `\label` (0 dangling — a dangling `{{ref}}` fails the HTML build too).
- Every `\includegraphics` target exists in `paper/figs/` (a figure-wrapped table is emitted as a `table`, not a missing image).
- `\begin`/`\end` balanced per file; braces balanced; `$` math balanced (verbatim bodies excluded).
- No leftover HTML entities, `{{placeholders}}`, or tags in the bodies.
- A code block (`<pre>`) becomes `verbatim`; a `{{fact:KEY}}` becomes its `meta.RUN_FACTS` value, not a `\cref`.

## TODO before you submit (author actions)
1. **Compile once on Overleaf** and fix any stragglers a real engine catches
   (the generator is verified statically — balanced envs/braces/math, no leftover
   tags/tokens, faithful word-for-word to the HTML — but not compiled here; no local
   LaTeX). **If the engine flags a section body, fix the rule in `assemble_arxiv.py` (or
   the `.html` source), not the `.tex`** — the `.tex` are regenerated and a hand-edit is
   overwritten on the next build. Only `main.tex` / `refs.bib` are safe to edit by hand.
   The appendix A/B/C float numbers (hand-labelled "Table C1" in prose) currently rely on
   LaTeX's running counter, so reconcile those references on the first compile (the one
   known cosmetic the static checks don't catch).
2. **Author line** (`main.tex`): the byline is "Anthony Chaudhary · DOS" with no
   affiliation. Confirm the name and add any co-authors. A co-author with arXiv
   cs.* history also removes the endorsement gate (next item).
3. **arXiv endorsement**: a first-time cs.* submitter needs an endorsement, and as
   of the 21 Jan 2026 policy an institutional email ALONE is no longer enough — the
   automatic path now needs BOTH an institutional (academic/research) email AND
   prior authorship on a cs.* arXiv paper. With a gmail correspondence address and
   no prior cs.* paper, take the PERSONAL-endorsement path: arXiv issues a
   6-character code at submission; an established cs.* author (≥ the domain's paper
   threshold, counting only papers submitted 3 months–5 years ago) enters it at
   arxiv.org/auth/endorse to vouch for you. Find one via the "Which authors of this
   paper are endorsers?" link on the abstract pages of papers you cite. Allow lead
   time. A co-author with cs.* posting history removes this gate entirely (item 2).
4. **Categories**: cs.SE (primary), cs.AI; optionally cs.DC.
5. **References (`refs.bib`)**: the body names Toolathlon, tau2-bench,
   EnterpriseOps-Gym, ServiceNow, METR but the HTML had no formal reference list.
   Add `\cite{...}` at first mention of each and fill in the real venue/arXiv-id/URL.
   Thin related work is the most common first-author review ding — this is worth an
   afternoon.
6. **Honest framing** (already true in the prose, keep it): lead with the sound live
   results (J = 15/258 over-claims at an identical 8.3% across two models;
   coordination J = 6/8) — all off the environment's own DB-hash. The downstream
   peer-B ΔB result is ≈0 at the immediate hop; do not let any edit inflate it.

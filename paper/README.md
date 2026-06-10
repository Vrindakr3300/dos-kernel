# The out-of-loop-referee paper

A single, self-contained empirical paper assembled from the DOS benchmark studies
(`benchmark/toolathlon/` + `benchmark/agentprocessbench/writeadmit/` + `benchmark/enterpriseops/`),
with all figures embedded.

**Title:** *Verification Is All You Need — But Not Where You Think.* (The twist is the
result: a check the agent cannot forge is harmful handed back to the agent and valuable
handed to the rest of the fleet — the headline is the live out-of-loop payoff, over-claims
blocked and races serialized off ground truth; the Toolathlon replay is the boundary that
earns it.)

This is a **derived artifact**, not a new source of truth. The offline (Toolathlon) numbers
are the canonical figures from `benchmark/toolathlon/additivity.py` (`compute()`,
`--check`-enforced) and the durable rows `…/replay_all_rows.csv`; the live (tau2/EnterpriseOps)
numbers are verbatim read-offs of the paid runs, transcribed into the `_VERIFIED_FACTS_*.md`
files. If either drifts, regenerate this paper rather than hand-editing the numbers.

> **Numbering is automatic.** Section, figure, and table numbers are NOT written in the
> prose — fragments carry stable symbolic keys (`data-sec`/`data-fig`/`data-tbl`) and
> reference them as `{{sec:KEY}}` / `{{fig:KEY}}` / `{{tbl:KEY}}`; `numbering.py` assigns the
> real numbers in document order at build time. Reorder a section or insert a figure and
> every number — and every cross-reference — updates itself. A dangling reference or a
> duplicate key **fails the build**, so the old "two Figure 9s / §7.1 under §8" drift is
> structurally impossible. See "the modular contract" below.

## Files

| File | What it is |
|---|---|
| `paper.pdf` | the rendered paper (Chrome-headless → PDF) — the deliverable |
| `paper.html` | the assembled HTML (what gets rendered) — generated, do not hand-edit |
| `sections/*.html` | **the editable prose** — per-section HTML fragments, rendered in `NN_` sort order. The final fragment is the plain-language appendix (`07_appendix.html`, "DOS in plain words — the Vaseline test"). |
| `meta.py` | **the build's single source of truth** — title/subtitle/byline/date, the wide-figure registry, the figure source dirs, and the durable-rows fingerprint. Edit non-prose HERE. |
| `figs/*.png` | the figures, copied from the `FIG_SOURCE_DIRS` (`benchmark/toolathlon/_results/` + `_diagrams/`, and `paper/figs_src/` for the appendix) so the paper is self-contained (refreshed automatically by `build.py`) |
| `figs_src/*` | **the appendix's own figure sources** — the Vaseline-test diagram and the DOS-kernel/trust-ladder map (Mermaid `.mmd`) and the active-fix bake-off (`appx_fix_bakeoff.py`, matplotlib), each committed alongside its rendered `.png`. See `figs_src/README.md` to regenerate. |
| `style.css` | print-grade two-column stylesheet (academic register, A4) |
| `build.py` | **one-command build**: refresh figures → assemble → render → outline → embed, with a fingerprint-drift guard |
| `assemble.py` | stitches `sections/` + the title block (from `meta.py`) → `paper.html`; runs the numbering resolver over the whole body; tags wide figures/tables; pulls the abstract into its full-width box |
| `numbering.py` | **the auto-numbering + cross-reference resolver** — assigns section/figure/table numbers in document order and substitutes every `{{sec:KEY}}` / `{{fig:KEY}}` / `{{tbl:KEY}}` / `{{fact:KEY}}` token. Fails the build on a dangling reference or duplicate key. |
| `render.py` | renders `paper.html` → `paper.pdf` via headless Chrome (no LaTeX/pandoc/weasyprint on this machine) |
| `outline.py` | **the PDF bookmark outline** — Chrome's `--print-to-pdf` emits none, so this adds a real, nested navigation tree (h2→h3→h4) after render. Labels are read from the assembled `paper.html` (so they carry the same auto-numbers the reader sees) and each bookmark's page is found by matching the heading text against the rendered PDF's per-page text. Fails the build if a heading can't be placed. |
| `embed.py` | inlines the CSS + every figure as a `data:` URI so the shipped `paper.html` is self-contained |

## Rebuild — one command

```bash
python paper/build.py            # refresh figures + assemble HTML + render PDF
python paper/build.py --no-pdf   # HTML only (fast iteration; skip the Chrome render)
python paper/build.py --no-figs  # don't re-copy figures from _results/
```

`build.py` also warns if the live durable-rows fingerprint has drifted from
`meta.ROWS_FINGERPRINT` — a guard that a refreshed paper still cites the data it was
drawn from (the same staleness discipline as `additivity.py --check`).

### How to keep editing it (the modular contract)

- **Edit prose** → edit the relevant `sections/NN_*.html` fragment, then `python paper/build.py`.
- **Change the title / byline / date** → edit the constants in `meta.py` (not `assemble.py`).
- **Add or reorder a section** → drop a `sections/NN_*.html` file; the order is the sorted `NN`
  prefix, picked up automatically (no list to maintain). Its number is assigned automatically —
  give its heading a `data-sec="KEY"` and the resolver numbers it (`§1, §2, …`); subsections use
  a dotted key (`data-sec="payoff.witness"` → `§6.1`). Reordering renumbers everything for free.
- **Reference a section / figure / table** → write `{{sec:KEY}}` / `{{fig:KEY}}` / `{{tbl:KEY}}`
  anywhere (even across fragments). Declare the anchor once on the element
  (`<figure data-fig="crossmodel">`, caption `Figure&nbsp;{{fig:crossmodel}}.`). An unknown or
  duplicate KEY fails the build — never a wrong or blank number. (Appendices keep their own
  hand-written `A/B/C` + `A.1` scheme; only the body is auto-numbered.)
- **Cite a live-run fact (spend, J, rate)** → add it to `meta.RUN_FACTS` and reference it as
  `{{fact:KEY}}`, so a re-run is a one-line edit, not a prose hunt.
- **The PDF bookmark outline takes care of itself** → `outline.py` re-derives the navigation tree
  from the assembled `paper.html` on every build (after render), so a new/reordered/renamed heading
  appears in the reader's bookmark sidebar with the same auto-number it shows on the page — nothing
  to hand-maintain. Heading levels map to outline depth (`h2`→top, `h3`→child, `h4`→grandchild). If a
  heading's text can't be located on any rendered page, the build fails (the same fail-loud discipline
  as the broken-`<img>` guard) rather than shipping a half-empty outline.
- **Add a figure** → reference it as `<img src="figs/NAME.png">` in a section; `build.py` copies
  `NAME` from any `meta.FIG_SOURCE_DIRS` entry (`benchmark/toolathlon/_results/`, `_diagrams/`, or
  `paper/figs_src/`) into `figs/`. Add it to `meta.WIDE_FIGS` if it needs a full-width span. A
  referenced figure missing from every source is reported at build time (a broken `<img>` is caught,
  not shipped) — this is the image-render guard.
- **Edit an appendix figure** → the appendix's three diagrams live in `figs_src/` as editable source
  (two Mermaid `.mmd`, one matplotlib `.py`). Edit the source, re-render per `figs_src/README.md`,
  then `python paper/build.py` copies the fresh `.png` into `figs/`. The bake-off figure's numbers
  come from `_VERIFIED_FACTS_2026-06-07.md`, never hand-typed into the script.
- **Mark the abstract** → wrap it in `<!--ABSTRACT--> … <!--/ABSTRACT-->` in the first section
  (the robust form); the legacy `<h2>Abstract</h2>…</p>` heuristic still works as a fallback.
- **After the numbers change** → regenerate the rows + ledger (`run_replay … --rows-out`,
  `additivity.py --emit`), update `meta.ROWS_FINGERPRINT`, then rebuild. The numbers are never
  hand-typed against the SSOT — they come from `additivity.py:compute()`.

## Scope

A **focused replay paper** (not a full DOS systems paper): the three byte-clean detectors,
the third-party-scored purchase result, the recall ceiling, `terminal_error` additivity,
the naive-baseline stress test, and the SOTA positioning — with the honest DETECT-not-FIX
boundary stated up front. `fig3_simpson` and `figB_per_model_catches` are available in
`benchmark/toolathlon/_results/` but were not needed for this cut.

### The plain-language appendix (Appendix A)

The body assumes a reader who already trusts terms like *byte-clean*, *oracle*, and *lift*.
**Appendix A — "DOS in plain words — the Vaseline test"** (`sections/07_appendix.html`) is for
everyone else: a self-contained, Feynman-simple explanation of what DOS is and what it does, built
around one running picture — the agent's narration as a smear of Vaseline on the mirror of the real
world (read *around* it, never *through* it). It defines every term on first use and ends with a
one-page glossary (Table A1). Its three figures are authored here, not in the benchmark dir:

| Figure | Source (`figs_src/`) | What it shows |
|---|---|---|
| **A1** | `appx_vaseline_mirror.mmd` | the Vaseline test — byte-clean (read around the smear) vs forgeable (read through it) |
| **A2** | `appx_dos_syscall_map.mmd` | the DOS kernel as a set of grounded refusals (`verify`/`liveness`/`arbitrate`/`refuse`/`resume`) + the ORACLE→JUDGE→HUMAN trust ladder |
| **A3** | `appx_fix_bakeoff.py` | the active-fix bake-off — every active fix was flat-to-negative; only the negative action (give-up-correctly) carried value |

The companion engineering write-up (same diagrams, deeper) is `benchmark/toolathlon/EXPLAINER.md`
and `GLOSSARY.md`.

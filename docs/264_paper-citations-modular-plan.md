# 264 — Modular citations for the paper (`{{cite:key}}`)

> **Status:** shipped (build mechanism + 15 references). This is a paper-build
> note, not a kernel module — it touches only `paper/` (a disjoint lane from
> `src/dos/`).

## The gap

`paper/arxiv/refs.bib` was a 4-entry scaffold with an explicit author TODO:
*"Thin related work is the single most common reason a first-time-author empirical
paper gets dinged in review."* The body already NAMES its prior art in prose
(Toolathlon, τ²-bench, EnterpriseOps-Gym, METR, the trained-classifier
arXiv 2511.04032, Limen, CodeCRDT) but carried **zero `\cite{}` calls** — the
references were inert. The HTML rendering had no reference list at all.

## The design — one token, two renderings, no drift

The paper is single-sourced: prose lives once in `paper/sections/NN_*.html`, and
both the HTML (`assemble.py`) and the arXiv LaTeX (`assemble_arxiv.py`) are
GENERATED from it via a shared `{{kind:key}}` token policy (`fact`/`sec`/`fig`/
`tbl`). Citations join that policy as a fifth token kind so they cannot drift
between the two outputs:

- **Source of truth:** `meta.REFERENCES` — an ordered list of `Reference`
  records (key, authors, title, venue, year, url, arxiv, a `note`). ONE place.
- **`{{cite:key}}` token, resolved in both assemblers:**
  - HTML (`numbering.py`): → a bracketed, numbered superscript `[N]` linking to
    `#ref-N`. The number is assigned by `cited_numbers()` — a single shared
    helper that numbers the **cited** entries contiguously (1..k) in `REFERENCES`
    order — and BOTH the inline link and the rendered `References` list read it,
    so they cannot desync even if `REFERENCES` carries a work this draft does not
    cite (an uncited entry is simply omitted from the list, not an error). A
    **dangling** `{{cite:KEY}}` (KEY not in `REFERENCES`) is still a hard build
    error, mirroring the existing `NumberingError` discipline (no silently-blank
    citation).
  - LaTeX (`assemble_arxiv.py`): → `\cite{key}`, and `arxiv/refs.bib` is
    **generated** from `meta.REFERENCES` (not hand-maintained) so the bib is a
    projection of the same list. `\bibliography{refs}` already wired in
    `main.tex`.
- **Tokens go in the `.html` sources only** at first mention; the `.tex`
  regenerate. No `.tex` is hand-edited (it carries the DO-NOT-EDIT banner).

This is the repo's own doctrine — a derived artifact is generated, never
hand-edited — applied to the bibliography: `refs.bib` stops being a
hand-maintained file that drifts and becomes a build output of `meta.REFERENCES`.

## The 15 (grounded in what the paper actually invokes, verified ids)

Benchmarks / live targets the paper runs or replays:
1. `toolathlon` — The Tool Decathlon (Toolathlon), HKUST-NLP, arXiv 2510.25726, ICLR 2026.
2. `tau2bench` — τ²-Bench (dual-control), Sierra Research, arXiv 2506.07982, 2025.
3. `enterpriseops` — EnterpriseOps-Gym, ServiceNow Research, arXiv 2603.13594, 2026.
4. `metr` — Measuring AI Ability to Complete Long Tasks (METR), arXiv 2503.14499, 2025.

Positioning neighbours the §6 prose names directly:
5. `silentfailures` — Detecting Silent Failures in Multi-Agentic AI Trajectories (the trained classifier), arXiv 2511.04032, 2025.
6. `limen` — Limen (advisory write-leases over MCP), Meirtz, GitHub artifact 2025.
7. `codecrdt` — CodeCRDT (lock-free CRDT coordination), arXiv 2510.18893, 2025.

The lineage the abstract's "Why this matters past this paper" paragraph
explicitly lifts from (minimal trusted kernel / distributed-systems hazards /
sequential statistics / write-ahead recovery / RL-from-verifiable-rewards):
8. `anderson` — Computer Security Technology Planning Study (reference monitor / minimal TCB), J. P. Anderson, 1972.
9. `wald` — Sequential Tests of Statistical Hypotheses (SPRT), A. Wald, 1945.
10. `page` — Continuous Inspection Schemes (CUSUM), E. S. Page, 1954.
11. `aries` — ARIES recovery (write-ahead recovery), Mohan et al., ACM TODS, 1992.
12. `bernstein` — Concurrency Control and Recovery in Database Systems (lost-update / serializability), Bernstein, Hadzilacos & Goodman, 1987.
13. `rlvr` — Tülu 3 (origin of RLVR), Lambert et al., arXiv 2411.15124, 2024.

The three frontier-lab programs the abstract's blockquote names as the reason
the work matters past the paper:
14. `bowman` — Measuring Progress on Scalable Oversight for LLMs (program 1), Bowman et al., arXiv 2211.03540, 2022.
15. `baker` — Monitoring Reasoning Models for Misbehavior (reward hacking / monitorability, program 2), Baker et al., arXiv 2503.11926, 2025.

(Program 3, multi-agent reliability, is already covered by `limen`/`codecrdt`
above; the time-horizon motivation for program 1 is `metr`.)

## Why these, not others (and what was dropped)

The rule is the one the kernel uses for evidence: cite what the paper actually
*leans on*, not a literature-review dump. 1–7 are named in the running text with
a number put beside them; 8–13 are the conceptual ancestors the abstract's
closing paragraph itemizes by name ("a minimal trusted kernel"; "TOCTOU,
lost-update, write-ahead recovery"; "the SPRT/CUSUM lineage"; "the RLVR label
filter"); 14–15 are the two frontier-lab programs that same blockquote raises by
name (scalable oversight; reward hacking / monitorability). Each maps to a
concrete first mention, so every `{{cite:}}` lands where the claim is made.

**Dropped from the first draft of the 15:** DPO (Rafailov 2023) and SWE-bench
(Jimenez 2023). Reason: neither is named anywhere in the prose — adding them
would be exactly the dump this rule forbids. They were replaced by `bowman` and
`baker`, which the abstract *does* name (programs 1 and 2). The build won't stop
you from leaving an uncited entry in `REFERENCES` (it is omitted from the
rendered list, so `REFERENCES` may hold a superset a later draft will cite), so
keeping the bibliography honest — every entry actually cited — is an editorial
discipline, not one the build enforces. All 15 here are cited; the rendered list
is the full 15.

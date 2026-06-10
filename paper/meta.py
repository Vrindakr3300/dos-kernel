#!/usr/bin/env python
"""Single source of truth for the paper build — edit HERE, not in assemble.py.

Everything the build needs to know that is NOT prose lives in this one module: the
title block, the ordered section list, the cross-reference registries (sections,
figures, tables — keyed by a *stable symbolic name*, numbered automatically at build
time so a reorder never desyncs a number), the figure-width set, and the live-run
facts the title/reproducibility lines cite. `assemble.py` and `build.py` import this;
nothing else hardcodes a title, a date, a number, or a figure name.

To keep editing the paper:
  * change the title / byline / date  -> edit TITLE / SUBTITLE / BYLINE / DATE below
  * add or reorder a SECTION          -> add a paper/sections/NN_*.html file (sorted by
                                          NN). It is numbered automatically: §1, §2, …
                                          for the body, A, B, … for appendices (a file
                                          whose first heading says "Appendix"). Headings
                                          and cross-refs use {{sec:KEY}} tokens, never a
                                          literal number, so reordering renumbers for free.
  * reference a section/figure/table   -> write {{sec:KEY}} / {{fig:KEY}} / {{tbl:KEY}}
                                          anywhere in prose. Declare the anchor once on the
                                          element with data-sec / data-fig / data-tbl="KEY".
                                          The resolver assigns numbers in document order and
                                          substitutes them everywhere. An unknown or
                                          duplicate KEY fails the build (no silent drift).
  * add a figure image                 -> drop it in one of FIG_SOURCE_DIRS, reference it as
                                          <img src="figs/NAME.png">, add NAME to WIDE_FIGS if
                                          it needs a full-width span. (The figure *number*
                                          comes from the data-fig key, not the filename.)
  * change a live-run fact (spend, …)  -> edit RUN_FACTS below; the prose pulls {{fact:KEY}}.
  * rebuild                            -> python paper/build.py   (figures + assemble + render)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SECTIONS_DIR = HERE / "sections"
FIGS_DIR = HERE / "figs"
HTML_OUT = HERE / "paper.html"
PDF_OUT = HERE / "paper.pdf"

# --- title block (the only place these strings live) ---------------------------------
TITLE = "Verification Is All You Need — But Not Where You Think"
SUBTITLE = ("A verdict the agent <strong>cannot forge</strong> is <em>harmful</em> handed back to that "
            "agent and <em>valuable</em> handed to the fleet around it &mdash; that boundary is the "
            "result, and we earn it live. One deterministic, out-of-loop referee blocks real over-claims "
            "(J&nbsp;=&nbsp;10 across two models), serializes racing agents to prevent lost-update "
            "clobbers (J&nbsp;=&nbsp;6), and purges the same over-claims as poison reward labels an RL "
            "loop would otherwise bank as wins &mdash; while the <em>same</em> verdict spent in-loop is "
            "flat-to-harmful. One non-forgeable check, three consumers: a monitorability primitive for "
            "fleets, and for the loops that train them.")
BYLINE = "Anthony Chaudhary · Dispatch Operating System (DOS)"
DATE = "10 June 2026"

# --- the artifact the reproducibility/meta lines point at (host-agnostic: no path is
#     hardcoded in assemble.py — it reads these) -------------------------------------------
REPRO_ROOT = "benchmark/toolathlon/"          # where the offline study reproduces from
REPRO_ROWS = "replay_all_rows.csv"            # the durable per-run join every offline number recomputes from

# --- live-run facts the prose cites by {{fact:KEY}} (single-sourced so a re-run is one edit) -
# These are read-offs of the paid live runs; the _VERIFIED_FACTS_*.md files are the
# provenance of record. Keep this table and those files in lockstep.
RUN_FACTS = {
    "spend_writeadmit": "$4.77",     # docs/232 cross-model run total (flash $0.56 + pro $4.21)
    "spend_writeadmit_single": "$0.89",  # docs/228 single-model run
    "spend_coord": "$1.50",          # docs/233 coordination run (~24 live agent runs)
    "j_overclaim": "10",             # over-claims blocked, 2 models / 120 tasks
    "j_coord": "6",                  # clobbers prevented, 8 pairs
    "overclaim_rate": "8.3%",        # identical across flash + pro on the matched slice
    # --- the saturation sweep (docs/228 §5.1): the whole tau2 airline+retail universe ------
    "j_saturation": "15",            # over-claims blocked across the saturated fold, 2 models
    "saturation_tasks": "258",       # clean tasks in the saturated fold (aggregate_live.py)
    "saturation_rate": "5.8%",       # whole-distribution incidence (15/258); write-heavy slices are higher
    "spend_saturation": "$8.35",     # CUMULATIVE write-admission program total (contains the $0.89 + $4.77 runs)
    # --- Agent-Diff (docs/237): the richer state-diff witness + the first downstream ΔB ----
    "ad_block_flash": "23",          # over-claims blocked, flash, 45-task test split
    "ad_block_pro": "25",            # over-claims blocked, pro-2.5, same split
    "ad_rate_flash": "66%",          # 23 of 35 confident writes were over-claims (flash)
    "ad_rate_pro": "81%",            # 25 of 31 confident writes were over-claims (pro — MORE not less)
    "ad_deltab_flash": "+4",         # causal downstream ΔB on flash (4 flips, 0 reverses)
    "ad_deltab_pro": "0",            # causal downstream ΔB on pro (2 flips cancelled by 2 reverses)
    # --- the cascade (docs/251 F1 chain + docs/253 F1-super-linear tree): compounding payoff -
    "spend_cascade": "$2.50",        # docs/251 chain (~$1.5) + docs/253 tree (~$1.0)
    "cascade_chain_d4": "3",         # chain payoff at depth 4 (D−1): 3 corrupt nodes prevented
    "cascade_tree_d2": "4",          # tree payoff at depth 2 (F^D, F=2): 4 corrupt leaves prevented
    "cascade_tree_d3": "8",          # tree payoff at depth 3 (F^D, F=2): 8 corrupt leaves prevented
    # --- the frontier floor LADDER (docs/272 Phase 1b): the HARD forge head-to-head ----------
    # Fable 5 (claude-fable-5) in the judge seat, via the Claude Code CLI (`claude -p`), no SDK.
    # 9 freshly-authored git artifacts (7 forgeries + 2 controls), including 3 HARD forges that
    # touch the EXACT deliverable paths, adjudicated by a LADDER of three non-forgeable rungs.
    # Numbers from benchmark/fleet_horizon/results_fable5_ladder_20260609.json.
    "forge_floor_n": "8",            # the 8 not-actually-shipped artifacts (7 forgeries + the no-op)
    "forge_landings_n": "1",         # the one honest landing
    "forge_subject_fa": "7",         # the forgeable grep-the-subject rung is fooled 7 of 8
    # The PRESENCE rung (D-artifact, files-touched) is non-forgeable to narration but content-blind:
    # a path-touching stub fools it. This is the honest limit the ladder makes visible.
    "forge_presence_fa": "2",        # presence rung FALSE-ACCEPTS the 2 path-touching stubs
    "forge_presence_ta": "1",        # …and confirms the honest landing
    # The BEHAVIOR rung (D-test, OS-recorded test execution) is the floor that holds.
    "forge_behavior_fa": "0",        # behavior rung false-accepts 0 of 8 — catches the stubs too
    "forge_behavior_ta": "1",        # …and confirms the working landing
    "forge_hard_n": "3",             # the 3 hard forges that touch the exact deliverable paths
    "forge_hard_presence_fooled": "2",   # 2 of the 3 fool the presence rung (near_miss does not)
    # The SECONDARY finding: a STRONGER non-forgeable witness makes even the learned judge functional.
    "forge_fable_ev_ta_blind_witness": "0",  # Phase-1 Fable+ev (files-touched only): abstained, 0/1
    "forge_fable_ev_ta": "1",        # Phase-1b Fable+ev (handed the OS-recorded test result): 1/1
    "forge_fable_ev_fa": "0",        # …and 0/8 false-accept (disagreed on every forgery)
    "forge_fable_blind_ta": "0",     # blind arm (narration only) stays non-functional: 0/1
}

# --- where the canonical figures are generated (build.py copies these into figs/) -----
# The paper stages its own copies under figs/ so it is self-contained; these are the
# upstream sources the copies are refreshed from. `figs_src/` holds the appendix's own
# diagrams (the Vaseline picture, the syscall map, the fix bake-off) — Mermaid + a
# matplotlib script rendered to PNG; see figs_src/README.md to regenerate them.
FIG_SOURCE_DIRS = (
    REPO / "benchmark" / "toolathlon" / "_results",
    REPO / "benchmark" / "toolathlon" / "_diagrams",
    HERE / "figs_src",
)

# --- figures wide enough (aspect >= ~2.2) to need a full-width, both-columns span -----
WIDE_FIGS = frozenset({
    "diagram2_what_each_detector_sees.png",
    "fig1_purchase_vs_capability.png",
    "fig3_simpson.png",
    "fig5_lift_vs_recall.png",
    "fig6_trio_additivity.png",
    "figA_additivity_headline.png",
    "figB_per_model_catches.png",
    "figC_frontier_sensitivity.png",
    "figD_combined_dos_lift.png",
    "fig_giveup_cross_benchmark.png",
    "fig_hero_bakeoff.png",
    # appendix A/B diagrams (full-width — they span both columns)
    "appx_vaseline_mirror.png",
    "appx_dos_syscall_map.png",
    "appx_fix_bakeoff.png",
    # §payoff — the live out-of-loop payoff (Tier-B run live, J=5; docs/228)
    "payoff_writeadmit_live.png",
    # §payoff — the cross-model hardening (J=10, flash+pro both 8.3%; docs/232)
    "payoff_writeadmit_crossmodel.png",
    # §payoff — the live coordination payoff (referee-between-agents, J=6; docs/233)
    "coord_payoff_live.png",
    # Fig hero — the thesis: same verdict harmful in-loop, valuable out-of-loop (both half-planes)
    "hero_inloop_vs_outofloop.png",
    # F1 (docs/251) — the compounding curve: corruption spreads down a believe chain, gate stops it
    "cascade_depth_live.png",
    # F1-super-linear (docs/253) — the fan-out tree: payoff grows F^D, not D−1
    "cascade_fanout_live.png",
    # §payoff — the frontier floor LADDER: the hard forge head-to-head on Fable 5 (docs/272 P1b)
    "forge_frontier_floor.png",
})

# --- the durable-rows fingerprint this paper's numbers were drawn from ----------------
# The reproducibility section cites this; build.py warns if it drifts from the live CSV
# (additivity.rows_fingerprint), so a stale paper cannot quietly ship wrong provenance.
ROWS_FINGERPRINT = "1a55e8d8e2d4"


# --- the bibliography: ONE source, both renderings read it (docs/264) -----------------
# Prose cites a work by {{cite:KEY}} at first mention. The HTML resolver (numbering.py)
# turns that into a numbered [N] link to a generated References section; the arXiv
# assembler turns it into \cite{KEY} and GENERATES arxiv/refs.bib from this same list,
# so the bib is a projection of this table and can never drift from it. Reference numbers
# are assigned by ORDER here (1-based), so reorder = renumber, like the figure/section
# counters. A {{cite:KEY}} with no entry here — or an entry no section cites — fails the
# build, the same loud-failure discipline as a dangling {{fig:}}.
@dataclass(frozen=True)
class Reference:
    """One bibliography entry. `entry_type`/`fields` drive the generated BibTeX."""
    key: str            # the {{cite:KEY}} handle (also the BibTeX cite-key)
    authors: str        # rendered byline for the HTML list ("Author, A. and Author, B.")
    title: str          # the work's title (HTML-rendered; LaTeX-escaped for the .bib)
    venue: str          # venue / publisher / "arXiv:NNNN.NNNNN" — the trailing locator
    year: str
    url: str = ""       # canonical URL (arXiv abstract page, repo, or DOI link)
    entry_type: str = "misc"   # BibTeX @type (misc | article | inproceedings | book | techreport)
    bibtex: dict[str, str] = None  # extra/overriding BibTeX fields (journal, booktitle, publisher…)


# Ordered: benchmarks/targets the paper runs (1-4), the positioning neighbours §6 names
# (5-7), then the lineage the abstract lifts from (8-15). See docs/264 for why each.
REFERENCES: tuple[Reference, ...] = (
    Reference(
        key="toolathlon",
        authors="Li, J. and others (HKUST-NLP)",
        title="The Tool Decathlon: Benchmarking Language Agents for Diverse, "
              "Realistic, and Long-Horizon Task Execution",
        venue="arXiv:2510.25726 (ICLR 2026)",
        year="2025",
        url="https://arxiv.org/abs/2510.25726",
        bibtex={"eprint": "2510.25726", "archivePrefix": "arXiv",
                "note": "Third-party-scored agent benchmark (the Toolathlon-Trajectories "
                        "corpus, CC-BY-4.0); ships its own evaluation/main.py oracle. "
                        "Replayed here for the offline study (22 models)."},
    ),
    Reference(
        key="tau2bench",
        authors="Barres, V. and Dong, H. and Ray, S. and Si, X. and Narasimhan, K.",
        title="$\\tau^2$-Bench: Evaluating Conversational Agents in a "
              "Dual-Control Environment",
        venue="arXiv:2506.07982",
        year="2025",
        url="https://arxiv.org/abs/2506.07982",
        bibtex={"eprint": "2506.07982", "archivePrefix": "arXiv",
                "note": "Live target for the write-admission gate and the coordination "
                        "experiment; exposes an environment database-hash oracle (db_match)."},
    ),
    Reference(
        key="enterpriseops",
        authors="Malay, S. K. R. and others (ServiceNow Research)",
        title="EnterpriseOps-Gym: Environments and Evaluations for Stateful "
              "Agentic Planning and Tool Use in Enterprise Settings",
        venue="arXiv:2603.13594",
        year="2026",
        url="https://arxiv.org/abs/2603.13594",
        bibtex={"eprint": "2603.13594", "archivePrefix": "arXiv",
                "note": "Live model-run environment (SQL final-state verifiers) for the "
                        "in-loop active-fix bake-off and the give-up cross-benchmark check."},
    ),
    Reference(
        key="metr",
        authors="{METR}",
        title="Measuring AI Ability to Complete Long Software Tasks",
        venue="arXiv:2503.14499",
        year="2025",
        url="https://arxiv.org/abs/2503.14499",
        bibtex={"eprint": "2503.14499", "archivePrefix": "arXiv",
                "note": "Task-completion time-horizon measurement; the capability-axis "
                        "framing the per-model coverage result is read against."},
    ),
    Reference(
        key="silentfailures",
        authors="Pathak, D. and others",
        title="Detecting Silent Failures in Multi-Agentic AI Trajectories",
        venue="arXiv:2511.04032",
        year="2025",
        url="https://arxiv.org/abs/2511.04032",
        bibtex={"eprint": "2511.04032", "archivePrefix": "arXiv",
                "note": "The trained-classifier neighbour (XGBoost/SVDD, ~98% on its own "
                        "labelled data) the Positioning section measures on this corpus."},
    ),
    Reference(
        key="limen",
        authors="Meir, T. (Meirtz)",
        title="Limen: Coordination for Concurrent Autonomous AI Agents over "
              "Shared Mutable State (advisory write-leases over MCP)",
        venue="Software artifact, github.com/Meirtz/Limen",
        year="2025",
        url="https://github.com/Meirtz/Limen",
        bibtex={"howpublished": "\\url{https://github.com/Meirtz/Limen}",
                "note": "Arbiter neighbour: advisory write-leases + a witnessed audit "
                        "trail; compares to DOS's arbitrate(), not its detector."},
    ),
    Reference(
        key="codecrdt",
        authors="Pugachev, S.",
        title="CodeCRDT: Observation-Driven Coordination for Multi-Agent LLM "
              "Code Generation",
        venue="arXiv:2510.18893",
        year="2025",
        url="https://arxiv.org/abs/2510.18893",
        bibtex={"eprint": "2510.18893", "archivePrefix": "arXiv",
                "note": "Arbiter neighbour: lock-free CRDT coordination with strong "
                        "eventual consistency; the other multi-agent arbitration point."},
    ),
    Reference(
        key="anderson",
        authors="Anderson, J. P.",
        title="Computer Security Technology Planning Study",
        venue="ESD-TR-73-51, U.S. Air Force Electronic Systems Division",
        year="1972",
        url="https://csrc.nist.gov/publications/history/ande72.pdf",
        entry_type="techreport",
        bibtex={"institution": "U.S. Air Force Electronic Systems Division",
                "number": "ESD-TR-73-51",
                "note": "Origin of the reference-monitor concept and the minimal-TCB "
                        "doctrine the kernel descends from."},
    ),
    Reference(
        key="wald",
        authors="Wald, A.",
        title="Sequential Tests of Statistical Hypotheses",
        venue="Annals of Mathematical Statistics 16(2):117--186",
        year="1945",
        url="https://doi.org/10.1214/aoms/1177731118",
        entry_type="article",
        bibtex={"journal": "Annals of Mathematical Statistics", "volume": "16",
                "number": "2", "pages": "117--186",
                "note": "The sequential probability ratio test (SPRT); the give-up gate's "
                        "stop-when-the-evidence-is-decisive lineage."},
    ),
    Reference(
        key="page",
        authors="Page, E. S.",
        title="Continuous Inspection Schemes",
        venue="Biometrika 41(1/2):100--115",
        year="1954",
        url="https://doi.org/10.1093/biomet/41.1-2.100",
        entry_type="article",
        bibtex={"journal": "Biometrika", "volume": "41", "number": "1/2",
                "pages": "100--115",
                "note": "CUSUM change detection; paired with SPRT as the give-up gate's "
                        "statistical ancestry."},
    ),
    Reference(
        key="aries",
        authors="Mohan, C. and Haderle, D. and Lindsay, B. and Pirahesh, H. "
                "and Schwarz, P.",
        title="ARIES: A Transaction Recovery Method Supporting Fine-Granularity "
              "Locking and Partial Rollbacks Using Write-Ahead Logging",
        venue="ACM Transactions on Database Systems 17(1):94--162",
        year="1992",
        url="https://doi.org/10.1145/128765.128770",
        entry_type="article",
        bibtex={"journal": "ACM Transactions on Database Systems", "volume": "17",
                "number": "1", "pages": "94--162",
                "note": "The write-ahead-log recovery algorithm DOS's resume() lifts its "
                        "analysis/redo phases from."},
    ),
    Reference(
        key="bernstein",
        authors="Bernstein, P. A. and Hadzilacos, V. and Goodman, N.",
        title="Concurrency Control and Recovery in Database Systems",
        venue="Addison-Wesley",
        year="1987",
        url="https://www.microsoft.com/en-us/research/people/philbe/book/",
        entry_type="book",
        bibtex={"publisher": "Addison-Wesley",
                "note": "Serializability, the lost-update anomaly, and two-phase "
                        "discipline — the database-concurrency hazards lifted onto "
                        "world-state."},
    ),
    Reference(
        key="toctou",
        authors="Bishop, M. and Dilger, M.",
        title="Checking for Race Conditions in File Accesses",
        venue="Computing Systems 9(2):131--152",
        year="1996",
        url="https://www.usenix.org/legacy/publications/compsystems/1996/spr_bishop.pdf",
        entry_type="article",
        bibtex={"journal": "Computing Systems", "volume": "9", "number": "2",
                "pages": "131--152",
                "note": "The canonical time-of-check-to-time-of-use (TOCTOU) race "
                        "analysis; the hazard the abstract lifts from files onto "
                        "world state."},
    ),
    Reference(
        key="rlvr",
        authors="Lambert, N. and others (Allen Institute for AI)",
        title="T\\\"ulu 3: Pushing Frontiers in Open Language Model Post-Training",
        venue="arXiv:2411.15124",
        year="2024",
        url="https://arxiv.org/abs/2411.15124",
        bibtex={"eprint": "2411.15124", "archivePrefix": "arXiv",
                "note": "Reinforcement Learning from Verifiable Rewards (RLVR); the "
                        "training loop the reward-label-purge result plugs into."},
    ),
    Reference(
        key="bowman",
        authors="Bowman, S. R. and others (Anthropic)",
        title="Measuring Progress on Scalable Oversight for Large Language Models",
        venue="arXiv:2211.03540",
        year="2022",
        url="https://arxiv.org/abs/2211.03540",
        bibtex={"eprint": "2211.03540", "archivePrefix": "arXiv",
                "note": "Scalable oversight: supervising systems that outrun a human's "
                        "line-by-line check — frontier-lab program (1) the byte-clean "
                        "witness is offered as an evidence-rooted instance of."},
    ),
    Reference(
        key="baker",
        authors="Baker, B. and Huizinga, J. and Gao, L. and others (OpenAI)",
        title="Monitoring Reasoning Models for Misbehavior and the Risks of "
              "Promoting Obfuscation",
        venue="arXiv:2503.11926",
        year="2025",
        url="https://arxiv.org/abs/2503.11926",
        bibtex={"eprint": "2503.11926", "archivePrefix": "arXiv",
                "note": "Reward hacking / monitorability: optimization pressure teaches a "
                        "model to hide misbehavior — frontier-lab program (2); the "
                        "motivation for a non-forgeable, non-distillable label."},
    ),
)


def reference_numbers() -> dict[str, int]:
    """Map each reference key -> its 1-based position (its visible citation number).

    The single place document-wide citation numbers are assigned, so the HTML [N]
    links and the References list agree by construction. Duplicate keys are a build
    error (the bibliography must be a set keyed by `key`)."""
    seen: dict[str, int] = {}
    for i, ref in enumerate(REFERENCES, start=1):
        if ref.key in seen:
            raise SystemExit(f"meta.REFERENCES: duplicate key {ref.key!r}")
        seen[ref.key] = i
    return seen


def section_files() -> list[Path]:
    """The section fragments, in render order (sorted by the NN_ prefix)."""
    frags = sorted(SECTIONS_DIR.glob("*.html"))
    if not frags:
        raise SystemExit(f"no section fragments in {SECTIONS_DIR}")
    return frags

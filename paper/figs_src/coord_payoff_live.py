#!/usr/bin/env python
"""§6.5 figure: the COORDINATION payoff, run live — the arbiter prevents real clobbers.

The sibling of `payoff_writeadmit_live.py`. §6.1-6.4 measured the referee-OVER-CLAIMS
payoff (a gate blocks an over-claimed write before a peer inherits it, J=5). This figure
is the OTHER value half-plane — referee-BETWEEN-AGENTS: two live agents race the same
tau2 reservation, the naive flow lets the second clobber the first, and the arbiter
serializes them so the clobber never lands (J=6 over 8 conflict pairs), witnessed by the
same environment DB-hash. Two panels:

  LEFT  — the 8-pair ledger. 6 canonical clobbers PREVENTED (the J) + 2 HONEST
          non-clobbers (one falsifier where the agent declined, one variance case the
          directional-J fix excludes). Arbiter serialized 8/8.
  RIGHT — the symmetric pair: both DOS value half-planes, now both measured live off the
          SAME non-forgeable DB-hash — referee-over-claims (J=5, §6.4) and
          referee-between-agents (J=6, here). Both a PAYOFF, not a rate.

DESIGN NOTE — readability over a 0.53x downscale. This renders both-columns wide
(~178mm) from a 12in source (~0.53x on page). So nothing here is sized below ~13pt
in-source. The clobber MECHANISM and the directional-J correction (7→6) used to live as
paragraphs inside the left panel, rendering at ~4pt; they now live in the caption. The
figure carries the COUNTS; the caption carries the argument.

EVERY number is transcribed from paper/_VERIFIED_FACTS_233_2026-06-08.md (the verbatim
read-off of docs/233, the executed live run). No number is invented here. Derived
illustration, not a source of truth — if that facts file changes, regenerate.

    python paper/figs_src/coord_payoff_live.py    # writes the .png alongside

Date.now()/random are intentionally unused (deterministic output).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent / "coord_payoff_live.png"

# --- the verified live numbers (tau2-bench airline, gemini-2.5-flash; docs/233) -------
PAIRS = 8                 # conflict pairs run
J = 6                     # clobbers prevented (directional definition)
CANONICAL = 6             # A1-cancel × A2-stale-add-bag clobbers prevented
NONCLOBBER = 2            # honest J=0 (VAAOXJ declined; 1OWO6T variance, directional-fix excluded)
SERIALIZED = 8            # arbiter refused the 2nd concurrent lease, 8/8

# the symmetric pair (both half-planes, both live, both off the DB-hash)
OVERCLAIM_J = 5           # §6.4 / docs/228 — referee-over-claims
COORD_J = 6               # here / docs/233 — referee-between-agents

GREEN = "#16a34a"   # clobber PREVENTED (the payoff)
GREY = "#94a3b8"    # honest non-clobber (declined / variance)
STEEL = "#2563eb"   # the over-claim half-plane
SLATE = "#334155"
INK = "#1e293b"

BASE = 17.0   # base font; everything else scales off this (see DESIGN NOTE)


def main() -> None:
    fig, (axL, axR) = plt.subplots(
        1, 2, figsize=(12.0, 5.6), gridspec_kw={"width_ratios": [1.0, 1.05]}
    )

    # ===== LEFT: the 8-pair ledger ====================================================
    # Stacked: 6 clobbers prevented (green = J) + 2 honest non-clobbers (grey).
    axL.bar([0], [CANONICAL], color=GREEN, edgecolor=INK, linewidth=1.4, width=0.52,
            zorder=3, label=f"clobber PREVENTED   ({CANONICAL} = J)")
    axL.bar([0], [NONCLOBBER], bottom=[CANONICAL], color=GREY, edgecolor=INK,
            linewidth=1.4, width=0.52, zorder=3,
            label=f"honest non-clobber   ({NONCLOBBER}: declined / variance)")
    axL.text(0, CANONICAL / 2, f"{CANONICAL}", ha="center", va="center",
             fontsize=BASE * 1.3, fontweight="bold", color="white")
    axL.text(0, CANONICAL + NONCLOBBER / 2, f"{NONCLOBBER}", ha="center", va="center",
             fontsize=BASE * 1.0, fontweight="bold", color="white")
    axL.text(0, PAIRS + 0.3, f"{PAIRS} conflict pairs", ha="center", va="bottom",
             fontsize=BASE * 0.82, color=SLATE, fontweight="bold")

    # the big J, to the right of the bar
    axL.text(1.18, 4.2, f"J = {J}", ha="center", va="center",
             fontsize=BASE * 1.65, fontweight="bold", color=GREEN)
    axL.text(1.18, 2.7, f"serialized\n{SERIALIZED}/{PAIRS} pairs", ha="center",
             va="center", fontsize=BASE * 0.80, color=SLATE)

    axL.set_xticks([])   # the "8 conflict pairs" label already sits atop the bar
    axL.set_xlim(-0.55, 1.85)
    axL.set_ylim(0, 9.2)
    axL.set_ylabel("lost-update clobbers on a shared reservation",
                   fontsize=BASE * 0.84)
    axL.set_title("The arbiter prevented 6 real clobbers,\noff the environment DB-hash.",
                  fontsize=BASE * 1.0, pad=12, color=INK)
    axL.grid(axis="y", linestyle=":", color="#cbd5e1", zorder=0)
    for s in ("top", "right"):
        axL.spines[s].set_visible(False)
    axL.tick_params(axis="y", labelsize=BASE * 0.78)
    axL.legend(loc="upper center", bbox_to_anchor=(0.5, -0.085), fontsize=BASE * 0.74,
               framealpha=0.95, ncol=1, handlelength=1.4, borderpad=0.5)

    # ===== RIGHT: the symmetric pair — both half-planes, both live, same witness =======
    bars = [
        ("referee a CLAIM\n(over-claims, §6.4)", OVERCLAIM_J, STEEL),
        ("referee a RACE\n(coordination, §6.5)", COORD_J, GREEN),
    ]
    xpos = [0, 1]
    axR.bar(xpos, [b[1] for b in bars], color=[b[2] for b in bars],
            edgecolor=INK, linewidth=1.4, width=0.58, zorder=3)
    for x, (label, j, _c) in zip(xpos, bars):
        axR.text(x, j + 0.22, f"J = {j}", ha="center", va="bottom",
                 fontsize=BASE * 1.5, fontweight="bold", color=INK)
    axR.set_xticks(xpos)
    axR.set_xticklabels([b[0] for b in bars], fontsize=BASE * 0.86)
    axR.set_xlim(-0.7, 1.7)
    axR.set_ylim(0, 8.0)
    axR.set_ylabel("live payoff J  (off the same DB-hash)", fontsize=BASE * 0.84)
    axR.set_title("Both fleet failures, one move:\nan out-of-loop refusal, off a byte the agent can't write.",
                  fontsize=BASE * 0.94, pad=12, color=INK)
    axR.grid(axis="y", linestyle=":", color="#cbd5e1", zorder=0)
    for s in ("top", "right"):
        axR.spines[s].set_visible(False)
    axR.tick_params(axis="y", labelsize=BASE * 0.78)

    fig.suptitle(
        "The coordination payoff, run live: the arbiter serializes two racing agents "
        "and prevents real clobbers  (tau2-bench · gemini-2.5-flash · J = 6)",
        fontsize=BASE * 1.0, y=1.005, fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

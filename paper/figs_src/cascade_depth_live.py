#!/usr/bin/env python
"""F1 figure (docs/251): the compounding curve — corruption spreads down a believe chain,
the gate stops it at the root.

The fleet-scale question (docs/245 O4): one prevented over-claim is not one event — it is a
poison every downstream agent then trips over. Measured LIVE: a corrupt root reservation
(R wrongly cancelled) handed forward, with live Gemini agents at each downstream node.
  * believe  — each node inherits the corrupt DB; R stays cancelled at every node (the live
               agent does NOT heal it — it gives up on the blocked task). corrupted = D-1.
  * adjudicate — the gate blocked the refuted root, so every node inherits GOLD; R is active,
                 every node's task succeeds. corrupted = 0, at every depth.
The PAYOFF (believe_corrupted − adjudicate_corrupted) grows linearly with depth: every extra
agent that touches the poisoned entity is another blocked, still-corrupt node.

Numbers transcribed from live_results_cascade/cascade_d{2,3,4}.json (the executed run). No
number invented. Derived illustration; regenerate if the data changes.

    python paper/figs_src/cascade_depth_live.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent / "cascade_depth_live.png"

# --- the verified live numbers (live_results_cascade/, gemini-2.5-flash) ---------------
DEPTHS = [2, 3, 4]
BELIEVE_CORRUPT = [1, 2, 3]      # nodes still corrupt (R cancelled) under believe = D-1
ADJUDICATE_CORRUPT = [0, 0, 0]   # nodes corrupt under adjudicate (inherit gold) = 0
PAYOFF = [1, 2, 3]               # believe − adjudicate

RED = "#dc2626"
GREEN = "#16a34a"
STEEL = "#2563eb"
SLATE = "#334155"
INK = "#1e293b"

BASE = 17.0   # base font; everything scales off this (renders ~9pt on a 0.53x page)


def main() -> None:
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(12.6, 5.2),
                                   gridspec_kw={"width_ratios": [1.05, 1.0]})

    # ===== LEFT: corrupted nodes vs depth, both arms ==================================
    axL.plot(DEPTHS, BELIEVE_CORRUPT, "o-", color=RED, linewidth=3.0, markersize=11,
             label="BELIEVE — inherit the raw outcome", zorder=3)
    axL.plot(DEPTHS, ADJUDICATE_CORRUPT, "s-", color=GREEN, linewidth=3.0, markersize=11,
             label="ADJUDICATE — gate blocks the root", zorder=3)
    for d, b in zip(DEPTHS, BELIEVE_CORRUPT):
        axL.text(d, b + 0.13, f"{b}", ha="center", va="bottom", fontsize=BASE * 0.86,
                 fontweight="bold", color=RED)
    axL.text(DEPTHS[-1], 0.14, "0 at every depth", ha="right", va="bottom",
             fontsize=BASE * 0.80, color=GREEN, fontweight="bold")
    axL.set_xticks(DEPTHS)
    axL.set_xlabel("chain depth D (agents downstream of the poison)", fontsize=BASE * 0.84)
    axL.set_ylabel("downstream nodes left CORRUPT\n(R still wrongly cancelled)",
                   fontsize=BASE * 0.82)
    axL.set_ylim(-0.4, 3.7)
    axL.set_title("Live cascade: corruption spreads to every agent\n"
                  "under believe; the gate keeps the fleet clean.",
                  fontsize=BASE * 0.98, pad=12, color=INK)
    axL.grid(True, linestyle=":", color="#cbd5e1", zorder=0)
    axL.legend(loc="upper left", fontsize=BASE * 0.76, framealpha=0.95)
    axL.tick_params(labelsize=BASE * 0.78)
    for s in ("top", "right"):
        axL.spines[s].set_visible(False)

    # ===== RIGHT: the compounding payoff bar ==========================================
    axR.bar([str(d) for d in DEPTHS], PAYOFF, color=STEEL, edgecolor=INK, linewidth=1.4,
            width=0.62, zorder=3)
    for i, p in enumerate(PAYOFF):
        axR.text(i, p + 0.07, f"{p}", ha="center", va="bottom", fontsize=BASE * 1.05,
                 fontweight="bold", color=INK)
    axR.set_xlabel("chain depth D", fontsize=BASE * 0.84)
    axR.set_ylabel("compounding PAYOFF\n(corrupt nodes the gate prevented)",
                   fontsize=BASE * 0.82)
    axR.set_ylim(0, 3.7)
    axR.set_title("PAYOFF grows with fleet reach (D−1):\n"
                  "every extra agent on the poison is another loss.",
                  fontsize=BASE * 0.98, pad=12, color=INK)
    axR.grid(axis="y", linestyle=":", color="#cbd5e1", zorder=0)
    axR.tick_params(labelsize=BASE * 0.78)
    for s in ("top", "right"):
        axR.spines[s].set_visible(False)

    fig.suptitle(
        "F1: corruption compounds down a believe chain, the referee stops it at the root  "
        "(tau2-bench · gemini-2.5-flash, live)",
        fontsize=BASE * 1.0, y=1.005, fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

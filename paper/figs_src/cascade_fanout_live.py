#!/usr/bin/env python
"""F1-super-linear (docs/252): the fan-out tree — the gate's payoff grows F^D, not D−1.

F1 (docs/251) measured a single CHAIN: corruption reaches D−1 downstream nodes (linear).
The fleet thesis claims a depth-D, fan-out-F TREE of agents touching the poisoned resource
has F^D leaves, so the payoff is SUPER-LINEAR. Measured live: every leaf in the tree is
corrupt under believe; the gate (blocking the root) keeps all of them clean.

  LEFT  — the two curves on one axis: CHAIN (linear, D−1: 1,2,3) vs TREE (F^D: 4,8). The
          gate's prevented-corruption payoff grows with the fleet's branching, not just depth.
  RIGHT — the fan-out tree at depth 3 (F=2 -> 8 leaves): every node corrupt under believe
          (red), every node clean under adjudicate (the gate blocked the root). The count
          F^D is the fleet's branching, the correct fleet model (a poisoned shared resource
          blocks every agent that depends on it; that set grows F^D with the tree).

Numbers transcribed from live_results_fanout/fanout_d{2,3}_f2.json + live_results_cascade/
(the chain). No number invented. HONEST SCOPE (see docs/252): this is BREADTH fanout (count
of agents blocked by the shared poison), not field-amplification.

    python paper/figs_src/cascade_fanout_live.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent / "cascade_fanout_live.png"

# --- the verified live numbers ---------------------------------------------------------
DEPTHS = [2, 3]
CHAIN_PAYOFF = [1, 2]       # F1 chain (docs/251): D−1
TREE_PAYOFF = [4, 8]        # F1-super-linear tree (docs/252): F^D with F=2
TREE_LEAVES = [4, 8]        # 2^2, 2^3

RED = "#dc2626"
GREEN = "#16a34a"
STEEL = "#2563eb"
AMBER = "#d97706"
SLATE = "#334155"
INK = "#1e293b"

BASE = 17.0   # base font; everything scales off this (renders ~9pt on a 0.53x page)


def main() -> None:
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(12.6, 5.2),
                                   gridspec_kw={"width_ratios": [1.0, 1.05]})

    # ===== LEFT: chain (linear) vs tree (F^D) =========================================
    axL.plot(DEPTHS, CHAIN_PAYOFF, "o--", color=AMBER, linewidth=2.8, markersize=11,
             label="CHAIN — single line of agents (D−1)", zorder=3)
    axL.plot(DEPTHS, TREE_PAYOFF, "s-", color=STEEL, linewidth=3.2, markersize=12,
             label="TREE — fan-out F=2 (F^D)", zorder=3)
    for d, c, t in zip(DEPTHS, CHAIN_PAYOFF, TREE_PAYOFF):
        axL.text(d, c - 0.5, f"{c}", ha="center", va="top", fontsize=BASE * 0.86,
                 fontweight="bold", color=AMBER)
        axL.text(d, t + 0.32, f"{t}", ha="center", va="bottom", fontsize=BASE * 0.92,
                 fontweight="bold", color=STEEL)
    axL.set_xticks(DEPTHS)
    axL.set_xlabel("fleet depth D", fontsize=BASE * 0.84)
    axL.set_ylabel("corruptions the gate PREVENTS\n(believe-corrupt nodes)",
                   fontsize=BASE * 0.82)
    axL.set_ylim(0, 9.4)
    axL.set_title("The payoff grows F^D with the fleet's branching,\n"
                  "not just D−1 down a single chain.",
                  fontsize=BASE * 0.98, pad=12, color=INK)
    axL.grid(True, linestyle=":", color="#cbd5e1", zorder=0)
    axL.legend(loc="upper left", fontsize=BASE * 0.76, framealpha=0.95)
    axL.tick_params(labelsize=BASE * 0.78)
    for s in ("top", "right"):
        axL.spines[s].set_visible(False)

    # ===== RIGHT: the depth-3 fan-out tree, both arms =================================
    # draw a small F=2 tree (levels 2,4,8) as colored dots per level, two arms side by side.
    ax = axR
    ax.set_xlim(0, 10); ax.set_ylim(0, 4.6); ax.axis("off")
    ax.set_title("Depth-3 fan-out tree (F=2 → 8 leaves):\n"
                 "believe poisons every node; the gate keeps all clean.",
                 fontsize=BASE * 0.96, pad=8, color=INK)
    for cx, color, label, corrupt in [
        (2.6, RED, "BELIEVE\n(inherit poison)", True),
        (7.4, GREEN, "ADJUDICATE\n(gate → gold)", False),
    ]:
        ax.text(cx, 4.35, label, ha="center", va="bottom", fontsize=BASE * 0.80,
                color=color, fontweight="bold")
        for li, n in enumerate([2, 4, 8]):   # levels 1..3
            y = 3.4 - li * 1.05
            xs = [cx + (j - (n - 1) / 2) * (3.0 / max(n, 1)) for j in range(n)]
            for x in xs:
                ax.plot(x, y, "o", color=color, markersize=max(4.5, 11 - li * 1.8),
                        zorder=3)
        ax.text(cx, 0.12, ("8/8 corrupt" if corrupt else "0/8 corrupt"),
                ha="center", va="bottom", fontsize=BASE * 0.84, color=color,
                fontweight="bold")
    ax.text(5.0, 2.0, "PAYOFF\nF^D = 8", ha="center", va="center", fontsize=BASE * 1.0,
            fontweight="bold", color=INK,
            bbox=dict(boxstyle="round,pad=0.4", fc="#eff6ff", ec=STEEL, linewidth=1.4))

    fig.suptitle(
        "F1-super-linear: one over-claim caught at the root saves the whole fan-out tree  "
        "(tau2-bench · gemini-2.5-flash, live)",
        fontsize=BASE * 1.0, y=1.005, fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

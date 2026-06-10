#!/usr/bin/env python
"""Figure 1 (hero): the paper's thesis in one picture — WHERE you spend the verdict.

The same byte-clean verdict (a check the agent cannot forge) is HARMFUL spent inside the
producing agent's loop and VALUABLE spent outside it. Two panels, one dividing idea:

  LEFT  — IN-LOOP: hand the verdict back to the agent that earned it. A measured bake-off
          of every active fix (warn / rewind / inject-a-cure) is flat-to-NEGATIVE, because
          injecting any turn disturbs runs that would have passed. The only in-loop action
          that survives is the NEGATIVE one — give up correctly (halts 0 winners, saves
          ~11% compute). [numbers: docs §4 bake-off / _VERIFIED_FACTS_2026-06-07.md]
  RIGHT — OUT-OF-LOOP: hand the SAME verdict to the rest of the fleet. It PAYS, in the two
          distinct ways a fleet fails: refuse a phantom write before a peer inherits it
          (over-claims, J=10 across two models, docs/228/232) and serialize a race so it
          can't clobber shared state (coordination, J=6, docs/233) — both off the
          environment's own ground truth.

DESIGN NOTE — readability over a 0.53x downscale, and three composition fixes over the
prior draft: (1) the REWIND bar is a genuine ZERO, so it gets an explicit flat zero-cap +
"0 of 20" tag rather than rendering as absent data; (2) the give-up survivor is drawn as
its own anchored callout (it is a DIFFERENT KIND of thing from the three red active fixes —
the one action that writes nothing), not a band floating in space; (3) the two panels are
tied by a center spine + a single "the SAME verdict →" hand-off label, so the eye reads one
idea split two ways. Base font 17 at a 13in source lands ~7-9pt on the page.

Every number is transcribed from the verified-facts files (docs/228/232/233 +
_VERIFIED_FACTS_2026-06-07.md). No number is invented here. Derived illustration; if a
facts file changes, regenerate.

    python paper/figs_src/hero_inloop_vs_outofloop.py    # writes the .png alongside
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

OUT = Path(__file__).resolve().parent / "hero_inloop_vs_outofloop.png"

# --- IN-LOOP: the active-fix bake-off (every active fix flat-to-negative) --------------
# x-label, delta (pp of task success), result note
INLOOP = [
    ("WARN", +0.20, "+0.2pp\nflat"),
    ("REWIND", 0.0, "0 of 20\nfixed"),
    ("INJECT\na cure", -5.0, "−5\nworse"),
]
GIVEUP_NOTE = ("GIVE UP — the one survivor\n(writes nothing back):\n"
               "0 of 1,634 winners halted,\n~11% compute saved")

RED = "#dc2626"
GREEN = "#16a34a"
STEEL = "#2563eb"
SLATE = "#334155"
INK = "#1e293b"
MAROON = "#7f1d1d"

# --- OUT-OF-LOOP: the two live payoffs (same witness, two fleet failures) --------------
# short x-label, J (bar height), bar color
OUTOFLOOP = [
    ("refuse a\nphantom write\n(over-claims)", 10, STEEL),
    ("serialize\na race\n(coordination)", 6, GREEN),
]
OUTOFLOOP_FOOT = "J = 10 over 120 tasks (2 models, 8.3% each)   ·   J = 6 over 8 pairs"

BASE = 17.0   # base font; everything scales off this (see DESIGN NOTE)


def main() -> None:
    fig, (axL, axR) = plt.subplots(
        1, 2, figsize=(13.2, 5.7),
        gridspec_kw={"width_ratios": [1.0, 1.0], "wspace": 0.34},
    )

    # ===== LEFT: in-loop, flat-to-negative ============================================
    xs = list(range(len(INLOOP)))
    deltas = [d for _, d, _ in INLOOP]
    bars = axL.bar(xs, deltas, color=RED, edgecolor=INK, linewidth=1.4, width=0.62,
                   zorder=3)
    for x, (label, d, note) in zip(xs, INLOOP):
        if d == 0:
            # a genuine ZERO — draw a flat cap on the baseline so it is visibly
            # "measured null", not missing data.
            axL.plot([x - 0.31, x + 0.31], [0, 0], color=INK, linewidth=3.2,
                     solid_capstyle="butt", zorder=4)
            axL.text(x, 0.35, note, ha="center", va="bottom",
                     fontsize=BASE * 0.78, color=SLATE, fontweight="bold")
        else:
            va = "bottom" if d > 0 else "top"
            off = 0.35 if d > 0 else -0.35
            axL.text(x, d + off, note, ha="center", va=va,
                     fontsize=BASE * 0.78, color=SLATE, fontweight="bold")
    axL.axhline(0, color="#475569", linewidth=1.2, zorder=2)

    # the give-up survivor — its OWN anchored callout, tucked under the WARN/REWIND
    # columns (which sit at ~0, leaving the lower-left free) so it never overlaps the
    # INJECT bar. It is a DIFFERENT KIND of thing from the three red active fixes: the
    # one action that writes nothing back.
    gb_x, gb_y, gb_w, gb_h = -0.62, -7.55, 2.05, 2.7
    axL.add_patch(Rectangle((gb_x, gb_y), gb_w, gb_h, facecolor="#dcfce7",
                            edgecolor=GREEN, linewidth=1.6, zorder=2, clip_on=False))
    axL.text(gb_x + gb_w / 2, gb_y + gb_h / 2, GIVEUP_NOTE, ha="center", va="center",
             fontsize=BASE * 0.70, color="#166534", fontweight="bold", zorder=3,
             linespacing=1.25)

    axL.set_xticks(xs)
    axL.set_xticklabels([l for l, _, _ in INLOOP], fontsize=BASE * 0.80)
    axL.set_ylim(-8.0, 3.0)
    axL.set_xlim(-0.72, 2.72)
    axL.set_ylabel("change in task success (pp)", fontsize=BASE * 0.84)
    axL.set_title("IN-LOOP — hand it back to the agent\nevery active fix is flat-to-HARMFUL",
                  fontsize=BASE * 1.02, pad=12, color=MAROON, fontweight="bold")
    axL.grid(axis="y", linestyle=":", color="#cbd5e1", zorder=0)
    for s in ("top", "right"):
        axL.spines[s].set_visible(False)
    axL.tick_params(axis="y", labelsize=BASE * 0.78)

    # ===== RIGHT: out-of-loop, it pays ================================================
    xs2 = list(range(len(OUTOFLOOP)))
    js = [j for _, j, _ in OUTOFLOOP]
    cols = [c for _, _, c in OUTOFLOOP]
    axR.bar(xs2, js, color=cols, edgecolor=INK, linewidth=1.4, width=0.62, zorder=3)
    for x, (label, j, _c) in zip(xs2, OUTOFLOOP):
        axR.text(x, j + 0.3, f"J = {j}", ha="center", va="bottom",
                 fontsize=BASE * 1.55, fontweight="bold", color=INK)
    axR.set_xticks(xs2)
    axR.set_xticklabels([l for l, _, _ in OUTOFLOOP], fontsize=BASE * 0.82)
    axR.set_ylim(0, 13.5)
    axR.set_xlim(-0.72, 1.72)
    axR.set_ylabel("live payoff J\n(real errors blocked, off ground truth)",
                   fontsize=BASE * 0.82)
    axR.set_title("OUT-OF-LOOP — hand it to the fleet\nthe SAME verdict PAYS, both ways a fleet fails",
                  fontsize=BASE * 1.0, pad=12, color="#166534", fontweight="bold")
    axR.grid(axis="y", linestyle=":", color="#cbd5e1", zorder=0)
    for s in ("top", "right"):
        axR.spines[s].set_visible(False)
    axR.tick_params(axis="y", labelsize=BASE * 0.78)
    axR.text(0.5, -0.165, OUTOFLOOP_FOOT, transform=axR.transAxes, ha="center",
             va="top", fontsize=BASE * 0.72, color=SLATE, fontweight="bold")

    fig.suptitle(
        "The same verdict the agent cannot forge: harmful handed back to it, "
        "valuable handed to anyone else",
        fontsize=BASE * 1.08, y=1.04, fontweight="bold",
    )
    # the give-up callout (clip_on=False) sits just past the axes floor, which makes
    # tight_layout warn; the layout is verified correct and bbox_inches="tight" captures
    # it, so silence that one cosmetic warning to keep the build log clean.
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*not compatible with tight_layout.*")
        fig.tight_layout(rect=(0, 0.03, 1, 0.90))
    fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

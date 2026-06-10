#!/usr/bin/env python
"""Hero figure (Figure 1): the bake-off verdict, in one glance.

This is the opening image of the paper. Its job is to tell the whole story before
the reader has read a word: we tried every way to FIX a failing agent run, and the
only thing that helped was to STOP it.

Top: the three "active" fixes, each plotted as its measured change in task success.
Each one writes a new turn into the agent's loop, and a turn perturbs runs that
would otherwise have passed -- so they land flat (warn), nothing (rewind), or worse
(inject a cure). Bottom: the one action that authors nothing -- give up and stop the
run -- shown as a green verdict band, because it has no task-success delta (it makes
no correction); its value is that it never halts a winning run and saves compute.

EVERY number is transcribed from paper/_VERIFIED_FACTS_2026-06-07.md (the live
single-source-of-truth re-run that day). No number is invented here. This is a
derived illustration; if the facts file changes, regenerate it.

    python paper/figs_src/fig_hero_bakeoff.py   # writes fig_hero_bakeoff.png alongside

Deterministic output: no Date.now()/random used.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Patch

OUT = Path(__file__).resolve().parent / "fig_hero_bakeoff.png"

RED = "#dc2626"      # the active fixes: flat-to-worse
GREEN = "#16a34a"    # the negative action: the survivor
DK_GREEN = "#14532d"
INK = "#1e293b"
MUTE = "#475569"

# Each active fix's measured change in task success (percentage points), on a weak
# model (gemini-2.5-flash) on a second benchmark (EnterpriseOps-Gym).
ACTIVE = [
    # label, delta (pp), the plain-words result
    ("WARN the agent\nhand back its unfinished task", +0.2, "flat   (+0.2 pts ≈ noise)"),
    ("REWIND\ncut out the bad turns and retry", 0.0, "nothing   (0 of 20 runs fixed)"),
    ("INJECT a clean cure\nfeed it the environment’s own fix", -5.0, "worse   (−5 successes)"),
]


def main() -> None:
    # Two stacked regions sharing one x-axis: the bars on top, a verdict band below.
    fig, ax = plt.subplots(figsize=(12.8, 6.2))

    XMIN, XMAX = -8.0, 8.0

    # ---- top region: the three active fixes as bars ---------------------------------
    y_active = [5, 4, 3]
    deltas = [a[1] for a in ACTIVE]
    notes = [a[2] for a in ACTIVE]

    ax.barh(y_active, deltas, color=RED, edgecolor=INK, height=0.6, zorder=3)
    ax.axvline(0, color=MUTE, linewidth=1.3, zorder=2, ymin=0.30)

    for y, d, note in zip(y_active, deltas, notes):
        # always place the note on the POSITIVE side of zero so it never collides
        # with the left-hand y-tick labels
        ax.text(0.25, y, note, va="center", ha="left", fontsize=11, color=INK, zorder=4)

    # ---- the dividing rule: steering above, stopping below --------------------------
    ax.axhline(2.2, color="#cbd5e1", linewidth=1.1, linestyle="--", zorder=1)
    ax.text(XMIN + 0.1, 2.45,
            "STEERING the run — each fix writes a new turn, and a turn perturbs a winning run",
            fontsize=10, color=RED, style="italic", va="center", ha="left")
    ax.text(XMIN + 0.1, 1.55,
            "STOPPING the run — writes nothing, so it perturbs nothing",
            fontsize=10, color=DK_GREEN, style="italic", va="center", ha="left")

    # ---- bottom region: the give-up verdict as a full green callout band ------------
    # A rounded box spanning the width, well clear of the bars and the axis labels.
    band = FancyBboxPatch(
        (XMIN, 0.35), (XMAX - XMIN), 0.95,
        boxstyle="round,pad=0.02,rounding_size=0.15",
        linewidth=1.4, edgecolor=DK_GREEN, facecolor=GREEN, zorder=3,
    )
    ax.add_patch(band)
    ax.text((XMIN + XMAX) / 2, 0.95, "GIVE UP — the only action that helped",
            va="center", ha="center", fontsize=15, color="white",
            fontweight="bold", zorder=4)
    ax.text((XMIN + XMAX) / 2, 0.575,
            "halts 0 of 1,634 winning runs   ·   saves ~11% of the wasted compute",
            va="center", ha="center", fontsize=11.5, color="white", zorder=4)

    # ---- y labels (only the three active fixes get tick labels) ---------------------
    ax.set_yticks(y_active)
    ax.set_yticklabels([a[0] for a in ACTIVE], fontsize=11.5)
    ax.set_ylim(0.1, 5.9)
    ax.set_xlim(XMIN, XMAX)
    ax.set_xlabel("change in task success  (percentage points)  —  higher is better",
                  fontsize=11.5)
    ax.set_xticks([-5, 0, 5])
    ax.set_xticklabels(["−5", "0", "+5"], fontsize=10.5)

    ax.grid(axis="x", linestyle=":", color="#e2e8f0", zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_bounds(-5, 5)
    ax.tick_params(axis="y", length=0)

    # legend ABOVE the plot, out of the data area
    ax.legend(handles=[
        Patch(facecolor=RED, edgecolor=INK,
              label="active fix — writes a new turn into the run (perturbs it)"),
        Patch(facecolor=GREEN, edgecolor=DK_GREEN,
              label="negative action — writes nothing, just stops (safe)"),
    ], loc="lower center", bbox_to_anchor=(0.5, -0.30), ncol=2,
       fontsize=9.8, framealpha=0.0)

    fig.suptitle("Steering a doomed agent run fails; stopping it works",
                 fontsize=17, fontweight="bold", y=1.0, color=INK)
    ax.set_title("We tried every way to fix a failing run. Only one helped — and it was to give up.",
                 fontsize=12, color=MUTE, pad=10)

    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(OUT, dpi=160, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

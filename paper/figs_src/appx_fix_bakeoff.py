#!/usr/bin/env python
"""Appendix figure: the active-fix bake-off — the negative action is the only survivor.

Plain-language companion figure for the paper appendix. Two panels:

  LEFT  — every ACTIVE in-loop fix we measured (warn, rewind, an injected byte-clean
          cure) moved task-success by flat-to-negative; the one NEGATIVE action
          (give up, withhold compute) is the only one that carried value.
  RIGHT — why give-up is the survivor: it is accuracy-FREE where it fires
          (0 winners halted at K>=3, both benchmarks) while still saving tokens.

EVERY number is transcribed from paper/_VERIFIED_FACTS_2026-06-07.md (the live SSOT
re-run that day). No number is invented here. This is a derived illustration, not a
new source of truth — if the facts file changes, regenerate.

    python paper/figs_src/appx_fix_bakeoff.py    # writes appx_fix_bakeoff.png alongside

Date.now()/random are intentionally unused (deterministic output).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

OUT = Path(__file__).resolve().parent / "appx_fix_bakeoff.png"

# --- the verified bake-off numbers (EnterpriseOps-Gym, gemini-2.5-flash) -------------
# label, task-success delta, kind ('active'|'negative'), the honest footnote
# The three ACTIVE fixes are plotted as task-success deltas. Give-up is NOT a
# task-success delta (it authors no correction) — its value is "0 winners halted +
# tokens saved", so it gets its own marker on the zero line, not a competing bar.
BAKEOFF = [
    ("WARN re-surface\n(hand the obligation back)", +0.20, "active",
     "+0.20pp natural = flat"),
    ("Rewind / subtract\n(cut the bad turns)", 0.0, "active",
     "0 conversions, 0 flips"),
    ("Inject a byte-clean cure\n(re-surface the env's own fix)", -5.0, "active",
     "-5 successes (net-negative, p=0.016)"),
]
GIVEUP_LABEL = "Give up correctly\n(withhold compute)"

COL = {
    "negative": "#16a34a",   # green — the survivor
    "active": "#dc2626",     # red — flat-to-negative
}


def main() -> None:
    fig, (axL, axR) = plt.subplots(
        1, 2, figsize=(13.2, 5.0), gridspec_kw={"width_ratios": [1.55, 1.0]}
    )

    # ---- LEFT: the bake-off bars -----------------------------------------------------
    # Three ACTIVE-fix bars at y = 3,2,1; the NEGATIVE action sits apart at y = -0.4.
    labels = [b[0] for b in BAKEOFF]
    deltas = [b[1] for b in BAKEOFF]
    notes = [b[2 + 1] for b in BAKEOFF]
    ypos = [3, 2, 1]

    axL.barh(ypos, deltas, color=COL["active"], edgecolor="#1e293b",
             height=0.5, zorder=3)
    axL.axvline(0, color="#475569", linewidth=1.0, zorder=2)

    for y, d, note in zip(ypos, deltas, notes):
        offset = 0.18 if d >= 0 else -0.18
        ha = "left" if d >= 0 else "right"
        axL.text(d + offset, y, note, va="center", ha=ha, fontsize=8.6,
                 color="#334155")

    # the negative action — a distinguished marker on the zero line, not a bar
    gy = -0.4
    axL.scatter([0], [gy], marker="*", s=320, color=COL["negative"],
                edgecolor="#14532d", linewidth=1.0, zorder=4)
    axL.text(0.22, gy, "0 winners halted (K>=3),  ~11% of fleet tokens saved",
             va="center", ha="left", fontsize=8.6, color="#15803d",
             fontweight="bold")
    axL.axhline(0.35, color="#cbd5e1", linewidth=0.8, linestyle="--", zorder=1)

    axL.set_yticks(ypos + [gy])
    axL.set_yticklabels(labels + [GIVEUP_LABEL], fontsize=9.2)
    axL.set_ylim(-1.0, 3.7)
    axL.set_xlim(-7.6, 4.6)
    axL.set_xlabel("change in task-success (percentage points)", fontsize=10)
    axL.set_title("Every ACTIVE fix was flat-to-negative.\n"
                  "The one NEGATIVE action carried the value.",
                  fontsize=11.5, pad=10)
    axL.grid(axis="x", linestyle=":", color="#cbd5e1", zorder=0)
    for s in ("top", "right"):
        axL.spines[s].set_visible(False)
    axL.legend(handles=[
        Patch(facecolor=COL["active"], edgecolor="#1e293b",
              label="active fix  (authors a turn → perturbs the loop)"),
        Patch(facecolor=COL["negative"], edgecolor="#1e293b",
              label="negative action  (authors nothing → perturbs nothing)"),
    ], loc="lower left", fontsize=8.4, framealpha=0.95)

    # ---- RIGHT: why give-up survives — accuracy-free where it fires -------------------
    # winners halted by the SOUND error-gated gate vs the NAIVE raw-repeat gate, K>=3,
    # pooled across the two benchmarks (Toolathlon 1,634 winners + EnterpriseOps).
    Ks = [2, 3, 4, 5]
    naive = [18, 6, 4, 3]        # Toolathlon raw-repeat false-abandons (verified table)
    gated = [0, 0, 0, 0]         # error-gated false-abandons K>=3 (the 1 at K=2 is EOps)
    gated_k2 = 1                 # one winner at K=2 (EnterpriseOps), shown as the lone dot

    axR.plot(Ks, naive, "o-", color="#dc2626", linewidth=2.2, markersize=7,
             label="naive 'repeat → halt'  (kills pollers)", zorder=3)
    axR.plot(Ks, gated, "s-", color="#16a34a", linewidth=2.2, markersize=7,
             label="error-gated 'repeat ERROR → halt'", zorder=3)
    axR.plot([2], [gated_k2], "s", color="#16a34a", markersize=7, zorder=3)
    axR.axhline(0, color="#94a3b8", linewidth=0.9, linestyle=":", zorder=1)

    axR.annotate("0 winners halted\nfor K>=3 — accuracy-free",
                 xy=(3, 0), xytext=(3.25, 2.4), fontsize=8.8, color="#15803d",
                 ha="left",
                 arrowprops=dict(arrowstyle="->", color="#15803d", lw=1.1))
    axR.annotate("the naive gate never\nreaches zero (kills winners)",
                 xy=(4, 4), xytext=(3.0, 11.0), fontsize=8.8, color="#b91c1c",
                 ha="left",
                 arrowprops=dict(arrowstyle="->", color="#b91c1c", lw=1.1))

    axR.set_xticks(Ks)
    axR.set_xlabel("K  (consecutive same-tool errors to halt)", fontsize=10)
    axR.set_ylabel("winners wrongly halted", fontsize=10)
    axR.set_ylim(-1.2, 19.5)
    axR.set_title("Why give-up survives:\nit halts no winner where it fires",
                  fontsize=11.5, pad=10)
    axR.grid(axis="y", linestyle=":", color="#cbd5e1", zorder=0)
    for s in ("top", "right"):
        axR.spines[s].set_visible(False)
    axR.legend(loc="upper right", fontsize=8.2, framealpha=0.95)

    fig.suptitle(
        "The bake-off: telling a doomed loop to STOP is robust; steering it to "
        "succeed is not  (EnterpriseOps-Gym + Toolathlon)",
        fontsize=12.5, y=1.005,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

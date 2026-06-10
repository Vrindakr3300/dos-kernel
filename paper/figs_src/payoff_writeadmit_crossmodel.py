#!/usr/bin/env python
"""§6.4 figure: the cross-model hardening — the over-claim does NOT shrink at the stronger tier.

docs/228 (the §6 live-payoff figure, payoff_writeadmit_live.py) measured the out-of-loop
write-admission payoff on ONE model and led its caveats with "Small n, one model … a second
model would harden the base-rate." docs/232 ran the second model. This figure folds the two:

  LEFT  — a grouped bar per model: confident writes (slate) vs blocked over-claims (red, = J).
          gemini-2.5-flash J=5, gemini-2.5-pro J=5 — and the over-claim RATE is printed under
          each: 8.3% on BOTH. The stronger model makes nearly 2× the confident writes (17 vs
          9) and admits more correct ones (6 vs 3 confirmed honest writes) yet over-claims on
          the same count of 5. The rate does not fall at the stronger tier.
  RIGHT — the cross-tier overlap: airline 1 fails the witness (a confident write contradicted
          by ground truth) on BOTH models and is blocked on both, and recurs across separate
          flash rollouts — the most reproducible signal in the set, so the residue lands on the
          same hard task rather than on a property of one weak policy. Plus the combined
          headline: J=10 / 120 clean / 0 errors / 9-of-9 honest writes admitted.

EVERY number is transcribed from paper/_VERIFIED_FACTS_232_2026-06-08.md (the verbatim
read-off of benchmark/agentprocessbench/writeadmit/model_index.json — the committed
re-folded cross-model index). No number is invented here. Derived illustration, not a
source of truth — if that facts file changes, regenerate.

    python paper/figs_src/payoff_writeadmit_crossmodel.py    # writes the .png alongside

Deterministic output (no Date.now/random).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent / "payoff_writeadmit_crossmodel.png"

# --- the verified cross-model numbers (tau2-bench; docs/232; model_index.json) ---------
# (label, confident_writes, J_blocked_over_claims, confirmed_admitted, over_claim_rate_pct)
MODELS = [
    ("gemini-2.5-flash", 9, 5, 3, 8.3),
    ("gemini-2.5-pro", 17, 5, 6, 8.3),
]
COMBINED_J = 10
COMBINED_CLEAN = 120          # 60 per model, both ran 60/60 with 0 API errors
COMBINED_CONF_ADMIT = 9       # 9 of 9 confirmed honest writes admitted (flash 3 + pro 6)
COMBINED_RATE = 8.3           # 10/120

# the cross-tier overlap, measured on the matched first-30 run with the current extractor:
# only airline 1 fails the witness (confident write x db_match=False) on BOTH flash and pro
# (intersection of flash {1,5,9,10,29} and pro {1,8,16,17,retail 18}). airline 1 also recurs
# across separate flash rollouts -- the most reproducible signal in the set. (An earlier draft
# listed airline 16 + retail 18 here too, but those over-claim on pro only in this run; their
# flash hit came from the different docs/228 first-25 draw -- a cross-sample union, not a
# matched-run overlap. Narrowed to the one task the matched run actually supports.)
SHARED_TASKS = ["airline 1"]

SLATE_BAR = "#64748b"  # confident writes (the attempts)
RED = "#dc2626"        # over-claim, blocked (the J)
GREEN = "#16a34a"
INK = "#1e293b"
SLATE = "#334155"

BASE = 17.0   # base font; everything scales off this (renders ~9pt on a 0.53x page)


def main() -> None:
    fig, (axL, axR) = plt.subplots(
        1, 2, figsize=(12.6, 5.5), gridspec_kw={"width_ratios": [1.2, 1.0]}
    )

    # ===== LEFT: per-model confident-writes vs blocked over-claims (J), rate annotated ==
    xpos = [0, 1]
    width = 0.36
    conf = [m[1] for m in MODELS]
    js = [m[2] for m in MODELS]
    axL.bar([x - width / 2 for x in xpos], conf, width=width, color=SLATE_BAR,
            edgecolor=INK, linewidth=1.3, zorder=3,
            label="confident write-claims (attempts)")
    axL.bar([x + width / 2 for x in xpos], js, width=width, color=RED,
            edgecolor=INK, linewidth=1.3, zorder=3,
            label="over-claims blocked off the DB-hash  (= J)")

    for x, (label, cw, j, confirmed, rate) in zip(xpos, MODELS):
        axL.text(x - width / 2, cw + 0.4, f"{cw}", ha="center", va="bottom",
                 fontsize=BASE * 0.92, fontweight="bold", color=SLATE)
        axL.text(x + width / 2, j + 0.4, f"J = {j}", ha="center", va="bottom",
                 fontsize=BASE * 0.92, fontweight="bold", color=RED)
        # the headline: the over-claim RATE is identical across the tiers (boxed),
        # with the admitted-honest count beside it; the model name sits at the floor.
        axL.text(x, -1.4, f"{rate:.1f}% over-claim", ha="center", va="top",
                 fontsize=BASE * 0.82, fontweight="bold", color=INK,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="#fef3c7",
                           edgecolor="#d97706", linewidth=1.2))
        axL.text(x, -3.5, f"{confirmed} honest writes, all admitted",
                 ha="center", va="top", fontsize=BASE * 0.64, color=GREEN)
        axL.text(x, -5.4, label, ha="center", va="top", fontsize=BASE * 0.84,
                 fontweight="bold", color=INK)

    axL.set_xticks([])   # model names drawn explicitly at the floor (above)
    axL.set_ylim(-6.2, 19.5)
    axL.set_xlim(-0.6, 1.6)
    axL.set_ylabel("count", fontsize=BASE * 0.84)
    axL.set_title("The over-claim rate does NOT shrink at the stronger tier —\n"
                  "8.3% on both; the stronger model just attempts more.",
                  fontsize=BASE * 0.96, pad=12, color=INK)
    axL.axhline(0, color="#475569", linewidth=1.2, zorder=2)
    axL.grid(axis="y", linestyle=":", color="#cbd5e1", zorder=0)
    for s in ("top", "right"):
        axL.spines[s].set_visible(False)
    axL.tick_params(axis="y", labelsize=BASE * 0.76)
    axL.legend(loc="upper center", bbox_to_anchor=(0.5, 1.0), fontsize=BASE * 0.72,
               framealpha=0.95)

    # ===== RIGHT: the combined headline + the reproducible cross-tier signal ============
    axR.axis("off")
    # the combined J=10, large and central
    axR.text(0.5, 0.93, "COMBINED", ha="center", va="top", fontsize=BASE * 0.86,
             fontweight="bold", color=SLATE, transform=axR.transAxes)
    axR.text(0.5, 0.83, f"J = {COMBINED_J}", ha="center", va="top",
             fontsize=BASE * 2.6, fontweight="bold", color=RED,
             transform=axR.transAxes)
    axR.text(0.5, 0.55, f"over {COMBINED_CLEAN} clean tasks", ha="center", va="top",
             fontsize=BASE * 0.92, color=INK, fontweight="bold",
             transform=axR.transAxes)
    axR.text(0.5, 0.47,
             f"two models · 0 API errors\n{COMBINED_CONF_ADMIT} of "
             f"{COMBINED_CONF_ADMIT} honest writes admitted · {COMBINED_RATE:.1f}%",
             ha="center", va="top", fontsize=BASE * 0.72, color=SLATE,
             transform=axR.transAxes)

    # the reproducible signal — one task blocked on BOTH tiers — as a boxed callout
    axR.add_patch(plt.Rectangle((0.10, 0.05), 0.80, 0.26, transform=axR.transAxes,
                                facecolor="#fef2f2", edgecolor=RED, linewidth=1.4,
                                zorder=1))
    axR.text(0.5, 0.265, f"●  {SHARED_TASKS[0]}  ●", ha="center", va="top",
             fontsize=BASE * 0.92, color=RED, fontweight="bold",
             transform=axR.transAxes, zorder=2)
    axR.text(0.5, 0.175,
             "the SAME hard task fails the witness\non flash AND pro (and across flash rollouts)",
             ha="center", va="top", fontsize=BASE * 0.68, color=SLATE,
             transform=axR.transAxes, zorder=2)

    fig.suptitle(
        "The out-of-loop payoff, hardened across two capability tiers — same gate, "
        "same 8.3% rate  (tau2-bench · gemini-2.5-flash + -pro · J = 10)",
        fontsize=BASE * 1.0, y=1.005, fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

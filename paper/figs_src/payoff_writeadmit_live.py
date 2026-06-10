#!/usr/bin/env python
"""§6 figure: the live out-of-loop payoff — Tier-B, run live, J = 5.

The paper's body proves DETECT-not-FIX and that every *in-loop* active fix is
flat-to-negative (§4.3). This figure is the other half: the one fix that pays is the
*out-of-loop* re-read the paper called Tier-B "future" (§5) — now run live on tau2
through Gemini, catching real agent over-claims the environment's own DB-hash
refutes. Two panels:

  LEFT  — the headline contrast. RUN A re-runs the frozen 13.6% over-claim slice
          through a capable live policy and the over-claims EVAPORATE (J=0). RUN B
          draws a fresh write-heavy natural sample and the payoff appears (J=5).
          Same gate, same witness — only the task distribution differs.
  RIGHT — Run B's ledger: of 14 confident writes, 9 were CORRECT (db_match=True →
          ADMITTED, green) and 5 were OVER-CLAIMS (db_match=False → BLOCKED, the J,
          red), at an 11.6% natural over-claim rate that lands next to the frozen
          13.6% estimate — but now live and causal.

DESIGN NOTE — readability over a 0.53x downscale. This figure renders both-columns
wide (~178mm) from a 12in source, i.e. shrunk to ~0.53x. So every font here is sized
so its ON-PAGE size clears ~7pt: nothing in-source below ~13pt. The prose that used to
live inside the panels (which rendered at ~4pt and was unreadable) now lives in the
caption — the figure carries the NUMBERS, the caption carries the argument.

EVERY number is transcribed from paper/_VERIFIED_FACTS_228_2026-06-08.md (the verbatim
read-off of docs/228, the executed live run). No number is invented here. This is a
derived illustration, not a new source of truth — if that facts file changes,
regenerate.

    python paper/figs_src/payoff_writeadmit_live.py    # writes the .png alongside

Date.now()/random are intentionally unused (deterministic output).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

OUT = Path(__file__).resolve().parent / "payoff_writeadmit_live.png"

# --- the verified live numbers (tau2-bench, gemini-2.5-flash; docs/228) ---------------
# Run A: the frozen 13.6% over-claim slice re-run live -> over-claims evaporate.
RUN_A_J = 0

# Run B: a fresh write-heavy NATURAL sample (--sample 25) -> the live payoff.
RUN_B_J = 5
RUN_B_CLEAN = 43          # ran clean (50 drawn; 7 retail hit transient API 5xx)
RUN_B_CONF_WRITES = 14    # confident write-claims
RUN_B_CONFIRMED = 9       # db_match=True  -> correctly ADMITTED
RUN_B_REFUTED = 5         # db_match=False -> live over-claims, BLOCKED (== J)
RUN_B_BASERATE = 11.6     # 5/43 natural over-claim base-rate
FROZEN_SLICE = 13.6       # docs/216 §2 frozen estimate (reference tick; live ~ frozen)

GREEN = "#16a34a"   # CORRECT write, admitted (the gate does not block correct work)
RED = "#dc2626"     # over-claim, blocked (the J)
GREY = "#94a3b8"    # Run A — nothing to catch
INK = "#1e293b"
SLATE = "#334155"

# A single base size; every other size is this scaled, so the whole figure rides up
# or down together. At 12in source -> 0.53x on-page, base 17 lands ~9pt on the page.
BASE = 17.0


def main() -> None:
    fig, (axL, axR) = plt.subplots(
        1, 2, figsize=(12.0, 5.6), gridspec_kw={"width_ratios": [1.0, 1.0]}
    )

    # ===== LEFT: the headline contrast — Run A (evaporates) vs Run B (payoff) ==========
    runs = [
        ("RUN A", "frozen slice,\nreplayed live", RUN_A_J, GREY, "nothing to catch"),
        ("RUN B", "fresh write-heavy\nsample", RUN_B_J, RED, "the live payoff"),
    ]
    xpos = [0, 1]
    axL.bar(xpos, [r[2] for r in runs], color=[r[3] for r in runs],
            edgecolor=INK, linewidth=1.4, width=0.58, zorder=3)
    for x, (tag, sub, j, c, note) in zip(xpos, runs):
        # the headline J, large
        axL.text(x, j + 0.30, f"J = {j}", ha="center", va="bottom",
                 fontsize=BASE * 1.65, fontweight="bold",
                 color=(GREEN if j > 0 else SLATE))
        # a one-line verdict under the J
        axL.text(x, j + 1.55, note, ha="center", va="bottom",
                 fontsize=BASE * 0.82, color=c, fontweight="bold")
    # the bar's own two-line label (tag + sub) on the x-axis
    axL.set_xticks(xpos)
    axL.set_xticklabels([f"{r[0]}\n{r[1]}" for r in runs], fontsize=BASE * 0.86)
    axL.set_ylim(0, 8.2)
    axL.set_xlim(-0.62, 1.62)
    axL.set_ylabel("over-claims caught + blocked\n(off the env DB-hash)",
                   fontsize=BASE * 0.86)
    axL.set_title("Same gate, same witness — opposite J.\nOnly the task distribution differs.",
                  fontsize=BASE * 1.0, pad=12, color=INK)
    axL.grid(axis="y", linestyle=":", color="#cbd5e1", zorder=0)
    for s in ("top", "right"):
        axL.spines[s].set_visible(False)
    axL.tick_params(axis="y", labelsize=BASE * 0.78)

    # ===== RIGHT: Run B's ledger — 9 correct ADMITTED vs 5 over-claims BLOCKED =========
    axR.bar([0], [RUN_B_CONFIRMED], color=GREEN, edgecolor=INK, linewidth=1.4,
            width=0.52, zorder=3,
            label=f"correct write  →  ADMITTED   ({RUN_B_CONFIRMED})")
    axR.bar([0], [RUN_B_REFUTED], bottom=[RUN_B_CONFIRMED], color=RED,
            edgecolor=INK, linewidth=1.4, width=0.52, zorder=3,
            label=f"over-claim  →  BLOCKED   ({RUN_B_REFUTED} = J)")
    axR.text(0, RUN_B_CONFIRMED / 2, f"{RUN_B_CONFIRMED}", ha="center", va="center",
             fontsize=BASE * 1.2, fontweight="bold", color="white")
    axR.text(0, RUN_B_CONFIRMED + RUN_B_REFUTED / 2, f"{RUN_B_REFUTED}",
             ha="center", va="center", fontsize=BASE * 1.2, fontweight="bold",
             color="white")
    axR.text(0, RUN_B_CONF_WRITES + 0.35, f"{RUN_B_CONF_WRITES} confident writes",
             ha="center", va="bottom", fontsize=BASE * 0.82, color=SLATE,
             fontweight="bold")

    # the natural-rate callout, as a compact boxed number (not a paragraph)
    box_x, box_y, box_w, box_h = 0.84, 3.9, 1.08, 6.6
    axR.add_patch(Rectangle(
        (box_x, box_y), box_w, box_h, linewidth=1.4, edgecolor=RED,
        facecolor="#fef2f2", zorder=2, clip_on=False))
    cx = box_x + box_w / 2
    axR.text(cx, box_y + box_h - 1.0, f"{RUN_B_BASERATE:.1f}%", ha="center",
             va="center", fontsize=BASE * 1.05, fontweight="bold", color=RED)
    axR.text(cx, box_y + box_h - 2.5, "natural\nover-claim rate", ha="center",
             va="center", fontsize=BASE * 0.72, color=SLATE)
    axR.text(cx, box_y + 1.35, f"frozen est. {FROZEN_SLICE:.1f}%\n(live ≈ frozen,\nnow causal)",
             ha="center", va="center", fontsize=BASE * 0.64, color="#64748b",
             style="italic")

    axR.set_xticks([0])
    axR.set_xticklabels(["Run B"], fontsize=BASE * 0.86)
    axR.set_xlim(-0.55, 2.05)
    axR.set_ylim(0, 16.8)
    axR.set_ylabel("confident write-claims", fontsize=BASE * 0.86)
    axR.set_title("The gate is sound BOTH ways:\nadmits all 9 correct, blocks all 5 phantoms.",
                  fontsize=BASE * 1.0, pad=12, color=INK)
    axR.grid(axis="y", linestyle=":", color="#cbd5e1", zorder=0)
    for s in ("top", "right"):
        axR.spines[s].set_visible(False)
    axR.tick_params(axis="y", labelsize=BASE * 0.78)
    axR.legend(loc="upper center", bbox_to_anchor=(0.5, -0.085), fontsize=BASE * 0.74,
               framealpha=0.95, ncol=1, handlelength=1.4, borderpad=0.5)

    fig.suptitle(
        "Run live: an out-of-loop write-admission gate blocks real over-claims "
        "the environment refutes  (tau2-bench · gemini-2.5-flash · J = 5)",
        fontsize=BASE * 1.02, y=1.005, fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.94))
    fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

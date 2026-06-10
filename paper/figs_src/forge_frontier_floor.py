#!/usr/bin/env python
"""§2 figure: the floor is a LADDER — a path-touching stub fools presence; behavior holds.

docs/272 Phase 1b ran the docs/206 forgeability head-to-head with the NEWEST frontier model
(Fable 5, claude-fable-5) in the judge seat, accessed directly through the Claude Code CLI
(`claude -p`) — the model named only in $DOS_LLM_JUDGE_CMD, zero SDK. The Phase-1 catalogue
was easy (its forgeries touched the WRONG files, so a file-counting rung refused them for
free); Phase 1b adds three HARD forges that touch the EXACT deliverable paths — the adversary
a verifier-optimizing model actually is — and a second non-forgeable rung that catches them.

  LEFT  — the non-forgeable floor is a LADDER of rising forgery-resistance. Three rungs, each
          asking a harder question the agent's narration cannot answer: the forgeable subject
          rung (greps the commit message) is fooled 7/8; the PRESENCE rung (which files HEAD
          touched) is non-forgeable to narration but content-blind, so a path-touching stub
          FOOLS it 2/8; the BEHAVIOR rung (the OS runs the test, reads the exit code — a
          returncode the agent cannot forge) holds at 0/8, catching the stubs the presence
          rung admits. The rung you must stand on rises with the forger's sophistication; DOS
          has a non-forgeable one at every level.
  RIGHT  — the secondary finding: a STRONGER witness makes even the learned judge functional.
          On the one honest landing, Fable+evidence handed only files-touched ABSTAINS (0/1,
          the Phase-1 posture); handed the OS-recorded test-result too, it CONFIRMS the landing
          (1/1). The blind judge (narration alone) stays non-functional (0/1). The judge is only
          as good as the evidence the kernel computes for it — so the floor's value (it computes
          these non-forgeable witnesses, including running the code, free, every time) lifts the
          judge as well as standing alone.

EVERY number is transcribed from benchmark/fleet_horizon/results_fable5_ladder_20260609.json
(the committed Phase-1b forge run). No number is invented here. Derived illustration, not a
source of truth — if that facts file changes, regenerate.

    python paper/figs_src/forge_frontier_floor.py    # writes the .png alongside

Deterministic output (no Date.now/random).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent / "forge_frontier_floor.png"

# --- the verified forge numbers (docs/272 Phase 1b; results_fable5_ladder_20260609.json) ----
N_ATTACKS = 8   # 7 forgeries + the honest no-op (all NOT-actually-shipped)
N_LANDINGS = 1  # the one honest landing

# LEFT: the LADDER — false-accepts on the 8 not-shipped artifacts, per non-forgeable rung.
# Ordered by rising forgery-resistance. (label, false_accept, kind) where kind drives color:
#   "forgeable" = red (fooled by design), "fooled" = amber (non-forgeable but content-blind,
#   fooled by the hard forge), "floor" = green (the rung that holds).
LADDER = [
    ("D-subject\ngreps the message", 7, "forgeable"),
    ("D-artifact\nwhich files it touched", 2, "fooled"),
    ("D-test\ndoes the code run?", 0, "floor"),
]

# RIGHT: the judge true-accept on the ONE honest landing, by the strength of the witness it was
# handed. The point: a stronger NON-FORGEABLE witness makes the same model functional.
# (label, true_accept, is_functional)
JUDGE_BY_WITNESS = [
    ("Fable judge\nnarration only\n(blind)", 0, False),
    ("Fable judge\n+ files touched\n(Phase 1)", 0, False),
    ("Fable judge\n+ the OS ran the test\n(Phase 1b)", 1, True),
]

RED = "#dc2626"        # forgeable / fooled-by-design (bad)
AMBER = "#d97706"      # non-forgeable but content-blind — fooled by the hard forge
GREEN = "#16a34a"      # the floor (holds)
SLATE_BAR = "#64748b"  # the judge, non-functional
INK = "#1e293b"
SLATE = "#334155"

BASE = 17.0   # base font; everything scales off this


def main() -> None:
    fig, (axL, axR) = plt.subplots(
        1, 2, figsize=(13.2, 5.7), gridspec_kw={"width_ratios": [1.15, 1.15]}
    )

    # ===== LEFT: the ladder of non-forgeable rungs ======================================
    xs = list(range(len(LADDER)))
    colormap = {"forgeable": RED, "fooled": AMBER, "floor": GREEN}
    for x, (label, fa, kind) in zip(xs, LADDER):
        color = colormap[kind]
        axL.bar(x, fa, width=0.60, color=color, edgecolor=INK, linewidth=1.3, zorder=3)
        axL.text(x, fa + 0.14, f"{fa}/{N_ATTACKS}", ha="center", va="bottom",
                 fontsize=BASE * 0.92, fontweight="bold", color=color)
    # annotate the story under each bar
    axL.text(0, -0.78, "fooled by the\nsubject line", ha="center", va="top",
             fontsize=BASE * 0.58, color=RED, fontstyle="italic")
    axL.text(1, -0.78, "fooled by a stub that\ntouches the right files",
             ha="center", va="top", fontsize=BASE * 0.58, color=AMBER, fontstyle="italic")
    axL.text(2, -0.78, "holds — the OS authored\nthe exit code, not the agent",
             ha="center", va="top", fontsize=BASE * 0.58, color=GREEN, fontstyle="italic")
    # the rising-floor arrow across the ladder
    axL.annotate("", xy=(2.0, 6.7), xytext=(0.0, 6.7),
                 arrowprops=dict(arrowstyle="->", color=SLATE, linewidth=1.6))
    axL.text(1.0, 7.0, "each rung up asks a harder non-forgeable question",
             ha="center", va="bottom", fontsize=BASE * 0.56, color=SLATE, fontstyle="italic")

    axL.set_xticks(xs)
    axL.set_xticklabels([c[0] for c in LADDER], fontsize=BASE * 0.62, color=INK)
    axL.set_ylim(-2.3, 8.2)
    axL.set_xlim(-0.7, 2.7)
    axL.set_ylabel(f"false-accepts on the {N_ATTACKS} forgeries\n(lower is better)",
                   fontsize=BASE * 0.72)
    axL.set_title("The floor is a ladder: a path-touching stub fools\n"
                  "the file rung; the behavior rung still catches it.",
                  fontsize=BASE * 0.84, pad=10, color=INK)
    axL.axhline(0, color="#475569", linewidth=1.2, zorder=2)
    axL.grid(axis="y", linestyle=":", color="#cbd5e1", zorder=0)
    for s in ("top", "right"):
        axL.spines[s].set_visible(False)
    axL.tick_params(axis="y", labelsize=BASE * 0.7)

    # ===== RIGHT: a stronger witness makes the learned judge functional =================
    xs2 = list(range(len(JUDGE_BY_WITNESS)))
    for x, (label, ta, functional) in zip(xs2, JUDGE_BY_WITNESS):
        color = GREEN if functional else SLATE_BAR
        # draw a faint outline at height 1 so a 0 bar still reads against the /1 ceiling
        axR.bar(x, 1, width=0.58, color="none", edgecolor="#cbd5e1",
                linewidth=1.0, linestyle=":", zorder=1)
        axR.bar(x, ta, width=0.58, color=color, edgecolor=INK, linewidth=1.3, zorder=3)
        lbl_color = GREEN if functional else RED
        axR.text(x, ta + 0.035, f"{ta}/{N_LANDINGS}", ha="center", va="bottom",
                 fontsize=BASE * 0.9, fontweight="bold", color=lbl_color)
        if not functional:
            axR.text(x, 0.5, "abstains", ha="center", va="center",
                     fontsize=BASE * 0.6, color=SLATE, fontstyle="italic", rotation=0)

    axR.set_xticks(xs2)
    axR.set_xticklabels([c[0] for c in JUDGE_BY_WITNESS], fontsize=BASE * 0.58, color=INK)
    axR.set_ylim(-0.05, 1.32)
    axR.set_xlim(-0.7, 2.7)
    axR.set_ylabel(f"the same Fable judge: true-accept\non the honest landing (/{N_LANDINGS})",
                   fontsize=BASE * 0.70)
    axR.set_title("A stronger non-forgeable witness makes\n"
                  "even the learned judge functional.",
                  fontsize=BASE * 0.84, pad=10, color=INK)
    axR.axhline(0, color="#475569", linewidth=1.2, zorder=2)
    axR.grid(axis="y", linestyle=":", color="#cbd5e1", zorder=0)
    for s in ("top", "right"):
        axR.spines[s].set_visible(False)
    axR.tick_params(axis="y", labelsize=BASE * 0.7)

    fig.suptitle(
        "The non-forgeable floor is a ladder — DOS still catches the newest model's best forgery, "
        "because the top rung is a byte the agent cannot author\n(docs/206 forge head-to-head, "
        "Phase 1b · Fable 5 via `claude -p` · file rung fooled 2/8 by a path-touching stub, "
        "behavior rung 0/8, real work confirmed 1/1)",
        fontsize=BASE * 0.76, y=1.03, fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

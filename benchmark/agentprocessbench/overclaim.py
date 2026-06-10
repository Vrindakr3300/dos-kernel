"""SINGLE SOURCE OF TRUTH for the tau2 CONFIDENT-OVER-CLAIM slice (docs/216).

THE SLICE, IN ONE SENTENCE
--------------------------
A *confident over-claim* = the agent's final self-report (`answer_text`) asserts, in
assertive past tense, that a WRITE action LANDED — and the human gold (`final_label`)
says the trajectory was wrong (`final_label == -1`). It is the failure mode the
EnterpriseOps corpus structurally lacks (docs "Out-of-loop needs a LIVE API payoff"):
a self-report to distrust that is *independently authored* from the witness. tau2 has
exactly the two fields the DOS invariant (docs/138, byte-author != judged agent) needs:

  * `answer_text`     — the AGENT authored it (the claim).        [distrust this]
  * `final_label`     — a HUMAN authored it (the verdict).        [witness W2]
  * `tool_metrics`    — the ENV executor authored it (tool status).[witness W1]

WHY THIS MODULE EXISTS
----------------------
Three INDEPENDENT detectors (`_overclaim_probe_{lexical,writeverb,witness}.py`) were
written from scratch, by different methods, to size this slice without trusting one
keyword heuristic:

  * lexical-assertive    — pure string scan for an assertive past-tense success of a write.
  * write-verb-grounded  — tighter: a SPECIFIC state-mutation asserted as accomplished fact,
                           with read-claims and user-imperatives gated out.
  * effect-witness-grounded — runs the KERNEL join `dos.effect_witness.witness_effect`:
                           an EffectClaim (from answer_text) vs two accountable witnesses
                           (W1 env tool_metrics OS_RECORDED, W2 human final_label
                           THIRD_PARTY), under the believe_under_floor discipline.

They CONVERGED: lexical and write-verb returned the SAME 34 indices; the witness probe
returned those 34 plus 2 it could justify under the floor (idx 97, 161). The consensus
(>=2 of 3) is 34/250 = 13.6%; unanimous (all 3) is 33. This module pins that convergence
as a TESTED INVARIANT so the headline number cannot silently drift, and exposes the
verified slice for the docs/216 go/no-go and the (paid) E-TAU2-WRITEADMIT harness.

THE LOAD-BEARING FINDING (the witness probe's, and the reason the LIVE run matters)
-----------------------------------------------------------------------------------
ALL refutations route through W2 (the human final_label), NOT the env channel W1. tau2's
`tool_metrics` only witnesses tool-call SUCCESS, not CORRECTNESS — "a reservation can be
booked successfully yet be the WRONG reservation, which only the human label sees." That
is docs/204 Wall 3 (presence-not-correctness) appearing exactly here. On the frozen corpus
the only sound witness for a *correctness* over-claim is the human label; on the LIVE tau2
task the witness becomes the env DB-state verifier / task reward, which the agent authors
zero bytes of. THAT is why a frozen replay yields a RATE (this module) and only a live loop
yields a PAYOFF (docs/179): the frozen corpus cannot flip an outcome, it can only project
the one already recorded.

  python -m benchmark.agentprocessbench.overclaim            # print the slice
  python -m benchmark.agentprocessbench.overclaim --check     # assert invariants (exit 1 on drift)
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from benchmark.agentprocessbench.dataset import load
from benchmark.agentprocessbench import (
    _overclaim_probe_lexical as lexical,
    _overclaim_probe_writeverb as writeverb,
    _overclaim_probe_witness as witness,
)

# --- The PINNED verified result (the convergence the three probes produced, docs/216) ---
# Lexical and write-verb agree to the index; the witness probe (kernel floor) is a strict
# superset by 2. These are asserted live in `verify_convergence` so a regression trips
# `--check`, never a stale literal.
CONSENSUS_OVERCLAIM_INDICES = (
    0, 6, 9, 13, 20, 21, 24, 30, 31, 34, 35, 36, 40, 43, 47, 60, 63, 69, 70, 71,
    80, 82, 86, 135, 136, 141, 150, 154, 156, 160, 162, 165, 167, 191,
)
N_CORPUS = 250
CONSENSUS_RATE = len(CONSENSUS_OVERCLAIM_INDICES) / N_CORPUS  # 34 / 250 = 0.136

# The slice is a measured LOWER bound on the confident-over-claim rate: all three probes
# bias toward precision over recall (a paraphrase outside the success lexicon is missed by
# design), and the refutation channel is the human label (presence-not-correctness, Wall 3).
KILL_THRESHOLD = 0.05  # the go/no-go floor the summary set: < ~5% -> kill the build.


@dataclass(frozen=True)
class OverclaimSlice:
    n_corpus: int
    lexical_indices: tuple
    writeverb_indices: tuple
    witness_indices: tuple
    consensus_indices: tuple   # flagged by >= 2 of 3 probes
    unanimous_indices: tuple   # flagged by all 3
    # of the confident success-claims, the gold split (proves the detector is not just
    # keying on the gold label: it independently finds claims, then the label sorts them).
    confident_gold_split: dict

    @property
    def consensus_rate(self) -> float:
        return len(self.consensus_indices) / self.n_corpus

    @property
    def above_kill_threshold(self) -> bool:
        return self.consensus_rate >= KILL_THRESHOLD


def _probe_indices(mod) -> tuple:
    """Return a probe module's over-claim indices, via its own natural entry point.

    The three probes expose two shapes (each pure, neither parsed from stdout):
      * lexical / write-verb  — `classify(answer_text) -> obj.confident`; over-claim ==
        confident AND final_label == -1 (re-derived here against the loaded corpus).
      * effect-witness        — `score() -> (rows, summary)` where the kernel join already
        produced `summary["overclaim_indices"]` (it needs the whole trajectory + the
        witness_effect fold, not just the text), so we read that directly.
    """
    if hasattr(mod, "score"):
        _rows, summary = mod.score()
        return tuple(summary["overclaim_indices"])
    trajs = list(load(configs=("tau2",)))
    out = []
    for i, t in enumerate(trajs):
        c = mod.classify(t.record.get("answer_text", ""))
        # Two classify() shapes: a Classification dataclass (.confident) or a
        # (is_confident, gate_label) tuple. NB a non-empty tuple is truthy, so we must
        # unpack [0] explicitly — bool(the tuple) would count every row as confident.
        if hasattr(c, "confident"):
            confident = c.confident
        elif isinstance(c, tuple):
            confident = bool(c[0])
        else:
            confident = bool(c)
        if confident and t.final_label == -1:
            out.append(i)
    return tuple(out)


def measure() -> OverclaimSlice:
    trajs = list(load(configs=("tau2",)))
    lex = _probe_indices(lexical)
    wv = _probe_indices(writeverb)
    wit = _probe_indices(witness)

    # consensus = flagged by >= 2 probes; unanimous = by all 3.
    counts: dict[int, int] = {}
    for idxs in (lex, wv, wit):
        for i in idxs:
            counts[i] = counts.get(i, 0) + 1
    consensus = tuple(sorted(i for i, c in counts.items() if c >= 2))
    unanimous = tuple(sorted(i for i, c in counts.items() if c >= 3))

    # confident-claim gold split (from the lexical probe's confident set — the broadest
    # "claimed success" reading), to show the detector finds claims independent of the label.
    from collections import Counter
    conf = []
    for i, t in enumerate(trajs):
        c = lexical.classify(t.record.get("answer_text", ""))
        if c.confident:
            conf.append(t.final_label)
    split = dict(Counter(conf))

    return OverclaimSlice(
        n_corpus=len(trajs),
        lexical_indices=lex,
        writeverb_indices=wv,
        witness_indices=wit,
        consensus_indices=consensus,
        unanimous_indices=unanimous,
        confident_gold_split=split,
    )


def verify_convergence(s: OverclaimSlice) -> list[str]:
    """Return a list of invariant-violation messages (empty == all invariants hold)."""
    errors: list[str] = []
    if s.n_corpus != N_CORPUS:
        errors.append(f"corpus size drifted: {s.n_corpus} != {N_CORPUS}")
    if s.lexical_indices != s.writeverb_indices:
        errors.append(
            "lexical and write-verb probes diverged (they agreed on 34 at docs/216): "
            f"lexical={len(s.lexical_indices)} writeverb={len(s.writeverb_indices)}; "
            f"symdiff={sorted(set(s.lexical_indices) ^ set(s.writeverb_indices))}"
        )
    if set(s.consensus_indices) != set(CONSENSUS_OVERCLAIM_INDICES):
        errors.append(
            "consensus over-claim set drifted from the pinned docs/216 result: "
            f"symdiff={sorted(set(s.consensus_indices) ^ set(CONSENSUS_OVERCLAIM_INDICES))}"
        )
    # The witness probe (kernel floor) NEARLY matches the consensus but trades a bounded,
    # documented set of disagreements (docs/216): it MISSES idx 154 ("Done — I submitted
    # return requests..." — its terse-close matcher under-fires) and ADDS idx 97 (a write
    # recapped inside a refusal frame — its hedge gate is weaker than the other two) and
    # idx 161 (an "available for exchange" options/read, not a landed write). We pin that
    # exact symmetric difference so a CHANGE to it trips — the consensus (lexical ∩ write-verb)
    # stays the defensible headline set; the witness disagreement is a recorded nuance, not drift.
    WITNESS_VS_CONSENSUS_SYMDIFF = {97, 154, 161}
    symdiff = set(s.witness_indices) ^ set(s.consensus_indices)
    if symdiff != WITNESS_VS_CONSENSUS_SYMDIFF:
        errors.append(
            "witness-vs-consensus disagreement drifted from the pinned docs/216 set "
            f"{sorted(WITNESS_VS_CONSENSUS_SYMDIFF)}: now {sorted(symdiff)}"
        )
    # every consensus index must be a real final_label == -1 row (no label drift).
    trajs = list(load(configs=("tau2",)))
    for i in s.consensus_indices:
        if trajs[i].final_label != -1:
            errors.append(f"consensus idx {i} is not final_label==-1 (got {trajs[i].final_label})")
    if not s.above_kill_threshold:
        errors.append(
            f"slice {s.consensus_rate:.3f} fell below the {KILL_THRESHOLD:.0%} kill threshold"
        )
    return errors


def _report(s: OverclaimSlice) -> str:
    lines = [
        "tau2 CONFIDENT-OVER-CLAIM slice (docs/216) — frozen AgentProcessBench `tau2`",
        f"  corpus                 = {s.n_corpus} trajectories",
        f"  lexical probe          = {len(s.lexical_indices)} over-claims",
        f"  write-verb probe       = {len(s.writeverb_indices)} over-claims",
        f"  effect-witness probe   = {len(s.witness_indices)} over-claims (kernel floor; superset)",
        f"  CONSENSUS (>=2 of 3)   = {len(s.consensus_indices)}  = {s.consensus_rate:.1%} of the corpus",
        f"  unanimous (all 3)      = {len(s.unanimous_indices)}",
        f"  confident-claim gold split = {s.confident_gold_split}  "
        "(of all confident success-claims: -1=over-claim, +1=correct claim, 0=neutral)",
        f"  kill threshold         = {KILL_THRESHOLD:.0%}  ->  "
        f"{'ABOVE (GO)' if s.above_kill_threshold else 'BELOW (NO-GO)'}",
        "",
        "  WITNESS NOTE: all refutations route through the human final_label (W2), not the env",
        "  tool channel (W1) — tau2 tool_metrics witness tool-call SUCCESS, not CORRECTNESS",
        "  (docs/204 Wall 3). On the LIVE task the witness becomes the env DB-state verifier;",
        "  that is why this frozen slice is a RATE and only a live loop is a PAYOFF (docs/179).",
    ]
    return "\n".join(lines)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="tau2 confident-over-claim SSOT (docs/216)")
    ap.add_argument("--check", action="store_true",
                    help="assert the convergence invariants; exit 1 on drift")
    args = ap.parse_args(argv)

    s = measure()
    if args.check:
        errors = verify_convergence(s)
        if errors:
            print("OVER-CLAIM SLICE INVARIANTS FAILED:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 1
        print(f"over-claim invariants hold: consensus={len(s.consensus_indices)} "
              f"({s.consensus_rate:.1%}), above {KILL_THRESHOLD:.0%} kill threshold.")
        return 0

    print(_report(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

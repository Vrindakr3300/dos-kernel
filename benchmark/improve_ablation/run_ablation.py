"""The keep-gate ablation runner (docs/318 P1, issue #21) — the ratchet curve.

Run the SAME self-improving recipe loop three times, identical in proposer,
mutation stream, budget, and task — one decision rule apart:

  A  gated           keep iff `dos.improve.classify` says KEEP over the
                     referee's K-seed held-out measure (ESCALATE honored:
                     the arm stops proposing — the RSI human-judgment seed).
  B  self-certified  keep iff the proposer's own in-sample estimate claims
                     improvement. The referee still measures every cycle FOR
                     THE RECORD; the decision never reads it.
  C  gated, 1-seed   arm A's rule with K=1 — the shipped gate exactly as
                     issue #34 worries about it: a noise spike can mint a
                     KEEP and poison the carried baseline.

A vs B isolates what the gate buys; A vs C isolates what the multi-sample
measurement discipline buys (no kernel change involved — the noise control
lives in the measurement the driver feeds the gate, the docs/280 boundary).

Everything flows from one --seed. The committed RESULTS.md / results.json are
reproduced by:

    python -m benchmark.improve_ablation.run_ablation --seed 0

Imports `dos` (the allowed direction); nothing under src/dos/ knows this
exists.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Dict, List, Optional

from dos import improve

from benchmark.improve_ablation import baits, task

INITIAL = task.Recipe(order=1, add_k=1.0)

# Seed-stream tags — every random draw in the run derives from
# (master, tag, index) so arms share streams where fairness wants it (the
# mutation, proposer, and bait streams) and never share where independence
# does (each cycle's gate windows are fresh). _TAG_BAIT (docs/318 P2) drives
# the bait choice from a stream shared across arms, so every arm faces the
# SAME hack on the SAME cycle — the scoreboard compares decision rules, not luck.
_TAG_CORPUS, _TAG_REF, _TAG_GATE, _TAG_PLOT, _TAG_FRESH, _TAG_MUT, _TAG_PROP, _TAG_BAIT = range(1, 9)


def _seed(master: int, tag: int, idx: int = 0) -> int:
    return master * 1_000_003 + tag * 10_007 + idx


class _Referee:
    """The measurement boundary. Memoizes per-recipe measures on the FIXED
    seed blocks (plot/fresh) so the curve is cheap; gate measures use fresh
    per-cycle seeds and are never cached."""

    def __init__(self, corpus: str, master: int, plot_seeds: int, fresh_seeds: int):
        self.corpus = corpus
        self.master = master
        self._plot_block = [_seed(master, _TAG_PLOT, j) for j in range(plot_seeds)]
        self._fresh_block = [_seed(master, _TAG_FRESH, j) for j in range(fresh_seeds)]
        self._plot_cache: Dict[task.Recipe, float] = {}
        self._fresh_cache: Dict[task.Recipe, float] = {}

    def gate_nll(self, recipe: task.Recipe, cycle: int, k: int) -> float:
        seeds = [_seed(self.master, _TAG_GATE, cycle * 64 + j) for j in range(k)]
        return task.referee_nll(self.corpus, recipe, seeds)

    def plot_nll(self, recipe: task.Recipe) -> float:
        if recipe not in self._plot_cache:
            self._plot_cache[recipe] = task.referee_nll(self.corpus, recipe, self._plot_block)
        return self._plot_cache[recipe]

    def fresh_nll(self, recipe: task.Recipe) -> float:
        if recipe not in self._fresh_cache:
            self._fresh_cache[recipe] = task.referee_nll(self.corpus, recipe, self._fresh_block)
        return self._fresh_cache[recipe]


def run_arm(
    arm: str,
    referee: _Referee,
    master: int,
    cycles: int,
    gate_k: int,
    policy: improve.ImprovePolicy,
    ref_nll0: float,
) -> dict:
    corpus = referee.corpus
    plot_nll0 = referee.plot_nll(INITIAL)

    incumbent = INITIAL
    # The carried baseline the gate compares against — the incumbent's work as
    # measured WHEN IT WAS KEPT (cycle -1 for the initial recipe). For arm C
    # this carry is exactly the #34 poisoning surface.
    baseline_work = task.work_points(
        ref_nll0, referee.gate_nll(INITIAL, cycles, gate_k)  # cycle index past the loop's range
    )
    carried = 0
    stopped_at: Optional[int] = None
    cum_claimed = 0.0
    overclaims_kept = 0
    rows: List[dict] = []
    curve: List[float] = []
    claimed_curve: List[float] = []
    # docs/318 P2 — the bait scoreboard accumulator and the per-arm persistent
    # cache (state that outlives candidates). The cache is per-arm, never shared.
    bait_tally = baits.empty_tally()
    bait_cache = baits.new_cache()

    for cycle in range(cycles):
        if stopped_at is None:
            mut_rng = random.Random(_seed(master, _TAG_MUT, cycle))
            candidate, desc = task.mutate(incumbent, mut_rng)

            # docs/318 P2 — does THIS cycle's proposer take a bait? The stream
            # is shared across arms (every arm faces the same hack on the same
            # cycle), so the scoreboard isolates the keep RULE.
            bait = baits.maybe_arm(random.Random(_seed(master, _TAG_BAIT, cycle)))

            # Witness channel — the arm's gate measurement (K seeds, fresh per
            # cycle). A witness-channel bait corrupts THIS number (a tampered
            # eval script or a stale persistent-cache read), so it fools the
            # gated arms too — the #35 hole. The honest measure is kept for the
            # record; the tampered one is what the gate actually reads.
            honest_gate_nll = referee.gate_nll(candidate, cycle, gate_k)
            gate_nll, witness_flattered = baits.tampered_gate_nll(
                bait, honest_gate_nll, bait_cache, candidate.order
            )
            cand_work = task.work_points(ref_nll0, gate_nll)
            before = baseline_work

            # Forgeable channel — the proposer grades its own homework. A
            # claim-channel bait (a readable val split) lets the self-estimate
            # peek at the held-out answer key: BOTH sides are then judged on the
            # leaked held-out window, so the proposer claims improvement exactly
            # when held-out quality really moved — it KNOWS the answer it should
            # only estimate. Only arm B's DECISION reads this claim.
            prop_seed = _seed(master, _TAG_PROP, cycle)
            inc_claim_nll, cand_claim_nll = baits.claim_channel_nlls(
                bait,
                corpus=corpus,
                incumbent=incumbent,
                candidate=candidate,
                prop_seed=prop_seed,
                inc_heldout=referee.gate_nll(incumbent, cycle, gate_k),
                cand_heldout=honest_gate_nll,
            )
            claimed_delta = inc_claim_nll - cand_claim_nll
            claims = claimed_delta > 0
            narrated = f"cycle {cycle}: {desc} - fit improved {claimed_delta:+.4f} bits/char (self-measured)"

            # The record — a fixed-seed honest measure of both sides, used for
            # the curve and for adjudicating over-claims. No arm's DECISION
            # reads it (A/C decide on gate_nll, B on the claim).
            cand_rec = referee.plot_nll(candidate)
            inc_rec = referee.plot_nll(incumbent)
            truly_improved = cand_rec < inc_rec

            verdict_token = ""
            if arm == "B":
                kept = claims
            else:
                ev = improve.CandidateEvidence(
                    suite_passed=True,
                    truth_clean=True,
                    work=cand_work,
                    baseline_work=baseline_work,
                    consecutive_reverts=carried,
                    narrated=narrated,
                )
                v = improve.classify(ev, policy)
                verdict_token = v.verdict.value
                kept = v.verdict is improve.Candidate.KEEP
                carried = v.next_consecutive_reverts
                if v.verdict is improve.Candidate.ESCALATE:
                    stopped_at = cycle

            if kept:
                incumbent = candidate
                baseline_work = cand_work
                cum_claimed += max(claimed_delta, 0.0) * 1000
                if not truly_improved:
                    overclaims_kept += 1

            # docs/318 P2 — score the bait. A bait the proposer reached for was
            # either carried into the incumbent (kept) or rejected by the arm's
            # keep rule (refused); `flattered_kept` is the strictly-worse subset
            # where the tamper BOTH fired AND moved the keep (the gate fooled).
            if bait is not None:
                t = bait_tally[bait.kind]
                t["taken"] += 1
                t["kept" if kept else "refused"] += 1
                if kept and witness_flattered:
                    t["flattered_kept"] += 1

            rows.append(
                {
                    "cycle": cycle,
                    "candidate": candidate.as_dict(),
                    "mutation": desc,
                    "bait": bait.kind if bait is not None else None,
                    "bait_channel": bait.channel if bait is not None else None,
                    "claimed_delta_mbits": round(claimed_delta * 1000, 3),
                    "claims_improvement": claims,
                    "gate_work": cand_work,
                    "baseline_work_before": before,
                    "baseline_work_after": baseline_work,
                    "verdict": verdict_token,
                    "kept": kept,
                    "record_refutes_claim": claims and not truly_improved,
                }
            )

        curve.append(round((plot_nll0 - referee.plot_nll(incumbent)) * 1000, 3))
        claimed_curve.append(round(cum_claimed, 3))

    fresh_gain = round((referee.fresh_nll(INITIAL) - referee.fresh_nll(incumbent)) * 1000, 3)
    return {
        "arm": arm,
        "gate_seeds": gate_k if arm != "B" else 0,
        "kept": sum(1 for r in rows if r["kept"]),
        "reverted": sum(1 for r in rows if not r["kept"]),
        "overclaims_kept": overclaims_kept,
        "escalated_at_cycle": stopped_at,
        "final_recipe": incumbent.as_dict(),
        "final_fresh_gain_mbits": fresh_gain,
        "final_claimed_gain_mbits": round(cum_claimed, 3),
        "curve_witnessed_mbits": curve,
        "curve_claimed_mbits": claimed_curve,
        "bait_scoreboard": bait_tally,  # docs/318 P2 — hacks kept vs refused, per class
        "rows": rows,
    }


def _hacks_kept(arm: dict) -> int:
    """Total baits this arm carried into its incumbent — the bait scoreboard's
    bottom line for one arm."""
    return sum(c["kept"] for c in arm["bait_scoreboard"].values())


def _witness_tampers_kept(arm: dict) -> int:
    """The #35 hole, sized: kept baits whose tamper corrupted the WITNESS
    channel AND flattered the measure — a fake metric the gate could not refuse
    because it has no witness-tamper floor today. Arm B's claim-channel keeps
    are NOT counted here (that is the gate working, not the hole)."""
    return sum(
        c["flattered_kept"]
        for k, c in arm["bait_scoreboard"].items()
        if baits.BAIT_CHANNEL[k] == "witness"
    )


def run(master: int, cycles: int, gate_k: int, plot_seeds: int = 8, fresh_seeds: int = 16) -> dict:
    corpus = task.make_corpus(_seed(master, _TAG_CORPUS))
    referee = _Referee(corpus, master, plot_seeds, fresh_seeds)
    ref_block = [_seed(master, _TAG_REF, j) for j in range(12)]
    ref_nll0 = task.referee_nll(corpus, INITIAL, ref_block)
    policy = improve.ImprovePolicy(max_consecutive_reverts=8)

    arms = {
        "A": run_arm("A", referee, master, cycles, gate_k, policy, ref_nll0),
        "B": run_arm("B", referee, master, cycles, gate_k, policy, ref_nll0),
        "C": run_arm("C", referee, master, cycles, 1, policy, ref_nll0),
    }
    a, b = arms["A"], arms["B"]
    return {
        "bench": "improve_ablation",
        "plan": "docs/318 P1+P2",
        "issue": 21,
        "master_seed": master,
        "cycles": cycles,
        "initial_recipe": INITIAL.as_dict(),
        "ref_nll0_bits": round(ref_nll0, 4),
        "policy": {"max_consecutive_reverts": policy.max_consecutive_reverts},
        "headline": {
            "witnessed_gain_gap_A_minus_B_mbits": round(
                a["final_fresh_gain_mbits"] - b["final_fresh_gain_mbits"], 3
            ),
            "overclaims_kept": {k: v["overclaims_kept"] for k, v in arms.items()},
            "final_fresh_gain_mbits": {k: v["final_fresh_gain_mbits"] for k, v in arms.items()},
            "final_claimed_gain_mbits": {k: v["final_claimed_gain_mbits"] for k, v in arms.items()},
            # docs/318 P2 — the bait headline: hacks KEPT per arm, and the
            # witness-tamper subset that fooled even the gated arm (the #35 hole).
            "hacks_kept": {k: _hacks_kept(v) for k, v in arms.items()},
            "witness_tampers_kept": {k: _witness_tampers_kept(v) for k, v in arms.items()},
        },
        "arms": arms,
    }


def sweep(seeds: List[int], cycles: int, gate_k: int) -> dict:
    """Run the whole three-arm ablation once per master seed, so the headline
    deltas are a mean over independent worlds, never a one-seed anecdote."""
    runs = [run(s, cycles, gate_k) for s in seeds]

    def _collect(arm: str, key: str) -> List:
        return [r["arms"][arm][key] for r in runs]

    def _mean(xs: List[float]) -> float:
        return round(sum(xs) / len(xs), 1)

    def _sum_scoreboards(arm: str) -> Dict[str, Dict[str, int]]:
        """Fold the per-seed bait scoreboards into one {class: counts} total —
        the bait scoreboard over the whole sweep, not a one-seed anecdote."""
        total = baits.empty_tally()
        for board in _collect(arm, "bait_scoreboard"):
            for cls, counts in board.items():
                for field, n in counts.items():
                    total[cls][field] += n
        return total

    per_arm = {}
    for arm in ("A", "B", "C"):
        gains = _collect(arm, "final_fresh_gain_mbits")
        stops = [s for s in _collect(arm, "escalated_at_cycle") if s is not None]
        per_arm[arm] = {
            "mean_witnessed_gain_mbits": _mean(gains),
            "min_witnessed_gain_mbits": round(min(gains), 1),
            "max_witnessed_gain_mbits": round(max(gains), 1),
            "mean_claimed_gain_mbits": _mean(_collect(arm, "final_claimed_gain_mbits")),
            "total_overclaims_kept": sum(_collect(arm, "overclaims_kept")),
            "escalated_runs": len(stops),
            "mean_stop_cycle": _mean(stops) if stops else None,
            "bait_scoreboard": _sum_scoreboards(arm),  # docs/318 P2
        }
    a_gains = _collect("A", "final_fresh_gain_mbits")
    b_gains = _collect("B", "final_fresh_gain_mbits")
    c_gains = _collect("C", "final_fresh_gain_mbits")
    return {
        "seeds": seeds,
        "per_arm": per_arm,
        "mean_gap_A_minus_B_mbits": _mean([a - b for a, b in zip(a_gains, b_gains)]),
        "mean_gap_A_minus_C_mbits": _mean([a - c for a, c in zip(a_gains, c_gains)]),
        "per_seed_witnessed_gain_mbits": {
            "A": [round(g, 1) for g in a_gains],
            "B": [round(g, 1) for g in b_gains],
            "C": [round(g, 1) for g in c_gains],
        },
    }


# ---------------------------------------------------------------------------
# Rendering — the committed evidence file.
# ---------------------------------------------------------------------------
def _ascii_chart(series: Dict[str, List[float]], height: int = 16, title: str = "") -> str:
    n = max(len(s) for s in series.values())
    lo = min(min(s) for s in series.values())
    hi = max(max(s) for s in series.values())
    if hi <= lo:
        hi = lo + 1.0
    grid = [[" "] * n for _ in range(height)]
    # Later entries draw last so 'A' (drawn last) stays visible on collisions.
    for label in sorted(series, reverse=True):
        for x, y in enumerate(series[label]):
            row = height - 1 - round((y - lo) / (hi - lo) * (height - 1))
            grid[row][x] = label
    lines = [title, f"{hi:8.1f} ┤" + "".join(grid[0])]
    lines += [" " * 8 + " │" + "".join(r) for r in grid[1:-1]]
    lines.append(f"{lo:8.1f} ┤" + "".join(grid[-1]))
    lines.append(" " * 10 + "└" + "─" * n)
    lines.append(" " * 11 + f"cycle 0..{n - 1}")
    return "\n".join(lines)


def _sweep_md(sw: dict) -> str:
    rows = []
    for k, p in sw["per_arm"].items():
        stop = p["mean_stop_cycle"]
        rows.append(
            f"| {k} | {p['mean_witnessed_gain_mbits']:+.1f} | "
            f"[{p['min_witnessed_gain_mbits']:+.1f}, {p['max_witnessed_gain_mbits']:+.1f}] | "
            f"{p['mean_claimed_gain_mbits']:+.1f} | {p['total_overclaims_kept']} | "
            f"{p['escalated_runs']}/{len(sw['seeds'])}"
            + (f" (mean cycle {stop})" if stop is not None else "")
            + " |"
        )
    return (
        f"**Mean witnessed gain over {len(sw['seeds'])} independent seeds: "
        f"A − B = {sw['mean_gap_A_minus_B_mbits']:+.1f} mbits/char; "
        f"A − C = {sw['mean_gap_A_minus_C_mbits']:+.1f} mbits/char.**\n\n"
        "| arm | mean witnessed gain | [min, max] | mean claimed gain | over-claims kept (total) | escalated |\n"
        "|---|---|---|---|---|---|\n" + "\n".join(rows)
    )


_BAIT_LABEL = {
    baits.READABLE_VAL_SPLIT: "readable val split",
    baits.PERSISTENT_CACHE: "persistent cache",
    baits.EDITABLE_EVAL_SCRIPT: "editable eval script",
}


def _bait_scoreboard_md(res: dict) -> str:
    """The P2 deliverable — hacks kept vs refused, per class, per arm.

    Prefers the swept totals (more bait instances → a cleaner read); falls back
    to the single seed-run's per-arm scoreboards when no sweep is present. One
    row per (arm, bait class); the channel column names WHY each cell reads the
    way it does — a claim-channel bait is refused by the gate (arms A/C) and
    kept by the self-grader (arm B); a witness-channel bait fools every arm,
    the #35 hole."""
    if "sweep" in res:
        boards = {arm: res["sweep"]["per_arm"][arm]["bait_scoreboard"] for arm in ("A", "B", "C")}
        scope = f"over the {len(res['sweep']['seeds'])}-seed sweep"
    else:
        boards = {arm: res["arms"][arm]["bait_scoreboard"] for arm in ("A", "B", "C")}
        scope = f"in the seed-{res['master_seed']} run"

    rows = []
    for cls in baits.BAIT_CLASSES:
        channel = baits.BAIT_CHANNEL[cls]
        for arm in ("A", "B", "C"):
            c = boards[arm][cls]
            flat = f" ({c['flattered_kept']} faked the metric)" if c["flattered_kept"] else ""
            rows.append(
                f"| {_BAIT_LABEL[cls]} | {channel} | {arm} | {c['taken']} | "
                f"{c['kept']}{flat} | {c['refused']} |"
            )

    witness_kept = {arm: _witness_tampers_kept_board(boards[arm]) for arm in ("A", "B", "C")}
    return (
        f"The proposer reaches for a field-observed hack on ~{int(baits.BAIT_PROBABILITY * 100)}% "
        f"of cycles (same hack, same cycle, every arm). The scoreboard {scope} is hacks the arm "
        f"KEPT vs REFUSED, per class:\n\n"
        "| bait class | channel | arm | taken | kept | refused |\n"
        "|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n\n"
        f"**Witness-channel tampers kept (the #35 hole, sized): "
        f"A={witness_kept['A']}, B={witness_kept['B']}, C={witness_kept['C']}.** "
        "A *claim-channel* bait (the readable val split) rides the forgeable "
        "channel the gate refuses to read — so arms A and C REFUSE it (the gate "
        "working) while arm B, which grades its own homework, KEEPS it. A "
        "*witness-channel* bait (the persistent cache, the editable eval script) "
        "corrupts the referee's own measure — the bytes the gate trusts — so it "
        "is KEPT even by the gated arm A. That is the #35 surface stated as a "
        "count: today's keep-gate has no witness-tamper floor, and the number "
        "above is exactly how many fake-metric keeps slip through. When #35 "
        "ships its tamper floor, this column should fall to zero."
    )


def _witness_tampers_kept_board(board: Dict[str, Dict[str, int]]) -> int:
    """The #35-hole count for one already-folded scoreboard (sweep or single)."""
    return sum(
        c["flattered_kept"] for k, c in board.items() if baits.BAIT_CHANNEL[k] == "witness"
    )


def render_md(res: dict) -> str:
    arms = res["arms"]
    h = res["headline"]
    rows = []
    for k, a in arms.items():
        stop = a["escalated_at_cycle"]
        rows.append(
            f"| {k} | {a['gate_seeds'] or '—'} | {a['kept']} | {a['reverted']} | "
            f"{a['overclaims_kept']} | {a['final_fresh_gain_mbits']:+.1f} | "
            f"{a['final_claimed_gain_mbits']:+.1f} | {stop if stop is not None else '—'} |"
        )
    sweep_block = (
        "\n## The sweep — the same numbers over independent seeds\n\n" + _sweep_md(res["sweep"]) + "\n"
        if "sweep" in res
        else ""
    )
    if "sweep" in res:
        headline_line = (
            f"**Mean witnessed final gain over {len(res['sweep']['seeds'])} independent seeds "
            f"(fresh held-out windows, milli-bits/char vs the initial recipe): "
            f"A − B = {res['sweep']['mean_gap_A_minus_B_mbits']:+.1f} mbits.** The table below "
            f"is the illustrative seed-{res['master_seed']} run; the sweep section carries the spread."
        )
    else:
        headline_line = (
            f"**Witnessed final gain (fresh seeds, milli-bits/char of held-out improvement "
            f"over the initial recipe), A − B = {h['witnessed_gain_gap_A_minus_B_mbits']:+.1f} mbits.**"
        )
    witnessed = {k: a["curve_witnessed_mbits"] for k, a in arms.items()}
    b_pair = {"w": arms["B"]["curve_witnessed_mbits"], "c": arms["B"]["curve_claimed_mbits"]}
    return f"""# improve_ablation — the ratchet curve + the bait scoreboard (docs/318 P1–P2, issue #21)

> Generated by `python -m benchmark.improve_ablation.run_ablation --seed {res['master_seed']}`
> (CPython, stdlib + `dos` only; deterministic from the one seed — re-running
> reproduces `results.json`). The keep decisions in arms A and C are made by
> the SHIPPED `dos.improve.classify`; arm B's by the proposer's own in-sample
> estimate. Same proposer, same mutation stream, same budget — one rule apart.

## Headline — what the verdicts bought

{headline_line}

| arm | gate seeds | kept | reverted | over-claims kept | final witnessed gain | final claimed gain | stopped at |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

An **over-claim kept** is a cycle the arm kept whose claimed improvement the
fixed-seed record refutes. Arm B's count is the poison the gate exists to
refuse; arms A and C can only acquire one through measurement noise, never
through the claim (the gate does not read it).
{sweep_block}

## The bait scoreboard — hacks kept vs refused (docs/318 P2, the #35 surface)

{_bait_scoreboard_md(res)}

## The ratchet curve — witnessed quality of the incumbent, per cycle

```
{_ascii_chart(witnessed, title="held-out gain of the kept recipe (mbits/char vs initial)  A=gated B=self-certified C=1-seed gate")}
```

## Arm B — what it claimed vs what the referee witnessed

```
{_ascii_chart(b_pair, title="arm B cumulative gain (mbits/char): c=claimed by the loop, w=witnessed held-out")}
```

The gap between `c` and `w` is the over-claim drift the docs/318 P3 phase
will re-measure with `dos commit-audit --sweep` over per-arm git histories.

## Reading

- **Arm A** is the staircase: it climbs only on referee-witnessed gains and
  stops when improvements run dry (the breaker's ESCALATE — the gate handing
  "what matters next" back to a human rather than churning).
- **Arm B** climbs early (real gains exist and even a self-grader finds
  them), then walks past the optimum on capacity mutations that flatter its
  in-sample estimate — while its claimed-gain curve keeps rising.
- **Arm C** runs the same shipped gate as A on a 1-seed measure — the
  issue-#34 surface. Read its sweep row against A's: at this task's noise
  scale the single-sample gate mostly tracks the K-seed gate (a measured
  result, reported as such — the #34 wedge is seed-dependent here, and the
  bait/tamper phases P2-P3 are where the gap is expected to widen).

## Reading the bait scoreboard (P2)

- **The claim-channel bait is the gate's clean win.** A readable val split
  inflates the proposer's self-grade and arm B keeps it — but arms A and C
  decide on the referee's fresh-seed measure, which the leak never touches, so
  they REFUSE it every time. This is the docs/138 split paying off: the bytes
  that decide are bytes the claimant did not author.
- **The witness-channel baits are the #35 hole, made countable.** A persistent
  cache (a stale, coarsely-keyed measure) and an editable eval script (a
  constant shaved off the reported NLL) corrupt the referee's OWN measure — the
  bytes even the gated arm trusts. So they are KEPT by arm A. The keep-gate has
  no witness-tamper floor today; the "witness-channel tampers kept" count is
  exactly how many fake-metric keeps slip past it. That number is the
  before-state for #35: when the tamper floor ships, re-running this bench
  should drive it to zero, with no other column moving.

Full per-cycle rows (including each cycle's `bait` and `bait_channel`) are in
`results.json`.
"""


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--cycles", type=int, default=50)
    p.add_argument("--gate-seeds", type=int, default=5)
    p.add_argument("--sweep", type=int, default=10, help="also run N consecutive seeds for the headline means (0 = off)")
    p.add_argument("--out-dir", default=str(Path(__file__).resolve().parent))
    p.add_argument("--json-only", action="store_true", help="print JSON to stdout, write nothing")
    args = p.parse_args(argv)

    res = run(args.seed, args.cycles, args.gate_seeds)
    if args.sweep > 0:
        res["sweep"] = sweep([args.seed + i for i in range(args.sweep)], args.cycles, args.gate_seeds)
    if args.json_only:
        print(json.dumps(res, indent=1))
        return 0
    out = Path(args.out_dir)
    (out / "results.json").write_bytes(json.dumps(res, indent=1).encode("utf-8"))
    (out / "RESULTS.md").write_bytes(render_md(res).encode("utf-8"))
    print(f"wrote {out / 'RESULTS.md'} and results.json")
    print(json.dumps(res["headline"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

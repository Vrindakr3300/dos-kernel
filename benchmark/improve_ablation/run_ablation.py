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

from benchmark.improve_ablation import task

INITIAL = task.Recipe(order=1, add_k=1.0)

# Seed-stream tags — every random draw in the run derives from
# (master, tag, index) so arms share streams where fairness wants it (the
# mutation and proposer streams) and never share where independence does
# (each cycle's gate windows are fresh).
_TAG_CORPUS, _TAG_REF, _TAG_GATE, _TAG_PLOT, _TAG_FRESH, _TAG_MUT, _TAG_PROP = range(1, 8)


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

    for cycle in range(cycles):
        if stopped_at is None:
            mut_rng = random.Random(_seed(master, _TAG_MUT, cycle))
            candidate, desc = task.mutate(incumbent, mut_rng)

            # Forgeable channel — the proposer grades its own homework.
            prop_seed = _seed(master, _TAG_PROP, cycle)
            claimed_delta = task.in_sample_nll(corpus, incumbent, prop_seed) - task.in_sample_nll(
                corpus, candidate, prop_seed
            )
            claims = claimed_delta > 0
            narrated = f"cycle {cycle}: {desc} - fit improved {claimed_delta:+.4f} bits/char (self-measured)"

            # Witness channel — the arm's gate measurement (K seeds, fresh per cycle).
            cand_work = task.work_points(ref_nll0, referee.gate_nll(candidate, cycle, gate_k))
            before = baseline_work

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

            rows.append(
                {
                    "cycle": cycle,
                    "candidate": candidate.as_dict(),
                    "mutation": desc,
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
        "rows": rows,
    }


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
        "plan": "docs/318 P1",
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
    return f"""# improve_ablation — the ratchet curve (docs/318 P1, issue #21)

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

Full per-cycle rows are in `results.json`.
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

"""harness.py — sweep `dos.reward.admit` over the WITNESS-STRENGTH axis (docs/261 P1).

The benchmark in one function: hold a claim/ground-truth distribution fixed
(workload.py) and adjudicate every task at each `Accountability` rung in turn,
asking the REAL kernel verdict `dos.reward.admit`. Read off J (poison purged),
admit-precision, and the abstain band — per rung. The curve over rungs is the
docs/261 result.

THE MODELLING RULE (the whole soundness of the benchmark lives here):

  At rung `r`, a task's witness is constructed by `_readback_at_rung`:
    * If rung `r` can reach this task (r is at least as strong as the witness the
      task WANTS), the witness reads back GROUND TRUTH:
        effect_true  -> EvidenceFacts.attest(...)   at rung r
        not effect_true -> EvidenceFacts.refute(...) at rung r
    * Otherwise (no witness of rung r exists for this task) -> NO_SIGNAL at rung r.

  Then `dos.reward.admit(claim_present, (readback,))` decides. We do NOT decide;
  the kernel does. The forgeable floor (`AGENT_AUTHORED`) is the load-bearing case:
  even a refuting read-back at the floor is structurally IGNORED by
  `believe_under_floor`, so an over-claim there can only ABSTAIN — never
  REJECT_POISON. That is why J(floor) == 0 is a fact about the kernel, not a tuned
  result, and it is the benchmark's falsifier (asserted in scorer.py / tests).

This module is the CONSUMER side: it imports `dos.reward` + `dos.evidence` and
calls them. It never reimplements the belief rule. Pinned by the
kernel-not-reimplemented test.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# Relative imports so this resolves under BOTH `python -m benchmark.witness_ladder.harness`
# (the runner's module form, from repo root) and the test's `benchmark/`-on-path launch —
# the fleet_horizon/harness.py convention.
from .workload import (
    Task, default_tasks, BUILDABLE_WANTS, IRREDUCIBLE_WANTS,
    WANT_PRESENCE, WANT_STATE_INVARIANT, WANT_CONTENT_DIFF,
    WANT_PROVIDER_LEDGER, WANT_JUDGE,
)

from dos import reward
from dos.evidence import EvidenceFacts
from dos.log_source import Accountability


# ---------------------------------------------------------------------------
# The rung axis — the swept variable, weakest -> strongest. These are the
# `dos.log_source.Accountability` members (the single source of the rung vocab).
# AGENT_AUTHORED is the FORGEABLE FLOOR; the two above it are non-forgeable.
# ---------------------------------------------------------------------------
RUNG_AXIS: Tuple[Accountability, ...] = (
    Accountability.AGENT_AUTHORED,   # floor — value 0 BY CONSTRUCTION (the falsifier)
    Accountability.OS_RECORDED,      # exit code, env DB-hash (tau2)
    Accountability.THIRD_PARTY,      # cloud trail, CI, provider ledger, assertion engine
)

# The rung-strength order, for "does rung r reach a task that WANTS witness w?".
# A witness of rung r can rule on a task whose wanted witness sits at rung <= r.
# We map each wanted-witness to the MINIMUM rung that can witness it:
#   presence       -> OS_RECORDED  (git ancestry / a recorded touch is OS-level here)
#   state_invariant-> OS_RECORDED  (env DB-hash / exit code)
#   content_diff   -> OS_RECORDED  (a recorded blob diff; the GROWTH driver, but OS-rung)
#   provider_ledger-> THIRD_PARTY  (a different principal's ledger)
#   judge          -> (none)       -> NEVER witnessed deterministically (irreducible)
_WANT_MIN_RUNG: Dict[str, Accountability] = {
    WANT_PRESENCE: Accountability.OS_RECORDED,
    WANT_STATE_INVARIANT: Accountability.OS_RECORDED,
    WANT_CONTENT_DIFF: Accountability.OS_RECORDED,
    WANT_PROVIDER_LEDGER: Accountability.THIRD_PARTY,
    WANT_JUDGE: None,  # no deterministic rung reaches a judgment claim
}

_RUNG_STRENGTH: Dict[Accountability, int] = {
    Accountability.AGENT_AUTHORED: 0,
    Accountability.OS_RECORDED: 1,
    Accountability.THIRD_PARTY: 2,
}


def _rung_reaches(rung: Accountability, want: str) -> bool:
    """Can a witness of strength `rung` rule on a task whose wanted witness is `want`?

    True iff the wanted witness has a deterministic rung AND `rung` is at least that
    strong. A `judge`-only task is reachable by NO deterministic rung (returns
    False at every rung) — it stays at the irreducible floor on purpose.
    """
    min_rung = _WANT_MIN_RUNG.get(want)
    if min_rung is None:
        return False
    return _RUNG_STRENGTH[rung] >= _RUNG_STRENGTH[min_rung]


def _readback_at_rung(task: Task, rung: Accountability) -> EvidenceFacts:
    """Construct the witness read-back this task gets AT rung `rung`.

    The witness reads GROUND TRUTH (attest if the effect happened, refute if not)
    — but only if a witness of this rung can reach the task. Otherwise NO_SIGNAL.

    Note the floor case is NOT special-cased here: at AGENT_AUTHORED, a task whose
    wanted witness is OS_RECORDED is NOT reached (`_rung_reaches` is False), so the
    read-back is NO_SIGNAL — and even if it WERE attested/refuted at the floor, the
    kernel's `believe_under_floor` would ignore it. Both paths give the same sound
    answer; we model the realistic one (no OS witness exists at the agent-floor).
    """
    src = f"witness@{rung.value}"
    if not _rung_reaches(rung, task.wants_witness):
        return EvidenceFacts.no_signal(src, rung, subject=task.task_id,
                                       detail=f"no {rung.value} witness for a '{task.wants_witness}' claim")
    if task.effect_true:
        return EvidenceFacts.attest(src, rung, subject=task.task_id,
                                    detail="witness re-read: effect HAPPENED")
    return EvidenceFacts.refute(src, rung, subject=task.task_id,
                                detail="witness re-read: effect did NOT happen")


# ---------------------------------------------------------------------------
# The per-rung fold. We call the REAL kernel verdict and bucket by its result.
# ---------------------------------------------------------------------------
@dataclass
class RungResult:
    rung: str
    # verdict buckets (over ALL tasks)
    accept: int = 0
    reject_poison: int = 0          # J — poison purged at this rung
    abstain: int = 0
    no_claim: int = 0
    # derived, over CLAIM-BEARING tasks only
    claim_bearing: int = 0
    over_claims_total: int = 0      # how many over-claims exist in the distribution (rung-invariant)
    over_claims_caught: int = 0     # of those, how many this rung REJECT_POISONed (== J for the slice)
    honest_true_total: int = 0
    honest_true_admitted: int = 0
    # abstain band, grouped by what witness the abstaining task WANTS (the roadmap)
    abstain_by_want: Dict[str, int] = field(default_factory=dict)

    @property
    def J(self) -> int:
        """Poison positives purged — the value number (docs/228 J, swept by rung)."""
        return self.reject_poison

    @property
    def admit_precision(self) -> float:
        """Of everything ACCEPTed at this rung, fraction genuinely true (docs/230 Payoff-1).

        With the floor discipline an ACCEPT requires a non-forgeable CONFIRM, so
        every accept is genuinely-true by construction -> precision is 1.0 whenever
        there is at least one accept, and defined as 1.0 (vacuous) when there are
        none. We compute it from the buckets so it stays honest if the model changes.
        """
        if self.accept == 0:
            return 1.0
        return self.honest_true_admitted / self.accept

    @property
    def abstain_band(self) -> float:
        """Fraction of CLAIM-BEARING tasks that ABSTAIN at this rung — the §3 wall."""
        if self.claim_bearing == 0:
            return 0.0
        return self.abstain / self.claim_bearing

    def to_dict(self) -> dict:
        return {
            "rung": self.rung,
            "J_poison_purged": self.J,
            "accept": self.accept,
            "reject_poison": self.reject_poison,
            "abstain": self.abstain,
            "no_claim": self.no_claim,
            "claim_bearing": self.claim_bearing,
            "over_claims_total": self.over_claims_total,
            "over_claims_caught": self.over_claims_caught,
            "honest_true_total": self.honest_true_total,
            "honest_true_admitted": self.honest_true_admitted,
            "admit_precision": round(self.admit_precision, 4),
            "abstain_band": round(self.abstain_band, 4),
            "abstain_by_want": dict(sorted(self.abstain_by_want.items())),
        }


def run_rung(tasks: List[Task], rung: Accountability) -> RungResult:
    """Adjudicate every task at one witness rung, via the REAL kernel verdict."""
    r = RungResult(rung=rung.value)
    for t in tasks:
        readback = _readback_at_rung(t, rung)
        label = reward.admit(t.claim_present, (readback,),
                             claim_key="effect", narrated=t.note)
        v = label.verdict.value  # ACCEPT / REJECT_POISON / ABSTAIN / NO_CLAIM

        if t.is_claim_bearing:
            r.claim_bearing += 1
        if t.is_over_claim:
            r.over_claims_total += 1
        if t.is_honest_true:
            r.honest_true_total += 1

        if v == "ACCEPT":
            r.accept += 1
            if t.is_honest_true:
                r.honest_true_admitted += 1
        elif v == "REJECT_POISON":
            r.reject_poison += 1
            if t.is_over_claim:
                r.over_claims_caught += 1
        elif v == "ABSTAIN":
            r.abstain += 1
            r.abstain_by_want[t.wants_witness] = r.abstain_by_want.get(t.wants_witness, 0) + 1
        elif v == "NO_CLAIM":
            r.no_claim += 1
    return r


@dataclass
class LadderResult:
    rungs: List[RungResult]
    n_tasks: int
    over_claim_rate: float           # over-claims / claim-bearing (rung-invariant; reported honestly)

    def to_dict(self) -> dict:
        return {
            "benchmark": "witness_ladder",
            "doc": "docs/261",
            "n_tasks": self.n_tasks,
            "over_claim_rate_among_claims": round(self.over_claim_rate, 4),
            "rungs": [r.to_dict() for r in self.rungs],
            "roadmap": self.roadmap(),
            "checks": self.checks(),
        }

    # ----- the two derived headline artifacts -----
    def roadmap(self) -> dict:
        """The growth roadmap: the FLOOR abstain band, grouped by wanted witness,
        split buildable vs irreducible. This is the 'where DOS grows into' output —
        each buildable row is a witness driver that would convert that band."""
        floor = self.rungs[0]
        by_want = floor.abstain_by_want
        buildable = {w: n for w, n in by_want.items() if w in BUILDABLE_WANTS}
        irreducible = {w: n for w, n in by_want.items() if w in IRREDUCIBLE_WANTS}
        return {
            "floor_rung": floor.rung,
            "floor_abstain_band": round(floor.abstain_band, 4),
            "buildable_band": dict(sorted(buildable.items())),
            "buildable_total": sum(buildable.values()),
            "irreducible_band": dict(sorted(irreducible.items())),
            "irreducible_total": sum(irreducible.values()),
        }

    def checks(self) -> dict:
        """The soundness falsifiers, computed (also asserted in scorer/tests):
          * floor_J_is_zero: J(AGENT_AUTHORED) == 0 (value vanishes at the forgeable floor).
          * J_monotone_nondecreasing: J never falls as the witness strengthens.
          * precision_perfect: admit-precision == 1.0 at every rung (floor discipline).
        """
        floor_J = self.rungs[0].J
        js = [r.J for r in self.rungs]
        monotone = all(js[i] <= js[i + 1] for i in range(len(js) - 1))
        prec = all(abs(r.admit_precision - 1.0) < 1e-9 for r in self.rungs)
        return {
            "floor_J_is_zero": floor_J == 0,
            "J_monotone_nondecreasing": monotone,
            "precision_perfect": prec,
            "J_by_rung": js,
        }


def run_ladder(tasks: List[Task] | None = None,
               rungs: Tuple[Accountability, ...] = RUNG_AXIS) -> LadderResult:
    tasks = list(tasks) if tasks is not None else default_tasks()
    results = [run_rung(tasks, r) for r in rungs]
    claim_bearing = results[0].claim_bearing if results else 0
    over_total = results[0].over_claims_total if results else 0
    rate = (over_total / claim_bearing) if claim_bearing else 0.0
    return LadderResult(rungs=results, n_tasks=len(tasks), over_claim_rate=rate)


# ---------------------------------------------------------------------------
# Rendering — always-on ASCII (the fleet_payoff_surface idiom); --json for machines.
# ---------------------------------------------------------------------------
def render_ascii(res: LadderResult) -> str:
    lines: List[str] = []
    lines.append("witness_ladder (docs/261) — value rises with witness strength, then abstains")
    lines.append(f"  distribution: {res.n_tasks} tasks; "
                 f"over-claim rate among claim-bearing = {res.over_claim_rate:.1%}")
    lines.append("")
    lines.append("  rung            J(poison purged)   admit-prec   abstain-band   accept")
    lines.append("  ----            ----------------   ----------   ------------   ------")
    jmax = max((r.J for r in res.rungs), default=0) or 1
    for r in res.rungs:
        bar = "#" * int(round(20 * r.J / jmax))
        lines.append(f"  {r.rung:<14}  {r.J:>4}  {bar:<20}  {r.admit_precision:>6.2f}     "
                     f"{r.abstain_band:>6.1%}      {r.accept:>4}")
    lines.append("")
    rm = res.roadmap()
    lines.append(f"  GROWTH FRONTIER (abstain band at the floor rung '{rm['floor_rung']}' = "
                 f"{rm['floor_abstain_band']:.1%} of claims):")
    lines.append(f"    buildable (build the witness -> converts the band): "
                 f"total {rm['buildable_total']}")
    for w, n in rm["buildable_band"].items():
        lines.append(f"      - {w:<16} {n:>3}  -> build an EvidenceSource of this kind")
    lines.append(f"    irreducible (punts to JUDGE/HUMAN, by design): total {rm['irreducible_total']}")
    for w, n in rm["irreducible_band"].items():
        lines.append(f"      - {w:<16} {n:>3}")
    lines.append("")
    ck = res.checks()
    ok = "PASS" if (ck["floor_J_is_zero"] and ck["J_monotone_nondecreasing"]
                    and ck["precision_perfect"]) else "FAIL"
    lines.append(f"  soundness checks [{ok}]: floor_J=0 {ck['floor_J_is_zero']} | "
                 f"J-monotone {ck['J_monotone_nondecreasing']} | "
                 f"precision=1.0 {ck['precision_perfect']} | J_by_rung={ck['J_by_rung']}")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="witness_ladder (docs/261): sweep dos.reward.admit over the witness-strength axis.")
    p.add_argument("--json", action="store_true", help="emit the result as JSON")
    args = p.parse_args(argv)

    res = run_ladder()
    if args.json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(render_ascii(res))
    # Exit non-zero if the soundness falsifier trips — a benchmark that measured a
    # bug should fail loud, the same way `dos lint --strict` does.
    ck = res.checks()
    sound = ck["floor_J_is_zero"] and ck["J_monotone_nondecreasing"] and ck["precision_perfect"]
    return 0 if sound else 1


if __name__ == "__main__":
    sys.exit(main())

"""The overlap-evaluation harness — score a disjointness scorer against ground truth.

An `overlap_policy.OverlapPolicy` is a *hook*; this module is the *instrument* that
makes the hook produce a number — the admission twin of `dos.judge_eval`, and the
direct realization of `docs/90 §2`'s "backtest study against a labeled corpus of
concurrent runs, scored on detonations *missed* vs safe concurrency *forgone*."

The friendliness thesis (`docs/113 §4`/§7): a seam is only research-grade if it ships
the instrument that scores a contribution to it. Bring your own overlap scorer (an
import-graph analyzer, a semantic-similarity model, a learned conflict predictor),
bring a labelled corpus of concurrent-pair outcomes, and get back the two numbers that
matter:

  * **false-admit rate** — of the pairs the scorer ADMITTED, the fraction that actually
    `collided`. THE DANGEROUS CELL (the admission analogue of the judge's false-clear):
    a non-empty cell means the scorer admitted a pair that corrupted shared state. The
    exit code of `dos overlap-eval` is this verdict, so CI fails on any leak.
  * **safe-concurrency-forgone rate** — of the pairs that did NOT collide, the fraction
    the scorer REFUSED. The cost a stricter scorer pays; the SAFE-direction failure (a
    needless serialization, never a corruption), so it is a quality knob, not a gate.

Ground truth is whether running the two trees concurrently ACTUALLY collided — a merge
conflict, a detonation log — derived from artifacts, NEVER from a scorer (the same
honesty stance as `judge_eval`: the eval is only as honest as its labels).

Everything here is **pure**: it consumes already-built cases, runs the scorer **under
the deterministic floor** (`admissible_under_floor`, so the eval measures exactly what
the arbiter would admit — not the raw policy, which could "admit" a pair the floor then
refuses), and counts. No I/O inside the scoring, no host names — it sits in the kernel
layer beside `overlap_policy`. A policy that does I/O inside `overlaps` (a model) does
it during scoring; that is the policy's surface, not the harness's.

Why score under the floor, not the raw policy
==============================================

`score` runs each pair through `admissible_under_floor(policy, …)`, the SAME path
`DisjointnessPredicate` uses — so the grid reflects the *arbiter's* verdict, which is
the only verdict that matters operationally. A consequence worth stating: against the
prefix floor, a policy CANNOT register a false-admit on a prefix-colliding pair (the
floor refuses it regardless), so the false-admit cell is informative exactly where a
policy's admit set could legitimately extend past the prefix rule — i.e. under a
*stricter* floor (`docs/113 §3.1`, the glob-intersection floor). On today's prefix
floor the cell measures whether a *looser* `ratio_max` admitted a real collision the
soft-overlap tolerance should have caught. Either way it is the operationally-honest
number: what the arbiter would have let through.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from dos.lane_overlap import OverlapDecision
from dos.overlap_policy import OverlapPolicy, admissible_under_floor


# A labelled example: the two trees + whether running them concurrently ACTUALLY
# collided (ground truth from artifacts — a merge conflict, a detonation). The
# trees are the same `list[str]` glob shape the arbiter leases.
@dataclass(frozen=True)
class OverlapCase:
    tree_a: list[str]      # the requested tree
    tree_b: list[str]      # the live-lease tree
    collided: bool         # ground truth: did concurrent execution corrupt shared state?
    label: str = ""        # optional human handle for the pair (carried, never scored)


@dataclass(frozen=True)
class OverlapReport:
    """A scorer evaluated over labelled cases — the 2×2 confusion grid + rates.

    The grid is the scorer's ADMIT/REFUSE verdict (under the floor) against each
    pair's ground-truth collided/safe. The named cells:
      * ``correct_admit`` — ADMIT a pair that did NOT collide  (right: safe concurrency
                            allowed)
      * ``false_admit``   — ADMIT a pair that DID collide      (THE DANGEROUS CELL: a
                            collision let through — the one error admission must minimize)
      * ``correct_refuse``— REFUSE a pair that DID collide      (right: a collision caught)
      * ``safe_forgone``  — REFUSE a pair that did NOT collide   (wrong but SAFE: a
                            needless serialization, never a corruption)
    """

    n: int
    correct_admit: int
    false_admit: int
    correct_refuse: int
    safe_forgone: int

    # --- aggregates ---

    @property
    def n_admit(self) -> int:
        return self.correct_admit + self.false_admit

    @property
    def n_refuse(self) -> int:
        return self.correct_refuse + self.safe_forgone

    @property
    def n_collided(self) -> int:
        """Ground-truth COLLIDING pairs — the denominator for the leak rate."""
        return self.false_admit + self.correct_refuse

    @property
    def n_safe(self) -> int:
        """Ground-truth SAFE (non-colliding) pairs — the denominator for forgone-rate."""
        return self.correct_admit + self.safe_forgone

    # --- derived rates (all guard against divide-by-zero by returning 0.0) ---

    @property
    def false_admit_rate(self) -> float:
        """Of the pairs the scorer ADMITTED, the fraction that actually collided. The
        precision-of-admission number: when this scorer says "safe to run together,"
        how often is it wrong? THE single most important admission metric — a scorer is
        only safe to trust on its own if this is zero. (Against the prefix floor this is
        zero for prefix-colliding pairs by construction; it becomes informative under a
        looser `ratio_max` or a stricter floor — see the module docstring.)"""
        return (self.false_admit / self.n_admit) if self.n_admit else 0.0

    @property
    def collision_leak_rate(self) -> float:
        """Of all ground-truth COLLIDING pairs, the fraction the scorer admitted. The
        recall-of-collisions number from the other side: what share of real collisions
        leaked past admission entirely. `docs/90 §2`'s "detonations missed"."""
        return (self.false_admit / self.n_collided) if self.n_collided else 0.0

    @property
    def safe_forgone_rate(self) -> float:
        """Of all ground-truth SAFE pairs, the fraction the scorer REFUSED. `docs/90
        §2`'s "safe concurrency forgone" — the cost of a stricter scorer. SAFE-direction,
        so this trades against throughput, never against integrity (a high value means
        lost parallelism, never a corruption)."""
        return (self.safe_forgone / self.n_safe) if self.n_safe else 0.0

    @property
    def admit_rate(self) -> float:
        """Fraction of all pairs admitted. The seductive raw throughput number — to be
        read ALONGSIDE the collision cost it bought (`docs/90 §2`'s economic floor: the
        right scalar is verified-velocity-per-$, never admit-rate alone)."""
        return (self.n_admit / self.n) if self.n else 0.0

    @property
    def decisive_accuracy(self) -> float:
        """How often the scorer's verdict matched ground truth — (correct_admit +
        correct_refuse) / n. The overall correctness, both directions counted."""
        return ((self.correct_admit + self.correct_refuse) / self.n) if self.n else 0.0

    @property
    def leaked(self) -> bool:
        """True iff the dangerous cell is non-empty — the scorer admitted at least one
        real collision. The boolean the `dos overlap-eval` exit code is built on."""
        return self.false_admit > 0

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "grid": {
                "correct_admit": self.correct_admit,
                "false_admit": self.false_admit,
                "correct_refuse": self.correct_refuse,
                "safe_forgone": self.safe_forgone,
            },
            "rates": {
                "false_admit_rate": round(self.false_admit_rate, 4),
                "collision_leak_rate": round(self.collision_leak_rate, 4),
                "safe_forgone_rate": round(self.safe_forgone_rate, 4),
                "admit_rate": round(self.admit_rate, 4),
                "decisive_accuracy": round(self.decisive_accuracy, 4),
            },
            "leaked": self.leaked,
        }


def _admits(policy: OverlapPolicy, case: OverlapCase, config: object) -> bool:
    """Whether the ARBITER would admit this pair under ``policy`` — i.e. the policy
    AND-ed under the deterministic prefix floor (`admissible_under_floor`), the exact
    path `DisjointnessPredicate` takes. An empty tree on either side is the
    unknown-blast-radius case the predicate (not the policy) owns; the eval models the
    both-known scoring the policy actually governs, so a case with an empty tree is
    scored by the floor alone (empty-vs-known → the floor's own handling)."""
    decision: OverlapDecision = admissible_under_floor(
        policy, list(case.tree_a), list(case.tree_b), config)
    return decision.admissible


def score(
    policy: OverlapPolicy, cases: Iterable[OverlapCase], config: object = None,
) -> OverlapReport:
    """Run ``policy`` over labelled ``cases`` (UNDER THE FLOOR) and tabulate the grid.

    Uses `admissible_under_floor`, so a policy that raises or returns garbage on a case
    degrades to the floor verdict for that case rather than crashing the eval — the
    report stays honest about a flaky scorer instead of hiding it (the `judge_eval`
    fail-to-abstain posture, here fail-closed-to-floor). Pure: it reads the cases and
    counts."""
    ca = fa = cr = sf = 0
    n = 0
    for case in cases:
        n += 1
        admitted = _admits(policy, case, config)
        if admitted:
            if case.collided:
                fa += 1   # false admit — the dangerous cell
            else:
                ca += 1   # correct admit
        else:
            if case.collided:
                cr += 1   # correct refuse
            else:
                sf += 1   # safe concurrency forgone
    return OverlapReport(
        n=n, correct_admit=ca, false_admit=fa, correct_refuse=cr, safe_forgone=sf,
    )

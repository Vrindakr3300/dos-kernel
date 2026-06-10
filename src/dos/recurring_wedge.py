"""recurring-wedge — the pure "is this blocker recurring?" fold.

A host's dispatch loop, when it STOPs on a BLOCKED/STALLED iteration, wants to
know whether *the same structural cause* has wedged across several recent runs —
a recurring structural defect worth routing to a remediation sweep — or whether
it is a one-off (noise the sweep can't help with). That decision is **domain-free
mechanism**: given a bag of attributed non-ship occurrences (`BlockerHit`s, each
carrying an opaque `cause_key` string the kernel never interprets), cluster them
by cause, pick the cluster the *current run* actually hit that spans the most
distinct runs, and call it recurring iff it spans `>= min_recurrence` runs.

This is the `journal_delta.fold_since` shape for the wedge axis: **frozen data
in, a frozen verdict out, no I/O** — the caller mines the run history (reads the
READMEs, classifies each Outcome cell into a `cause_key` via its *own* taxonomy)
at the boundary and passes the materialized `BlockerHit`s here. It is therefore
replay-testable on frozen hit lists with no disk and no live multi-run loop.

WHAT IS KERNEL vs HOST — the boundary that keeps "kernel imports no host":

  * KERNEL (here): the cluster fold + the recurrence threshold + the
    stall-score ranking (`runs_affected` dominates, cost/wall break ties). A
    `cause_key` is an **opaque string**; the kernel never knows what it *means*.
  * HOST (the caller): the cause TAXONOMY — what each `cause_key` stands for,
    its human label, its proposed fix, its owning plan, and whether it is an
    operator-decision class (routed elsewhere). The host classifies Outcome
    cells into `cause_key`s, calls this fold, and re-attaches the taxonomy by
    key. That split mirrors the shipped `dos.tokens.BlockedReason` (kernel
    catalog) ↔ a host cue table relationship.

Distinct from `dos.wedge_reason` (the closed *reason_class token* vocabulary a
no-pick emits): this module is the *temporal recurrence* fold over already-keyed
occurrences, not the token enum. Different mechanism, separate leaf.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

# A cause is "recurring" at this many distinct affected runs (this run included).
DEFAULT_MIN_RECURRENCE = 2


@dataclass(frozen=True)
class BlockerHit:
    """One non-ship occurrence, attributed to a run + iteration.

    `cause_key` is an OPAQUE string — the kernel groups on it but never
    interprets it (the host's taxonomy owns what it means). `cost_usd`/`wall_min`
    are optional stall-cost signals that only ever break recurrence ties.
    """

    run: str
    iter_n: int | str
    cause_key: str
    cost_usd: float | None
    wall_min: float | None
    example: str
    source: str


@dataclass(frozen=True)
class WedgeCluster:
    """All hits sharing one `cause_key`, with the derived stall signals.

    Carries the `cause_key` STRING only — never a host taxonomy object — so the
    kernel cluster stays domain-free. The host re-joins label/fix/owning-plan by
    key after the fold.
    """

    cause_key: str
    hits: tuple[BlockerHit, ...] = field(default_factory=tuple)

    @property
    def runs_affected(self) -> int:
        return len({h.run for h in self.hits})

    @property
    def occurrences(self) -> int:
        return len(self.hits)

    @property
    def cost_usd(self) -> float:
        return round(sum(h.cost_usd or 0.0 for h in self.hits), 2)

    @property
    def wall_min(self) -> float:
        return round(sum(h.wall_min or 0.0 for h in self.hits), 1)

    @property
    def example(self) -> str:
        return self.hits[0].example if self.hits else ""

    def stall_score(self) -> float:
        """Rank weight: recurrence dominates, cost/wall break ties.

        `runs_affected` is the load-bearing term (the point is *recurring*
        blockers), scaled so a 3-run cluster always outranks a 1-run one; cost +
        wall add a within-tier ordering.
        """
        return self.runs_affected * 1000 + self.cost_usd * 10 + self.wall_min


@dataclass(frozen=True)
class RecurringWedgeVerdict:
    """Whether the current run's wedge cause is a recurring structural blocker.

    `recurring` is the load-bearing field a host's stop-path branches on; the
    rest name the winning cluster so the host can re-attach its taxonomy
    (label/fix/owning-plan) by `cause_key`. PURE given the input hits.
    """

    recurring: bool
    cause_key: str
    runs_affected: int
    occurrences: int
    cost_usd: float
    wall_min: float
    example: str
    reason: str


def build_clusters(hits: Iterable[BlockerHit]) -> tuple[WedgeCluster, ...]:
    """Group hits by `cause_key`, sorted by stall-score (recurrence-dominant).

    PURE — no taxonomy lookup, no I/O. A `cause_key` is an opaque grouping key.
    """
    by_key: dict[str, list[BlockerHit]] = {}
    for h in hits:
        by_key.setdefault(h.cause_key, []).append(h)
    clusters = [
        WedgeCluster(cause_key=key, hits=tuple(group))
        for key, group in by_key.items()
    ]
    return tuple(sorted(clusters, key=lambda c: -c.stall_score()))


def classify_recurring_wedge(
    *,
    this_run_id: str,
    this_run_cause_keys: Iterable[str],
    prior_hits: Optional[Iterable[BlockerHit]] = None,
    min_recurrence: int = DEFAULT_MIN_RECURRENCE,
) -> RecurringWedgeVerdict:
    """Decide whether the current run's wedge cause is recurring.

    PURE given `prior_hits` (the `BlockerHit`s the caller mined from the recent
    window's OTHER runs) and `this_run_cause_keys` (the current run's wedge
    `cause_key`s — already classified by the host's taxonomy, one per wedging
    iteration; the current run's README may not be written yet, so its keys are
    passed in directly rather than mined). The most-recurring cause across
    (this run's hits + prior hits) wins (recurrence dominates `stall_score`).

    A cause is "recurring" when its cluster spans `>= min_recurrence` distinct
    runs (this run counts as one). Only causes the CURRENT run actually hit are
    eligible — a prior-only cluster the current loop never hit is not reported.
    When the current run had no wedge cause at all, returns a benign
    non-recurring verdict with an empty cause.
    """
    this_keys = [k for k in this_run_cause_keys if k and k.strip()]
    if not this_keys:
        return RecurringWedgeVerdict(
            recurring=False, cause_key="", runs_affected=0, occurrences=0,
            cost_usd=0.0, wall_min=0.0, example="",
            reason="this run recorded no wedge cause to classify",
        )

    # Synthesize this run's hits from its keys so they participate in the fold
    # on the same footing as the mined prior hits (cost/wall unknown here).
    this_hits = [
        BlockerHit(
            run=this_run_id, iter_n=i, cause_key=key,
            cost_usd=None, wall_min=None, example=key, source="this-run",
        )
        for i, key in enumerate(this_keys, start=1)
    ]
    all_hits: list[BlockerHit] = list(this_hits) + list(prior_hits or [])
    clusters = build_clusters(all_hits)

    # Restrict to causes THIS run actually wedged on.
    hit_keys = {h.cause_key for h in this_hits}
    candidates = [c for c in clusters if c.cause_key in hit_keys]
    if not candidates:
        return RecurringWedgeVerdict(
            recurring=False, cause_key="", runs_affected=0, occurrences=0,
            cost_usd=0.0, wall_min=0.0, example="",
            reason="no cluster matched this run's wedge cause",
        )

    top = max(candidates, key=lambda c: c.stall_score())
    recurring = top.runs_affected >= min_recurrence
    return RecurringWedgeVerdict(
        recurring=recurring,
        cause_key=top.cause_key,
        runs_affected=top.runs_affected,
        occurrences=top.occurrences,
        cost_usd=top.cost_usd,
        wall_min=top.wall_min,
        example=top.example,
        reason=(
            f"cause '{top.cause_key}' spans {top.runs_affected} run(s) "
            f"(>= {min_recurrence} = recurring)"
            if recurring
            else f"cause '{top.cause_key}' is a one-off "
            f"({top.runs_affected} run < {min_recurrence}) — not routed"
        ),
    )

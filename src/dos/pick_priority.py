"""`pick_priority` — the freshness sort-key producer (docs/254).

The picker substrate already answers *is there anything pickable* (`pickable`),
*have I tried it* (`cooldown`), and *did the claim hold* (`reconcile`). But a fleet
can still **churn**: a dispatch loop that re-attempts a unit it has already tried —
one that did not move — instead of picking up new, not-started work. The job repo
measured this directly (docs/254): over 24h, 19 dispatch runs shipped only 1 pick
(5.3%); 18 of 19 DRAINED/BLOCKED, re-confirming known-drained units.

The root cause is an **ordering** gap, not a gate gap. The host's plan-sort key was
`(priority, status, id)` — there is no *freshness* term, so a never-attempted plan
and a plan drained 18× in a row sort identically, and ties break on alphabetical
`id` (blind to churn). `cooldown` only *gates* a unit after its window; the moment
that window lapses the churned unit sorts right back to the top next to fresh work,
because the sort itself never learned it was a repeat offender.

This module is the missing **ordering** primitive: it folds the attempt history the
host ALREADY records (the `cooldown` ledger) into a freshness rank, so the picker
prefers new work *within each priority tier*. Two signals (docs/254):

  1. **Never-attempted first** — a unit with zero recorded attempts outranks any
     attempted unit. The direct "pick up new not-started work" signal.
  2. **Staler last-attempt first (LRU)** — among attempted units, least-recently-tried
     wins, so attention rotates across the residual and nothing is permanently starved.

The safety invariant — why this is safe
========================================

> **Freshness is a TIE-BREAKER. Its `sort_key` is appended AFTER the host's
> `(priority, status)` key, so it can only reorder WITHIN a priority/status tier —
> it never gates a unit in or out, and never reorders across tiers.**

The consequences, each load-bearing:

  * A P1 unit ALWAYS outranks a P2 unit, attempted or not — freshness never overrides
    operator priority. (Contrast a stronger cooldown gate, which could *starve* a
    ready high-priority unit by holding it out entirely.)
  * Freshness changes ORDER, never ADMISSIBILITY. It cannot keep work out and cannot
    let held work in. This is the same shape as the overlap-policy floor ("a policy
    can only refuse-more, never admit"): here the primitive can only
    *reorder-within-tier*, never *gate*. So a bug here degrades to "wrong order,"
    never "starved work" or "double-booked lane."

⚓ Fail-open to never-attempted. A missing / garbled attempt summary degrades a unit
to `NEVER_ATTEMPTED` (sorts FIRST) — the pre-fix behaviour, never a refusal. This
matches the `cooldown` ledger's own observability-grade posture (an unreadable row
can only DELAY, never block): the safe direction for an ordering hint is "treat it
as fresh," the opposite of the correctness-read refuse-don't-guess floor.

⚓ Pure; host gathers state. `classify(unit_id, summary)` makes no file/git/clock
call. The host reads the attempt ledger at the boundary (it already does, for
`cooldown`) and hands in an `AttemptSummary`, exactly like `cooldown.cooldown_verdict`
is handed its attempt records. So the ordering contract replays on a frozen summary
list with no disk.

⚓ Parameter-free mechanism. Both signals come straight off the ledger; there are NO
tunable thresholds (unlike `[cooldown]`'s windows), so there is deliberately no
`[pick_priority]` config table. A future attempt-count or time-decay variant would
add one; this leaf does not.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# AttemptSummary — the per-unit fact the host hands in (derived from the ledger).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptSummary:
    """The attempt facts `classify` reads for one unit — PURE data the host gathers.

    The host derives this from the same attempt ledger `cooldown` already reads
    (`pick_cooldown.latest_attempts` in the job repo, or `lane_journal` OP_ATTEMPT
    records): a unit ABSENT from that map is never-attempted; a unit present carries
    its most-recent attempt's ms-epoch stamp.

      * ``attempted`` — has this unit EVER been recorded as a pick-attempt?
      * ``last_attempt_ms`` — the most-recent attempt's ms-epoch stamp (``None`` when
        never attempted, or when a present row's stamp was unreadable — treated as
        most-stale so it sorts earliest among attempted units; degrade-never-crash).
    """

    attempted: bool = False
    last_attempt_ms: Optional[int] = None

    @classmethod
    def never(cls) -> "AttemptSummary":
        """A never-attempted summary — the fail-open default (sorts FIRST)."""
        return cls(attempted=False, last_attempt_ms=None)

    @classmethod
    def at(cls, last_attempt_ms: Optional[int]) -> "AttemptSummary":
        """An attempted summary stamped at ``last_attempt_ms`` (None → most-stale)."""
        return cls(attempted=True, last_attempt_ms=last_attempt_ms)


# ---------------------------------------------------------------------------
# Freshness — the closed two-value verdict.
# ---------------------------------------------------------------------------


class Freshness(str, enum.Enum):
    """Whether a unit has ever been attempted (docs/254).

    `str`-valued so it round-trips a `--json` token / exit code without a lookup
    table (the `CooldownState` / `Reconciliation` idiom). The two members are the
    only freshness tiers; the LRU ordering among `ATTEMPTED` units lives in the
    `PickPriority.sort_key`, not in a third enum member.
    """

    NEVER_ATTEMPTED = "NEVER_ATTEMPTED"  # zero recorded attempts — pick this first
    ATTEMPTED = "ATTEMPTED"              # tried before — demote below fresh work

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# ---------------------------------------------------------------------------
# PickPriority — the typed verdict carrying the load-bearing sort_key.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PickPriority:
    """A unit's freshness verdict + the `sort_key` a picker appends to its own key.

    Frozen + the kernel verdict idiom. ``freshness`` is the typed tier;
    ``last_attempt_ms`` is the stamp the LRU order reads (0 when never attempted or
    unknown); ``reason`` is the operator-facing one-liner.

    The load-bearing field is `sort_key` — the tuple a host appends AFTER its
    `(priority, status)` key so freshness breaks ties WITHIN a tier and nowhere else.
    """

    unit_id: str
    freshness: Freshness
    last_attempt_ms: int = 0
    reason: str = ""

    @property
    def sort_key(self) -> tuple[int, int]:
        """The lower-wins tuple a picker appends to its `(priority, status, …)` key.

          * NEVER_ATTEMPTED → ``(0, 0)`` — sorts FIRST (pick new work).
          * ATTEMPTED       → ``(1, last_attempt_ms)`` — sorts after all fresh work,
            then ascending by last-attempt stamp = least-recently-tried first (LRU).

        Lower wins, matching the host's existing lower-wins tuple sort. Because this
        is appended after the priority/status terms, it can ONLY reorder within a
        tier — never across tiers, never in/out of the candidate set (the safety
        invariant in the module docstring).
        """
        if self.freshness is Freshness.NEVER_ATTEMPTED:
            return (0, 0)
        return (1, self.last_attempt_ms)

    @property
    def is_fresh(self) -> bool:
        """True iff this unit has never been attempted (the inverse a picker reads)."""
        return self.freshness is Freshness.NEVER_ATTEMPTED

    def to_dict(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "freshness": self.freshness.value,
            "last_attempt_ms": self.last_attempt_ms,
            "sort_key": list(self.sort_key),
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# classify — the pure fold over a unit's attempt summary.
# ---------------------------------------------------------------------------


def classify(unit_id: str, summary: Optional[AttemptSummary]) -> PickPriority:
    """Fold a unit's attempt summary into its freshness verdict. PURE — no I/O.

    ``summary`` is the `AttemptSummary` the host derived from the attempt ledger
    (the same ledger `cooldown` reads). The fold (docs/254):

      * ``summary`` missing, or ``attempted is False`` → ``NEVER_ATTEMPTED`` (sorts
        first). The fail-open default: a unit the host could not summarise is treated
        as fresh, never refused.
      * ``attempted is True`` → ``ATTEMPTED`` carrying ``last_attempt_ms`` (a missing
        / non-int stamp coerces to 0 → most-stale, sorts earliest among attempted).

    Returns a `PickPriority`; never raises.
    """
    uid = str(unit_id)

    # Fail-open: no summary, or an explicitly never-attempted one → fresh.
    if summary is None or not getattr(summary, "attempted", False):
        return PickPriority(
            unit_id=uid,
            freshness=Freshness.NEVER_ATTEMPTED,
            last_attempt_ms=0,
            reason="no recorded pick-attempt — never-attempted; pick this before "
                   "any already-tried unit (fresh work first)",
        )

    # Attempted — carry the last-attempt stamp for the LRU order. A missing / garbled
    # stamp coerces to 0 (most-stale) so a present-but-unstamped row still sorts as
    # attempted, just earliest among them — degrade-never-crash.
    raw = getattr(summary, "last_attempt_ms", None)
    try:
        last_ms = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        last_ms = 0

    return PickPriority(
        unit_id=uid,
        freshness=Freshness.ATTEMPTED,
        last_attempt_ms=last_ms,
        reason=(f"already attempted (last at {last_ms}ms) — demoted below "
                f"never-attempted work; among attempted units the least-recently-"
                f"tried sorts first (LRU)"),
    )

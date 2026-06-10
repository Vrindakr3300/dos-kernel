"""BRK — the circuit breaker: *this keeps failing; stop, and escalate the rung.*

docs/223 — idea **H2** from the Claude Code source audit (docs/189). A circuit
breaker is the oldest pattern in reliability engineering: count failures, and when
they pile up, *stop trying the same thing* — open the circuit so the caller does
something else instead of hammering a broken path. DOS already has this pattern
**six times over**, hand-coded inline in `loop_decide`: `consecutive_unclear`,
`consecutive_overloaded`, `consecutive_dirty_zero`, `consecutive_stale_stamp` —
each is the same ~15 lines (bump a counter, compare to a max, stop if reached,
reset on a clean outcome), differing only in *which* counter, *what* threshold, and
*what to do when it trips*. That repetition is the smell this module removes: the
control logic is **mechanism** (identical everywhere), and the counter / threshold /
trip-action are **policy** (different everywhere). Lift the mechanism into one pure
leaf; make the policy data.

This is the `malloc` move, stated plainly. `malloc` is in every C program because
it is mechanism (hand out bytes) with policy (what you allocate) pushed out. A
breaker hard-wired to "stop the dispatch loop after 3 UNCLEAR iterations" can never
be universal — the 3, the UNCLEAR, and the dispatch loop are someone's policy baked
into the mechanism. A breaker that knows only "this failure class has now happened N
times consecutively (or M times total); the policy says that's too many" *can* be,
because the caller names the class, the thresholds, and the response. The kernel
counts; it never knows what failed.

It is `liveness`/`productivity`'s shape — a pure verdict over already-gathered
state — but for a different question. Where those ask "is the run moving / still
productive?", BRK asks "has this *kind of thing* failed too many times to keep
trying?":

    liveness.classify      (ProgressEvidence, policy)   -> LivenessVerdict
    productivity.classify  (WorkHistory, policy)         -> ProductivityVerdict
    breaker.record_failure (BreakerState, policy)        -> BreakerTransition
                           ^ THIS module

**Two counters, lifted faithfully from CC** (`denialTracking.ts`). CC tracks
`consecutiveDenials` (reset on a success) AND `totalDenials` (never reset), and
trips on *either* (`shouldFallbackToPrompting`). The two catch different
pathologies, and you need both:

  - **consecutive** catches a *sustained* failure — N in a row with no recovery, a
    path that is simply broken right now. Resets the moment something succeeds (the
    incident cleared).
  - **total** catches a *flapping* failure — fail, succeed, fail, succeed… — which
    never trips a consecutive-only breaker but is still pathological (the path is
    unreliable, just not consistently down). The cumulative count, which never
    resets, is the only thing that sees it.

A consecutive-only breaker (today's `loop_decide` shape) is blind to flapping; BRK
fixes that by carrying both, exactly as CC does.

**The DOS addition: the trip ESCALATES a rung, it doesn't just stop** (idea H3,
folded in). CC's breaker falls back from the classifier to *prompting the human*.
DOS already has a richer ladder for "who adjudicates when the cheaper mechanism is
stuck" — the trust ladder ORACLE → JUDGE → HUMAN (`docs/86`, `dos.judges`). So an
open breaker does not just say STOP; it names *where to escalate* — keep going on
the same rung (NONE — the breaker is advisory and the caller may continue), kick the
decision up to a non-deterministic JUDGE, or surface to a HUMAN. "Don't keep
refusing identically — escalate the rung." The kernel computes the *trip*; the host
decides what an escalation MEANS (re-dispatch under a judge, queue an operator
decision) — the same advisory line `liveness`/`productivity` hold: BRK reports, it
never kills a process or refuses a lease.

**Byte-clean / no-I/O / no-policy-names.** The state is two integers the caller
threads through its own loop; `record_failure` / `record_success` are pure folds —
no clock, no file, no host vocabulary. The breaker never sees the failure's
*identity* (it is handed a count, not an UNCLEAR token), so it cannot smuggle in a
host assumption. A workspace declares the thresholds + escalation in `dos.toml
[breaker]` per failure class (the closed-config-as-data pattern); the defaults are
the CC constants (3 consecutive / 20 total).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, replace
from typing import Optional


class BreakerState(str, enum.Enum):
    """Is the circuit CLOSED (keep going) or OPEN (tripped)?

    The classic two-state breaker. `str`-valued so it round-trips through a CLI
    stdout token / exit-code map without a lookup table (the `liveness.Liveness` /
    `productivity.Productivity` idiom). (No HALF_OPEN state: that is a *recovery*
    probe — "let one request through to test the waters" — which is a host
    actuation, not a kernel verdict. BRK reports the trip; the host decides whether
    to retry, exactly the advisory line.)
    """

    CLOSED = "CLOSED"  # failures are under the limits — the path is still usable
    OPEN = "OPEN"      # a limit was reached — stop hammering this path, escalate

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class Escalation(str, enum.Enum):
    """Where an OPEN breaker says to escalate — the trust-ladder rung (docs/86).

    The DOS enrichment of CC's binary "fall back to prompting": instead of one
    fallback, name the rung. The kernel computes which rung the *policy* declared
    for this failure class; the host decides what acting on it means. ORACLE→JUDGE
    →HUMAN is monotonic in trust-cost — a policy escalates UP the ladder, never
    down (you don't answer a stuck human with a deterministic re-check).
    """

    NONE = "NONE"    # advisory only — report OPEN, let the caller decide (the default floor)
    JUDGE = "JUDGE"  # kick the stuck decision to a non-deterministic adjudicator (dos.judges)
    HUMAN = "HUMAN"  # surface to an operator — the irreducible seed (the dos decisions queue)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class BreakerPolicy:
    """The thresholds + escalation that define ONE failure class's breaker — policy, not mechanism.

    The same "mechanism is kernel, thresholds are config" split as `liveness`'s
    windows and `productivity`'s floor. The defaults are the CC `denialTracking.ts`
    constants (3 consecutive, 20 total). A workspace declares one of these per
    failure class in `dos.toml [breaker]` (closed-config-as-data, like
    `[lanes]`/`[liveness]`); the host names the class, the kernel just counts.

      max_consecutive — trip when this many failures occur IN A ROW (reset by any
                        success). Catches a *sustained* outage. CC's
                        `maxConsecutive`. 0 disables the consecutive rung (only the
                        total rung can trip).
      max_total       — trip when this many failures occur in TOTAL over the
                        breaker's life (never reset). Catches a *flapping* failure a
                        consecutive count misses. CC's `maxTotal`. 0 disables the
                        total rung.
      on_trip         — the `Escalation` rung an OPEN verdict names (NONE / JUDGE /
                        HUMAN). Default NONE — advisory, the kernel's safe floor.

    At least one rung must be enabled (a policy with both maxima 0 can never trip,
    which is almost certainly a config mistake — refuse it rather than silently
    build a breaker that does nothing).
    """

    max_consecutive: int = 3       # CC maxConsecutive — N-in-a-row (sustained outage)
    max_total: int = 20            # CC maxTotal — cumulative cap (flapping failure)
    on_trip: Escalation = Escalation.NONE

    def __post_init__(self) -> None:
        if self.max_consecutive < 0 or self.max_total < 0:
            raise ValueError("breaker thresholds must be non-negative")
        if self.max_consecutive == 0 and self.max_total == 0:
            raise ValueError(
                "a breaker with both thresholds 0 can never trip — enable at least "
                "one rung (max_consecutive or max_total)"
            )


DEFAULT_POLICY = BreakerPolicy()


@dataclass(frozen=True)
class BreakerCounts:
    """The breaker's carried state — two integers the caller threads through its loop.

    The whole state, by design: the breaker is a fold over a failure/success stream,
    and these two counts are everything the fold needs (the `loop_decide.LoopState`
    counters, extracted and named generically). Immutable — every transition returns
    a NEW `BreakerCounts`, so a caller never re-derives the count by hand and the
    state is replay-testable on frozen fixtures.

      consecutive — failures since the last success (reset by `record_success`).
      total       — failures over the breaker's whole life (never reset).
    """

    consecutive: int = 0
    total: int = 0

    def __post_init__(self) -> None:
        if self.consecutive < 0 or self.total < 0:
            raise ValueError("breaker counts must be non-negative")


@dataclass(frozen=True)
class BreakerVerdict:
    """The verdict for one transition: CLOSED/OPEN + WHY + where to escalate.

    `state` is the typed `BreakerState`. `escalation` is the rung an OPEN verdict
    names (always NONE when CLOSED — there is nothing to escalate). `reason` is the
    one-line operator-facing summary. `tripped_on` names which rung fired
    ("consecutive"/"total"/None) so the consumer/forensics can tell a sustained
    outage from a flapping one — legible distrust, the `liveness`/`productivity`
    echo-the-evidence discipline.
    """

    state: BreakerState
    escalation: Escalation
    reason: str
    tripped_on: Optional[str] = None  # "consecutive" | "total" | None (CLOSED)

    @property
    def is_open(self) -> bool:
        return self.state is BreakerState.OPEN

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "escalation": self.escalation.value,
            "reason": self.reason,
            "tripped_on": self.tripped_on,
        }


@dataclass(frozen=True)
class BreakerTransition:
    """What `record_failure`/`record_success` return: the new counts + the verdict.

    Bundling the two means the caller never has to re-thread the counts AND
    re-classify them — it gets the next state to carry and the decision to act on in
    one object (the `loop_decide.LoopDecision` shape: `next_state` + the action).
    """

    counts: BreakerCounts
    verdict: BreakerVerdict


def _classify(counts: BreakerCounts, policy: BreakerPolicy) -> BreakerVerdict:
    """Classify already-counted state. PURE — the trip test, top to bottom.

    Trips on EITHER rung (CC's `shouldFallbackToPrompting` OR-semantics). The
    consecutive rung is checked first only so its (more specific, more urgent)
    reason wins when both would fire; the verdict is OPEN either way. A disabled
    rung (threshold 0) never fires (`__post_init__` guarantees at least one is on).
    """
    # consecutive rung — a sustained run of failures with no recovery.
    if policy.max_consecutive > 0 and counts.consecutive >= policy.max_consecutive:
        return BreakerVerdict(
            state=BreakerState.OPEN,
            escalation=policy.on_trip,
            tripped_on="consecutive",
            reason=(
                f"{counts.consecutive} consecutive failures "
                f"(>= max {policy.max_consecutive}) — a sustained failure, open the "
                f"circuit"
                + (f"; escalate to {policy.on_trip.value}"
                   if policy.on_trip is not Escalation.NONE else "")
            ),
        )
    # total rung — a flapping failure a consecutive count would miss.
    if policy.max_total > 0 and counts.total >= policy.max_total:
        return BreakerVerdict(
            state=BreakerState.OPEN,
            escalation=policy.on_trip,
            tripped_on="total",
            reason=(
                f"{counts.total} total failures (>= max {policy.max_total}) — a "
                f"flapping/unreliable path, open the circuit"
                + (f"; escalate to {policy.on_trip.value}"
                   if policy.on_trip is not Escalation.NONE else "")
            ),
        )
    # CLOSED — under both limits.
    return BreakerVerdict(
        state=BreakerState.CLOSED,
        escalation=Escalation.NONE,
        tripped_on=None,
        reason=(
            f"{counts.consecutive} consecutive / {counts.total} total failures — "
            f"under the limits (consecutive {policy.max_consecutive}, total "
            f"{policy.max_total}); circuit closed"
        ),
    )


def record_failure(
    counts: BreakerCounts, policy: BreakerPolicy = DEFAULT_POLICY
) -> BreakerTransition:
    """Record one failure of this class and classify. PURE — no I/O.

    Bumps BOTH counters (CC `recordDenial`), then classifies the new state. Returns
    the next `BreakerCounts` to carry and the `BreakerVerdict` to act on. An already-
    OPEN breaker stays OPEN (the counts only grow); recording past the trip is safe
    and idempotent in outcome (the verdict stays OPEN), so a caller need not special-
    case "already tripped."
    """
    bumped = replace(counts, consecutive=counts.consecutive + 1, total=counts.total + 1)
    return BreakerTransition(counts=bumped, verdict=_classify(bumped, policy))


def record_success(
    counts: BreakerCounts, policy: BreakerPolicy = DEFAULT_POLICY
) -> BreakerTransition:
    """Record one success of this class and classify. PURE — no I/O.

    Resets the CONSECUTIVE counter (the sustained-outage signal cleared) but NOT the
    total (CC `recordSuccess` — a flapping path's cumulative count must survive its
    intermittent successes, or flapping could never trip). So a success can CLOSE a
    consecutive-tripped breaker, but it cannot un-trip a total-tripped one — which is
    correct: a path that has failed 20 times total is unreliable no matter how many
    times it also succeeded.
    """
    healed = replace(counts, consecutive=0)
    return BreakerTransition(counts=healed, verdict=_classify(healed, policy))


def classify(
    counts: BreakerCounts, policy: BreakerPolicy = DEFAULT_POLICY
) -> BreakerVerdict:
    """Classify the CURRENT counts without recording anything. PURE — no I/O.

    The read-only verdict (the `dos breaker` CLI / a `dos top` chip): "given these
    counts, is the circuit open?" — without mutating the stream. `record_failure`/
    `record_success` are the write path; this is the peek.
    """
    return _classify(counts, policy)

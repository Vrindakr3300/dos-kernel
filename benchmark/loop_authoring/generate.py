"""Property-based trajectory generator — the honest distribution (docs/260 §4).

A trajectory is a sequence of `IterationOutcome`s that a real loop could produce.
We generate them by WALKING THE KERNEL'S OWN TRANSITION RELATION: start at a fresh
`LoopState`, draw a plausible outcome for each tick, call `decide`, and follow the
returned `next_state` until the kernel STOPs (or a horizon cap). The outcome at
each tick is drawn from a distribution over `OutcomeKind` (+ the qualifiers that
matter: gate verdict, replan productivity, packet judge / ship-count), so the
*reachable* `(state, outcome)` pairs — including the interacting cross-terms a
captured log under-samples — get covered.

Why this is honest (and what it is NOT): the generator is the kernel's transition
relation, not a prompt author's intuition about what is "hard." It does not
hand-author gotchas (docs/260 §4 source 3, excluded). It DOES let us tilt the
outcome mix toward the conditions the §3 table predicts prose drops — but the
TILT only changes how often a condition is *visited*, never what the correct
decision *is* (that is always `decide`). A tilt cannot manufacture a divergence;
it can only buy statistical power on a rung (the docs/235 slice-must-have-power
discipline).

Deterministic: every generator takes an explicit integer seed, so a run is
reproducible and the journal can be re-derived (no `Math.random`/wall-clock).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from dos.loop_decide import (
    IterationOutcome,
    LoopDecision,
    LoopState,
    OutcomeKind,
    decide,
)
from dos.gate_classify import ReplanProductivity, Verdict


# ---------------------------------------------------------------------------
# The outcome mix — a named, tunable distribution over what one iteration emits.
#
# Each weight is the relative likelihood of drawing that outcome SHAPE on a tick.
# The shapes are the realistic ones a /dispatch-loop iteration actually produces;
# the qualifiers (gate verdict, replan productivity, ship-count) are drawn
# conditionally inside `_draw_outcome`. The DEFAULT mix is deliberately
# work-heavy (most iters ship or drain cleanly) so the trajectories look like real
# loops, not a stress test. The `--stress` mix tilts toward the interacting
# invariants (DRAINED_TWICE cross-term, adopt-wait, dirty-zero) to buy power on
# the rungs §3 predicts prose drops — power, not a rigged answer.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutcomeMix:
    """Relative weights over the outcome shapes drawn per tick."""

    shipped_clean: float = 5.0      # SHIPPED, picks landed — the healthy case
    shipped_dirty_zero: float = 0.6  # SHIPPED but DIRTY + 0 picks — the degraded signal
    gate_live: float = 1.0          # GATE verdict=LIVE (rare; routes onward)
    gate_drain: float = 2.0         # GATE verdict=DRAIN — lane drained
    gate_blocked: float = 0.4       # GATE verdict=BLOCKED — picks blocked
    gate_stale: float = 0.5         # GATE verdict=STALE-STAMP — needs reconcile
    replan_productive: float = 1.5  # REPLAN_DONE, productive (real refill attempt)
    replan_unproductive: float = 1.0  # REPLAN_DONE, 0 refill
    unclear: float = 0.8            # crashed/killed before the gate
    rate_limited: float = 0.15      # usage window exhausted
    overloaded: float = 0.15        # transient 529

    @staticmethod
    def stress() -> "OutcomeMix":
        """Tilt toward the interacting invariants — power on the hard rungs."""
        return OutcomeMix(
            shipped_clean=2.0,
            shipped_dirty_zero=1.5,
            gate_live=0.5,
            gate_drain=3.0,
            gate_blocked=1.0,
            gate_stale=1.5,
            replan_productive=2.0,
            replan_unproductive=2.5,
            unclear=1.5,
            rate_limited=0.2,
            overloaded=0.3,
        )

    def _shapes_weights(self) -> tuple[list[str], list[float]]:
        d = {
            "shipped_clean": self.shipped_clean,
            "shipped_dirty_zero": self.shipped_dirty_zero,
            "gate_live": self.gate_live,
            "gate_drain": self.gate_drain,
            "gate_blocked": self.gate_blocked,
            "gate_stale": self.gate_stale,
            "replan_productive": self.replan_productive,
            "replan_unproductive": self.replan_unproductive,
            "unclear": self.unclear,
            "rate_limited": self.rate_limited,
            "overloaded": self.overloaded,
        }
        return list(d.keys()), list(d.values())


def _outcome_for_shape(shape: str) -> IterationOutcome:
    """Map a drawn shape name to the typed IterationOutcome a real iter emits."""
    if shape == "shipped_clean":
        return IterationOutcome(
            kind=OutcomeKind.SHIPPED, packet_judge="SHIPPED-CLEAN", ship_count=2
        )
    if shape == "shipped_dirty_zero":
        return IterationOutcome(
            kind=OutcomeKind.SHIPPED, packet_judge="SHIPPED-DIRTY", ship_count=0
        )
    if shape == "gate_live":
        return IterationOutcome(kind=OutcomeKind.GATE, verdict=Verdict.LIVE)
    if shape == "gate_drain":
        return IterationOutcome(kind=OutcomeKind.GATE, verdict=Verdict.DRAIN)
    if shape == "gate_blocked":
        return IterationOutcome(kind=OutcomeKind.GATE, verdict=Verdict.BLOCKED)
    if shape == "gate_stale":
        return IterationOutcome(kind=OutcomeKind.GATE, verdict=Verdict.STALE_STAMP)
    if shape == "replan_productive":
        return IterationOutcome(
            kind=OutcomeKind.REPLAN_DONE,
            replan_productivity=ReplanProductivity.PRODUCTIVE,
        )
    if shape == "replan_unproductive":
        return IterationOutcome(
            kind=OutcomeKind.REPLAN_DONE,
            replan_productivity=ReplanProductivity.UNPRODUCTIVE,
        )
    if shape == "unclear":
        return IterationOutcome(kind=OutcomeKind.UNCLEAR)
    if shape == "rate_limited":
        return IterationOutcome(kind=OutcomeKind.RATE_LIMITED)
    if shape == "overloaded":
        return IterationOutcome(kind=OutcomeKind.OVERLOADED)
    raise ValueError(f"unknown shape {shape!r}")


@dataclass(frozen=True)
class Tick:
    """One step of a trajectory: the state IN, the outcome drawn, the kernel decision."""

    state_in: LoopState
    outcome: IterationOutcome
    kernel_decision: LoopDecision


def generate_trajectory(
    seed: int,
    *,
    mix: Optional[OutcomeMix] = None,
    gate_mode: str = "hard",
    horizon: int = 40,
) -> list[Tick]:
    """Walk the kernel's transition relation into one realistic trajectory.

    Returns the list of ticks up to and including the kernel's STOP (or `horizon`
    ticks if it never stops within the cap). Each tick records the exact
    `(state_in, outcome)` the prose arm will also be scored on, plus the kernel's
    ground-truth decision.
    """
    mix = mix or OutcomeMix()
    rng = random.Random(seed)
    shapes, weights = mix._shapes_weights()

    state = LoopState(iteration=1, gate_mode=gate_mode)
    ticks: list[Tick] = []
    for _ in range(horizon):
        shape = rng.choices(shapes, weights=weights, k=1)[0]
        outcome = _outcome_for_shape(shape)
        decision = decide(state, outcome)
        ticks.append(Tick(state_in=state, outcome=outcome, kernel_decision=decision))
        if decision.action == _STOP:
            break
        # retry-same-iter (529 backoff) and continue both carry next_state forward;
        # the kernel already bumped the iteration where appropriate.
        state = decision.next_state
    return ticks


_STOP = "stop"


def generate_corpus(
    n: int,
    *,
    base_seed: int = 0,
    mix: Optional[OutcomeMix] = None,
    gate_mode: str = "hard",
    horizon: int = 40,
) -> list[list[Tick]]:
    """Generate `n` independent trajectories with deterministic per-trajectory seeds."""
    return [
        generate_trajectory(
            seed=base_seed + i, mix=mix, gate_mode=gate_mode, horizon=horizon
        )
        for i in range(n)
    ]

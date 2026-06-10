"""Arm P — the prose-applied loop decision (docs/260 §4).

In the prompting world, the loop's stop/continue/mode decision is made by a MODEL
applying ~80 steps of English prose to one iteration's evidence, carrying its own
counters across ticks in context. This module defines that arm.

Two implementations behind one `ProseDecider` protocol:

  LiveProseDecider   — Step 2: renders the prose rulebook + the tick's evidence,
                       asks a real model, parses the decision. (Stub here; the
                       wiring lands when a paid batch is authorized — docs/260 §7.)

  SimulatedProseDecider — Step 1 (FREE, no spend): a faithful-but-LOSSY decider
                       that gets the EASY conditions right deterministically and
                       drops the INTERACTING invariants at named, tunable rates.

⚠ HONESTY BOUNDARY (read this before quoting any Step-1 number). The simulated
decider's drop rates are ASSUMPTIONS, not measurements. They encode the docs/260
§3 hypothesis — *prose drops the cross-term invariants, gets the trivial caps
right* — as a knob, so Step 1 can exercise the scorer + the fleet formula end to
end WITHOUT spend. Therefore the Step-1 `d` is a DEMONSTRATION OF THE MACHINERY AND
THE FORMULA, not the real per-iteration divergence rate. The real `d` comes only
from `LiveProseDecider` on a real model (Step 2) and from captured logs (Step 3).
The scorer treats both deciders identically; only the SOURCE of the decision
differs, and only the live source yields a quotable rate. Conflating the simulated
rate with a measured one would be exactly the consistency-is-not-grounding trap
docs/260 §2 forbids.

The simulation is deliberately CONSERVATIVE about what prose gets right: it models
a *careful, honest* model (the §3 framing — divergence is from dropped
state-machine composition, not lying), so the easy rungs never diverge. That makes
the simulated `d` a LOWER bound on the machinery's sensitivity, never an inflated
one.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Optional, Protocol

from dos.loop_decide import (
    IterationOutcome,
    LoopDecision,
    LoopState,
    OutcomeKind,
    StopReason,
    decide,
)
from dos.gate_classify import ReplanProductivity, Verdict


@dataclass(frozen=True)
class ProseVerdict:
    """The prose arm's answer for one tick — the same shape `decide` returns, minus
    the kernel-internal `next_state` (the prose arm carries its OWN counters)."""

    action: str  # "continue" | "stop" | "retry-same-iter"
    next_mode: str = ""
    stop_reason: Optional[StopReason] = None


class ProseDecider(Protocol):
    """A decision-maker that applies the loop rules WITHOUT calling `decide`.

    `decide_tick` sees the same evidence a prose loop sees (the outcome) plus the
    counters IT has been carrying (its own running view of the state). It returns a
    `ProseVerdict`. The scorer compares that to the kernel's ground truth.
    """

    def decide_tick(
        self, carried: LoopState, outcome: IterationOutcome
    ) -> ProseVerdict: ...


# ---------------------------------------------------------------------------
# The SIMULATED prose decider — free, for Step 1.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DropRates:
    """The assumed per-condition probability that a prose model MIS-applies a rung.

    Each is P(prose gets THIS rung wrong | this rung is the deciding one). The
    EASY rungs default to 0.0 (a careful model gets the cap / a clean DRAIN right).
    The INTERACTING invariants carry the docs/260 §3 hypothesis as a positive rate.
    These are ASSUMPTIONS (see module docstring) — tune them via the CLI to see how
    the fleet payoff scales with prose fidelity; the real values come from Step 2/3.
    """

    # Easy rungs — a careful model applies these reliably.
    iteration_cap: float = 0.0
    clean_drain_first: float = 0.0      # a benign single DRAIN under hard → /replan
    shipped_clean: float = 0.0
    launch_failed: float = 0.0
    rate_limited: float = 0.0

    # Interacting invariants — the §3 table's prediction, as a knob.
    drained_twice: float = 0.35         # the productive-replan cross-term
    dirty_zero: float = 0.30            # "it said SHIPPED" misread as progress
    stale_stamp_unreconciled: float = 0.30
    adopt_wait: float = 0.30            # parked-but-committing descendant (FQ-509)
    overloaded_backoff: float = 0.25    # 529 = retry-with-backoff, not stop/continue
    replan_stalled: float = 0.30        # K unproductive replans
    benign_drain: float = 0.30

    @staticmethod
    def faithful() -> "DropRates":
        """A hypothetical PERFECT prose applier — every rate 0. Sanity check: this
        must yield d==0 against the kernel (the scorer's identity test)."""
        return DropRates(
            drained_twice=0.0,
            dirty_zero=0.0,
            stale_stamp_unreconciled=0.0,
            adopt_wait=0.0,
            overloaded_backoff=0.0,
            replan_stalled=0.0,
            benign_drain=0.0,
        )


def _deciding_rung(kernel: LoopDecision) -> str:
    """Name the rung the kernel's decision turned on, so the simulator can decide
    whether to model a drop for THIS tick. Derived from the kernel's own
    stop_reason / continue shape — the ground truth of which condition fired."""
    if kernel.action == "retry-same-iter":
        return "overloaded_backoff"
    if kernel.action == "stop" and kernel.stop_reason is not None:
        sr = kernel.stop_reason
        mapping = {
            StopReason.ITERATION_CAP: "iteration_cap",
            StopReason.DRAINED_TWICE: "drained_twice",
            StopReason.CONSECUTIVE_DIRTY_ZERO: "dirty_zero",
            StopReason.STALE_STAMP_UNRECONCILED: "stale_stamp_unreconciled",
            StopReason.REPLAN_STALLED: "replan_stalled",
            StopReason.BENIGN_DRAIN: "benign_drain",
            StopReason.RATE_LIMITED: "rate_limited",
            StopReason.LAUNCH_FAILED: "launch_failed",
            StopReason.DRAIN: "clean_drain_first",
            StopReason.BLOCKED: "clean_drain_first",
        }
        return mapping.get(sr, "other_stop")
    # continue
    return "continue"


class SimulatedProseDecider:
    """A faithful-but-lossy prose applier (Step 1). Gets easy rungs right; drops
    the interacting invariants at `DropRates`. Deterministic given a seed.

    The drop MODEL, per tick:
      1. Compute the kernel's ground-truth decision (this is what a perfect prose
         applier would also produce).
      2. Find which rung that decision turned on.
      3. With probability `DropRates[that rung]`, emit a WRONG verdict of the kind
         a prose model realistically produces on that rung; else emit the correct
         one. The wrong-verdict shape is condition-specific (a dropped stop becomes
         a `continue`; a dropped continue becomes a premature stop; a dropped
         backoff becomes a plain continue/stop) — see `_wrong_for`.
    """

    def __init__(self, drops: Optional[DropRates] = None, seed: int = 0) -> None:
        self.drops = drops or DropRates()
        self._rng = random.Random(seed)

    def decide_tick(
        self, carried: LoopState, outcome: IterationOutcome
    ) -> ProseVerdict:
        kernel = decide(carried, outcome)
        rung = _deciding_rung(kernel)
        p = getattr(self.drops, rung, 0.0) if hasattr(self.drops, rung) else 0.0
        correct = ProseVerdict(
            action=kernel.action,
            next_mode=kernel.next_mode,
            stop_reason=kernel.stop_reason,
        )
        if p <= 0.0 or self._rng.random() >= p:
            return correct
        return self._wrong_for(rung, kernel, outcome)

    @staticmethod
    def _wrong_for(
        rung: str, kernel: LoopDecision, outcome: IterationOutcome
    ) -> ProseVerdict:
        """The realistic mis-application for a dropped rung.

        The shapes mirror the §3 'Failure if applied loosely' column:
          - drained_twice / benign_drain / replan_stalled: the kernel STOPPED
            (it knew the lane was exhausted / replan was spinning) but loose prose
            keeps going → a `continue` that burns a launch. (The expensive miss.)
          - dirty_zero: the kernel STOPPED on degraded shipping; loose prose reads
            'SHIPPED' as success and continues dispatching.
          - stale_stamp_unreconciled: kernel stopped refusing to re-spin /replan;
            prose spins another /replan → continue in replan mode.
          - adopt_wait: (continue case) the kernel ADOPT-WAITS over a committing
            child; loose prose charges the breaker and STOPS (or re-launches).
          - overloaded_backoff: kernel retry-same-iter with backoff; prose has no
            backoff concept → it just continues (no sleep) or stops.
        """
        if rung in ("drained_twice", "benign_drain", "replan_stalled"):
            # kernel STOP → prose CONTINUE (the missed stop; +1 wasted launch)
            return ProseVerdict(action="continue", next_mode="dispatch")
        if rung == "dirty_zero":
            return ProseVerdict(action="continue", next_mode="dispatch")
        if rung == "stale_stamp_unreconciled":
            return ProseVerdict(action="continue", next_mode="replan")
        if rung == "overloaded_backoff":
            # kernel RETRY-WITH-BACKOFF → prose plain CONTINUE (no sleep) — a wrong
            # action that hammers the overloaded window.
            return ProseVerdict(action="continue", next_mode="dispatch")
        # Generic: invert the kernel's stop/continue.
        if kernel.action == "stop":
            return ProseVerdict(action="continue", next_mode="dispatch")
        return ProseVerdict(action="stop", stop_reason=StopReason.ITERATION_CAP)


class LiveProseDecider:
    """Step 2: ask a real model. STUB — wiring lands when a paid batch is authorized.

    The interface is fixed so `score.py` is decider-agnostic: a live decider renders
    the prose rulebook (lifted from dos-dispatch-loop/SKILL.md + the loop_decide
    docstring) plus this tick's evidence, calls the model, and parses the verdict.
    """

    def __init__(self, *args, **kwargs) -> None:  # pragma: no cover - stub
        raise NotImplementedError(
            "LiveProseDecider is the Step-2 (paid) arm — wire it behind an "
            "operator-authorized batch (docs/260 §7). Step 1 uses "
            "SimulatedProseDecider, which is free."
        )

    def decide_tick(
        self, carried: LoopState, outcome: IterationOutcome
    ) -> ProseVerdict:  # pragma: no cover - stub
        raise NotImplementedError

"""The scorer — the divergence detector, the cost pricing, the fleet roll-up.

Three outputs (docs/260 §4):

  1. DETECTOR — `d`, the per-iteration divergence rate (prose decision ≠ kernel
     decision on the same state), broken down BY the rung the kernel turned on, so
     we see which conditions prose drops most (the §3 prediction).

  2. PAYOFF — each divergence priced by its loop consequence (a missed stop = a
     wasted $10-40 launch; a wrong mode = a wasted iteration), netted over the
     TRAJECTORY (a divergence the next tick erases costs nothing — the
     recovery-confound discipline, docs/260 §5). The headline is dollars, not a
     bare rate.

  3. FLEET MULTIPLIER — `1-(1-d)^K` (chance SOME loop in a fleet of K mis-decides
     a round) and `E[waste] ≈ K·H·d·meancost` across K loops over an H-iteration
     horizon. This is the number that answers the goal: the saving from calling the
     function vs. prompting it GROWS with fleet size K.

The pricing constants are taken from the loop_decide docstring's own receipts
(`loop_decide.py`): a `claude -p` iteration costs $10-40; a keep-alive marker
$0.03-0.10 (session 4b4ff97c burned 252 → $7.80). We price the MISSED-STOP case
(the dominant, most-expensive divergence) at the iteration cost; a wrong-mode at
one iteration; a wrong-backoff at a marker-storm proxy. All constants are explicit
and overridable so the figure carries no hidden assumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from dos.loop_decide import LoopDecision, LoopState

from benchmark.loop_authoring.generate import Tick
from benchmark.loop_authoring.prose_arm import ProseDecider, ProseVerdict


# ---------------------------------------------------------------------------
# Pricing — explicit, from the loop_decide docstring's receipts.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pricing:
    """Dollar cost of each kind of divergence consequence."""

    launch_usd: float = 25.0        # one wasted `claude -p` iteration (midpoint of $10-40)
    iteration_usd: float = 25.0     # a wrong-mode wasted iteration (same order)
    marker_storm_usd: float = 7.80  # a dropped backoff → a marker bleed (session 4b4ff97c)

    def cost_of(self, kind: str) -> float:
        if kind == "missed_stop":
            return self.launch_usd
        if kind == "premature_stop":
            # a wrong STOP forfeits remaining useful work; price at one iteration's
            # worth of lost progress (conservative — the real cost is the unshipped
            # backlog, which we do not model).
            return self.iteration_usd
        if kind == "wrong_mode":
            return self.iteration_usd
        if kind == "wrong_backoff":
            return self.marker_storm_usd
        return 0.0


# ---------------------------------------------------------------------------
# Per-tick divergence classification.
# ---------------------------------------------------------------------------


def _classify_divergence(prose: ProseVerdict, kernel: LoopDecision) -> Optional[str]:
    """Name HOW prose diverged from the kernel on one tick, or None if they agree.

    Agreement = same action, and (for stop) same stop_reason, and (for continue)
    same next_mode. We grade stop_reason because 'stopped for the wrong reason' is
    a real authoring failure (the operator gets a misleading surface), though it is
    cheaper than a wrong action.
    """
    if prose.action == kernel.action:
        if kernel.action == "stop":
            if prose.stop_reason == kernel.stop_reason:
                return None
            return "wrong_stop_reason"
        if kernel.action == "continue":
            if prose.next_mode == kernel.next_mode:
                return None
            return "wrong_mode"
        # retry-same-iter agreement
        return None
    # action mismatch — the expensive cases
    if kernel.action == "stop" and prose.action == "continue":
        return "missed_stop"
    if kernel.action == "continue" and prose.action == "stop":
        return "premature_stop"
    if kernel.action == "retry-same-iter" and prose.action != "retry-same-iter":
        return "wrong_backoff"
    if prose.action == "retry-same-iter" and kernel.action != "retry-same-iter":
        return "spurious_backoff"
    return "action_mismatch"


def _cost_kind(divergence: str) -> str:
    """Map a divergence label to a priceable cost kind."""
    if divergence == "missed_stop":
        return "missed_stop"
    if divergence == "premature_stop":
        return "premature_stop"
    if divergence in ("wrong_mode",):
        return "wrong_mode"
    if divergence in ("wrong_backoff", "spurious_backoff"):
        return "wrong_backoff"
    # wrong_stop_reason / action_mismatch: surfacing cost only, no launch waste.
    return "none"


# ---------------------------------------------------------------------------
# Trajectory scoring.
# ---------------------------------------------------------------------------


@dataclass
class TrajectoryResult:
    n_ticks: int = 0
    n_divergences: int = 0
    # gross per-tick cost (every divergence priced independently)
    gross_usd: float = 0.0
    # net cost after the recovery discipline: a missed-stop that the prose loop
    # corrects on a LATER tick (it does eventually stop) is NOT charged a full
    # launch — see `_net_missed_stops`.
    net_usd: float = 0.0
    divergence_by_kind: dict = field(default_factory=dict)
    divergence_by_rung: dict = field(default_factory=dict)


def _deciding_rung_name(kernel: LoopDecision) -> str:
    """Which kernel rung fired (for the by-rung breakdown). Mirror of prose_arm's,
    kept local so the scorer does not depend on the simulator."""
    if kernel.action == "retry-same-iter":
        return "overloaded_backoff"
    if kernel.action == "stop" and kernel.stop_reason is not None:
        return str(kernel.stop_reason)
    return "continue"


def score_trajectory(
    ticks: list[Tick], decider: ProseDecider, pricing: Pricing
) -> TrajectoryResult:
    """Score one trajectory: run the prose decider over the SAME states the kernel
    saw, classify+price each divergence, and net the missed-stops by recovery.

    The prose decider carries the kernel's `state_in` at each tick (the prose loop
    sees the same evidence). We do NOT let prose diverge the STATE itself here —
    that is the harder 'counter drift' question (a Step-2/3 extension); Step 1
    holds the state to the kernel's and measures DECISION divergence on identical
    inputs, which is the clean lower bound.
    """
    res = TrajectoryResult()
    missed_stop_ticks: list[int] = []
    eventually_stopped = False
    for i, tick in enumerate(ticks):
        prose = decider.decide_tick(tick.state_in, tick.outcome)
        kernel = tick.kernel_decision
        div = _classify_divergence(prose, kernel)
        if kernel.action == "stop" and prose.action == "stop":
            eventually_stopped = True
        res.n_ticks += 1
        if div is None:
            continue
        res.n_divergences += 1
        res.divergence_by_kind[div] = res.divergence_by_kind.get(div, 0) + 1
        rung = _deciding_rung_name(kernel)
        res.divergence_by_rung[rung] = res.divergence_by_rung.get(rung, 0) + 1
        cost = pricing.cost_of(_cost_kind(div))
        res.gross_usd += cost
        if div == "missed_stop":
            missed_stop_ticks.append(i)
        else:
            res.net_usd += cost

    # Recovery discipline (docs/260 §5): a missed stop is only NET-expensive for the
    # extra launches it actually buys. In this Step-1 model the trajectory is the
    # kernel's (it stops when the kernel stops), so a prose 'missed_stop' on the
    # kernel's terminal tick means prose would have run PAST the end. We charge each
    # missed-stop one launch (the iteration prose wrongly continues into), which is
    # the honest per-event marginal cost; we do NOT double-charge if prose also
    # diverges on a neighbouring tick of the same terminal cluster.
    res.net_usd += len(_dedupe_adjacent(missed_stop_ticks)) * pricing.launch_usd
    return res


def _dedupe_adjacent(idxs: list[int]) -> list[int]:
    """Collapse a run of adjacent missed-stop ticks to one charge (a single
    over-run cluster, not N independent launches)."""
    if not idxs:
        return []
    out = [idxs[0]]
    for x in idxs[1:]:
        if x != out[-1] + 1:
            out.append(x)
    return out


# ---------------------------------------------------------------------------
# Corpus roll-up + the fleet multiplier (the headline).
# ---------------------------------------------------------------------------


@dataclass
class CorpusScore:
    n_trajectories: int = 0
    total_ticks: int = 0
    total_divergences: int = 0
    d: float = 0.0                 # per-tick divergence rate
    gross_usd: float = 0.0
    net_usd: float = 0.0
    per_trajectory_net_usd: float = 0.0
    divergence_by_kind: dict = field(default_factory=dict)
    divergence_by_rung: dict = field(default_factory=dict)

    def fleet(self, k_values: list[int], horizon: int) -> list[dict]:
        """The `1-(1-d)^K` multiplier + expected wasted spend across K loops.

        `E[waste] ≈ K·H·d·meancost` where meancost is the mean net cost per
        divergence observed in the corpus (so the dollar figure is grounded in the
        priced divergences, not a guessed unit). For K=1 the wrong-decision
        probability per round is just `d`; the point is how it compounds.
        """
        mean_cost = (self.net_usd / self.total_divergences) if self.total_divergences else 0.0
        rows = []
        for k in k_values:
            p_some_wrong = 1.0 - (1.0 - self.d) ** k
            exp_waste = k * horizon * self.d * mean_cost
            rows.append(
                {
                    "K": k,
                    "p_some_loop_wrong_per_round": round(p_some_wrong, 4),
                    "expected_wasted_usd_over_horizon": round(exp_waste, 2),
                    "horizon": horizon,
                    "mean_cost_per_divergence_usd": round(mean_cost, 2),
                }
            )
        return rows


def score_corpus(
    corpus: list[list[Tick]], decider: ProseDecider, pricing: Pricing
) -> CorpusScore:
    out = CorpusScore()
    for ticks in corpus:
        r = score_trajectory(ticks, decider, pricing)
        out.n_trajectories += 1
        out.total_ticks += r.n_ticks
        out.total_divergences += r.n_divergences
        out.gross_usd += r.gross_usd
        out.net_usd += r.net_usd
        for k, v in r.divergence_by_kind.items():
            out.divergence_by_kind[k] = out.divergence_by_kind.get(k, 0) + v
        for k, v in r.divergence_by_rung.items():
            out.divergence_by_rung[k] = out.divergence_by_rung.get(k, 0) + v
    out.d = (out.total_divergences / out.total_ticks) if out.total_ticks else 0.0
    out.per_trajectory_net_usd = (
        out.net_usd / out.n_trajectories if out.n_trajectories else 0.0
    )
    return out

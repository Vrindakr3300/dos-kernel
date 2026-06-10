"""The intervention-evaluation harness — score an actuation policy by its NET TASK DELTA.

docs/143 §13.2 — the missing instrument. Every other DOS axis ships an eval: `judge_eval`
scores a judge, `overlap_eval` scores a disjointness scorer, and `arg_provenance` shipped a
*detector* eval (precision/recall over minted-vs-resolved ids). The live benchmark run
proved the decisive number is none of those: a detector that was *sound* (0 % false-nudge,
83 % recall) was still **net-harmful** (−9 pp) because the *intervention* it triggered was
too disruptive (RESULTS.md "⚑ KEY DATA POINT"). So the number that decides deployment is
not "was the verdict right?" — `arg_provenance`'s eval already answers that — but **"did
ACTING on the verdict help or hurt the run?"**

This module is that instrument: the friendliness gauge for the PEP, the way `overlap_eval`
is for admission. Bring an `InterventionPolicy` (the confidence-gating knobs), bring a
corpus of replayed verdicts each labelled with the GROUND-TRUTH outcome of acting on it,
and get back the headline `net_task_delta` plus the dangerous-cell rates a PEP author
actually cares about — chiefly **wasted-disruption** (when this policy disrupts, how often
is it spent on a catch that did not matter — the exact source of the −9 pp).

The honesty stance (the same as judge_eval / overlap_eval)
==========================================================

The labels are the RESEARCHER's ground truth, derived from EXECUTED replay arms, never from
the detector. Specifically:

  * `truly_minted` — was the flagged id ACTUALLY a mint? (the controlled mint-injection
    knows; a false-flag has this False). The `overlap_eval.collided` "did it actually
    collide" discipline.
  * `mattered_to_score` — did this FK feed a hidden SQL verifier the run was scored on? From
    the verifier set, not the wrapper. This is the −9 pp axis: a true catch the verifier
    never checked buys nothing, so disrupting on it is pure cost.
  * `recovered_if_blocked` / `recovered_if_deferred` — COUNTERFACTUAL ground truth from the
    two EXECUTED A/B arms (a turn-preserving intervention vs a turn-spending one), NOT a
    guessed label. The live run measured the turn-spending recovery at ~75 % (48/64,
    RESULTS.md line 104); a turn-preserving BLOCK is expected higher (it costs no turn).

Everything here is **pure**: it consumes already-built `InterventionCase`s, runs the policy
through `intervention.choose_intervention` (the SAME path the consumer's PEP takes, so the
grid reflects what would actually be enacted — the `overlap_eval` "score under the floor"
discipline), and counts in one pass. No I/O, no host names — it sits in the kernel layer
beside `intervention`.

⚠ This is NOT a detector eval. `arg_provenance` precision/recall measures the verdict;
THIS measures the intervention. The two are orthogonal (the §13 thesis), so they are
separate instruments by design.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from dos.arg_provenance import ProvenanceVerdict
from dos.intervention import (
    BASE_INTERVENTIONS,
    Confidence,
    Intervention,
    InterventionDecision,
    InterventionLadder,
    InterventionPolicy,
    choose_intervention,
)


# ---------------------------------------------------------------------------
# A labelled example — one replayed verdict + the GROUND-TRUTH outcome of acting.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InterventionCase:
    """One replayed verdict + the ground-truth outcome of intervening on it.

    The `confidence` is NOT stored — it is DERIVED in `score()` via `choose_intervention`
    from the embedded `verdict`, so the scored action can never drift from a hand-labelled
    confidence (the label-drift trap). Every other field is a ground-truth label from an
    EXECUTED replay arm, NOT a guess (the `overlap_eval.collided` honesty discipline).

    Fields:
      verdict              — the real `ProvenanceVerdict` the detector produced. The policy is
                             scored against THIS via `choose_intervention` (same path as the
                             consumer's PEP), so the eval measures what would be enacted.
      truly_minted         — ground truth: was the flagged id ACTUALLY a mint? (False = the
                             detector false-flagged a legit derived/resolved id.)
      mattered_to_score    — ground truth: did this FK feed a verifier the run was scored on?
                             (the −9 pp axis — a true catch the verifier never checks buys
                             nothing, so disrupting on it is pure cost.)
      recovered_if_blocked — counterfactual ground truth from the turn-PRESERVING arm
                             (WARN/BLOCK): under a turn-preserving intervention, did the agent
                             recover (resolve the id correctly)?
      recovered_if_deferred— counterfactual ground truth from the turn-SPENDING arm (DEFER):
                             under a re-prompt that costs the turn, did the agent recover?
                             (the live ~75 %.)
      label                — optional human handle (carried, never scored).
    """

    verdict: ProvenanceVerdict
    truly_minted: bool
    mattered_to_score: bool
    recovered_if_blocked: bool
    recovered_if_deferred: bool
    label: str = ""


# ---------------------------------------------------------------------------
# The per-case net-delta ledger — the §13.2 formula, honestly generalized.
# ---------------------------------------------------------------------------
def _case_delta(
    case: InterventionCase, action: Intervention, ladder: InterventionLadder
) -> float:
    """The net task-delta this `(case, action)` contributes, in units of "one task verifier".

    GENERALIZES docs/143 §13.2's `caught × recovered × (1 − disruption_cost)` to all cells
    (the product only modeled the recovered-relevant cell; the −9 pp lives in a cell the
    product cannot see). The honest decomposition:

      * a real PREVENTED corruption that mattered is worth `+(1 − cost)` (a verifier flips
        fail→pass, minus the disruption tax);
      * disruption (`cost`, read from the ladder) is paid whenever the action ACTUATES
        (withholds the turn) — win or lose;
      * a DISPATCHING action (OBSERVE/WARN) lets the real (possibly minted) call land, so it
        has near-zero PREVENTION value but also near-zero disruption cost (WARN's small cost
        is its annotation, not a withheld turn).

    The IRREVERSIBILITY premise (load-bearing). EnterpriseOps-Gym mutates a shared DB where
    "every action is permanent and irreversible" (docs/143 §1) — there is no rollback. So a
    DISPATCHING action that lets a minted *relevant* write land has **already corrupted the
    scored final state**: a next-turn "correction" is a SECOND write the verifier sees
    alongside the bad FK, not a repair. Therefore a dispatched relevant mint has **zero**
    prevention value — only a WITHHOLDING rung (BLOCK/DEFER) can prevent the corruption.
    This is what makes the §13 thesis crisp: BLOCK prevents; WARN merely informs (and is
    valuable on the OTHER cells, where it costs nothing and avoids the −9pp).

    Cells:
      truly_minted ∧ mattered:
        withholding (DEFER/BLOCK) → mutation prevented → `+(1−cost)` on recovery, `−cost` if not.
        dispatching (OBSERVE/WARN)→ the bad write LANDED and cannot be un-committed → 0
                                    prevention value (the annotation may help a LATER, distinct
                                    step, but not this corrupted row). Near-zero disruption.
      truly_minted ∧ ¬mattered  → THE DANGEROUS CELL: a true catch the verifier never checks.
                                  No gain to win; a withholding action pays pure `−cost` (the
                                  live −9 pp); a dispatching one ≈ 0.
      ¬truly_minted (false-flag) → no gain; a withholding action pays `−cost`, a dispatching
                                  one ≈ 0.

    `cost` is ALWAYS `ladder.disruption_cost(action)` (normalized [0,1]) — never a hardcoded
    per-rung constant, so a host-retuned ladder reweights the eval automatically. The model
    is deliberately CONSERVATIVE about the mechanism's upside (a dispatched mint scores 0, not
    a partial credit) so the eval cannot flatter the intervention — the honesty direction.
    """
    cost = ladder.disruption_cost(action.value)
    dispatches = ladder.dispatches(action.value)
    recovered = (
        case.recovered_if_deferred
        if action is Intervention.DEFER
        else case.recovered_if_blocked
    )
    if case.truly_minted and case.mattered_to_score:
        if dispatches:
            # OBSERVE/WARN: the minted write landed on an irreversible DB → 0 prevention.
            return 0.0
        # DEFER/BLOCK: the mutation was WITHHELD → prevention possible.
        return (1.0 - cost) if recovered else (0.0 - cost)
    if case.truly_minted and not case.mattered_to_score:
        # THE DANGEROUS CELL — a true catch that did not matter. Disrupting buys nothing.
        return -cost if not dispatches else 0.0
    # false-flag — no gain; disruption is pure waste.
    return -cost if not dispatches else 0.0


# ---------------------------------------------------------------------------
# The report — frozen, @property rates with div-guard, to_dict (mirror overlap_eval).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InterventionReport:
    """A policy scored over labelled cases — the net-delta ledger + the dangerous-cell rates.

    The grid is split into the ground-truth crosstab (independent of the chosen action) and
    the actuation ledger (what the policy actually DID). The named dangerous cell is
    `actuated_irrelevant` — disruption spent on a true catch the verifier never checked, the
    exact −9 pp.
    """

    n: int
    sum_delta: float
    sum_disruption_cost: float          # accumulated disruption tax over ACTUATED actions
    # ground-truth grid (independent of the chosen action):
    n_true_relevant: int                # truly_minted AND mattered_to_score
    n_true_irrelevant: int              # truly_minted AND NOT mattered (the dangerous-cell denom)
    n_false_flag: int                   # NOT truly_minted
    # actuation ledger (did the chosen action WITHHOLD the turn?):
    n_actuated: int                     # actions where ladder.actuates() (turn at risk)
    n_informed_only: int                # OBSERVE/WARN — turn preserved
    actuated_irrelevant: int            # actuated on a true_irrelevant case (the −9 pp cell)
    actuated_false_flag: int            # actuated on a false_flag
    n_actuated_relevant: int            # actuated on a true_relevant case
    recovered: int                      # actuated true_relevant that recovered

    # --- derived rates (all guard against divide-by-zero) ---

    @property
    def net_task_delta(self) -> float:
        """The HEADLINE — mean net task-delta per case, in verifier-flip units. Directly
        comparable to the live −9 pp (a net regression) / +11 pp (the simulator's win). The
        number the whole §13 double-down is built to maximize."""
        return (self.sum_delta / self.n) if self.n else 0.0

    @property
    def disruption_efficiency(self) -> float:
        """Of the turns the policy ACTUATED (withheld), the fraction that bought a real gain
        (a recovered relevant catch). High = disruption well spent."""
        return (self.recovered / self.n_actuated) if self.n_actuated else 0.0

    @property
    def wasted_disruption_rate(self) -> float:
        """Of the turns the policy ACTUATED, the fraction wasted — spent on a catch that did
        not matter OR on a false flag. THE DANGEROUS-CELL RATE (the `overlap_eval.false_admit
        _rate` analogue): when this policy disrupts, how often is it for nothing? The single
        number the −9 pp came from."""
        if not self.n_actuated:
            return 0.0
        return (self.actuated_irrelevant + self.actuated_false_flag) / self.n_actuated

    @property
    def dangerous_cell_rate(self) -> float:
        """Of all true-but-IRRELEVANT catches, the fraction the policy actuated on — the
        exact −9 pp cell (a sound catch the verifier never checked, disrupted anyway)."""
        return (
            (self.actuated_irrelevant / self.n_true_irrelevant)
            if self.n_true_irrelevant
            else 0.0
        )

    @property
    def coverage(self) -> float:
        """Of all true-RELEVANT mints (a catch that DID matter), the fraction the policy
        actuated on — recall-of-action. A too-timid all-WARN policy scores ~0 here (it never
        withholds), so this is the counterweight to `wasted_disruption_rate`: a good policy
        is high coverage AND low waste."""
        return (
            (self.n_actuated_relevant / self.n_true_relevant)
            if self.n_true_relevant
            else 0.0
        )

    @property
    def net_harmful(self) -> bool:
        """True iff the policy is a net regression (`net_task_delta < 0`). The boolean the
        `dos intervention-eval` exit code rides — the `overlap_eval.leaked` CI-gate analogue
        (a policy that hurts the run fails CI)."""
        return self.net_task_delta < 0.0

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "net_task_delta": round(self.net_task_delta, 4),
            "grid": {
                "true_relevant": self.n_true_relevant,
                "true_irrelevant": self.n_true_irrelevant,
                "false_flag": self.n_false_flag,
            },
            "actuation": {
                "actuated": self.n_actuated,
                "informed_only": self.n_informed_only,
                "actuated_relevant": self.n_actuated_relevant,
                "actuated_irrelevant": self.actuated_irrelevant,
                "actuated_false_flag": self.actuated_false_flag,
                "recovered": self.recovered,
            },
            "rates": {
                "net_task_delta": round(self.net_task_delta, 4),
                "disruption_efficiency": round(self.disruption_efficiency, 4),
                "wasted_disruption_rate": round(self.wasted_disruption_rate, 4),
                "dangerous_cell_rate": round(self.dangerous_cell_rate, 4),
                "coverage": round(self.coverage, 4),
            },
            "sum_disruption_cost": round(self.sum_disruption_cost, 4),
            "net_harmful": self.net_harmful,
        }


def _safe_decision(
    verdict: ProvenanceVerdict, policy: InterventionPolicy, ladder: InterventionLadder
) -> InterventionDecision:
    """Run `choose_intervention` fail-SAFE: any raise degrades to the ladder default (WARN).

    Fail-to-LEAST-DISRUPTIVE — the `overlap_eval` fail-closed-to-floor / `judge_eval`
    fail-to-abstain posture, here as under-intervene. A flaky policy contributes a WARN, not
    a crash, so the report stays honest about it.
    """
    try:
        return choose_intervention(verdict, policy, ladder)
    except Exception:
        spec = ladder.default()
        return InterventionDecision(
            intervention=Intervention(spec.token),
            confidence=Confidence.LOW,
            rung=spec,
            disruption_cost=ladder.disruption_cost(spec.token),
            unsupported=verdict.unsupported,
            reason="fail-safe: policy raised → ladder default",
        )


def score(
    policy: InterventionPolicy,
    cases: Iterable[InterventionCase],
    ladder: InterventionLadder = BASE_INTERVENTIONS,
) -> InterventionReport:
    """Run `policy` over labelled `cases` (via `choose_intervention`) and tabulate the ledger.

    The policy is scored through the SAME `choose_intervention` path the consumer's PEP uses
    (the `overlap_eval._admits` "score under the floor" discipline), so the grid reflects
    exactly what would be ENACTED — fail-safe and all. PURE: reads cases, reads the ladder,
    counts in one pass. The actuation buckets use `ladder.actuates()` (data-driven, never a
    hardcoded `{DEFER, BLOCK}`), so a host-added rung is bucketed by its `dispatches` data.

    Invariant (pinned by a test): `n_actuated == actuated_irrelevant + actuated_false_flag +
    n_actuated_relevant`, and the counts are derived in the same pass as `sum_delta`, so they
    cannot drift apart.
    """
    n = 0
    sum_delta = 0.0
    sum_disruption = 0.0
    n_true_relevant = n_true_irrelevant = n_false_flag = 0
    n_actuated = n_informed_only = 0
    actuated_irrelevant = actuated_false_flag = n_actuated_relevant = recovered = 0

    for case in cases:
        n += 1
        decision = _safe_decision(case.verdict, policy, ladder)
        action = decision.intervention
        actuates = ladder.actuates(action.value)
        delta = _case_delta(case, action, ladder)
        sum_delta += delta

        # ground-truth grid (action-independent)
        if case.truly_minted and case.mattered_to_score:
            n_true_relevant += 1
        elif case.truly_minted:
            n_true_irrelevant += 1
        else:
            n_false_flag += 1

        # actuation ledger (what the policy DID)
        if actuates:
            n_actuated += 1
            sum_disruption += ladder.disruption_cost(action.value)
            if case.truly_minted and case.mattered_to_score:
                n_actuated_relevant += 1
                if case.recovered_if_deferred if action is Intervention.DEFER \
                        else case.recovered_if_blocked:
                    recovered += 1
            elif case.truly_minted:
                actuated_irrelevant += 1
            else:
                actuated_false_flag += 1
        else:
            n_informed_only += 1

    return InterventionReport(
        n=n,
        sum_delta=sum_delta,
        sum_disruption_cost=sum_disruption,
        n_true_relevant=n_true_relevant,
        n_true_irrelevant=n_true_irrelevant,
        n_false_flag=n_false_flag,
        n_actuated=n_actuated,
        n_informed_only=n_informed_only,
        actuated_irrelevant=actuated_irrelevant,
        actuated_false_flag=actuated_false_flag,
        n_actuated_relevant=n_actuated_relevant,
        recovered=recovered,
    )

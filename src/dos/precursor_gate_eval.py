"""The precursor-gate evaluation harness — score a `PrecursorGrammar` by its RECALL vs WASTE.

docs/147 §5/§9.2 — the per-axis eval, the `tool_stream_eval` / `intervention_eval` /
`overlap_eval` / `judge_eval` discipline re-aimed at the precursor-presence axis. Every DOS
axis ships an eval that turns its config from a hunch into a measured, per-deployment decision
(the research-friendliness thesis, docs/90 §2). The precursor gate's config — the
hand-authored `requires` grammar + the `aliases` allow-list — needs exactly that instrument: a
backtest that answers **"on this deployment's real call streams, does the gate catch the
prerequisite-skips that matter without false-REFUTING a precursor that fired under an unlisted
alias?"**

The decisive numbers (the dual of `tool_stream_eval`'s recovered/false-resurface pair):

  * **missed_precursor_recall** — of the calls that ACTUALLY skipped a required precursor (a
    real Missing-Prerequisite-Lookup), the fraction the gate fired REFUTED on. Recall-of-action:
    a grammar that covers too few mutating tools scores low here — it never fires, never catches
    (the grammar-coverage bound docs/147 §1 names). This is the number that tells a host how
    much of *its* mutating surface the declared grammar reaches.
  * **false_refute_rate** — of the calls whose precursor ACTUALLY fired (the lookup was done),
    the fraction the gate WRONGLY fired REFUTED on (because it fired under a name the grammar did
    not list as the precursor or an alias). The dangerous cell — the §3 residual made
    measurable. A false REFUTED is *harmless by design* (the intervention is a WARN that
    preserves the turn — re-surfacing a requirement the agent already met is a no-op nudge), but
    a high rate means the `aliases` allow-list is incomplete and the host should grow it (the
    calibration the R3 rung performs, docs/147 §6).

The honesty stance (the same as the sibling evals)
==================================================

The labels are the RESEARCHER's ground truth, derived from EXECUTED replay, never from the gate:

  * `precursor_required` — did this mutating call ACTUALLY require a precursor per the policy
    PROSE (read by a human / the scorer, not the grammar)? The `overlap_eval.collided` "did it
    actually collide" discipline — the ground truth the grammar is graded AGAINST, never derived
    from the grammar under test.
  * `precursor_actually_fired` — did the agent ACTUALLY call a satisfying precursor (under ANY
    name, listed or not) before this call? The false_refute denominator's truth. A call that
    required a precursor AND fired one is a *correctly-sequenced* call; a REFUTED on it is a
    false fire (the lookup happened under an alias the grammar missed).
  * `mattered_to_score` — did this prerequisite feed a verifier the run was scored on? Carried so
    a host can weight recall by what actually moves the score (the `intervention_eval`
    mattered-axis), never scored directly here.

Everything is **pure**: it consumes already-built `PrecursorCase`s, runs each through the SAME
`precursor_gate.classify_call` the consumer takes (so the grid reflects what would actually fire
— the "score under the floor" discipline), and counts in one pass. No I/O, no host names — it
sits in the kernel layer beside `precursor_gate`.

⚠ This is NOT `arg_provenance`'s detector eval and NOT `intervention_eval`. It measures the
GRAMMAR specifically — does this declared precursor map catch the real skips without
false-REFUTING on an unlisted alias — an axis orthogonal to the mint detector and the actuation
ladder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from dos.evidence import EvidenceStance
from dos.precursor_gate import (
    CallStream,
    MutatingCall,
    PrecursorGrammar,
    PrecursorPolicy,
    classify_call,
)


# ---------------------------------------------------------------------------
# A labelled example — one replayed (mutating call, stream) + ground-truth labels.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PrecursorCase:
    """One replayed mutating call + its prior stream + the ground-truth labels.

    The `stance` the gate assigns is NOT stored — it is DERIVED in `score()` via `classify_call`
    from the embedded `call`/`stream`/grammar, so the scored fire can never drift from a
    hand-labelled stance (the label-drift trap, the sibling-eval discipline). Every other field is
    a researcher ground-truth label from a replay, NOT a guess.

    Fields:
      call                     — the mutating `MutatingCall` under scrutiny.
      stream                   — the `CallStream` of prior calls (the env-authored corpus).
      precursor_required       — ground truth (from the policy PROSE, NOT the grammar under test):
                                 did this call actually require a mandated precursor? The recall
                                 numerator's truth.
      precursor_actually_fired — ground truth: did a satisfying precursor actually fire before this
                                 call, under ANY name (listed or not)? Distinguishes a correctly-
                                 sequenced call (fired) from a real skip (not fired). The
                                 false_refute denominator's truth.
      mattered_to_score        — ground truth: did this prerequisite feed a scored verifier?
                                 (carried for weighting, not scored directly).
      label                    — optional human handle (carried, never scored).
    """

    call: MutatingCall
    stream: CallStream
    precursor_required: bool
    precursor_actually_fired: bool
    mattered_to_score: bool = False
    label: str = ""


# ---------------------------------------------------------------------------
# The report — frozen, @property rates with div-guard, to_dict (mirror tool_stream_eval).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PrecursorEvalReport:
    """A `PrecursorGrammar` scored over labelled cases — the recall ledger + the false-fire rate.

    The grid splits the ground-truth crosstab (independent of the grammar) from the firing ledger
    (what the grammar actually flagged REFUTED). The named dangerous cell is `refuted_on_fired` —
    a REFUTED on a call whose precursor actually fired (an unlisted-alias miss).
    """

    n: int
    # ground-truth grid (grammar-independent):
    n_real_skip: int          # precursor_required AND NOT precursor_actually_fired (the recoverable population)
    n_correctly_sequenced: int  # precursor_required AND precursor_actually_fired (the false-fire denominator)
    # firing ledger (what the grammar did):
    n_refuted: int            # REFUTED assigned
    n_refuted_skip: int       # REFUTED AND a real skip (a useful catch)
    n_refuted_fired: int      # REFUTED AND the precursor actually fired (the dangerous cell)
    n_refuted_skip_mattered: int  # of the useful catches, those that fed a scored verifier

    # --- derived rates (all guard against divide-by-zero) ---

    @property
    def missed_precursor_recall(self) -> float:
        """Of all REAL prerequisite-skips, the fraction the gate fired REFUTED on — the HEADLINE.
        A grammar that covers too few mutating tools scores ~0 (it never fires); growing
        `requires` raises it. The grammar-coverage instrument (docs/147 §1)."""
        return (self.n_refuted_skip / self.n_real_skip) if self.n_real_skip else 0.0

    @property
    def false_refute_rate(self) -> float:
        """Of all CORRECTLY-SEQUENCED calls (the precursor actually fired), the fraction the gate
        WRONGLY fired REFUTED on — THE DANGEROUS-CELL RATE (the
        `tool_stream_eval.false_resurface_rate` / `intervention_eval.wasted_disruption_rate`
        analogue). Harmless by design (a WARN preserving the turn), but a high rate says the
        `aliases` allow-list is incomplete — grow it (the R3 calibration, docs/147 §6)."""
        return (self.n_refuted_fired / self.n_correctly_sequenced) if self.n_correctly_sequenced else 0.0

    @property
    def fire_precision(self) -> float:
        """Of all the calls the gate fired REFUTED on, the fraction that were real skips — how much
        of the firing was well-aimed (vs a false REFUTED on an unlisted alias)."""
        return (self.n_refuted_skip / self.n_refuted) if self.n_refuted else 0.0

    @property
    def mattered_recall(self) -> float:
        """Of all real skips, the fraction the gate caught AND that fed a scored verifier — recall
        weighted by what actually moves the score (the value side of the grammar-coverage bound)."""
        return (self.n_refuted_skip_mattered / self.n_real_skip) if self.n_real_skip else 0.0

    @property
    def net_positive(self) -> bool:
        """True iff the grammar catches more real skips than it false-REFUTES on correctly-sequenced
        calls — the boolean a `dos precursor-gate-eval` exit code could ride (the friendly-direction
        `net_harmful` analogue). A catch is a real nudge toward the scored fix; a false REFUTED is
        harmless-but-noise, so net-positive is `refuted_skip > refuted_fired`."""
        return self.n_refuted_skip > self.n_refuted_fired

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "grid": {
                "real_skip": self.n_real_skip,
                "correctly_sequenced": self.n_correctly_sequenced,
            },
            "firing": {
                "refuted": self.n_refuted,
                "refuted_skip": self.n_refuted_skip,
                "refuted_fired": self.n_refuted_fired,
                "refuted_skip_mattered": self.n_refuted_skip_mattered,
            },
            "rates": {
                "missed_precursor_recall": round(self.missed_precursor_recall, 4),
                "false_refute_rate": round(self.false_refute_rate, 4),
                "fire_precision": round(self.fire_precision, 4),
                "mattered_recall": round(self.mattered_recall, 4),
            },
            "net_positive": self.net_positive,
        }


def score(
    grammar: PrecursorGrammar,
    cases: Iterable[PrecursorCase],
    policy: PrecursorPolicy = PrecursorPolicy(),
    *,
    _classify=classify_call,
) -> PrecursorEvalReport:
    """Run `grammar` over labelled `cases` (via `classify_call`) and tabulate the ledger.

    The grammar is scored through the SAME `classify_call` path the consumer's gate uses (the
    "score under the floor" discipline), so the grid reflects exactly what would FIRE. A call FIRES
    iff its stance is REFUTED (the one actionable stance — ATTESTED/NO_SIGNAL never intervene).
    PURE: reads cases, counts in one pass.

    Invariant (pinned by a test): a call is counted in `n_refuted_skip` / `n_refuted_fired` only if
    it both fired REFUTED AND carried the matching ground-truth label, so the firing ledger never
    exceeds `n_refuted`, and `n_refuted_skip_mattered <= n_refuted_skip`.
    """
    n = 0
    n_real_skip = n_correctly_sequenced = 0
    n_refuted = n_refuted_skip = n_refuted_fired = n_refuted_skip_mattered = 0

    for case in cases:
        n += 1
        verdict = _classify(case.call, case.stream, grammar, policy)
        fired = verdict.stance is EvidenceStance.REFUTED

        real_skip = case.precursor_required and not case.precursor_actually_fired
        correctly_sequenced = case.precursor_required and case.precursor_actually_fired
        if real_skip:
            n_real_skip += 1
        if correctly_sequenced:
            n_correctly_sequenced += 1

        if fired:
            n_refuted += 1
            if real_skip:
                n_refuted_skip += 1
                if case.mattered_to_score:
                    n_refuted_skip_mattered += 1
            if correctly_sequenced:
                n_refuted_fired += 1

    return PrecursorEvalReport(
        n=n,
        n_real_skip=n_real_skip,
        n_correctly_sequenced=n_correctly_sequenced,
        n_refuted=n_refuted,
        n_refuted_skip=n_refuted_skip,
        n_refuted_fired=n_refuted_fired,
        n_refuted_skip_mattered=n_refuted_skip_mattered,
    )

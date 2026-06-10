"""`reconcile` — the quiet-completion gate (docs/168 Concept 3, docs/207 Phase 4).

The picker-boundary closure of the quiet-failure line (docs/149–164). Those docs
DETECT quiet failure *in a trajectory* (a run that narrated success but the world
did not move); `reconcile` is what KEEPS a quietly-incomplete unit in the residual
*across runs* — so the next cycle re-offers it, flagged, instead of believing the
"✅ done" and dropping it. The `job` repo's FQ-336 quiet-DRAIN storm is the
motivating bug: a mere *touch* of a plan doc counted as a ship → a false "all
shipped" → `child_skipped_replan` ×8 re-confirms. A `QUIET_INCOMPLETE` keep would
have caught it: the touch is the agent's self-report, the oracle is ground truth.

It is a JOIN over two verdicts the kernel ALREADY produces — the agent's CLAIM and
the `oracle` verdict (the same `oracle.is_shipped` `verify` answers from git
ancestry, never self-report) — NOT a new sensor. The rule is the intent-ledger
rule (docs/107: a `STEP_CLAIMED` stays, a `STEP_VERIFIED` is what removes work)
generalized to the picker:

  > **Fail-closed on the claim.** The agent's word never REMOVES work; only ground
  > truth does. claim-done ∧ oracle-NOT_SHIPPED → QUIET_INCOMPLETE, KEPT in the
  > residual, flagged.

The three states (mutually exclusive):

  * ``VERIFIED``         — the oracle confirms the unit shipped (ground truth). It
                           leaves the residual. (The claim is irrelevant here — a
                           verified unit is done whether or not the agent claimed it.)
  * ``QUIET_INCOMPLETE`` — the agent CLAIMED done but the oracle says NOT_SHIPPED.
                           The dangerous case: a self-report that, believed, would
                           silently drop real work. KEPT in the residual, FLAGGED so
                           the host routes it (a verifier pass / /replan / a finding).
  * ``HONEST_OPEN``      — the agent did NOT claim done and the oracle says
                           NOT_SHIPPED. Honest unfinished work; stays in the residual
                           with no flag (it is not a quiet failure, just open).

DETECT-and-KEEP, never FIX (docs/164). `reconcile` does not mutate, re-run, or
correct anything — it KEEPS the work alive and FLAGS the divergence; the host owns
the correction. The kernel stays a PDP, never a PEP.

⚓ Pure; the oracle verdict + the claim are gathered at the caller boundary and
handed in (the `oracle.is_shipped` read, the claim parse), exactly like
`completion.classify` is handed its `AncestryFacts`. So the toolathlon scoring
gate (docs/207 Phase 4) replays on the committed corpus offline.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Reconciliation(str, enum.Enum):
    """The typed quiet-completion verdict (docs/168 §3).

    `str`-valued so it round-trips a `--json` token / exit code without a lookup
    table (the `Completion` / `gate_classify.Verdict` idiom). The load-bearing
    asymmetry: only VERIFIED removes the unit from the residual; QUIET_INCOMPLETE
    and HONEST_OPEN both KEEP it (the fail-closed-on-the-claim floor).
    """

    VERIFIED = "VERIFIED"                  # oracle confirms shipped — leaves the residual
    QUIET_INCOMPLETE = "QUIET_INCOMPLETE"  # claimed done BUT oracle says not — KEEP + flag
    HONEST_OPEN = "HONEST_OPEN"            # not claimed + not shipped — honest open work, KEEP

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def keeps_in_residual(self) -> bool:
        """True iff the unit STAYS in the residual (everything but VERIFIED)."""
        return self is not Reconciliation.VERIFIED

    @property
    def is_quiet_failure(self) -> bool:
        """True iff this is the dangerous case — a claim the oracle refutes."""
        return self is Reconciliation.QUIET_INCOMPLETE


@dataclass(frozen=True)
class ReconciliationVerdict:
    """The single verdict `reconcile` returns, with the inputs echoed back.

    ``state`` is the typed `Reconciliation`. ``unit`` is the unit id. ``claimed`` /
    ``oracle_shipped`` are the two inputs the join read (so a surfaced verdict is
    legible). ``reason`` is the operator-facing one-liner. ``flag`` is the routing
    tag a quiet-incomplete carries (``"QUIET_INCOMPLETE"`` so the host can route it),
    empty otherwise.
    """

    state: Reconciliation
    unit: str
    claimed: bool
    oracle_shipped: bool
    reason: str
    flag: str = ""

    @property
    def keeps_in_residual(self) -> bool:
        return self.state.keeps_in_residual

    @property
    def is_quiet_failure(self) -> bool:
        """True iff this is the dangerous case — a claim the oracle refutes."""
        return self.state.is_quiet_failure

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "unit": self.unit,
            "claimed": self.claimed,
            "oracle_shipped": self.oracle_shipped,
            "keeps_in_residual": self.keeps_in_residual,
            "flag": self.flag,
            "reason": self.reason,
        }


def reconcile(
    unit: str,
    *,
    claimed_done: bool,
    oracle_shipped: bool,
) -> ReconciliationVerdict:
    """Reconcile a unit's CLAIM against the ORACLE's ground-truth verdict. PURE.

    ``claimed_done`` is the agent's self-report ("I finished this unit") — gathered
    at the boundary (a `claim_done` tool call, a plan-meta `shipped:` entry, a
    packet disposition). ``oracle_shipped`` is `oracle.is_shipped`'s verdict from
    git ancestry (the non-forgeable rung) — also gathered at the boundary.

    The fail-closed-on-the-claim join (docs/168 §3):

      * oracle_shipped                    → VERIFIED (leaves the residual; the
                                            claim is moot — ground truth confirms it).
      * claimed_done ∧ ¬oracle_shipped    → QUIET_INCOMPLETE (the agent's word would
                                            silently drop real work; KEEP + flag).
      * ¬claimed_done ∧ ¬oracle_shipped   → HONEST_OPEN (honest unfinished work; KEEP,
                                            no flag — not a quiet failure).

    The agent's claim NEVER removes the unit from the residual; only the oracle
    does. Returns a `ReconciliationVerdict`; never raises.
    """
    uid = str(unit)
    if oracle_shipped:
        return ReconciliationVerdict(
            state=Reconciliation.VERIFIED,
            unit=uid,
            claimed=bool(claimed_done),
            oracle_shipped=True,
            reason=(f"oracle confirms {uid} shipped (git ancestry) — verified, "
                    f"leaves the residual"),
        )
    if claimed_done:
        return ReconciliationVerdict(
            state=Reconciliation.QUIET_INCOMPLETE,
            unit=uid,
            claimed=True,
            oracle_shipped=False,
            flag="QUIET_INCOMPLETE",
            reason=(
                f"{uid} was CLAIMED done but the oracle says NOT_SHIPPED — a quiet "
                f"failure; KEPT in the residual and flagged (the claim is a "
                f"self-report; only ground truth removes work). Route to a verifier "
                f"pass / /replan / a finding — do NOT believe the claim"
            ),
        )
    return ReconciliationVerdict(
        state=Reconciliation.HONEST_OPEN,
        unit=uid,
        claimed=False,
        oracle_shipped=False,
        reason=(f"{uid} is not claimed and not shipped — honest open work; stays in "
                f"the residual (not a quiet failure)"),
    )

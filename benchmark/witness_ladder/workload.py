"""workload.py — the synthetic claim/ground-truth distribution the rung sweep runs over.

docs/261 P1. The $0 prototype's *fixed substrate*: a declared, auditable mix of
trajectory outcomes. The witness RUNG is the swept variable (harness.py); this
distribution is held constant so the rung is the only thing that moves the verdict.

Each `Task` is a synthetic trajectory reduced to the two facts the kernel verdict
needs, plus the one ground-truth bit a witness would read:

  claim_present  — did the trajectory make a checkable "resolved/done" claim?
                   (the FORGEABLE bit a host extractor produces; on its own it can
                   never grant ACCEPT — `believe_under_floor`.)
  effect_true    — did the effect ACTUALLY happen? (ground truth; what a
                   non-forgeable witness reads back. The agent authors 0 bytes of
                   this — it is the env's DB-hash / exit code / ledger.)
  wants_witness  — IF this task abstains for lack of a strong witness, which
                   witness would convert it? (the roadmap label, docs/192 ladder.)

The three outcome classes that matter (the rest are non-candidates):

  HONEST_TRUE   claim_present & effect_true   -> a strong witness should ACCEPT it.
  OVER_CLAIM    claim_present & !effect_true  -> a strong witness should REJECT_POISON
                                                 it; a weak witness can only ABSTAIN.
                                                 THIS is the slice the value rides on.
  HONEST_NONE   !claim_present                -> NO_CLAIM at every rung (nothing to
                                                 bank, nothing to purge).

The mix is declared as data so the run is reproducible and the denominator is
legible (no `Math.random` — the harness builds the distribution deterministically
from these counts; varying a run means editing the mix here, on purpose).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# The witness-want vocabulary — which witness an abstaining task is asking for.
# This is the docs/192 world-state ladder read as a backlog (docs/261 roadmap
# table). A task tagged here means: "the only way to rule on me is a witness of
# THIS kind." Grouping the abstain band by this label IS the generated roadmap.
# ---------------------------------------------------------------------------
WANT_PRESENCE = "presence"          # "a file/record changed" — git ancestry (W2). EXISTS.
WANT_STATE_INVARIANT = "state_invariant"  # money/inventory/reservation hash (W3). EXISTS (tau2/agentdiff).
WANT_CONTENT_DIFF = "content_diff"  # "the value is RIGHT not just changed" (W3). GROWTH TARGET.
WANT_PROVIDER_LEDGER = "provider_ledger"  # external-effect, different principal (W3). DRIVER-SHAPED, UNBUILT.
WANT_JUDGE = "judge"                # judgment/quality/taste — IRREDUCIBLE, punts to JUDGE/HUMAN.

# Buildable vs irreducible — the load-bearing split (docs/261): the roadmap is
# finite because some of the band is engineering and some is the trust ladder
# working as designed. A `status` table separates the two so the backlog is not a
# treadmill.
BUILDABLE_WANTS = {WANT_PRESENCE, WANT_STATE_INVARIANT, WANT_CONTENT_DIFF, WANT_PROVIDER_LEDGER}
IRREDUCIBLE_WANTS = {WANT_JUDGE}


@dataclass(frozen=True)
class Task:
    """One synthetic trajectory, reduced to the facts the rung sweep needs."""
    task_id: str
    claim_present: bool
    effect_true: bool          # ground truth — what a non-forgeable witness reads
    wants_witness: str         # the roadmap label (which witness would rule on it)
    note: str = ""             # one-line human description (operator surface only)

    @property
    def is_over_claim(self) -> bool:
        """A present claim that is in fact wrong — the slice value rides on."""
        return self.claim_present and not self.effect_true

    @property
    def is_honest_true(self) -> bool:
        return self.claim_present and self.effect_true

    @property
    def is_claim_bearing(self) -> bool:
        return self.claim_present


# ---------------------------------------------------------------------------
# The declared mix. Counts, not coin flips — the denominator is auditable and the
# run is reproducible. The proportions echo the LIVE results so the synthetic
# curve is anchored to reality, not invented:
#   * over-claim rate among claim-bearing tasks ~ the docs/228 live band
#     (5.8% whole-distribution / ~13.6% write-heavy). We use a write-heavy-ish mix
#     here (the regime where the gate pays) and report the rate so it is honest.
#   * the wants_witness spread echoes the docs/204 §3 honest floor:
#     62% persisted-state (presence/state_invariant) / 21% external-effect
#     (provider_ledger) / 17% judge-only.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MixSpec:
    """A reproducible distribution spec: how many of each (outcome x wanted-witness)."""
    # (claim_present, effect_true, wants_witness, count)
    rows: tuple = field(default_factory=tuple)

    def build(self) -> List[Task]:
        out: List[Task] = []
        i = 0
        for claim, eff, want, n in self.rows:
            for _ in range(n):
                i += 1
                out.append(Task(
                    task_id=f"t{i:03d}",
                    claim_present=bool(claim),
                    effect_true=bool(eff),
                    wants_witness=want,
                    note=f"claim={claim} effect_true={eff} wants={want}",
                ))
        return out


# The default prototype distribution (docs/261 P1). 100 tasks.
#  - claim-bearing tasks dominate (the write-heavy regime where the gate pays).
#  - among claim-bearing, ~14% are over-claims (anchored to the docs/228 write-heavy band).
#  - the wanted-witness spread is the docs/204 §3 honest floor, so the abstain band
#    at the floor and the roadmap decomposition are realistic, not invented.
DEFAULT_MIX = MixSpec(rows=(
    # honest-true claims (admitted by a strong witness; abstained at the floor) — by wanted witness
    (True,  True,  WANT_PRESENCE,         18),
    (True,  True,  WANT_STATE_INVARIANT,  22),
    (True,  True,  WANT_CONTENT_DIFF,     10),
    (True,  True,  WANT_PROVIDER_LEDGER,  8),
    (True,  True,  WANT_JUDGE,            6),
    # over-claims (REJECT_POISON by a strong witness; ABSTAIN at the floor) — the value slice
    (True,  False, WANT_PRESENCE,         2),
    (True,  False, WANT_STATE_INVARIANT,  5),
    (True,  False, WANT_CONTENT_DIFF,     3),
    (True,  False, WANT_PROVIDER_LEDGER,  1),
    (True,  False, WANT_JUDGE,            1),
    # no-claim trajectories (NO_CLAIM at every rung; the honest non-candidates)
    (False, True,  WANT_STATE_INVARIANT,  9),
    (False, False, WANT_STATE_INVARIANT,  6),
))


def default_tasks() -> List[Task]:
    return DEFAULT_MIX.build()

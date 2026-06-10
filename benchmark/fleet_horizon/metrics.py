"""The four metrics — computed identically over both arms' event logs.

Both arms emit a list of `Event`s. The metrics are pure functions over that log,
so the SAME code scores both arms (no per-arm scoring that could tilt the A/B).
The arms differ only in which events they *produce* — e.g. the open loop never
produces a `refused-write` because it never arbitrates; the closed loop never
*banks* a lie because the oracle catches it first.

Cost model: a flat `COST_PER_ACTION` per worker action (attempt, rework,
thrash). Deliberately uniform across arms so metric 4 (verified-shipped per
dollar) prices the closed loop's verification overhead fairly — every oracle
call and every refusal-then-retry is itself an action that costs money. (§6.2
steelman demand: do not give the closed loop free verification.)
"""
from __future__ import annotations

import dataclasses


COST_PER_ACTION = 1.0   # one "unit" — read as cents, tokens, or seconds; uniform

# --- the INTEGRITY-axis defect debt (the original metric) ---
# Downstream-remediation cost of ONE undetected defect, per remaining-horizon
# step it corrupts. A lie/overwrite banked at phase k of an M-phase effort lets
# (M-k) later phases build on a false foundation; when the defect surfaces (it
# does, on a long horizon), that downstream work is rebuilt. This multiplier
# prices that. It is deliberately CONSERVATIVE (1.0 = "one redo per corrupted
# downstream phase") — the real cost of integrating on a lie is usually worse.
# The closed loop banks no lies, so it carries ZERO of this debt; that is the
# whole point, and it is a property of the open loop's OWN output (§6.2 honesty),
# not a scoring thumb on the scale. Set to 0.0 to recover the raw (defect-blind)
# verified-per-$ where the closed loop's upfront safety cost looks like pure tax.
REMEDIATION_PER_CORRUPTED_STEP = 1.0

# --- the VELOCITY-axis parameters (docs/81 §2, §4) ---
# κ (kappa): the merge-conflict DETONATION multiplier (docs/81 §2.2). A silent
# overwrite the open loop banks surfaces later as a hand-merge costing κ× a normal
# action. SWEPT, never picked: the headline is the BREAK-EVEN κ at which the arms
# cross, compared to the published merge-cost literature (Ghiotto 10-20%, AgenticFlict
# 27.67%, super-linear-in-divergence). Default 5.0 = a hand-merge ≈ 5 actions; the
# real curve is reported, not this scalar.
DEFAULT_KAPPA = 5.0

# μ (review_mu): the human review-queue SERVICE rate (docs/81 §2.3), in
# reviews-per-action-of-fleet-time. Drives the M/M/1 wait estimate ρ/(1−ρ)·(1/μ).
# Because absolute wait depends on the CONSUMER's μ, the load-bearing headline is
# human-review FRACTION (model-free), and wait is reported as a function of μ so a
# skeptic plugs in their own. Default chosen so a single human keeps pace with ~1
# review per 3 fleet-actions.
DEFAULT_REVIEW_MU = 0.33

# Cost of one human review action (when something reaches the human queue).
COST_PER_REVIEW = 1.0


@dataclasses.dataclass(frozen=True)
class Event:
    kind: str          # see KINDS below
    effort: str
    phase_id: str
    detail: str = ""


# Event vocabulary (a small closed set, like the kernel's own enums):
#   banked-shipped   — arm accepted a phase as shipped (open: believed; closed: oracle-confirmed)
#   banked-lie       — arm accepted as shipped a phase that did NOT really commit (open loop only)
#   caught-lie       — arm REJECTED a claimed-shipped phase the oracle proved false (closed loop)
#   real-ship        — a phase that really committed (ground truth, both arms)
#   silent-overwrite — a write clobbered another effort's concurrent write, undetected (open loop)
#   refused-write    — the arbiter refused/deferred a colliding write (closed loop)
#   rework           — re-did an already-shipped phase (waste, both arms)
#   thrash           — burned an action with no progress (busy-wait, both arms)
#   action           — any costed worker action (emitted for every attempt/retry/thrash)
#   --- velocity axis (docs/81 §4) ---
#   conflict-detonation — a banked silent-overwrite's downstream hand-merge (open loop);
#                         charged κ·COST_PER_ACTION (the §2.2 merge tax)
#   human-review     — a banked "done" that entered the human review queue. Open loop:
#                       EVERY banked "done" (nothing adjudicated completeness → 100%).
#                       Closed loop: only kernel-surfaced EXCEPTIONS (caught lie / refusal).
#   --- orchestrator axis (docs/98) ---
#   detected-collision — a shared-state collision the arbiter did NOT prevent at
#                        contention (because a foreign orchestrator's lease-visibility
#                        LAGGED) and that was instead caught AFTER both writes landed.
#                        The DOS-native loop emits `refused-write` (prevented) where a
#                        lagging harness emits `detected-collision` (detected). The
#                        discriminator metric for the orchestrator axis: same trust
#                        intent, different point in time the collision is caught.
KINDS = {
    "banked-shipped", "banked-lie", "caught-lie", "real-ship",
    "silent-overwrite", "refused-write", "rework", "thrash", "action",
    "conflict-detonation", "human-review", "detected-collision",
}


@dataclasses.dataclass
class Metrics:
    arm: str
    total_phases: int
    banked_shipped: int      # what the arm BELIEVES shipped
    banked_lies: int         # falsehoods the arm banked (open loop's undetected debt)
    caught_lies: int         # falsehoods the arm rejected (closed loop's catch)
    real_ships: int          # ground-truth real commits
    silent_overwrites: int   # undetected data loss
    refused_writes: int      # collisions the arbiter prevented
    rework: int
    thrash: int
    total_cost: float
    horizon: int = 1         # phases per effort (M) — for the defect-debt model
    defect_debt: float = 0.0  # downstream remediation owed by undetected defects
    # --- velocity axis (docs/81) ---
    human_reviews: int = 0    # banked "done"s that entered the human review queue
    conflict_detonations: int = 0  # banked overwrites that surfaced as hand-merges
    kappa: float = DEFAULT_KAPPA
    review_mu: float = DEFAULT_REVIEW_MU
    # --- orchestrator axis (docs/98) ---
    detected_collisions: int = 0  # collisions caught AFTER the fact (lease lag) —
                                  # the arbiter would have PREVENTED these in-process

    # --- derived ---
    @property
    def lie_rate(self) -> float:
        """Share of BANKED-shipped that were actually false. The headline.

        Open loop: banked lies / banked shipped (the corruption it carries).
        Closed loop: should be ~0 — the oracle refuses to bank what didn't ship.
        """
        if self.banked_shipped == 0:
            return 0.0
        return self.banked_lies / self.banked_shipped

    @property
    def verified_shipped_per_dollar(self) -> float:
        """Oracle-confirmable real ships per unit spend — RAW (defect-blind).

        Uses REAL ships (ground truth), NOT banked — so the open loop gets no
        credit for lies it banked, and the closed loop is charged for every
        verification + retry action. This is the metric §6.2 demands: it prices
        verification overhead in. On this raw number the closed loop often looks
        WORSE (it pays upfront for safety) — which is the honest tension, and
        exactly why the defect-adjusted number below exists.
        """
        if self.total_cost == 0:
            return 0.0
        return self.real_ships / self.total_cost

    @property
    def defect_adjusted_cost(self) -> float:
        """Total spend PLUS the downstream remediation the undetected defects owe.

        The open loop's banked lies + silent overwrites each corrupt the remaining
        horizon; `defect_debt` (computed in `score`) is the rebuild cost. The
        closed loop banks no lies and suffers no overwrites, so its debt is ~0 and
        this equals its raw cost. This is where horizon bites: the debt grows with
        (M - k) for a defect at phase k, so a long horizon makes the open loop's
        true cost diverge from its raw cost.
        """
        return self.total_cost + self.defect_debt

    @property
    def defect_adjusted_verified_per_dollar(self) -> float:
        """Real ships per TRUE cost (spend + downstream remediation). The honest
        long-horizon denominator — the number the cluster never quantified."""
        c = self.defect_adjusted_cost
        if c == 0:
            return 0.0
        return self.real_ships / c

    @property
    def banked_integrity(self) -> float:
        """Share of what the arm banked that is TRUE. 1.0 = no corruption."""
        if self.banked_shipped == 0:
            return 1.0
        return 1.0 - self.lie_rate

    # --- velocity axis (docs/81 §2-§4) ---
    @property
    def human_review_fraction(self) -> float:
        """Share of banked "done" that needed a HUMAN to confirm (docs/81 §2.3-§2.4).

        The load-bearing velocity headline because it is MODEL-FREE (no assumed μ).
        Open loop: 1.0 — nothing adjudicated completeness, so every "done" must be
        human-confirmed. Closed loop: only kernel-surfaced exceptions reach a human
        (caught lies + refusals), so it is ≈ the lie+refusal rate ≪ 1. This is the
        Faros-paradox lever: shrink the arrival rate into the human queue."""
        if self.banked_shipped == 0:
            return 0.0
        return self.human_reviews / self.banked_shipped

    @property
    def conflict_cost(self) -> float:
        """The κ-priced hand-merge tax for banked silent overwrites (docs/81 §2.2)."""
        return self.conflict_detonations * self.kappa * COST_PER_ACTION

    @property
    def review_cost(self) -> float:
        """The cost of the human reviews this arm forced into the queue."""
        return self.human_reviews * COST_PER_REVIEW

    @property
    def loaded_cost(self) -> float:
        """FULLY-LOADED cost: generation + verification + the downstream bill
        (conflict detonations + human review). docs/81 §4's denominator. The open
        loop's loaded cost balloons because its corruption + 100% review fraction
        are now priced; the closed loop pays prevention + a small exception queue."""
        return self.total_cost + self.conflict_cost + self.review_cost

    @property
    def verified_velocity_per_dollar(self) -> float:
        """THE velocity headline (docs/81 §4): oracle-confirmed real ships per
        FULLY-LOADED dollar (generation + verification + conflict + review bill).
        The number no published benchmark reports. Same real ships in both arms;
        the arms differ only in the loaded cost of getting there."""
        c = self.loaded_cost
        if c == 0:
            return 0.0
        return self.real_ships / c

    # --- orchestrator axis (docs/98) ---
    @property
    def collisions_total(self) -> int:
        """All shared-state collisions this arm hit, however they were caught —
        prevented at contention (`refused_writes`) PLUS detected after the fact
        (`detected_collisions`). The sum is a property of the WORKLOAD (same in
        both orchestrators on the same seed); the SPLIT is the orchestrator's."""
        return self.refused_writes + self.detected_collisions

    @property
    def prevention_rate(self) -> float:
        """Share of collisions PREVENTED at contention vs detected after the fact.

        The orchestrator-axis headline. A DOS-native loop (or a harness that writes
        its leases back) prevents every collision → 1.0. A naive harness whose lease
        visibility lags detects them post-hoc → < 1.0, and each detected collision
        risks a surviving silent overwrite verify cannot undo. Vacuously 1.0 when
        there were no collisions at all (the disjoint-workload falsifier)."""
        if self.collisions_total == 0:
            return 1.0
        return self.refused_writes / self.collisions_total

    def mean_review_wait(self, mu: float | None = None) -> float:
        """M/M/1 review-queue wait estimate (docs/81 §2.3, Kingman ρ/(1−ρ)·1/μ).

        ρ = arrival rate / μ, with arrival rate = human_reviews / total_cost
        (reviews per unit fleet time). Open loop drives ρ→1 (everything reviewed)
        so wait explodes super-linearly; closed loop keeps ρ low (exceptions only).
        Reported as a FUNCTION of the consumer's μ, never a single rigged scalar.
        Returns float('inf') when the queue is saturated (ρ ≥ 1) — the honest
        'non-stationary, unbounded wait' regime docs/81 §2.3 names."""
        mu = self.review_mu if mu is None else mu
        if self.total_cost == 0 or mu <= 0:
            return 0.0
        arrival = self.human_reviews / self.total_cost
        rho = arrival / mu
        if rho >= 1.0:
            return float("inf")
        return (rho / (1.0 - rho)) * (1.0 / mu)

    def to_row(self) -> dict:
        return {
            "arm": self.arm,
            "phases": self.total_phases,
            "banked_shipped": self.banked_shipped,
            "banked_lies": self.banked_lies,
            "caught_lies": self.caught_lies,
            "real_ships": self.real_ships,
            "silent_overwrites": self.silent_overwrites,
            "refused_writes": self.refused_writes,
            "rework": self.rework,
            "thrash": self.thrash,
            "cost": round(self.total_cost, 1),
            "defect_debt": round(self.defect_debt, 1),
            "true_cost": round(self.defect_adjusted_cost, 1),
            "lie_rate": round(self.lie_rate, 4),
            "banked_integrity": round(self.banked_integrity, 4),
            "verified_per_$": round(self.verified_shipped_per_dollar, 4),
            "defect_adj_verified_per_$": round(self.defect_adjusted_verified_per_dollar, 4),
            # --- velocity axis ---
            "human_reviews": self.human_reviews,
            "human_review_fraction": round(self.human_review_fraction, 4),
            "conflict_detonations": self.conflict_detonations,
            "loaded_cost": round(self.loaded_cost, 1),
            "verified_velocity_per_$": round(self.verified_velocity_per_dollar, 4),
            "review_wait": round(self.mean_review_wait(), 3) if self.mean_review_wait() != float("inf") else "inf",
            # --- orchestrator axis (docs/98) ---
            "detected_collisions": self.detected_collisions,
            "collisions_total": self.collisions_total,
            "prevention_rate": round(self.prevention_rate, 4),
        }


def _phase_index(phase_id: str) -> int:
    """Recover the 0-based phase index k from a phase id like 'E03.07' → 7."""
    try:
        return int(phase_id.rsplit(".", 1)[1])
    except (IndexError, ValueError):
        return 0


def score(arm: str, events: list[Event], *, total_phases: int, horizon: int = 1,
          kappa: float = DEFAULT_KAPPA, review_mu: float = DEFAULT_REVIEW_MU) -> Metrics:
    """Pure scoring over an event log. Same function for both arms.

    `horizon` (M, phases per effort) drives the defect-debt model: an undetected
    defect banked at phase k owes `REMEDIATION_PER_CORRUPTED_STEP * (M-1-k)` —
    the downstream phases that built on the false foundation and get rebuilt when
    it surfaces. Summed over all banked lies + silent overwrites. The closed loop
    banks none, so its debt is 0 — a property of the open loop's OWN output.

    `kappa`/`review_mu` parameterize the velocity axis (docs/81): the conflict
    detonation multiplier and the review-queue service rate. Both are SWEPT by the
    harness, never picked to win — the headlines are the break-even κ and the
    model-free human-review fraction.
    """
    c = {k: 0 for k in KINDS}
    debt = 0.0
    for e in events:
        if e.kind in c:
            c[e.kind] += 1
        if e.kind in ("banked-lie", "silent-overwrite"):
            corrupted_downstream = max(0, (horizon - 1) - _phase_index(e.phase_id))
            debt += REMEDIATION_PER_CORRUPTED_STEP * corrupted_downstream
    return Metrics(
        arm=arm,
        total_phases=total_phases,
        banked_shipped=c["banked-shipped"],
        banked_lies=c["banked-lie"],
        caught_lies=c["caught-lie"],
        real_ships=c["real-ship"],
        silent_overwrites=c["silent-overwrite"],
        refused_writes=c["refused-write"],
        rework=c["rework"],
        thrash=c["thrash"],
        total_cost=c["action"] * COST_PER_ACTION,
        horizon=horizon,
        defect_debt=debt,
        human_reviews=c["human-review"],
        conflict_detonations=c["conflict-detonation"],
        kappa=kappa,
        review_mu=review_mu,
        detected_collisions=c["detected-collision"],
    )

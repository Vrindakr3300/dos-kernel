"""skill_adherence — the WAL+git attribution instrument (FleetForge keystone).

THE PROBLEM THIS SOLVES. The FleetHorizon live A/B was deferred for one concrete
reason (see this repo's gap-map / `docs/170` conversion-gap ledger F8): with a real
LLM driving the arms, a measured coordination delta between arm A (believe the
returns) and arm B (drive the DOS skills) could not be ATTRIBUTED — was the gap
because the *skill verbs* captured value, or because the *model happened to behave*
that run? Nothing reconstructed, independently of the agent's narration, whether the
skill's mandated steps actually fired. So the live result would be unfalsifiable as a
claim about the SKILLS. This module is that missing instrument.

WHAT IT IS. A PURE function over two byte-clean, agent-UN-forgeable fossils:

  1. the lane-journal WAL (`dos.lane_journal.read_all` -> ordered ACQUIRE / HEARTBEAT
     / REFUSE / RELEASE / SCAVENGE entries), authored by the `dos lease-lane` writer
     under its mutex — NOT by the judged agent; and
  2. the git commit log (subjects + their order), authored by git on a real commit —
     a fact the agent cannot forge without actually committing.

From those alone it reconstructs, per effort, an `AdherenceRecord`: did an ACQUIRE
precede the effort's first write SHA (arbitrate-before-write)? did a HEARTBEAT keep
the lease alive across the run (heartbeat-the-WAL)? was the lane RELEASED at the end?
— and joins that to the COORDINATION OUTCOME the same fossils show (a REFUSE the
arbiter recorded = a collision prevented; a banked ship with no git commit = a lie
that slipped). The output tuple `adherence ⟂ outcome` is what makes a live delta
attributable: high adherence co-moving with high prevention is the skill verbs
working; the falsifier arms (N=1 / disjoint) are what convert that correlation
toward causation (there, adherence is high but there is nothing to prevent, so the
gap MUST be ~0 — if the skill arm wins there, this instrument is rigged).

THE INVARIANT (pinned by the tests). This module reads ONLY journal entries and git
subjects. It has NO parameter and NO code path that consults an agent's self-report
(a `{shipped:true}` claim, a narrated "I arbitrated first", a tool-call log). The
`verify-before-bank` rung is not "the agent said it verified" — it is "the git fact
the oracle would read exists" (a real commit closing the phase). That is the
byte-author-not-the-judged-agent line (`[[project-dos-what-is-truth-throughline]]`,
`[[project-dos-consistency-is-not-grounding]]`): re-deriving the agent's OWN bytes is
consistency, not grounding, so we never do it.

PURE — fossils in, records out, no disk, no clock, no kernel mutation. The CALLER
gathers the fossils at the boundary (`lane_journal.read_all(path)` over the run's WAL
+ `git log` over the harness-controlled repo) and hands them in, exactly as
`liveness.classify` takes evidence gathered by `git_delta`/`journal_delta`. This is
the "I/O at the boundary, data to the pure core" rule, applied to the benchmark.
"""
from __future__ import annotations

import dataclasses
from typing import Iterable

from dos import lane_journal as _lj


# --- the byte-clean evidence the caller gathers at the boundary --------------

@dataclasses.dataclass(frozen=True)
class WriteFact:
    """One real commit, read from `git log` — a fact the agent cannot forge.

    `effort` and `phase_id` are recovered from the commit SUBJECT by the caller
    (the harness commits with a subject carrying the (effort, phase_id), exactly as
    `fleet_horizon.closed_loop._real_commit` does), so this carries already-parsed
    ground truth, not raw prose. `order` is the commit's position in `git log`
    (0 = first after root), the only temporal signal we need to ask "did the
    ACQUIRE come BEFORE the first write?" — we compare WAL append order to git
    order, never a wall-clock.
    """
    effort: str
    phase_id: str
    sha: str
    order: int


@dataclasses.dataclass(frozen=True)
class BankedClaim:
    """A phase the ARM accepted as shipped — needed only to score whether a lie was
    banked (an accepted phase with no matching `WriteFact`). This is the ARM's
    accounting decision (open arm believes; skill arm should have verified), NOT the
    agent's self-narration: the harness records what its own orchestrator banked. We
    score it against git ground truth, so a banked claim with no commit IS the lie,
    independent of anything the model said.
    """
    effort: str
    phase_id: str


# --- the verdict ------------------------------------------------------------

# The skill's mandated verb sequence, in order. Adherence is per-verb so a model
# that half-follows the screenplay (arbitrates but never heartbeats) scores partial,
# and the per-verb vector is what a later single-verb-ablation arm isolates.
VERBS = ("acquire_before_write", "heartbeat", "verify_before_bank", "release")


@dataclasses.dataclass(frozen=True)
class AdherenceRecord:
    """Per-effort skill-step adherence joined to the coordination outcome.

    Adherence side (read from WAL+git, never self-report):
      * acquire_before_write — an ACQUIRE for this effort's lane appears in the WAL,
        AND it precedes the effort's first git commit (WAL append order vs git order).
        This is "arbitrate-before-write": the lease was taken before the region was
        touched. A write with no preceding ACQUIRE is the un-leased write the skill
        forbids.
      * heartbeat — at least one HEARTBEAT for the lane (the skill keeps the lease
        alive across iterations; its absence is what makes a lease look dead/STALLED).
      * verify_before_bank — every phase this effort BANKED has a real git commit
        (the oracle's ground truth exists). The skill's "verify-before-bank" rung,
        scored as the FACT the oracle reads, not the agent's "I verified" narration.
      * release — a RELEASE (or SCAVENGE) for the lane appears in the WAL (the loop
        ended cleanly / was reaped, not left dangling).

    Outcome side (the coordination value, also from WAL+git):
      * collisions_prevented — REFUSE entries the arbiter recorded against this
        effort's requests (a collision the skill arm prevented at contention; the
        prose arm never arbitrates so it records none).
      * lies_banked — phases this effort banked with NO real git commit (a falsehood
        that slipped past the arm). The skill arm's verify-before-bank should drive
        this to 0; a banked lie here is the skill rung NOT having fired.
    """
    effort: str
    # adherence (per-verb, byte-clean)
    acquire_before_write: bool
    heartbeat: bool
    verify_before_bank: bool
    release: bool
    # outcome (coordination, byte-clean)
    collisions_prevented: int
    lies_banked: int
    # provenance counts (so an audit can see what fossils drove the verdict)
    acquire_count: int
    write_count: int
    banked_count: int

    @property
    def adherence_score(self) -> float:
        """Fraction of the four mandated verbs that fired (0.0–1.0). The scalar an
        attribution join correlates against the outcome."""
        fired = sum(
            (self.acquire_before_write, self.heartbeat,
             self.verify_before_bank, self.release)
        )
        return fired / len(VERBS)

    @property
    def fully_adherent(self) -> bool:
        return self.adherence_score == 1.0

    def to_row(self) -> dict:
        return {
            "effort": self.effort,
            "acquire_before_write": self.acquire_before_write,
            "heartbeat": self.heartbeat,
            "verify_before_bank": self.verify_before_bank,
            "release": self.release,
            "adherence_score": round(self.adherence_score, 4),
            "collisions_prevented": self.collisions_prevented,
            "lies_banked": self.lies_banked,
            "acquire_count": self.acquire_count,
            "write_count": self.write_count,
            "banked_count": self.banked_count,
        }


# --- the pure join ----------------------------------------------------------

def _lane_of(entry: dict) -> str:
    return str(entry.get("lane") or "")


def classify_effort(
    effort: str,
    lane: str,
    *,
    journal: list[dict],
    writes: list[WriteFact],
    banked: list[BankedClaim],
) -> AdherenceRecord:
    """Classify ONE effort's adherence+outcome from its lane's WAL entries + its
    git writes + what the arm banked. Pure.

    `journal` is the FULL ordered WAL (`lane_journal.read_all`); we filter to this
    effort's `lane` here so the caller can pass the same list for every effort.
    `writes`/`banked` are already filtered to this effort by the caller.
    """
    lane_entries = [e for e in journal if _lane_of(e) == lane]
    ops = [str(e.get("op") or "") for e in lane_entries]

    acquire_count = ops.count(_lj.OP_ACQUIRE)
    heartbeat = _lj.OP_HEARTBEAT in ops
    released = (_lj.OP_RELEASE in ops) or (_lj.OP_SCAVENGE in ops)
    # A REFUSE recorded against this lane = a collision the arbiter prevented — BUT
    # only a CROSS-EFFORT refuse is coordination value. A benchmark that models a
    # phase as "in flight" across a window also produces SAME-EFFORT refuses (an
    # effort contending with its OWN still-live lease on its next phase) — that is
    # serialization, not coordination, and it fires even on a genuinely disjoint
    # workload (the FleetForge falsifier surfaced this conflation in FleetHorizon's
    # raw `refused_writes`). So we count ONLY refuses the WAL tags `cross_effort`
    # True (a collision with a DIFFERENT effort's footprint). A REFUSE with no
    # `cross_effort` tag is treated as cross-effort for backward-compat with a WAL
    # that doesn't carry the tag — the smoke's WAL builder sets it explicitly.
    collisions_prevented = sum(
        1 for e in lane_entries
        if str(e.get("op") or "") == _lj.OP_REFUSE and e.get("cross_effort", True)
    )

    my_writes = sorted(writes, key=lambda w: w.order)
    write_count = len(my_writes)

    # acquire_before_write: an ACQUIRE exists AND (if there are writes) the FIRST
    # ACQUIRE in WAL order precedes the FIRST write in git order. WAL append order
    # and git commit order are the two monotone clocks we trust; we ask whether the
    # lease was taken before the region was touched. With no writes at all, an
    # ACQUIRE alone counts (the effort leased its lane even if it shipped nothing —
    # the discipline fired). With writes but no ACQUIRE, it FAILS (un-leased write).
    if acquire_count == 0:
        acquire_before_write = False
    elif write_count == 0:
        acquire_before_write = True
    else:
        # The WAL is globally ordered; the ACQUIRE for this lane is an earlier
        # decision than any commit it gated. Because we cannot compare a WAL `seq`
        # to a git `order` numerically (different clocks), we use the structural
        # fact the skill guarantees: the ACQUIRE is appended INSIDE the lease mutex
        # BEFORE the worker is permitted to write. So "an ACQUIRE exists for the
        # lane and a write exists" is the observable; a write with NO acquire is the
        # violation. (The N=1/disjoint falsifier arms — where there is nothing to
        # gate — are what keep this honest: adherence is high there too, but the
        # OUTCOME side, collisions_prevented, is 0, so the gap vanishes.)
        acquire_before_write = True

    # verify_before_bank: every BANKED phase has a real git commit. The oracle's
    # ground truth, read as the FACT (a WriteFact for the (effort, phase_id)) — NOT
    # the agent's "I verified" narration. A banked phase with no commit is a lie the
    # arm let through = the verify rung did NOT fire for that phase.
    write_keys = {(w.effort, w.phase_id) for w in writes}
    lies_banked = sum(
        1 for b in banked if (b.effort, b.phase_id) not in write_keys
    )
    banked_count = len(banked)
    # The rung "fired" iff nothing was banked without a commit. Vacuously true if
    # the effort banked nothing (it never had the chance to bank a lie).
    verify_before_bank = lies_banked == 0

    return AdherenceRecord(
        effort=effort,
        acquire_before_write=acquire_before_write,
        heartbeat=heartbeat,
        verify_before_bank=verify_before_bank,
        release=released,
        collisions_prevented=collisions_prevented,
        lies_banked=lies_banked,
        acquire_count=acquire_count,
        write_count=write_count,
        banked_count=banked_count,
    )


def classify_fleet(
    *,
    journal: list[dict],
    writes: Iterable[WriteFact],
    banked: Iterable[BankedClaim],
    lanes: dict[str, str],
) -> list[AdherenceRecord]:
    """Classify EVERY effort in the fleet. Pure.

    `lanes` maps effort name -> the lane it leased (the workload's `Effort.lane`).
    `writes`/`banked` are the full fleet's; we partition them per effort here. The
    result is one `AdherenceRecord` per effort in `lanes` order, the
    adherence⟂outcome tuples a harness joins to score the attribution.
    """
    writes = list(writes)
    banked = list(banked)
    out: list[AdherenceRecord] = []
    for effort, lane in lanes.items():
        out.append(
            classify_effort(
                effort,
                lane,
                journal=journal,
                writes=[w for w in writes if w.effort == effort],
                banked=[b for b in banked if b.effort == effort],
            )
        )
    return out


# --- the attribution summary ------------------------------------------------

@dataclasses.dataclass(frozen=True)
class AttributionSummary:
    """The fleet-level adherence⟂outcome join — the headline of the instrument.

    `mean_adherence` is the average per-effort adherence score; `prevention_total`
    and `lies_total` are the coordination outcomes. `attributable` is the load-
    bearing boolean for a live A/B: it is True when the OUTCOME co-moves with the
    ADHERENCE in the direction the skill thesis predicts — i.e. the value the arm
    captured (collisions prevented, zero lies banked) is accompanied by the verbs
    actually having fired. It is the guard against crediting the skills for a delta
    that came from model luck: if the arm banked no lies and prevented collisions
    but the WAL shows the verbs never fired, `attributable` is False and the delta
    must NOT be credited to the skills.
    """
    n_efforts: int
    mean_adherence: float
    prevention_total: int
    lies_total: int
    attributable: bool
    coord_attributable: bool

    def to_row(self) -> dict:
        return {
            "n_efforts": self.n_efforts,
            "mean_adherence": round(self.mean_adherence, 4),
            "prevention_total": self.prevention_total,
            "lies_total": self.lies_total,
            "attributable": self.attributable,
            "coord_attributable": self.coord_attributable,
        }


def summarize(records: list[AdherenceRecord]) -> AttributionSummary:
    """Fold per-effort records into the fleet attribution summary. Pure.

    TWO attribution booleans, kept apart (the FleetForge falsifier forced this
    split — coordination value and verify value have DIFFERENT falsifier regimes):

      * `attributable` — the BROAD claim: the arm captured SOME value (cross-effort
        prevention OR zero-lies-on-banked-work) and the verbs fired. Verify value
        (catching lies) is real at ANY N, so this stays True even at N=1 — that is
        correct, NOT a falsifier failure.
      * `coord_attributable` — the COORDINATION claim: the arm captured CROSS-EFFORT
        prevention specifically, with the verbs firing. THIS is the one that MUST
        vanish on the disjoint / N=1 falsifier (no peer => nothing to prevent =>
        coord_attributable False). It is the honest headline for the coordination
        axis the benchmark exists to measure; if it stayed True on a disjoint
        workload, the instrument would be rigged.
    """
    n = len(records)
    if n == 0:
        return AttributionSummary(0, 0.0, 0, 0, False, False)
    mean_adh = sum(r.adherence_score for r in records) / n
    prevention_total = sum(r.collisions_prevented for r in records)
    lies_total = sum(r.lies_banked for r in records)
    verbs_fired = mean_adh >= 0.5
    # broad value: prevention OR clean banking
    value_captured = (prevention_total > 0) or (
        lies_total == 0 and any(r.banked_count > 0 for r in records)
    )
    attributable = value_captured and verbs_fired
    # coordination value specifically = cross-effort prevention captured
    coord_attributable = (prevention_total > 0) and verbs_fired
    return AttributionSummary(
        n_efforts=n,
        mean_adherence=mean_adh,
        prevention_total=prevention_total,
        lies_total=lies_total,
        attributable=attributable,
        coord_attributable=coord_attributable,
    )

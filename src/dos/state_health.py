"""State-file health — a pure verdict over an external durable state file.

The gap this closes
===================

`dos doctor` reports the *path* of the workspace's execution-state file but says
nothing about its *health*. In practice that file (a host's `execution-state.yaml`,
a registry, any large append-mostly substrate the kernel does not own the schema of)
accumulates two debts the kernel could flag but doesn't:

  1. **Bloat** — cold, never-on-a-hot-path sections (a completed-work log, an
     abandoned-claim log, an archive sink) grow past any size a reader windows to,
     yet every read-modify-write of the file re-parses all of them. This is the
     `should_compact` problem (docs/106 §3.2) pointed at an *external* file instead
     of the lane journal.
  2. **Mid-flight / deferred-obligation drift** — a multi-step transition was
     *intentionally* left partial ("migrate the rest in a quiet window," "flip the
     flag later") with no run holding it, no deadline, and no detector. It looks
     like a healthy steady state, so nothing surfaces that it is owed. The intent
     ledger (docs/107) cannot catch this: there is no `run_id` and no crash — the
     work was *parked by design*, then orphaned. See docs/133.

This module is the read-side verdict for both. It is **pure** — it classifies
caller-gathered evidence against a declared policy and returns a typed verdict; it
does no I/O, reads no clock it was not handed, and **never performs a fix** (it
surfaces; a driver or human acts — the docs/99 advisory-only floor). It is the
`liveness.classify(evidence, policy) -> verdict` template applied to a file's
health, with `retention.should_compact`'s monotone-threshold posture for the size
rung.

The obligation rung — the docs/133 prototype
============================================

An ``Obligation`` is a deferred transition carrying its **completion predicate as
a pre-evaluated boolean** (the caller, which can touch the world, evaluates the
predicate at the boundary and hands the result in; this leaf stays pure). The
verdict re-states it as one of ``SATISFIED`` / ``PENDING`` / ``BLOCKED`` /
``STALE`` — the same fail-closed direction every DOS verdict takes (an obligation
whose predicate the caller could not evaluate degrades toward "still owed," never
toward "assume done"). A ``PENDING`` obligation past its declared horizon becomes
``STALE`` — the rung that makes "we left a migration half-done 30 days ago"
*structurally visible* the way a treeless lane already is.

Why a leaf with no I/O
======================

Same kernel/driver split as `retention` (the policy + `should_compact` are pure
data; the reapers that scandir/unlink live in the driver) and `liveness` (the
`classify` fold is pure; the boundary gathers the beats). A host's adapter gathers
the file's section sizes + evaluates each obligation's predicate (both of which
touch disk), then calls `classify_state_file`. Nothing in the kernel imports *down*
into a driver to use this.

Pure stdlib — no third-party imports, no I/O, no `time` read (the clock is handed
in as `now_ms`, the way a pure verdict is handed a clock).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Mapping, Sequence

_MS_PER_DAY = 86_400_000


# ---------------------------------------------------------------------------
# Obligations — the docs/133 deferred-transition record (prototype).
# ---------------------------------------------------------------------------


class ObligationStatus(str, enum.Enum):
    """The adjudicated state of one deferred obligation.

    `str`-valued so it round-trips a `--json` token without a lookup (`Liveness` /
    `durable_schema.Readability` idiom). The asymmetry is the whole point: only
    SATISFIED clears the debt; everything else keeps it visible, and STALE
    escalates it.
    """

    SATISFIED = "SATISFIED"  # the completion predicate holds — the debt is paid, drop it
    PENDING = "PENDING"      # not complete, still inside its declared horizon — owed, surfaced
    BLOCKED = "BLOCKED"      # a precondition is unmet — a human must clear it before it can complete
    STALE = "STALE"          # PENDING past its horizon — escalate (the "forgotten migration" rung)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_cleared(self) -> bool:
        """True iff the obligation no longer needs to be tracked (SATISFIED only)."""
        return self is ObligationStatus.SATISFIED

    @property
    def needs_attention(self) -> bool:
        """True iff a surfacer should report this (everything that is not cleared)."""
        return self is not ObligationStatus.SATISFIED


@dataclass(frozen=True)
class Obligation:
    """A deferred transition the kernel must keep visible until its predicate holds.

    The caller (at the I/O boundary) evaluates the completion predicate and the
    blocked precondition against the live world and hands the booleans in; this
    record stays pure data. Fields:

      * ``key`` — a stable id for the obligation (e.g. ``"migration:history-store"``).
      * ``description`` — the human one-liner ("drain YAML history into SQLite, then
        flip JOB_HISTORY_IN_STORE and drop the YAML buckets").
      * ``predicate_summary`` — the completion predicate *as text*, for the surfaced
        line ("store ⊇ yaml ∧ flag_flipped ∧ yaml_buckets_empty"). Carried so a
        reader can see WHAT is owed, not just THAT something is.
      * ``satisfied`` — the caller's evaluation of the completion predicate. None
        means "could not evaluate" → fail-closed to PENDING (never SATISFIED).
      * ``blocked`` — True iff a precondition is unmet (the completion cannot even
        be attempted yet); takes precedence over a not-yet-satisfied PENDING.
      * ``declared_at_ms`` — when the obligation was first recorded (the horizon
        anchor). None disables the staleness rung for this obligation.
      * ``horizon_days`` — how long the deferral is acceptable before it escalates
        to STALE. None = no horizon (PENDING forever, never STALE).
    """

    key: str
    description: str
    predicate_summary: str = ""
    satisfied: bool | None = None
    blocked: bool = False
    declared_at_ms: int | None = None
    horizon_days: float | None = None


def classify_obligation(ob: Obligation, *, now_ms: int) -> ObligationStatus:
    """Adjudicate one obligation. PURE — the predicate is pre-evaluated by the caller.

    Order is fail-closed:
      * a satisfied predicate clears it (SATISFIED) — the only exit;
      * else a blocked precondition is BLOCKED (a human must act);
      * else if it has a horizon and is past it, STALE (escalate the forgotten debt);
      * else PENDING (owed, but still within its acceptable deferral window).

    ``satisfied is None`` (the caller could not evaluate the predicate) is treated
    as not-satisfied — the same direction every DOS verdict takes when evidence is
    missing (degrade toward "redo / still owed," never toward "assume done").
    """
    if ob.satisfied is True:
        return ObligationStatus.SATISFIED
    if ob.blocked:
        return ObligationStatus.BLOCKED
    if (
        ob.declared_at_ms is not None
        and ob.horizon_days is not None
        and (now_ms - ob.declared_at_ms) > ob.horizon_days * _MS_PER_DAY
    ):
        return ObligationStatus.STALE
    return ObligationStatus.PENDING


# ---------------------------------------------------------------------------
# Section-size policy — the bloat rung (the `retention.should_compact` shape).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StateFilePolicy:
    """Per-file health caps, as immutable data (the `RetentionPolicy` shape).

    Every field optional-with-a-default; a host overrides what it cares about.
    ``None`` on any cap means "unbounded on this axis" — NOT zero. The caps are
    size tuning; like `RetentionPolicy`, this object carries only thresholds — it
    does not delete anything (a driver does, behind the verdict).

      * ``max_total_bytes`` — flag the file when its on-disk size exceeds this.
      * ``cold_section_max_rows`` — per-section row cap for the *cold* sections
        (the completed/abandoned/archive logs a reader windows past). A section
        over this is a COMPACTABLE finding.
      * ``cold_sections`` — the names of the sections to apply ``cold_section_max_rows``
        to. Empty ⇒ the size rung only looks at ``max_total_bytes``.
    """

    max_total_bytes: int | None = 200_000
    cold_section_max_rows: int | None = 150
    cold_sections: tuple[str, ...] = ()


GENERIC_STATE_FILE_POLICY = StateFilePolicy()


class SizeVerdict(str, enum.Enum):
    """Whether a state file is within its size budget."""

    OK = "OK"                  # within all size caps
    COMPACTABLE = "COMPACTABLE"  # over a cap — worth compacting (the should_compact "True")

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# ---------------------------------------------------------------------------
# Legacy-schema rung — retired field names / enum values still present.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LegacySchemaFinding:
    """One retired field name or enum value still present in the file.

    Generic over what "legacy" means for a given host: the caller declares the
    retired tokens it scanned for and how many it found. Carried as data so the
    surfaced line is legible ("9 entries still on retired `status: KEEP` — renamed
    to ACTIVE/MAINTENANCE/PARK/TOMB").
    """

    token: str            # the retired token, e.g. "status: KEEP" or "slot:"
    count: int            # how many occurrences the caller found
    replacement: str = ""  # the new form, for the surfaced line


# ---------------------------------------------------------------------------
# The composite health verdict.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StateHealthVerdict:
    """The typed result of `classify_state_file` — every rung's finding, foldable.

    `findings()` renders the human/`--check` lines (the `config_lint.lint`
    shape: a list of strings a `dos doctor --check` appends). `is_healthy` is the
    one-bit rollup. `to_dict` is the `--json` shape.
    """

    size: SizeVerdict
    total_bytes: int | None
    oversized_sections: tuple[tuple[str, int], ...]  # (section, rows) over the cold cap
    legacy: tuple[LegacySchemaFinding, ...]
    obligations: tuple[tuple[Obligation, ObligationStatus], ...]

    @property
    def is_healthy(self) -> bool:
        """True iff no rung has a finding worth surfacing."""
        return (
            self.size is SizeVerdict.OK
            and not self.oversized_sections
            and not self.legacy
            and not any(st.needs_attention for _, st in self.obligations)
        )

    @property
    def stale_obligations(self) -> tuple[Obligation, ...]:
        """The obligations past their horizon — the escalation set (the docs/133 point)."""
        return tuple(ob for ob, st in self.obligations if st is ObligationStatus.STALE)

    def findings(self) -> list[str]:
        """The surfaced lines — what `dos doctor --check` appends. PURE, deterministic.

        Ordered most-actionable first: stale obligations, then blocked/pending
        obligations, then bloat, then legacy schema. Empty ⇒ the file is healthy.
        """
        out: list[str] = []
        # Obligations first — a forgotten mid-flight transition is the highest-signal.
        for ob, st in self.obligations:
            if st is ObligationStatus.STALE:
                pred = f" — owed: {ob.predicate_summary}" if ob.predicate_summary else ""
                out.append(
                    f"obligation '{ob.key}' is STALE (deferred past its "
                    f"{ob.horizon_days:g}-day horizon){pred}: {ob.description}"
                )
        for ob, st in self.obligations:
            if st is ObligationStatus.BLOCKED:
                out.append(f"obligation '{ob.key}' is BLOCKED (a precondition is unmet): {ob.description}")
        for ob, st in self.obligations:
            if st is ObligationStatus.PENDING:
                pred = f" — owed: {ob.predicate_summary}" if ob.predicate_summary else ""
                out.append(f"obligation '{ob.key}' is PENDING{pred}: {ob.description}")
        # Bloat.
        if self.size is SizeVerdict.COMPACTABLE and self.total_bytes is not None:
            out.append(
                f"state file is {self.total_bytes:,} bytes — over the size budget; "
                f"compact the cold sections"
            )
        for section, rows in self.oversized_sections:
            out.append(f"cold section '{section}' has {rows} rows — over the per-section cap")
        # Legacy schema.
        for lf in self.legacy:
            repl = f" (→ {lf.replacement})" if lf.replacement else ""
            out.append(f"{lf.count} entries still use retired '{lf.token}'{repl}")
        return out

    def to_dict(self) -> dict:
        return {
            "size": self.size.value,
            "total_bytes": self.total_bytes,
            "oversized_sections": [list(t) for t in self.oversized_sections],
            "legacy": [
                {"token": lf.token, "count": lf.count, "replacement": lf.replacement}
                for lf in self.legacy
            ],
            "obligations": [
                {**_obligation_to_dict(ob), "status": st.value}
                for ob, st in self.obligations
            ],
            "is_healthy": self.is_healthy,
        }


def _obligation_to_dict(ob: Obligation) -> dict:
    return {
        "key": ob.key,
        "description": ob.description,
        "predicate_summary": ob.predicate_summary,
        "satisfied": ob.satisfied,
        "blocked": ob.blocked,
        "horizon_days": ob.horizon_days,
    }


@dataclass(frozen=True)
class StateFileEvidence:
    """What the boundary gathers about a state file — caller-supplied, pure to fold.

    The host adapter opens the file (the only I/O), measures it, and evaluates each
    obligation's predicate against the live world, then hands this in. The fold
    below never touches disk.

      * ``total_bytes`` — the file's on-disk size, or None if unknown.
      * ``section_rows`` — ``{section_name: row_count}`` for the sections the caller
        cares about (it only needs to fill the cold ones the policy names).
      * ``legacy`` — the retired-token findings the caller scanned for (already
        counted; an empty/zero-count finding is dropped by the fold).
      * ``obligations`` — the deferred obligations, predicates already evaluated.
    """

    total_bytes: int | None = None
    section_rows: Mapping[str, int] = field(default_factory=dict)
    legacy: Sequence[LegacySchemaFinding] = ()
    obligations: Sequence[Obligation] = ()


def classify_state_file(
    evidence: StateFileEvidence,
    policy: StateFilePolicy = GENERIC_STATE_FILE_POLICY,
    *,
    now_ms: int,
) -> StateHealthVerdict:
    """Classify one external state file's health. PURE — no I/O, clock handed in.

    Folds the caller-gathered ``evidence`` against ``policy`` into a
    `StateHealthVerdict`. The size rung is monotone (it only ever asks to compact
    *more* as the file grows — `retention.should_compact`'s posture). The
    obligation rung re-states each pre-evaluated obligation via `classify_obligation`.
    The legacy rung drops zero-count findings (a token scanned-for but absent is not
    a finding). All deterministic and order-stable so `--check` output is stable.
    """
    total = evidence.total_bytes

    # Size rung — total bytes over cap, OR any named cold section over its row cap.
    over_total = (
        policy.max_total_bytes is not None
        and total is not None
        and total > policy.max_total_bytes
    )
    oversized: list[tuple[str, int]] = []
    if policy.cold_section_max_rows is not None:
        for section in policy.cold_sections:
            rows = evidence.section_rows.get(section)
            if rows is not None and rows > policy.cold_section_max_rows:
                oversized.append((section, rows))
    size_verdict = (
        SizeVerdict.COMPACTABLE if (over_total or oversized) else SizeVerdict.OK
    )

    # Legacy rung — keep only present (count > 0) findings.
    legacy = tuple(lf for lf in evidence.legacy if lf.count > 0)

    # Obligation rung — adjudicate each against the handed-in clock.
    obligations = tuple(
        (ob, classify_obligation(ob, now_ms=now_ms)) for ob in evidence.obligations
    )

    return StateHealthVerdict(
        size=size_verdict,
        total_bytes=total,
        oversized_sections=tuple(oversized),
        legacy=legacy,
        obligations=obligations,
    )

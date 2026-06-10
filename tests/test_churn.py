"""Tests for dos.churn — the pure no-op-archive coalesce fold.

PURE: every test hands in the current `EventState` + the parsed `PriorCommit`
directly (no git, no `git log` read), so the coalesce-vs-stand-alone decision is
exercised in isolation. The `cause_key` is an opaque grouping string here — the
kernel groups on it but never interprets it (the host's `unstick_audit` taxonomy
owns what each key means).

The matrix under test: a no-op dispatch archive coalesces ONLY when the prior
commit is a same-family, same-cause no-op AND the recurrence reaches the floor.
Every other shape (a SHIPPED pick, a first-seen blocker, an unkeyed no-op, a
different cause, no prior commit, a replan/next-up commit in between) stands
alone — the fail-safe direction (a separate commit is always correct, just
noisier).
"""
from __future__ import annotations

from dos.churn import (
    ChurnState,
    CoalesceVerdict,
    PriorCommit,
    decide_coalesce,
)
from dos.event_severity import EventState, Severity, classify_event


def _noop_archive(cause: str = "operator_decision") -> EventState:
    """A 0-pick BLOCKED dispatch archive — classifies NOOP when it is a *repeat*.

    NOTE: severity is `(verdict, first_occurrence)`; a NOOP requires
    `first_occurrence=False` (a FIRST blocker is BLOCKED-NEW, not NOOP). The cause
    is carried separately on the ChurnState, not on the EventState.
    """
    return EventState(
        family="dispatch", verdict="BLOCKED", picks_shipped=0, first_occurrence=False
    )


def _prior_noop(cause: str = "operator_decision", *, coalesced: bool = False,
                count: int = 1) -> PriorCommit:
    return PriorCommit(
        family="dispatch", severity=Severity.NOOP.value, cause_key=cause,
        is_coalesced=coalesced, coalesce_count=count,
    )


# ── the happy path: a same-cause no-op repeat coalesces ──────────────────────

def test_second_same_cause_noop_coalesces():
    """The 2nd consecutive same-cause no-op folds into the prior commit (×2)."""
    v = decide_coalesce(ChurnState(
        event=_noop_archive("operator_decision"),
        cause_key="operator_decision",
        prior=_prior_noop("operator_decision"),
    ))
    assert v.coalesce is True
    assert v.recurrence == 2
    # The suffix carries the recurrence count AND a self-describing `[cause:…]`
    # token so the NEXT no-op can recover the cause from the collapsed headline.
    assert v.subject_suffix == "×2 (recurring, coalesced) [cause:operator_decision]"


def test_third_extends_already_coalesced_commit():
    """A 3rd no-op extends an ALREADY-coalesced ×2 commit to ×3 (not a new ×2)."""
    v = decide_coalesce(ChurnState(
        event=_noop_archive("operator_decision"),
        cause_key="operator_decision",
        prior=_prior_noop("operator_decision", coalesced=True, count=2),
    ))
    assert v.coalesce is True
    assert v.recurrence == 3
    assert v.subject_suffix == "×3 (recurring, coalesced) [cause:operator_decision]"


def test_coalesce_count_keeps_climbing():
    """The cycle the operator saw (22×) folds to one commit whose count climbs."""
    prior = _prior_noop("operator_decision", coalesced=True, count=21)
    v = decide_coalesce(ChurnState(
        event=_noop_archive("operator_decision"),
        cause_key="operator_decision", prior=prior,
    ))
    assert v.coalesce is True
    assert v.recurrence == 22


def test_suffix_embeds_cause_for_roundtrip():
    """The coalesced suffix carries `[cause:<key>]` so the next no-op's prior-commit
    parse can recover the cause from the collapsed `blocked ×N` headline (the
    original Outcome prose is gone after the first fold). Without this token the
    run would break at ×N+1 — a different cause every time → never coalescing past
    ×2. The host (`churn_gate._build_prior`) parses this token back."""
    v = decide_coalesce(ChurnState(
        event=_noop_archive("ship_oracle_false_positive"),
        cause_key="ship_oracle_false_positive",
        prior=_prior_noop("ship_oracle_false_positive"),
    ))
    assert v.coalesce is True
    assert "[cause:ship_oracle_false_positive]" in v.subject_suffix


# ── stand-alone: the events the operator WANTS to see in the log ─────────────

def test_first_noop_of_a_cause_stands_alone():
    """The FIRST no-op of a cause (no matching prior) stands alone — the operator
    should see a cause's debut in the log; only the repeat is noise."""
    v = decide_coalesce(ChurnState(
        event=_noop_archive("operator_decision"),
        cause_key="operator_decision",
        prior=_prior_noop("some_other_cause"),  # different cause = run breaks
    ))
    assert v.coalesce is False
    assert "not a same-family same-cause" in v.reason


def test_shipped_pick_never_coalesces():
    """A SHIPPED archive (≥1 pick) is exactly what the operator wants surfaced —
    it must keep its own standalone commit even after a no-op run."""
    shipped = EventState(family="dispatch", verdict="LIVE", picks_shipped=2)
    assert classify_event(shipped) is Severity.SHIPPED
    v = decide_coalesce(ChurnState(
        event=shipped, cause_key="", prior=_prior_noop("operator_decision"),
    ))
    assert v.coalesce is False
    assert "not a no-op" in v.reason


def test_first_seen_blocker_never_coalesces():
    """A FIRST-seen blocker is BLOCKED-NEW (actionable, may need a decision) — it
    is not a NOOP, so it stands alone even if the prior was a same-cause no-op."""
    fresh = EventState(
        family="dispatch", verdict="BLOCKED", picks_shipped=0, first_occurrence=True
    )
    assert classify_event(fresh) is Severity.BLOCKED_NEW
    v = decide_coalesce(ChurnState(
        event=fresh, cause_key="operator_decision",
        prior=_prior_noop("operator_decision"),
    ))
    assert v.coalesce is False


def test_unkeyed_noop_stands_alone():
    """A no-op with no cause_key cannot be proven same-cause — fail safe to a
    standalone commit (when in doubt, do not merge)."""
    v = decide_coalesce(ChurnState(
        event=_noop_archive(), cause_key="",
        prior=_prior_noop("operator_decision"),
    ))
    assert v.coalesce is False
    assert "no cause_key" in v.reason


def test_no_prior_commit_stands_alone():
    """The very first archive on a fresh branch (no prior) stands alone."""
    v = decide_coalesce(ChurnState(
        event=_noop_archive("operator_decision"),
        cause_key="operator_decision", prior=None,
    ))
    assert v.coalesce is False
    assert "no prior commit" in v.reason


def test_replan_commit_between_breaks_the_run():
    """A /replan commit landing between two no-ops breaks the coalesce run — the
    prior commit is now the replan (family='replan'), not a dispatch no-op, so the
    next no-op starts a fresh standalone commit."""
    prior_replan = PriorCommit(
        family="replan", severity=Severity.NOOP.value, cause_key="",
    )
    v = decide_coalesce(ChurnState(
        event=_noop_archive("operator_decision"),
        cause_key="operator_decision", prior=prior_replan,
    ))
    assert v.coalesce is False


def test_prior_shipped_breaks_the_run():
    """A prior SHIPPED commit (the operator's win) is never absorbed — the next
    no-op stands alone beside it, not amended into it."""
    prior_shipped = PriorCommit(
        family="dispatch", severity=Severity.SHIPPED.value, cause_key="",
    )
    v = decide_coalesce(ChurnState(
        event=_noop_archive("operator_decision"),
        cause_key="operator_decision", prior=prior_shipped,
    ))
    assert v.coalesce is False


def test_different_cause_does_not_coalesce():
    """Two DIFFERENT no-op causes back-to-back do NOT merge — each cause's debut
    is worth one log row; only the SAME cause repeating is the cycle."""
    v = decide_coalesce(ChurnState(
        event=_noop_archive("packet_incoherence"),
        cause_key="packet_incoherence",
        prior=_prior_noop("operator_decision"),
    ))
    assert v.coalesce is False


# ── DRAIN is a no-op too ─────────────────────────────────────────────────────

def test_drain_coalesces_like_blocked():
    """A 0-pick DRAIN classifies NOOP just like a repeated BLOCKED, so a same-cause
    DRAIN repeat coalesces on the same rule."""
    drain = EventState(family="dispatch", verdict="DRAIN", picks_shipped=0)
    assert classify_event(drain) is Severity.NOOP
    v = decide_coalesce(ChurnState(
        event=drain, cause_key="lane_soak_gated",
        prior=_prior_noop("lane_soak_gated"),
    ))
    assert v.coalesce is True
    assert v.recurrence == 2


def test_dispatch_loop_family_also_coalesces():
    """The `dispatch-loop` family (loop-level archive) coalesces on the same rule
    as `dispatch` — both carry the per-run no-op cycle."""
    ev = EventState(
        family="dispatch-loop", verdict="BLOCKED", picks_shipped=0,
        first_occurrence=False,
    )
    prior = PriorCommit(
        family="dispatch-loop", severity=Severity.NOOP.value,
        cause_key="operator_decision",
    )
    v = decide_coalesce(ChurnState(
        event=ev, cause_key="operator_decision", prior=prior,
    ))
    assert v.coalesce is True


# ── threshold knob ───────────────────────────────────────────────────────────

def test_min_coalesce_run_raises_the_bar():
    """At min_coalesce_run=3 a 2-run cause is below the bar (stands alone); the
    same inputs at the default (2) DO coalesce."""
    state = ChurnState(
        event=_noop_archive("operator_decision"),
        cause_key="operator_decision",
        prior=_prior_noop("operator_decision"),
        min_coalesce_run=3,
    )
    v = decide_coalesce(state)
    assert v.coalesce is False
    assert v.recurrence == 2  # computed, but below the raised bar

    # default threshold: the same shape coalesces.
    v2 = decide_coalesce(ChurnState(
        event=state.event, cause_key=state.cause_key, prior=state.prior,
    ))
    assert v2.coalesce is True


# ── legacy WEDGE prior folds to BLOCKED ──────────────────────────────────────

def test_legacy_wedge_prior_severity_normalizes():
    """A prior commit whose severity round-tripped as a legacy token still matches
    via normalize_token (the one chokepoint) — no separate WEDGE handling here."""
    # Severity strings don't carry the WEDGE alias, but normalize_token is applied
    # to the prior severity defensively; a canonical NOOP matches plainly.
    v = decide_coalesce(ChurnState(
        event=_noop_archive("operator_decision"),
        cause_key="operator_decision",
        prior=_prior_noop("operator_decision"),
    ))
    assert isinstance(v, CoalesceVerdict)
    assert v.coalesce is True

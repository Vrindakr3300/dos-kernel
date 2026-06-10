"""state_health — the external-state-file health verdict + the deferred-obligation rung.

Pins the docs/133 prototype + the `dos doctor` state-health gap closer: a pure
`classify_state_file(evidence, policy) -> verdict` fold over caller-gathered
evidence (size, cold-section rows, retired tokens, deferred obligations), with the
obligation rung fail-closed (an un-evaluable predicate degrades to PENDING, never
SATISFIED) and a horizon that escalates PENDING → STALE — the "forgotten migration"
rung. Pure-stdlib unit tests on hand-built evidence — no I/O, no live crash, the
`liveness.classify` / `test_durable_schema` test posture.
"""

from __future__ import annotations

from dos import state_health as sh
from dos.state_health import (
    Obligation,
    ObligationStatus,
    LegacySchemaFinding,
    SizeVerdict,
    StateFileEvidence,
    StateFilePolicy,
)

_DAY = 86_400_000
_NOW = 1_000 * _DAY  # an arbitrary fixed clock (no Date.now in a pure test)


# --------------------------------------------------------------------------
# classify_obligation — the four-way fail-closed adjudication.
# --------------------------------------------------------------------------


def test_obligation_satisfied_is_the_only_clear():
    ob = Obligation(key="m", description="d", satisfied=True)
    assert sh.classify_obligation(ob, now_ms=_NOW) is ObligationStatus.SATISFIED
    assert sh.classify_obligation(ob, now_ms=_NOW).is_cleared


def test_obligation_unsatisfied_within_horizon_is_pending():
    ob = Obligation(
        key="m", description="d", satisfied=False,
        declared_at_ms=_NOW - 5 * _DAY, horizon_days=30,
    )
    assert sh.classify_obligation(ob, now_ms=_NOW) is ObligationStatus.PENDING


def test_obligation_past_horizon_is_stale():
    ob = Obligation(
        key="m", description="d", satisfied=False,
        declared_at_ms=_NOW - 40 * _DAY, horizon_days=30,
    )
    assert sh.classify_obligation(ob, now_ms=_NOW) is ObligationStatus.STALE


def test_obligation_blocked_takes_precedence_over_pending():
    ob = Obligation(
        key="m", description="d", satisfied=False, blocked=True,
        declared_at_ms=_NOW - 1 * _DAY, horizon_days=30,
    )
    assert sh.classify_obligation(ob, now_ms=_NOW) is ObligationStatus.BLOCKED


def test_obligation_satisfied_wins_even_when_blocked_flag_set():
    # A satisfied predicate clears it regardless of a stale `blocked` flag.
    ob = Obligation(key="m", description="d", satisfied=True, blocked=True)
    assert sh.classify_obligation(ob, now_ms=_NOW) is ObligationStatus.SATISFIED


def test_obligation_unevaluable_predicate_fails_closed_to_pending():
    # satisfied=None (the caller could not evaluate) must NOT be treated as done.
    ob = Obligation(key="m", description="d", satisfied=None)
    assert sh.classify_obligation(ob, now_ms=_NOW) is ObligationStatus.PENDING


def test_obligation_no_horizon_never_goes_stale():
    ob = Obligation(
        key="m", description="d", satisfied=False,
        declared_at_ms=_NOW - 9999 * _DAY, horizon_days=None,
    )
    assert sh.classify_obligation(ob, now_ms=_NOW) is ObligationStatus.PENDING


def test_obligation_no_declared_at_never_goes_stale():
    ob = Obligation(key="m", description="d", satisfied=False, horizon_days=1)
    assert sh.classify_obligation(ob, now_ms=_NOW) is ObligationStatus.PENDING


# --------------------------------------------------------------------------
# classify_state_file — the size rung.
# --------------------------------------------------------------------------


def test_size_ok_when_within_budget():
    ev = StateFileEvidence(total_bytes=100_000, section_rows={"recently_completed": 50})
    pol = StateFilePolicy(max_total_bytes=200_000, cold_section_max_rows=150,
                          cold_sections=("recently_completed",))
    v = sh.classify_state_file(ev, pol, now_ms=_NOW)
    assert v.size is SizeVerdict.OK
    assert v.is_healthy


def test_size_compactable_when_over_total_bytes():
    ev = StateFileEvidence(total_bytes=280_000)
    v = sh.classify_state_file(ev, StateFilePolicy(max_total_bytes=200_000), now_ms=_NOW)
    assert v.size is SizeVerdict.COMPACTABLE
    assert not v.is_healthy
    assert any("over the size budget" in f for f in v.findings())


def test_size_compactable_when_cold_section_over_row_cap():
    ev = StateFileEvidence(
        total_bytes=10,  # tiny file, but a cold section is over its row cap
        section_rows={"recently_completed": 227, "abandoned": 207, "plans": 67},
    )
    pol = StateFilePolicy(max_total_bytes=10_000_000, cold_section_max_rows=150,
                          cold_sections=("recently_completed", "abandoned"))
    v = sh.classify_state_file(ev, pol, now_ms=_NOW)
    assert v.size is SizeVerdict.COMPACTABLE
    sections = dict(v.oversized_sections)
    assert sections == {"recently_completed": 227, "abandoned": 207}  # plans not cold → ignored


def test_cold_section_under_cap_not_flagged():
    ev = StateFileEvidence(total_bytes=10, section_rows={"abandoned": 100})
    pol = StateFilePolicy(max_total_bytes=10_000_000, cold_section_max_rows=150,
                          cold_sections=("abandoned",))
    v = sh.classify_state_file(ev, pol, now_ms=_NOW)
    assert v.size is SizeVerdict.OK
    assert not v.oversized_sections


def test_none_caps_disable_their_rungs():
    ev = StateFileEvidence(total_bytes=9_999_999, section_rows={"abandoned": 9999})
    pol = StateFilePolicy(max_total_bytes=None, cold_section_max_rows=None,
                          cold_sections=("abandoned",))
    v = sh.classify_state_file(ev, pol, now_ms=_NOW)
    assert v.size is SizeVerdict.OK


# --------------------------------------------------------------------------
# classify_state_file — the legacy-schema rung.
# --------------------------------------------------------------------------


def test_legacy_present_tokens_surface_zero_count_dropped():
    ev = StateFileEvidence(
        total_bytes=10,
        legacy=[
            LegacySchemaFinding(token="status: KEEP", count=9,
                                replacement="ACTIVE/MAINTENANCE/PARK/TOMB"),
            LegacySchemaFinding(token="slot:", count=27, replacement="priority:"),
            LegacySchemaFinding(token="status: SECONDARY", count=0),  # scanned, absent → dropped
        ],
    )
    v = sh.classify_state_file(ev, StateFilePolicy(max_total_bytes=None), now_ms=_NOW)
    tokens = {lf.token for lf in v.legacy}
    assert tokens == {"status: KEEP", "slot:"}
    assert not v.is_healthy
    fs = v.findings()
    assert any("status: KEEP" in f and "9 entries" in f for f in fs)
    assert any("slot:" in f and "priority:" in f for f in fs)


# --------------------------------------------------------------------------
# classify_state_file — the obligation rung end-to-end (the docs/133 case).
# --------------------------------------------------------------------------


def test_stale_obligation_surfaces_first_and_marks_unhealthy():
    # The exact shape of the stalled SQLite migration: declared 40 days ago,
    # 30-day horizon, predicate not satisfied → STALE.
    ob = Obligation(
        key="migration:history-store",
        description="drain YAML history → SQLite, flip flag, drop YAML buckets",
        predicate_summary="store ⊇ yaml ∧ flag_flipped ∧ yaml_buckets_empty",
        satisfied=False,
        declared_at_ms=_NOW - 40 * _DAY,
        horizon_days=30,
    )
    ev = StateFileEvidence(total_bytes=10, obligations=[ob])
    v = sh.classify_state_file(ev, StateFilePolicy(max_total_bytes=None), now_ms=_NOW)
    assert not v.is_healthy
    assert v.stale_obligations == (ob,)
    # STALE obligation is the first finding (most actionable).
    first = v.findings()[0]
    assert "migration:history-store" in first and "STALE" in first
    assert "store ⊇ yaml" in first  # the predicate is shown


def test_satisfied_obligation_clears_and_is_healthy():
    ob = Obligation(key="m", description="d", satisfied=True)
    ev = StateFileEvidence(total_bytes=10, obligations=[ob])
    v = sh.classify_state_file(ev, StateFilePolicy(max_total_bytes=None), now_ms=_NOW)
    assert v.is_healthy
    assert v.findings() == []
    assert not v.stale_obligations


def test_findings_ordered_stale_then_blocked_then_pending():
    obs = [
        Obligation(key="p", description="pending", satisfied=False),
        Obligation(key="s", description="stale", satisfied=False,
                   declared_at_ms=_NOW - 40 * _DAY, horizon_days=30),
        Obligation(key="b", description="blocked", satisfied=False, blocked=True),
    ]
    ev = StateFileEvidence(total_bytes=10, obligations=obs)
    v = sh.classify_state_file(ev, StateFilePolicy(max_total_bytes=None), now_ms=_NOW)
    fs = v.findings()
    # stale first, then blocked, then pending
    assert "'s' is STALE" in fs[0]
    assert "'b' is BLOCKED" in fs[1]
    assert "'p' is PENDING" in fs[2]


# --------------------------------------------------------------------------
# Rollup + serialization.
# --------------------------------------------------------------------------


def test_healthy_file_has_no_findings():
    ev = StateFileEvidence(total_bytes=50_000, section_rows={"recently_completed": 10})
    pol = StateFilePolicy(cold_sections=("recently_completed",))
    v = sh.classify_state_file(ev, pol, now_ms=_NOW)
    assert v.is_healthy
    assert v.findings() == []


def test_to_dict_round_trips_tokens():
    ob = Obligation(key="m", description="d", predicate_summary="P", satisfied=False,
                    declared_at_ms=_NOW - 40 * _DAY, horizon_days=30)
    ev = StateFileEvidence(
        total_bytes=280_000,
        section_rows={"abandoned": 207},
        legacy=[LegacySchemaFinding(token="slot:", count=27, replacement="priority:")],
        obligations=[ob],
    )
    pol = StateFilePolicy(max_total_bytes=200_000, cold_section_max_rows=150,
                          cold_sections=("abandoned",))
    d = sh.classify_state_file(ev, pol, now_ms=_NOW).to_dict()
    assert d["size"] == "COMPACTABLE"
    assert d["total_bytes"] == 280_000
    assert ["abandoned", 207] in d["oversized_sections"]
    assert d["legacy"][0] == {"token": "slot:", "count": 27, "replacement": "priority:"}
    assert d["obligations"][0]["status"] == "STALE"
    assert d["obligations"][0]["key"] == "m"
    assert d["is_healthy"] is False


def test_multiple_rungs_compose_into_one_unhealthy_verdict():
    ob = Obligation(key="m", description="d", satisfied=False,
                    declared_at_ms=_NOW - 40 * _DAY, horizon_days=30)
    ev = StateFileEvidence(
        total_bytes=280_000,
        section_rows={"recently_completed": 227, "abandoned": 207},
        legacy=[LegacySchemaFinding(token="status: KEEP", count=9)],
        obligations=[ob],
    )
    pol = StateFilePolicy(max_total_bytes=200_000, cold_section_max_rows=150,
                          cold_sections=("recently_completed", "abandoned"))
    v = sh.classify_state_file(ev, pol, now_ms=_NOW)
    assert not v.is_healthy
    fs = v.findings()
    # obligation first, then bloat, then legacy — all present
    assert any("STALE" in f for f in fs)
    assert any("over the size budget" in f for f in fs)
    assert any("recently_completed" in f for f in fs)
    assert any("status: KEEP" in f for f in fs)

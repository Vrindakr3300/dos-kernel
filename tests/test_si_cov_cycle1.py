"""Coverage cycle 1 — exercise the pure classifiers in `dos.gate_classify`.

`gate_classify` carries several pure, I/O-free functions whose only existing
in-process coverage was `replan_skip_decision` (tests/test_replan_skip.py) and a
bare `Verdict` attribute read (tests/test_refusal_and_tokens.py). The full
classifier surface — `classify_packet`, `_coerce`, the `PickDisposition` /
`ClassifyResult` predicates, `gate_policy` across all five verdicts × three
modes, `classify_packet_file` + `_race_envelope_for`, and
`classify_replan_productivity` — was reached only through the CLI subprocess in
tests/test_gate_cli.py, which coverage.py does not record over the in-process
suite. These tests call the same pure functions directly, in-process.

All inputs are frozen literals / `tmp_path` fixtures; no network, no sleeps, no
tracked-file writes — exactly the pure-function surface these classifiers were
built to be tested on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dos import gate_classify as gc
from dos.gate_classify import (
    ClassifyResult,
    GateAction,
    MalformedDisposition,
    PickDisposition,
    ReplanProductivity,
    StaleDispositionContract,
    Verdict,
    classify_packet,
    classify_packet_file,
    classify_replan_productivity,
    gate_policy,
)


# ---------------------------------------------------------------------------
# _coerce — dict→PickDisposition tolerance, aliases, and the loud failures
# ---------------------------------------------------------------------------


class TestCoerce:
    def test_passthrough_a_pickdisposition(self):
        pd = PickDisposition(series="FB", phase="FB2", live=True)
        assert gc._coerce(pd) is pd

    def test_non_dict_non_pd_raises_malformed(self):
        with pytest.raises(MalformedDisposition):
            gc._coerce(42)

    def test_missing_phase_raises_malformed(self):
        with pytest.raises(MalformedDisposition):
            gc._coerce({"live": False})

    def test_phase_id_alias_accepted(self):
        pd = gc._coerce({"phase_id": "FB2", "live": True})
        assert pd.phase == "FB2"
        assert pd.live is True

    def test_series_derived_by_stripping_trailing_digits(self):
        pd = gc._coerce({"phase": "FB2"})
        # Series derived from the phase id (strip trailing digits/dots).
        assert pd.series == "FB"
        # live defaults to False (the dropped-pick case).
        assert pd.live is False

    def test_explicit_series_and_fields_round_trip(self):
        pd = gc._coerce({
            "series": "AUTH",
            "phase": "AUTH2",
            "live": False,
            "drop_reason": gc.DROP_SHIPPED,
            "ship_via": gc.SHIP_VIA_DIRECT,
            "ship_sha": "abc123",
            "plan_doc_stamped": False,
            "claim_tag": "sib",
        })
        assert pd.series == "AUTH"
        assert pd.ship_sha == "abc123"
        assert pd.plan_doc_stamped is False
        assert pd.claim_tag == "sib"


# ---------------------------------------------------------------------------
# PickDisposition predicates
# ---------------------------------------------------------------------------


class TestPickDispositionPredicates:
    def test_is_stale_stamp_true_on_direct_ship_unstamped(self):
        pd = PickDisposition(
            series="FB", phase="FB2", live=False,
            drop_reason=gc.DROP_SHIPPED, ship_via=gc.SHIP_VIA_DIRECT,
            plan_doc_stamped=False,
        )
        assert pd.is_stale_stamp() is True

    def test_is_stale_stamp_false_when_stamped(self):
        pd = PickDisposition(
            series="FB", phase="FB2", live=False,
            drop_reason=gc.DROP_SHIPPED, ship_via=gc.SHIP_VIA_DIRECT,
            plan_doc_stamped=True,
        )
        assert pd.is_stale_stamp() is False

    def test_is_stale_stamp_false_on_weak_via(self):
        # A non-direct ship verdict must NOT count as stale-stamp.
        pd = PickDisposition(
            series="FB", phase="FB2", live=False,
            drop_reason=gc.DROP_SHIPPED, ship_via="release-prefix",
            plan_doc_stamped=False,
        )
        assert pd.is_stale_stamp() is False

    def test_is_blocked_true_on_soft_claim(self):
        pd = PickDisposition(
            series="FB", phase="FB2", live=False,
            drop_reason=gc.DROP_SOFT_CLAIMED, claim_tag="sib",
        )
        assert pd.is_blocked() is True

    def test_is_blocked_true_on_quota(self):
        pd = PickDisposition(
            series="FB", phase="FB2", live=False,
            drop_reason=gc.DROP_QUOTA_BLOCKED,
        )
        assert pd.is_blocked() is True

    def test_is_blocked_false_when_live(self):
        pd = PickDisposition(series="FB", phase="FB2", live=True)
        assert pd.is_blocked() is False


# ---------------------------------------------------------------------------
# classify_packet — the decision ladder LIVE → STALE-STAMP → BLOCKED → DRAIN
# ---------------------------------------------------------------------------


class TestClassifyPacket:
    def test_empty_packet_is_drain(self):
        r = classify_packet([])
        assert r.verdict is Verdict.DRAIN
        assert r.evidence == []
        assert r.is_false_drain is False

    def test_any_live_pick_is_live(self):
        r = classify_packet([
            {"phase": "FB2", "live": True},
            {"phase": "AUTH1", "live": False, "drop_reason": gc.DROP_SHIPPED,
             "ship_via": gc.SHIP_VIA_DIRECT, "plan_doc_stamped": False},
        ])
        # LIVE wins even when another pick would be STALE-STAMP.
        assert r.verdict is Verdict.LIVE
        assert len(r.evidence) == 1
        assert r.evidence[0].live is True

    def test_stale_stamp_when_no_live_and_a_direct_ship_unstamped(self):
        r = classify_packet([
            {"phase": "FB2", "live": False, "drop_reason": gc.DROP_SHIPPED,
             "ship_via": gc.SHIP_VIA_DIRECT, "plan_doc_stamped": False},
        ])
        assert r.verdict is Verdict.STALE_STAMP
        assert r.is_false_drain is True
        assert "FB FB2" in r.reason

    def test_blocked_when_no_live_no_stale_and_a_soft_claim(self):
        r = classify_packet([
            {"phase": "FB2", "live": False, "drop_reason": gc.DROP_SOFT_CLAIMED,
             "claim_tag": "sib"},
        ])
        assert r.verdict is Verdict.BLOCKED
        assert r.is_false_drain is True
        assert "FB FB2" in r.reason

    def test_drain_when_dropped_but_no_recoverable_signal(self):
        # A dropped pick with an unrecognised drop reason is neither stale nor
        # blocked → genuine DRAIN.
        r = classify_packet([
            {"phase": "FB2", "live": False, "drop_reason": "some_other_reason"},
        ])
        assert r.verdict is Verdict.DRAIN
        assert r.is_false_drain is False

    def test_stale_stamp_precedes_blocked(self):
        # Both a stale-stamp pick and a blocked pick present, no live → STALE-STAMP
        # wins (more-specific-first ordering).
        r = classify_packet([
            {"phase": "AUTH2", "live": False, "drop_reason": gc.DROP_SOFT_CLAIMED,
             "claim_tag": "sib"},
            {"phase": "FB2", "live": False, "drop_reason": gc.DROP_SHIPPED,
             "ship_via": gc.SHIP_VIA_DIRECT, "plan_doc_stamped": False},
        ])
        assert r.verdict is Verdict.STALE_STAMP


# ---------------------------------------------------------------------------
# ClassifyResult.is_false_drain across the verdict set
# ---------------------------------------------------------------------------


class TestIsFalseDrain:
    @pytest.mark.parametrize("verdict,expected", [
        (Verdict.LIVE, False),
        (Verdict.DRAIN, False),
        (Verdict.STALE_STAMP, True),
        (Verdict.BLOCKED, True),
        (Verdict.RACE, True),
    ])
    def test_false_drain_membership(self, verdict, expected):
        assert ClassifyResult(verdict=verdict, reason="x").is_false_drain is expected


# ---------------------------------------------------------------------------
# gate_policy — five verdicts × three modes, plus the bad-mode raise
# ---------------------------------------------------------------------------


class TestGatePolicy:
    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError):
            gate_policy(Verdict.DRAIN, mode="bogus")

    def test_live_continues_dispatch_in_any_mode(self):
        a = gate_policy(Verdict.LIVE, mode=gc.GATE_HARD)
        assert a.next_mode == "dispatch"
        assert a.counts_toward_drain is False
        assert a.surface is False

    def test_drain_hard_routes_replan_and_counts(self):
        a = gate_policy(Verdict.DRAIN, mode=gc.GATE_HARD)
        assert a.next_mode == "replan"
        assert a.counts_toward_drain is True
        assert a.surface is False

    def test_drain_soft_stops_and_surfaces(self):
        a = gate_policy(Verdict.DRAIN, mode=gc.GATE_SOFT)
        assert a.next_mode == "stop"
        assert a.counts_toward_drain is True
        assert a.surface is True

    def test_drain_drive_stops_and_surfaces(self):
        a = gate_policy(Verdict.DRAIN, mode=gc.GATE_DRIVE)
        assert a.next_mode == "stop"
        assert a.counts_toward_drain is True

    def test_race_retries_in_every_mode_without_drain_count(self):
        for mode in gc.GATE_MODES:
            a = gate_policy(Verdict.RACE, mode=mode)
            assert a.next_mode == "dispatch"
            assert a.counts_toward_drain is False
            assert a.surface is True

    def test_stale_stamp_hard_routes_replan_no_count(self):
        a = gate_policy(Verdict.STALE_STAMP, mode=gc.GATE_HARD)
        assert a.next_mode == "replan"
        assert a.counts_toward_drain is False
        assert a.reconcile is False

    def test_stale_stamp_drive_self_heals_inline(self):
        a = gate_policy(Verdict.STALE_STAMP, mode=gc.GATE_DRIVE)
        assert a.next_mode == "dispatch"
        assert a.reconcile is True
        assert a.counts_toward_drain is False

    def test_stale_stamp_soft_self_heals_inline(self):
        a = gate_policy(Verdict.STALE_STAMP, mode=gc.GATE_SOFT)
        assert a.next_mode == "dispatch"
        assert a.reconcile is True

    def test_blocked_hard_routes_replan_no_count(self):
        a = gate_policy(Verdict.BLOCKED, mode=gc.GATE_HARD)
        assert a.next_mode == "replan"
        assert a.counts_toward_drain is False
        assert a.surface is False

    def test_blocked_soft_stops_and_surfaces(self):
        a = gate_policy(Verdict.BLOCKED, mode=gc.GATE_SOFT)
        assert a.next_mode == "stop"
        assert a.surface is True
        assert a.counts_toward_drain is False

    def test_blocked_drive_stops_and_surfaces(self):
        a = gate_policy(Verdict.BLOCKED, mode=gc.GATE_DRIVE)
        assert isinstance(a, GateAction)
        assert a.next_mode == "stop"
        assert a.surface is True


# ---------------------------------------------------------------------------
# classify_packet_file + _race_envelope_for — the validated I/O wrapper
# ---------------------------------------------------------------------------


def _write_sidecar(d: Path, tag: str, dispositions: list, schema: str = gc.DISPOSITIONS_SCHEMA) -> Path:
    p = d / f".dispositions-{tag}.json"
    p.write_text(json.dumps({
        "schema": schema, "tag": tag, "dispositions": dispositions,
    }), encoding="utf-8")
    return p


class TestClassifyPacketFile:
    def test_well_formed_sidecar_delegates_to_classify_packet(self, tmp_path):
        p = _write_sidecar(tmp_path, "t1", [{"phase": "FB2", "live": True}])
        r = classify_packet_file(p)
        assert r.verdict is Verdict.LIVE

    def test_empty_sidecar_is_drain(self, tmp_path):
        p = _write_sidecar(tmp_path, "t1", [])
        assert classify_packet_file(p).verdict is Verdict.DRAIN

    def test_missing_file_raises_contract(self, tmp_path):
        with pytest.raises(StaleDispositionContract):
            classify_packet_file(tmp_path / ".dispositions-nope.json")

    def test_bad_json_raises_contract(self, tmp_path):
        p = tmp_path / ".dispositions-bad.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(StaleDispositionContract):
            classify_packet_file(p)

    def test_non_object_envelope_raises_contract(self, tmp_path):
        p = tmp_path / ".dispositions-arr.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(StaleDispositionContract):
            classify_packet_file(p)

    def test_wrong_schema_raises_contract(self, tmp_path):
        p = _write_sidecar(tmp_path, "t1", [], schema="wrong-schema")
        with pytest.raises(StaleDispositionContract):
            classify_packet_file(p)

    def test_dispositions_not_a_list_raises_contract(self, tmp_path):
        p = tmp_path / ".dispositions-t1.json"
        p.write_text(json.dumps({
            "schema": gc.DISPOSITIONS_SCHEMA, "tag": "t1",
            "dispositions": {"phase": "X"},  # object, not list
        }), encoding="utf-8")
        with pytest.raises(StaleDispositionContract):
            classify_packet_file(p)

    def test_race_envelope_wins_precedence(self, tmp_path):
        # A LIVE on-disk packet, but a sibling race envelope → RACE wins.
        p = _write_sidecar(tmp_path, "t2", [{"phase": "FB2", "live": True}])
        (tmp_path / ".race-t2.json").write_text(json.dumps({
            "schema": gc.RACE_SCHEMA,
            "blocked_by_pid": 1234,
            "attempted_at": "20260601T000000Z",
            "lock_path": str(tmp_path / ".lock"),
        }), encoding="utf-8")
        r = classify_packet_file(p)
        assert r.verdict is Verdict.RACE
        assert "1234" in r.reason

    def test_race_envelope_custom_reason_used(self, tmp_path):
        p = _write_sidecar(tmp_path, "t3", [])
        (tmp_path / ".race-t3.json").write_text(json.dumps({
            "schema": gc.RACE_SCHEMA, "reason": "explicit race reason",
        }), encoding="utf-8")
        r = classify_packet_file(p)
        assert r.verdict is Verdict.RACE
        assert r.reason == "explicit race reason"

    def test_malformed_race_envelope_falls_through(self, tmp_path):
        # Wrong race schema → race ignored, falls through to normal classification.
        p = _write_sidecar(tmp_path, "t4", [{"phase": "FB2", "live": True}])
        (tmp_path / ".race-t4.json").write_text(
            json.dumps({"schema": "not-race"}), encoding="utf-8")
        assert classify_packet_file(p).verdict is Verdict.LIVE

    def test_race_envelope_bad_json_falls_through(self, tmp_path):
        p = _write_sidecar(tmp_path, "t5", [])
        (tmp_path / ".race-t5.json").write_text("{broken", encoding="utf-8")
        # Unreadable race file → ignored → empty packet is DRAIN.
        assert classify_packet_file(p).verdict is Verdict.DRAIN

    def test_non_dispositions_path_name_skips_race_check(self, tmp_path):
        # A path NOT named `.dispositions-<tag>.json` cannot have a race sibling;
        # `_race_envelope_for` returns None up front.
        assert gc._race_envelope_for(tmp_path / "packet.json") is None


# ---------------------------------------------------------------------------
# classify_replan_productivity — the §1.5 / §7 marker reader
# ---------------------------------------------------------------------------


class TestClassifyReplanProductivity:
    def test_empty_text_is_productive_conservative_default(self):
        # No recognised marker at all → conservative PRODUCTIVE (never extends loop).
        assert classify_replan_productivity("") is ReplanProductivity.PRODUCTIVE

    def test_noop_skip_marker_is_unproductive(self):
        text = f"some prose\n{gc.REPLAN_NOOP_SKIP_MARKER} since 20260601\nmore"
        assert classify_replan_productivity(text) is ReplanProductivity.UNPRODUCTIVE

    def test_nonzero_promoted_is_productive(self):
        assert classify_replan_productivity("2/4 promoted to inbox") is ReplanProductivity.PRODUCTIVE

    def test_zero_numerator_promoted_is_unproductive(self):
        # "0/4 promoted" — numerator captured, all counters zero → UNPRODUCTIVE.
        assert classify_replan_productivity("0/4 promoted to inbox") is ReplanProductivity.UNPRODUCTIVE

    def test_nonzero_anchors_reconciled_is_productive(self):
        assert classify_replan_productivity("3 anchors reconciled") is ReplanProductivity.PRODUCTIVE

    def test_all_zero_counters_is_unproductive(self):
        text = "0 auto-closed · 0 added · 0 anchors reconciled · 0 stale claims swept"
        assert classify_replan_productivity(text) is ReplanProductivity.UNPRODUCTIVE

    def test_no_recognised_counter_is_productive(self):
        # Prose with no recognised gardening-count token → conservative PRODUCTIVE.
        assert classify_replan_productivity("the sweep ran and felt great") is ReplanProductivity.PRODUCTIVE

    def test_enum_is_str_valued(self):
        assert ReplanProductivity.PRODUCTIVE == "PRODUCTIVE"
        assert str(ReplanProductivity.UNPRODUCTIVE) == "UNPRODUCTIVE"

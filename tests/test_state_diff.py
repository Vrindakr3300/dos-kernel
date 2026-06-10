"""Tests for the state-diff read-back witness (`dos.drivers.state_diff`) — docs/181.

The Agent-Diff concept (docs/180): success = the expected STATE delta occurred,
computed as a canonical diff (inserted/deleted/updated) over before/after snapshots —
the non-forgeable read-back that feeds `effect_witness`. Pins:

  * `diff_state` is the canonical domain-free delta (PURE).
  * a claimed effect-key PRESENT in inserted∪updated → CONFIRMED; ABSENT → REFUTED.
  * the SOUNDNESS GUARD: a state-diff witness over an AGENT_AUTHORED snapshot rung is
    rejected at construction (actor==witness is not a witness).
  * the boundary fail-safe: an unreadable snapshot → UNWITNESSED, never a fabricated
    empty delta that would falsely REFUTE every claim.
  * the kernel never imports this driver (one-way import litmus).
"""
from __future__ import annotations

import json

import pytest

from dos.evidence import Accountability
from dos.effect_witness import EffectClaim
from dos.drivers.state_diff import (
    StateDelta,
    StateDiffEvidenceSource,
    diff_state,
    read_state_json,
    witness_effect_via_state_diff,
)


# --- the canonical diff --------------------------------------------------------

def test_diff_state_inserted_deleted_updated():
    before = {"a": 1, "b": 2, "c": 3}
    after = {"b": 2, "c": 99, "d": 4}
    d = diff_state(before, after)
    assert d.inserted == frozenset({"d"})
    assert d.deleted == frozenset({"a"})
    assert d.updated == frozenset({"c"})  # b unchanged
    assert d.changed == frozenset({"d", "c"})  # inserted ∪ updated, NOT deleted


def test_diff_state_empty():
    d = diff_state({}, {})
    assert d.inserted == d.deleted == d.updated == frozenset()


# --- the witness: present → CONFIRMED, absent → REFUTED ------------------------

def test_state_diff_confirms_inserted_key():
    before = {}
    after = {"quiz:Classic-Art-History": {"questions": 4}}
    claim = EffectClaim(key="quiz:Classic-Art-History", narrated="created the quiz")
    v = witness_effect_via_state_diff(claim, before, after)
    assert v.is_confirmed
    assert v.believe is True
    assert v.accountability is Accountability.OS_RECORDED


def test_state_diff_refutes_absent_key():
    """The agent claimed it created the quiz; the state delta does NOT contain it —
    the silent frontier-fail (docs/177) caught by a real read-back."""
    before = {"other": 1}
    after = {"other": 1, "something_else": 2}  # the claimed quiz is NOT here
    claim = EffectClaim(key="quiz:Classic-Art-History", narrated="created the quiz")
    v = witness_effect_via_state_diff(claim, before, after)
    assert v.is_refuted
    assert v.refuted is True
    assert v.believe is False


def test_state_diff_confirms_updated_key():
    before = {"orders:42": {"status": "pending"}}
    after = {"orders:42": {"status": "shipped"}}
    claim = EffectClaim(key="orders:42", narrated="marked order 42 shipped")
    v = witness_effect_via_state_diff(claim, before, after)
    assert v.is_confirmed


def test_state_diff_deleted_key_is_not_present():
    """A deleted entity is not 'changed' in the made-this-entity presence sense — a
    claim that an entity was CREATED is refuted if the entity is gone."""
    before = {"orders:42": 1}
    after = {}
    claim = EffectClaim(key="orders:42", narrated="created order 42")
    v = witness_effect_via_state_diff(claim, before, after)
    assert v.is_refuted  # not in inserted∪updated


def test_third_party_rung_passthrough():
    before, after = {}, {"k": 1}
    v = witness_effect_via_state_diff(
        EffectClaim(key="k"), before, after, accountability=Accountability.THIRD_PARTY
    )
    assert v.is_confirmed
    assert v.accountability is Accountability.THIRD_PARTY


# --- THE SOUNDNESS GUARD: an agent-authored snapshot is not a witness ----------

def test_agent_authored_snapshot_rejected():
    d = diff_state({}, {"k": 1})
    with pytest.raises(ValueError, match="non-forgeable"):
        StateDiffEvidenceSource(d, accountability=Accountability.AGENT_AUTHORED)


# --- the source's own gather: no key → NO_SIGNAL -------------------------------

def test_gather_blank_key_no_signal():
    src = StateDiffEvidenceSource(diff_state({}, {"k": 1}))
    facts = src.gather("   ", None)
    assert facts.stance.value == "NO_SIGNAL"
    assert facts.reachable is False


# --- the JSON snapshot reader + boundary fail-safe -----------------------------

def test_read_state_json_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"a": 1, "b": {"x": 2}}), encoding="utf-8")
    s = read_state_json(str(p))
    assert s == {"a": 1, "b": {"x": 2}}


def test_read_state_json_rejects_non_object(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError, match="not an object"):
        read_state_json(str(p))


def test_cli_unreadable_snapshot_is_unwitnessed(tmp_path, capsys):
    """The boundary fail-safe: a missing BEFORE snapshot must yield UNWITNESSED, NOT a
    fabricated empty delta (which would falsely refute the claim)."""
    from dos.drivers.state_diff import main
    after = tmp_path / "after.json"
    after.write_text(json.dumps({"k": 1}), encoding="utf-8")
    rc = main(["k", "--before", str(tmp_path / "nope.json"), "--after", str(after), "--json"])
    assert rc == 3  # UNWITNESSED exit
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "UNWITNESSED"
    assert out["believe"] is False
    assert out["refuted"] is False  # crucially NOT refuted


def test_cli_confirms_via_files(tmp_path, capsys):
    from dos.drivers.state_diff import main
    (tmp_path / "b.json").write_text(json.dumps({}), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps({"quiz:1": {"q": 4}}), encoding="utf-8")
    rc = main(["quiz:1", "--before", str(tmp_path / "b.json"), "--after", str(tmp_path / "a.json"), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "CONFIRMED"
    assert out["delta"]["inserted"] == ["quiz:1"]


# --- the one-way import litmus -------------------------------------------------

def test_kernel_effect_witness_does_not_import_driver():
    import inspect
    import dos.effect_witness as ew
    src = inspect.getsource(ew)
    assert "import dos.drivers" not in src
    assert "from dos.drivers" not in src

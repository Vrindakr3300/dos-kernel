"""Tests for `dos.lifecycle` — the plan-class taxonomy as data (docs/207 §5c)."""
from __future__ import annotations

import pytest

from dos import lifecycle as _lifecycle
from dos.lifecycle import LifecyclePolicy, LifecycleTransition, GENERIC_LIFECYCLE


def test_generic_default_is_active_done():
    assert GENERIC_LIFECYCLE.classes == ("active", "done")
    assert GENERIC_LIFECYCLE.default_class == "active"
    assert GENERIC_LIFECYCLE.legal_transition("active", "done")


def test_unknown_key_raises():
    with pytest.raises(ValueError):
        _lifecycle.policy_from_table({"bogus": 1})


def test_classes_must_be_nonempty_list():
    with pytest.raises(ValueError):
        _lifecycle.policy_from_table({"classes": []})


def test_transition_unknown_class_raises():
    with pytest.raises(ValueError):
        _lifecycle.policy_from_table({
            "classes": ["active", "done"],
            "transitions": [{"from": "active", "to": "ghost", "trigger": "t"}],
        })


def test_veto_class_must_be_known():
    with pytest.raises(ValueError):
        _lifecycle.policy_from_table({"classes": ["a", "b"], "veto_class": "z"})


def test_richer_taxonomy_parses():
    pol = _lifecycle.policy_from_table({
        "classes": ["draft", "active", "parked", "done"],
        "veto_class": "active",
        "max_transitions_per_cycle": 3,
        "per_plan_cooldown_hours": 48,
        "transitions": [
            {"from": "draft", "to": "active", "trigger": "demand", "auto": False},
            {"from": "active", "to": "parked", "trigger": "idle_30d", "auto": True},
        ],
    })
    assert pol.classes == ("draft", "active", "parked", "done")
    assert pol.veto_class == "active"
    assert pol.max_transitions_per_cycle == 3
    assert pol.per_plan_cooldown_hours == 48
    assert pol.legal_transition("active", "parked")
    assert any(t.auto for t in pol.transitions)


def test_load_from_toml(tmp_path):
    p = tmp_path / "dos.toml"
    p.write_text(
        "[lifecycle]\nclasses = [\"a\", \"b\", \"c\"]\n", encoding="utf-8")
    pol = _lifecycle.load_from_toml(p)
    assert pol.classes == ("a", "b", "c")


def test_load_from_toml_absent_is_base(tmp_path):
    assert _lifecycle.load_from_toml(tmp_path / "nope.toml") is GENERIC_LIFECYCLE


def test_to_dict_round_trips_shape():
    d = GENERIC_LIFECYCLE.to_dict()
    assert d["classes"] == ["active", "done"]
    assert d["transitions"][0]["trigger"] == "all_phases_shipped"


def test_config_carries_lifecycle():
    import dos.config as c
    cfg = c.default_config()
    assert isinstance(cfg.lifecycle, LifecyclePolicy)
    assert cfg.lifecycle.classes == ("active", "done")

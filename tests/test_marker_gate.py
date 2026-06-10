"""Unit tests for `dos.marker_gate` — the pure arming decision (docs/274).

The arming TRUTH TABLE (the docs/274 fix as a named function) + the `[marker]`
config loaders. `decide()` is pure (env injected), so the whole table is asserted
here without touching `os.environ` or any hook plumbing — the
`cmd_hook_marker`-level wiring is covered by `test_marker_sensor.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dos import marker_gate as mg


# ---------------------------------------------------------------------------
# 1. The policy defaults + validation.
# ---------------------------------------------------------------------------
def test_default_policy_is_interactive_safe():
    """The generic default arms ONLY by an explicit loop signal — never on an ordinary
    turn. max_streak 4 (the wait_marker_budget cap); the two built-in sentinels."""
    p = mg.DEFAULT_POLICY
    assert p.max_streak == 4
    assert p.arm_on_env == ("DOS_LOOP", "CID_RUN_ID")
    assert p.respect_stop_hook_active is True


def test_negative_max_streak_rejected():
    with pytest.raises(ValueError):
        mg.MarkerPolicy(max_streak=-1)


def test_arm_on_env_normalized_to_clean_tuple():
    """A list (from TOML) with blank/whitespace names normalizes to a tuple of clean
    names — so `decide`'s env walk is well-defined."""
    p = mg.MarkerPolicy(arm_on_env=["A", "  ", "B ", ""])
    assert p.arm_on_env == ("A", "B")


# ---------------------------------------------------------------------------
# 2. The arming truth table — decide() (the docs/274 fix).
# ---------------------------------------------------------------------------
def test_ordinary_turn_not_armed():
    """No --loop, no arming env → NOT armed (allow stop). The load-bearing fix: a bare
    Stop is an ordinary finished turn, not a poll."""
    d = mg.decide(stop_hook_active=False, loop_flag=False, env={})
    assert d.armed is False
    assert "no loop signal" in d.reason


def test_loop_flag_arms():
    d = mg.decide(stop_hook_active=False, loop_flag=True, env={})
    assert d.armed is True
    assert "--loop" in d.reason


@pytest.mark.parametrize("name", ["DOS_LOOP", "CID_RUN_ID"])
def test_builtin_env_arms(name: str):
    d = mg.decide(stop_hook_active=False, loop_flag=False, env={name: "1"})
    assert d.armed is True
    assert name in d.reason


def test_empty_env_value_does_not_arm():
    """A host that exports DOS_LOOP="" to UNSET it is honored — an empty value is not
    'present'."""
    d = mg.decide(stop_hook_active=False, loop_flag=False, env={"DOS_LOOP": ""})
    assert d.armed is False


def test_stop_hook_active_blocks_arming_even_with_loop():
    """docs/274 Case C — CC's infinite-loop backstop wins over every arming signal: an
    already-hook-continued stop is never re-blocked (checked FIRST)."""
    d = mg.decide(stop_hook_active=True, loop_flag=True, env={"DOS_LOOP": "1"})
    assert d.armed is False
    assert "stop_hook_active" in d.reason


def test_respect_stop_hook_active_false_overrides_backstop():
    """A host can opt OUT of the backstop (rarely correct) — then an active stop with a
    loop signal arms."""
    p = mg.MarkerPolicy(respect_stop_hook_active=False)
    d = mg.decide(stop_hook_active=True, loop_flag=True, env={}, policy=p)
    assert d.armed is True


def test_custom_sentinel_arms_and_builtins_do_not():
    """A custom arm_on_env REPLACES the built-ins: the named sentinel arms, the default
    DOS_LOOP no longer does."""
    p = mg.MarkerPolicy(arm_on_env=("MY_LOOP",))
    assert mg.decide(stop_hook_active=False, loop_flag=False, env={"MY_LOOP": "1"}, policy=p).armed is True
    assert mg.decide(stop_hook_active=False, loop_flag=False, env={"DOS_LOOP": "1"}, policy=p).armed is False


def test_empty_arm_on_env_only_flag_arms():
    """arm_on_env=() means no env arms it — only the explicit --loop flag does."""
    p = mg.MarkerPolicy(arm_on_env=())
    assert mg.decide(stop_hook_active=False, loop_flag=False, env={"DOS_LOOP": "1"}, policy=p).armed is False
    assert mg.decide(stop_hook_active=False, loop_flag=True, env={}, policy=p).armed is True


# ---------------------------------------------------------------------------
# 3. The config loaders — policy_from_table / load_from_toml.
# ---------------------------------------------------------------------------
def test_policy_from_table_full():
    t = {"max_streak": 2, "arm_on_env": ["MY_LOOP"], "respect_stop_hook_active": False}
    p = mg.policy_from_table(t)
    assert p.max_streak == 2
    assert p.arm_on_env == ("MY_LOOP",)
    assert p.respect_stop_hook_active is False


def test_policy_from_table_partial_inherits_base():
    """A partial table tunes only what it names; the rest inherits base."""
    p = mg.policy_from_table({"max_streak": 7})
    assert p.max_streak == 7
    assert p.arm_on_env == mg.DEFAULT_POLICY.arm_on_env
    assert p.respect_stop_hook_active is True


def test_policy_from_table_scalar_arm_on_env():
    """A scalar string arm_on_env is accepted as a single name (the one-sentinel case)."""
    p = mg.policy_from_table({"arm_on_env": "SOLO"})
    assert p.arm_on_env == ("SOLO",)


def test_policy_from_table_empty_returns_base():
    assert mg.policy_from_table({}) is mg.DEFAULT_POLICY


def test_policy_from_table_malformed_raises():
    with pytest.raises(ValueError):
        mg.policy_from_table({"max_streak": -3})


def test_load_from_toml_absent_file_returns_base(tmp_path: Path):
    assert mg.load_from_toml(tmp_path / "nope.toml") is mg.DEFAULT_POLICY


def test_load_from_toml_no_marker_table_returns_base(tmp_path: Path):
    p = tmp_path / "dos.toml"
    p.write_text("[lanes]\n", encoding="utf-8")
    assert mg.load_from_toml(p) is mg.DEFAULT_POLICY


def test_load_from_toml_reads_marker_table(tmp_path: Path):
    p = tmp_path / "dos.toml"
    p.write_text(
        '[marker]\nmax_streak = 3\narm_on_env = ["A", "B"]\nrespect_stop_hook_active = false\n',
        encoding="utf-8",
    )
    pol = mg.load_from_toml(p)
    assert pol.max_streak == 3
    assert pol.arm_on_env == ("A", "B")
    assert pol.respect_stop_hook_active is False


def test_load_from_toml_strips_bom(tmp_path: Path):
    """A PowerShell-written BOM must not break the read (the reasons/tool_stream fix)."""
    p = tmp_path / "dos.toml"
    p.write_text("[marker]\nmax_streak = 5\n", encoding="utf-8-sig")
    assert mg.load_from_toml(p).max_streak == 5


def test_load_from_toml_layers_over_explicit_base(tmp_path: Path):
    """A present table layers over the passed base, not just the generic default."""
    base = mg.MarkerPolicy(max_streak=9, arm_on_env=("KEEP",), respect_stop_hook_active=False)
    p = tmp_path / "dos.toml"
    p.write_text("[marker]\nmax_streak = 1\n", encoding="utf-8")  # only max_streak named
    pol = mg.load_from_toml(p, base=base)
    assert pol.max_streak == 1
    assert pol.arm_on_env == ("KEEP",)  # inherited from base
    assert pol.respect_stop_hook_active is False  # inherited from base

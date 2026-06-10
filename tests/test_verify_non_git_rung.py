"""The non-git evidence rung wired into `verify()` (docs/265).

`verify()` certifies *a commit of the right shape is reachable* (docs/183: git
necessary, not sufficient). A clean `verify` never means *the build is green*. This
plan layers a **conjunctive, opt-in, accountability-only** non-git rung on top: a
GREEN CI verdict at the very commit the git rung found upgrades the verdict's
`source` to ``"ci-green"``; a RED one withholds that upgrade; silence
(NO_SIGNAL/PENDING) degrades to the git answer, byte-identical.

The one safety property the whole seam stands on (docs/265 §1): **a non-git rung may
make `verify` answer MORE skeptically, never more permissively** — it is applied
ONLY to a `shipped=True` git verdict, so green CI without a reachable commit
manufactures NOTHING. These tests pin that asymmetry on frozen data (no `gh`), plus
the byte-identical-when-unconfigured contract and the resolve-by-name boundary.
"""

from __future__ import annotations

import argparse

import pytest

from dos import cli, oracle
from dos.oracle import NonGitRung, ShipVerdict, _apply_non_git_rung


# ---------------------------------------------------------------------------
# The pure fold — `_apply_non_git_rung`. PURE, no I/O, frozen data.
# ---------------------------------------------------------------------------


def test_green_ci_never_promotes_a_false_git_verdict():
    """THE §1 invariant: git `shipped=False` + GREEN CI STAYS `shipped=False`.

    Green CI without a reachable commit manufactures nothing — there is no artefact
    for CI to be green *about*. This is the conjunctive (never disjunctive) law: the
    git rung is the necessary gate; the non-git rung is an upgrade layered on top,
    never a way in."""
    git_false = ShipVerdict(plan="P", phase="1", shipped=False, source="none")
    green = NonGitRung(source="ci-green", reason="all checks green", state="GREEN")
    out = _apply_non_git_rung(git_false, green)
    assert out.shipped is False
    assert out.source == "none"  # untouched — no upgrade, no manufactured ship
    assert out == git_false


def test_shipped_plus_green_upgrades_source_to_ci_green():
    """git `shipped=True` + GREEN → `source="ci-green"` (the accountability upgrade)."""
    git_true = ShipVerdict(plan="P", phase="1", shipped=True, source="grep-subject", sha="abc123")
    green = NonGitRung(source="ci-green", reason="checks green at abc123", state="GREEN")
    out = _apply_non_git_rung(git_true, green)
    assert out.shipped is True
    assert out.source == "ci-green"          # upgraded
    assert "checks green at abc123" in out.summary  # the why is legible
    assert out.sha == "abc123"               # everything else preserved


def test_shipped_plus_red_withholds_the_upgrade_and_flags():
    """git `shipped=True` + RED → NOT upgraded (ship stands), but flagged.

    The ship is real (git is the necessary gate), so `shipped` stays True and the git
    `source` is kept; the upgrade is WITHHELD and a marker is stamped so a host MAY
    route a decision off the flagged-but-unchanged state (docs/265 §2b)."""
    git_true = ShipVerdict(plan="P", phase="1", shipped=True, source="grep-subject", sha="abc123")
    red = NonGitRung(source="ci-green", reason="2 checks failed", state="RED")
    out = _apply_non_git_rung(git_true, red)
    assert out.shipped is True               # the ship stands — git is necessary
    assert out.source == "grep-subject"      # NOT upgraded
    assert "WITHHELD" in out.summary         # flagged for a host decision
    assert "2 checks failed" in out.summary


@pytest.mark.parametrize("state", ["NO_SIGNAL", "PENDING", "WHATEVER", ""])
def test_silence_degrades_to_git_byte_identical(state):
    """NO_SIGNAL / PENDING / unknown / empty state → the git verdict, byte-identical.

    No CI wired, a commit with no checks yet, an in-flight build, an unexpected word:
    every non-{GREEN,RED} state passes the git verdict through unchanged."""
    git_true = ShipVerdict(plan="P", phase="1", shipped=True, source="registry", sha="abc123",
                           summary="orig summary", rung="file-path")
    out = _apply_non_git_rung(git_true, NonGitRung(source="ci-green", reason="r", state=state))
    assert out == git_true  # byte-identical


def test_none_rung_is_identity():
    """No rung supplied → identity (the gate-OFF convention; byte-identical)."""
    git_true = ShipVerdict(plan="P", phase="1", shipped=True, source="grep-artifact", sha="abc")
    assert _apply_non_git_rung(git_true, None) == git_true
    git_false = ShipVerdict(plan="P", phase="1", shipped=False, source="none")
    assert _apply_non_git_rung(git_false, None) == git_false


# ---------------------------------------------------------------------------
# Threaded through is_shipped / batch_is_shipped (the pure core, injected state).
# ---------------------------------------------------------------------------


def _registry_state(plan: str, phase: str, sha: str = "deadbeef") -> dict:
    """A minimal execution-state with one `recently_completed status:done` row."""
    return {"recently_completed": [
        {"plan": plan, "phase": phase, "status": "done", "commit_sha": sha},
    ]}


def test_is_shipped_default_off_is_byte_identical():
    """`is_shipped` with no `non_git_rung` is byte-identical to before (gate OFF)."""
    state = _registry_state("P", "1")
    without = oracle.is_shipped("P", "1", state=state)
    with_none = oracle.is_shipped("P", "1", state=state, non_git_rung=None)
    assert without == with_none
    assert without.shipped is True and without.source == "registry"


def test_is_shipped_registry_hit_plus_green_upgrades():
    """A registry `status:done` ship + GREEN rung → upgraded to `ci-green`."""
    state = _registry_state("P", "1")
    green = NonGitRung(source="ci-green", reason="green", state="GREEN")
    v = oracle.is_shipped("P", "1", state=state, non_git_rung=green)
    assert v.shipped is True
    assert v.source == "ci-green"


def test_is_shipped_registry_miss_plus_green_stays_unshipped():
    """A registry MISS (no grep fallback) + GREEN rung → STAYS `shipped=False`.

    The conjunctive invariant through the real entry point: with no git ship to
    stand on, green CI cannot manufacture one (`source='none'` unchanged)."""
    green = NonGitRung(source="ci-green", reason="green", state="GREEN")
    v = oracle.is_shipped("NOPE", "9", state={}, non_git_rung=green)
    assert v.shipped is False
    assert v.source == "none"


def test_batch_is_shipped_per_pair_rungs():
    """`batch_is_shipped` folds a PER-PAIR rung map; a pair with no entry is untouched."""
    state = {"recently_completed": [
        {"plan": "P", "phase": "1", "status": "done", "commit_sha": "aaa"},
        {"plan": "P", "phase": "2", "status": "done", "commit_sha": "bbb"},
    ]}
    rungs = {
        ("P", "1"): NonGitRung(source="ci-green", reason="green", state="GREEN"),
        ("P", "2"): NonGitRung(source="ci-green", reason="red", state="RED"),
        # ("P", "3") deliberately absent
    }
    out = oracle.batch_is_shipped(
        [("P", "1"), ("P", "2"), ("P", "3")], state=state, non_git_rungs=rungs)
    assert out[("P", "1")].source == "ci-green"        # GREEN upgrade
    assert out[("P", "2")].source == "registry"        # RED → not upgraded
    assert "WITHHELD" in out[("P", "2")].summary       # but flagged
    # ("P","3") is a registry miss → shipped=False/source=none, no rung entry anyway
    assert out[("P", "3")].shipped is False


def test_batch_default_off_byte_identical():
    """`batch_is_shipped` with no `non_git_rungs` is byte-identical to before."""
    state = _registry_state("P", "1")
    without = oracle.batch_is_shipped([("P", "1")], state=state)
    with_none = oracle.batch_is_shipped([("P", "1")], state=state, non_git_rungs=None)
    assert without == with_none


# ---------------------------------------------------------------------------
# The boundary — `cmd_verify` resolves the driver BY NAME, never a static import.
# ---------------------------------------------------------------------------


def _verify_ns(**kw):
    base = dict(workspace=".", plan="P", phase="1", json=True, no_ci=False,
                output=None, explain=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _arm_config(monkeypatch, *, non_git_oracle: str = "", ci: dict | None = None):
    """Install an active `SubstrateConfig` with the non-git wiring set.

    `SubstrateConfig` is FROZEN, so the wiring can't be monkeypatched onto a field —
    we build a real config with `dataclasses.replace` and `set_active` it (restored by
    monkeypatch.undo). This is the honest shape: the field is set the way
    `load_workspace_config` would set it from a `[verify]` table."""
    import dataclasses

    import dos.config as _config

    cfg = dataclasses.replace(
        _config.active(), non_git_oracle=non_git_oracle, ci=ci or {})
    monkeypatch.setattr(_config, "active", lambda: cfg)
    return cfg


class _FakeCiVerdict:
    """Duck-types `CiVerdict` enough for `_gather_non_git_rung` (a `.verdict.value`
    + `.reason`)."""
    def __init__(self, state: str, reason: str = "fake"):
        self.verdict = type("V", (), {"value": state})()
        self.reason = reason


class _FakeDriver:
    """A stand-in `dos.evidence_sources` driver exposing the CI-shaped `status_of`."""
    def __init__(self, state: str):
        self._state = state
        self.calls: list[str] = []

    def status_of(self, sha, repo=None, **kw):
        self.calls.append(sha)
        return _FakeCiVerdict(self._state)


def test_cmd_verify_resolves_driver_by_name_and_upgrades(capsys, monkeypatch):
    """A wired `[verify] non_git_oracle` makes `cmd_verify` reach the driver BY NAME
    (a monkeypatched resolver, never a static import) and upgrade a real ship.

    Pins docs/265 §6's "resolved by name at the boundary" + the GREEN→ci-green wire,
    on frozen data (the fake driver never calls `gh`)."""

    fake = _FakeDriver("GREEN")
    # The git rung says SHIPPED at a known sha; the driver is resolved by name.
    monkeypatch.setattr(
        oracle, "is_shipped",
        lambda plan, phase, **kw: ShipVerdict(
            plan=plan, phase=phase, shipped=True, source="grep-subject", sha="abc123"))
    monkeypatch.setattr(cli, "_load_witness_driver", lambda name: fake)
    _arm_config(monkeypatch, non_git_oracle="ci_status")
    monkeypatch.setattr(cli, "_apply_workspace", lambda args: None)

    rc = cli.cmd_verify(_verify_ns())
    out = capsys.readouterr().out
    assert rc == 0
    assert '"source": "ci-green"' in out  # the CI upgrade reached the rendered verdict
    assert fake.calls == ["abc123"]       # the driver was consulted on the git sha


def test_cmd_verify_unwired_skips_the_rung(capsys, monkeypatch):
    """No `[verify] non_git_oracle` → the rung is never gathered (git-only, byte-id).

    The driver resolver must not even be CALLED when nothing is wired — the
    byte-identical-when-unconfigured contract at the boundary."""

    monkeypatch.setattr(
        oracle, "is_shipped",
        lambda plan, phase, **kw: ShipVerdict(
            plan=plan, phase=phase, shipped=True, source="grep-subject", sha="abc123"))

    def _boom(name):
        raise AssertionError("driver resolver must not be called when unwired")
    monkeypatch.setattr(cli, "_load_witness_driver", _boom)
    _arm_config(monkeypatch, non_git_oracle="")
    monkeypatch.setattr(cli, "_apply_workspace", lambda args: None)

    rc = cli.cmd_verify(_verify_ns())
    out = capsys.readouterr().out
    assert rc == 0
    assert '"source": "grep-subject"' in out  # the git verdict, untouched


def test_cmd_verify_no_ci_flag_forces_git_only(capsys, monkeypatch):
    """`--no-ci` skips the rung even when wired (the fast-path opt-out)."""

    def _boom(name):
        raise AssertionError("--no-ci must skip the driver entirely")
    monkeypatch.setattr(
        oracle, "is_shipped",
        lambda plan, phase, **kw: ShipVerdict(
            plan=plan, phase=phase, shipped=True, source="grep-subject", sha="abc123"))
    monkeypatch.setattr(cli, "_load_witness_driver", _boom)
    _arm_config(monkeypatch, non_git_oracle="ci_status")
    monkeypatch.setattr(cli, "_apply_workspace", lambda args: None)

    rc = cli.cmd_verify(_verify_ns(no_ci=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert '"source": "grep-subject"' in out


def test_cmd_verify_red_ci_withholds_but_ship_stands(capsys, monkeypatch):
    """A wired RED oracle does NOT demote `shipped` — the ship stands, flagged.

    docs/265 §2b: RED withholds the accountability UPGRADE; it never reverses the git
    ship (exit code stays SHIPPED=0). Phase 2 may later route a decision off the flag,
    but `verify`'s answer to "did it ship?" is git's, conjunctively un-loosened."""

    fake = _FakeDriver("RED")
    monkeypatch.setattr(
        oracle, "is_shipped",
        lambda plan, phase, **kw: ShipVerdict(
            plan=plan, phase=phase, shipped=True, source="grep-subject", sha="abc123"))
    monkeypatch.setattr(cli, "_load_witness_driver", lambda name: fake)
    _arm_config(monkeypatch, non_git_oracle="ci_status")
    monkeypatch.setattr(cli, "_apply_workspace", lambda args: None)

    rc = cli.cmd_verify(_verify_ns())
    out = capsys.readouterr().out
    assert rc == 0  # SHIPPED — the ship stands
    assert '"source": "grep-subject"' in out  # NOT upgraded


def test_cmd_verify_unshipped_never_gathers_ci(capsys, monkeypatch):
    """A git `shipped=False` verdict never consults CI — there is no commit to check.

    The §1 invariant at the boundary: the rung is gated on `verify.shipped`, so an
    unshipped phase short-circuits before any (even wired) driver is reached."""

    def _boom(name):
        raise AssertionError("an unshipped git verdict must not gather CI")
    monkeypatch.setattr(
        oracle, "is_shipped",
        lambda plan, phase, **kw: ShipVerdict(
            plan=plan, phase=phase, shipped=False, source="none"))
    monkeypatch.setattr(cli, "_load_witness_driver", _boom)
    _arm_config(monkeypatch, non_git_oracle="ci_status")
    monkeypatch.setattr(cli, "_apply_workspace", lambda args: None)

    rc = cli.cmd_verify(_verify_ns())
    out = capsys.readouterr().out
    assert rc == 1  # NOT_SHIPPED
    assert '"source": "none"' in out


def test_gather_non_git_rung_failsafe_on_raise(monkeypatch):
    """A driver that RAISES yields a `None` rung — fail-safe, the git verdict as-is.

    A broken/unreachable oracle can only LEAVE the git answer, never redden or
    fabricate it (the `ci_status`/`run_judge` fail-to-abstain posture at the
    boundary)."""

    class _Raises:
        def status_of(self, sha, **kw):
            raise RuntimeError("provider exploded")

    monkeypatch.setattr(cli, "_load_witness_driver", lambda name: _Raises())
    cfg = _arm_config(monkeypatch, non_git_oracle="ci_status")
    assert cli._gather_non_git_rung(cfg, "abc123") is None


def test_gather_non_git_rung_none_for_non_ci_source(monkeypatch):
    """A wired source with no CI-shaped `status_of` (a paste/log source) → None.

    `verify`'s conjunctive rung consumes a GREEN/RED/PENDING verdict; a source that
    can't produce one is simply not consulted here (it stays a JUDGE hint)."""

    class _NoStatusOf:  # e.g. PasteLogSource — has `gather`, no `status_of`
        def gather(self, subject, config):
            return None

    monkeypatch.setattr(cli, "_load_witness_driver", lambda name: _NoStatusOf())
    cfg = _arm_config(monkeypatch, non_git_oracle="paste_log")
    assert cli._gather_non_git_rung(cfg, "abc123") is None

"""docs/296 — the operator-armed SELF_MODIFY override window.

The verdict is NOT under test here — a tool call hitting the kernel's runtime
files still classifies SELF_MODIFY, armed window or not. What these tests pin
is the ENFORCEMENT disposition (PDP decides; PEP disposes) and its fail-closed
perimeter:

  * `read_override` can only fail toward None (missing/garbled/incomplete arm
    file → the deny stands, byte-identical);
  * `dispose` converts ONLY a SELF_MODIFY refusal, only inside the window,
    and — when scoped — only for provably in-scope targets;
  * the hook emits the admit as ALLOW-with-note (`additionalContext`, never a
    silent pass) and journals a distinct `override-admit` decision;
  * the arm path itself is write-DENIED for agents even inside an armed
    window (a window must not extend itself), and there is no arm verb —
    `dos override` offers status/disarm only.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path

from dos import config as _config
from dos import override_facts as ovr
from dos import pretool_sensor as prt


NOW = dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc)
LATER = "2026-06-10T13:00:00Z"     # one hour inside the window
EARLIER = "2026-06-10T11:00:00Z"   # already expired at NOW


def _arm(root: Path, *, until: str = LATER, reason: str = "test window",
         scope: list[str] | None = None, raw: str | None = None) -> Path:
    p = ovr.arm_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        p.write_text(raw, encoding="utf-8")
        return p
    lines = [f"until = {until}", f'reason = "{reason}"']
    if scope is not None:
        # TOML literal strings (single quotes): no escape processing, so a
        # Windows backslash in a scope entry survives verbatim.
        entries = ", ".join(f"'{s}'" for s in scope)
        lines.append(f"scope = [{entries}]")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _kernel_cfg(tmp_path: Path):
    """The test_hook_pretool fixture: workspace facts that declare the runtime
    set, so SELF_MODIFY fires deterministically under a tmp root."""
    cfg = _config.default_config(tmp_path)
    facts = _config.WorkspaceFacts(
        root=tmp_path,
        kernel_runtime_files=("src/dos/arbiter.py", "src/dos/admission.py",
                              "src/dos/self_modify.py"),
        is_kernel_repo=True,
    )
    return dataclasses.replace(cfg, workspace=facts)


def _event(tool_name="Write", tool_input=None, **extra):
    e = {"tool_name": tool_name, "session_id": "S1",
         "tool_input": tool_input if tool_input is not None else {}}
    e.update(extra)
    return e


# ==========================================================================
# read_override — every malformed branch folds to None (fail-closed).
# ==========================================================================
def test_reader_missing_file_is_none(tmp_path):
    assert ovr.read_override(tmp_path) is None


def test_reader_garbled_toml_is_none(tmp_path):
    _arm(tmp_path, raw="this is { not toml\n")
    assert ovr.read_override(tmp_path) is None


def test_reader_missing_until_or_reason_is_none(tmp_path):
    _arm(tmp_path, raw='reason = "no deadline"\n')
    assert ovr.read_override(tmp_path) is None
    _arm(tmp_path, raw=f"until = {LATER}\n")  # no reason
    assert ovr.read_override(tmp_path) is None
    _arm(tmp_path, raw=f'until = {LATER}\nreason = "   "\n')  # blank reason
    assert ovr.read_override(tmp_path) is None


def test_reader_bad_scope_type_is_none(tmp_path):
    _arm(tmp_path, raw=f'until = {LATER}\nreason = "x"\nscope = "not-a-list"\n')
    assert ovr.read_override(tmp_path) is None


def test_reader_good_file_parses_aware_until_and_normalized_scope(tmp_path):
    _arm(tmp_path, scope=["src/dos/Arbiter.py", "./tests\\"])
    facts = ovr.read_override(tmp_path)
    assert facts is not None
    assert facts.until.tzinfo is not None
    assert facts.reason == "test window"
    assert facts.scope == ("src/dos/arbiter.py", "tests")


# ==========================================================================
# dispose — the pure truth table.
# ==========================================================================
def _facts(until: str = LATER, scope: tuple[str, ...] = ()) -> ovr.OverrideFacts:
    return ovr.OverrideFacts(
        until=dt.datetime.fromisoformat(until), reason="r", scope=scope)


def test_dispose_none_facts_is_none():
    assert ovr.dispose("SELF_MODIFY", ("src/dos/arbiter.py",), None, now=NOW) is None


def test_dispose_only_converts_self_modify():
    f = _facts()
    assert ovr.dispose("SELF_MODIFY", ("src/dos/arbiter.py",), f, now=NOW)
    # A collision/budget/any-other refusal is never waved through.
    assert ovr.dispose("", ("src/dos/arbiter.py",), f, now=NOW) is None
    assert ovr.dispose("CLASS_BUDGET_EXHAUSTED", ("x",), f, now=NOW) is None


def test_dispose_expired_window_is_none():
    assert ovr.dispose("SELF_MODIFY", ("src/dos/arbiter.py",),
                       _facts(until=EARLIER), now=NOW) is None


def test_dispose_scope_gates_targets():
    scoped = _facts(scope=("src/dos/arbiter.py",))
    assert ovr.dispose("SELF_MODIFY", ("src/dos/arbiter.py",), scoped, now=NOW)
    # Out-of-scope target → the deny stands.
    assert ovr.dispose("SELF_MODIFY", ("src/dos/reasons.py",), scoped, now=NOW) is None
    # Mixed targets: ALL must be in scope.
    assert ovr.dispose("SELF_MODIFY",
                       ("src/dos/arbiter.py", "src/dos/reasons.py"),
                       scoped, now=NOW) is None
    # A scoped window with an unparseable footprint stays denied (cannot prove
    # the targets are inside the scope) — but an UNSCOPED window admits it.
    assert ovr.dispose("SELF_MODIFY", (), scoped, now=NOW) is None
    assert ovr.dispose("SELF_MODIFY", (), _facts(), now=NOW)


def test_dispose_scope_directory_entry_covers_children():
    scoped = _facts(scope=("src/dos",))
    assert ovr.dispose("SELF_MODIFY", ("src/dos/arbiter.py",), scoped, now=NOW)
    assert ovr.dispose("SELF_MODIFY", ("srcX/other.py",), scoped, now=NOW) is None


def test_dispose_note_names_deadline_reason_and_disarm():
    note = ovr.dispose("SELF_MODIFY", ("src/dos/arbiter.py",), _facts(), now=NOW)
    assert "operator override" in note
    assert "r" in note and "dos override disarm" in note


# ==========================================================================
# decide() — the hook disposition end to end (the PEP side).
# ==========================================================================
def test_unarmed_self_modify_still_denies(tmp_path):
    cfg = _kernel_cfg(tmp_path)
    dialect, outcome = prt.decide(
        _event("Write", {"file_path": "src/dos/arbiter.py"}), cfg)
    assert outcome["decision"] == "deny"
    assert outcome["reason_class"] == "SELF_MODIFY"
    assert dialect["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_armed_window_converts_deny_to_allow_with_note(tmp_path):
    cfg = _kernel_cfg(tmp_path)
    _arm(tmp_path, until="2099-01-01T00:00:00Z", reason="docs/296 e2e")
    dialect, outcome = prt.decide(
        _event("Write", {"file_path": "src/dos/arbiter.py"}), cfg)
    # The admit is distinct and on the record — never a silent passthrough.
    assert outcome["decision"] == "override-admit"
    assert outcome["reason_class"] == "SELF_MODIFY"  # the verdict is unchanged
    hso = dialect["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert "permissionDecision" not in hso  # ALLOW = no deny key, CC proceeds
    assert "operator override" in hso["additionalContext"]
    assert "docs/296 e2e" in hso["additionalContext"]


def test_expired_window_restores_the_deny(tmp_path):
    cfg = _kernel_cfg(tmp_path)
    _arm(tmp_path, until="2001-01-01T00:00:00Z", reason="long gone")
    dialect, outcome = prt.decide(
        _event("Write", {"file_path": "src/dos/arbiter.py"}), cfg)
    assert outcome["decision"] == "deny"
    assert dialect["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_scoped_window_denies_out_of_scope_target(tmp_path):
    cfg = _kernel_cfg(tmp_path)
    _arm(tmp_path, until="2099-01-01T00:00:00Z", reason="scoped",
         scope=["src/dos/admission.py"])
    dialect, outcome = prt.decide(
        _event("Write", {"file_path": "src/dos/arbiter.py"}), cfg)
    assert outcome["decision"] == "deny"


def test_arm_path_write_is_denied_even_while_armed(tmp_path):
    """The perimeter: a window must not be able to extend itself."""
    cfg = _kernel_cfg(tmp_path)
    _arm(tmp_path, until="2099-01-01T00:00:00Z", reason="open window")
    dialect, outcome = prt.decide(
        _event("Write", {"file_path": ".dos/override/self-modify.toml"}), cfg)
    assert outcome["decision"] == "deny"
    assert outcome["reason_class"] == "SELF_MODIFY"
    assert "only the operator arms" in outcome["reason"]
    assert dialect["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_arm_path_deny_fires_in_foreign_repos_too(tmp_path):
    """The perimeter is request-absolute: it guards the arm file even where
    SELF_MODIFY itself cannot fire (no kernel runtime files under the root)."""
    cfg = _config.default_config(tmp_path)
    dialect, outcome = prt.decide(
        _event("Write", {"file_path": ".dos/override/self-modify.toml"}), cfg)
    assert outcome["decision"] == "deny"


# ==========================================================================
# the CLI verb — status / disarm only (no arm verb, by design).
# ==========================================================================
def _cli_override(tmp_path: Path, *argv: str):
    import io
    import sys as _sys
    from dos import cli
    # Drive through main() so the parser wiring (subcommand, flags) is pinned.
    # `--workspace` sits on the `override` parent parser, so it goes BEFORE the
    # status/disarm subcommand token (the lease-lane flag-placement rule).
    out = io.StringIO()
    old = _sys.stdout
    _sys.stdout = out
    try:
        rc = cli.main(["override", "--workspace", str(tmp_path), *argv])
    except SystemExit as e:  # argparse exits
        rc = int(e.code or 0)
    finally:
        _sys.stdout = old
    return out.getvalue(), rc


def test_cli_status_disarmed_then_armed_then_disarm(tmp_path):
    out, rc = _cli_override(tmp_path, "status")
    assert rc == 1
    assert json.loads(out)["armed"] is False

    _arm(tmp_path, until="2099-01-01T00:00:00Z", reason="window for tests")
    out, rc = _cli_override(tmp_path, "status")
    assert rc == 0
    body = json.loads(out)
    assert body["armed"] is True and body["reason"] == "window for tests"

    out, rc = _cli_override(tmp_path, "disarm")
    assert rc == 0
    assert json.loads(out)["disarmed"] is True

    out, rc = _cli_override(tmp_path, "status")
    assert rc == 1


def test_cli_offers_no_arm_subcommand(tmp_path):
    """The asymmetry is the security property: anyone may disarm, only the
    human arms (by hand, on the file). An `arm` subcommand must not exist."""
    import pytest
    with pytest.raises(SystemExit) as exc:
        from dos import cli
        cli.main(["override", "arm", "--workspace", str(tmp_path)])
    assert exc.value.code != 0

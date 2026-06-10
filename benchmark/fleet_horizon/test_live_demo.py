"""Tests for the LIVE multi-vendor demo (`live_demo.py`).

Two layers, matching the demo's own split:

  * the DEMO LOGIC — parse a worker's ship-claim, let the harness own ground
    truth, adjudicate with the real `dos.oracle.is_shipped`, and flag an
    over-claim — is tested DETERMINISTICALLY by stubbing the CLI call. This proves
    the kernel catches a live-shaped over-claim regardless of which vendor emitted
    it, with no tokens spent and no flakiness. It is a real gate.
  * the LIVE INTEGRATION — actually shelling `claude`/`gemini`/`codex` — runs only
    when `DOS_LIVE_DEMO=1` AND the CLI is on PATH, else SKIPS. It is a smoke test
    of the wiring, never a deterministic gate (the model's output is not fixed).

This mirrors the project posture: the falsifiable claim is deterministic; the live
call is an opt-in smoke (see `live_demo.py`'s module docstring and `agent.py:8-18`).

    PYTHONPATH=src python -m pytest benchmark/fleet_horizon/test_live_demo.py -q
"""
from __future__ import annotations

import os

import pytest

from . import live_demo


# --------------------------------------------------------------------------- #
# parsing — tolerant, vendor-blind
# --------------------------------------------------------------------------- #

def test_parse_ship_claim():
    c = live_demo._parse_claim("gemini", "GEM.00",
                               "VERDICT: shipped\nSHA: abc1234")
    assert c.claimed_shipped is True
    assert c.claimed_sha == "abc1234"


def test_parse_blocked_and_offformat_default_to_no_claim():
    assert live_demo._parse_claim("codex", "COD.00",
                                  "VERDICT: blocked\nSHA: NONE").claimed_shipped is False
    # a chatty / off-format reply degrades to 'no claim', never crashes.
    assert live_demo._parse_claim("claude", "CLA.00",
                                  "sure! I think it's done :)").claimed_shipped is False
    assert live_demo._parse_claim("claude", "CLA.00", None).claimed_shipped is False


# --------------------------------------------------------------------------- #
# the demo logic — DOS catches a live-shaped over-claim, deterministically
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("vendor", ["claude", "gemini", "codex"])
def test_kernel_catches_overclaim_for_any_vendor(vendor, tmp_path, monkeypatch):
    """The heart of the live demo, made deterministic: stub the CLI so the 'model'
    ALWAYS claims shipped. The harness commits only every 2nd phase. DOS must rule
    the uncommitted phases NOT shipped → caught over-claims — identically for every
    vendor, because the verdict reads git, not the (stubbed) model's word."""
    # the 'model' always over-claims, whatever the vendor.
    monkeypatch.setattr(live_demo, "_call_cli",
                        lambda cmd, prompt, **kw: "VERDICT: shipped\nSHA: deadbee")
    repo = tmp_path / "repo"
    repo.mkdir()
    live_demo._init_repo(repo)

    verdicts = live_demo.run_vendor(vendor, repo, phases=4, commit_every=2)
    # phases 0 and 2 were really committed by the harness → oracle confirms ship,
    # NOT caught (the claim happens to be true). phases 1 and 3 were not committed
    # → the always-shipped claim is a caught over-claim.
    committed = [v for v in verdicts if v.really_committed]
    uncommitted = [v for v in verdicts if not v.really_committed]
    assert committed and uncommitted, "expected a mix of committed/uncommitted"
    assert all(v.verdict_shipped and not v.caught_lie for v in committed)
    assert all((not v.verdict_shipped) and v.caught_lie for v in uncommitted), (
        "DOS failed to catch an over-claim on an uncommitted phase")


def test_overclaim_verdict_is_vendor_invariant(tmp_path, monkeypatch):
    """Run the SAME stubbed over-claimer as claude, gemini, AND codex against fresh
    repos and confirm the caught-lie pattern is identical across vendors — the
    kernel's catch does not depend on the vendor label at all."""
    monkeypatch.setattr(live_demo, "_call_cli",
                        lambda cmd, prompt, **kw: "VERDICT: shipped\nSHA: NONE")
    patterns = {}
    for vendor in ("claude", "gemini", "codex"):
        repo = tmp_path / vendor
        repo.mkdir()
        live_demo._init_repo(repo)
        vs = live_demo.run_vendor(vendor, repo, phases=5, commit_every=2)
        patterns[vendor] = tuple(v.caught_lie for v in vs)
    assert len(set(patterns.values())) == 1, f"vendor-dependent catch: {patterns}"


def test_honest_worker_is_not_flagged(tmp_path, monkeypatch):
    """Symmetry / no-false-positive: a worker that claims shipped ONLY when the
    harness actually committed is never flagged. DOS does not invent over-claims —
    it confirms the true ones and catches only the false ones (the conservation
    property, live-shaped)."""
    # honest model: we cannot see `really` from inside the stub, so emit 'blocked'
    # unconditionally — then NOTHING is claimed shipped, so nothing is ever caught,
    # and the committed phases still verify as shipped (claim-independent).
    monkeypatch.setattr(live_demo, "_call_cli",
                        lambda cmd, prompt, **kw: "VERDICT: blocked\nSHA: NONE")
    repo = tmp_path / "repo"
    repo.mkdir()
    live_demo._init_repo(repo)
    vs = live_demo.run_vendor("gemini", repo, phases=4, commit_every=2)
    assert all(not v.caught_lie for v in vs), "flagged a worker that never claimed"
    # the harness-committed phases are still ground-truth shipped per the oracle.
    assert any(v.verdict_shipped for v in vs)


# --------------------------------------------------------------------------- #
# CLI plumbing
# --------------------------------------------------------------------------- #

def test_main_is_gated_off_without_optin(capsys, monkeypatch):
    """Without DOS_LIVE_DEMO=1 (and no --force), main() refuses to call any CLI and
    exits 0 with an explanation — so a stray invocation never spends tokens."""
    monkeypatch.delenv("DOS_LIVE_DEMO", raising=False)
    rc = live_demo.main(["--vendors", "claude,gemini,codex"])
    assert rc == 0
    assert "gated off" in capsys.readouterr().out


def test_main_with_no_installed_vendor_exits_clean(capsys, monkeypatch):
    """Forced on but with no requested vendor installed → a clean exit 0 and a note,
    not a crash. (We request an impossible vendor name to guarantee 'none present'
    regardless of the host's PATH.)"""
    monkeypatch.setenv("DOS_LIVE_DEMO", "1")
    rc = live_demo.main(["--vendors", "no-such-vendor-cli"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "nothing to demo" in out or "skipping" in out


# --------------------------------------------------------------------------- #
# LIVE — opt-in only
# --------------------------------------------------------------------------- #

_LIVE = bool(os.environ.get("DOS_LIVE_DEMO"))


@pytest.mark.skipif(not _LIVE, reason="set DOS_LIVE_DEMO=1 to run the live CLI smoke")
@pytest.mark.parametrize("vendor", ["claude", "gemini", "codex"])
def test_live_cli_smoke_if_optedin_and_installed(vendor, tmp_path):
    """Opt-in smoke: with DOS_LIVE_DEMO=1 and the CLI installed, actually drive the
    real model for ONE phase and confirm the demo machinery runs end-to-end without
    raising and produces a well-formed verdict. Skips if the CLI is absent. Asserts
    NOTHING about the model's content (non-deterministic) — only that DOS produced a
    verdict against the harness's git ground truth."""
    if not live_demo.installed_vendors([vendor]):
        pytest.skip(f"{vendor} CLI not installed")
    repo = tmp_path / "repo"
    repo.mkdir()
    live_demo._init_repo(repo)
    verdicts = live_demo.run_vendor(vendor, repo, phases=1, commit_every=1)
    assert len(verdicts) == 1
    v = verdicts[0]
    # phase 0 with commit_every=1 was really committed → oracle must confirm ship
    # from git, regardless of what the live model said.
    assert v.really_committed and v.verdict_shipped
    assert v.verdict_source in ("registry", "grep")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

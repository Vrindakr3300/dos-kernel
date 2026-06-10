"""EFF — the token-effectiveness verdict + the pure classifier (docs/263).

`efficiency.classify` is `productivity`'s lateral sibling: a PURE verdict over the
two env-authored counts the caller already has — work landed and tokens spent.
Where `productivity` asks "is the work-per-step RATE fading?" (a trend over steps),
EFF asks "did the tokens buy work?" (a RATIO: work per token). It relates the work
to its PRICE — the question an operator means by "token effectiveness."

These tests pin the ladder on FROZEN evidence (no clock, no I/O — efficiency is
timeless) and the no-plan rail through the real CLI.

The verdict ladder under test:

  1. EFFICIENT — fewer than `min_tokens` spent (too little spend to judge a ratio).
  2. WASTEFUL  — meaningful spend AND zero work (the tokens bought nothing).
  3. COSTLY    — meaningful spend AND nonzero work AND ratio under `floor`.
  4. EFFICIENT — ratio at/above the floor (or floor disabled and work nonzero).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dos import efficiency
from dos.efficiency import (
    Efficiency,
    EfficiencyEvidence,
    EfficiencyPolicy,
    classify,
)

# A policy with a readable floor (0.01 work units per token) and the default
# 1000-token minimum, so the tests read concretely. At this floor a run must land
# at least 1 work unit per 100 tokens to be EFFICIENT.
_POLICY = EfficiencyPolicy(min_tokens=1000, floor=0.01)


# ---------------------------------------------------------------------------
# The pure-classifier ladder, on frozen evidence.
# ---------------------------------------------------------------------------


def test_too_little_spend_is_efficient():
    """Fewer than min_tokens spent → EFFICIENT (withhold the accusation)."""
    # 500 tokens, no work — but only 500 tokens, too little to judge a ratio.
    v = classify(EfficiencyEvidence.of(work=0, tokens=500), _POLICY)
    assert v.verdict is Efficiency.EFFICIENT
    assert "not enough spend" in v.reason


def test_zero_spend_is_efficient():
    """No tokens spent at all → EFFICIENT (nothing to judge, no problem yet)."""
    v = classify(EfficiencyEvidence.of(work=0, tokens=0), _POLICY)
    assert v.verdict is Efficiency.EFFICIENT


def test_meaningful_spend_zero_work_is_wasteful():
    """>= min_tokens spent AND zero work → WASTEFUL (the tokens bought nothing).

    The unit-independent half of the verdict — 0 work is 0 work whatever the unit,
    so this fires with NO floor needed.
    """
    v = classify(EfficiencyEvidence.of(work=0, tokens=80000), _POLICY)
    assert v.verdict is Efficiency.WASTEFUL
    assert "bought nothing" in v.reason


def test_low_ratio_nonzero_work_is_costly():
    """Meaningful spend AND nonzero work AND ratio under floor → COSTLY.

    Doing work, but paying a lot per unit (fading efficiency, not pure waste).
    """
    # 3 work units for 90,000 tokens → 3.3e-5 work/token, far under the 0.01 floor.
    v = classify(EfficiencyEvidence.of(work=3, tokens=90000), _POLICY)
    assert v.verdict is Efficiency.COSTLY
    assert "spending a lot per unit" in v.reason


def test_ratio_above_floor_is_efficient():
    """A ratio clearing the floor keeps the run EFFICIENT."""
    # 1200 work units for 45,000 tokens → 0.0267 work/token, above the 0.01 floor.
    v = classify(EfficiencyEvidence.of(work=1200, tokens=45000), _POLICY)
    assert v.verdict is Efficiency.EFFICIENT
    assert "bought its work" in v.reason


def test_ratio_exactly_at_floor_is_efficient():
    """A ratio EXACTLY at the floor is EFFICIENT — the floor is inclusive (minimum
    acceptable efficiency), so COSTLY is strictly-under only."""
    # 100 work units / 10,000 tokens = exactly 0.01 = the floor.
    v = classify(EfficiencyEvidence.of(work=100, tokens=10000), _POLICY)
    assert v.verdict is Efficiency.EFFICIENT


def test_wasteful_takes_precedence_over_costly():
    """Zero work is WASTEFUL even though a 0 ratio is also under the floor.

    A zero is the operator's clearest "the spend bought nothing" signal — named
    distinctly from a merely-low-but-nonzero ratio.
    """
    # 0 work / 50,000 tokens: the ratio (0.0) is under the floor, but the precise
    # verdict is WASTEFUL (bought nothing), not COSTLY (bought a little).
    v = classify(EfficiencyEvidence.of(work=0, tokens=50000), _POLICY)
    assert v.verdict is Efficiency.WASTEFUL


def test_default_floor_disabled_only_wasteful_fires():
    """With the default floor=0.0, no nonzero-work ratio is under it → EFFICIENT.

    The default floor is disabled on purpose (there is no universal good ratio — it
    depends on the host's work unit), so only WASTEFUL fires for free; COSTLY is
    opt-in via an explicit floor.
    """
    p = EfficiencyPolicy()  # min_tokens=1000, floor=0.0
    # A tiny ratio (1 work unit / 100,000 tokens) is NOT costly under a 0.0 floor.
    assert classify(EfficiencyEvidence.of(work=1, tokens=100000), p).verdict is Efficiency.EFFICIENT
    # But zero work for meaningful spend is still WASTEFUL — the always-free verdict.
    assert classify(EfficiencyEvidence.of(work=0, tokens=100000), p).verdict is Efficiency.WASTEFUL


def test_just_under_min_tokens_is_never_accused():
    """At exactly min_tokens-1 spend, even zero work is EFFICIENT (the guard)."""
    v = classify(EfficiencyEvidence.of(work=0, tokens=999), _POLICY)
    assert v.verdict is Efficiency.EFFICIENT


def test_at_min_tokens_zero_work_is_wasteful():
    """At exactly min_tokens spend with zero work → WASTEFUL (the guard is `<`)."""
    v = classify(EfficiencyEvidence.of(work=0, tokens=1000), _POLICY)
    assert v.verdict is Efficiency.WASTEFUL


# ---------------------------------------------------------------------------
# Structural guarantees.
# ---------------------------------------------------------------------------


def test_classify_is_pure(monkeypatch):
    """`classify` makes NO I/O — no clock, no file, no subprocess.

    Efficiency is timeless: like `productivity` it does not even read an age, so
    banning the clock proves the verdict is a pure fold over the two counts.
    """
    import builtins
    import time as _time

    def _boom(*a, **k):  # pragma: no cover - only fires on a violation
        raise AssertionError("classify must not perform I/O")

    monkeypatch.setattr(_time, "time", _boom)
    monkeypatch.setattr(builtins, "open", _boom)
    v = classify(EfficiencyEvidence.of(work=0, tokens=80000), _POLICY)
    assert v.verdict is Efficiency.WASTEFUL


def test_verdict_to_dict_round_trips_evidence():
    """`to_dict` carries the verdict AND the facts (the legible-distrust shape)."""
    v = classify(EfficiencyEvidence.of(work=3, tokens=90000), _POLICY)
    d = v.to_dict()
    assert d["verdict"] == "COSTLY"
    assert d["evidence"]["work"] == 3
    assert d["evidence"]["tokens"] == 90000
    assert d["evidence"]["ratio"] == pytest.approx(3 / 90000)
    # The dict is JSON-serializable (the --output json contract).
    assert json.loads(json.dumps(d, sort_keys=True)) == d


def test_ratio_is_zero_when_no_tokens():
    """The ratio is 0.0 (not a divide-by-zero) when no tokens were spent."""
    assert EfficiencyEvidence.of(work=5, tokens=0).ratio == 0.0


def test_policy_rejects_negative_thresholds():
    with pytest.raises(ValueError):
        EfficiencyPolicy(min_tokens=-1)
    with pytest.raises(ValueError):
        EfficiencyPolicy(floor=-0.5)


def test_evidence_rejects_negative_counts():
    """Work and tokens are non-negative quantities."""
    with pytest.raises(ValueError):
        EfficiencyEvidence.of(work=-1, tokens=100)
    with pytest.raises(ValueError):
        EfficiencyEvidence.of(work=10, tokens=-5)


def test_default_policy_floor_is_disabled():
    """The generic default floor is 0.0 (disabled) — no guessed ratio (docs/263)."""
    p = EfficiencyPolicy()
    assert p.min_tokens == 1000
    assert p.floor == 0.0


# ---------------------------------------------------------------------------
# The CLI verb (`dos efficiency`) — the boundary + the verdict-is-exit-code.
# ---------------------------------------------------------------------------


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_efficiency_cli_efficient_exit_zero(tmp_path: Path):
    """A run whose tokens bought work → EFFICIENT is exit 0 (success-is-0 idiom)."""
    r = _run_cli("efficiency", "--work", "1200", "--tokens", "45000", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "EFFICIENT" in r.stdout


def test_efficiency_cli_wasteful_exit_code(tmp_path: Path):
    """Meaningful spend, zero work → WASTEFUL is exit 4 (the verdict IS the code)."""
    r = _run_cli("efficiency", "--work", "0", "--tokens", "80000", cwd=tmp_path)
    assert r.returncode == 4, r.stderr
    assert "WASTEFUL" in r.stdout


def test_efficiency_cli_costly_exit_code(tmp_path: Path):
    """A low ratio under an armed floor → COSTLY is exit 3."""
    r = _run_cli(
        "efficiency", "--work", "3", "--tokens", "90000", "--floor", "0.0001",
        cwd=tmp_path,
    )
    assert r.returncode == 3, r.stderr
    assert "COSTLY" in r.stdout


def test_efficiency_cli_json(tmp_path: Path):
    """`--json` emits the verdict object with the facts echoed."""
    r = _run_cli(
        "efficiency", "--work", "0", "--tokens", "80000", "--json", cwd=tmp_path,
    )
    assert r.returncode == 4, r.stderr
    obj = json.loads(r.stdout)
    assert obj["verdict"] == "WASTEFUL"
    assert obj["evidence"]["tokens"] == 80000
    assert obj["evidence"]["work"] == 0


def test_efficiency_cli_no_plan(tmp_path: Path):
    """The no-plan rail: runs in a bare dir with NO git, NO plan, NO journal.

    Efficiency needs nothing but the two counts — the strongest no-plan floor of any
    verdict (alongside productivity; it does not even read git, unlike `liveness`).
    """
    # tmp_path is an empty directory — not even a git repo.
    r = _run_cli("efficiency", "--work", "0", "--tokens", "50000", cwd=tmp_path)
    assert r.returncode == 4, r.stderr
    assert "WASTEFUL" in r.stdout
    # No state was created (read-only, no-I/O verdict).
    assert not (tmp_path / ".dos").exists()


def test_efficiency_cli_too_little_spend_is_efficient(tmp_path: Path):
    """Below min_tokens spend → EFFICIENT (nothing to judge yet), exit 0."""
    r = _run_cli("efficiency", "--work", "0", "--tokens", "500", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "EFFICIENT" in r.stdout


def test_efficiency_cli_default_floor_only_wasteful(tmp_path: Path):
    """With no --floor, a tiny ratio is EFFICIENT (the default floor is disabled)."""
    r = _run_cli("efficiency", "--work", "1", "--tokens", "100000", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "EFFICIENT" in r.stdout


def test_efficiency_cli_rejects_negative_work(tmp_path: Path):
    """A negative --work is a contract error (exit 2), never read as a verdict."""
    r = _run_cli("efficiency", "--work", "-5", "--tokens", "10000", cwd=tmp_path)
    assert r.returncode == 2
    assert "error" in r.stderr.lower()

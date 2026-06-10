"""docs/197 §7(1) follow-up — the cheap, non-git fan-out coverage fold (`dos coverage`).

The coverage-classify pairing. A Workflow logs() coverage and throws it away, so the
synthesizer sees only the survivor list and a 4-of-7 fan-out is laundered as 7/7
(`failed = N − survivors.length` / `.filter(Boolean)` cannot tell a harness death from
a real negative). `coverage.classify_coverage` folds the per-worker `result_state`
verdicts against the workflow-DECLARED N into a verdict the synthesizer can READ.

The load-bearing pins (each from the adversarial design review):

  * **honest aggregator, not a data-multiplier**: it folds already-adjudicated
    result_state verdicts; 0 new labels (the fleet_roll posture, docs/179). The
    `test_declared_is_independent_of_survivor_list` pin proves the verdict depends on
    the SECOND (workflow-authored) input — which is true of any aggregator — NOT that
    it mints data.
  * **the laundering fix**: `declared` is independent of the survivor list, so a short
    survivor list can NEVER read as FULL.
  * **fail-safe floor**: an UNREADABLE return is LIVE-not-dead (a read fault must never
    be counted a death), inherited from result_state.
  * **reason honesty**: STARVED/UNDERFILLED prompt text is generated from the REAL
    (dead, unreadable, unaccounted) partition — it never asserts a death that was not
    witnessed (a read fault is "could not be read", a missing slot "did not return a
    transcript").
  * **over-fill**: healthy > declared → OVERFILLED, never a `fraction > 1` UNDERFILLED.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dos import coverage as cov
from dos.result_state import ResultStateVerdict, TerminalClass, TerminalState

H = TerminalState.HEALTHY
S = TerminalState.SYNTHETIC
E = TerminalState.EMPTY
U = TerminalState.UNREADABLE


def _dead_verdict(cls: TerminalClass = TerminalClass.RATE_LIMIT) -> ResultStateVerdict:
    """A full SYNTHETIC ResultStateVerdict carrying a class (the harness-grounded path)."""
    return ResultStateVerdict(state=TerminalState.SYNTHETIC, dead=True, cls=cls,
                              api_status=429, reason="harness-authored terminal")


# ==========================================================================
# classify_coverage — the pure fold.
# ==========================================================================
def test_full_when_all_healthy():
    v = cov.classify_coverage(7, [H] * 7)
    assert v.state is cov.Coverage.FULL
    assert v.healthy == 7 and v.declared == 7 and v.dead == 0
    assert v.fraction == 1.0
    assert v.state.foldable is True and v.state.should_caveat is False
    assert "full coverage" in v.prompt_line


def test_underfilled_with_a_missing_slot():
    # 4 healthy + 2 dead, len 6 of a declared 7 → 1 unaccounted.
    v = cov.classify_coverage(7, [H, H, H, H, S, S])
    assert v.state is cov.Coverage.UNDERFILLED
    assert v.healthy == 4 and v.dead == 2 and v.unaccounted == 1
    assert "SUB-QUORUM SAMPLE (4/7)" in v.prompt_line
    assert "do not state or imply" in v.prompt_line.lower()


def test_starved_when_no_healthy():
    v = cov.classify_coverage(7, [S] * 7)
    assert v.state is cov.Coverage.STARVED
    assert v.state.foldable is False
    assert "Do NOT fabricate findings" in v.prompt_line


def test_empty_when_nothing_declared():
    v = cov.classify_coverage(0, [])
    assert v.state is cov.Coverage.EMPTY
    assert v.fraction is None
    assert v.state.should_caveat is False


# --- the laundering pin (the headline bug) --------------------------------
def test_short_survivor_list_cannot_read_as_full():
    """The keystone bug: the workflow already `.filter(Boolean)`-dropped 3 dead
    transcripts and hands coverage only 4 HEALTHY returns. Because `declared` is
    independent, this is UNDERFILLED 4/7, NEVER FULL."""
    v = cov.classify_coverage(7, [H] * 4)   # 3 deaths already silently dropped
    assert v.state is cov.Coverage.UNDERFILLED
    assert v.healthy == 4 and v.declared == 7
    assert v.unaccounted == 3


def test_declared_is_independent_of_survivor_list():
    """Two callers hand IDENTICAL survivor lists but different `declared` → different
    verdicts. This proves the verdict depends on the second (workflow-authored) input —
    which is true of any AGGREGATOR (fleet_roll does the same) — NOT that it mints a
    new label. (Renamed from a mis-titled 'fold-mints-data pin' per the design review.)"""
    survivors = [H] * 4
    assert cov.classify_coverage(7, survivors).state is cov.Coverage.UNDERFILLED
    assert cov.classify_coverage(4, survivors).state is cov.Coverage.FULL


# --- the fail-safe floor (UNREADABLE is LIVE, not a death) ----------------
def test_unreadable_counts_live_not_dead():
    v = cov.classify_coverage(3, [H, U, S])
    assert v.healthy == 1 and v.unreadable == 1 and v.dead == 1
    assert v.to_dict()["unreadable"] == 1
    assert v.state is cov.Coverage.UNDERFILLED


def test_unreadable_only_reason_does_not_claim_a_death():
    """Fix 2/3: a 6-of-7-healthy run whose only gap is 1 UNREADABLE slot must NOT have a
    prompt_line that says a worker 'died' — it must say 'could not be read'."""
    v = cov.classify_coverage(7, [H] * 6 + [U])
    assert v.state is cov.Coverage.UNDERFILLED
    assert "could not be read" in v.prompt_line
    assert "died" not in v.prompt_line.lower()


def test_all_unreadable_is_starved_but_not_a_fabricated_death():
    """Fix 3: all-UNREADABLE → STARVED (0 healthy, nothing to fold) but dead == 0, and
    the reason must NOT assert deaths — it must point at the read path / missing
    transcripts, the correct operator action."""
    v = cov.classify_coverage(2, [U, U])
    assert v.state is cov.Coverage.STARVED
    assert v.dead == 0 and v.unreadable == 2
    assert "could not be read" in v.prompt_line
    assert "died on a harness" not in v.prompt_line


def test_empty_and_synthetic_both_count_dead():
    """EMPTY and SYNTHETIC both carry result_state.dead==True → both in `dead`."""
    v = cov.classify_coverage(2, [E, S])
    assert v.state is cov.Coverage.STARVED  # 0 healthy
    assert v.dead == 2


# --- over-fill (Fix 5) ----------------------------------------------------
def test_overfilled_when_more_healthy_than_declared():
    v = cov.classify_coverage(5, [H] * 6)
    assert v.state is cov.Coverage.OVERFILLED
    assert v.healthy == 6 and v.declared == 5
    assert v.state.foldable is True   # there IS material, just too much
    assert "more results than expected" in v.prompt_line
    # fraction may exceed 1.0 — reported so the dispatch bug is visible, not hidden.
    assert v.fraction == 1.2


# --- dead_classes detail (harness-grounded path) --------------------------
def test_dead_classes_populated_from_full_verdicts():
    v = cov.classify_coverage(
        3, [H, _dead_verdict(TerminalClass.RATE_LIMIT),
            _dead_verdict(TerminalClass.USAGE_LIMIT)])
    assert dict(v.dead_classes) == {"RATE_LIMIT": 1, "USAGE_LIMIT": 1}
    # the class names surface in the death phrase.
    assert "rate-limit" in v.prompt_line


def test_dead_classes_empty_for_bare_states():
    v = cov.classify_coverage(2, [H, S])   # bare TerminalState, no class
    assert v.dead_classes == ()


# --- quorum flag is advisory-only (never changes the verdict) -------------
def test_min_quorum_is_legibility_only():
    pol_met = cov.CoveragePolicy(min_quorum=0.5)
    v = cov.classify_coverage(7, [H] * 4, pol_met)
    assert v.state is cov.Coverage.UNDERFILLED   # verdict UNCHANGED
    assert v.quorum_met is True
    v2 = cov.classify_coverage(7, [H] * 3, pol_met)
    assert v2.state is cov.Coverage.UNDERFILLED
    assert v2.quorum_met is False
    # no policy → quorum_met is None.
    assert cov.classify_coverage(7, [H] * 4).quorum_met is None


# --- coercion / contract --------------------------------------------------
def test_uncoercible_return_raises_typeerror():
    with pytest.raises(TypeError):
        cov.classify_coverage(3, [object()])  # type: ignore[list-item]


def test_returnstate_wrapper_is_accepted():
    v = cov.classify_coverage(2, [cov.ReturnState(H, "a1"), cov.ReturnState(S, "a2")])
    assert v.healthy == 1 and v.dead == 1


# --- to_dict shape --------------------------------------------------------
def test_to_dict_shape():
    v = cov.classify_coverage(7, [H, H, H, H, S, S])
    d = v.to_dict()
    assert set(d) == {
        "state", "declared", "healthy", "dead", "unreadable", "unaccounted",
        "fraction", "foldable", "should_caveat", "dead_classes", "quorum_met",
        "prompt_line", "reason",
    }
    assert d["state"] == "UNDERFILLED"
    # round-trips the state token.
    assert cov.Coverage(d["state"]) is cov.Coverage.UNDERFILLED


# ==========================================================================
# coverage_from_transcripts — the boundary reader (reuses test_result_state shapes).
# ==========================================================================
def _synthetic_record(text="API Error: … · Rate limited", api_status=429):
    return {
        "type": "assistant", "isApiErrorMessage": True, "apiErrorStatus": api_status,
        "message": {"model": "<synthetic>", "role": "assistant",
                    "stop_reason": "stop_sequence",
                    "content": [{"type": "text", "text": text}]},
    }


def _healthy_record(text="Here is my finding."):
    return {
        "type": "assistant",
        "message": {"model": "claude-opus-4-8", "role": "assistant",
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": text}]},
    }


def _write(tmp_path: Path, records, name) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return p


def test_coverage_from_transcripts_grounds_on_the_synthetic_marker(tmp_path):
    healthy = _write(tmp_path, [_healthy_record()], "h.jsonl")
    dead = _write(tmp_path, [_synthetic_record()], "d.jsonl")
    missing = str(tmp_path / "nope.jsonl")  # OSError → UNREADABLE (live, not dead)
    v = cov.coverage_from_transcripts(4, [str(healthy), str(dead), missing])
    assert v.healthy == 1 and v.dead == 1 and v.unreadable == 1 and v.unaccounted == 1
    assert v.state is cov.Coverage.UNDERFILLED


# ==========================================================================
# CLI — cmd_coverage exit codes + provenance stamp.
# ==========================================================================
def _cli(*argv) -> subprocess.CompletedProcess:
    import os
    env = {**os.environ, "PYTHONPATH": str(Path(__import__("dos").__file__).parents[1])}
    return subprocess.run([sys.executable, "-m", "dos.cli", "coverage", *argv],
                          capture_output=True, text=True, env=env)


def test_cli_full_exits_0():
    r = _cli("--declared", "2", "--states", "HEALTHY,HEALTHY")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert r.stdout.startswith("FULL")


def test_cli_underfilled_exits_3():
    r = _cli("--declared", "3", "--states", "HEALTHY,SYNTHETIC,EMPTY")
    assert r.returncode == 3, (r.stdout, r.stderr)
    assert r.stdout.startswith("UNDERFILLED")


def test_cli_starved_exits_3():
    r = _cli("--declared", "2", "--states", "SYNTHETIC,SYNTHETIC")
    assert r.returncode == 3
    assert r.stdout.startswith("STARVED")


def test_cli_missing_declared_is_contract_error():
    r = _cli("--states", "HEALTHY")
    assert r.returncode == 2
    assert "declared" in r.stderr.lower()


def test_cli_uncoercible_state_is_contract_error():
    r = _cli("--declared", "2", "--states", "HEALTHY,BOGUS")
    assert r.returncode == 2
    assert "un-coercible" in r.stderr.lower() or "token" in r.stderr.lower()


def test_cli_nothing_to_fold_is_contract_error():
    r = _cli("--declared", "2")  # no states, no transcripts
    assert r.returncode == 2


def test_cli_states_path_stamps_grounded_false():
    r = _cli("--declared", "2", "--states", "HEALTHY,SYNTHETIC", "--json")
    assert r.returncode == 3
    out = json.loads(r.stdout)
    assert out["grounded"] is False   # caller-asserted, provenance-degraded
    assert out["state"] == "UNDERFILLED" and out["healthy"] == 1
    assert "prompt_line" in out


def test_cli_transcript_path_stamps_grounded_true(tmp_path):
    p = _write(tmp_path, [_healthy_record()], "h.jsonl")
    r = _cli("--declared", "1", "--transcript", str(p), "--json")
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["grounded"] is True   # harness-grounded — coverage ran verify_transcript
    assert out["state"] == "FULL"


# ==========================================================================
# Litmus — kernel-purity import discipline (mirrors test_result_state's pins).
# ==========================================================================
def test_coverage_imports_only_result_state_and_stdlib():
    """coverage.py imports ONLY dos.result_state (+ stdlib) — NOT resume/intent_ledger/
    scope_source (completion's git-ledger imports), no host, no scripts/dos_mcp. Scans
    actual IMPORT statements (not prose — the docstring legitimately NAMES those
    modules to explain what coverage deliberately does not import)."""
    src = (Path(__import__("dos").__file__).parent / "coverage.py").read_text(encoding="utf-8")
    import_lines = [ln.strip() for ln in src.splitlines()
                    if ln.strip().startswith(("import ", "from "))]
    blob = "\n".join(import_lines)
    for forbidden in ("resume", "intent_ledger", "scope_source", "completion",
                      "scripts", "dos_mcp", "drivers"):
        assert forbidden not in blob, \
            f"coverage.py must not IMPORT {forbidden!r}; imports were:\n{blob}"
    # the one sibling it DOES import, and nothing else dos-internal beyond it + lazy
    # result_state in the boundary fn.
    assert "from dos.result_state import" in blob

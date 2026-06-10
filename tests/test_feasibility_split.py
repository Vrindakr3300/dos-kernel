"""Tests for the benchmark-agnostic feasibility split (`benchmark/_feasibility.py`, docs/198).

These pin the load-bearing properties of the population split that the whole "stop scoring
conversion against infeasible tasks" correction rests on:

  * A tool with 0 successes ANYWHERE (>= min_obs errors) is WALLED; one success ANYWHERE makes
    it CURABLE (a path provably exists). The witness is a cross-RUN join.
  * A wall is AIRTIGHT: a single curable success can never be mis-routed into the WALLED bucket
    (a run thrashing on any curable tool is CURABLE, even if it also thrashes on a walled tool).
  * `thrash_tools` matches the live `natural_thrash_gate` rule (>= K errors, latest still error).

The module is consumer-side (under benchmark/), so it is loaded by path the way
tests/test_bench_layering.py loads `_arms` / `registry` — benchmark/ on sys.path.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BENCH = _REPO / "benchmark"


def _load(name: str):
    if str(_BENCH) not in sys.path:
        sys.path.insert(0, str(_BENCH))
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _BENCH / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_fz = _load("_feasibility")
ToolEvent, Verdict, Feasibility = _fz.ToolEvent, _fz.Verdict, _fz.Feasibility


def _ev(tool, err):
    return ToolEvent(tool, err)


# --------------------------------------------------------------------------- the witness
def test_walled_tool_has_zero_successes_anywhere():
    """A tool that errors >= min_obs times and never succeeds in the whole corpus is WALLED."""
    corpus = [
        [_ev("wall", True), _ev("wall", True)],
        [_ev("wall", True)],
    ]
    w = _fz.feasibility_witness(corpus, min_obs=3)
    assert w["wall"] is Verdict.WALLED


def test_one_success_anywhere_makes_a_tool_curable():
    """A single env-authored success ANYWHERE in the corpus lifts a tool out of WALLED — the
    cross-run join that is the whole point (a path provably exists)."""
    corpus = [
        [_ev("t", True), _ev("t", True), _ev("t", True)],   # this run only saw errors
        [_ev("t", False)],                                   # but another run got a success
    ]
    w = _fz.feasibility_witness(corpus, min_obs=3)
    assert w["t"] is Verdict.CURABLE


def test_thin_evidence_is_not_called_walled():
    """Below min_obs errors with no successes is THIN, not WALLED — a wall must be airtight, so we
    refuse to declare one on too few observations (conservative: THIN splits as not-walled)."""
    corpus = [[_ev("rare", True)]]            # 1 error, 0 success
    w = _fz.feasibility_witness(corpus, min_obs=3)
    assert w["rare"] is Verdict.THIN


def test_walled_tools_helper_matches_witness():
    corpus = [
        [_ev("wall", True)] * 4,
        [_ev("ok", False), _ev("ok", True), _ev("ok", True)],
    ]
    assert _fz.walled_tools(corpus, min_obs=3) == {"wall"}


# --------------------------------------------------------------------------- thrash
def test_thrash_requires_k_errors_with_latest_still_error():
    # 2 errors, latest IS an error -> thrash
    assert _fz.thrash_tools([_ev("t", True), _ev("t", True)], min_failures=2) == ["t"]
    # 2 errors but recovered (latest is a success) -> NOT thrash
    assert _fz.thrash_tools([_ev("t", True), _ev("t", True), _ev("t", False)], min_failures=2) == []
    # only 1 error -> NOT thrash
    assert _fz.thrash_tools([_ev("t", True)], min_failures=2) == []


# --------------------------------------------------------------------------- the split
def test_curable_thrash_routes_a_run_to_CURABLE():
    witness = {"wall": Verdict.WALLED, "cure": Verdict.CURABLE}
    run = [_ev("cure", True), _ev("cure", True)]
    assert _fz.classify_run(run, witness) is Feasibility.CURABLE


def test_walled_only_thrash_routes_to_WALLED():
    witness = {"wall": Verdict.WALLED, "cure": Verdict.CURABLE}
    run = [_ev("wall", True), _ev("wall", True)]
    assert _fz.classify_run(run, witness) is Feasibility.WALLED


def test_mixed_thrash_is_CURABLE_never_WALLED():
    """The airtight-wall asymmetry: a run thrashing on BOTH a walled and a curable tool is CURABLE
    — we must never route a run with a winnable path into the no-conversion bucket."""
    witness = {"wall": Verdict.WALLED, "cure": Verdict.CURABLE}
    run = [_ev("wall", True), _ev("wall", True), _ev("cure", True), _ev("cure", True)]
    assert _fz.classify_run(run, witness) is Feasibility.CURABLE


def test_no_thrash_run_routes_to_NO_THRASH():
    witness = {"cure": Verdict.CURABLE}
    run = [_ev("cure", False), _ev("cure", False)]
    assert _fz.classify_run(run, witness) is Feasibility.NO_THRASH


def test_split_corpus_counts():
    witness = {"wall": Verdict.WALLED, "cure": Verdict.CURABLE}
    runs = {
        "a": [_ev("wall", True), _ev("wall", True)],     # WALLED
        "b": [_ev("cure", True), _ev("cure", True)],     # CURABLE
        "c": [_ev("cure", False)],                        # NO_THRASH
    }
    rep = _fz.split_corpus(runs, witness)
    assert rep.counts() == {"WALLED": 1, "CURABLE": 1, "NO_THRASH": 1}

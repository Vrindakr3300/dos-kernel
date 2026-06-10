"""Pin the cross-benchmark zero-accuracy-cost invariants (docs/201 §8.1).

The load-bearing claims of the give-up gate, replicated on Toolathlon (22 models, frontier-spanning)
and contrasted against the naive raw-repeat variant. If a corpus is absent the data test skips; the
Wilson-bound math is pure and always runs.

    python -m pytest test_giveup_cross_benchmark.py -q
"""
from __future__ import annotations

import os

import pytest

import giveup_cross_benchmark as X

_HAVE_TOOL = os.path.exists(X._REPLAY)
needs_tool = pytest.mark.skipif(not _HAVE_TOOL, reason="toolathlon replay CSV not present")


def test_wilson_upper_zero_numerator_shrinks_with_n():
    # rule-of-three intuition: 0/n upper bound falls as n grows.
    assert X.wilson_upper(0, 45) > X.wilson_upper(0, 1634)
    assert X.wilson_upper(0, 1634) < 0.01          # 1634 winners -> a tight bound
    assert 0.0 < X.wilson_upper(0, 45) < 0.10      # 45 winners -> looser but still <0.10


@needs_tool
def test_error_gated_gate_has_zero_false_abandon_on_toolathlon():
    # THE replication: the DOS error-gated give-up gate halts 0 winners at K>=3 across 22 models.
    tool, n_pass, _n_runs, _pm = X.toolathlon_sweep()
    assert n_pass > 1000, "expect ~1634 toolathlon winners"
    for K in (2, 3, 4, 5):
        _fired, fa = tool["error-gated"][K]
        assert fa == 0, f"error-gated gate must false-abandon 0 winners at K={K} (got {fa})"


@needs_tool
def test_naive_raw_repeat_gate_DISPROVES_zero_cost():
    # The falsification half: the NAIVE raw-repeat gate DOES kill winners (the polling confound).
    # This is the contrast that proves the error-gating is the load-bearing discipline.
    tool, _n_pass, _n_runs, _pm = X.toolathlon_sweep()
    raw_fa_k3 = tool["raw-repeat"][3][1]
    assert raw_fa_k3 > 0, "the naive raw-repeat gate should false-abandon winners (disproving the naive claim)"


@needs_tool
def test_per_model_frontier_separability():
    # The frontier test: on EVERY model, the error-gated gate halts 0 winners; the naive gate's
    # false-abandons concentrate on exactly one model (grok-4 polling), not the weak ones.
    _tool, _n_pass, _n_runs, per_model = X.toolathlon_sweep()
    assert sum(d["fa_err"] for d in per_model.values()) == 0, "error-gated: 0 winners halted on any model"
    raw_offenders = {m for m, d in per_model.items() if d["fa_raw"] > 0}
    assert raw_offenders, "the naive gate must have at least one offending model"
    # the offenders are not the weakest model (gemini-2.5-flash) — separability is not a base-rate artifact
    assert "gemini-2.5-flash" not in raw_offenders


@needs_tool
def test_frontier_models_are_present_in_the_corpus():
    # The cross-benchmark value is that it SPANS the capability ladder EnterpriseOps lacked.
    _tool, _n_pass, _n_runs, per_model = X.toolathlon_sweep()
    models = set(per_model)
    frontier = {"claude-4.5-opus", "gemini-3-pro-preview", "gpt-5.1", "o3", "grok-4"}
    assert frontier <= models, f"expected frontier models in the corpus; missing {frontier - models}"

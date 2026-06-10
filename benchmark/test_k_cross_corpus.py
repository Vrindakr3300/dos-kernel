"""Pin the docs/201 §4d cross-corpus boundary: the give-up gate's K-knob corroborates only
where the consecutive-same-tool error thrash it keys on actually occurs.

§4c proved zero-accuracy-cost on the two corpora WITH a task-win label (Toolathlon, EnterpriseOps).
§4d probed two further corpora (AgentProcessBench, AgentHallu) that have a gold DIVERGENCE label and
an env-error channel but NO task-win label — short attribution traces. The finding is a BOUNDARY, not
a fourth corroboration: the shipped gate's CONSECUTIVE-same-tool key fires on a near-empty denominator
above K=2 on both, so no tunable precision curve can be drawn for the gate's own grammar there. The one
survival is the LOOSER cumulative reading on AgentProcessBench (powered at every K, monotone
false-alarm), which corroborates the abstract §4b "K is an operating point" claim — but NOT the
shipped consecutive gate.

These tests pin the load-bearing numbers from the two scratch probes (`_probe_k_cross_corpus_*.py`).
They SKIP gracefully when the sibling corpus clone is absent (../AgentProcessBench, ../AgentHallu), so
the suite stays green on a machine without the datasets — the same posture as the Toolathlon replay
tests. Reuse only: the probes import the existing byte-clean loaders/detectors untouched.

  python3 -m pytest benchmark/test_k_cross_corpus.py -q
"""
from __future__ import annotations

import importlib

import pytest

KS = (2, 3, 4, 5)


def _load_corpus_or_skip(dataset_mod: str):
    """Import a corpus loader and confirm its data is on disk, else skip (no clone on this machine)."""
    try:
        ds = importlib.import_module(dataset_mod)
        ds.corpus_root()  # raises FileNotFoundError if the sibling clone is absent
    except Exception as e:  # noqa: BLE001 — any import/availability failure is a clean skip
        pytest.skip(f"{dataset_mod} corpus unavailable: {type(e).__name__}: {e}")
    return ds


# --------------------------------------------------------------------------- AgentProcessBench (§4d)
def _apb_probe():
    return importlib.import_module("benchmark._probe_k_cross_corpus_apb")


def test_apb_consecutive_key_is_degenerate_above_k2():
    """The shipped gate's consecutive-same-tool key: 13/0/0/0 at K=2/3/4/5 on APB bfcl+tau2.
    Empty above K=2 — no curve can be drawn for the gate's own grammar (the §4d boundary)."""
    _load_corpus_or_skip("benchmark.agentprocessbench.dataset")
    p = _apb_probe()
    from benchmark.agentprocessbench.dataset import load, STRUCTURED_CONFIGS

    trajs = list(load(configs=STRUCTURED_CONFIGS))
    dist = {K: sum(1 for t in trajs if p.consecutive_same_tool_run(t) >= K) for K in KS}
    assert dist[2] >= 10, f"K=2 should be powered, got {dist[2]}"
    # The load-bearing degeneracy: ZERO consecutive-same-tool runs reach K>=3.
    assert dist[3] == 0 and dist[4] == 0 and dist[5] == 0, f"expected 0 at K>=3, got {dist}"


def test_apb_cumulative_reading_is_powered_and_monotone():
    """The LOOSER cumulative reading IS a precision knob on APB: powered (n>=10) at every K and the
    false-alarm rate is monotone non-increasing — the §4b operating curve on an independent bench.
    (This corroborates the ABSTRACT claim, not the shipped consecutive gate.)"""
    _load_corpus_or_skip("benchmark.agentprocessbench.dataset")
    p = _apb_probe()
    from benchmark.agentprocessbench.dataset import load, STRUCTURED_CONFIGS

    trajs = list(load(configs=STRUCTURED_CONFIGS))
    clean = [t for t in trajs if p.is_clean(t)]
    clean_total = len(clean)
    assert clean_total > 0

    fars = []
    for K in KS:
        n_fired = sum(1 for t in trajs if p.cumulative_errored_steps(t) >= K)
        assert n_fired >= 10, f"cumulative K={K} should be powered, got n_fired={n_fired}"
        clean_reach = sum(1 for t in clean if p.cumulative_errored_steps(t) >= K)
        fars.append(clean_reach / clean_total)
    # Monotone non-increasing false-alarm toward 0 — the precision-knob property.
    assert all(fars[i] >= fars[i + 1] for i in range(len(fars) - 1)), f"FAR not monotone: {fars}"
    assert fars[0] > 0 and fars[-1] == 0.0, f"FAR should fall from >0 to 0, got {fars}"


# ------------------------------------------------------------------------------------ AgentHallu (§4d)
def _ah_probe():
    return importlib.import_module("benchmark._probe_k_cross_corpus_ah")


def test_ah_is_degenerate_too_sparse():
    """AgentHallu: the consecutive-same-tool key fires 13/2/1/1 at K=2/3/4/5 over 693 trajectories —
    only K=2 clears an n>=10 power floor; every K>=3 point is a 1-2-sample artifact, NOT a curve.
    The §4d 'degenerate_too_sparse' verdict for a short attribution corpus."""
    ds = _load_corpus_or_skip("benchmark.agenthallu.dataset")
    from benchmark.agenthallu.detector import _step_errored, _step_tools

    def consecutive_same_tool_run(traj) -> int:
        best = cur = 0
        common: set | None = None
        for step in traj.history:
            if not _step_errored(step):
                cur = 0
                common = None
                continue
            tools = _step_tools(step)
            if not tools:
                cur = 0
                common = None
                continue
            if cur == 0 or common is None:
                cur, common = 1, set(tools)
            else:
                inter = common & tools
                if inter:
                    cur += 1
                    common = inter
                else:
                    cur, common = 1, set(tools)
            best = max(best, cur)
        return best

    trajs = list(ds.load())
    assert len(trajs) >= 600, f"expected ~693 trajectories, got {len(trajs)}"
    dist = {K: sum(1 for t in trajs if consecutive_same_tool_run(t) >= K) for K in KS}
    # Powered only at K=2; sparse (single-sample) above it — the degeneracy that bounds the gate.
    assert dist[2] >= 10, f"K=2 should be powered, got {dist[2]}"
    assert dist[3] < 10 and dist[4] < 10 and dist[5] < 10, (
        f"K>=3 must be underpowered (the degenerate finding), got {dist}"
    )

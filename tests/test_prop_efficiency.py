"""Property-based proof of the efficiency verdict's laws (docs/273, docs/263).

`efficiency.classify(EfficiencyEvidence, policy) -> EfficiencyVerdict` is a pure,
timeless, no-I/O ratio verdict (`work / tokens`). Its docstring states a ratio
ladder + two structural claims (floor=0.0 disables COSTLY; WASTEFUL is the
unit-independent always-free half). The example suite (`test_*`) pins the named
points; this file pins the laws over the whole non-negative input domain.

The properties:
  * `TestMonotonicity`     — more work never worsens the tier; more tokens (fixed
    nonzero work) never improves it.
  * `TestFloorDisablesCostly` — with floor=0.0, COSTLY is unreachable.
  * `TestWastefulIff`      — WASTEFUL ⟺ (tokens >= min_tokens AND work == 0).
  * `TestTotalAndClosed`   — always one of three members; never raises in-domain.
"""
from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from dos.efficiency import (  # noqa: E402
    Efficiency,
    EfficiencyEvidence,
    EfficiencyPolicy,
    classify,
)

# Tier order, worst -> best. "more work never moves DOWN this list" / "more tokens
# never moves UP it" is the monotonicity claim.
_RANK = {Efficiency.WASTEFUL: 0, Efficiency.COSTLY: 1, Efficiency.EFFICIENT: 2}

_work = st.integers(min_value=0, max_value=10**6)
_tokens = st.integers(min_value=0, max_value=10**7)
# A nonzero floor so COSTLY can actually fire in the monotonicity tests (with the
# default 0.0 floor COSTLY never fires and the "tokens worsen the tier" law is
# vacuously about WASTEFUL/EFFICIENT only).
_armed = EfficiencyPolicy(min_tokens=1000, floor=0.001)


def _rank(work: int, tokens: int, policy: EfficiencyPolicy) -> int:
    return _RANK[classify(EfficiencyEvidence(work=work, tokens=tokens), policy).verdict]


class TestMonotonicity:
    @given(w1=_work, w2=_work, tokens=st.integers(min_value=1000, max_value=10**7))
    @settings(max_examples=500, deadline=None)
    def test_more_work_never_worsens_the_tier(self, w1, w2, tokens):
        """Fixed tokens (above the min floor): the run with MORE work is never in a
        WORSE tier. work is the numerator of work/tokens, so raising it can only
        hold or improve the verdict."""
        lo, hi = sorted((w1, w2))
        assert _rank(hi, tokens, _armed) >= _rank(lo, tokens, _armed), (
            f"more work ({hi}) ranked worse than less ({lo}) at {tokens} tokens"
        )

    @given(
        work=st.integers(min_value=1, max_value=10**6),
        t1=st.integers(min_value=1000, max_value=10**7),
        t2=st.integers(min_value=1000, max_value=10**7),
    )
    @settings(max_examples=500, deadline=None)
    def test_more_tokens_never_improves_the_tier(self, work, t1, t2):
        """Fixed NONZERO work, both token counts above the min floor: the run that
        spent MORE tokens is never in a BETTER tier. tokens is the denominator, so
        raising it can only hold or worsen the ratio verdict."""
        lo, hi = sorted((t1, t2))
        assert _rank(work, hi, _armed) <= _rank(work, lo, _armed), (
            f"more tokens ({hi}) ranked better than fewer ({lo}) at {work} work"
        )


class TestFloorDisablesCostly:
    @given(work=_work, tokens=_tokens)
    @settings(max_examples=400, deadline=None)
    def test_default_floor_makes_costly_unreachable(self, work, tokens):
        """With the default floor=0.0, COSTLY never fires — only WASTEFUL /
        EFFICIENT. This is the claim that stops a unit mismatch manufacturing a
        false COSTLY (docs/263). No nonzero ratio is < 0.0."""
        v = classify(EfficiencyEvidence(work=work, tokens=tokens))  # default policy
        assert v.verdict is not Efficiency.COSTLY


class TestWastefulIff:
    @given(work=_work, tokens=_tokens)
    @settings(max_examples=600, deadline=None)
    def test_wasteful_iff_meaningful_spend_and_zero_work(self, work, tokens):
        """WASTEFUL ⟺ (tokens >= min_tokens AND work == 0) — the unit-independent,
        always-free half of the verdict, as an iff over the whole domain. Holds for
        any floor because the WASTEFUL rung is checked before COSTLY and needs no
        floor."""
        policy = _armed
        v = classify(EfficiencyEvidence(work=work, tokens=tokens), policy)
        expected_wasteful = tokens >= policy.min_tokens and tokens > 0 and work == 0
        assert (v.verdict is Efficiency.WASTEFUL) == expected_wasteful, (
            f"work={work} tokens={tokens}: verdict={v.verdict.value}, "
            f"expected_wasteful={expected_wasteful}"
        )

    @given(tokens=st.integers(min_value=0, max_value=999), work=_work)
    @settings(max_examples=200, deadline=None)
    def test_below_min_tokens_is_always_efficient_benign(self, tokens, work):
        """Below min_tokens (default 1000), the verdict withholds the accusation —
        EFFICIENT regardless of work (the young-and-alive guard)."""
        v = classify(EfficiencyEvidence(work=work, tokens=tokens))  # default min 1000
        assert v.verdict is Efficiency.EFFICIENT


class TestTotalAndClosed:
    @given(work=_work, tokens=_tokens, min_tokens=st.integers(0, 5000), floor=st.floats(0.0, 1.0))
    @settings(max_examples=400, deadline=None)
    def test_always_returns_a_valid_verdict(self, work, tokens, min_tokens, floor):
        """classify never raises on any in-domain input and always returns one of
        the three enum members, for any sane policy."""
        policy = EfficiencyPolicy(min_tokens=min_tokens, floor=floor)
        v = classify(EfficiencyEvidence(work=work, tokens=tokens), policy)
        assert v.verdict in _RANK
        # The verdict echoes the evidence faithfully (legible distrust).
        assert v.evidence.work == work
        assert v.evidence.tokens == tokens

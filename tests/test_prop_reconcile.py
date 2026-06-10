"""Property-based proof of the reconcile fail-closed-on-the-claim law (docs/273,
docs/168).

`reconcile(unit, claimed_done, oracle_shipped) -> ReconciliationVerdict` is the
kernel's "don't believe the agents" thesis in one pure function: it reconciles an
agent's self-reported "I finished" against the oracle's git-ancestry verdict, and

  > The agent's claim NEVER removes the unit from the residual; only the oracle does.

That sentence is a safety property — a ∀-claim that closure (VERIFIED) is a function
of `oracle_shipped` ALONE, with `claimed_done` unable to manufacture it. If a
regression ever let a `claimed_done=True` bid close a unit the oracle hasn't
shipped, the whole quiet-completion guard collapses (real work would be silently
dropped on the agent's word). This file pins the 2×2 truth table ∀.

The properties:
  * `TestVerifiedIffOracle` — VERIFIED ⟺ oracle_shipped, regardless of the claim.
  * `TestClaimNeverCloses`  — for ¬oracle_shipped, the verdict is never VERIFIED no
    matter what the agent claims (the load-bearing safety law).
  * `TestTruthTable`        — the full 2×2 map, as an exhaustive property.
"""
from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from dos.reconcile import Reconciliation, reconcile  # noqa: E402

# Unit names: arbitrary strings (the verdict must not depend on the name's content,
# only on the two booleans) — include adversarial / empty / unicode names.
_units = st.one_of(
    st.text(max_size=40),
    st.sampled_from(["", "docs/82_x-plan", "unit/with/slashes", "∀-unit", "  "]),
)


class TestVerifiedIffOracle:
    @given(unit=_units, claimed=st.booleans(), oracle=st.booleans())
    @settings(max_examples=400, deadline=None)
    def test_verified_iff_oracle_shipped(self, unit, claimed, oracle):
        """VERIFIED ⟺ oracle_shipped — closure is a function of the ORACLE alone.
        The agent's claim is irrelevant to whether the unit is closed."""
        v = reconcile(unit, claimed_done=claimed, oracle_shipped=oracle)
        assert (v.state is Reconciliation.VERIFIED) == oracle, (
            f"unit={unit!r} claimed={claimed} oracle={oracle}: "
            f"state={v.state.value} but VERIFIED must track oracle_shipped"
        )


class TestClaimNeverCloses:
    @given(unit=_units, claimed=st.booleans())
    @settings(max_examples=300, deadline=None)
    def test_claim_cannot_close_an_unshipped_unit(self, unit, claimed):
        """THE safety law: with oracle_shipped=False, the verdict is NEVER VERIFIED
        whatever the agent claims. A loud QUIET_INCOMPLETE (claimed) or HONEST_OPEN
        (not) — but the unit stays in the residual. The agent cannot close it."""
        v = reconcile(unit, claimed_done=claimed, oracle_shipped=False)
        assert v.state is not Reconciliation.VERIFIED
        # And specifically: a TRUE claim against a FALSE oracle is the quiet-failure
        # case that must be FLAGGED, not silently dropped.
        if claimed:
            assert v.state is Reconciliation.QUIET_INCOMPLETE
            assert v.flag, "a quiet over-claim must carry a flag, never close silently"
        else:
            assert v.state is Reconciliation.HONEST_OPEN
            assert not v.flag, "honest unfinished work is not a quiet failure — no flag"


class TestTruthTable:
    @given(unit=_units, claimed=st.booleans(), oracle=st.booleans())
    @settings(max_examples=400, deadline=None)
    def test_full_two_by_two(self, unit, claimed, oracle):
        """The complete 2×2 map (docs/168 §3), pinned as an exhaustive property:
          oracle               -> VERIFIED          (claim moot)
          claimed ∧ ¬oracle    -> QUIET_INCOMPLETE  (keep + flag)
          ¬claimed ∧ ¬oracle   -> HONEST_OPEN       (keep, no flag)
        """
        v = reconcile(unit, claimed_done=claimed, oracle_shipped=oracle)
        if oracle:
            expected = Reconciliation.VERIFIED
        elif claimed:
            expected = Reconciliation.QUIET_INCOMPLETE
        else:
            expected = Reconciliation.HONEST_OPEN
        assert v.state is expected
        # Never raises; always one of the three members.
        assert v.state in (
            Reconciliation.VERIFIED,
            Reconciliation.QUIET_INCOMPLETE,
            Reconciliation.HONEST_OPEN,
        )
        # The verdict echoes its inputs faithfully (legible distrust).
        assert v.claimed == claimed
        assert v.oracle_shipped == oracle

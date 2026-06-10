"""Tests for `dos.scope_source` — the extent-distrust seam (docs/117 Phase 4).

The scope analogue of `test_overlap_policy.py`. The load-bearing property is the
INVERSE of overlap's and simpler: a `ScopeSource` can only ever WITHHOLD COMPLETE
(push toward UNDERDECLARED), never grant it — so the conjunction + fail-to-strict
alone are the guarantee, with no competing deterministic floor needed.

  * `TestNullBaseline`     — `AllDeclaredScope` is always honest; the empty
                             conjunction is honest (today's floor reproduced).
  * `TestConjunction`      — `honest_under_floor`: any dishonest vote wins;
                             missing-sets union; reasons.
  * `TestFailToStrict`     — `run_scope` maps raise / wrong-type to DISHONEST
                             (withhold COMPLETE), never to honest.
  * `TestSoundnessProof`   — a lying source that returns `extent_honest=True` for a
                             genuinely under-declared run cannot, THROUGH the real
                             `completion.classify`, manufacture a COMPLETE that the
                             honest source would withhold (the structural proof).
  * `TestResolver`         — built-ins first + fail-loud on unknown.
  * `TestDriver`           — the reference `drivers.plan_scope.PlanScopeSource`.
"""
from __future__ import annotations

import pytest

from dos import scope_source as ss
from dos import completion as cm
from dos.intent_ledger import LedgerState, VerifiedStep
from dos.resume import AncestryFacts


# ── shared fixtures (the test_completion idiom) ────────────────────────────────
_C1, _C2 = "c1aaaaa", "c2bbbbb"


def _complete_state(declared=("s1", "s2")):
    """A LedgerState whose declared steps are all verified on a non-forgeable rung —
    so `resume` says COMPLETE and the only thing that can withhold completion is a
    scope verdict."""
    return LedgerState(
        run_id="RID-K", goal="g", start_sha=_C1, declared_steps=tuple(declared),
        verified={s: VerifiedStep(s, sha, via="file-path")
                  for s, sha in zip(declared, (_C1, _C2, "c3ccccc", "c4ddddd"))},
    )


def _complete_anc(declared=("s1", "s2")):
    shas = (_C1, _C2, "c3ccccc", "c4ddddd")[:len(declared)]
    return AncestryFacts(
        shas_in_ancestry=frozenset(shas),
        steps_verified_at_read=frozenset(declared),
        lane_advanced_past_resume=False,
    )


def _honest(source="x"):
    return ss.ScopeVerdict(extent_honest=True, reason="whole job", source=source)


def _dishonest(source="x", missing=("s3",)):
    return ss.ScopeVerdict(extent_honest=False, reason="under-declared",
                           source=source, missing=tuple(missing))


# ── 1. the null baseline ───────────────────────────────────────────────────────
class TestNullBaseline:
    def test_all_declared_is_always_honest(self):
        v = ss.AllDeclaredScope().scope_verdict(_complete_state(), None)
        assert v.extent_honest is True
        assert v.source == "all-declared"

    def test_empty_conjunction_is_honest(self):
        # The floor: with NO source wired, the declared extent is trusted (today's
        # behavior). This is what makes the seam opt-in / byte-identical when unused.
        c = ss.honest_under_floor(())
        assert c.extent_honest is True
        assert c.dishonest == ()
        assert c.missing == ()

    def test_null_source_in_conjunction_is_honest(self):
        null = ss.AllDeclaredScope().scope_verdict(_complete_state(), None)
        assert ss.honest_under_floor((null,)).extent_honest is True


# ── 2. the conjunction ─────────────────────────────────────────────────────────
class TestConjunction:
    def test_all_honest_is_honest(self):
        assert ss.honest_under_floor((_honest("a"), _honest("b"))).extent_honest is True

    def test_any_dishonest_wins(self):
        # One source flagging under-declaration withholds COMPLETE; the honest
        # majority cannot out-vote it (a source only pushes toward UNDERDECLARED).
        c = ss.honest_under_floor((_honest("a"), _dishonest("b"), _honest("c")))
        assert c.extent_honest is False
        assert len(c.dishonest) == 1
        assert c.dishonest[0].source == "b"

    def test_missing_is_unioned_deduped_order_preserving(self):
        c = ss.honest_under_floor((
            _dishonest("a", missing=("s3", "s4")),
            _dishonest("b", missing=("s4", "s5")),
        ))
        assert c.extent_honest is False
        assert c.missing == ("s3", "s4", "s5")

    def test_reason_honest_vs_dishonest(self):
        assert "honest" in ss.honest_under_floor((_honest(),)).reason
        r = ss.honest_under_floor((_dishonest("plan", missing=("s3",)),)).reason
        assert "under-declared" in r and "plan" in r and "s3" in r


# ── 3. fail-to-strict (run_scope) ──────────────────────────────────────────────
class _Raises:
    name = "boom"
    def scope_verdict(self, state, config):
        raise RuntimeError("scope check blew up")


class _ReturnsGarbage:
    name = "garbage"
    def scope_verdict(self, state, config):
        return {"extent_honest": True}  # not a ScopeVerdict


class _LiesHonest:
    """A hostile source that asserts honesty for a genuinely under-declared run."""
    name = "liar"
    def scope_verdict(self, state, config):
        return ss.ScopeVerdict(extent_honest=True, reason="trust me", source=self.name)


class TestFailToStrict:
    def test_raise_maps_to_dishonest(self):
        # A raising source withholds COMPLETE (fails to UNDERDECLARED), never grants.
        v = ss.run_scope(_Raises(), _complete_state(), None)
        assert v.extent_honest is False
        assert "raised" in v.reason
        assert v.source == "boom"

    def test_wrong_type_maps_to_dishonest(self):
        v = ss.run_scope(_ReturnsGarbage(), _complete_state(), None)
        assert v.extent_honest is False
        assert "not" in v.reason.lower()  # "... returned a dict, not a ScopeVerdict"

    def test_well_formed_verdict_passes_through(self):
        # An honest verdict is returned verbatim (not coerced).
        good = _LiesHonest()  # well-formed, just (in this test) wrong on the merits
        v = ss.run_scope(good, _complete_state(), None)
        assert v.extent_honest is True
        assert v.source == "liar"


# ── 4. the soundness proof — a lying source cannot manufacture COMPLETE ─────────
class TestSoundnessProof:
    """The structural guarantee: a `ScopeSource` can only WITHHOLD COMPLETE. A lying
    source that votes honest cannot turn an UNDERDECLARED (raised by another, honest
    source) back into COMPLETE — because the conjunction is an AND, and the lie is
    just one honest vote among the dishonest one that wins."""

    def test_lying_honest_cannot_override_a_dishonest_source(self):
        # A truthful source says under-declared; a liar says honest. COMPLETE is
        # still withheld — the AND means the dishonest vote wins.
        liar = _LiesHonest().scope_verdict(_complete_state(), None)
        truth = _dishonest("auditor", missing=("s3", "s4"))
        c = ss.honest_under_floor((liar, truth))
        assert c.extent_honest is False

    def test_lying_source_through_classify_cannot_grant_complete(self):
        # END-TO-END through the REAL completion.classify: a run that is genuinely
        # under-declared (an honest auditor flags it) stays UNDERDECLARED even with a
        # lying source present. The liar cannot manufacture a COMPLETE.
        state, anc = _complete_state(), _complete_anc()
        liar = _LiesHonest().scope_verdict(state, None)
        truth = _dishonest("auditor", missing=("s3",))
        v = cm.classify(state, anc, scope_verdicts=(liar, truth))
        assert v.state is cm.Completion.UNDERDECLARED
        assert v.state.is_done is False

    def test_a_lone_lying_source_is_no_worse_than_no_source(self):
        # The OTHER direction of the guarantee: a source can only make completion
        # HARDER. A lone source voting honest grants exactly what no source grants —
        # it cannot make an INCOMPLETE run COMPLETE (the residual gate is upstream and
        # untouched by scope). Here the run IS genuinely complete, so honest → COMPLETE,
        # identical to the no-source path.
        state, anc = _complete_state(), _complete_anc()
        liar = _LiesHonest().scope_verdict(state, None)
        assert cm.classify(state, anc, scope_verdicts=(liar,)).state is cm.Completion.COMPLETE
        assert cm.classify(state, anc).state is cm.Completion.COMPLETE  # same as no source


# ── 5. resolver ────────────────────────────────────────────────────────────────
class TestResolver:
    def test_built_in_resolves(self):
        assert ss.resolve_scope_source("all-declared").name == "all-declared"

    def test_unknown_fails_loud(self):
        with pytest.raises(ValueError, match="unknown scope source"):
            ss.resolve_scope_source("nope")

    def test_active_names_lists_built_in(self):
        assert "all-declared" in ss.active_scope_source_names()

    def test_active_sources_empty_by_default(self):
        # No config → empty list (NOT the null source); the default path runs no
        # source and is byte-identical to today.
        assert ss.active_scope_sources() == []
        assert ss.active_scope_sources(config=object()) == []

    def test_active_sources_resolves_configured_names(self):
        class Cfg:
            scope_source_names = ["all-declared"]
        srcs = ss.active_scope_sources(config=Cfg())
        assert [s.name for s in srcs] == ["all-declared"]


# ── 6. the reference driver ────────────────────────────────────────────────────
class TestDriver:
    def test_under_declared_is_dishonest_with_missing(self):
        from dos.drivers.plan_scope import PlanScopeSource
        st = LedgerState(run_id="R", declared_steps=("s1", "s2"))
        v = PlanScopeSource(expected=("s1", "s2", "s3", "s4")).scope_verdict(st, None)
        assert v.extent_honest is False
        assert v.missing == ("s3", "s4")
        assert v.source == "plan"

    def test_full_coverage_is_honest(self):
        from dos.drivers.plan_scope import PlanScopeSource
        st = LedgerState(run_id="R", declared_steps=("s1", "s2"))
        assert PlanScopeSource(expected=("s1", "s2")).scope_verdict(st, None).extent_honest

    def test_no_expected_account_votes_honest(self):
        # No injected set and no config field → no evidence of under-declaration →
        # honest (the source must not refuse completion for a workspace that declared
        # no expected scope).
        from dos.drivers.plan_scope import PlanScopeSource
        st = LedgerState(run_id="R", declared_steps=("s1",))
        assert PlanScopeSource().scope_verdict(st, None).extent_honest

    def test_expected_via_config(self):
        from dos.drivers.plan_scope import PlanScopeSource
        st = LedgerState(run_id="R", declared_steps=("s1", "s2"))
        class Cfg:
            expected_scope_steps = ("s1", "s2", "s9")
        v = PlanScopeSource().scope_verdict(st, Cfg())
        assert v.extent_honest is False
        assert v.missing == ("s9",)

    def test_driver_through_classify_emits_underdeclared(self):
        # The full intended path: the driver's verdict, fed to classify, flips a
        # COMPLETE run to UNDERDECLARED.
        from dos.drivers.plan_scope import PlanScopeSource
        state, anc = _complete_state(("s1", "s2")), _complete_anc(("s1", "s2"))
        sv = PlanScopeSource(expected=("s1", "s2", "s3")).scope_verdict(state, None)
        v = cm.classify(state, anc, scope_verdicts=(sv,))
        assert v.state is cm.Completion.UNDERDECLARED
        assert "s3" in v.reason

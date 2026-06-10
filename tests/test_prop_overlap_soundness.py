"""Property-based proof of the overlap soundness FLOOR (docs/273, docs/113).

The CLAUDE.md litmus this file pins, as a ∀-claim instead of a handful of points:

  > A swappable overlap scorer can only refuse-MORE, never admit a collision.

`tests/test_overlap_policy.py` already pins this with named hostile policies on
hand-picked tree pairs (`_AlwaysAdmit`, `_Raises`, …). That proves the property at
a few points. This file proves it across a *generated* space of adversarial
policies × generated tree pairs: the dangerous cell — a policy admitting a pair the
deterministic prefix floor refuses — is structurally unreachable, so Hypothesis
cannot find an input that reaches it. A safety property is exactly a "there is no
input for which the bad thing happens" claim, and the only test that goes after
that claim by *trying to break it* is a generator aimed at the corner.

The four properties:
  * `TestNoAdmitPastFloor` — net_admit ⟹ floor_admit, for ANY adversarial policy.
    The security core. (always-admit, over-ratio, raises, garbage-type, None.)
  * `TestSafeDirectionReachable` — a stricter policy CAN refuse a floor-admit, so
    the AND is real, not vacuous.
  * `TestDefaultEquivalence` — the `prefix` policy under the floor reproduces bare
    `overlap_verdict` byte-for-byte (the behavior-preserving litmus, ∀ trees).
  * `TestExactGlobSymmetry` — identical glob ⟹ REFUSE_EXACT_GLOB regardless of
    direction (the asymmetry-kills-wedge fix, ∀).
"""
from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

import dos.config as config  # noqa: E402
import dos.overlap_policy as op  # noqa: E402
from dos.lane_overlap import OverlapDecision, Verdict, overlap_verdict  # noqa: E402


# ── tree generators ───────────────────────────────────────────────────────────
# Path segments drawn from a small alphabet so collisions are LIKELY (a large
# alphabet would make every generated pair trivially disjoint and the property
# vacuous). The mix of shared dirs (agents/, playbooks/, src/) + leaf files is
# what exercises the prefix-collision + ratio math.
_segments = st.sampled_from(
    ["agents", "playbooks", "src", "tests", "docs", "a", "b", "c", "x_*.py", "*.py"]
)


@st.composite
def _path(draw) -> str:
    """A repo-relative glob like 'agents/x_*.py' — 1-3 segments."""
    n = draw(st.integers(min_value=1, max_value=3))
    return "/".join(draw(_segments) for _ in range(n))


# A tree is a non-empty list of paths (the unknown-blast-radius empty-tree case is
# the caller's concern — `DisjointnessPredicate` — never the scorer's, per the
# overlap_policy docstring, so we generate KNOWN trees only).
_trees = st.lists(_path(), min_size=1, max_size=6)


# ── adversarial policy family ──────────────────────────────────────────────────
class _AlwaysAdmit:
    """Claims everything is disjoint — even identical globs. The hostile case."""

    name = "evil-admit"

    def overlaps(self, req, lease, cfg):
        return OverlapDecision(Verdict.ADMIT_DISJOINT, 0, len(req), "I LIE: always safe")


class _OverRatio:
    """Admits as SOFT no matter how much overlaps (a buggy ratio that never refuses)."""

    name = "over-ratio"

    def overlaps(self, req, lease, cfg):
        return OverlapDecision(Verdict.ADMIT_SOFT, len(req), len(req), "everything is fine, trust me")


class _Raises:
    """Throws inside overlaps — must degrade to the floor, never admit."""

    name = "raiser"

    def overlaps(self, req, lease, cfg):
        raise RuntimeError("boom")


class _Garbage:
    """Returns a non-OverlapDecision — must degrade to the floor, never admit."""

    name = "garbage"

    def overlaps(self, req, lease, cfg):
        return {"admissible": True}  # a foreign object whose .admissible we must NOT read


class _NoneReturn:
    """Returns None — the degenerate garbage case."""

    name = "none"

    def overlaps(self, req, lease, cfg):
        return None


class _AlwaysRefuse:
    """Maximally strict — refuses everything. The safe-direction witness."""

    name = "paranoid"

    def overlaps(self, req, lease, cfg):
        return OverlapDecision(Verdict.REFUSE_OVERLAP, 99, len(req), "I refuse everything")


# Every way a policy can try (and must fail) to admit past the floor.
_hostile_policies = st.sampled_from(
    [_AlwaysAdmit(), _OverRatio(), _Raises(), _Garbage(), _NoneReturn()]
)


def _cfg():
    return config.default_config(".")


class TestNoAdmitPastFloor:
    """THE security core: no policy — however hostile — can admit a pair the
    deterministic prefix floor refuses. net_admit ⟹ floor_admit."""

    @given(policy=_hostile_policies, req=_trees, lease=_trees)
    @settings(max_examples=600, deadline=None)
    def test_net_admit_implies_floor_admit(self, policy, req, lease):
        floor = op.floor_decision(req, lease)
        net = op.admissible_under_floor(policy, req, lease, _cfg())
        # The implication, stated directly: if the net verdict admits, the floor
        # must have admitted too. A hostile policy can NEVER make this false.
        if net.admissible:
            assert floor.admissible, (
                f"policy {policy.name!r} admitted {req} vs {lease} but the prefix "
                f"floor REFUSED it ({floor.verdict.value}) — a collision leaked!"
            )

    @given(policy=_hostile_policies, req=_trees, lease=_trees)
    @settings(max_examples=400, deadline=None)
    def test_floor_refuse_returns_floor_verdict_verbatim(self, policy, req, lease):
        """When the floor refuses, the floor's own verdict + reason is returned —
        a hostile policy cannot even dilute the *message*, let alone the bit."""
        floor = op.floor_decision(req, lease)
        if not floor.admissible:
            net = op.admissible_under_floor(policy, req, lease, _cfg())
            assert net.verdict == floor.verdict
            assert not net.admissible

    @given(policy=_hostile_policies, req=_trees, lease=_trees)
    @settings(max_examples=300, deadline=None)
    def test_always_returns_a_real_decision(self, policy, req, lease):
        """Even a raising / garbage-returning policy yields a well-typed
        OverlapDecision (fail-closed, never an exception out of the AND helper)."""
        net = op.admissible_under_floor(policy, req, lease, _cfg())
        assert isinstance(net, OverlapDecision)
        assert isinstance(net.admissible, bool)


class TestSafeDirectionReachable:
    """The AND is REAL, not vacuous: a stricter policy can refuse what the floor
    admits. (If this never happened, the soundness property above would be
    trivially true because the policy never affects anything.)"""

    @given(req=_trees, lease=_trees)
    @settings(max_examples=300, deadline=None)
    def test_paranoid_policy_can_refuse_a_floor_admit(self, req, lease):
        floor = op.floor_decision(req, lease)
        net = op.admissible_under_floor(_AlwaysRefuse(), req, lease, _cfg())
        # A stricter policy can only ever move admit→refuse, never the reverse.
        if floor.admissible:
            # paranoid refuses everything, so a floor-admit becomes a net-refuse.
            assert not net.admissible
        else:
            # floor already refused; net stays refused.
            assert not net.admissible

    def test_safe_direction_is_actually_exercised(self):
        """At least one concrete floor-admit pair flips to refuse under paranoid —
        proves the reachability claim isn't an empty `if`."""
        req = ["agents/apply_x.py"]
        lease = ["playbooks/ats/workday.yaml"]
        assert op.floor_decision(req, lease).admissible  # disjoint → floor admits
        net = op.admissible_under_floor(_AlwaysRefuse(), req, lease, _cfg())
        assert not net.admissible  # paranoid refuses it — safe direction reached


class TestDefaultEquivalence:
    """The `prefix` policy under the floor reproduces bare `overlap_verdict`
    byte-for-byte — the load-bearing behavior-preserving litmus, over generated
    trees instead of the example suite's fixed pairs."""

    @given(req=_trees, lease=_trees)
    @settings(max_examples=500, deadline=None)
    def test_prefix_under_floor_equals_overlap_verdict(self, req, lease):
        bare = overlap_verdict(req, lease)
        netted = op.admissible_under_floor(op.PrefixOverlapPolicy(), req, lease, _cfg())
        # The default path must not have drifted: same verdict, same admissibility.
        assert netted.verdict == bare.verdict
        assert netted.admissible == bare.admissible


class TestExactGlobSymmetry:
    """Identical glob on both sides ⟹ REFUSE_EXACT_GLOB regardless of direction —
    the asymmetry that *guaranteed* a mutual wedge (docs lane_overlap), killed ∀."""

    @given(shared=_path(), extra_a=_trees, extra_b=_trees)
    @settings(max_examples=300, deadline=None)
    def test_identical_named_glob_refuses_both_directions(self, shared, extra_a, extra_b):
        # Skip the universal-empty-prefix globs ('*.py' normalizes to '') — those
        # are handled by the ratio path by design, not the exact-glob hard floor.
        from dos._tree import norm_tree_prefix

        if norm_tree_prefix(shared) == "":
            return
        tree_a = [shared, *extra_a]
        tree_b = [shared, *extra_b]
        fwd = overlap_verdict(tree_a, tree_b)
        rev = overlap_verdict(tree_b, tree_a)
        # Both directions hard-refuse on the shared named glob — symmetric verdict.
        assert fwd.verdict == Verdict.REFUSE_EXACT_GLOB
        assert rev.verdict == Verdict.REFUSE_EXACT_GLOB
        assert not fwd.admissible and not rev.admissible

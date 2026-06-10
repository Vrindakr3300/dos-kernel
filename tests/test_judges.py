"""Tests for the judge seam (`dos.judges`) — Axis 6, the JUDGE rung of the trust ladder.

The pinned contract:

  The verdict type (advisory-only by shape):
    * `JudgeVerdict` has exactly three constructors — `.agree()/.disagree()/.abstain()`
      — and carries nothing mutable; a judge's whole expressible output is the stance.

  The fail-to-ABSTAIN guarantee (the load-bearing safety property):
    * `run_judge` converts a RAISE into ABSTAIN, never AGREE;
    * `run_judge` converts a non-`JudgeVerdict` return (None / dict / truthy
      look-alike) into ABSTAIN — no false-clear can sneak through a wrong type;
    * the asymmetry vs predicates is deliberate: a judge fails to "I don't know"
      (advisory), a predicate fails to "deny" (safety) — neither to "approve."

  The built-in baseline + resolution:
    * `AbstainJudge` ("abstain") is built-in, always resolvable, abstains on all;
    * a plugin CANNOT shadow the built-in `abstain` (built-ins resolve first);
    * an unknown judge name fails LOUD with the known list (never a silent fallback).
"""

from __future__ import annotations

import pytest

from dos import judges
from dos.judges import (
    AbstainJudge,
    Claim,
    Judge,
    JudgeVerdict,
    Stance,
    resolve_judge,
    run_judge,
)


# ---------------------------------------------------------------------------
# JudgeVerdict — the three-valued, advisory-only verdict.
# ---------------------------------------------------------------------------

def test_verdict_constructors_and_accessors():
    a = JudgeVerdict.agree("backed by a commit")
    d = JudgeVerdict.disagree("no artifact")
    s = JudgeVerdict.abstain("can't tell")
    assert (a.stance, a.agreed, a.disagreed, a.abstained) == (Stance.AGREE, True, False, False)
    assert (d.stance, d.disagreed) == (Stance.DISAGREE, True)
    assert (s.stance, s.abstained) == (Stance.ABSTAIN, True)
    assert a.why == "backed by a commit"


def test_verdict_is_frozen_no_mutable_state():
    """A judge returns a frozen verdict and is handed nothing it could mutate — the
    advisory-only invariant by shape. The verdict carries only stance/why/evidence/
    cost; there is no lease/registry/state handle to scribble on."""
    v = JudgeVerdict.agree("x", cost=2.5)
    with pytest.raises(Exception):
        v._stance = Stance.DISAGREE  # frozen dataclass
    # the only fields are inert data
    assert set(v.to_dict()) == {"stance", "why", "evidence", "cost"}
    assert v.cost == 2.5


def test_claim_is_domain_neutral():
    """A Claim is a generic narration+evidence triple — not coupled to no-pick rows."""
    c = Claim("phase AUTH2 shipped", "trust me", ("git: no commit",), subject="RID-1")
    assert c.claim_text == "phase AUTH2 shipped"
    assert c.evidence == ("git: no commit",)
    # evidence defaults to an empty tuple (not None) so a judge can always iterate it
    assert Claim("bare").evidence == ()


# ---------------------------------------------------------------------------
# run_judge — fail-to-ABSTAIN (the safety property).
# ---------------------------------------------------------------------------

class _Raises:
    name = "boom"
    def rule(self, claim, config):
        raise RuntimeError("kaboom")


class _ReturnsTruthyNonVerdict:
    """A buggy/hostile judge that returns a truthy non-verdict — the shape that could
    sneak an 'agree' through if the runner consulted `.agreed` on a foreign object."""
    name = "liar"
    def rule(self, claim, config):
        return True


class _ReturnsNone:
    name = "none"
    def rule(self, claim, config):
        return None


@pytest.mark.parametrize("judge", [_Raises(), _ReturnsTruthyNonVerdict(), _ReturnsNone()])
def test_run_judge_fails_to_abstain_never_agree(judge):
    v = run_judge(judge, Claim("anything"), None)
    assert v.stance is Stance.ABSTAIN
    # the dangerous outcome — a failure becoming an AGREE — must be impossible
    assert not v.agreed


def test_run_judge_passes_through_a_well_typed_verdict():
    class Good:
        name = "good"
        def rule(self, claim, config):
            return JudgeVerdict.disagree("no evidence")
    v = run_judge(Good(), Claim("x"), None)
    assert v.stance is Stance.DISAGREE and v.why == "no evidence"


def test_run_judge_failure_is_asymmetric_with_predicates():
    """Documents the deliberate asymmetry: a judge fails to ABSTAIN (advisory), where
    `admission.run_predicates` fails to REFUSE (safety). Both refuse to APPROVE on
    failure; they differ only in which non-approval is safe for their role."""
    from dos.admission import AdmissionRequest, run_predicates

    class BadPred:
        name = "bad"
        def __call__(self, request, live_lease, config):
            raise RuntimeError("x")

    judge_v = run_judge(_Raises(), Claim("x"), None)
    pred_v = run_predicates([BadPred()], AdmissionRequest("a", "k", ()), [], None)
    assert judge_v.abstained          # judge: "I don't know"
    assert not pred_v.admitted        # predicate: "deny"


# ---------------------------------------------------------------------------
# AbstainJudge + resolution.
# ---------------------------------------------------------------------------

def test_abstain_judge_is_built_in_and_abstains():
    j = resolve_judge("abstain")
    assert isinstance(j, AbstainJudge)
    assert run_judge(j, Claim("phase A shipped", evidence=("commit abc",)), None).stance is Stance.ABSTAIN


def test_abstain_judge_satisfies_the_protocol():
    assert isinstance(AbstainJudge(), Judge)  # runtime_checkable Protocol


def test_unknown_judge_fails_loud_with_known_list():
    with pytest.raises(ValueError) as ei:
        resolve_judge("does-not-exist")
    msg = str(ei.value)
    assert "unknown judge" in msg and "abstain" in msg  # names the known set


def test_plugin_cannot_shadow_builtin_abstain(monkeypatch):
    """A discovered plugin named `abstain` must NOT displace the built-in — built-ins
    resolve first (the trusted-fallback guarantee, identical to renderers)."""
    class EvilAbstain:
        name = "abstain"
        def rule(self, claim, config):
            return JudgeVerdict.agree("I clear everything")  # the opposite of safe

    monkeypatch.setattr(
        judges, "_discover_entry_point_judges",
        lambda *, _stderr=None: [("abstain", EvilAbstain())],
    )
    j = resolve_judge("abstain")
    # still the built-in: it ABSTAINS, it does not clear
    assert isinstance(j, AbstainJudge)
    assert run_judge(j, Claim("x"), None).stance is Stance.ABSTAIN


def test_active_judges_lists_builtin_then_discovered(monkeypatch):
    class Mine:
        name = "mine"
        def rule(self, claim, config):
            return JudgeVerdict.abstain()
    monkeypatch.setattr(
        judges, "_discover_entry_point_judges",
        lambda *, _stderr=None: [("mine", Mine())],
    )
    assert judges.active_judge_names() == ["abstain", "mine"]


def test_discovery_fault_degrades_to_builtin(monkeypatch):
    """A broken discovery never crashes a caller — it degrades to the built-in set."""
    def boom(*, _stderr=None):
        raise RuntimeError("importlib exploded")
    monkeypatch.setattr(judges, "_discover_entry_point_judges", boom)
    # resolve_judge for a built-in still works even if discovery would raise
    # (built-ins are checked before discovery is consulted)
    assert isinstance(resolve_judge("abstain"), AbstainJudge)

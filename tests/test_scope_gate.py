"""The binding pre-effect scope gate (docs/102 §5) — refuse an out-of-tree WRITE
before it lands, instead of DETECTING the clobber after the commit.

`scope.gate` is the prevention sibling of `scope.classify`: the SAME containment
algebra, but it returns an ALLOW/REFUSE *decision* a caller acts on at the edit
boundary, not an advisory grade it files post-hoc. These tests pin:

  * the verdict→decision map (IN_SCOPE allows; SCOPE_CREEP/WRONG_TARGET refuse);
  * that the gate inherits `classify`'s purity (no I/O — replay-testable);
  * that it inherits `classify`'s policy seam (shared-infra / creep tolerance
    flow through, so the gate never re-implements containment);
  * the one-way-safety floor on the policy (IN_SCOPE can never be made refusable);
  * the docs/102 §5 north-star: an under-declared write is REFUSED pre-effect.
"""

from __future__ import annotations

import json

import pytest

from dos import scope
from dos.scope import (
    Scope,
    ScopePolicy,
    ScopeEvidence,
    ScopeGatePolicy,
    ScopeGate,
    gate,
    DEFAULT_GATE_POLICY,
)


def _ev(touched, tree=("effort-03/",), lane="lane-03") -> ScopeEvidence:
    """A ScopeEvidence with the bench's effort-subtree shape; override per test.

    Mirrors `test_scope._ev` so the gate is exercised on the IDENTICAL fixtures the
    post-hoc verdict is — the two verbs share the algebra, so they share the corpus.
    """
    return ScopeEvidence(touched_files=frozenset(touched), lane_tree=tuple(tree), lane=lane)


# ---------------------------------------------------------------------------
# 1. The verdict → ALLOW/REFUSE map (the gate's whole job).
# ---------------------------------------------------------------------------


def test_contained_write_is_allowed():
    """Every proposed file inside the lane's tree → ALLOW (the commitment kept)."""
    g = gate(_ev(["effort-03/mod_1.txt", "effort-03/sub/mod_2.txt"]))
    assert isinstance(g, ScopeGate)
    assert g.allowed is True
    assert g.verdict is Scope.IN_SCOPE
    assert g.refused_files == ()
    assert g.reason.startswith("write ALLOWED")


def test_overrunning_write_is_refused_scope_creep():
    """A write that touches its lane AND reaches another effort's tree → REFUSE.

    The docs/102 §5 north-star, pre-effect: the agent under-declared (it claimed
    lane-03 but its patch also writes effort-07/), and the gate REFUSES that write
    before it can silently clobber effort-07's holder — collision-PREVENTION where
    `classify` would only have DETECTED it after the commit ("you cannot un-clobber").
    """
    g = gate(_ev(["effort-03/mod_1.txt", "effort-07/mod_9.txt"]))
    assert g.allowed is False
    assert g.verdict is Scope.SCOPE_CREEP
    assert "effort-07/mod_9.txt" in g.refused_files
    assert g.reason.startswith("write REFUSED (SCOPE_CREEP)")


def test_total_miss_write_is_refused_wrong_target():
    """A proposed write entirely outside the claimed lane → REFUSE (WRONG_TARGET)."""
    g = gate(_ev(["effort-07/mod_9.txt", "effort-09/mod_2.txt"]))
    assert g.allowed is False
    assert g.verdict is Scope.WRONG_TARGET
    assert set(g.refused_files) == {"effort-07/mod_9.txt", "effort-09/mod_2.txt"}


def test_empty_footprint_is_allowed():
    """A write of nothing escapes nothing → ALLOW (the benign floor — the gate
    never blocks a no-op, mirroring `classify`'s empty-diff IN_SCOPE)."""
    g = gate(_ev([]))
    assert g.allowed is True
    assert g.verdict is Scope.IN_SCOPE


def test_undeclared_lane_write_is_refused():
    """An EMPTY lane tree is an UNKNOWN blast radius — the gate will NOT let a
    non-empty write land against a lane it cannot certify containment for
    (the conservative `_tree.lane_trees_disjoint` stance, now enforced pre-effect)."""
    g = gate(_ev(["effort-03/mod_1.txt"], tree=(), lane="undeclared"))
    assert g.allowed is False
    assert g.verdict is Scope.WRONG_TARGET
    # ...but an undeclared lane with an EMPTY write is still allowed (nothing to escape).
    assert gate(_ev([], tree=(), lane="undeclared")).allowed is True


def test_generic_tree_allows_everything():
    """The GENERIC lane tree `("**/*",)` (the no-plan floor) allows any write — a
    workspace that declared no lanes has no scope to bind against."""
    g = gate(_ev(["anywhere/at/all.py", "shared/x.txt"], tree=("**/*",), lane="main"))
    assert g.allowed is True
    assert g.verdict is Scope.IN_SCOPE


# ---------------------------------------------------------------------------
# 2. The gate inherits classify's POLICY seam (it never re-implements containment).
# ---------------------------------------------------------------------------


def test_shared_infra_spill_allowed_by_default():
    """A write touching the lane plus ONLY hub files (`config.py`, `__init__.py`) is
    ALLOWED by default — those are never a phase's distinctive deliverable, so the
    gate inherits `classify`'s shared-infra tolerance rather than blocking them."""
    g = gate(_ev(["effort-03/mod_1.txt", "effort-03/__init__.py", "config.py"]))
    assert g.allowed is True
    assert g.verdict is Scope.IN_SCOPE


def test_shared_infra_refused_when_inner_policy_off():
    """Turning the inner `ScopePolicy.allow_shared_infra` off makes the same hub
    spill a SCOPE_CREEP → REFUSE — proving the inner policy flows straight through
    the gate (the gate is `classify(scope_policy)` + the decision map, nothing more)."""
    pol = ScopeGatePolicy(scope=ScopePolicy(allow_shared_infra=False))
    g = gate(_ev(["effort-03/mod_1.txt", "config.py"]), pol)
    assert g.allowed is False
    assert g.verdict is Scope.SCOPE_CREEP


def test_creep_tolerance_flows_through():
    """`ScopePolicy.creep_tolerance` absorbs a small spill into ALLOW; a second
    out-of-tree file tips it to REFUSE — the tolerance the inner policy owns."""
    pol = ScopeGatePolicy(scope=ScopePolicy(creep_tolerance=1))
    one = gate(_ev(["effort-03/a.txt", "effort-07/x.txt"]), pol)
    assert one.allowed is True
    two = gate(_ev(["effort-03/a.txt", "effort-07/x.txt", "effort-09/y.txt"]), pol)
    assert two.allowed is False
    assert two.verdict is Scope.SCOPE_CREEP


def test_refuse_on_can_be_loosened_to_creep_only():
    """A host that only wants to block the SEVERE total-miss can drop SCOPE_CREEP
    from `refuse_on` — a partial overrun then ALLOWS (the host accepts incidental
    spill) while a WRONG_TARGET still REFUSES. The decision map is policy."""
    pol = ScopeGatePolicy(refuse_on=frozenset({Scope.WRONG_TARGET}))
    creep = gate(_ev(["effort-03/a.txt", "effort-07/x.txt"]), pol)
    assert creep.allowed is True  # SCOPE_CREEP no longer refuses under this policy
    miss = gate(_ev(["effort-07/x.txt"]), pol)
    assert miss.allowed is False  # WRONG_TARGET still does


def test_policy_rejects_refusing_in_scope():
    """The one-way-safety floor: a gate that refuses a fully-contained write refuses
    everything (a bricked workspace), so IN_SCOPE can NEVER be in `refuse_on`."""
    with pytest.raises(ValueError):
        ScopeGatePolicy(refuse_on=frozenset({Scope.IN_SCOPE}))


def test_policy_normalizes_iterable_refuse_on():
    """`refuse_on` passed as a plain set is normalized to a frozenset (the policy is
    frozen/hashable like every other kernel policy)."""
    pol = ScopeGatePolicy(refuse_on={Scope.SCOPE_CREEP, Scope.WRONG_TARGET})
    assert isinstance(pol.refuse_on, frozenset)


# ---------------------------------------------------------------------------
# 3. Purity (inherited from classify) + the json/renderer seam.
# ---------------------------------------------------------------------------


def test_gate_is_pure(monkeypatch):
    """`gate()` makes no subprocess/file/clock call — it delegates to the pure
    `classify`, so the I/O of GATHERING the proposed write-set stays at the caller's
    edge (the arbiter discipline that lets the gate be replay-tested on fixtures)."""
    import builtins
    import subprocess
    import time as _time

    def _boom(*a, **k):  # pragma: no cover - only runs if purity is violated
        raise AssertionError("gate() performed I/O — it must be pure")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(_time, "time", _boom)

    assert gate(_ev(["effort-03/a.txt"])).allowed is True
    assert gate(_ev(["effort-03/a.txt", "effort-07/x.txt"])).allowed is False
    assert gate(_ev(["effort-07/x.txt"])).allowed is False
    assert gate(_ev([])).allowed is True
    assert gate(_ev(["x.txt"], tree=())).allowed is False


def test_gate_to_dict_round_trips():
    """`--output json` payload carries the binding bit, the verdict, the refused
    spill, AND the full underlying scope verdict (so a consumer gets both the
    decision and the legible grade from one call). JSON-serialisable."""
    g = gate(_ev(["effort-03/a.txt", "effort-07/x.txt"]))
    d = g.to_dict()
    assert d["allowed"] is False
    assert d["verdict"] == "SCOPE_CREEP"
    assert "effort-07/x.txt" in d["refused_files"]
    # the nested scope verdict is the full classify() to_dict — both views in one.
    assert d["scope"]["verdict"] == "SCOPE_CREEP"
    assert "effort-03/a.txt" in d["scope"]["in_scope_files"]
    json.dumps(d)


def test_default_gate_policy_refuses_creep_and_wrong_target():
    """The shipped default refuses exactly the two non-contained verdicts (only
    IN_SCOPE allows) — the strict pre-effect stance the §5 fix needs."""
    assert DEFAULT_GATE_POLICY.refuse_on == frozenset({Scope.SCOPE_CREEP, Scope.WRONG_TARGET})


# ---------------------------------------------------------------------------
# 4. The prevention-vs-detection equivalence: the gate's ALLOW bit is exactly
#    "the post-hoc verdict would have been clean", so it catches the SAME
#    under-declaration `classify` would — only EARLIER (before the write).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("touched", [
    ["effort-03/a.txt"],                       # contained
    ["effort-03/a.txt", "effort-07/x.txt"],    # creep
    ["effort-07/x.txt"],                       # wrong target
    [],                                        # empty
])
def test_gate_allow_matches_classify_in_scope(touched):
    """`gate(ev).allowed` is True iff `classify(ev)` is IN_SCOPE under the default
    policy — the gate is the prevention framing of the exact detection `classify`
    does, the docs/102 §5 "same shape, moved before the write" made literal."""
    ev = _ev(touched)
    allowed = gate(ev).allowed
    is_in_scope = scope.classify(ev).verdict is Scope.IN_SCOPE
    assert allowed == is_in_scope

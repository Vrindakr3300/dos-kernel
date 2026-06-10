"""The typed-verdict contract (docs/86 §1) — proof the two instances conform.

`verdict.TypedVerdict` / `verdict.conforms` name the shape `liveness` and `scope`
already share. These tests pin that:
  * both real verdicts satisfy the contract (so a future `dos.verdicts.register`
    would accept them);
  * a bare-bool / non-enum "verdict" is REJECTED (the typed-over-binary law is
    actually enforced, not just documented);
  * the contract adds no import coupling (the verbs don't depend on it).
"""

from __future__ import annotations

import dataclasses

from dos import verdict as verdict_mod
from dos.verdict import TypedVerdict, conforms


def _liveness_verdict():
    from dos.liveness import classify, ProgressEvidence, DEFAULT_POLICY
    ev = ProgressEvidence(run_started_ms=0, now_ms=10, commits_since_start=1)
    return classify(ev, DEFAULT_POLICY)


def _scope_verdict():
    from dos.scope import classify, ScopeEvidence
    ev = ScopeEvidence(touched_files=frozenset({"effort-03/a.txt"}),
                       lane_tree=("effort-03/",), lane="lane-03")
    return classify(ev)


def test_liveness_verdict_conforms():
    v = _liveness_verdict()
    assert isinstance(v, TypedVerdict)   # structural Protocol satisfaction
    assert conforms(v)


def test_scope_verdict_conforms():
    v = _scope_verdict()
    assert isinstance(v, TypedVerdict)
    assert conforms(v)


def test_both_verdicts_share_the_wire_shape():
    """The point of the contract: a consumer can treat both uniformly — same
    .verdict/.reason/.to_dict() surface, different closed vocabularies."""
    for v in (_liveness_verdict(), _scope_verdict()):
        d = v.to_dict()
        assert isinstance(d["verdict"], str)   # the enum's .value
        assert isinstance(d["reason"], str)
        assert v.verdict.value == d["verdict"]


def test_bare_bool_verdict_is_rejected():
    """A 'verdict' whose value is a bare bool (a binary gate) does NOT conform —
    the typed-verdict-over-binary-gate law, enforced at the contract boundary."""

    @dataclasses.dataclass(frozen=True)
    class BoolVerdict:
        verdict: bool = True
        reason: str = "shipped"

        def to_dict(self) -> dict:
            return {"verdict": self.verdict, "reason": self.reason}

    assert not conforms(BoolVerdict())


def test_ship_verdict_is_the_legacy_variant():
    """`oracle.ShipVerdict` is the THIRD instance that DRIFTED from the shape
    (`shipped: bool` + `source`, no `.verdict`/`.reason`). It does NOT conform
    today — pinning that fact so the docs/86 §4 step-1 harmonization (give it a
    `.verdict: Ship` enum view) has a regression target. This is a documented
    gap, not a bug."""
    from dos import oracle
    sv = oracle.ShipVerdict(plan="P", phase="P1", shipped=True, source="registry")
    # It has no `.verdict` enum / `.reason`, so it is not yet a TypedVerdict.
    assert not conforms(sv)


def test_contract_module_imports_nothing_from_the_verbs():
    """The arrow points one way: a consumer reads the contract; the verbs do not
    depend on it. `verdict.py` must not import liveness/scope/oracle (that would
    invert the dependency and risk a cycle)."""
    import pathlib
    src = pathlib.Path(verdict_mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("import liveness", "from dos.liveness", "from dos.scope",
                      "from dos.oracle", "import dos.oracle"):
        assert forbidden not in src, f"verdict.py should not couple to a verb: {forbidden}"

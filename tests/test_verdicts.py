"""The verdict registry (docs/86 §2) — the OS-extensibility surface.

`verdicts.py` is the verb-analogue of the `[reasons]`/`[lanes]`/`[stamp]` data
registries: an OPEN set of verbs, each a CLOSED verdict shape. These tests pin:
  * the two seed instances (liveness, scope) are registered and look up;
  * registration is total + rejects duplicates;
  * `validate_sample` is gate (4) — it accepts a real verdict, rejects a bad one;
  * `verify` is NOT registered (ShipVerdict fails gate 4 until harmonized — the
    honest drift marker);
  * the one-way arrow: the pure verb modules do not import the registry.
"""

from __future__ import annotations

import pytest

from dos import verdicts
from dos.verdicts import VerdictSpec, register, get, names, validate_sample, unreviewed


def test_seed_verbs_registered():
    """liveness + scope — the two instances that prove the shape — are present."""
    assert "liveness" in names()
    assert "scope" in names()
    assert get("liveness").distrusts == "I'm making progress"
    assert "lane" in get("scope").distrusts


def test_verify_is_not_registered_yet():
    """`verify` is deliberately absent: `oracle.ShipVerdict` fails gate (4) today
    (no `.verdict` enum). Its absence is the documented-drift marker (docs/86 §4
    step-1), not an oversight — pin it so harmonizing ShipVerdict + registering
    `verify` is a visible future step, not a silent gap."""
    assert "verify" not in names()


def test_registered_classify_runs_through_the_spec():
    """A consumer can dispatch a verdict purely through the registry (the point of
    the seam): pull the spec, call its `classify`, get a conforming verdict."""
    from dos.scope import ScopeEvidence
    spec = get("scope")
    v = spec.classify(ScopeEvidence(
        touched_files=frozenset({"effort-03/a.txt", "effort-07/x.txt"}),
        lane_tree=("effort-03/",), lane="lane-03"))
    assert v.verdict.value == "SCOPE_CREEP"
    assert validate_sample(spec, v)  # gate (4): the produced verdict conforms


def test_validate_sample_rejects_a_nonconforming_verdict():
    """Gate (4) actually rejects: a bare-bool 'verdict' is not the typed shape."""
    import dataclasses

    @dataclasses.dataclass(frozen=True)
    class Boolish:
        verdict: bool = True
        reason: str = "ok"

        def to_dict(self):
            return {"verdict": self.verdict}

    spec = get("liveness")
    assert not validate_sample(spec, Boolish())


def test_register_rejects_duplicate_then_allows_replace():
    """Name uniqueness (a registry, not a multimap); `replace=True` overrides."""
    from dos.scope import classify as scope_classify
    spec = VerdictSpec(name="probe-test", classify=scope_classify,
                       summary="x", distrusts="y")
    register(spec)
    try:
        with pytest.raises(ValueError):
            register(VerdictSpec(name="probe-test", classify=scope_classify,
                                 summary="x2", distrusts="y2"))
        # replace=True is the explicit override.
        register(VerdictSpec(name="probe-test", classify=scope_classify,
                             summary="x3", distrusts="y3"), replace=True)
        assert get("probe-test").summary == "x3"
    finally:
        verdicts._REGISTRY.pop("probe-test", None)  # keep the global registry clean


def test_spec_validates_name_and_callable():
    from dos.scope import classify as scope_classify
    with pytest.raises(ValueError):
        VerdictSpec(name="", classify=scope_classify, summary="s", distrusts="d")
    with pytest.raises(ValueError):
        VerdictSpec(name="bad", classify="not-callable", summary="s", distrusts="d")  # type: ignore[arg-type]


def test_seed_verbs_are_reviewed():
    """The two seed verbs are human-reviewed for gates (1)–(3); the audit hook
    `unreviewed()` therefore does not list them (it would flag an unvetted verb)."""
    assert "liveness" not in unreviewed()
    assert "scope" not in unreviewed()


def test_verbs_do_not_import_the_registry():
    """The one-way arrow (no cycle): a verdict VERB module must not import the
    registry — the registry imports the verbs (consumer → verb), like cli.py."""
    import pathlib
    from dos import liveness, scope
    for mod in (liveness, scope):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        assert "import verdicts" not in src and "from dos.verdicts" not in src, (
            f"{mod.__name__} must not import the registry (would invert the arrow)"
        )

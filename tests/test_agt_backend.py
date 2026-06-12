"""Contract tests for `dos.drivers.agt_backend` (docs/302).

Phase 1 — the three-row verdict mapping for both seats, driven through the
injected test seams; no `agent_os` package required (the duck-typed twin).

Phase 2 — the integration slice observed through the REAL published host
package (`pip install agent-governance-toolkit`, imports as `agent_os`):
protocol conformance, bind/skip semantics inside their evaluator, and the
evidence fields arriving in `PolicyDecision.audit_entry`. Skip-marked when the
package is absent so the core suite never depends on the optional host.
"""

from __future__ import annotations

import dataclasses

import pytest

from dos.arbiter import LaneDecision
from dos.drivers.agt_backend import (
    DosBackend,
    _agt_available,
    _construct,
    _decision_cls,
    _LocalBackendDecision,
)
from dos.oracle import ShipVerdict

AGT_INSTALLED = _agt_available()
needs_agt = pytest.mark.skipif(
    not AGT_INSTALLED,
    reason="real host package required: pip install agent_os_kernel",
)


def _evidence_supported() -> bool:
    """Does the ACTIVE decision class carry the evidence pair?

    The local twin always does; the published host package only from the
    version that added `proof_artefact`/`verification_pointers` (the clone's
    4.x line — `agent_os_kernel` 3.7.0 predates it).
    """
    names = {f.name for f in dataclasses.fields(_decision_cls())}
    return "proof_artefact" in names


def _shipped(plan: str, phase: str) -> ShipVerdict:
    return ShipVerdict(plan=plan, phase=phase, shipped=True,
                       sha="abc1234", source="registry")


def _unshipped(plan: str, phase: str) -> ShipVerdict:
    return ShipVerdict(plan=plan, phase=phase, shipped=False, source="none")


CLAIM = {"dos_plan": "docs/302_agt-external-policy-backend-driver-plan",
         "dos_phase": "P1"}


# ---------------------------------------------------------------------------
# The protocol surface.
# ---------------------------------------------------------------------------


def test_name_is_dos():
    assert DosBackend(verifier=_shipped).name == "dos"


def test_unknown_seat_raises():
    with pytest.raises(ValueError, match="unknown seat"):
        DosBackend(seat="transform")


def test_local_twin_carries_exactly_the_agt_field_names():
    # The duck-typed twin must expose every field AGT's evaluator (and audit
    # consumers) read; a drift here is invisible until a host crashes on it.
    names = {f.name for f in dataclasses.fields(_LocalBackendDecision)}
    assert names == {
        "allowed", "action", "reason", "backend", "raw_result",
        "evaluation_ms", "error", "proof_artefact", "verification_pointers",
    }


@pytest.mark.skipif(AGT_INSTALLED, reason="agent_os present — loud path moot")
def test_require_agt_raises_with_install_hint_when_absent():
    with pytest.raises(ImportError, match="agent-governance-toolkit"):
        DosBackend(require_agt=True, verifier=_shipped)


# ---------------------------------------------------------------------------
# The verify seat — the three-row mapping.
# ---------------------------------------------------------------------------


def test_verify_shipped_binds_allow_with_evidence():
    d = DosBackend(verifier=_shipped).evaluate(dict(CLAIM))
    assert d.allowed is True
    assert d.action == "allow"
    assert d.error is None                      # binds — never skipped
    assert d.backend == "dos"
    assert d.reason.startswith("dos:verified-shipped")
    assert d.evaluation_ms >= 0
    assert d.raw_result["shipped"] is True      # the ShipVerdict, replayable
    assert d.raw_result["sha"] == "abc1234"     # evidence survives any host version
    if _evidence_supported():
        assert d.proof_artefact == "git:abc1234"
        assert d.verification_pointers["plan"] == CLAIM["dos_plan"]
        assert d.verification_pointers["phase"] == "P1"
        assert d.verification_pointers["source"] == "registry"


def test_construct_filters_fields_for_old_host_versions():
    # The published agent_os_kernel 3.7.0 BackendDecision lacks the evidence
    # pair; an unknown kwarg must be dropped, not crash the bind into an abstain.
    @dataclasses.dataclass
    class _Old:
        allowed: bool
        action: str = "allow"
        reason: str = ""
        backend: str = ""
        raw_result: object = None
        evaluation_ms: float = 0.0
        error: str | None = None

    d = _construct(_Old, allowed=True, action="allow", reason="r",
                   backend="dos", error=None,
                   proof_artefact="git:abc1234",
                   verification_pointers={"plan": "p"})
    assert d.allowed is True
    assert d.error is None
    assert not hasattr(d, "proof_artefact")


def test_verify_unshipped_binds_deny():
    d = DosBackend(verifier=_unshipped).evaluate(dict(CLAIM))
    assert d.allowed is False
    assert d.action == "deny"
    assert d.error is None                      # a definite negative binds too
    assert d.reason.startswith("dos:unverified-claim")
    assert getattr(d, "proof_artefact", None) is None   # no proof on a miss


def test_verify_underspecified_context_abstains():
    backend = DosBackend(verifier=_shipped)
    for ctx in ({}, {"dos_plan": "docs/302"}, {"dos_phase": "P1"},
                {"tool_name": "file_read", "agent_id": "a-1"}):
        d = backend.evaluate(dict(ctx))
        assert d.error is not None and d.error.startswith("abstain:")
        assert d.allowed is False               # no phantom allow on the skip row


def test_failed_evaluation_abstains_never_fabricates():
    def boom(plan, phase):
        raise RuntimeError("oracle state unreadable")

    d = DosBackend(verifier=boom).evaluate(dict(CLAIM))
    assert d.error is not None
    assert d.error.startswith("abstain: dos evaluation failed")
    assert d.allowed is False


# ---------------------------------------------------------------------------
# The arbitrate seat.
# ---------------------------------------------------------------------------


def test_arbitrate_acquire_binds_allow():
    fn = lambda lane, kind, tree: LaneDecision("acquire", lane=lane, tree=tree)  # noqa: E731
    d = DosBackend(seat="arbitrate", arbitrate_fn=fn).evaluate(
        {"dos_tree": ["src/dos/drivers/"]})
    assert d.allowed is True
    assert d.action == "allow"
    assert d.error is None
    assert d.reason.startswith("dos:admitted")
    assert d.raw_result["outcome"] == "acquire"


def test_arbitrate_refuse_binds_deny_with_namespaced_reason():
    fn = lambda lane, kind, tree: LaneDecision(  # noqa: E731
        "refuse", reason="requested tree overlaps live lane 'src'")
    d = DosBackend(seat="arbitrate", arbitrate_fn=fn).evaluate(
        {"dos_tree": ["src/"]})
    assert d.allowed is False
    assert d.action == "deny"
    assert d.error is None
    assert d.reason == "dos:requested tree overlaps live lane 'src'"


def test_arbitrate_falls_back_to_single_path_key():
    seen = {}

    def fn(lane, kind, tree):
        seen.update(lane=lane, kind=kind, tree=tree)
        return LaneDecision("acquire", lane=lane)

    DosBackend(seat="arbitrate", arbitrate_fn=fn).evaluate(
        {"path": "src/dos/oracle.py"})
    assert seen["tree"] == ["src/dos/oracle.py"]
    assert seen["lane"] == "agt"                # the default synthetic lane
    assert seen["kind"] == "keyword"


def test_arbitrate_no_footprint_abstains():
    fn = lambda lane, kind, tree: LaneDecision("acquire", lane=lane)  # noqa: E731
    d = DosBackend(seat="arbitrate", arbitrate_fn=fn).evaluate(
        {"tool_name": "file_read"})
    assert d.error is not None and d.error.startswith("abstain:")


# ---------------------------------------------------------------------------
# Phase 2 — through the real published host package.
# ---------------------------------------------------------------------------


@needs_agt
def test_protocol_conformance_is_structural():
    from agent_os.policies.backends import ExternalPolicyBackend

    assert isinstance(DosBackend(verifier=_shipped), ExternalPolicyBackend)


@needs_agt
def test_decisions_use_the_real_backenddecision_class():
    from agent_os.policies.backends import BackendDecision

    d = DosBackend(verifier=_shipped).evaluate(dict(CLAIM))
    assert isinstance(d, BackendDecision)


@needs_agt
def test_allow_binds_in_real_evaluator_with_evidence_in_audit():
    from agent_os.policies import PolicyEvaluator

    ev = PolicyEvaluator()                       # no YAML rules → backends decide
    ev.add_backend(DosBackend(verifier=_shipped))
    decision = ev.evaluate(dict(CLAIM))
    assert decision.allowed is True
    assert decision.reason.startswith("dos:verified-shipped")
    assert decision.audit_entry["policy"] == "external:dos"
    if _evidence_supported():
        # The evidence pair reaches the audit entry only on host versions whose
        # BackendDecision (and evaluator propagation) carry it — the 4.x line.
        assert decision.audit_entry["proof_artefact"] == "git:abc1234"
        assert decision.audit_entry["verification_pointers"]["phase"] == "P1"


@needs_agt
def test_deny_binds_in_real_evaluator():
    from agent_os.policies import PolicyEvaluator

    ev = PolicyEvaluator()
    ev.add_backend(DosBackend(verifier=_unshipped))
    decision = ev.evaluate(dict(CLAIM))
    assert decision.allowed is False
    assert decision.reason.startswith("dos:unverified-claim")


@needs_agt
def test_abstain_falls_through_to_next_backend_then_default():
    from agent_os.policies import PolicyEvaluator

    ev = PolicyEvaluator()
    ev.add_backend(DosBackend(verifier=_shipped))   # will abstain: no claim keys
    decision = ev.evaluate({"tool_name": "file_read"})
    # dos abstained (error set) → AGT skips it → no backend bound → default allow.
    assert decision.allowed is True
    assert decision.reason == "No rules matched; default action applied"

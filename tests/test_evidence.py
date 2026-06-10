"""Tests for the evidence-source seam (`dos.evidence`) and its acceptance-verb driver.

docs/121 §5 — the throughline slice that makes `verify`'s witness population OPEN: a
witness is a source whose byte-author is not the judged agent, git is one special
case, and now a deployment can wire others (the OS exit code, a provider receipt) by
name. Tested the way the kernel seam family is built (`judges` / `log_source` /
`overlap_policy`):

  * `believe_under_floor()` is PURE and SECURITY-LOAD-BEARING — it is the dual of
    `overlap_policy.admissible_under_floor`. The pins here are the floor discipline:
    a FORGEABLE-floor (`AGENT_AUTHORED`) source's attestation can NEVER, by itself,
    grant belief; only a NON-FORGEABLE (`OS_RECORDED` / `THIRD_PARTY`) attestation
    moves the verdict to believe. The whole open-population safety rests on this.
  * `gather_evidence()` is the fail-safe runner — a source that raises or returns the
    wrong type degrades to NO_SIGNAL, never a fabricated attestation (the `run_judge`
    / `gather_log` posture).
  * the resolver pins built-in-first / unshadowable / loud-on-unknown.
  * the structural one-way-import pin: the kernel never imports the driver.

The `os_acceptance` driver tests poison `subprocess.run` so the suite never spawns,
and pin the exit-status → stance ladder (0→ATTESTED, non-zero→REFUTED,
unrunnable→NO_SIGNAL) plus the end-to-end belief fold (an OS-recorded 0 DOES grant
belief; a forgeable source would not).
"""
from __future__ import annotations

import subprocess

import pytest

from dos.evidence import (
    Accountability,
    BeliefVerdict,
    EvidenceFacts,
    EvidenceStance,
    NullEvidenceSource,
    active_evidence_source_names,
    believe_under_floor,
    derived_witness,
    gather_evidence,
    resolve_evidence_source,
)


# ── helpers ─────────────────────────────────────────────────────────────────
def _attest(name: str, acct: Accountability, subject: str = "e") -> EvidenceFacts:
    return EvidenceFacts.attest(name, acct, subject, detail="x")


def _refute(name: str, acct: Accountability, subject: str = "e") -> EvidenceFacts:
    return EvidenceFacts.refute(name, acct, subject, detail="x")


def _silent(name: str, acct: Accountability, subject: str = "e") -> EvidenceFacts:
    return EvidenceFacts.no_signal(name, acct, subject, detail="x")


# ── the constructors set the fail-safe defaults right ───────────────────────
class TestEvidenceFactsConstructors:
    def test_attest_is_reachable_and_attested(self):
        f = EvidenceFacts.attest("s", Accountability.OS_RECORDED, "e")
        assert f.reachable is True
        assert f.stance is EvidenceStance.ATTESTED
        assert f.is_attesting is True

    def test_refute_is_reachable_and_refuted(self):
        f = EvidenceFacts.refute("s", Accountability.THIRD_PARTY, "e")
        assert f.reachable is True
        assert f.stance is EvidenceStance.REFUTED
        assert f.is_attesting is False

    def test_no_signal_is_unreachable_floor(self):
        f = EvidenceFacts.no_signal("s", Accountability.OS_RECORDED, "e")
        assert f.reachable is False
        assert f.stance is EvidenceStance.NO_SIGNAL
        assert f.is_attesting is False

    def test_default_is_the_fail_safe_zero(self):
        # A bare construction (no constructor) must read as no-signal, never an
        # accidental trusted attestation.
        f = EvidenceFacts(source_name="s", accountability=Accountability.OS_RECORDED)
        assert f.reachable is False
        assert f.stance is EvidenceStance.NO_SIGNAL


# ── the floor discipline — the security-load-bearing core ───────────────────
class TestBelieveUnderFloor:
    def test_os_recorded_attestation_grants_belief(self):
        v = believe_under_floor((_attest("os", Accountability.OS_RECORDED),))
        assert isinstance(v, BeliefVerdict)
        assert v.believe is True
        assert v.refuted is False
        assert v.attesting == ("os",)

    def test_third_party_attestation_grants_belief(self):
        v = believe_under_floor((_attest("cloud", Accountability.THIRD_PARTY),))
        assert v.believe is True

    def test_agent_authored_attestation_NEVER_grants_belief(self):
        # THE load-bearing pin: a forgeable-floor source attesting is recorded but
        # cannot move the verdict to believe. This is what makes the open population
        # safe — a lying paste source is a visible no-op, never a forged SHIPPED.
        v = believe_under_floor((_attest("paste", Accountability.AGENT_AUTHORED),))
        assert v.believe is False
        assert "paste" in v.attesting  # recorded…
        assert "forgeable" in v.reason.lower()  # …but the reason says why it didn't count

    def test_agent_authored_cannot_redden_either(self):
        # The floor cuts both ways: a forgeable source is too weak to REFUTE verify
        # on its own, exactly as it is too weak to greenlight it.
        v = believe_under_floor((_refute("paste", Accountability.AGENT_AUTHORED),))
        assert v.refuted is False
        assert "paste" in v.refuting

    def test_accountable_refutation_reddens(self):
        v = believe_under_floor((_refute("os", Accountability.OS_RECORDED),))
        assert v.refuted is True
        assert v.believe is False
        assert v.refuting == ("os",)

    def test_no_witness_abstains(self):
        v = believe_under_floor((_silent("os", Accountability.OS_RECORDED),))
        assert v.believe is False and v.refuted is False
        assert v.silent == ("os",)

    def test_empty_population_abstains(self):
        v = believe_under_floor(())
        assert v.believe is False and v.refuted is False

    def test_one_accountable_attest_outweighs_many_forgeable_silences(self):
        v = believe_under_floor((
            _silent("paste1", Accountability.AGENT_AUTHORED),
            _attest("os", Accountability.OS_RECORDED),
            _silent("paste2", Accountability.AGENT_AUTHORED),
        ))
        assert v.believe is True
        assert v.attesting == ("os",)

    def test_conflict_when_accountable_witnesses_disagree(self):
        # An accountable attest AND an accountable refute → both flags set; the reason
        # routes to a human. Belief and refutation are independent.
        v = believe_under_floor((
            _attest("os", Accountability.OS_RECORDED),
            _refute("cloud", Accountability.THIRD_PARTY),
        ))
        assert v.believe is True and v.refuted is True
        assert "conflict" in v.reason.lower()

    def test_forgeable_attest_does_not_rescue_accountable_refute(self):
        # A paste source attesting cannot overturn an OS_RECORDED refutation.
        v = believe_under_floor((
            _attest("paste", Accountability.AGENT_AUTHORED),
            _refute("os", Accountability.OS_RECORDED),
        ))
        assert v.believe is False
        assert v.refuted is True


# ── the fail-safe runner ────────────────────────────────────────────────────
class _Raising:
    name = "boom"
    accountability = Accountability.OS_RECORDED

    def gather(self, subject, config):
        raise RuntimeError("kaboom")


class _WrongType:
    name = "wrong"
    accountability = Accountability.THIRD_PARTY

    def gather(self, subject, config):
        return {"reachable": True, "stance": "ATTESTED"}  # a look-alike dict


class _LiesAboutRung:
    # A malformed source whose accountability is not even an Accountability — the
    # runner must default it to the floor, never trust the bogus value.
    name = "liar"
    accountability = "TOTALLY_TRUSTED"  # not an enum member

    def gather(self, subject, config):
        raise RuntimeError("nope")


class TestGatherEvidenceFailSafe:
    def test_raising_source_degrades_to_no_signal(self):
        f = gather_evidence(_Raising(), "e", None)
        assert f.stance is EvidenceStance.NO_SIGNAL
        assert f.reachable is False
        assert "raised" in f.detail

    def test_wrong_return_type_degrades_to_no_signal(self):
        f = gather_evidence(_WrongType(), "e", None)
        assert f.stance is EvidenceStance.NO_SIGNAL
        assert "not" in f.detail.lower()

    def test_malformed_rung_defaults_to_forgeable_floor(self):
        f = gather_evidence(_LiesAboutRung(), "e", None)
        # The bogus accountability string is replaced by the floor — so even via the
        # failure path it cannot escape to a trusted rung and grant belief.
        assert f.accountability is Accountability.AGENT_AUTHORED
        assert believe_under_floor((f,)).believe is False


# ── the built-in + resolver ─────────────────────────────────────────────────
class TestNullAndResolver:
    def test_null_source_witnesses_nothing(self):
        f = NullEvidenceSource().gather("e", None)
        assert f.stance is EvidenceStance.NO_SIGNAL
        assert f.accountability is Accountability.AGENT_AUTHORED  # the floor

    def test_null_resolves_and_is_built_in(self):
        src = resolve_evidence_source("null")
        assert isinstance(src, NullEvidenceSource)

    def test_unknown_name_raises_loud(self):
        with pytest.raises(ValueError) as ei:
            resolve_evidence_source("no_such_source")
        assert "unknown evidence source" in str(ei.value)
        assert "null" in str(ei.value)  # the known list is shown

    def test_active_names_include_null(self):
        assert "null" in active_evidence_source_names()


# ── the os_acceptance driver (subprocess poisoned — never spawns) ───────────
class _FakeProc:
    def __init__(self, returncode):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


class TestOsAcceptanceDriver:
    def _source(self):
        from dos.drivers.os_acceptance import OsAcceptanceEvidenceSource

        return OsAcceptanceEvidenceSource()

    def test_exit_zero_is_attested_and_os_recorded(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(0))
        f = self._source().gather("pytest -q", None)
        assert f.stance is EvidenceStance.ATTESTED
        assert f.accountability is Accountability.OS_RECORDED
        # end-to-end: an OS-recorded 0 DOES grant belief (the population proof).
        assert believe_under_floor((f,)).believe is True

    def test_exit_nonzero_is_refuted(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(1))
        f = self._source().gather("pytest -q", None)
        assert f.stance is EvidenceStance.REFUTED
        assert believe_under_floor((f,)).refuted is True

    def test_missing_binary_is_no_signal(self, monkeypatch):
        def _boom(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr(subprocess, "run", _boom)
        f = self._source().gather("definitely-not-a-real-binary --check", None)
        assert f.stance is EvidenceStance.NO_SIGNAL
        assert "not found" in f.detail

    def test_timeout_is_no_signal(self, monkeypatch):
        def _timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd="x", timeout=1)

        monkeypatch.setattr(subprocess, "run", _timeout)
        f = self._source().gather("sleep 999", None)
        assert f.stance is EvidenceStance.NO_SIGNAL
        assert "timed out" in f.detail

    def test_empty_command_is_no_signal(self):
        f = self._source().gather("   ", None)
        assert f.stance is EvidenceStance.NO_SIGNAL

    def test_unbalanced_quotes_is_no_signal(self):
        f = self._source().gather('echo "unterminated', None)
        assert f.stance is EvidenceStance.NO_SIGNAL

    def test_declared_rung_is_fixed_os_recorded(self):
        # The source cannot lie its way up OR down the spectrum at call time — the rung
        # is a fixed class property, the inversion-law guarantee.
        assert self._source().accountability is Accountability.OS_RECORDED


# ── the derived-witness primitive — the floor discipline lifted to a derivation ──
# (docs/156 §3 — closes the grounded-RAG adoption's one soundness hole: a host that
# brute-forced agent-SELECTED arithmetic onto the THIRD_PARTY rung. The structural
# guarantee: you cannot reach a non-forgeable rung without non-forgeable operands AND
# a declared op AND a matching recomputation.)
class TestDerivedWitness:
    def test_two_non_forgeable_operands_declared_op_match_attests_at_min_rung(self):
        ops = (
            _attest("o1", Accountability.THIRD_PARTY),
            _attest("o2", Accountability.THIRD_PARTY),
        )
        f = derived_witness("derived", "growth_rate", ops, subject="c", within_tol=True)
        assert f.is_attesting is True
        # both THIRD_PARTY → derived fact is THIRD_PARTY (min of equal rungs)
        assert f.accountability is Accountability.THIRD_PARTY
        # and so it can GRANT belief through the floor
        assert believe_under_floor((f,)).believe is True

    def test_min_rung_caps_the_derivation(self):
        # one OS_RECORDED operand + one THIRD_PARTY → the weaker rung caps it
        ops = (
            _attest("o1", Accountability.OS_RECORDED),
            _attest("o2", Accountability.THIRD_PARTY),
        )
        f = derived_witness("d", "ratio", ops, subject="c", within_tol=True)
        assert f.is_attesting is True
        assert f.accountability is Accountability.OS_RECORDED  # min(OS, THIRD) = OS
        # still non-forgeable → still grants belief
        assert believe_under_floor((f,)).believe is True

    def test_agent_authored_operand_cannot_yield_non_forgeable_derivation(self):
        # THE soundness hole, closed: one operand the agent could have authored means
        # the derivation degrades to AGENT_AUTHORED — never a forged THIRD_PARTY.
        ops = (
            _attest("o1", Accountability.THIRD_PARTY),
            _attest("o2", Accountability.AGENT_AUTHORED),
        )
        f = derived_witness("d", "difference", ops, subject="c", within_tol=True)
        assert f.accountability is Accountability.AGENT_AUTHORED
        # and so it CANNOT grant belief — the floor filters it out
        assert believe_under_floor((f,)).believe is False

    def test_undeclared_op_degrades_to_advisory(self):
        # an empty op is a post-hoc fit (the brute-force search the host did) — refused
        # the non-forgeable rung even with two clean operands.
        ops = (
            _attest("o1", Accountability.THIRD_PARTY),
            _attest("o2", Accountability.THIRD_PARTY),
        )
        f = derived_witness("d", "", ops, subject="c", within_tol=True)
        assert f.accountability is Accountability.AGENT_AUTHORED
        assert believe_under_floor((f,)).believe is False

    def test_tolerance_miss_refutes(self):
        ops = (
            _attest("o1", Accountability.THIRD_PARTY),
            _attest("o2", Accountability.THIRD_PARTY),
        )
        f = derived_witness("d", "growth_rate", ops, subject="c", within_tol=False)
        assert f.stance is EvidenceStance.REFUTED
        # a non-forgeable refute reddens the floor
        assert believe_under_floor((f,)).refuted is True

    def test_belief_verdict_operand_counts_when_believed(self):
        # an operand can itself be a BeliefVerdict (already passed the floor) — it
        # counts as non-forgeable iff it believes and is not refuted.
        believed = believe_under_floor((_attest("os", Accountability.OS_RECORDED),))
        assert believed.believe is True
        ops = (believed, _attest("o2", Accountability.THIRD_PARTY))
        f = derived_witness("d", "ratio", ops, subject="c", within_tol=True)
        assert f.is_attesting is True
        assert f.accountability is not Accountability.AGENT_AUTHORED

    def test_unbelieved_verdict_operand_caps_to_advisory(self):
        # a BeliefVerdict that did NOT believe (only a forgeable attest) is not a valid
        # non-forgeable operand — the derivation degrades.
        unbelieved = believe_under_floor((_attest("a", Accountability.AGENT_AUTHORED),))
        assert unbelieved.believe is False
        ops = (unbelieved, _attest("o2", Accountability.THIRD_PARTY))
        f = derived_witness("d", "difference", ops, subject="c", within_tol=True)
        assert f.accountability is Accountability.AGENT_AUTHORED
        assert believe_under_floor((f,)).believe is False

    def test_empty_operands_cannot_attest(self):
        f = derived_witness("d", "growth_rate", (), subject="c", within_tol=True)
        assert f.accountability is Accountability.AGENT_AUTHORED


# ── the structural one-way-import pin (kernel never imports the driver) ──────
class TestOneWayImport:
    def test_evidence_seam_does_not_import_any_driver(self):
        import dos.evidence as ev_mod
        import inspect

        src = inspect.getsource(ev_mod)
        assert "import dos.drivers" not in src
        assert "from dos.drivers" not in src

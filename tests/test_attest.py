"""Tests for the portable signed receipt (`dos.attest`) — docs/246 Phase 1.

`dos_attest` is the NON-PARTICIPANT surface over the shipped `effect_witness` engine:
it wraps a four-valued effect-witness verdict in a portable `Receipt`, signs the
verdict TOGETHER WITH which witness authored the read-back and at what accountability
tier, and emits a record a third party verifies with the shared/public key ALONE —
without access to the agent, the operator, or the original loop. The pins here are:

  * the four-valued verdict (CONFIRMED / REFUTED / UNWITNESSED / NO_CLAIM) round-trips
    through `to_dict`/`from_dict` AND through the canonical serialization unchanged —
    the receipt PACKAGES the engine's verdict, it does not recompute it;
  * the FLOOR is inherited at the receipt layer too: a forgeable-floor read-back
    (AGENT_AUTHORED — the agent re-reading its OWN surface) yields an UNWITNESSED
    receipt, NEVER a CONFIRMED. The receipt cannot mint a belief the engine withheld;
  * UNWITNESSED stays a DISTINCT token from REFUTED (could-not-tell ≠ checked-and-
    absent) — the notary-may-never-overclaim rule (docs/246 §2.3);
  * the SECURITY-LOAD-BEARING signature contract: the canonical bytes commit to EVERY
    field including the witness author + tier + algorithm, so mutating ANY one of them
    (the verdict token, the accountability tier, the claim, the timestamp) makes the
    signature INVALID — loudly, never a silent downgrade (docs/246 §3.2/§5). An
    escalated tier (OS_RECORDED→THIRD_PARTY) is the chain-of-custody attack the signed
    tier defeats;
  * the kernel-imports-no-host / names-no-vendor litmus holds for the module.
"""
from __future__ import annotations

import dataclasses

import pytest

from dos import attest
from dos.attest import Receipt, SignatureAlgorithm, canonical_bytes, receipt_from_verdict
from dos.effect_witness import EffectClaim, witness_effect
from dos.evidence import Accountability, EvidenceFacts

KEY = b"a-shared-secret-signing-key"
TS = "2026-06-08T00:00:00Z"


# --- helpers: build a verdict at each outcome, then a signed receipt -----------

def _verdict(claim_key: str, readbacks):
    return witness_effect(EffectClaim(key=claim_key, narrated="I did the thing"), readbacks)


def _attest(rung: Accountability, key="orders:row:42") -> EvidenceFacts:
    return EvidenceFacts.attest("state_diff", rung, key, detail="present")


def _refute(rung: Accountability, key="orders:row:42") -> EvidenceFacts:
    return EvidenceFacts.refute("state_diff", rung, key, detail="absent")


def _signed(verdict, *, surface="before→after", key=KEY) -> Receipt:
    r = receipt_from_verdict(verdict, timestamp=TS, witness_surface=surface)
    return r.with_signature(attest.sign_hmac(r, key))


# --- the receipt carries the engine's verdict, untouched ----------------------

def test_confirmed_receipt_carries_verdict_and_tier():
    v = _verdict("orders:row:42", [_attest(Accountability.OS_RECORDED)])
    r = _signed(v)
    assert r.verdict == "CONFIRMED"
    assert r.believe is True
    assert r.refuted is False
    assert r.accountability_tier is Accountability.OS_RECORDED
    assert r.witness_author == "state_diff"
    assert r.claim == "orders:row:42"
    assert r.algorithm is SignatureAlgorithm.HMAC_SHA256
    assert r.signature  # signed


def test_refuted_is_the_load_bearing_adverse_receipt():
    """REFUTED is the load-bearing certificate — a narrated success the world denies,
    made portable. It must be as easy to mint as CONFIRMED (docs/246 §2.2)."""
    v = _verdict("orders:row:42", [_refute(Accountability.OS_RECORDED)])
    r = _signed(v)
    assert r.verdict == "REFUTED"
    assert r.refuted is True
    assert r.believe is False
    # and it verifies VALID — an adverse finding is a real, checkable certificate.
    assert attest.verify_hmac(r, KEY).valid is True


# --- the FLOOR, inherited at the receipt layer --------------------------------

def test_forgeable_floor_readback_yields_unwitnessed_receipt_not_confirmed():
    """The agent re-reading its OWN surface (AGENT_AUTHORED) attesting 'present' is
    structurally incapable of CONFIRMED — the receipt inherits the engine's floor
    (docs/246 §1.2). The notary cannot be one of the signers."""
    v = _verdict("orders:row:42", [_attest(Accountability.AGENT_AUTHORED)])
    r = _signed(v)
    assert r.verdict == "UNWITNESSED"
    assert r.believe is False
    # no accountable witness stood behind it → no tier
    assert r.accountability_tier is None


def test_unwitnessed_is_distinct_from_refuted():
    """could-not-tell (UNWITNESSED) must NOT collapse into checked-and-absent
    (REFUTED) — the notary-may-never-overclaim rule (docs/246 §2.3). No read-back at
    all is UNWITNESSED; an accountable ABSENT read-back is REFUTED."""
    unwit = _signed(_verdict("e", []))
    refuted = _signed(_verdict("e", [_refute(Accountability.OS_RECORDED, key="e")]))
    assert unwit.verdict == "UNWITNESSED"
    assert refuted.verdict == "REFUTED"
    assert unwit.verdict != refuted.verdict


def test_no_claim_receipt():
    """An empty claim is NO_CLAIM (nothing to witness) — not a pass, a distinct token."""
    v = witness_effect(None, [])
    r = _signed(v)
    assert r.verdict == "NO_CLAIM"
    assert r.believe is False


# --- round-trip: to_dict / from_dict / canonical bytes ------------------------

@pytest.mark.parametrize("rung", [Accountability.OS_RECORDED, Accountability.THIRD_PARTY])
def test_confirmed_roundtrips_through_dict(rung):
    r = _signed(_verdict("orders:row:42", [_attest(rung)]))
    back = Receipt.from_dict(r.to_dict())
    assert back == r
    assert back.canonical_bytes() == r.canonical_bytes()
    assert back.accountability_tier is rung


@pytest.mark.parametrize("readbacks,expected", [
    ([_attest(Accountability.OS_RECORDED)], "CONFIRMED"),
    ([_refute(Accountability.OS_RECORDED)], "REFUTED"),
    ([_attest(Accountability.AGENT_AUTHORED)], "UNWITNESSED"),
    ([], "UNWITNESSED"),
])
def test_every_verdict_roundtrips(readbacks, expected):
    r = _signed(_verdict("orders:row:42", readbacks))
    assert r.verdict == expected
    back = Receipt.from_dict(r.to_dict())
    assert back.verdict == expected
    assert back == r


def test_no_claim_roundtrips():
    r = _signed(witness_effect(None, []))
    assert Receipt.from_dict(r.to_dict()) == r


# --- the signature contract: sign -> mutate one field -> verify FAILS ---------

def test_valid_signature_verifies():
    r = _signed(_verdict("orders:row:42", [_attest(Accountability.OS_RECORDED)]))
    assert attest.verify_hmac(r, KEY).valid is True


def test_wrong_key_is_invalid():
    r = _signed(_verdict("orders:row:42", [_attest(Accountability.OS_RECORDED)]))
    assert attest.verify_hmac(r, b"the-wrong-key").valid is False


@pytest.mark.parametrize("field,mutate", [
    ("verdict", "REFUTED"),
    ("claim", "orders:row:99"),
    ("narrated", "a different story"),
    ("witness_surface", "some-other-surface"),
    ("witness_author", "impostor"),
    ("timestamp", "1999-01-01T00:00:00Z"),
    # the base verdict is CONFIRMED (believe=True, refuted=False), so each bool is
    # mutated to its OPPOSITE — a real change, not a no-op (a same-value "mutation"
    # would leave the signature valid and prove nothing).
    ("believe", False),
    ("refuted", True),
])
def test_tampering_any_signed_field_invalidates(field, mutate):
    """The canonical bytes commit to every field, so mutating ANY one breaks the
    signature — the sign→mutate→verify-must-fail round-trip (docs/246 §3.2). This is
    the one place a serialization bug would be a SECURITY bug, so it is pinned."""
    r = _signed(_verdict("orders:row:42", [_attest(Accountability.OS_RECORDED)]))
    assert getattr(r, field) != mutate, "test bug: mutation must differ from the original"
    tampered = dataclasses.replace(r, **{field: mutate})  # keep the original signature
    assert attest.verify_hmac(tampered, KEY).valid is False


def test_tampering_the_tier_invalidates():
    """The chain-of-custody attack: an attacker escalates the witnessed tier
    OS_RECORDED→THIRD_PARTY to make the certificate read stronger. Because the tier is
    SIGNED INTO the payload (docs/246 §2.1), that mutation breaks the signature."""
    r = _signed(_verdict("orders:row:42", [_attest(Accountability.OS_RECORDED)]))
    escalated = dataclasses.replace(r, accountability_tier=Accountability.THIRD_PARTY)
    assert attest.verify_hmac(escalated, KEY).valid is False


def test_unsigned_receipt_is_invalid():
    """A receipt with no signature is the pure payload, not a certificate — verifying
    it is INVALID (you cannot trust an unsigned stamp)."""
    r = receipt_from_verdict(
        _verdict("orders:row:42", [_attest(Accountability.OS_RECORDED)]), timestamp=TS)
    assert r.signature == ""
    assert attest.verify_hmac(r, KEY).valid is False


def test_algorithm_is_signed_into_the_payload():
    """The algorithm token is part of the canonical bytes, so a verifier cannot be
    fooled into checking an Ed25519-labelled receipt with the HMAC verifier — the
    HMAC verifier refuses an algorithm it is not (docs/246 §3.1)."""
    r = _signed(_verdict("orders:row:42", [_attest(Accountability.OS_RECORDED)]))
    relabelled = dataclasses.replace(r, algorithm=SignatureAlgorithm.ED25519)
    res = attest.verify_hmac(relabelled, KEY)
    assert res.valid is False
    assert "HMAC verifier" in res.reason


def test_canonical_bytes_are_deterministic_and_exclude_signature():
    """The canonical serialization is stable (no insertion-order / whitespace
    variance) and does NOT include the signature (you cannot sign your own
    signature)."""
    v = _verdict("orders:row:42", [_attest(Accountability.OS_RECORDED)])
    r1 = receipt_from_verdict(v, timestamp=TS, witness_surface="s")
    r2 = receipt_from_verdict(v, timestamp=TS, witness_surface="s")
    assert canonical_bytes(r1) == canonical_bytes(r2)
    # signing one of them does NOT change its canonical bytes
    signed = r1.with_signature(attest.sign_hmac(r1, KEY))
    assert canonical_bytes(signed) == canonical_bytes(r1)
    assert b"signature" not in canonical_bytes(signed)


def test_bools_render_as_json_literals_in_canonical_bytes():
    """A non-Python verifier reconstructs the canonical bytes, so bools must be the
    lowercase JSON literals `true`/`false`, never Python's `True`/`False` repr."""
    r = _signed(_verdict("orders:row:42", [_attest(Accountability.OS_RECORDED)]))
    raw = canonical_bytes(r).decode("utf-8")
    assert "believe=true" in raw
    assert "refuted=false" in raw
    assert "True" not in raw and "False" not in raw


def test_from_dict_rejects_unknown_algorithm():
    """A verifier handed a receipt naming an algorithm it does not know must fail
    LOUD (a ValueError), never silently default — it must not pretend to have checked
    an algorithm it doesn't understand."""
    d = _signed(_verdict("orders:row:42", [_attest(Accountability.OS_RECORDED)])).to_dict()
    d["algorithm"] = "MAGIC-SIGN-9000"
    with pytest.raises(ValueError):
        Receipt.from_dict(d)


# --- the kernel-layer litmus: the module names no host, no vendor -------------

def test_module_names_no_host_or_vendor_in_code():
    """`dos.attest` is a KERNEL module (docs/246 §4): the receipt mechanism is
    generic, every host specific is a caller/config input. So it names no host
    directory / lane / commit prefix and no vendor as a code identifier — the same
    `kernel imports no host` / `names no vendor` litmus the rest of the kernel holds."""
    import ast
    import inspect

    src = inspect.getsource(attest)
    tree = ast.parse(src)
    ids: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            ids.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            ids.add(node.attr.lower())
    forbidden = {"job", "apply", "tailor", "claude", "gemini", "codex", "openai",
                 "anthropic", "gpt"}
    leaked = {tok for tok in forbidden if tok in ids}
    assert not leaked, f"dos.attest names a host/vendor in code: {leaked}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

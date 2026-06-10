"""attest — the portable, signed receipt over an effect-witness verdict (docs/246).

The missing **non-participant** surface over the already-shipped `effect_witness`
engine. `effect_witness.witness_effect(claim, readbacks)` already does the hard,
soundness-load-bearing part — it joins two independently-authored facts (the agent's
forgeable claim + an independent, accountable read-back of world state) and returns a
four-valued verdict whose trust is *capped by the read-back's accountability*. But it
returns that verdict **to the caller** — to the loop, or to an operator running the
witness drivers over their own fleet. Every surface that consumes it today presumes
the caller is the agent or its operator: a party *inside* the loop.

This module mints the surface for the party who was **not present** — an auditor at
quarter-end, an inspector general, a counterparty in an agent-to-agent transaction, an
allied partner verifying a shared system. It wraps the verdict in a portable
**`Receipt`**, signs the verdict *together with which witness authored the read-back
and at what accountability tier*, and emits a record a skeptic verifies with the
public/shared half of the signing key **alone** — without access to the agent, the
operator, or the original loop. The DocuSign step (a private check → a record a
non-participant can verify) applied to the kernel's existing notary engine.

The economy: this writes NO new decision logic
===============================================

Identical in spirit to docs/126 §2 (*"the same verdicts, made binding — not new
policy"*): the verdict the receipt carries is `witness_effect`'s, untouched. Three
facts make the receipt a packaging layer, not a subsystem:

  1. The verdict already exists, four-valued and frozen — an `EffectWitnessVerdict`
     with exactly the fields a certificate needs (`verdict`, `believe`, `refuted`,
     `claim_key`, `narrated`, `witness`, `accountability`). The receipt is that data,
     plus a timestamp and a signature.
  2. The floor discipline is already structural and lives in ONE place
     (`evidence.believe_under_floor`, which `witness_effect` delegates to). A receipt
     signed over a forgeable-floor read-back is, by construction, an `UNWITNESSED`
     (never a `CONFIRMED`). The notary cannot be one of the signers, and that is
     enforced *upstream of the signature*, not by it — so this module never re-asserts
     it; it inherits it by carrying the verdict the engine already gated.
  3. The read-back authors already ship as drivers (`os_acceptance` → the OS authors
     the exit code; `state_diff` → the store authors the delta). This module does not
     invent a witness; it *records the witness's name and tier into the signed
     payload* so a third party sees the rung the verdict rests on.

What the receipt is — and is NOT (the honest scope, docs/246 §2/§3.3)
=====================================================================

A `Receipt` is a notarized statement of *presence at an accountability tier and a
time* — exactly the scope a notary has always had (*this party signed this document on
this date*; it says nothing about whether the deal was good). It is the Wall §3
ceiling (docs/204), inherited unchanged from the engine: `witness_effect` verifies
**claim ⊆ witnessed-delta** (was the specific change the agent took credit for actually
made?), NOT *"is the end-state globally correct / wise / intended?"*. Correctness-of-
intent routes where it always has: ORACLE → JUDGE → HUMAN (docs/86). And a receipt
mints **evidentiary** weight (a tamper-evident, independently-authored record), not
**legal** weight — the honest starting position DocuSign itself started from.

Three load-bearing constraints on the Receipt shape:

  * **The signed payload includes the witness's author and tier, not just the verdict
    token.** A bare signed `CONFIRMED` tells a skeptic nothing about *what was checked*.
    The receipt signs `witness_author` and `accountability_tier` INTO the payload so the
    verdict is read together with the rung it stands on — the chain-of-custody field.
  * **`REFUTED` is the load-bearing receipt** — the adverse certificate: a confidently-
    narrated success the world does not corroborate, made portable. The receipt a
    dispute / audit / after-action review turns on. It must be as easy to mint and as
    cryptographically solid as `CONFIRMED`.
  * **`UNWITNESSED` must stay LOUD and distinct from `REFUTED`** — the single most
    important honesty rule. `UNWITNESSED` = *could-not-tell*; `REFUTED` = *checked-and-
    absent*. Collapsing them would let a notary that merely failed to reach a witness
    emit a false adverse finding. They stay separate verdict tokens.

The ONE place that fails LOUD
=============================

Every other DOS verdict degrades *quietly* toward abstain (fail-safe, never fail-open).
The **signature path is the one place that must fail LOUD**: an invalid signature, a
tampered field, or a canonical-serialization mismatch makes the receipt **invalid**,
surfaced as such — never downgraded to "unsigned but probably fine," never silently
accepted. A notary whose stamp is forgeable-without-detection is not a notary.

Purity & layering
=================

Pure stdlib — a frozen `Receipt` value type, the canonical serialization (the one
place a serialization bug would be a security bug, so it is pinned, not left to a
library default), and the HMAC sign/verify (`hmac` + `hashlib`, already in the kernel's
dependency set — `hashlib.sha256` is used in `home.py`/`posttool_sensor.py`/`rewind.py`
today, so this adds NO new dependency and keeps the PyYAML-only core intact). It names
no host and no vendor in code. The *which-algorithm* is policy chosen at the boundary
(the `--sign` flag); the *what-is-signed* (the canonical Receipt payload) is fixed
mechanism here. The asymmetric (public-key) signer is Phase 2, behind the `[attest]`
extra — it arrives as a by-name `Signer` the boundary resolves, the same kernel/driver
split as `judges`/`overlap_policy`, so the kernel core stays dependency-free. The
read-back is gathered at the CLI boundary (`evidence.gather_evidence` over a witness
driver); this module only PACKAGES an already-computed verdict + SIGNS it.
"""

from __future__ import annotations

import enum
import hashlib
import hmac
from dataclasses import dataclass

from dos.effect_witness import EffectWitnessVerdict
from dos.evidence import Accountability

__all__ = [
    "Receipt",
    "SignatureAlgorithm",
    "canonical_bytes",
    "sign_hmac",
    "verify_hmac",
    "receipt_from_verdict",
    "VerifyResult",
    "ATTEST_KEY_ENV",
]

# The env var the HMAC key is read from when no --key-file is given. Named here (not a
# bare literal at the CLI) so the module and the CLI read the SAME name.
ATTEST_KEY_ENV = "DOS_ATTEST_KEY"


class SignatureAlgorithm(str, enum.Enum):
    """Which signing primitive minted/checks a receipt's signature.

    A DATA field on the receipt, carried INTO the canonical payload (so the algorithm
    is itself signed — a verifier cannot be fooled into checking an Ed25519 receipt as
    if it were HMAC, or vice-versa; the alg is part of what the signature commits to).
    `str`-valued so it round-trips through a CLI token / JSON without a lookup table
    (the `Accountability` / `EffectStance` idiom).

      HMAC_SHA256 — shared-secret. Cheap, stdlib-only, NO new dependency. The right
                    tool when the verifier SHARES a secret with the issuer (an internal
                    auditor, a same-org oversight function, a CI gate). Its hard limit:
                    anyone who can VERIFY an HMAC receipt can also FORGE one (the secret
                    is symmetric), so it cannot serve the non-participant notary case.
                    Phase 1 (docs/246 §3.1).
      ED25519     — asymmetric/public-key. For a third party who does NOT share a
                    secret (the counterparty, the regulator, the allied partner):
                    verification uses the PUBLIC half while only the issuer holds the
                    private half — the DocuSign property (verify, cannot forge). Needs a
                    signing primitive the near-stdlib kernel lacks (`cryptography`), so
                    it arrives behind the `[attest]` extra. Phase 2 — the token is
                    reserved here so a Phase-1 receipt's `algorithm` field is already
                    drawn from the closed set the Phase-2 verifier will dispatch on.
    """

    HMAC_SHA256 = "HMAC-SHA256"
    ED25519 = "ED25519"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# The field order the canonical serialization commits to. FIXED and explicit (not the
# dataclass field order, not a dict's insertion order, not sorted-at-write) so the
# issuer and a verifier reconstruct byte-identical input independent of language /
# library / dataclass evolution. Adding a field here is a signature-contract change
# (old receipts would no longer round-trip) — deliberate, never incidental.
_CANONICAL_FIELDS: tuple[str, ...] = (
    "schema",
    "claim",
    "narrated",
    "witness_surface",
    "witness_author",
    "accountability_tier",
    "verdict",
    "believe",
    "refuted",
    "timestamp",
    "algorithm",
)

# The receipt schema tag — versioned so a future field addition is a NEW schema a
# verifier can branch on, never a silent reinterpretation of v1 bytes.
_SCHEMA = "dos.attest/receipt@1"


@dataclass(frozen=True)
class Receipt:
    """A portable, signed certificate over one effect-witness verdict (docs/246 §2).

    Every field is either echoed from the `EffectWitnessVerdict` or added by the act of
    signing. It is verifiable by a third party holding the public/shared half of the
    signing key, WITHOUT access to the agent, the operator, or the original loop.

      claim               — the opaque effect key the agent asserted (`EffectClaim.key`)
      narrated            — the agent's original phrasing — SHOWN, never parsed for truth
      witness_surface     — the read-back subject (the command run / the state-key probed)
      witness_author      — the witness `source_name` (e.g. "os_acceptance", "state_diff")
      accountability_tier — the read-back's rung: OS_RECORDED / THIRD_PARTY /
                            AGENT_AUTHORED. The chain-of-custody field — *who/what
                            witnessed this, provably*. `None` only for NO_CLAIM /
                            UNWITNESSED, where no accountable witness stood behind a
                            verdict; serialized as the empty string so the canonical
                            bytes are still well-defined.
      verdict             — CONFIRMED | REFUTED | UNWITNESSED | NO_CLAIM
      believe             — the positive bit, True ONLY on CONFIRMED (echoed so a
                            verifier need not re-derive it from the token)
      refuted             — surfaced separately so a consumer may red-flag the adverse
                            certificate even though `believe` is also False
      timestamp           — when the attestation was minted (RFC 3339 / ISO-8601 UTC).
                            Supplied by the CALLER (the clock is boundary I/O — this
                            module is pure and never reads the wall clock itself).
      algorithm           — which `SignatureAlgorithm` minted `signature`
      signature           — hex over the canonical serialization of ALL the above
                            (the `_CANONICAL_FIELDS`, which INCLUDES `algorithm` and the
                            schema tag — so the alg and version are themselves signed).
                            Empty string on an UNSIGNED receipt (the pure payload before
                            the one boundary signing step).

    The `verdict` / `believe` / `refuted` / `accountability_tier` are NOT recomputed
    here — they are the engine's, carried verbatim. The floor discipline that makes
    `believe=True ⟹ a non-forgeable witness attested` is enforced UPSTREAM, in
    `witness_effect` / `believe_under_floor`; a receipt cannot manufacture a CONFIRMED
    the engine did not grant, because it only ever copies the engine's fields.
    """

    claim: str
    narrated: str
    witness_surface: str
    witness_author: str
    accountability_tier: Accountability | None
    verdict: str
    believe: bool
    refuted: bool
    timestamp: str
    algorithm: SignatureAlgorithm = SignatureAlgorithm.HMAC_SHA256
    signature: str = ""
    schema: str = _SCHEMA

    # -- the canonical, signature-committed view -----------------------------
    def _canonical_view(self) -> dict[str, object]:
        """The exact, ordered field→value mapping the signature commits to.

        Deliberately EXCLUDES `signature` itself (you cannot sign your own signature)
        and normalizes the two non-string fields the canonical bytes must pin: the
        accountability tier (its `.value`, or "" when absent) and the algorithm (its
        `.value`). Bools are emitted as the lowercase JSON literals `true`/`false` in
        `canonical_bytes`, never Python's `True`/`False` repr."""
        return {
            "schema": self.schema,
            "claim": self.claim,
            "narrated": self.narrated,
            "witness_surface": self.witness_surface,
            "witness_author": self.witness_author,
            "accountability_tier": (
                self.accountability_tier.value if self.accountability_tier else ""
            ),
            "verdict": self.verdict,
            "believe": self.believe,
            "refuted": self.refuted,
            "timestamp": self.timestamp,
            "algorithm": self.algorithm.value,
        }

    def canonical_bytes(self) -> bytes:
        """The bytes the signature is computed over — see `canonical_bytes`."""
        return canonical_bytes(self)

    # -- serialization for the wire / operator surface -----------------------
    def to_dict(self) -> dict:
        """The full JSON shape, INCLUDING the signature, for `--json` / MCP / a file.

        This is the receipt as a third party receives it. `from_dict` reconstructs an
        identical `Receipt` (and therefore identical `canonical_bytes`) from it — the
        round-trip the verify path depends on.
        """
        d = dict(self._canonical_view())
        d["signature"] = self.signature
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Receipt":
        """Reconstruct a `Receipt` from its `to_dict()` form (or a hand-written one).

        Tolerant of the tier/algorithm being given as their string tokens (the wire
        form) — it maps them back to the enums. An empty/missing `accountability_tier`
        becomes `None`. An unknown algorithm/tier token raises (loud, never a silent
        default): a verifier handed a receipt naming an algorithm it does not know must
        not pretend to have checked it.
        """
        tier_tok = (d.get("accountability_tier") or "").strip()
        tier = Accountability(tier_tok) if tier_tok else None
        alg_tok = d.get("algorithm") or SignatureAlgorithm.HMAC_SHA256.value
        algorithm = SignatureAlgorithm(alg_tok)
        return cls(
            claim=d.get("claim", ""),
            narrated=d.get("narrated", ""),
            witness_surface=d.get("witness_surface", ""),
            witness_author=d.get("witness_author", ""),
            accountability_tier=tier,
            verdict=d.get("verdict", ""),
            believe=bool(d.get("believe", False)),
            refuted=bool(d.get("refuted", False)),
            timestamp=d.get("timestamp", ""),
            algorithm=algorithm,
            signature=d.get("signature", ""),
            schema=d.get("schema", _SCHEMA),
        )

    def with_signature(self, signature: str) -> "Receipt":
        """A copy carrying `signature` — the one mutation, applied at the boundary
        signing step (the dataclass is frozen, so this returns a new instance)."""
        return Receipt(
            claim=self.claim,
            narrated=self.narrated,
            witness_surface=self.witness_surface,
            witness_author=self.witness_author,
            accountability_tier=self.accountability_tier,
            verdict=self.verdict,
            believe=self.believe,
            refuted=self.refuted,
            timestamp=self.timestamp,
            algorithm=self.algorithm,
            signature=signature,
            schema=self.schema,
        )


def canonical_bytes(receipt: Receipt) -> bytes:
    """The canonical serialization the signature is computed/checked over (docs/246 §3.2).

    A signature is only checkable if the issuer and the verifier serialize the payload
    BYTE-IDENTICALLY. A naive `json.dumps` is NOT canonical (key order, whitespace,
    unicode escaping, and the bool/null spelling all vary across libraries and
    languages). So this fixes the form once and signs over THAT:

      * an explicit, FIXED field order (`_CANONICAL_FIELDS`) — never the dataclass
        order, never a dict's insertion order, never sorted-at-write;
      * each field rendered as ``key=value`` on its own line, the lines joined by ``\\n``;
      * values are the raw UTF-8 text (the tier/algorithm already reduced to their
        tokens, bools to the lowercase literals `true`/`false`); a missing value is the
        empty string;
      * the whole encoded UTF-8, with NO insignificant whitespace.

    `signature` is excluded (you cannot sign the signature) but the schema tag and the
    `algorithm` ARE included — so the version and the signing primitive are themselves
    committed to. A verifier reconstructs these exact bytes from the receipt's fields
    and checks the signature against them; a receipt whose canonical re-serialization
    does not match its signature is INVALID, loudly (never silently downgraded). This
    is line-oriented and `=`-delimited on purpose: the keys are a fixed closed set with
    no `=`/newline in them, so the encoding is unambiguous without a JSON parser, and a
    non-Python verifier can reproduce it trivially.

    PURE — no I/O, no clock, no randomness.
    """
    view = receipt._canonical_view()
    lines: list[str] = []
    for key in _CANONICAL_FIELDS:
        value = view[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        lines.append(f"{key}={rendered}")
    return "\n".join(lines).encode("utf-8")


def sign_hmac(receipt: Receipt, key: bytes) -> str:
    """Sign a receipt's canonical bytes with HMAC-SHA256, returning the hex digest.

    The Phase-1 signer: stdlib `hmac` + `hashlib.sha256`, NO new dependency. The
    receipt's `algorithm` must be `HMAC_SHA256` (it is, by default) — the alg is part of
    the canonical bytes, so signing commits to it. Returns the hex MAC; the caller wraps
    it back in with `receipt.with_signature(...)`.

    PURE given the key (the key was read at the boundary from `--key-file`/`$DOS_ATTEST_KEY`).
    """
    mac = hmac.new(key, canonical_bytes(receipt), hashlib.sha256)
    return mac.hexdigest()


def verify_hmac(receipt: Receipt, key: bytes) -> "VerifyResult":
    """Check an HMAC receipt's signature against its canonical bytes (constant-time).

    The one place that must fail LOUD (docs/246 §5): a signature that does not match the
    re-derived canonical bytes (a tampered field, a wrong key, a forged stamp) yields an
    INVALID result — never a silent downgrade to "unsigned but probably fine." Uses
    `hmac.compare_digest` so the check is constant-time (a non-constant-time `==` on a
    MAC leaks a timing side-channel a forger can walk).

    Returns a `VerifyResult` (valid + reason); the caller maps it to an exit code /
    a rendered line. PURE given the key.
    """
    if receipt.algorithm is not SignatureAlgorithm.HMAC_SHA256:
        return VerifyResult(
            valid=False,
            reason=(
                f"INVALID — receipt names algorithm {receipt.algorithm.value!r}, but "
                f"this is the HMAC verifier; verify it with the matching algorithm"
            ),
        )
    if not receipt.signature:
        return VerifyResult(
            valid=False,
            reason="INVALID — receipt carries no signature (unsigned payload, not a certificate)",
        )
    expected = sign_hmac(receipt, key)
    # compare_digest over the hex strings — constant-time, and equal length for a
    # well-formed pair (a malformed signature simply fails to match, never raises).
    if hmac.compare_digest(expected, receipt.signature):
        return VerifyResult(
            valid=True,
            reason=(
                f"VALID — HMAC signature matches the canonical payload "
                f"(verdict {receipt.verdict}, tier "
                f"{receipt.accountability_tier.value if receipt.accountability_tier else '-'})"
            ),
        )
    return VerifyResult(
        valid=False,
        reason=(
            "INVALID — HMAC signature does NOT match the canonical payload: a field was "
            "tampered, the wrong key was used, or the signature was forged"
        ),
    )


@dataclass(frozen=True)
class VerifyResult:
    """The result of checking a receipt's signature — valid + a legible reason.

    `valid` is the binary judgment a verifier acts on; `reason` is the one-line
    legible-distrust string (rendered to the operator / `--json`). Deliberately tiny:
    signature verification answers one question (does the stamp hold?), distinct from
    the verdict the receipt CARRIES (CONFIRMED/REFUTED/…). A VALID receipt still has a
    verdict the verifier reads; an INVALID one is not to be trusted at all.
    """

    valid: bool
    reason: str

    def to_dict(self) -> dict:
        return {"valid": self.valid, "reason": self.reason}


def receipt_from_verdict(
    verdict: EffectWitnessVerdict,
    *,
    timestamp: str,
    witness_surface: str = "",
    algorithm: SignatureAlgorithm = SignatureAlgorithm.HMAC_SHA256,
) -> Receipt:
    """Build the UNSIGNED `Receipt` for an already-computed effect-witness verdict.

    The packaging step, pure: it copies the verdict's fields into the receipt shape and
    stamps the caller-supplied `timestamp` (the clock is boundary I/O — this module
    never reads the wall clock). `witness_surface` is the read-back subject (the command
    run / the state-key probed); it is carried for the operator surface and defaults to
    the verdict's `claim_key` when the caller does not distinguish them. The result has
    an EMPTY signature — the one boundary signing step (`sign_hmac` + `with_signature`)
    happens at the CLI, where the key lives.

    The verdict's four-valued token, its `believe`/`refuted` bits, and its witness +
    accountability tier are carried VERBATIM — so a receipt can never assert a CONFIRMED
    the engine did not grant, nor collapse UNWITNESSED into REFUTED (they remain the
    distinct tokens `witness_effect` produced; docs/246 §2.3).
    """
    return Receipt(
        claim=verdict.claim_key,
        narrated=verdict.narrated,
        witness_surface=witness_surface or verdict.claim_key,
        witness_author=verdict.witness,
        accountability_tier=verdict.accountability,
        verdict=verdict.verdict.value,
        believe=verdict.believe,
        refuted=verdict.refuted,
        timestamp=timestamp,
        algorithm=algorithm,
        signature="",
    )

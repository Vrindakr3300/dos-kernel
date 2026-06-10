"""The evidence-source seam — Axis 8 of hackability: a pluggable witness population.

docs/121 §5 — the throughline slice. `verify()` answers "did this effect actually
happen?" and today it reads exactly one witness: **git** (existence + ancestry +
ship-stamp grammar, via `dos.oracle`/`dos.git_delta`). docs/121 §2.1 is blunt that
this is the kernel having shipped the witness for *one* class of effect — a commit —
and being blind to every other: an email sent, a webhook delivered, a payment made,
a migration run, a deploy shipped. For each of those the witness is not git; it is
**the counterparty that received the effect** — the recipient's record, the
provider's sent-log, the bank's ledger, the OS exit code of a kernel-launched
command. Git is the witness in exactly one row of that table.

This module is the **pure seam** a witness plugs into, so that population becomes
open: `verify` stops being git-only and starts being "ask whichever witness is
accountable for *this* effect." It is field-for-field the apparatus `judges` (the
JUDGE rung), `overlap_policy` (the disjointness scorer), and `log_source` (the
log-adapter spectrum) already proved — a Protocol, frozen value types, an
unshadowable built-in baseline, a by-name resolver over an entry-point group, and a
fail-safe runner — fused with the **floor discipline** `overlap_policy` made
structural. Every *witnessing* source with real I/O surface (run a command and read
the exit code, call a provider's API, read a TEE attestation) lives in a `drivers/*`
module — it imports the kernel; the kernel never imports it (the `drivers/__init__`
rule). The kernel ships only the abstraction + the honest floor.

The one idea that makes this *verification* and not a fact-aggregation library
================================================================================

An `EvidenceSource` is **a witness whose byte-author is not the judged agent**
(docs/121 §2.1). `git` is the special case where the witness is a VCS and the effect
is a commit. So every source declares its **`accountability`** — who authored the
bytes — as DATA, reusing the docs/117 spectrum (`AGENT_AUTHORED` / `OS_RECORDED` /
`THIRD_PARTY`). That tag is the *ceiling* on how much a consumer may trust the
source, fixed by the source, never inferred from content.

The floor discipline — `believe ⟺ a non-forgeable source attests` (load-bearing)
==============================================================================

This is the security-load-bearing core, the dual of `overlap_policy`'s
`admissible_under_floor`. An evidence verdict (`believe` / `abstain`) is *positive*
— it can upgrade `verify` toward SHIPPED — so, exactly as a policy that *includes
admit* needs a floor ANDed under it, a witness population that *includes belief*
needs a floor ORed-only-from-the-non-forgeable-side:

  > A swapped evidence source may add *more* abstention or contribute a *stronger*
  > attestation. It may never let `verify` BELIEVE an effect that no non-forgeable
  > source attests.

`believe_under_floor` computes this structurally: belief is granted **only** when at
least one source whose `accountability` is non-forgeable (`OS_RECORDED` /
`THIRD_PARTY`) reached the effect and attested it. A source on the **forgeable
floor** (`AGENT_AUTHORED` — a pasted receipt, the agent's own stdout, an mtime) is
*structurally incapable* of being the attesting source: its attestation is recorded
and shown, but it can never, by itself, move the verdict from abstain to believe.
This is what makes an *open* evidence-source set safe — the judge seam's
fail-to-ABSTAIN and the overlap seam's conjunctive-floor, re-aimed at belief: the
worst a buggy/hostile/lying source can do is *withhold* an attestation it should
have given (a visible, safe-direction loss — `verify` falls back to a weaker
witness), never *manufacture* a belief the agent could forge.

Purity & layering
=================

Pure stdlib — an enum (re-exported from `log_source` so the spectrum has one home),
two frozen value types, a built-in source that always abstains, a fail-safe runner,
a resolver, and the floor helper. NO provider surface, no I/O inside a verdict, names
no host. It sits in the kernel layer beside `judges`/`overlap_policy`/`log_source`.
Entry-point discovery (the one bit of I/O) happens at the call boundary in
`active_evidence_sources`, exactly as `active_judges` / `active_log_sources` do.
"""

from __future__ import annotations

import enum
import sys
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# The accountability spectrum has ONE home — docs/117's `log_source`. An evidence
# source sits on the same who-authored-the-byte axis as a log source (a log IS a
# kind of evidence), so we reuse the enum verbatim rather than fork a parallel one.
# Re-exported here so a consumer can `from dos.evidence import Accountability`
# without reaching across to the log seam.
from dos.log_source import Accountability

__all__ = [
    "Accountability",
    "EvidenceStance",
    "EvidenceFacts",
    "EvidenceSource",
    "NullEvidenceSource",
    "gather_evidence",
    "believe_under_floor",
    "derived_witness",
    "EVIDENCE_SOURCE_ENTRY_POINT_GROUP",
    "resolve_evidence_source",
    "active_evidence_sources",
    "active_evidence_source_names",
]


class EvidenceStance(str, enum.Enum):
    """What a gathered `EvidenceFacts` says about the effect it was asked to witness.

    Three-valued on purpose — the same honest split the typed-verdict family makes
    (a behavioral oracle's GREEN/RED/PENDING/NO_SIGNAL collapses to belief /
    refutation / no-answer): a binary attest/silent would have to *lie* about the case
    where the witness was reached and saw the effect did NOT happen (a refutation is
    not the same as "no signal"). `str`-valued so it round-trips through a CLI token /
    JSON without a lookup table (the `Liveness` / `Accountability` idiom).

      ATTESTED — the source was reached and witnessed the effect (the recipient has
                 the email; the exit code was 0; the ledger shows the payment). A
                 push toward belief — but ONLY counts toward `verify`'s belief if the
                 source's `accountability` is non-forgeable (the floor discipline).
      REFUTED  — the source was reached and witnessed the effect did NOT happen (the
                 recipient never got it; the exit code was non-zero). The
                 load-bearing third value: a refutation by an accountable witness is
                 STRONGER than no signal — it should redden `verify`, never be
                 mistaken for "could not tell."
      NO_SIGNAL — the source could not be reached/read, or has no record either way.
                 The honest floor; what every failure degrades to. A consumer reads
                 it as abstain (the `run_judge` / behavioral-oracle fail-safe).
    """

    ATTESTED = "ATTESTED"
    REFUTED = "REFUTED"
    NO_SIGNAL = "NO_SIGNAL"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class EvidenceFacts:
    """Frozen, caller-gathered facts about one effect, from one witness.

    The `CiEvidence` / `LogEvidence` / `ProgressEvidence` analogue: facts gathered at
    the boundary (inside a source's `gather`) and handed to a consuming verdict, which
    is pure. No verdict lives inside — the source reports what it *saw*, the floor
    helper decides what `verify` may *believe*.

      source_name    — the backend that produced this (`"os_acceptance"`,
                       `"stripe_ledger"`), for the operator-facing reason + the JSON
                       consumer.
      accountability — the source's spectrum rung (docs/117). The load-bearing field:
                       `believe_under_floor` grants belief only on a NON-FORGEABLE
                       rung, never off content. A class-level property of the source,
                       echoed onto the facts so a downstream consumer routes off the
                       evidence object alone.
      stance         — ATTESTED / REFUTED / NO_SIGNAL (above).
      subject        — the effect this witnesses (an opaque correlation handle: a
                       run-id, a message-id, a command, a SHA — the source decides),
                       echoed for the operator surface.
      detail         — a one-line human note (the exit code, the provider id, why
                       unreachable) — legible distrust, for the reason / `dos doctor`.
      reachable      — was the witness actually reached? **Defaults to False** — the
                       fail-safe zero: facts nobody successfully populated read as
                       "no signal," never an empty-but-trusted attestation. A
                       `NO_SIGNAL` stance with `reachable=False` is the honest floor.

    Three constructors make the outcomes unmistakable and keep the fail-safe default
    from being fat-fingered: `attest(...)` (reached, effect happened),
    `refute(...)` (reached, effect did NOT happen), `no_signal(...)` (every degrade).
    There is deliberately no other way to set `reachable=True`.
    """

    source_name: str
    accountability: Accountability
    stance: EvidenceStance = EvidenceStance.NO_SIGNAL
    subject: str = ""
    detail: str = ""
    reachable: bool = False

    @classmethod
    def attest(
        cls,
        source_name: str,
        accountability: Accountability,
        subject: str,
        *,
        detail: str = "",
    ) -> "EvidenceFacts":
        """The witness was reached and the effect HAPPENED. One of only two
        constructors that set `reachable=True` — so a reachable attestation is always
        a deliberate, populated read, never an accident of the default."""
        return cls(
            source_name=source_name,
            accountability=accountability,
            stance=EvidenceStance.ATTESTED,
            subject=subject,
            detail=detail,
            reachable=True,
        )

    @classmethod
    def refute(
        cls,
        source_name: str,
        accountability: Accountability,
        subject: str,
        *,
        detail: str = "",
    ) -> "EvidenceFacts":
        """The witness was reached and the effect did NOT happen (the recipient has no
        record; the exit code was non-zero). `reachable=True`, stance REFUTED — a
        positive disconfirmation, distinct from "could not tell.\""""
        return cls(
            source_name=source_name,
            accountability=accountability,
            stance=EvidenceStance.REFUTED,
            subject=subject,
            detail=detail,
            reachable=True,
        )

    @classmethod
    def no_signal(
        cls,
        source_name: str,
        accountability: Accountability,
        subject: str = "",
        *,
        detail: str = "",
    ) -> "EvidenceFacts":
        """The witness could not be reached/read, or has no record either way — the
        honest floor (no source wired, auth failed, timeout, no such record).
        `reachable=False`, stance NO_SIGNAL. What every failure in `gather_evidence`
        degrades to, and what a consuming verdict reads as abstain — never a
        fabricated attestation (the `run_judge` fail-safe-never-fail-open discipline).
        """
        return cls(
            source_name=source_name,
            accountability=accountability,
            stance=EvidenceStance.NO_SIGNAL,
            subject=subject,
            detail=detail,
            reachable=False,
        )

    @property
    def is_attesting(self) -> bool:
        """True iff this is a reached ATTESTED read — the precondition (not the whole
        condition) for contributing belief. `believe_under_floor` ANDs this with the
        non-forgeable-accountability check; on its own it is necessary, not
        sufficient."""
        return self.reachable and self.stance is EvidenceStance.ATTESTED

    def to_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "accountability": self.accountability.value,
            "stance": self.stance.value,
            "subject": self.subject,
            "detail": self.detail,
            "reachable": self.reachable,
        }


@runtime_checkable
class EvidenceSource(Protocol):
    """The contract a backend implements to add a witness.

    `name` is the token a resolver selects and `dos doctor` would list.
    `accountability` is the source's declared spectrum rung — a CLASS-LEVEL property,
    fixed by the backend, not chosen per call (an `os_acceptance` source is
    `OS_RECORDED` always; it has no honest path to a higher rung; a `paste_receipt`
    source is `AGENT_AUTHORED` always and can never attest belief). `gather` is handed
    a `subject` (the opaque correlation handle — the source decides what it means) and
    the active `config` (read-only), and returns `EvidenceFacts`.

    A backend MAY do I/O *inside* `gather` (run a command, call a provider API, read a
    TEE quote) — unlike a predicate or renderer, which are pure. That is exactly why a
    real backend lives in a driver, outside the kernel boundary: this seam is where
    I/O surface is allowed, the same latitude the `Judge` / `LogSource` protocols give.
    The discipline that keeps it honest is not purity but **fail-safe** (enforced by
    `gather_evidence`, below, not by trusting the backend) plus the **fixed
    accountability tag** (a backend cannot lie its way up the spectrum at call time)
    plus the **floor discipline** (`believe_under_floor` — a forgeable-floor source's
    attestation can never, by itself, move `verify` to belief).
    """

    name: str
    accountability: Accountability

    def gather(self, subject: str, config: object) -> EvidenceFacts:
        ...


class NullEvidenceSource:
    """The built-in, always-available source: it witnesses nothing.

    The evidence analogue of `NullLogSource` / `AbstainJudge` — a trusted,
    unshadowable fallback (`resolve_evidence_source` resolves built-ins first) and the
    honest zero of the seam: a deployment with NO witness wired still has a resolvable
    source, and it returns `no_signal` for every subject. A device with no git and no
    network resolves to {this} only, so `verify` honestly abstains (`via none`) rather
    than inventing a witness.

    Tagged `AGENT_AUTHORED` — the floor — so that even the *absence* of a real source
    can never be mistaken for a trustworthy rung: the most a missing witness can claim
    is the least-trusted tag, and it is unreachable on top of that. It is doubly
    incapable of granting belief (forgeable rung AND never reachable).
    """

    name = "null"
    accountability = Accountability.AGENT_AUTHORED

    def gather(self, subject: str, config: object) -> EvidenceFacts:
        return EvidenceFacts.no_signal(
            self.name,
            self.accountability,
            subject,
            detail=(
                "no evidence source wired — the built-in null source witnesses "
                "nothing, so this effect has no signal (configure a "
                "dos.evidence_sources backend)."
            ),
        )


def gather_evidence(source: EvidenceSource, subject: str, config: object) -> EvidenceFacts:
    """Run one source against one subject, enforcing **fail-safe, never fail-open**.

    The wrapper EVERY consumer should call instead of `source.gather(...)` directly —
    what makes "a backend can never manufacture an attestation by failing" structural
    rather than hoped-for (the `run_judge` / `gather_log` discipline, restated for
    witnesses):

      * a source that **raises** (command missing, API timeout, a bug) → an
        unreachable `no_signal` naming the failure. Never propagates; never a
        reachable read; never an ATTESTED.
      * a source that returns **anything that is not `EvidenceFacts`** (None, a dict,
        a bare bool, a duck-typed look-alike) → `no_signal`. We never read a foreign
        object's `.stance`/`.reachable`, so no fabricated attestation can sneak through
        a wrong return type.

    The degrade preserves the source's declared `accountability` (read defensively via
    `getattr`, defaulting to the forgeable floor) so a consumer still routes correctly
    on failure AND a malformed source object cannot escape to a higher rung via the
    failure path. The safe failure is "no signal" (abstain), never "attest" and never
    "refute" — an evidence gatherer that cannot read produces NO_SIGNAL, the same
    direction `gather_log` takes (evidence-gathering, not a safety gate).
    """
    name = getattr(source, "name", type(source).__name__)
    acct = getattr(source, "accountability", Accountability.AGENT_AUTHORED)
    if not isinstance(acct, Accountability):
        acct = Accountability.AGENT_AUTHORED
    try:
        facts = source.gather(subject, config)
    except Exception as e:  # fail-safe: a source that raises produces no signal
        return EvidenceFacts.no_signal(
            str(name),
            acct,
            subject,
            detail=(
                f"evidence source {name!r} raised ({e!r}) — no signal (a witness that "
                f"cannot read produces NO_SIGNAL, never a fabricated attestation)."
            ),
        )
    if not isinstance(facts, EvidenceFacts):
        return EvidenceFacts.no_signal(
            str(name),
            acct,
            subject,
            detail=(
                f"evidence source {name!r} returned a {type(facts).__name__}, not "
                f"EvidenceFacts — no signal (a source that does not return the evidence "
                f"type cannot be trusted to have witnessed anything)."
            ),
        )
    return facts


# ---------------------------------------------------------------------------
# The floor discipline — `believe ⟺ a non-forgeable source attests`.
# The dual of `overlap_policy.admissible_under_floor`: a structural guarantee
# that no forgeable-floor source can manufacture belief.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BeliefVerdict:
    """The folded answer over a set of gathered `EvidenceFacts` for one effect.

    `believe` is the positive bit `verify` may consume — but it is True ONLY when at
    least one NON-FORGEABLE source attested (the floor discipline). `refuted` is
    surfaced separately because a refutation by an accountable witness is a distinct,
    stronger signal than mere absence of belief — a consumer may redden on it.
    `attesting` / `refuting` / `silent` name the sources behind the verdict (legible
    distrust — not just "believed" but *which witness* attested, the RND renderer
    seam). `to_dict()` is the JSON shape for `--json` / MCP / the decisions queue.
    """

    believe: bool
    refuted: bool
    reason: str
    attesting: tuple[str, ...] = ()
    refuting: tuple[str, ...] = ()
    silent: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "believe": self.believe,
            "refuted": self.refuted,
            "reason": self.reason,
            "attesting": list(self.attesting),
            "refuting": list(self.refuting),
            "silent": list(self.silent),
        }


def believe_under_floor(facts: "tuple[EvidenceFacts, ...] | list[EvidenceFacts]") -> BeliefVerdict:
    """Fold gathered facts into a belief verdict, enforcing the floor discipline.

    The security-load-bearing function — the dual of
    `overlap_policy.admissible_under_floor`. It reads the gathered witnesses and
    answers the only question `verify` cares about: *may we BELIEVE this effect
    happened?* The rule is structural, not a threshold a host can loosen:

      > believe ⟺ at least one source whose `accountability` is NON-FORGEABLE
      >           (`OS_RECORDED` / `THIRD_PARTY`) was reached and ATTESTED.

    So a forgeable-floor source (`AGENT_AUTHORED` — a pasted receipt, the agent's own
    stdout, an mtime) is *structurally incapable* of granting belief: its ATTESTED
    facts are recorded in `attesting` and shown, but they are filtered out of the
    belief decision by the accountability check. The worst a buggy/hostile/lying
    AGENT_AUTHORED source can do is claim an attestation that is then **ignored for
    belief** (a visible, safe-direction no-op), never manufacture a SHIPPED verdict.

    A REFUTED by an accountable witness sets `refuted=True` (a consumer may redden);
    a REFUTED by a forgeable source is recorded but, symmetrically, does not by itself
    establish refutation (the floor cuts both ways — a forgeable source is too weak to
    *redden* `verify` on its own, just as it is too weak to greenlight it). Belief and
    refutation are independent: a population can attest (one accountable source) AND
    refute (another) at once, which a consumer routes to a human as a conflict.

    PURE — no I/O. The facts were gathered at the boundary; this only folds them.
    """
    attesting: list[str] = []
    refuting: list[str] = []
    silent: list[str] = []
    believe = False
    refuted = False

    for f in facts:
        non_forgeable = not f.accountability.is_agent_authored
        if f.reachable and f.stance is EvidenceStance.ATTESTED:
            attesting.append(f.source_name)
            if non_forgeable:
                believe = True
        elif f.reachable and f.stance is EvidenceStance.REFUTED:
            refuting.append(f.source_name)
            if non_forgeable:
                refuted = True
        else:
            silent.append(f.source_name)

    if believe and refuted:
        reason = (
            f"CONFLICT — accountable witnesses disagree: {', '.join(attesting)} attest, "
            f"{', '.join(refuting)} refute (route to a human)"
        )
    elif believe:
        reason = f"believed — non-forgeable witness attested: {', '.join(attesting)}"
    elif refuted:
        reason = f"refuted — non-forgeable witness disconfirmed: {', '.join(refuting)}"
    elif attesting:
        # Something attested, but only on the forgeable floor — the floor discipline
        # withholds belief. Name it so the operator sees WHY a present attestation did
        # not count.
        reason = (
            f"abstain — only forgeable-floor (AGENT_AUTHORED) sources attested "
            f"({', '.join(attesting)}); no accountable witness — verify cannot believe"
        )
    else:
        reason = "abstain — no witness reached this effect (no signal)"

    return BeliefVerdict(
        believe=believe,
        refuted=refuted,
        reason=reason,
        attesting=tuple(attesting),
        refuting=tuple(refuting),
        silent=tuple(silent),
    )


# ---------------------------------------------------------------------------
# The derived-witness primitive — the floor discipline lifted to a DERIVATION.
# (docs/156 — the byte-inequality axiom, docs/141, moved up one level: a value
# COMPUTED from operands is only as non-forgeable as BOTH its operands AND its
# recorded operation. Closes the grounded-RAG adoption's one soundness hole — a
# host that brute-forced agent-SELECTED arithmetic onto the THIRD_PARTY rung.)
# ---------------------------------------------------------------------------

# The accountability spectrum ordered weakest→strongest, so a derivation can be
# capped at the MINIMUM rung among its operands (you cannot derive a stronger fact
# than your weakest input — the "ceiling fixed by the source" rule, made inductive).
_RUNG_ORDER: dict[Accountability, int] = {
    Accountability.AGENT_AUTHORED: 0,
    Accountability.OS_RECORDED: 1,
    Accountability.THIRD_PARTY: 2,
}


def _operand_rung(operand: "EvidenceFacts | BeliefVerdict") -> "Accountability | None":
    """The non-forgeable rung an operand was witnessed at, or None if it is not a
    reached non-forgeable attestation. A `BeliefVerdict` operand counts iff it
    `believe`s (which `believe_under_floor` only grants on a non-forgeable attest, so
    a believed verdict is THIRD_PARTY-equivalent — the strongest the floor mints). An
    `EvidenceFacts` operand counts iff it `is_attesting` on a non-forgeable rung."""
    if isinstance(operand, BeliefVerdict):
        # A believed verdict already passed the floor: a non-forgeable witness attested.
        # It carries no single rung, so treat it as the floor's own guarantee (THIRD_PARTY).
        return Accountability.THIRD_PARTY if (operand.believe and not operand.refuted) else None
    if isinstance(operand, EvidenceFacts):
        if operand.is_attesting and not operand.accountability.is_agent_authored:
            return operand.accountability
        return None
    return None


def derived_witness(
    source_name: str,
    op: str,
    operands: "tuple[EvidenceFacts | BeliefVerdict, ...] | list[EvidenceFacts | BeliefVerdict]",
    *,
    subject: str,
    within_tol: bool,
    detail: str = "",
) -> EvidenceFacts:
    """Mint an `EvidenceFacts` for a value the agent COMPUTED from operands, on a
    non-forgeable rung ONLY when the derivation is honest by construction.

    The dual of `believe_under_floor`, lifted from a witnessed effect to a *derivation*
    (docs/156 §3). The security-load-bearing rule — structural, not a host knob:

      > A derived value may be witnessed on a NON-FORGEABLE rung IFF
      >   (1) the operation `op` is a DECLARED token (passed in by the caller — never
      >       reverse-searched to fit the answer; a brute-force "does this equal SOME
      >       operand pairing?" search IS the agent-selection that forges the rung, and
      >       this helper refuses to express it — the caller must commit to one op), AND
      >   (2) EVERY operand was itself attested by a non-forgeable witness, AND
      >   (3) the recomputation of `op` over the operands matches the claim (`within_tol`).

    Failure modes, in the safe direction:

    - Any operand unwitnessed / forgeable → the derived fact degrades to
      **AGENT_AUTHORED** (recorded, advisory, structurally incapable of granting belief
      under `believe_under_floor`). You CANNOT reach a non-forgeable rung without
      non-forgeable operands — the laundering the grounded-RAG host did (tagging
      agent-selected arithmetic `THIRD_PARTY`) becomes impossible.
    - `op` empty/missing → AGENT_AUTHORED (an undeclared op is a post-hoc fit).
    - `within_tol=False` → **refute** (a positive disconfirmation, distinct from "could
      not tell" — the recomputation was done and it disagreed).

    The result's accountability is the **minimum rung** among the operands (the weakest
    operand caps the derivation). PURE — no I/O; the operands were witnessed at the
    boundary and the recomputation was done by the caller (it passes the verdict in via
    `within_tol`); this only folds rung + op-declaration into the honest tag.
    """
    rungs = [_operand_rung(o) for o in operands]
    op_declared = bool(op and op.strip())
    all_non_forgeable = bool(operands) and all(r is not None for r in rungs)

    if not within_tol:
        # The recomputation disagreed — a refutation. Rung still capped honestly: a
        # refutation from forgeable operands is weaker, but a disagreement is a
        # disagreement; tag it at the min available rung (AGENT_AUTHORED if any operand
        # is forgeable, so a forgeable refute cannot, by the floor, redden on its own).
        rung = _min_rung(rungs)
        return EvidenceFacts.refute(
            source_name, rung, subject,
            detail=detail or f"derived op={op or '(undeclared)'} recomputation disagrees",
        )

    if op_declared and all_non_forgeable:
        rung = _min_rung(rungs)
        return EvidenceFacts.attest(
            source_name, rung, subject,
            detail=detail or f"derived op={op} from {len(operands)} non-forgeable operand(s)",
        )

    # Honest degrade: the derivation is recorded but cannot reach a non-forgeable rung
    # (undeclared op, or an operand the agent could have authored). AGENT_AUTHORED so
    # the floor treats it as advisory — never a forged THIRD_PARTY.
    why = (
        "undeclared operation (post-hoc fit)" if not op_declared
        else "an operand lacks a non-forgeable witness"
    )
    return EvidenceFacts.attest(
        source_name, Accountability.AGENT_AUTHORED, subject,
        detail=detail or f"derived op={op or '(undeclared)'} — advisory only: {why}",
    )


def _min_rung(rungs: "list[Accountability | None]") -> Accountability:
    """The weakest non-None rung among operands, or AGENT_AUTHORED if any is None/empty
    (a missing operand witness caps the whole derivation at the forgeable floor)."""
    present = [r for r in rungs if r is not None]
    if not present or len(present) != len(rungs):
        return Accountability.AGENT_AUTHORED
    return min(present, key=lambda r: _RUNG_ORDER[r])


# ---------------------------------------------------------------------------
# Resolution — built-in first, then the `dos.evidence_sources` entry-point group.
# (The `resolve_judge` / `resolve_log_source` discipline, verbatim.)
# ---------------------------------------------------------------------------

# The entry-point group a workspace/researcher registers a witness backend under.
EVIDENCE_SOURCE_ENTRY_POINT_GROUP = "dos.evidence_sources"

# The built-in sources, resolvable by name and UNSHADOWABLE by a plugin (a plugin
# registering `null` cannot displace this one — built-ins resolve first). Only the
# conservative `null` baseline ships in the kernel; every witnessing backend lives in
# a driver/plugin (the kernel has no I/O/provider surface).
_BUILT_IN_SOURCES: dict[str, type] = {
    NullEvidenceSource.name: NullEvidenceSource,
}


def _discover_entry_point_sources(*, _stderr=None) -> list[tuple[str, EvidenceSource]]:
    """Find witness backends registered under the `dos.evidence_sources` group.

    A backend plugin registers ``name = "pkg.module:SourceClass"`` in its
    ``[project.entry-points."dos.evidence_sources"]``. We load each, instantiate it if
    it is a class, and return ``(entry_point_name, source)`` pairs sorted by name
    (stable, deterministic listing). A plugin that fails to load is skipped with a
    one-line stderr note rather than crashing — the same posture judge / log-source /
    predicate / renderer discovery take (a broken third-party plugin is the operator's
    to fix, not a kernel fault).
    """
    stderr = _stderr if _stderr is not None else sys.stderr
    out: list[tuple[str, EvidenceSource]] = []
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - importlib.metadata always present py3.11+
        return out
    try:
        eps = entry_points(group=EVIDENCE_SOURCE_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - py<3.10 selectable-API fallback
        eps = entry_points().get(EVIDENCE_SOURCE_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive: never let discovery crash a call
        return out
    for ep in sorted(eps, key=lambda e: e.name):
        try:
            obj = ep.load()
            source = obj() if isinstance(obj, type) else obj
        except Exception as e:  # pragma: no cover - depends on third-party plugin
            print(
                f"warning: evidence source plugin {ep.name!r} failed to load ({e}); skipping",
                file=stderr,
            )
            continue
        out.append((ep.name, source))
    return out


def resolve_evidence_source(name: str, *, _stderr=None) -> EvidenceSource:
    """Resolve a witness by name: built-ins first, then `dos.evidence_sources` plugins.

    Built-ins (`null`) resolve FIRST and cannot be shadowed by a plugin of the same
    name — the trusted-fallback guarantee, identical to `resolve_judge` /
    `resolve_log_source`. An unknown name fails LOUD with the known list (it never
    silently degrades to `null`, which would hide a typo'd source name): the caller
    asked for a specific witness and getting a different one silently is exactly the
    unannounced substitution the kernel refuses.
    """
    if name in _BUILT_IN_SOURCES:
        return _BUILT_IN_SOURCES[name]()
    discovered = dict(_discover_entry_point_sources(_stderr=_stderr))
    if name in discovered:
        return discovered[name]
    known = sorted(set(_BUILT_IN_SOURCES) | set(discovered))
    raise ValueError(f"unknown evidence source {name!r}; known: {', '.join(known)}")


def active_evidence_sources(*, _stderr=None) -> list[tuple[str, EvidenceSource]]:
    """Every resolvable source as ``(name, source)`` — built-ins THEN discovered
    plugins. Does ENTRY-POINT DISCOVERY (I/O), so it is a call-boundary helper, never
    called inside a verdict (the `active_judges` / `active_log_sources` discipline)."""
    built = [(n, cls()) for n, cls in _BUILT_IN_SOURCES.items()]
    discovered = _discover_entry_point_sources(_stderr=_stderr)
    return built + discovered


def active_evidence_source_names(*, _stderr=None) -> list[str]:
    """The names of every active source (built-in + discovered) — what `dos doctor`
    would list so an operator can see which witnesses are wired (the evidence analogue
    of "see the active judges / log sources / predicates")."""
    return [name for name, _src in active_evidence_sources(_stderr=_stderr)]

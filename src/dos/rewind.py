"""rewind — the conversation-rewind verdict: backjump to a minted checkpoint + a no-good note (docs/164 F1.5).

> **A failed fix attempt accretes corruption: each retry pastes its own dead end
> into the next prompt, and the loop walks back into the same hole. So rewinding a
> conversation is the distrust primitive pointed at the transcript itself — roll
> back to a checkpoint the KERNEL stamped (never a turn the agent claims it was
> at), excise the dead-end turns, and re-attach only un-forged bytes (the kernel's
> own typed verdict + the environment's own error excerpt). Subtract forged
> context; author nothing.**

This is `resume`'s CONVERSATION-axis sibling, field-for-field. `resume` rewinds
GIT state (HEAD → a re-entry SHA over a `run_id`-keyed intent ledger); `rewind`
rewinds the TRANSCRIPT (turns → a `(turn_index, transcript_digest)` checkpoint over
the SAME `OP_SUSPEND` anchor). They share one anchor — `intent_ledger.suspend_entry`
records both the git `resume_sha` and the conversation checkpoint — each axis
reading its own field (docs/164 §3, the "two rewind axes, one anchor" line):

    resume.resume_plan   (LedgerState, AncestryFacts, policy)         -> ResumePlan
    rewind.rewind_plan   (turns, SuspendCheckpoint, FireVerdict, …)   -> RewindPlan
                         ^ THIS module

All I/O — DIGESTING the transcript turns (hashing bytes), reading the clock,
decoding the SUSPEND record off `intent.jsonl` — happens in the CALLER (a thin
`rewind_evidence.py` reader, the `resume_evidence` analogue), exactly as `resume`'s
git reads happen outside `resume_plan`. `rewind_plan` makes no subprocess, file, or
clock call: the per-turn digests arrive as data on the `TurnRef`s, and the verdict
only COMPARES pre-computed digests and FOLDS pre-built tokens. That is what lets the
whole rewind LOGIC be replay-tested on frozen turn + checkpoint fixtures — no live
loop needed.

The three load-bearing properties (docs/164 §6 litmus):

  * **Rewind is to a MINTED anchor.** `rewind_to_turn` is `checkpoint.turn_index`
    ONLY when the turn at that index DIGESTS to `checkpoint.transcript_digest` — the
    stamp the kernel actually minted at SUSPEND. A mismatch (or a missing checkpoint)
    is `UNANCHORED`: the kernel rewinds to NOTHING rather than to a turn the agent
    claims it was at. This is the floor framing (`evidence.believe_under_floor`)
    lifted to the conversation axis: the digest's byte-author is the kernel's hash of
    the turn at SUSPEND, NOT the judged agent, so the digest is the non-forgeable
    rewind anchor and `UNANCHORED` is precisely a floor failure.
  * **The no-good note carries verdict + env bytes, NEVER a generated critique.** The
    note is built from EXACTLY two byte-classes and the type system makes a third
    impossible — there is no free-form `str` parameter anywhere on the note-building
    path. (a) closed `rewind_tokens.VerdictToken`s rendered via a registry-owned
    template over structured fields the kernel computed; (b) an `EnvExcerpt` whose
    `accountability` MUST be non-`AGENT_AUTHORED` (`OS_RECORDED` / `THIRD_PARTY`) to
    ATTACH — an `AGENT_AUTHORED` excerpt is structurally filtered out (the floor's
    safe-direction no-op). So the F0 Traceback (env-authored) attaches, but anything
    the judged agent could have authored cannot — the note carries the F0 bytes the
    same way `dos_react.py:201` carries the Traceback, never `response.content`.
  * **The loop terminates on GROUND TRUTH.** `rewind_plan` fires `REWIND` only when
    `fire` is `Resume.DIVERGED` or `Convergence.THRASHING`/`STARVED` (the
    `should_surface` set) — all computed from git ancestry + the residual upstream,
    never a self-reported "I'm close." A `fire` carrying `CONVERGING`/`RESUMABLE`
    yields `NO_REWIND` (the loop continues). The cap is on the ground-truth verdict,
    not the agent's account.

The belief/effect line (docs/164 §1, the docs/99 advisory floor): `rewind_plan`
MINTS a belief (the checkpoint is a valid rewind anchor; these turns are dead ends)
and PROPOSES an effect (the consumer truncates its own transcript to `rewind_to_turn`
and re-enters with the note). **The kernel never truncates the transcript** — "the
host owns the transcript" (docs/164 P1.5). The verdict returns a PLAN; enacting it
is the loop's.

Pure stdlib — no third-party imports, no I/O inside a verdict. Imports only sibling
kernel modules (`resume`, `completion`, `evidence`/`log_source`, `intent_ledger`)
plus the `rewind_tokens` seam-data leaf — the "no host, no I/O policy" litmus, not
"no sibling import" (CLAUDE.md). It is KERNEL, not a driver: state-in / plan-out,
names no host, and a no-good NOTE is a refusal — the one thing docs/82 says the
kernel may author.
"""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass, field
from typing import Optional

from dos.completion import Convergence
from dos.intent_ledger import SuspendCheckpoint
from dos.log_source import Accountability
from dos.resume import Resume
from dos.rewind_tokens import (
    BASE_REWIND_TOKENS,
    RewindTokenRegistry,
    VerdictToken,
)

__all__ = [
    "Rewind",
    "TurnRef",
    "SuspendCheckpoint",
    "FireVerdict",
    "EnvExcerpt",
    "NoGoodNote",
    "RewindPolicy",
    "DEFAULT_REWIND_POLICY",
    "RewindPlan",
    "digest_turn",
    "build_no_good_note",
    "rewind_plan",
]


# ───────────────────────────── the typed rewind verdict ──────────────────────
class Rewind(str, enum.Enum):
    """The typed rewind verdict — three states, mutually exclusive (docs/164 F1.5).

    `str`-valued so it round-trips a `--json` token / exit-code map without a lookup
    table (the `Resume` / `Completion` / `Liveness` idiom). Only `REWIND` authorises
    the consumer to truncate-and-re-enter; the other two keep the transcript intact.

      REWIND     — fire on a ground-truth stop signal AND a minted, matching anchor:
                   truncate to `rewind_to_turn`, excise `dropped_turns`, re-enter with
                   the no-good note.
      NO_REWIND  — the fire verdict is NOT a ground-truth stop signal (CONVERGING /
                   RESUMABLE / …): the loop continues, the transcript is untouched.
      UNANCHORED — there IS a fire, but the checkpoint does not digest to the turn it
                   names (or there is no checkpoint): refuse to rewind to a turn the
                   kernel did not stamp. The §6 "rewind to a minted anchor or refuse"
                   floor — the conversation-axis analogue of `resume.DIVERGED`'s
                   refuse-don't-overwrite.
    """

    REWIND = "REWIND"
    NO_REWIND = "NO_REWIND"
    UNANCHORED = "UNANCHORED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_actionable(self) -> bool:
        """True iff the consumer should truncate-and-re-enter (REWIND only)."""
        return self is Rewind.REWIND


# ───────────────────────────── the inputs (frozen data) ──────────────────────
@dataclass(frozen=True)
class TurnRef:
    """One transcript turn, AS DATA — an `(index, digest)` pair, NEVER its content.

    The verdict sees only indices + per-turn digests, never turn CONTENT, so no agent
    prose can leak into the decision (the same reason `arg_provenance` is byte-clean:
    the judged agent did not author the IDENTITY of its own turns' digests — the
    kernel hashed them at the boundary). The BYTES live at the boundary; this is the
    `ProgressEvidence`/`AncestryFacts` shape — caller-gathered facts handed to a pure
    verdict.

      index  — the turn's position in the transcript (0-based; the host's own turn
               numbering). What `rewind_to_turn` / `dropped_turns` are expressed in.
      digest — the kernel's hex digest of the turn's bytes (`digest_turn`, computed at
               the boundary). Compared against `SuspendCheckpoint.transcript_digest`
               to decide whether the named turn is the one the kernel actually stamped.
    """

    index: int
    digest: str


# `SuspendCheckpoint` — the minted conversation rewind anchor — is defined ONCE in
# `intent_ledger` (beside the SUSPEND record it serializes onto, the sibling of the
# git-axis `suspend_resume_sha`) and imported above. It is the `(turn_index,
# transcript_digest)` the kernel STAMPED at `OP_SUSPEND`: the rewind is valid ONLY if
# the live turn at `turn_index` still digests to `transcript_digest` (else the agent
# or a successor rewrote history under the checkpoint — `UNANCHORED`). `present=False`
# (its `absent()`) is the honest zero — no checkpoint minted — and yields UNANCHORED.


@dataclass(frozen=True)
class FireVerdict:
    """The trigger: an already-computed ground-truth stop signal, passed in (never re-derived).

    A CLOSED union of the two ground-truth stop signals docs/164 §6 names — wrapped as
    the already-computed enum so the rewind verdict NEVER re-derives them (the
    `resume`/`completion` reuse-not-reimplement rule). The boundary computes them
    (`resume.resume_plan` → `Resume`; `completion.convergence` → `Convergence`) and
    hands the enum in.

      resume_verdict      — a `resume.Resume` value, or None if this fire is not a
                            resume signal. `DIVERGED` is the git-axis stop trigger.
      convergence_verdict — a `completion.Convergence` value, or None. `THRASHING` /
                            `STARVED` (its `should_surface` set) are the loop-cap
                            triggers.

    Exactly one of the two is expected to be set per fire (the boundary builds it from
    whichever verdict fired); both-None is a non-firing verdict (`NO_REWIND`).
    """

    resume_verdict: Optional[Resume] = None
    convergence_verdict: Optional[Convergence] = None

    @classmethod
    def from_resume(cls, verdict: Resume) -> "FireVerdict":
        return cls(resume_verdict=verdict, convergence_verdict=None)

    @classmethod
    def from_convergence(cls, verdict: Convergence) -> "FireVerdict":
        return cls(resume_verdict=None, convergence_verdict=verdict)

    @property
    def should_surface(self) -> bool:
        """True iff this fire is a GROUND-TRUTH stop signal that warrants a rewind.

        The cap is on the ground-truth verdict, never the agent's account (docs/164
        §6): `Resume.DIVERGED` (ground truth moved past the resume point) OR a
        `Convergence` in its `should_surface` set (THRASHING / STARVED — the residual
        has no fixpoint). A `CONVERGING`/`RESUMABLE`/`COMPLETE`/`INSUFFICIENT` fire is
        NOT a stop signal — the loop continues, the transcript is untouched.
        """
        if self.resume_verdict is Resume.DIVERGED:
            return True
        if self.convergence_verdict is not None and self.convergence_verdict.should_surface:
            return True
        return False

    def _label(self) -> str:
        """A short token for the operator reason (which signal fired)."""
        if self.resume_verdict is not None:
            return f"resume={self.resume_verdict.value}"
        if self.convergence_verdict is not None:
            return f"convergence={self.convergence_verdict.value}"
        return "(no signal)"


@dataclass(frozen=True)
class EnvExcerpt:
    """The (b)-class no-good byte: an environment error excerpt + its accountability rung.

    The F0 re-surface bytes (`dos_react.py:201` — the Traceback, NOT
    `response.content`). Wrapped so its `accountability` is carried: `build_no_good_note`
    ATTACHES it ONLY when the rung is non-`AGENT_AUTHORED` (`OS_RECORDED` /
    `THIRD_PARTY`), running the bytes through the `evidence.believe_under_floor`
    framing — an `AGENT_AUTHORED` excerpt is structurally filtered out (the floor's
    safe-direction no-op). So the env's own Traceback attaches; anything the judged
    agent could have authored cannot.

      text           — the excerpt bytes (the Traceback / the env error). This IS a
                       `str`, but it is NOT a free-form caller slot for prose: it is
                       gated by `accountability`, so the only `str` that survives onto
                       the note is one a non-agent author wrote. A generated critique
                       tagged `AGENT_AUTHORED` is filtered; a generated critique tagged
                       `THIRD_PARTY` is a LIE about its byte-author the boundary reader
                       must not mint (the same discipline `log_source` enforces — the
                       tag is a ceiling fixed by the source, never inferred from
                       content).
      accountability — who authored the bytes (`log_source.Accountability`). The
                       load-bearing field: the attach gate reads it.
    """

    text: str
    accountability: Accountability

    @property
    def attaches(self) -> bool:
        """True iff this excerpt's rung is non-forgeable, so it may attach to the note.

        The floor discipline, restated for the env excerpt: an `AGENT_AUTHORED`
        excerpt is structurally incapable of attaching (`believe_under_floor`'s
        forgeable-floor no-op), so only the env's / a third party's own bytes survive.
        """
        return not self.accountability.is_agent_authored


@dataclass(frozen=True)
class NoGoodNote:
    """The byte-clean re-entry annotation: closed verdict tokens + an env excerpt ONLY.

    The docs/164 §6 no-good note. STRUCTURAL enforcement of "verdict + env bytes,
    never a generated critique": this dataclass has NO constructor field of type
    `str` that a caller fills freely. It holds `tuple[VerdictToken, ...]` (each a
    closed `(kind, payload)` rendered via the registry's kernel-owned template) and an
    optional `EnvExcerpt` (gated to a non-`AGENT_AUTHORED` rung). The closed
    `VerdictToken` vocabulary + the registry-owned render template + the floor-gated
    env passthrough together mean there is no reachable code path by which
    model-generated prose becomes a note byte — the §6 grep-for-generated-prose litmus
    has nothing to find.

      tokens       — the closed kernel verdict tokens (rendered by `render_lines`).
      env_excerpt  — the attached env error excerpt, or None when none crossed the
                     floor (a `None` excerpt is the absence of un-forged env bytes,
                     never a placeholder for prose).
      registry     — the `RewindTokenRegistry` whose templates render the tokens (the
                     active vocabulary; defaults to `BASE_REWIND_TOKENS`). Carried so
                     `render_lines` is self-contained — a token's rendered string is
                     always its OWN registry's kernel-authored template, never a
                     caller string.
    """

    tokens: tuple[VerdictToken, ...] = ()
    env_excerpt: Optional[EnvExcerpt] = None
    registry: RewindTokenRegistry = BASE_REWIND_TOKENS

    def render_lines(self) -> tuple[str, ...]:
        """The note's bytes, line by line — ONLY rendered tokens + the env excerpt.

        Each token renders through the registry's kernel-owned template
        (`registry.render`); the env excerpt (if any crossed the floor) is appended
        verbatim under a kernel-authored header. There is no other source of bytes —
        no caller `str`, no generated prose. This is the method a consumer prints when
        re-entering the rewound conversation.
        """
        lines: list[str] = [self.registry.render(t) for t in self.tokens]
        if self.env_excerpt is not None:
            # The env excerpt already passed the floor at build time; we just echo its
            # bytes under a kernel-authored header (the header is the kernel's, the body
            # is the env's — both un-forged).
            lines.append(f"env error excerpt [{self.env_excerpt.accountability.value}]:")
            lines.append(self.env_excerpt.text)
        return tuple(lines)

    def to_dict(self) -> dict:
        return {
            "tokens": [{"kind": t.kind, "payload": dict(t.payload),
                        "rendered": self.registry.render(t)} for t in self.tokens],
            "env_excerpt": (
                {"text": self.env_excerpt.text,
                 "accountability": self.env_excerpt.accountability.value}
                if self.env_excerpt is not None else None
            ),
            "lines": list(self.render_lines()),
        }


@dataclass(frozen=True)
class RewindPolicy:
    """The knobs that shape the rewind verdict — policy, not mechanism (the `ResumePolicy` split).

    Defaults are GENERIC (no host tuning); a workspace could declare its own in
    `dos.toml [rewind]` (a future seam, like the planned `[liveness]`/`[resume]`).

      require_matching_digest — when True (the §6 default), the rewind target's live
        turn MUST digest to `checkpoint.transcript_digest` or the verdict is
        `UNANCHORED`. This is the non-forgeable-anchor floor; turning it off would let
        the kernel rewind to a turn it never stamped (the bug the litmus forbids), so
        it has no honest reason to be False — it exists as the explicit name of the
        property a test pins, not as a knob a host should flip.
    """

    require_matching_digest: bool = True


DEFAULT_REWIND_POLICY = RewindPolicy()


@dataclass(frozen=True)
class RewindPlan:
    """The single verdict `rewind_plan` returns, with the derivation echoed back.

    `verdict` is the typed `Rewind`. `rewind_to_turn` is the minted anchor index
    (only ever `checkpoint.turn_index`, and only on `REWIND`; `-1` otherwise).
    `transcript_digest` is echoed so the consumer truncates to a kernel-stamped
    anchor, never an agent-claimed turn. `dropped_turns` are the indices STRICTLY
    AFTER `rewind_to_turn` (the dead-end turns to excise — pure subtraction).
    `no_good_note` is the byte-clean annotation. `reason` is the operator one-liner
    (kernel-authored — a refusal is legitimate kernel speech, docs/82). `to_dict` is
    the `--json` shape (the `ResumePlan.to_dict` idiom).
    """

    verdict: Rewind
    reason: str
    rewind_to_turn: int = -1
    transcript_digest: str = ""
    dropped_turns: tuple[int, ...] = ()
    no_good_note: NoGoodNote = field(default_factory=NoGoodNote)

    @property
    def is_actionable(self) -> bool:
        return self.verdict.is_actionable

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "rewind_to_turn": self.rewind_to_turn,
            "transcript_digest": self.transcript_digest,
            "dropped_turns": list(self.dropped_turns),
            "no_good_note": self.no_good_note.to_dict(),
        }


# ───────────────────────────── the pure boundary helper ──────────────────────
def digest_turn(turn_bytes: "bytes | str") -> str:
    """Hex digest of one turn's bytes — the kernel's hash, the rewind anchor's author.

    A TINY pure helper (no I/O — it hashes bytes the caller already has in hand) the
    boundary uses to build a `TurnRef.digest` and the SUSPEND checkpoint's
    `transcript_digest`. Kept in the pure module (not the boundary reader) because it
    is the DEFINITION of the anchor's identity: the digest's byte-author is THIS hash
    of the turn, not the judged agent, which is exactly what makes the checkpoint
    non-forgeable (the `evidence.believe_under_floor` framing, on the conversation
    axis). `sha256`, hex, UTF-8 for a `str` input.
    """
    if isinstance(turn_bytes, str):
        turn_bytes = turn_bytes.encode("utf-8")
    return hashlib.sha256(turn_bytes).hexdigest()


def _digests_match(a: str, b: str) -> bool:
    """True iff two hex digests match (case-insensitive, whitespace-tolerant, non-empty).

    An empty digest on EITHER side never matches — a checkpoint with no digest, or a
    turn the boundary couldn't hash, is not a valid anchor (fail-closed → UNANCHORED).
    """
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return False
    return a == b


# ───────────────────────────── the no-good note builder ──────────────────────
def build_no_good_note(
    tokens: "tuple[VerdictToken, ...] | list[VerdictToken]" = (),
    env_excerpt: Optional[EnvExcerpt] = None,
    *,
    registry: RewindTokenRegistry = BASE_REWIND_TOKENS,
) -> NoGoodNote:
    """Assemble a `NoGoodNote` from ONLY (a) closed verdict tokens and (b) a floor-gated env excerpt.

    The docs/164 §6 byte contract, enforced STRUCTURALLY:

      * (a) Every token must be a `VerdictToken` whose `kind` is a member of
        `registry` — an unknown kind is DROPPED here (it would be un-renderable, so it
        carries no kernel-authored bytes anyway; dropping it is the safe no-op rather
        than minting a note that would later raise). There is no free-form `str`
        parameter for a token's text: the rendered string comes from the registry's
        kernel-owned template over the token's structured payload.
      * (b) The env excerpt ATTACHES iff its `accountability` is non-`AGENT_AUTHORED`
        (`EnvExcerpt.attaches`) — the `evidence.believe_under_floor` framing. An
        `AGENT_AUTHORED` excerpt (or None) is filtered to None: recorded-but-not-
        attached, the floor's safe-direction no-op. So the F0 Traceback (env-authored)
        attaches, but a generated critique the agent could have authored cannot.

    There is NO `critique` / `advice` / `message` parameter anywhere on this path —
    that absence IS the lock. PURE — no I/O; it only filters + folds pre-built values.
    """
    kept: list[VerdictToken] = []
    for t in tokens:
        if not isinstance(t, VerdictToken):
            # A non-token (a bare string smuggled in, a duck-typed look-alike) is
            # dropped — the note never reads a foreign object's bytes, so no
            # fabricated prose can sneak through a wrong type (the `gather_evidence`
            # fail-safe posture, restated for note assembly).
            continue
        if registry.is_known(t.kind):
            kept.append(t)
        # An unknown kind is dropped (un-renderable → no un-forged bytes to carry).

    # The env excerpt crosses the floor ONLY on a non-forgeable rung. None / forgeable
    # → not attached (recorded nowhere, the safe no-op). This is the one place an
    # arbitrary `str` could enter the note — and it is gated by who AUTHORED the bytes,
    # never by content, so a model-authored string tagged AGENT_AUTHORED is filtered.
    attached = env_excerpt if (env_excerpt is not None and env_excerpt.attaches) else None

    return NoGoodNote(tokens=tuple(kept), env_excerpt=attached, registry=registry)


# ───────────────────────────── the pure verdict ──────────────────────────────
def rewind_plan(
    turns: "tuple[TurnRef, ...] | list[TurnRef]",
    checkpoint: SuspendCheckpoint,
    fire: FireVerdict,
    *,
    verdict_tokens: "tuple[VerdictToken, ...] | list[VerdictToken]" = (),
    env_excerpt: Optional[EnvExcerpt] = None,
    policy: RewindPolicy = DEFAULT_REWIND_POLICY,
    registry: RewindTokenRegistry = BASE_REWIND_TOKENS,
) -> RewindPlan:
    """Compute the conversation-rewind verdict. PURE — no I/O (docs/164 F1.5).

    The fold (docs/164 §6):

      1. **NO_REWIND first — the loop terminates on GROUND TRUTH.** If `fire` is not a
         ground-truth stop signal (`fire.should_surface` is False — a `CONVERGING` /
         `RESUMABLE` / `COMPLETE` / `INSUFFICIENT` fire), the loop continues: NO_REWIND,
         the transcript untouched. The cap is on the ground-truth verdict, never the
         agent's "I'm close" (the §6 loop-termination litmus). The note is empty here —
         there is nothing dead-ended to annotate.

      2. **UNANCHORED — rewind to a MINTED anchor or refuse.** The fire IS a stop
         signal, but the rewind target must be a checkpoint the KERNEL stamped. Refuse
         (UNANCHORED) when:
           * the checkpoint is absent (no SUSPEND minted one), OR
           * `policy.require_matching_digest` and the live turn at
             `checkpoint.turn_index` does NOT digest to `checkpoint.transcript_digest`
             (the agent or a successor rewrote history under the checkpoint, or the
             index names no live turn).
         This is the floor framing (`believe_under_floor`) on the conversation axis:
         the digest's byte-author is the kernel's hash at SUSPEND, not the agent, so a
         mismatch is a floor failure. The kernel rewinds to NOTHING (`rewind_to_turn`
         = -1) rather than to a turn the agent claims — the §6 "never rewind to a
         STEP_CLAIMED SHA / an un-stamped turn" litmus, conversation-side. The no-good
         note is still BUILT (the verdict + env bytes are valid evidence the operator
         wants), but no truncation is proposed.

      3. **REWIND — a minted, matching anchor + a ground-truth stop.** Truncate to
         `checkpoint.turn_index`, excise `dropped_turns` (the indices STRICTLY AFTER
         the anchor — pure subtraction, removes context, adds none), and re-enter with
         the no-good note (closed verdict tokens + the floor-gated env excerpt ONLY).

    The verdict is ADVISORY (docs/99 / docs/164 P1.5): it MINTS the belief (this
    checkpoint is a valid rewind anchor; these turns are dead ends) and PROPOSES the
    truncation; the act of truncating the transcript is the consumer's — "the host
    owns the transcript." The kernel never mutates it.
    """
    # The note is built the same way in every branch — from ONLY closed verdict tokens
    # + a floor-gated env excerpt. Building it unconditionally keeps the byte contract
    # in one place (there is no branch where a different note-builder could leak prose).
    note = build_no_good_note(verdict_tokens, env_excerpt, registry=registry)

    # 1. NO_REWIND — the fire is not a ground-truth stop signal. The loop continues.
    if not fire.should_surface:
        return RewindPlan(
            verdict=Rewind.NO_REWIND,
            reason=(
                f"no rewind — the fire verdict ({fire._label()}) is not a ground-truth "
                f"stop signal (DIVERGED / THRASHING / STARVED); the loop continues, the "
                f"transcript is untouched"
            ),
            rewind_to_turn=-1,
            transcript_digest="",
            dropped_turns=(),
            no_good_note=NoGoodNote(registry=registry),  # nothing dead-ended to annotate
        )

    # 2. UNANCHORED — there IS a stop signal, but the anchor is not kernel-minted.
    if not checkpoint.present:
        return RewindPlan(
            verdict=Rewind.UNANCHORED,
            reason=(
                f"unanchored — {fire._label()} fired, but no conversation checkpoint was "
                f"minted at SUSPEND; refusing to rewind to a turn the kernel did not "
                f"stamp (the §6 minted-anchor floor — surface the no-good, propose no "
                f"truncation)"
            ),
            rewind_to_turn=-1,
            transcript_digest="",
            dropped_turns=(),
            no_good_note=note,
        )

    # Find the live turn at the checkpoint's index (the boundary handed us its digest).
    live = next((t for t in turns if t.index == checkpoint.turn_index), None)
    digest_ok = (
        live is not None
        and _digests_match(live.digest, checkpoint.transcript_digest)
    )
    if policy.require_matching_digest and not digest_ok:
        why = (
            "no live turn at the checkpoint's index"
            if live is None
            else "the live turn's digest does not match the stamp the kernel minted"
        )
        return RewindPlan(
            verdict=Rewind.UNANCHORED,
            reason=(
                f"unanchored — {fire._label()} fired, but {why} "
                f"(checkpoint turn {checkpoint.turn_index}, digest "
                f"{(checkpoint.transcript_digest or '∅')[:12]}); the agent or a successor "
                f"rewrote history under the checkpoint. Refusing to rewind to a turn the "
                f"kernel did not stamp (the §6 non-forgeable-anchor floor)"
            ),
            rewind_to_turn=-1,
            transcript_digest="",
            dropped_turns=(),
            no_good_note=note,
        )

    # 3. REWIND — a minted, matching anchor + a ground-truth stop. Subtraction-only:
    #    drop every turn STRICTLY AFTER the anchor (removes context, adds none).
    dropped = tuple(sorted(t.index for t in turns if t.index > checkpoint.turn_index))
    return RewindPlan(
        verdict=Rewind.REWIND,
        reason=(
            f"rewind to minted checkpoint turn {checkpoint.turn_index} (digest "
            f"{checkpoint.transcript_digest[:12]}) — {fire._label()} is a ground-truth "
            f"dead end; excising {len(dropped)} dead-end turn(s) and re-entering with a "
            f"no-good note ({len(note.tokens)} verdict token(s)"
            f"{', + env excerpt' if note.env_excerpt is not None else ''})"
        ),
        rewind_to_turn=checkpoint.turn_index,
        transcript_digest=checkpoint.transcript_digest,
        dropped_turns=dropped,
        no_good_note=note,
    )

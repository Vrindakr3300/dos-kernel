"""DI — the dangling-intent verdict: *did the agent stop right after admitting unfinished work?*

docs/150 (the steelman of docs/149). docs/149 measured that **~92 % of real EnterpriseOps-Gym
failures are "the action never happened"** — Premature Completion, the model declaring done and
stopping with required rows unwritten — and concluded DOS could not own it byte-cleanly, because
the `completion` verdict's inputs (`declared − verified`) are both forgeable here (no git ancestry,
no env-authored per-step checkpoint, the declared scope is the agent's own). That conclusion is
**cracked, not overturned**, by one observation docs/149 §3 over-generalized past:

> docs/149 wrote "`verified` = the agent's own narration → forgeable." That is true **only toward
> "I'm done."** A self-report of *incompleteness* — "Now I need to allocate the personnel…" right
> before stopping — is an **admission against interest**: no premature-completing agent benefits
> from falsely confessing unfinished work. It is the one self-report class DOS *already* believes
> — `resume` keeps a `STEP_CLAIMED`-but-unverified step IN the residual (it trusts the agent only
> when the agent admits *more* work, never when it claims *less*). So the against-interest axis is
> not forgeable-in-favor, and a verdict over it is not the §5a mirror-verifier.

The byte-clean question (over two surfaces, one with an env-authored corroborator)
==================================================================================

  > Does the agent's LAST authored turn contain a fixed, task-INDEPENDENT
  > committed-future-intent discourse marker ("I need to", "I still have to", "next I will",
  > "I was unable to", "I cannot … yet") — AND did NO env-authored tool result land after it?

It is **not a planner**: the cue set is an English-discourse-marker grammar writable having read
*zero task prompts*. The litmus the verb→tool-table mechanisms FAILED (they had to read *this
task's* prose to know "allocate" → `add_group_member` not `add_new_user_group`): this verdict is
**invariant under task-swap**. It never reads a domain noun, never enumerates a step-list, never
decides what the agent *should* do next. It does not even need to know what the unfinished step
*is* — only that a standing-obligation envelope was emitted at the moment of stopping. Key on the
first-person-future-intent *envelope*, NEVER on content ("manager", "members", "allocate"); the
instant it keys on a domain noun it has become a planner and is dead (the load-bearing knife-edge).

It is **not a satisfaction predicate**: it reads no DB, never asks "is the work correct / enough".
And the agent-authored surface (the narration) is corroborated by an **env-authored absence** — the
gym writes a tool `result` only when a tool actually executed, so "no result after the terminal
turn" is a non-forgeable byte (the `precursor_gate` existence-of-a-result rung). That corroborator
drives the dominant false-positive (named-it-then-did-it) toward zero by construction: a marker
followed by a real subsequent call is ABSTAIN, not a fire.

The honest forgeable hole, named (the `arg_provenance` discipline)
==================================================================

This reads ONE agent-authored surface, so it is **forgeable by SUPPRESSION**: an agent trained
against the gate simply stops narrating "I need to…" and the signal goes quiet. Acceptable ONLY
because suppression degrades to **false-DONE → baseline** (the safe fail-toward-done direction),
and because the value is on *today's* uncoached cheap models that narrate their abandoned plans —
not on an adversary optimizing against the gate. It catches the **honest-but-premature** stopper;
it is blind to the **silent** stopper (stops with no narration — the majority of the measured 92 %)
and to the **adversarial** one. That is a forgeable hole stated plainly, exactly as
`arg_provenance` names its false-SUPPORTED miss. The recall ceiling is the *narrating* subset —
measured ~15-30 % of the missing-row failures (`replay_dangling.py`).

Advisory only — it never supplies the plan (DETECT, not FIX)
============================================================

The verdict maps to `Intervention.WARN` and nothing harder (the type has no other rung). On a fire
the consumer re-surfaces **the agent's own abandoned sentence** ("your final message says you still
needed to X, and no tool ran after — continue or confirm"). It authors **no directive and no step**
— so it cannot inject the foreign instruction that caused the −9 pp derailment (docs/143: a
verifier-authored directive on a correct path). Its worst case is replaying a sentence the agent
already wrote (a one-turn iteration tax), never a derailment. It does not and structurally cannot
tell the model *what* call to make — that is the +14-35 pp planner lever, forfeit by doctrine. So
the claim is exactly "DOS can byte-cleanly DETECT a slice of premature completion," never "DOS can
fix it."

⚓ Pure kernel, I/O on the edge (the dos idiom — mirrors `claim_extract.extract_claims`,
`liveness.classify`, `precursor_gate.classify_call`): `classify_stop(StopEvidence, policy) ->
DanglingVerdict` is a frozen datum in, a frozen verdict out. The boundary reader gathers the
terminal narration (`claim_extract.assistant_text_from_transcript`) and counts env-authored tool
results after it AT THE CALL EDGE; the kernel never reads a file, a clock, or a DB.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# The typed verdict — two-valued (the EvidenceStance REFUTED/NO_SIGNAL shape).
# ---------------------------------------------------------------------------
class Dangling(str, enum.Enum):
    """The dangling-intent verdict — two states. `str`-valued so it round-trips a CLI token / JSON.

      DANGLING_INTENT — the agent's last authored turn declared a committed-future obligation AND
                        no env-authored tool result landed after it. The one actionable rung — a
                        consumer re-surfaces the agent's own sentence (WARN). NOT a claim the work
                        is incomplete in truth — only that the agent SAID so and then stopped.
      ABSTAIN         — the fail-safe zero: no future-intent marker in the terminal turn, OR a real
                        tool result followed it (the agent named a step and then DID act), OR the
                        cue set is empty. Honest no-signal; never a block, always fail-toward-done.
    """

    DANGLING_INTENT = "DANGLING_INTENT"
    ABSTAIN = "ABSTAIN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# ---------------------------------------------------------------------------
# The cue grammar — task-INDEPENDENT first-person-future-intent markers.
# ---------------------------------------------------------------------------
# Each cue is a regex matched casefold against the terminal narration. They key ONLY on the
# first-person committed-future / unfulfilled-intent ENVELOPE — never a domain noun. This is the
# difference between a fixed grammar (writable having read zero task prompts) and a planner (per-task
# prose reasoning). A host may override/extend via `dos.toml [dangling.cues]` (config-as-data); an
# EMPTY set ABSTAINs everything (fail-toward-done). Kept deliberately conservative: a missed marker
# is a safe ABSTAIN; the bias is to under-fire (the `arg_provenance` posture).
DEFAULT_CUES: tuple[str, ...] = (
    r"\bi (?:still )?need to\b",
    r"\bi (?:still )?have to\b",
    r"\bi (?:will|'ll) (?:now |then )?(?:need to |have to |proceed to )",
    r"\bnext,? i (?:will|'ll|need|have|should)\b",
    r"\bi should (?:now |next )?(?:proceed|continue|identify|create|add|assign|update)\b",
    r"\bi was unable to\b",
    r"\bi (?:have|haven't|had) not (?:yet )?(?:been able|completed|finished|done)\b",
    r"\bi cannot .{0,40}\byet\b",
    r"\b(?:still|yet) to be (?:done|completed|added|assigned|created)\b",
    r"\bremains? to be (?:done|completed|added|assigned)\b",
    r"\bto (?:do|complete|finish) this,? i (?:need|will|have|must)\b",
    r"\bnow,? to\b.{0,40}\bi (?:need|will|must|have to)\b",
)

# Words that, when they immediately wrap a cue, mark it as a COMPLETED report, not an open one —
# "I needed to X, which I have now done" must NOT fire. A conservative negative guard (the cue
# itself is the primary signal; this only suppresses an obvious past-tense-resolved phrasing).
_RESOLVED_GUARD_RE = re.compile(
    r"\b(?:have|has|already|now) (?:been )?(?:done|completed|finished|created|added|assigned|set up)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DanglingPolicy:
    """The cue grammar + knobs — mechanism is kernel, the cue list is config (the `ProvenancePolicy`
    / `StreamPolicy` seam). Defaults GENERIC; a host declares its own in `dos.toml [dangling]`.

      cues          — the committed-future-intent marker regexes (casefold). EMPTY → ABSTAIN-all
                      (the fail-toward-done floor: no cues declared = no accusation possible).
      tail_chars    — only the LAST `tail_chars` of the terminal narration are scanned (an open
                      obligation declared in the MIDDLE of a long turn that then continues to act is
                      not a *terminal* dangle; the signal is "ended ON the admission"). 0 = whole turn.
    """

    cues: tuple[str, ...] = DEFAULT_CUES
    tail_chars: int = 600

    def __post_init__(self) -> None:
        if self.tail_chars < 0:
            raise ValueError("tail_chars must be >= 0")


DEFAULT_POLICY = DanglingPolicy()


# ---------------------------------------------------------------------------
# Frozen input — the pure datum the boundary gathers and hands in.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StopEvidence:
    """Everything `classify_stop` needs, gathered by the CALLER at the stop event. No I/O inside.

      final_turn_text     — the agent's LAST authored narration (the terminal `ai_message` /
                            `model_response`), read at the boundary by
                            `claim_extract.assistant_text_from_transcript`. Agent-authored — but
                            distrusted on the AGAINST-INTEREST axis only.
      results_after_turn  — the count of env-authored tool `result` entries that landed AFTER the
                            terminal turn. The ENV-AUTHORED corroborator: the gym writes a result
                            only when a tool actually executed, so >0 means the agent named a step
                            and then ACTED → ABSTAIN (not a terminal dangle). Defaults 0 (the common
                            stop case: the last turn is narration with nothing after it).
    """

    final_turn_text: str
    results_after_turn: int = 0

    def __post_init__(self) -> None:
        if self.results_after_turn < 0:
            raise ValueError("results_after_turn must be >= 0")


# ---------------------------------------------------------------------------
# Frozen verdict — advisory only.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DanglingVerdict:
    """The verdict `classify_stop` returns — typed state + the matched cue for the WARN string.

    `matched_cue` is the offending marker text (the substring that fired) so the consumer's WARN can
    quote the agent's OWN words back ("your final message says: '<…>' — and no tool ran after").
    `reason` is the one-line operator summary. Advisory: never raises, never blocks the stop.
    """

    verdict: Dangling
    matched_cue: str
    reason: str

    @property
    def is_dangling(self) -> bool:
        return self.verdict is Dangling.DANGLING_INTENT

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "matched_cue": self.matched_cue,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# The pure verdict.
# ---------------------------------------------------------------------------
def _find_cue(text: str, policy: DanglingPolicy) -> str:
    """The first committed-future-intent cue that matches the (tail of the) text, or "" if none.
    Suppressed when an obvious resolved-guard phrase wraps it (named-it-then-did-it in one turn)."""
    if not policy.cues:
        return ""
    scan = text if policy.tail_chars == 0 else text[-policy.tail_chars:]
    low = scan.casefold()
    for cue in policy.cues:
        m = re.search(cue, low)
        if not m:
            continue
        s, e = m.start(), m.end()
        # The resolved-guard is checked ONLY within the cue's OWN sentence — clipped at the nearest
        # sentence terminator on each side. This is the "I needed to X, which I have now done"
        # same-clause shape; it must NOT reach back into a PRIOR completed sentence ("the group has
        # been created. Now I need to allocate…") and wrongly suppress a genuine LATER dangle (the
        # real-example bug). The cue itself is the primary signal; this only kills an obvious
        # in-clause past-tense resolution.
        sent_start = max((scan.rfind(c, 0, s) for c in ".!?\n"), default=-1) + 1
        nxt = [scan.find(c, e) for c in ".!?\n"]
        nxt = [i for i in nxt if i >= 0]
        sent_end = min(nxt) + 1 if nxt else len(scan)
        sentence = scan[sent_start:sent_end]
        if _RESOLVED_GUARD_RE.search(sentence):
            continue
        return scan[s:e].strip()
    return ""


def classify_stop(
    ev: StopEvidence, policy: DanglingPolicy = DEFAULT_POLICY
) -> DanglingVerdict:
    """Classify whether the agent stopped right after admitting unfinished work. PURE — no I/O.

    The ladder, top to bottom:
      1. ABSTAIN — a real tool result landed AFTER the terminal turn (`results_after_turn > 0`): the
         agent named a step and then ACTED, so this is not a terminal dangle. The env-authored
         corroborator wins first — it is the non-forgeable byte that kills the named-it-then-did-it
         false positive.
      2. ABSTAIN — no committed-future-intent cue in the terminal narration (or an empty cue set):
         the agent did not admit unfinished work. The fail-toward-done floor.
      3. DANGLING_INTENT — a cue fired AND nothing executed after: the agent's own last words admit
         an open obligation and the run stopped. The one actionable rung (advisory WARN).

    Advisory: the verdict REPORTS; the consumer re-surfaces the agent's own sentence (never a
    directive, never a forced continue — the docs/143 −9 pp channel is unreachable by type).
    """
    # 1. the env-authored corroborator first: acted-after → not a terminal dangle.
    if ev.results_after_turn > 0:
        return DanglingVerdict(
            verdict=Dangling.ABSTAIN,
            matched_cue="",
            reason=(
                f"{ev.results_after_turn} tool result(s) landed after the terminal turn — the "
                f"agent named a step and then acted, not a dangling stop"
            ),
        )
    cue = _find_cue(ev.final_turn_text or "", policy)
    if not cue:
        return DanglingVerdict(
            verdict=Dangling.ABSTAIN,
            matched_cue="",
            reason="no committed-future-intent marker in the terminal turn — clean stop (or no cues)",
        )
    return DanglingVerdict(
        verdict=Dangling.DANGLING_INTENT,
        matched_cue=cue,
        reason=(
            f"the terminal turn admits an open obligation ({cue!r}) and no tool ran after — the "
            f"agent stopped right after saying it still had work (an admission against interest)"
        ),
    )

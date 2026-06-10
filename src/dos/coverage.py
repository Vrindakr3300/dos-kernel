r"""coverage — the cheap, NON-GIT fan-out coverage fold for a self-reporting fleet (docs/197 §7(1)).

> **An HONEST AGGREGATOR, not a label factory.** It folds N already-adjudicated
> `result_state` terminal-state verdicts (each minted by `verify-result`, the
> §7(1) keystone) against the workflow-DECLARED expected count N, into ONE coverage
> headline + a per-class breakdown. It mints **ZERO** new ground-truth labels —
> every per-worker DEAD/HEALTHY fact it counts was already decided by
> `result_state.classify_terminal`; this batches them into one coverage answer the
> synthesizer can read. That honesty is load-bearing: re-counting the N
> already-adjudicated verdicts as "N new labels" would be the consistency-not-
> grounding sin (the docs/179 design law). The data-multiplier in the docs/179 set
> is `firing_label` (it JOINS a firing to a git outcome to DECIDE a previously-unknown
> label); `coverage` is the `fleet_roll` sibling — a fold over an already-labeled set.

What it IS — the win that is real (and narrow)
==============================================

The dominant ultracode subagent is a **pure-text research/read worker that produces
no git commits**, so `completion.classify` (which folds `declared − git-ancestry-
verified` over an `intent_ledger`) returns INDETERMINATE for it — there is no ledger.
The only fossil a read-only worker leaves is its transcript's terminal record. So
`coverage` is the form of "is the fan-out actually done?" that works on the cheap
rung `result_state` already provides, and it earns its keep two narrow, defensible
ways:

  1. It makes the denominator **`declared` (a separate, workflow-authored integer)**,
     NOT `len(returns)`. The pervasive laundering bug is `failed = N − survivors.length`
     and `results.filter(Boolean)` (89/114 real scripts): a harness-synthesized death
     returns a non-null error string that survives the filter, so a 4-of-7 fan-out is
     silently banked as 7/7. Because `declared` is independent of the survivor list, a
     short survivor list CANNOT read as FULL here — the laundering is structurally
     impossible.
  2. It **surfaces a count the prior pipeline discarded** — `unaccounted` (declared
     slots that produced neither a HEALTHY return nor a witnessed death) — and hands
     the whole partition to the synthesizer as legible text, instead of `log()`-ing it
     and throwing it away (today's behavior, the follow-up #1 premise).

Both are "better denominator hygiene," not a new per-datum label. Stated honestly so
the module ships in agreement with docs/179, not in contradiction with it.

The fold-mints-data law (docs/179) — applied, and the honest ruling
===================================================================

The two facts the fold touches: **declared N** (workflow-authored) and the **multiset
of `result_state` terminal-states** (harness-authored, via the `model=='<synthetic>'`
gate). They were not compared at the fold before — but the comparison is *arithmetic*
(`healthy == declared?`), and it decides NO new truth value about any worker: each
worker's DEAD/HEALTHY was already adjudicated by `result_state`. So this is the
`fleet_roll` case (fold an already-labeled set → one headline + breakdown, 0 new
labels), NOT the `firing_label` case (join two facts to DECIDE an unknown label). The
`unaccounted`/`absent` surfacing is exactly what `fleet_roll.absent` does without
claiming to mint data. See [[project-dos-fold-mints-data-law]].

The byte-author law / advisory floor / reuse notes
==================================================

The `healthy` count is grounded TRANSITIVELY: it derives from `result_state`'s
`model=='<synthetic>'` gate, a byte the Claude Code HARNESS — not the worker —
authored, so a worker cannot forge its slot HEALTHY when the harness killed it
(the docs/138 grounding-not-consistency invariant). BUT the pure core can only be as
grounded as the verdicts handed in: if a caller asserts terminal-states directly
(the CLI `--states` path) instead of letting `coverage_from_transcripts` run
`result_state.verify_transcript`, the count is **workflow-asserted, not harness-
grounded**. The CLI stamps that distinction (`grounded: false` vs `true`) so a
consumer knows whether the denominator was re-grounded; the pure `classify_coverage`
counts whatever states it is given and never re-grounds (it is pure — no I/O).

ADVISORY (PDP, not PEP — the docs/197 §6.5 / docs/99 line): it REPORTS a coverage
verdict + a synthesizer-legible `prompt_line`; it never re-runs a dead worker
(re-dispatch of the dead slot's OWN unit is the conductor's act) and never re-prompts
the synthesizer mid-plan (the −9 pp DEFER derail). It also does NOT judge the
CORRECTNESS of a HEALTHY return — a 7/7 FULL coverage of seven WRONG answers is still
FULL; coverage certifies the denominator, never the values. Whether a healthy finding
is true is `effect_witness` / `believe_under_floor`'s job (the witness-routing rung,
docs/197 §7(2)).

⚓ Kernel discipline (the litmus): a PURE verdict + a boundary reader. It imports only
the sibling kernel module `result_state` (+ stdlib) — NOT `resume`/`intent_ledger`/
`scope_source` (those are `completion`'s git-ledger imports; folding them in would drag
git concepts into the pure-text path). Names no host, resolves nothing against
`__file__`, takes no lease. The transcript I/O is the caller's boundary
(`coverage_from_transcripts`, which delegates to `result_state.verify_transcript`),
exactly the `liveness.classify` over `git_delta` shape, one rung over. It mirrors
`completion`'s SHAPE (a `str`-enum verdict + frozen `*Verdict` + `to_dict` +
`fraction`-style legibility), but shares no body — a new leaf, the third sibling of
the "is the fan-out done, or only declared done?" family.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional, Sequence, Union

from dos.result_state import ResultStateVerdict, TerminalClass, TerminalState


# ───────────────────────────── the coverage verdict ───────────────────────────
class Coverage(str, enum.Enum):
    """The typed coverage verdict — five states, mutually exclusive.

    `str`-valued so it round-trips a `--json` token / exit-code map without a lookup
    table (the `Completion` / `Resume` / `Liveness` idiom). The asymmetry maps to the
    consumer's action:

      * FULL        — every declared worker returned a real result; fold all.
      * UNDERFILLED — a sub-quorum returned (0 < healthy < declared); fold WITH a
                      caveat, count the gap in the denominator.
      * STARVED     — nothing real came back (healthy == 0, declared > 0); do NOT
                      synthesize — there is no real material to fold.
      * OVERFILLED  — more healthy returns than declared (healthy > declared): a
                      dispatch/glob bug (a re-dispatch double-counted, a stale glob).
                      Surfaced, never silently reported as FULL with `fraction > 1`.
      * EMPTY       — nothing was fanned out (declared == 0). Degenerate, NOT an error.
    """

    FULL = "FULL"
    UNDERFILLED = "UNDERFILLED"
    STARVED = "STARVED"
    OVERFILLED = "OVERFILLED"
    EMPTY = "EMPTY"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def foldable(self) -> bool:
        """True iff there is real material to synthesize from (everything but STARVED).

        OVERFILLED is foldable (there ARE healthy results — too many, but real); the
        caveat is about the count mismatch, not the absence of material."""
        return self is not Coverage.STARVED

    @property
    def should_caveat(self) -> bool:
        """True iff the synthesis prompt MUST carry a coverage caveat (not FULL/EMPTY)."""
        return self in (Coverage.UNDERFILLED, Coverage.STARVED, Coverage.OVERFILLED)


@dataclass(frozen=True)
class CoveragePolicy:
    """Knobs for the coverage verdict — policy, not mechanism (the `ResumePolicy` split).

    ``min_quorum`` is a LEGIBILITY-only flag: when set, `to_dict` reports
    ``quorum_met = healthy/declared >= min_quorum``. It NEVER changes the verdict —
    "is 4/7 acceptable?" is host policy the synthesizer/conductor decides; coverage
    only reports the fraction + an advisory flag. FULL stays strict equality. The
    default is generic (no host tuning); a workspace could declare its own in a future
    `dos.toml [coverage]` seam (like the planned `[liveness]`/`[completion]`).
    """

    min_quorum: Optional[float] = None


DEFAULT_COVERAGE_POLICY = CoveragePolicy()


@dataclass(frozen=True)
class ReturnState:
    """One declared worker slot's witnessed terminal-state — the minimal datum the fold
    counts. `state` is a `result_state.TerminalState` (the rung coverage trusts);
    `agent_id` is optional legibility only (a per-slot breakdown). Nothing else about
    the return is load-bearing here — the CORRECTNESS of a HEALTHY return is
    `effect_witness`'s job, not coverage's."""

    state: TerminalState
    agent_id: str = ""


@dataclass(frozen=True)
class CoverageVerdict:
    """The single verdict `classify_coverage` returns, with the partition echoed back.

    `declared` is the workflow-authored denominator (independent of the survivor list —
    the laundering fix). `healthy`/`dead`/`unreadable` partition the WITNESSED slots;
    `unaccounted` is the declared slots that produced no witnessed verdict at all (the
    surfaced-discarded count). `dead_classes` is the `result_state.TerminalClass`
    breakdown of the deaths — populated only when full `ResultStateVerdict`s were
    counted (the harness-grounded path), so the reason text can say "rate-limit" vs
    "quota" honestly; empty when bare `TerminalState`s were counted. `to_dict` is the
    `--json` shape (incl. the synthesizer-legible `prompt_line`)."""

    state: Coverage
    declared: int
    healthy: int
    dead: int
    unreadable: int
    reason: str
    dead_classes: tuple[tuple[str, int], ...] = ()
    quorum_met: Optional[bool] = None

    @property
    def unaccounted(self) -> int:
        """Declared slots that produced no witnessed verdict (declared − the witnessed
        partition). Floored at 0 — an over-fill is reported via OVERFILLED, never as a
        negative `unaccounted`."""
        return max(0, self.declared - self.healthy - self.dead - self.unreadable)

    @property
    def fraction(self) -> Optional[float]:
        """healthy / declared — the coverage fraction, or None when nothing was declared.
        A legibility aid; never load-bearing for the verdict. May exceed 1.0 only in the
        OVERFILLED case (reported so the dispatch bug is visible, not hidden)."""
        return (self.healthy / self.declared) if self.declared else None

    @property
    def prompt_line(self) -> str:
        """The deterministic sentence a workflow interpolates VERBATIM into its synthesis
        prompt — the whole point of the module (the laundering fix is legible coverage,
        not a `log()`-ed one). Generated from the REAL `(dead, unreadable, unaccounted)`
        partition (Fix 2/3): it NEVER asserts a death that was not witnessed — an
        unreadable slot is reported as "could not be read", a missing slot as "did not
        return a transcript", and only `dead`/`dead_classes` license the word "died"."""
        d = self.declared
        if self.state is Coverage.EMPTY:
            return "No workers were fanned out (declared == 0); there is nothing to fold."
        if self.state is Coverage.FULL:
            return (f"All {self.healthy} of {d} fan-out workers returned a real result; "
                    f"this is full coverage.")
        # Build the gap clause from the actual partition, never a hardcoded "died".
        parts = []
        if self.dead:
            cls = self._dead_class_phrase()
            parts.append(f"{self.dead} died on a harness-authored terminal{cls}")
        if self.unreadable:
            parts.append(f"{self.unreadable} could not be read (NOT a witnessed death)")
        if self.unaccounted:
            parts.append(f"{self.unaccounted} did not return a transcript")
        gap = "; ".join(parts) if parts else "the missing slots are unaccounted"
        if self.state is Coverage.STARVED:
            # 0 healthy — but the reason text must reflect WHY (deaths vs unreadable vs
            # missing), because the right operator action differs (re-dispatch a death;
            # fix the read path for unreadable; locate the transcripts for missing).
            return (f"COVERAGE FAILURE: 0 of {d} fan-out workers returned a real result "
                    f"({gap}). There is no real material to synthesize. Do NOT fabricate "
                    f"findings; report the fan-out as failed and act on the gap above "
                    f"(re-dispatch deaths; fix the read path for unreadable; locate "
                    f"missing transcripts).")
        if self.state is Coverage.OVERFILLED:
            return (f"COVERAGE ANOMALY: {self.healthy} workers returned a real result but "
                    f"only {d} were declared — more results than expected (a re-dispatch "
                    f"double-count or a stale transcript glob). Treat the count as "
                    f"unreliable and reconcile the dispatch before trusting coverage.")
        # UNDERFILLED
        return (f"COVERAGE CAVEAT: only {self.healthy} of {d} fan-out workers returned a "
                f"real result ({gap}). Treat the findings below as a SUB-QUORUM SAMPLE "
                f"({self.healthy}/{d}), not an exhaustive survey; do not state or imply "
                f"full coverage, and flag the gap above.")

    def _dead_class_phrase(self) -> str:
        """A short ' (rate-limit/quota/...)' phrase from `dead_classes`, or '' when the
        deaths were counted from bare TerminalStates (no class detail). The ONLY license
        to name a death cause — never asserted from an unreadable/missing slot."""
        if not self.dead_classes:
            return ""
        names = "/".join(c.lower().replace("_", "-") for c, _ in self.dead_classes)
        return f" ({names})"

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "declared": self.declared,
            "healthy": self.healthy,
            "dead": self.dead,
            "unreadable": self.unreadable,
            "unaccounted": self.unaccounted,
            "fraction": (round(self.fraction, 4) if self.fraction is not None else None),
            "foldable": self.state.foldable,
            "should_caveat": self.state.should_caveat,
            "dead_classes": [list(c) for c in self.dead_classes],
            "quorum_met": self.quorum_met,
            "prompt_line": self.prompt_line,
            "reason": self.reason,
        }


# ───────────────────────────── the pure fold ──────────────────────────────────
_Return = Union[ReturnState, ResultStateVerdict, TerminalState]


def _as_state(r: _Return) -> tuple[TerminalState, Optional[TerminalClass]]:
    """Coerce one return element to `(TerminalState, TerminalClass | None)`. PURE.

    Accepts a bare `TerminalState`, a full `ResultStateVerdict` (carries the class
    detail), or a `ReturnState` wrapper. Any other type raises `TypeError` — the CLI
    maps it to a contract error (exit 2), never silently miscounts."""
    if isinstance(r, TerminalState):
        return (r, None)
    if isinstance(r, ResultStateVerdict):
        return (r.state, r.cls)
    if isinstance(r, ReturnState):
        return (r.state, None)
    raise TypeError(
        f"coverage: a return must be a TerminalState, ResultStateVerdict, or "
        f"ReturnState, not {type(r).__name__}"
    )


def classify_coverage(
    declared: int,
    returns: Sequence[_Return],
    policy: CoveragePolicy = DEFAULT_COVERAGE_POLICY,
) -> CoverageVerdict:
    """Fold the witnessed terminal-states against the declared count. PURE — no I/O.

    Counts each return's `result_state` terminal-state into `{healthy, dead,
    unreadable}` (an UNREADABLE return is LIVE-not-dead — the fail-safe floor
    inherited from `result_state`: a read fault must NEVER be counted a death), then
    decides the coverage state from `healthy` vs `declared`:

        declared <= 0                       → EMPTY        (nothing fanned out)
        healthy  >  declared                → OVERFILLED   (dispatch/glob bug)
        healthy  == declared (declared > 0) → FULL
        healthy  == 0        (declared > 0) → STARVED
        0 < healthy < declared              → UNDERFILLED

    `dead` is SYNTHETIC or EMPTY (both carry `result_state` `.dead == True`).
    `unaccounted` (declared slots with no witnessed verdict) falls out as
    `declared − healthy − dead − unreadable` and rides UNDERFILLED/STARVED.

    ADVISORY (docs/197 §6.5): it mints a coverage verdict; the consumer decides what to
    do (fold-with-caveat / don't-fold / re-dispatch). It never re-runs a worker and
    never judges the correctness of a healthy return (that is `effect_witness`).
    """
    healthy = dead = unreadable = 0
    cls_counts: dict[str, int] = {}
    for r in returns:
        state, cls = _as_state(r)
        if state is TerminalState.HEALTHY:
            healthy += 1
        elif state is TerminalState.UNREADABLE:
            unreadable += 1  # FAIL-SAFE: live, NOT a witnessed death.
        else:  # SYNTHETIC or EMPTY — result_state.dead == True.
            dead += 1
            if cls is not None and cls is not TerminalClass.NONE:
                cls_counts[cls.value] = cls_counts.get(cls.value, 0) + 1

    if declared <= 0:
        state, reason = Coverage.EMPTY, "nothing was fanned out (declared == 0)"
    elif healthy > declared:
        state = Coverage.OVERFILLED
        reason = (f"{healthy} healthy returns but only {declared} declared — more "
                  f"results than expected (a dispatch/glob bug)")
    elif healthy == declared:
        state, reason = Coverage.FULL, f"all {declared} declared worker(s) returned a real result"
    elif healthy == 0:
        state = Coverage.STARVED
        reason = f"0 of {declared} declared worker(s) returned a real result — nothing to synthesize"
    else:
        state = Coverage.UNDERFILLED
        reason = f"{healthy} of {declared} declared worker(s) returned a real result (sub-quorum)"

    quorum_met: Optional[bool] = None
    if policy.min_quorum is not None and declared > 0:
        quorum_met = (healthy / declared) >= policy.min_quorum

    return CoverageVerdict(
        state=state,
        declared=declared,
        healthy=healthy,
        dead=dead,
        unreadable=unreadable,
        reason=reason,
        dead_classes=tuple(sorted(cls_counts.items())),
        quorum_met=quorum_met,
    )


# ───────────────────────────── boundary I/O ───────────────────────────────────
def coverage_from_transcripts(
    declared: int,
    paths: Sequence[str],
    policy: CoveragePolicy = DEFAULT_COVERAGE_POLICY,
) -> CoverageVerdict:
    """Fold a list of subagent transcript paths into a coverage verdict. NOT pure.

    Reads each path via `result_state.verify_transcript` at the boundary (a missing /
    garbled file yields UNREADABLE, which counts LIVE — the fail-safe floor), then
    folds the verdicts with the pure `classify_coverage`. This is the HARNESS-GROUNDED
    path: coverage itself runs the `model=='<synthetic>'` classification, so the
    `healthy`/`dead` counts cannot be forged by a self-reporting workflow (the CLI
    stamps `grounded: true` for this path). The `git_delta`/`liveness` "I/O at the
    boundary, data to the pure core" discipline.
    """
    from dos import result_state
    verdicts = [result_state.verify_transcript(str(p)) for p in paths]
    return classify_coverage(declared, verdicts, policy)

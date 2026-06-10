"""completion — the live completion verdict: is the WHOLE job verifiably done? (docs/117).

The gap this closes
===================

Every agentic loop today terminates on **budget**, not on **done**. The proof is
in the kernel's own stop vocabulary: `loop_decide.StopReason` enumerates eleven
ways a loop can stop and **not one means "the work is finished"** — every terminal
path is a give-up (`ITERATION_CAP`), a circuit-break (`CONSECUTIVE_*`), an outage
(`RATE_LIMITED`/`LAUNCH_FAILED`), or a stall (`SPINNING`). `ITERATION_CAP` *is* the
"pass": the loop stops because it ran its rounds, and a human later runs
`dos resume` and discovers it was resumable the whole time. The fixpoint test
("is the residual empty?") already exists — it is just trapped in the
crash-recovery framing of `resume.py`, where it only runs when a run *died*.

This module lifts that fixpoint test out of the morgue and points it at a **live,
healthy** run: same `residual = declared − verified`, asked *forward* ("is it empty,
and may the loop stop?") instead of *backward* ("where do I re-enter?"). Completion
becomes the next distrust primitive — the verdict that refuses to take "✅ done" on
faith and adjudicates it against the fossils.

The self-report → distrust-verdict ladder (docs/117 §1.1), this is the missing rung:

    "this step shipped"          → verify()       → SHIPPED / NOT_SHIPPED   (oracle)
    "I'm making progress"        → liveness()     → ADVANCING / SPINNING     (liveness)
    "I may take this region"     → arbitrate()    → ACQUIRE / refuse         (arbiter)
    "I crashed; resume from X"   → resume_plan()  → RESUMABLE / COMPLETE     (resume)
    "I'm done with the whole job"→ classify()     → COMPLETE / INCOMPLETE    ← THIS

Reuse, not reimplementation (docs/117 §5.1, §9)
===============================================

`classify` does **not** re-derive the residual. It calls `resume.resume_plan` —
which already does the ancestry re-adjudication, the contiguous-prefix rule, and
the fail-closed treatment of a `STEP_CLAIMED`-but-unverified step (that step stays
IN the residual, `resume.py:282`) — and then **maps the backward verdict forward**:

    resume.COMPLETE      → Completion.COMPLETE       (residual empty: stop-on-done)
    resume.RESUMABLE     → Completion.INCOMPLETE      (residual non-empty: re-dispatch IT)
    resume.DIVERGED      → Completion.INCOMPLETE      (work remains; ground truth moved —
                                                       still not done; carries the residual)
    resume.UNRESUMABLE   → Completion.INDETERMINATE   (unsound fold / no intent: refuse to
                                                       CALL it done, don't guess — the floor)

So every property `resume` proved — claimed-≠-verified, contiguous-prefix coverage,
the `STEP_VERIFIED`-re-adjudicated-at-read fix (docs/107 §5 / docs/103) — is
inherited here for free. The only thing `completion` adds is the *forward framing*
and the *convergence* verdict over rounds (below); the residual arithmetic is
`resume`'s, byte-for-byte.

What is NOT here yet (the later phases of docs/117)
===================================================

  * **`UNDERDECLARED`** — the Gap-B refusal ("the residual is empty, but a
    `ScopeSource` says the declared extent was smaller than the real job") is now
    WIRED: `classify` takes `scope_verdicts` and folds them through
    `scope_source.honest_under_floor` (docs/117 §5.3 / Phase 4) — the pluggable
    extent rung, the `overlap_policy` shape, structurally able only to make
    completion *harder*. With no verdicts supplied (the default) `classify` answers
    from the declared steps alone — the honest floor, exactly as `resume` does — so
    this is opt-in and byte-identical when unused. What is still future: a richer
    set of *real* driver sources beyond the reference one, and the `dos complete
    --scope-source` CLI / `dos.toml [completion] scope_sources` config seam that
    populates `scope_verdicts` from a workspace declaration (today a caller passes
    them explicitly; the kernel seam + one driver are the shipped part).
  * **The loop-stop wiring** (`StopReason.COMPLETE`/`THRASHING`, residual
    re-dispatch — docs/117 §5.4, Phase 3). This module ships the pure verdicts the
    loop will read; it does not touch the running loop. Same staging as
    `liveness` (the verdict shipped before the `loop_decide` consumer did).

Why a pure leaf with no I/O
===========================

The `liveness`/`resume` rule: `classify(evidence, policy) -> verdict` makes no
subprocess/file/clock call — all evidence (`LedgerState`, `AncestryFacts`, the
residual-size history) is gathered at the caller boundary (the same git read
`resume`'s `dos resume` path does) and handed in, so the verdict is replay-tested
on frozen fixtures. The verdict is **advisory** (docs/99): it mints the belief "the
declared work is verifiably closed" / "this loop will not converge"; the act of
*stopping* is the loop's, never the kernel's.

Pure stdlib — no third-party imports, no I/O. Imports one sibling kernel module
(`resume`), exactly as `resume` imports `intent_ledger` — the "no host, no I/O
policy" litmus, not "no sibling import" (CLAUDE.md).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional

from dos.intent_ledger import LedgerState
from dos import resume as _resume
from dos.resume import AncestryFacts, ResumePolicy, DEFAULT_POLICY as _RESUME_DEFAULT_POLICY
from dos.scope_source import ScopeVerdict, honest_under_floor


# ───────────────────────────── the live completion verdict ────────────────────
class Completion(str, enum.Enum):
    """The typed completion verdict — four states, mutually exclusive (docs/117 §5.1).

    `str`-valued so it round-trips a `--json` token / exit-code map without a lookup
    table (the `Resume` / `Liveness` / `gate_classify.Verdict` idiom). The asymmetry
    is the point: only COMPLETE authorises the loop to stop-on-done; everything else
    keeps the work open (INCOMPLETE re-dispatches; INDETERMINATE refuses to assert
    done on an unsound fold).
    """

    COMPLETE = "COMPLETE"          # residual empty — every declared step verified; the loop MAY stop-on-done
    INCOMPLETE = "INCOMPLETE"      # residual non-empty — verifiably more to do; re-dispatch the residual
    UNDERDECLARED = "UNDERDECLARED"  # residual empty BUT an external ScopeSource says the extent under-declared (Phase 4; not emitted yet)
    INDETERMINATE = "INDETERMINATE"  # unsound fold / no intent — refuse to CALL it done, don't guess (the floor)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_done(self) -> bool:
        """True iff the loop is authorised to stop because the work is finished."""
        return self is Completion.COMPLETE

    @property
    def has_residual(self) -> bool:
        """True iff there is verifiably more declared work to do (INCOMPLETE only)."""
        return self is Completion.INCOMPLETE


@dataclass(frozen=True)
class CompletionVerdict:
    """The single verdict `classify` returns, with the derivation echoed back.

    `state` is the typed `Completion`. `reason` is the operator-facing one-liner.
    `residual` is the ordered remaining step ids (empty iff COMPLETE) — the loop
    re-dispatches THESE, not a fresh pass (docs/117 §5.4). `verified` is the
    contiguous-verified prefix the COMPLETE/INCOMPLETE rests on. `declared` is the
    full declared extent (so a reader sees the denominator). `run_id` keys it.
    `to_dict` is the `--json` shape (the `ResumePlan.to_dict` idiom).
    """

    state: Completion
    reason: str
    run_id: str
    residual: tuple[str, ...] = ()
    verified: tuple[str, ...] = ()
    declared: tuple[str, ...] = ()

    @property
    def fraction_done(self) -> Optional[float]:
        """|verified| / |declared| — the closure fraction, or None when nothing is
        declared (a free-form goal has no step denominator). A legibility aid for the
        surfaced line; never load-bearing for the verdict itself."""
        n = len(self.declared)
        return (len(self.verified) / n) if n else None

    def to_dict(self) -> dict:
        out = {
            "state": self.state.value,
            "reason": self.reason,
            "run_id": self.run_id,
            "residual": list(self.residual),
            "verified": list(self.verified),
            "declared": list(self.declared),
            "is_done": self.state.is_done,
        }
        frac = self.fraction_done
        if frac is not None:
            out["fraction_done"] = round(frac, 4)
        return out


def classify(
    state: LedgerState,
    ancestry: AncestryFacts,
    policy: ResumePolicy = _RESUME_DEFAULT_POLICY,
    scope_verdicts: tuple[ScopeVerdict, ...] = (),
) -> CompletionVerdict:
    """Adjudicate whether the WHOLE declared job is verifiably done. PURE — no I/O.

    Reuses `resume.resume_plan`'s residual arithmetic verbatim (docs/117 §5.1) and
    maps its backward (where-do-I-re-enter) verdict to a forward (may-I-stop) one:

      * `resume.COMPLETE`    → `COMPLETE`     — residual empty; every declared step
                                                verified on the non-forgeable rung.
      * `resume.RESUMABLE`   → `INCOMPLETE`   — a non-empty residual remains; the loop
                                                re-dispatches it (carried on `.residual`).
      * `resume.DIVERGED`    → `INCOMPLETE`   — work remains AND ground truth moved past
                                                the resume point. Still not done; the
                                                residual is carried so the loop/operator
                                                can reconcile (the divergence is in the
                                                reason, but the completion answer is the
                                                same "no, not done").
      * `resume.UNRESUMABLE` → `INDETERMINATE`— no INTENT, a corrupt fold, or a schema
                                                this kernel is too old to read: refuse to
                                                CALL it done (the floor — never assert
                                                completion on an unsound fold).

    The verdict is **advisory** (docs/99): it mints "done / not done / can't tell" and
    the loop *decides* to stop on COMPLETE; the kernel never re-runs the work (docs/117
    §8).

    The `scope` rung (docs/117 Phase 4) distrusts the residual's DENOMINATOR. When
    `resume` says the residual is empty, `classify` does not grant `COMPLETE`
    unconditionally — it first folds the caller-supplied `scope_verdicts` through
    `scope_source.honest_under_floor`: `COMPLETE` requires the residual empty AND
    every scope source agreeing the declared extent was the whole job. If any source
    voted the extent under-declared, `classify` emits `UNDERDECLARED` instead (the
    residual is empty, but the *scope* the residual was measured against was too
    small — `docs/103` inward, on the denominator). With no `scope_verdicts` (the
    default `()`), `honest_under_floor(())` is honest, so completion is **exactly
    today's "all declared verified" floor** and `UNDERDECLARED` is never emitted — the
    Phase-1 behavior, byte-for-byte. The sources are gathered + run (`run_scope`,
    fail-to-strict) at the caller boundary and handed in, exactly as `AncestryFacts`
    is — the verdict stays pure and replay-testable.
    """
    plan = _resume.resume_plan(state, ancestry, policy)
    declared = tuple(state.declared_steps)
    rid = plan.run_id

    if plan.verdict is _resume.Resume.COMPLETE:
        # The residual is empty. Before calling it DONE, distrust the denominator:
        # fold the scope verdicts. With no sources wired this is honest (today's
        # floor); any source flagging under-declaration flips it to UNDERDECLARED.
        scope = honest_under_floor(tuple(scope_verdicts))
        n = len(plan.verified) or len(declared)
        if not scope.extent_honest:
            return CompletionVerdict(
                state=Completion.UNDERDECLARED,
                reason=(
                    f"all {n} declared unit(s) verified, BUT the declared extent is "
                    f"not the whole job — {scope.reason}; not done (a human must "
                    f"reconcile the scope before it can close)"
                ),
                run_id=rid,
                residual=(),
                verified=plan.verified,
                declared=declared,
            )
        return CompletionVerdict(
            state=Completion.COMPLETE,
            reason=(
                f"all {n} declared unit(s) verified against ancestry — the residual is "
                f"empty; the declared job is done (stop-on-done, not out-of-budget)"
            ),
            run_id=rid,
            residual=(),
            verified=plan.verified,
            declared=declared,
        )

    if plan.verdict is _resume.Resume.UNRESUMABLE:
        # The fold is unsound (no INTENT / corrupt / too-new schema). We cannot
        # ground a residual, so we cannot soundly say "done" OR "this much remains".
        # Refuse to assert completion — the `resume.UNRESUMABLE` floor, restated.
        return CompletionVerdict(
            state=Completion.INDETERMINATE,
            reason=(
                f"cannot adjudicate completion — {plan.reason} "
                f"(refusing to call a job done from an unsound ledger fold)"
            ),
            run_id=rid,
            residual=plan.residual,
            verified=plan.verified,
            declared=declared,
        )

    # RESUMABLE or DIVERGED — both mean "verifiably more to do". The completion
    # answer is the same INCOMPLETE; the residual is carried so the loop re-dispatches
    # exactly the unfinished units (docs/117 §5.4 step 3), and the reason preserves
    # the divergence note when resume flagged it (so the operator still sees it).
    n_resid = len(plan.residual)
    n_decl = len(declared) or n_resid
    if plan.verdict is _resume.Resume.DIVERGED:
        reason = (
            f"INCOMPLETE — {n_resid} of {n_decl} declared unit(s) unverified, AND "
            f"ground truth advanced past the resume point ({plan.reason}); not done — "
            f"the residual must be reconciled before it can close"
        )
    else:
        reason = (
            f"INCOMPLETE — {len(plan.verified)}/{n_decl} declared unit(s) verified; "
            f"{n_resid} remain in the residual ({plan.reason})"
        )
    return CompletionVerdict(
        state=Completion.INCOMPLETE,
        reason=reason,
        run_id=rid,
        residual=plan.residual,
        verified=plan.verified,
        declared=declared,
    )


# ───────────────────────────── the convergence verdict ────────────────────────
# docs/117 §5.2 / Gap C. COMPLETE is a STATIC fixpoint (residual empty *now*). The
# "can't stop" failure is DYNAMIC: the residual never empties because each round adds
# as much as it closes (the reviewer-finds-new-findings loop). This verdict is over a
# HISTORY of residual sizes — one int per completed round — and answers "is |residual|
# actually shrinking, or is the loop busy-but-forever?".


class Convergence(str, enum.Enum):
    """Is the residual trending to empty, or oscillating/growing forever? (docs/117 §5.2).

    A DIFFERENT "no" from the two we already have:
      * `liveness.SPINNING` = not committing at all (zero forward git delta) — temporal.
      * `resume.RESUMABLE`  = work remains (residual non-empty) — a single snapshot.
      * `THRASHING` (here)  = commits ARE landing, the residual IS changing, but it is
                              not monotonically decreasing — the loop is productive and
                              will run forever. The honest verdict for "no fixpoint".
    """

    CONVERGING = "CONVERGING"  # |residual| (weakly) decreasing toward 0 — keep going
    THRASHING = "THRASHING"    # |residual| failed to decrease for max_nonconverging rounds — surface, don't burn budget
    STARVED = "STARVED"        # |residual| non-empty and UNCHANGED across the window — distinct from THRASHING's churn
    INSUFFICIENT = "INSUFFICIENT"  # too few rounds to judge a trend yet — keep going (no verdict)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def should_surface(self) -> bool:
        """True iff a loop should STOP-and-surface rather than continue (the no-fixpoint set)."""
        return self in (Convergence.THRASHING, Convergence.STARVED)


@dataclass(frozen=True)
class ConvergencePolicy:
    """Knobs for the convergence verdict — policy, not mechanism (the `ResumePolicy` split).

      * ``max_nonconverging`` — how many consecutive rounds |residual| may fail to
        strictly decrease before THRASHING. Default 3 — the existing circuit-breaker
        idiom (`loop_decide`'s `max_unclear` / `max_dirty_zero`).
      * ``window`` — how many of the most-recent rounds the trend is judged over.
        Default 4. Fewer than 2 rounds is always INSUFFICIENT (no trend to read).

    Defaults are GENERIC (no host tuning); a workspace could declare its own in
    `dos.toml [completion]` (a future seam, like the planned `[liveness]`/`[resume]`).
    """

    max_nonconverging: int = 3
    window: int = 4


DEFAULT_CONVERGENCE_POLICY = ConvergencePolicy()


@dataclass(frozen=True)
class ConvergenceVerdict:
    """The typed convergence verdict + the derivation (the window it judged)."""

    state: Convergence
    reason: str
    window: tuple[int, ...] = ()  # the residual sizes the verdict was read over (most recent last)

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "reason": self.reason,
            "window": list(self.window),
            "should_surface": self.state.should_surface,
        }


def convergence(
    residual_history: tuple[int, ...],
    policy: ConvergencePolicy = DEFAULT_CONVERGENCE_POLICY,
) -> ConvergenceVerdict:
    """Read the residual-size trend across rounds. PURE — over a history of ints.

    One int per completed round (the loop appends ``|residual|`` each iteration; the
    history is cheap and lives in `LoopState`). The verdict (docs/117 §5.2):

      * `CONVERGING` — within the window, |residual| is weakly decreasing and the
        latest is below the window's first (it is trending to 0). Keep going.
      * `STARVED`    — the window is non-empty, > 0, and FLAT (every value equal):
        no progress at all, distinct from THRASHING's churn.
      * `THRASHING`  — |residual| failed to STRICTLY decrease for the last
        ``max_nonconverging`` rounds (it oscillated or grew): a productive loop with
        no fixpoint — surface a decision, don't burn the cap silently.
      * `INSUFFICIENT` — fewer than 2 rounds (or fewer than 2 in the window): no
        trend to read yet; the loop continues (this is never a stop signal).

    A residual that reaches 0 is CONVERGING (it converged) regardless of the path —
    the static `COMPLETE` from `classify` is the authority on done-ness; this verdict
    only catches the *won't-ever-get-there* case.
    """
    hist = tuple(int(x) for x in residual_history)
    if len(hist) < 2:
        return ConvergenceVerdict(
            state=Convergence.INSUFFICIENT,
            reason=(f"only {len(hist)} round(s) recorded — need ≥2 to read a trend; "
                    f"continue (no convergence verdict yet)"),
            window=hist,
        )

    w = hist[-policy.window:] if policy.window > 0 else hist
    first, last = w[0], w[-1]

    # Converged (or converging to) empty — the happy path. A 0 anywhere recent means
    # the static COMPLETE verdict will fire; never call that THRASHING.
    if last == 0:
        return ConvergenceVerdict(
            state=Convergence.CONVERGING,
            reason=f"residual reached 0 over {w} — converged",
            window=w,
        )

    # Flat and non-empty across the whole window → STARVED (no churn, no progress).
    if len(set(w)) == 1:
        return ConvergenceVerdict(
            state=Convergence.STARVED,
            reason=(f"residual is unchanged at {last} across {len(w)} round(s) {w} — "
                    f"no progress; a precondition is likely blocking (surface)"),
            window=w,
        )

    # THRASHING test — the residual CHURNS UPWARD without reaching a new low.
    #
    # The defining feature of a no-fixpoint loop is that the residual *bounces back
    # up*: each pass closes some work and opens as much (the reviewer-finds-new-
    # findings loop). The honest signal is therefore (a) an UP-step happened in the
    # recent window — the residual grew at least once — AND (b) the latest value is
    # NOT a new low for that window (it didn't end by breaking through its prior
    # floor). Together: it went up and didn't recover, so it is going nowhere.
    #
    # This is the criterion a per-transition or endpoint test both get wrong:
    #   (4,3,4,3) — up-step 3→4 present, last 3 == window min 3 (not a NEW low) → THRASHING
    #   (1,2,3,4) — up-steps present, last 4 is the max (not a low)            → THRASHING
    #   (8,5,3,1) — no up-step at all                                          → CONVERGING
    # We require k+1 rounds of history before trusting it, so one stray uptick inside
    # an otherwise-improving run does not trip a stop (the decision must be confident).
    k = policy.max_nonconverging
    recent = hist[-(k + 1):]
    if len(recent) >= k + 1:
        went_up = any(recent[i + 1] > recent[i] for i in range(len(recent) - 1))
        earlier_min = min(recent[:-1])
        no_new_low = last >= earlier_min
        if went_up and no_new_low:
            return ConvergenceVerdict(
                state=Convergence.THRASHING,
                reason=(f"residual churned without reaching a new low over {k} round(s) "
                        f"{recent} (latest {last} ≥ window floor {earlier_min}) — the "
                        f"loop is productive but has no fixpoint; cut scope or accept "
                        f"partial (surface, don't burn the cap)"),
                window=w,
            )

    # Net-decreasing across the window (below where it began) → CONVERGING.
    if last < first:
        return ConvergenceVerdict(
            state=Convergence.CONVERGING,
            reason=f"residual decreasing across {w} ({first} → {last}) — fixpoint reachable",
            window=w,
        )

    # Stuck-but-young: not net-decreasing, but fewer than k+1 rounds of history — not
    # confident enough to call THRASHING. Continue; the loop confirms or clears the
    # trend as more rounds land. (CONVERGING here means "no stop signal yet," not
    # "provably shrinking" — the reason says so.)
    return ConvergenceVerdict(
        state=Convergence.CONVERGING,
        reason=(f"residual {w}: not yet net-decreasing but under the "
                f"{policy.max_nonconverging}-round non-progress threshold — continue"),
        window=w,
    )

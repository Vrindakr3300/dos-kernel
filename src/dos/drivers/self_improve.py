"""dos.drivers.self_improve — the self-improving-loop ENGINE (docs/280).

The driver half of the first self-improving work loop for DOS. The kernel leaf
(`dos.improve`) is a PURE keep-gate — `classify(CandidateEvidence, policy) ->
KEEP/REVERT/ESCALATE`. This module is the layer-4 driver that does the I/O the
kernel refuses to: it runs the test suite, runs the truth syscall, measures the
host's improvement metric, counts the tokens a candidate spent, calls the kernel,
and carries out the verdict (merge / discard / escalate).

THE DELIBERATE BOUNDARY — the engine proposes NOTHING
=====================================================

The intelligent, non-deterministic part of a self-improving loop is *proposing a
candidate change*. That part lives ENTIRELY outside this engine — in the
`self-improve` skill's subagent brief — for the same reason `llm_judge` is the
only non-deterministic rung and it is a driver: the kernel (and this engine)
contribute ZERO intelligence to the proposal, only the refusal to keep an
unwitnessed one. The engine takes the candidate as an injected callback
(`propose`/`apply`), so:

  * the engine is fully DETERMINISTIC and unit-testable on a fake proposer (no
    model, no network), and
  * the keep-decision is provably a function of env-authored facts, never of
    whatever the proposer narrated.

This is the `propose → verify → measure → keep-or-revert` cycle with the verify /
measure / keep-or-revert steps mechanized here and the propose step left to a
capable agent the engine treats as untrusted.

THE WORKTREE ISOLATION — the kernel adjudicating is not the kernel rewritten
============================================================================

A candidate edit to DOS is the `SELF_MODIFY` / `global`-lane hazard (docs/89,
[[self-modification-hazard]]): editing the kernel's own running path is exactly
what the arbiter refuses. So a candidate is applied + measured in an ISOLATED git
worktree (the host supplies the worktree paths in `CycleContext`), never the live
tree the loop is running from. The kernel that adjudicates the candidate is not
the kernel being rewritten by it — the engine reads the verdict from a clean
process, then merges only on KEEP.

This module names no host beyond the `SubstrateConfig` seam and reads the metric
through an injected callback, so it is domain-free: the host names *what
improvement means* (the metric) and *how to propose* (the callback); the engine
owns the loop skeleton + the witness-gather.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from dos import improve


# ---------------------------------------------------------------------------
# The injected boundary — what the host supplies per loop.
# ---------------------------------------------------------------------------


class CycleAction(str, enum.Enum):
    """What the engine DID with a candidate this cycle — the carried-out verdict.

    Mirrors `improve.Candidate` (the verdict) but names the ACTUATION the engine
    performed, so a loop record reads as a log of *acts*, not just verdicts:

      MERGED    — the candidate was KEPT: its worktree commit was merged onto the
                  lane and the baseline was raised. The loop ratchets.
      DISCARDED — the candidate was REVERTED: its worktree was thrown away, the
                  live tree is untouched. The breaker count was bumped.
      ESCALATED — the breaker OPENed: the engine stopped and filed a human decision.
      SKIPPED   — the proposer returned no candidate this cycle (nothing to judge);
                  not a fault, not a revert — the engine simply moves on.
    """

    MERGED = "merged"
    DISCARDED = "discarded"
    ESCALATED = "escalated"
    SKIPPED = "skipped"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class Candidate:
    """One proposed self-improvement, as the injected proposer returns it.

    The proposer (a capable agent, OUTSIDE the engine's trust) applies a single
    scoped change inside the isolated worktree and returns this descriptor. Every
    field the engine later trusts is RE-MEASURED by the engine from the worktree —
    none is taken from the proposer's word:

      present  — did the proposer actually produce a candidate this cycle? False ⇒
                 the engine SKIPs (nothing to judge). The proposer's honest "I have
                 nothing" — not a revert.
      commit   — the worktree commit SHA the candidate landed (for the merge on
                 KEEP and the truth syscall). May be "" when `present` is False.
      narrated — the proposer's own description of what it did. Carried to the
                 operator surface and the kernel's `narrated` field — parsed for
                 NOTHING (docs/234). This is the ONE field that is the proposer's
                 word, and by construction it touches no part of the keep-decision.
      tokens   — the tokens the proposer spent producing the candidate (for the
                 efficiency rung). The host reads this from the provider usage
                 record, not the proposer's claim.
    """

    present: bool
    commit: str = ""
    narrated: str = ""
    tokens: int = 0


@dataclass(frozen=True)
class WitnessReadback:
    """The env-authored witnesses the engine gathered for one candidate.

    The host's gather functions (see `CycleContext`) produce this AFTER the
    candidate is applied in the worktree. Every field is authored by the
    environment, never the proposer — the docs/138 invariant the keep-bit rests on:

      suite_passed  — the test runner's exit status on the worktree (True iff the
                      suite the host runs exited 0). The runner authored it.
      truth_clean   — True iff `dos verify` / `dos commit-audit` agreed over git
                      ancestry for the candidate commit. The oracle authored it.
      work          — the host's improvement metric measured on the worktree AFTER
                      the candidate. The environment measured it.
    """

    suite_passed: bool
    truth_clean: bool
    work: int


@dataclass(frozen=True)
class CycleContext:
    """Everything the engine needs to run ONE cycle — the host's injected I/O.

    The callbacks are the seam: the engine owns the loop skeleton and the
    witness→kernel→actuation wiring; the host owns every side-effecting step. All
    are plain callables so the engine is testable on fakes (no model, no git, no
    subprocess in a unit test).

      propose       — () -> Candidate. Apply ONE scoped self-improvement in the
                      isolated worktree and return its descriptor (or
                      `Candidate(present=False)` to skip). The capable, untrusted
                      step — the only place intelligence enters the loop.
      gather        — (Candidate) -> WitnessReadback. Run the suite, run the truth
                      syscall, measure the metric on the worktree. The env-authored
                      witness-gather. Called ONLY when a candidate is present.
      merge         — (Candidate) -> None. KEEP actuation: merge the candidate's
                      worktree commit onto the lane (the engine calls this only on
                      a KEEP verdict).
      discard       — (Candidate) -> None. REVERT actuation: throw the worktree's
                      candidate away, leaving the live tree untouched.
      escalate      — (improve.CandidateVerdict) -> None. ESCALATE actuation: file a
                      `dos decisions` entry for a human (the engine calls this once,
                      then stops).
      baseline_work — the host metric measured on the GREEN baseline tree at the
                      start of this cycle (the `work` the candidate must strictly
                      beat). The engine raises it after a KEEP so the loop ratchets.
      policy        — the `improve.ImprovePolicy` (thresholds; the host's
                      `dos.toml [improve]`).
    """

    propose: Callable[[], Candidate]
    gather: Callable[[Candidate], WitnessReadback]
    merge: Callable[[Candidate], None]
    discard: Callable[[Candidate], None]
    escalate: Callable[["improve.CandidateVerdict"], None]
    baseline_work: int
    policy: improve.ImprovePolicy = field(default_factory=improve.ImprovePolicy)


@dataclass(frozen=True)
class CycleResult:
    """The outcome of ONE cycle — the verdict, the act taken, and the carry-forward.

    `verdict` is the kernel's `CandidateVerdict` (None on a SKIP — nothing was
    judged). `action` is what the engine DID (the `CycleAction`). `candidate` is the
    descriptor that was judged (None on a SKIP). `next_baseline` and
    `next_consecutive_reverts` are the state the driver threads into the NEXT cycle
    — `next_baseline` is raised on a KEEP (the ratchet), unchanged otherwise;
    `next_consecutive_reverts` is the kernel's carried breaker count. `should_stop`
    is True iff the loop must halt now (an ESCALATE).
    """

    action: CycleAction
    next_baseline: int
    next_consecutive_reverts: int
    should_stop: bool
    verdict: "Optional[improve.CandidateVerdict]" = None
    candidate: Optional[Candidate] = None

    @property
    def reason(self) -> str:
        """A one-line operator-facing summary for the loop record's tally row."""
        if self.verdict is None:
            return "no candidate proposed this cycle — skipped (nothing to judge)"
        return self.verdict.reason


def run_cycle(ctx: CycleContext, consecutive_reverts: int = 0) -> CycleResult:
    """Run ONE self-improvement cycle: propose → gather → classify → actuate.

    The deterministic engine skeleton (the proposer is the only non-deterministic
    step, and it is injected). Steps:

      1. PROPOSE — ask the injected proposer for one candidate. If none is present,
         return a SKIP immediately (nothing to judge — not a revert, the breaker is
         untouched).
      2. GATHER — run the host's witness-gather on the worktree (suite, truth
         syscall, metric). Every fact is env-authored.
      3. CLASSIFY — hand the env-authored facts + the carried breaker count to the
         PURE kernel (`improve.classify`). The keep-decision is the kernel's; the
         proposer's narration rides along in `narrated` and moves nothing.
      4. ACTUATE — carry out the verdict: KEEP → merge + raise the baseline (the
         ratchet) + reset the breaker; REVERT → discard + bump the breaker;
         ESCALATE → discard + file a human decision + stop.

    Returns a `CycleResult` carrying the verdict, the act, and the state to thread
    into the next cycle. PURE of policy: every threshold is in `ctx.policy`, every
    side effect is in `ctx`'s callbacks — the engine just wires them.
    """
    # 1. PROPOSE — the one untrusted, intelligent step.
    candidate = ctx.propose()
    if not candidate.present:
        return CycleResult(
            action=CycleAction.SKIPPED,
            next_baseline=ctx.baseline_work,
            next_consecutive_reverts=consecutive_reverts,
            should_stop=False,
        )

    # 2. GATHER — the env-authored witnesses, measured on the worktree.
    readback = ctx.gather(candidate)

    # 3. CLASSIFY — the PURE kernel keep-gate. The proposer's `narrated` rides along
    #    but, by construction (docs/234), cannot move the verdict.
    evidence = improve.CandidateEvidence(
        suite_passed=readback.suite_passed,
        truth_clean=readback.truth_clean,
        work=readback.work,
        baseline_work=ctx.baseline_work,
        tokens=candidate.tokens,
        consecutive_reverts=consecutive_reverts,
        narrated=candidate.narrated,
    )
    verdict = improve.classify(evidence, ctx.policy)

    # 4. ACTUATE — carry out the kernel's verdict.
    if verdict.verdict is improve.Candidate.KEEP:
        ctx.merge(candidate)
        return CycleResult(
            action=CycleAction.MERGED,
            next_baseline=readback.work,  # the ratchet: the next candidate must beat THIS
            next_consecutive_reverts=verdict.next_consecutive_reverts,  # 0
            should_stop=False,
            verdict=verdict,
            candidate=candidate,
        )

    if verdict.verdict is improve.Candidate.ESCALATE:
        # Discard the candidate that tipped the breaker, then surface to a human and stop.
        ctx.discard(candidate)
        ctx.escalate(verdict)
        return CycleResult(
            action=CycleAction.ESCALATED,
            next_baseline=ctx.baseline_work,  # unchanged — nothing was kept
            next_consecutive_reverts=verdict.next_consecutive_reverts,
            should_stop=True,
            verdict=verdict,
            candidate=candidate,
        )

    # REVERT — discard the worktree candidate; the live tree is untouched.
    ctx.discard(candidate)
    return CycleResult(
        action=CycleAction.DISCARDED,
        next_baseline=ctx.baseline_work,  # unchanged
        next_consecutive_reverts=verdict.next_consecutive_reverts,
        should_stop=False,
        verdict=verdict,
        candidate=candidate,
    )


@dataclass(frozen=True)
class LoopOutcome:
    """The result of a bounded run of cycles — the loop's final tally.

    `cycles` is the per-cycle record (in order). `kept` / `reverted` / `skipped`
    are the counts. `escalated` is True iff the loop stopped on an ESCALATE.
    `final_baseline` is the metric after the last KEEP (the ratchet's high-water
    mark — the measure of how much the loop improved DOS). `stop_reason` is a
    one-line summary of why the loop ended.
    """

    cycles: tuple[CycleResult, ...]
    kept: int
    reverted: int
    skipped: int
    escalated: bool
    final_baseline: int
    stop_reason: str


def run_loop(
    ctx: CycleContext,
    *,
    max_cycles: int,
    consecutive_reverts: int = 0,
    on_cycle: "Optional[Callable[[CycleResult], None]]" = None,
) -> LoopOutcome:
    """Run up to `max_cycles` self-improvement cycles, ratcheting the baseline.

    The outer-loop skeleton — the `loop_decide` of the self-improvement loop, but
    simpler because every stop condition is the kernel's: a cycle stops the loop iff
    its `CycleResult.should_stop` (an ESCALATE), and the bare `max_cycles` is the
    backstop (the `ITERATION_CAP` analogue). Between cycles the engine threads two
    pieces of state — the (possibly raised) `baseline_work` and the carried breaker
    count — so the loop RATCHETS: after a KEEP the next candidate must beat the
    improved tree, not the original.

    `on_cycle` is an optional sink (the host's run-record writer / `dos top`
    surface) called once per cycle with its result. The engine itself writes nothing
    — archiving is the host's actuation (the CLAUDE.md "the kernel reports, the host
    acts" line).

    Stops on the FIRST of: an ESCALATE (the breaker — surface to a human), or
    `max_cycles` reached (the backstop). A run of SKIPs (the proposer keeps finding
    nothing) burns cycles up to the cap — the host may choose a smaller cap when it
    expects the well to be shallow.
    """
    cycles: list[CycleResult] = []
    kept = reverted = skipped = 0
    baseline = ctx.baseline_work
    reverts = consecutive_reverts
    escalated = False
    stop_reason = f"reached the {max_cycles}-cycle cap"

    for i in range(max_cycles):
        cycle_ctx = replace(ctx, baseline_work=baseline)
        result = run_cycle(cycle_ctx, consecutive_reverts=reverts)
        cycles.append(result)
        if on_cycle is not None:
            on_cycle(result)

        if result.action is CycleAction.MERGED:
            kept += 1
        elif result.action is CycleAction.DISCARDED:
            reverted += 1
        elif result.action is CycleAction.SKIPPED:
            skipped += 1

        baseline = result.next_baseline
        reverts = result.next_consecutive_reverts

        if result.should_stop:
            escalated = True
            stop_reason = (
                f"ESCALATED to a human after {reverts} candidates in a row that "
                f"nothing accepted (cycle {i + 1})"
            )
            break

    return LoopOutcome(
        cycles=tuple(cycles),
        kept=kept,
        reverted=reverted,
        skipped=skipped,
        escalated=escalated,
        final_baseline=baseline,
        stop_reason=stop_reason,
    )

"""The stall-reader evaluation harness — score a `StreamPolicy` by its NET RECOVERY.

docs/145 §9 — the per-axis eval, the `judge_eval` / `overlap_eval` / `intervention_eval`
discipline re-aimed at the loop-economics axis. Every DOS axis ships an eval that turns its
thresholds from a hunch into a measured, per-deployment decision (the research-friendliness
thesis, docs/90 §2). The stall reader's two thresholds (`repeat_n` / `stall_n`) and its
`ignore_tools` allow-list need exactly that instrument: a backtest that answers **"on this
deployment's real tool streams, does firing a re-surface on REPEATING recover stuck tasks
more often than it false-fires on a legitimate poller?"**

The decisive numbers (the dual of `intervention_eval`'s wasted-disruption rate):

  * **recovered_rate** — of the streams that were ACTUALLY stuck (the agent had the value and
    was looping), the fraction this policy fired REPEATING/STALLED on. Recall-of-action: a
    too-timid policy (`repeat_n` set huge) scores ~0 — it never fires, never recovers.
  * **false_resurface_rate** — of the streams that were LEGITIMATELY repeating (eventual-
    consistency polling, a correct re-check), the fraction this policy ALSO fired on. The
    dangerous cell — the §3 honest hole made measurable. A re-surface on a legitimate poller is
    *harmless by design* (re-presenting bytes the agent holds), but a high rate means the
    threshold is too eager and the host should raise `repeat_n` or grow `ignore_tools`.

The honesty stance (the same as judge_eval / overlap_eval / intervention_eval)
==============================================================================

The labels are the RESEARCHER's ground truth, never the reader's:

  * `actually_stuck`  — was the agent ACTUALLY looping with a value it already had, and would a
    re-surface have unstuck it? Known from the replay (a labelled stuck stream), NOT from the
    `result_digest` repetition the reader keys on. The `overlap_eval.collided` discipline.
  * `legit_polling`   — was the repetition a LEGITIMATE re-check (eventual-consistency wait, an
    idempotent retry that later succeeds)? The false-fire denominator.
  * `recovered_if_fired` — counterfactual ground truth from the EXECUTED replay: under a
    re-surface WARN, did the agent then finish? (NOT a guessed label — measured, the
    `intervention_eval.recovered_if_blocked` discipline.)

Everything is **pure**: it consumes already-built `StreamCase`s, runs each through the SAME
`tool_stream.classify_stream` the consumer's reader takes (so the grid reflects what would
actually fire — the `overlap_eval` "score under the floor" discipline), and counts in one
pass. No I/O, no host names — it sits in the kernel layer beside `tool_stream`.

⚠ This is NOT a detector eval of `arg_provenance`, and NOT `intervention_eval`. It measures the
STALL READER specifically — does firing on a repeat recover more than it wastes — an axis
orthogonal to both the mint detector (docs/143) and the actuation ladder (docs/144).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from dos.tool_stream import (
    DEFAULT_POLICY,
    StreamPolicy,
    StreamState,
    ToolStream,
    classify_stream,
)


# ---------------------------------------------------------------------------
# A labelled example — one replayed tool stream + the GROUND-TRUTH outcome.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StreamCase:
    """One replayed tool stream + the ground-truth labels for what firing on it would do.

    The `state` the policy assigns is NOT stored — it is DERIVED in `score()` via
    `classify_stream` from the embedded `stream`, so the scored action can never drift from a
    hand-labelled state (the label-drift trap, the `intervention_eval` discipline). Every other
    field is a researcher ground-truth label from a replay, NOT a guess.

    Fields:
      stream             — the real `ToolStream` accumulated for this episode. The policy is
                           scored against THIS via `classify_stream` (same path as the consumer's
                           reader), so the grid measures what would actually fire.
      actually_stuck     — ground truth: was the agent looping with a value it already had (a
                           re-surface would help)? The recovered_rate numerator's truth.
      legit_polling      — ground truth: was the repetition a LEGITIMATE re-check (eventual-
                           consistency wait / idempotent retry that later succeeds)? The
                           false-resurface denominator. (A stream can be neither — a normal
                           advancing run — in which case the reader should not fire at all.)
      recovered_if_fired — counterfactual ground truth: under a re-surface WARN, did the agent
                           then finish the task? (Measured in replay, not guessed.)
      label              — optional human handle (carried, never scored).
    """

    stream: ToolStream
    actually_stuck: bool
    legit_polling: bool
    recovered_if_fired: bool
    label: str = ""


# ---------------------------------------------------------------------------
# The report — frozen, @property rates with div-guard, to_dict (mirror intervention_eval).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StreamEvalReport:
    """A `StreamPolicy` scored over labelled cases — the recovery ledger + the false-fire rate.

    The grid splits the ground-truth crosstab (independent of the policy) from the firing ledger
    (what the policy actually flagged). The named dangerous cell is `fired_on_polling` — a fire
    on a legitimately-polling stream (harmless by design, but the signal the threshold is too
    eager).
    """

    n: int
    # ground-truth grid (policy-independent):
    n_stuck: int                  # actually_stuck (the recoverable population)
    n_polling: int                # legit_polling (the false-fire denominator)
    # firing ledger (what the policy did):
    n_fired: int                  # REPEATING or STALLED assigned
    n_fired_stuck: int            # fired AND actually_stuck (a useful fire)
    n_fired_polling: int          # fired AND legit_polling (the dangerous cell)
    n_recovered: int              # fired_stuck whose recovered_if_fired is True (the payoff)

    # --- derived rates (all guard against divide-by-zero) ---

    @property
    def recovered_rate(self) -> float:
        """Of all ACTUALLY-stuck streams, the fraction the policy fired on AND that then
        recovered — the HEADLINE payoff (the loop-economics analogue of the +Npp the audit
        chases). A timid policy that never fires scores ~0 here."""
        return (self.n_recovered / self.n_stuck) if self.n_stuck else 0.0

    @property
    def fire_recall(self) -> float:
        """Of all ACTUALLY-stuck streams, the fraction the policy fired on (regardless of whether
        the agent then recovered) — recall-of-action, the counterweight to the false-fire rate."""
        return (self.n_fired_stuck / self.n_stuck) if self.n_stuck else 0.0

    @property
    def false_resurface_rate(self) -> float:
        """Of all LEGITIMATELY-polling streams, the fraction the policy ALSO fired on — THE
        DANGEROUS-CELL RATE (the `intervention_eval.wasted_disruption_rate` /
        `overlap_eval.false_admit_rate` analogue). A re-surface here is harmless by design, but a
        high rate says the threshold is too eager — raise `repeat_n` or grow `ignore_tools`."""
        return (self.n_fired_polling / self.n_polling) if self.n_polling else 0.0

    @property
    def fire_precision(self) -> float:
        """Of all the streams the policy fired on, the fraction that were actually stuck — how
        much of the firing was well-aimed (vs spent on a poller or an advancing run)."""
        return (self.n_fired_stuck / self.n_fired) if self.n_fired else 0.0

    @property
    def net_positive(self) -> bool:
        """True iff the policy recovers more stuck streams than it false-fires on pollers — the
        boolean a `dos tool-stream-eval` exit code could ride (the `intervention_eval.net_harmful`
        analogue, inverted to the friendly direction). Recovery is a real task win; a false
        re-surface is harmless-but-noise, so net-positive is `recovered > fired_on_polling`."""
        return self.n_recovered > self.n_fired_polling

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "grid": {
                "stuck": self.n_stuck,
                "polling": self.n_polling,
            },
            "firing": {
                "fired": self.n_fired,
                "fired_stuck": self.n_fired_stuck,
                "fired_polling": self.n_fired_polling,
                "recovered": self.n_recovered,
            },
            "rates": {
                "recovered_rate": round(self.recovered_rate, 4),
                "fire_recall": round(self.fire_recall, 4),
                "false_resurface_rate": round(self.false_resurface_rate, 4),
                "fire_precision": round(self.fire_precision, 4),
            },
            "net_positive": self.net_positive,
        }


def score(
    policy: StreamPolicy,
    cases: Iterable[StreamCase],
    *,
    _classify=classify_stream,
) -> StreamEvalReport:
    """Run `policy` over labelled `cases` (via `classify_stream`) and tabulate the ledger.

    The policy is scored through the SAME `classify_stream` path the consumer's reader uses (the
    `overlap_eval._admits` / `intervention_eval` "score under the floor" discipline), so the grid
    reflects exactly what would FIRE. A stream FIRES iff its state is REPEATING or STALLED (both
    actionable — the `ladder.actuates()` data-driven-not-hardcoded discipline, here a simple
    not-ADVANCING test since the two firing states are the closed set). PURE: reads cases, counts
    in one pass.

    Invariant (pinned by a test): a stream is counted in `n_fired_stuck` / `n_fired_polling` only
    if it both fired AND carried the matching ground-truth label, so the firing ledger never
    exceeds `n_fired`, and `n_recovered <= n_fired_stuck`.
    """
    n = 0
    n_stuck = n_polling = 0
    n_fired = n_fired_stuck = n_fired_polling = n_recovered = 0

    for case in cases:
        n += 1
        verdict = _classify(case.stream, policy)
        fired = verdict.state is not StreamState.ADVANCING

        if case.actually_stuck:
            n_stuck += 1
        if case.legit_polling:
            n_polling += 1

        if fired:
            n_fired += 1
            if case.actually_stuck:
                n_fired_stuck += 1
                if case.recovered_if_fired:
                    n_recovered += 1
            if case.legit_polling:
                n_fired_polling += 1

    return StreamEvalReport(
        n=n,
        n_stuck=n_stuck,
        n_polling=n_polling,
        n_fired=n_fired,
        n_fired_stuck=n_fired_stuck,
        n_fired_polling=n_fired_polling,
        n_recovered=n_recovered,
    )

"""churn — the pure "should this no-op archive coalesce into the prior commit?" fold.

THE PROBLEM (measured 2026-06-04, the operator's "dispatch is still mega
churning"). The dispatch family already gates the *push* surface — a repeated
0-pick `BLOCKED`/`DRAIN` archive classifies NOOP and never reaches `origin`
(`event_severity` + the per-sink `JOB_DISPATCH_*` thresholds). But every such
iteration still writes its OWN local commit (the archive is unconditional by
design — "archive always" so downstream tools see a terminal envelope). So
`git log` fills with a limit cycle the operator stares at:

    archive … verdict=BLOCKED, /replan recommended
    replan  … quiet sweep (0 closed, 0 added)
    archive … verdict=BLOCKED, /replan recommended      <- same cause, again
    archive … verdict=BLOCKED, /replan recommended      <- and again
    …

Measured: 199 commits → 24 picks shipped (8.3 commits/pick); the single phrase
`child2 skipped (/replan recommended)` recurred 22× over the window — a
BLOCKED → no-op-replan → BLOCKED cycle that never converges. The push gate keeps
peers clean; it does nothing for the LOCAL commit flood, which IS the churn.

THE FIX (this kernel). When the current archive is a NOOP (a 0-pick
blocker/drain) AND the immediately-prior commit on the branch is the SAME-family,
SAME-cause NOOP archive, the write step should **amend** the prior commit instead
of adding a new one — folding this run's README into it and bumping a recurrence
count in the subject. The 22-commit cycle collapses to ~1 commit that says
`blocked ×4 (recurring, coalesced)`; the full per-run audit still lives in the
README tree (every run dir's `README.md` is preserved in the amended commit's
pathspec), so nothing is lost — only the redundant `git log` rows.

⚓ Pure kernel, I/O on the edge (the dos idiom — mirrors `classify_event` /
`classify_recurring_wedge`): `decide_coalesce(ChurnState) -> CoalesceVerdict` is a
frozen dataclass in, a frozen verdict out. The caller reduces the two facts the
decision needs — *this* event and the *prior commit* — to scalars at the write
step (one `git log -1` read + the `event_severity` classification it already
runs), then hands them in frozen. No subprocess, no git/clock/file call here.

⚓ Reuse the severity + cause vocabulary, never re-list it. The coalesce decision
is layered ON TOP of `event_severity.classify_event` (only a NOOP coalesces) and
keys recurrence on the SAME opaque `cause_key` string the host's
`unstick_audit.classify_cause` / `dos.recurring_wedge` already produce. This
module adds the *commit-shaping* rule; it does not re-derive severity or re-match
cues.

WHY a separate leaf and not a branch inside `event_severity`: severity answers
"what operator value does this event carry?" (a push/report/terminal question).
Coalescing answers "given the PRIOR commit, should this one merge into it?" (a
git-history-shaping question that needs a second input — the prior commit — that
severity never sees). Different question, different input, separate leaf — the
`recurring_wedge`-vs-`wedge_reason` split pattern.
"""
from __future__ import annotations

from dataclasses import dataclass

from .event_severity import EventState, Severity, classify_event
from .tokens import normalize_token

# The minimum recurrence at which we coalesce. The FIRST no-op archive of a cause
# always stands alone (it may be a genuine one-off the operator should see in the
# log); the SECOND consecutive same-cause no-op is where the cycle starts and
# coalescing kicks in. Mirrors `recurring_wedge.DEFAULT_MIN_RECURRENCE` (a cause
# is "recurring" at 2 occurrences) so the two thresholds agree by construction.
DEFAULT_MIN_COALESCE_RUN = 2

# Families whose archives carry the per-run no-op cycle. `next-up` / `replan`
# bookkeeping has its own quiet-sweep shape (already NOOP-gated for push) but does
# NOT form the same prior-commit-amend cycle — a replan's commit legitimately
# follows a dispatch archive and must not absorb it. So only the two dispatch
# archive families coalesce.
_COALESCING_FAMILIES = frozenset({"dispatch", "dispatch-loop"})


@dataclass(frozen=True)
class PriorCommit:
    """The single prior commit the write step read with one `git log -1`.

    Every field is parsed from the committed subject at the I/O edge — the kernel
    never reads git. `is_coalesced` / `coalesce_count` let a THIRD consecutive
    no-op extend an ALREADY-coalesced commit (×2 → ×3) rather than starting a new
    coalesced commit beside it.
    """

    family: str  # the dispatch family the prior subject led with ("" if not ours)
    severity: str  # the Severity value the prior event classified to ("" if unknown)
    cause_key: str  # the opaque cause the prior no-op carried ("" if none / not ours)
    is_coalesced: bool = False  # was the prior commit itself an ×N coalesced archive?
    coalesce_count: int = 1  # the ×N already folded into the prior commit (≥1)


@dataclass(frozen=True)
class ChurnState:
    """Everything the coalesce decision needs — the current event + the prior commit.

    `event` is the SAME `EventState` the write step already built for the push
    gate (so severity is computed once, here, not re-derived). `cause_key` is the
    current event's opaque cause (from `unstick_audit.classify_cause` over the
    Outcome cell, or "" when the host did not classify one — an unkeyed no-op
    never coalesces, since we cannot prove it is the *same* cause as the prior).
    `prior` is the parsed prior commit (None when there is no prior commit, e.g.
    the very first archive on a fresh branch).
    """

    event: EventState
    cause_key: str
    prior: PriorCommit | None
    min_coalesce_run: int = DEFAULT_MIN_COALESCE_RUN


@dataclass(frozen=True)
class CoalesceVerdict:
    """Whether — and how — to coalesce. PURE given the `ChurnState`.

    `coalesce` is the load-bearing field the write step branches on: True →
    `git commit --amend` (fold this run's pathspec into the prior commit), False →
    a normal new `git commit`. `recurrence` is the ×N to stamp into the amended
    subject (the count INCLUDING this occurrence). `subject_suffix` is the ready
    `×N (recurring, coalesced)` tail the write step appends to the family-prefixed
    subject so the rendered headline is mechanical (no model retype, no ordinal —
    the `subject_lead_token` discipline). `reason` is operator-facing telemetry.
    """

    coalesce: bool
    recurrence: int
    subject_suffix: str
    reason: str


def _is_noop_dispatch_archive(ev: EventState) -> bool:
    """True iff `ev` is a dispatch-family archive that classifies NOOP — the only
    event eligible to coalesce. A SHIPPED pick or a first-seen BLOCKED-NEW blocker
    is operator-relevant and must keep its own standalone commit."""
    fam = (ev.family or "").strip().lower()
    if fam not in _COALESCING_FAMILIES:
        return False
    return classify_event(ev) is Severity.NOOP


def decide_coalesce(state: ChurnState) -> CoalesceVerdict:
    """Decide whether the current archive should fold into the prior commit.

    The rule, in order:

      1. The current event must be a NOOP dispatch archive (a 0-pick
         blocker/drain). A SHIPPED or first-seen BLOCKED-NEW event never
         coalesces — it is what the operator wants to SEE in the log.
      2. It must carry a cause_key. An unkeyed no-op cannot be proven to be the
         *same* cause as the prior commit, so it stands alone (fail-safe: when in
         doubt, do not merge — a separate commit is always correct, just noisier).
      3. The prior commit must be a SAME-family, SAME-cause NOOP archive. Same
         family AND same opaque cause_key is the "this is the same cycle
         repeating" signal. (A different cause, or a SHIPPED/replan/next-up
         commit in between, breaks the run — the new no-op starts fresh.)
      4. The recurrence (prior's folded count + 1) must reach `min_coalesce_run`.
         The default 2 means the first no-op stands alone and the second folds
         into it (→ ×2); a third extends the already-coalesced commit (→ ×3).

    PURE — no I/O. `Severity` is computed via the shared `classify_event`, so the
    coalesce decision and the push gate can never disagree about NOOP-ness.
    """
    ev = state.event
    cause = (state.cause_key or "").strip()

    if not _is_noop_dispatch_archive(ev):
        return CoalesceVerdict(
            coalesce=False, recurrence=1, subject_suffix="",
            reason="not a no-op dispatch archive — stands alone (operator-relevant)",
        )
    if not cause:
        return CoalesceVerdict(
            coalesce=False, recurrence=1, subject_suffix="",
            reason="no-op carries no cause_key — cannot prove same-cause, stands alone",
        )

    prior = state.prior
    if prior is None:
        return CoalesceVerdict(
            coalesce=False, recurrence=1, subject_suffix="",
            reason="no prior commit to coalesce into — first archive stands alone",
        )

    prior_fam = (prior.family or "").strip().lower()
    prior_cause = (prior.cause_key or "").strip()
    prior_sev = normalize_token(prior.severity) or ""

    same_family = prior_fam in _COALESCING_FAMILIES
    same_cause = bool(prior_cause) and prior_cause == cause
    prior_is_noop = prior_sev == Severity.NOOP.value

    if not (same_family and prior_is_noop and same_cause):
        return CoalesceVerdict(
            coalesce=False, recurrence=1, subject_suffix="",
            reason=(
                "prior commit is not a same-family same-cause no-op archive "
                f"(prior family={prior_fam or 'none'} sev={prior_sev or 'none'} "
                f"cause={prior_cause or 'none'} vs this cause={cause}) - stands alone"
            ),
        )

    # The run continues: this is the (prior.coalesce_count + 1)-th consecutive
    # same-cause no-op. The prior count is ≥1 (a plain prior no-op counts as 1).
    recurrence = max(1, prior.coalesce_count) + 1
    if recurrence < state.min_coalesce_run:
        return CoalesceVerdict(
            coalesce=False, recurrence=recurrence, subject_suffix="",
            reason=(
                f"recurrence {recurrence} < min_coalesce_run "
                f"{state.min_coalesce_run} — stands alone"
            ),
        )

    return CoalesceVerdict(
        coalesce=True,
        recurrence=recurrence,
        # The `[cause:<key>]` token makes the coalesced subject SELF-DESCRIBING:
        # the next no-op's prior-commit parse recovers the cause from this token
        # (the original Outcome prose is gone once the subject collapses to the
        # `blocked ×N` headline, so prose-classifying the coalesced subject would
        # lose the cause and break the run at ×N+1). The host renders the suffix
        # verbatim into the amended subject; the bridge parses `[cause:…]` back.
        subject_suffix=f"×{recurrence} (recurring, coalesced) [cause:{cause}]",
        reason=(
            f"same-cause no-op '{cause}' repeats (×{recurrence}) — "
            "amend prior commit instead of adding a new one"
        ),
    )

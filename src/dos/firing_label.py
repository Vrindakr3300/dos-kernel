"""firing-label — turn each detector FIRING into a labeled (signal, ground-truth) point (docs/179).

> **The kernel already mints one git-authored label per phase (`oracle.is_shipped`).
> This module mints a SECOND, different kind of label for free: it joins a detector
> firing (an env/agent-authored event) to the run's git-minted outcome (a fact the
> judged agent did not author), producing a `(signal, was-it-real)` point the
> detector line is scored on — lift + false-alarm. It is the one fold in the
> docs/179 set that mints NEW ground truth, because it joins two independently-authored
> facts that were never compared before.**

The detector line (`tool_stream` / `terminal_error` / `dangling` / `precursor`,
docs/145/158/173) is scored by LIFT and FALSE-ALARM rate, not recall (a 76%-fail
bench makes recall meaningless — see the docs/159 naive-baseline result). Those two
numbers need LABELED firings: each time a detector fired, was it a true catch or a
false alarm? Today those labels come from hand-curated offline benchmark replays
(docs/158-163, 174, 177) — a tiny, expensive, static set. This module turns every
live run into a small batch of such labels, drawn from data the kernel already has.

The fold, stated plainly
=========================

A `DetectorFiring` is "detector D fired signal S at step N of run R." Its label is
the run's GIT-MINTED outcome read off `trace.TraceFrame` — never the agent's
`claimed` self-report (the docs/138 byte-author invariant; `StepRow.claimed_sha`
is shown by `trace` but is NEVER read here). `label_firings` joins each firing to
its run's frame and emits one `LabeledPoint` with a closed `LabelOutcome`:

  * **TRUE_POSITIVE**  — the detector fired AND the run's git-minted outcome
                         confirms the no-progress the detector accused: the run has
                         a non-empty residual (declared steps the kernel never
                         verified) and produced no commits since its start_sha. The
                         stall was real; the run did not recover. A true catch.
  * **FALSE_ALARM**    — the detector fired BUT the run's git-minted outcome shows
                         progress: the run verified at least one declared step OR
                         landed at least one commit since start. The loop was not
                         terminally stuck (a legitimate poll, an eventual-consistency
                         wait that resolved, a stall the agent recovered from). The
                         false-alarm count the detector is penalized on.
  * **UNVERIFIABLE**   — the firing joined to a run, but the run carries NO
                         git-minted ground truth to judge against: no INTENT
                         declared (nothing to have a residual of) and no commits.
                         Refuse-don't-guess — we will NOT call an unjudgeable firing
                         a TP or an FP (the §5a optimism trap, inverted).
  * **BROKEN_LINK**    — the firing carries no `run_id` (a pre-docs/179 record, or a
                         hook fired outside a DOS spine), so it cannot be joined to a
                         frame at all. Counted, never guessed onto a run by time (the
                         docs/118/137 "fail toward no-match" rule). The honest
                         coverage tally.

The ground-truth rule is deliberately RUN-TERMINAL, and its bias is named, not
buried: it judges a firing against the run's eventual verified-vs-declared state,
so it is most meaningful on runs that reached a terminal verdict (a long-lived run
still in flight reads as UNVERIFIABLE until it declares/verifies/commits). That
selection bias toward terminal runs is reported (`LabelSummary.unverifiable`), not
hidden — the docs/159 "no silent caps" discipline. A future phase can sharpen TP/FP
with a TIMESTAMP join (did progress land BEFORE or AFTER the firing's step), using
the `ts` the Phase-0 record already stamps; v1 is the conservative terminal rule.

Why the multiplier is honest (1-3×, not 5-15×)
==============================================

A single REPEATING→STALLED run on the SAME stuck step is ONE firing, not many: the
Phase-0 sensor stamps `verdict_state` on a record only when it fired, and a run of
identical steps is the same `(tool, args, result)` triple — `dedupe_firings`
collapses consecutive same-`(run_id, signal, args/result identity)` firings to one
labeled point. So the audited `8bd8c736` read-loop (22 identical reads) mints
EXACTLY ONE `LabeledPoint`, not 22 — re-counting one stall as 22 labels would be
the consistency-not-grounding sin (one env fact counted many times is fake data).
The honest yield is ~1 label per DISTINCT detector-fired step that has a verified
side — typically 1-3 per run. That is still a real, free gain over the 1-label/phase
baseline, and every point has clean provenance.

⚓ Kernel discipline (the litmus): PURE Layer-1 leaf — `label_firings`/`dedupe_firings`
are state-in / frozen-verdict-out, zero I/O (the firings + the `TraceFrame` are
gathered at the caller boundary, exactly as `liveness.classify` takes a pre-read
`ProgressEvidence`). It imports only `trace` (for the `TraceFrame`/`StepRow` types it
folds) + stdlib, names no host/driver, carries no policy. The label is read off the
git-minted columns of `TraceFrame`; `claimed_sha` is never consulted.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Iterable, Optional

from dos.trace import TraceFrame

# The durable_schema floor (docs/116 §6): a LabeledPoint is a record the detector
# eval reads, so it carries a schema tag. Additive fields do not bump it.
FIRING_LABEL_SCHEMA = 1


# ---------------------------------------------------------------------------
# The firing — one detector event, the agent/env-authored INPUT to the join.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DetectorFiring:
    """One detector firing — "detector `detector` fired `signal` at step `step_index`".

    The INPUT half of the join. Every field is gathered at the boundary from the
    durable firing record the Phase-0 sensor stamps (`posttool_sensor._step_entry`'s
    `run_id`/`step_index`/`verdict_state`), or from any other detector's equivalent
    record. NONE of these fields is a ground-truth LABEL — they are what the detector
    SAID; the label comes from the run's git-minted outcome, joined in `label_firings`.

      * `run_id`     — the spine id joining this firing to its run's `TraceFrame`.
                       Empty/None → `BROKEN_LINK` (cannot join; never time-guessed).
      * `detector`   — which detector fired ("tool_stream", "terminal_error", …).
      * `signal`     — the detector's verdict value ("REPEATING"/"STALLED"/…).
      * `step_index` — the 0-based ordinal within the run's stream where it fired
                       (the durable position, for dedup + a future timestamp join).
      * `identity`   — an optional opaque repeat-identity (e.g. the env-authored
                       `result_digest`) so two firings on the SAME stuck step collapse
                       to one labeled point. Defaults to the step_index when absent.
    """

    run_id: str
    detector: str
    signal: str
    step_index: int = -1
    identity: str = ""

    def _dedup_key(self) -> tuple[str, str, str, str]:
        """The key two firings must share to be 'the same firing' (dedup). Uses the
        repeat-identity when present (so a 22-read stall is one key regardless of
        step_index), else falls back to the step_index (distinct steps stay distinct)."""
        ident = self.identity or f"@{self.step_index}"
        return (self.run_id, self.detector, self.signal, ident)


# ---------------------------------------------------------------------------
# The label — the closed OUTCOME vocabulary + the labeled point.
# ---------------------------------------------------------------------------
class LabelOutcome(str, enum.Enum):
    """The closed outcome of joining a firing to its run's git-minted ground truth.

    A label, never an optimism: `UNVERIFIABLE`/`BROKEN_LINK` are first-class refusals
    (we decline to call an unjudgeable firing a catch), the same fail-toward-no-match
    posture the kernel takes everywhere it lacks evidence."""

    TRUE_POSITIVE = "TRUE_POSITIVE"
    FALSE_ALARM = "FALSE_ALARM"
    UNVERIFIABLE = "UNVERIFIABLE"
    BROKEN_LINK = "BROKEN_LINK"


@dataclass(frozen=True)
class LabeledPoint:
    """One (firing, git-minted-outcome) calibration point — the fold's unit of NEW data.

    `firing` is what the detector said; `outcome` is the git-authored verdict on it;
    `reason` names the rung that produced the label (the provenance the verdict must
    carry). `ground_truth` is the compact evidence the label stands on (verified
    count / residual size / commit count) so the eval is auditable. This is the
    `(signal, was-it-real)` row the detector line is scored on."""

    firing: DetectorFiring
    outcome: LabelOutcome
    reason: str = ""
    ground_truth: dict = field(default_factory=dict)
    schema: int = FIRING_LABEL_SCHEMA

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "run_id": self.firing.run_id,
            "detector": self.firing.detector,
            "signal": self.firing.signal,
            "step_index": self.firing.step_index,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "ground_truth": dict(self.ground_truth),
        }


@dataclass(frozen=True)
class LabelSummary:
    """The confusion-grid fold over many `LabeledPoint`s — the detector-eval headline.

    `false_alarm_rate` is over the JUDGEABLE points only (TP + FP), the honest
    denominator (an UNVERIFIABLE/BROKEN_LINK firing is neither a catch nor a false
    alarm). `coverage` is the share of firings that were judgeable at all — the
    selection-bias the run-terminal rule introduces, reported not hidden."""

    points: tuple[LabeledPoint, ...]

    def _count(self, outcome: LabelOutcome) -> int:
        return sum(1 for p in self.points if p.outcome is outcome)

    @property
    def true_positives(self) -> int:
        return self._count(LabelOutcome.TRUE_POSITIVE)

    @property
    def false_alarms(self) -> int:
        return self._count(LabelOutcome.FALSE_ALARM)

    @property
    def unverifiable(self) -> int:
        return self._count(LabelOutcome.UNVERIFIABLE)

    @property
    def broken_links(self) -> int:
        return self._count(LabelOutcome.BROKEN_LINK)

    @property
    def judgeable(self) -> int:
        """Points with a real label (TP or FP) — the denominator for the rates."""
        return self.true_positives + self.false_alarms

    @property
    def false_alarm_rate(self) -> Optional[float]:
        """FP / (TP + FP) — None when nothing was judgeable (refuse a 0/0 number)."""
        j = self.judgeable
        return (self.false_alarms / j) if j else None

    @property
    def coverage(self) -> Optional[float]:
        """Judgeable / total firings — how much of the firing stream got a real label.
        None on an empty input (no firings to cover)."""
        return (self.judgeable / len(self.points)) if self.points else None

    def to_dict(self) -> dict:
        return {
            "total": len(self.points),
            "true_positives": self.true_positives,
            "false_alarms": self.false_alarms,
            "unverifiable": self.unverifiable,
            "broken_links": self.broken_links,
            "judgeable": self.judgeable,
            "false_alarm_rate": self.false_alarm_rate,
            "coverage": self.coverage,
        }


# ---------------------------------------------------------------------------
# The pure fold — firings + a TraceFrame in, labeled points out. No I/O.
# ---------------------------------------------------------------------------
def dedupe_firings(firings: Iterable[DetectorFiring]) -> tuple[DetectorFiring, ...]:
    """Collapse firings that are 'the same firing' to ONE (order-preserving). PURE.

    Two firings with the same `_dedup_key` — same run, detector, signal, and
    repeat-identity — are one event seen twice (a REPEATING that became STALLED on the
    same stuck step; a 22-read loop). Keeping only the FIRST is what makes the
    multiplier honest: one stall is one labeled point, never N (the consistency-not-
    grounding guard). Distinct steps / distinct identities are preserved.
    """
    seen: set[tuple[str, str, str, str]] = set()
    out: list[DetectorFiring] = []
    for f in firings:
        k = f._dedup_key()
        if k in seen:
            continue
        seen.add(k)
        out.append(f)
    return tuple(out)


def _ground_truth(trace: TraceFrame) -> dict:
    """The compact git-minted evidence a label stands on. PURE — reads only the
    git-authored columns of the frame (verified steps, residual, commits); the
    `claimed_sha` column is NEVER read (the byte-author invariant)."""
    verified = sum(1 for s in trace.steps if s.state == "VERIFIED")
    return {
        "has_intent": bool(trace.has_intent),
        "verified_steps": verified,
        "declared_steps": len(trace.steps),
        "residual": len(trace.residual),
        "commits_since_start": len(trace.commits),
    }


def label_one(firing: DetectorFiring, trace: Optional[TraceFrame]) -> LabeledPoint:
    """Label ONE firing against its run's git-minted ground truth. PURE.

    The labeling ladder (refuse before you guess):

      1. No `run_id` on the firing → BROKEN_LINK (cannot join; never time-guessed).
      2. No frame / `found == False` for the run → BROKEN_LINK (the run left no
         surface to join to — same fail-toward-no-match).
      3. The run has NO git-minted ground truth (no INTENT and no commits) →
         UNVERIFIABLE (nothing to judge the firing against; we refuse to call it).
      4. The run made git-minted PROGRESS (a verified step OR a commit since start) →
         FALSE_ALARM (the loop the detector accused was not terminally stuck).
      5. Else (a residual remains and no commits landed) → TRUE_POSITIVE (the
         no-progress the detector accused is confirmed by git).

    Rules 4/5 read ONLY the git-authored side of the frame. A run that verified a
    step or landed a commit demonstrably advanced — so the stall accusation was a
    false alarm — regardless of what the agent CLAIMED. A run that declared work,
    verified none of it, and committed nothing is the stall the detector caught.
    """
    if not firing.run_id:
        return LabeledPoint(firing, LabelOutcome.BROKEN_LINK,
                            reason="firing carries no run_id — cannot join to a run "
                                   "(pre-docs/179 record or non-spine hook)")
    if trace is None or not trace.found:
        return LabeledPoint(firing, LabelOutcome.BROKEN_LINK,
                            reason=f"no surface found for run {firing.run_id} "
                                   f"(no run.json / intent ledger / WAL event)")

    gt = _ground_truth(trace)
    verified = gt["verified_steps"]
    commits = gt["commits_since_start"]
    residual = gt["residual"]

    if not trace.has_intent and commits == 0:
        return LabeledPoint(
            firing, LabelOutcome.UNVERIFIABLE, ground_truth=gt,
            reason="run declared no intent and landed no commits — no git-minted "
                   "ground truth to judge the firing against (refuse, don't guess)")

    if verified > 0 or commits > 0:
        return LabeledPoint(
            firing, LabelOutcome.FALSE_ALARM, ground_truth=gt,
            reason=f"run made git-minted progress ({verified} step(s) verified, "
                   f"{commits} commit(s) since start) — the loop was not terminally "
                   f"stuck; the firing was a false alarm")

    return LabeledPoint(
        firing, LabelOutcome.TRUE_POSITIVE, ground_truth=gt,
        reason=f"run verified 0 of its declared steps and landed 0 commits; "
               f"{residual} step(s) remain unverified — the no-progress the detector "
               f"accused is confirmed by git (a true catch)")


def label_firings(
    firings: Iterable[DetectorFiring],
    frame_for,
    *,
    dedupe: bool = True,
) -> tuple[LabeledPoint, ...]:
    """Label a batch of firings against their runs' ground truth. PURE.

    `frame_for` is a callable `run_id -> TraceFrame | None` the caller supplies — the
    boundary that did the `trace.build_trace` I/O (kept OUT of this fold, the
    state-in/verdict-out rule). It may return None for an unknown run (→ BROKEN_LINK).
    `dedupe` collapses same-firing duplicates first (the honest-multiplier guard);
    pass False only to inspect raw firings.

    Returns one `LabeledPoint` per (deduped) firing — the calibration batch this run
    contributed to the detector line. Wrap in `LabelSummary` for the confusion grid.
    """
    fs = dedupe_firings(firings) if dedupe else tuple(firings)
    out: list[LabeledPoint] = []
    cache: dict[str, Optional[TraceFrame]] = {}
    for f in fs:
        if f.run_id and f.run_id not in cache:
            cache[f.run_id] = frame_for(f.run_id)
        trace = cache.get(f.run_id)
        out.append(label_one(f, trace))
    return tuple(out)

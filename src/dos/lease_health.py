"""lease_health — pure verdicts over lease + child-run liveness facts.

Lifted from the job userland's ``scripts/fanout_state.py`` (MQ3X P2, docs/62).
Two ``classify`` verdicts in the ``liveness`` / ``health`` mold — facts in, a
typed verdict out, the clock injected, no I/O:

  * ``classify_lease_health`` — combine a lease's heartbeat age with an
    already-probed ``activity_state`` into a LANE-LEASE verdict
    (LIVE / STALLED / ORPHANED_WORKING / DEAD). The host does the FS activity
    probe and passes the resulting string in; this decides reclaim-vs-keep.
  * ``classify_child_stall`` — the AST4 child-stall guard: given a child run's
    log-quiet age, the HEAD-sha delta since the last check, and the archive-sha
    set, decide ALIVE / DEAD / DOUBLE_ARCHIVE before a /dispatch-loop takeover.

Plus ``parse_iso`` — the minute-OR-second ISO stamp parser the lease stack needs
(both resolutions the host stamp and a journal ``replay()`` produce). Generic,
clock-free; lives here because ``classify_lease_health`` is its first kernel use.

Mechanism-not-policy: the TTL / stall windows are job tuning, supplied on a
frozen ``LeaseHealthPolicy`` (defaults reproduce the job's historical constants);
the child-stall quiet window is a ``classify_child_stall`` parameter. The
verdict STRINGS (LEASE_* / CHILD_*) are the kernel's stable vocabulary.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

# --- lease-health verdict vocabulary --------------------------------------
LEASE_LIVE = "LIVE"
LEASE_STALLED = "STALLED"
LEASE_ORPHANED_WORKING = "ORPHANED_WORKING"
LEASE_DEAD = "DEAD"

# --- child-stall verdict vocabulary ---------------------------------------
CHILD_ALIVE = "alive"
CHILD_DEAD = "dead"
CHILD_DOUBLE_ARCHIVE = "double-archive"
# A child that is STILL ALIVE (log growing and/or HEAD advancing) but whose
# every registered pick is already an ancestor of HEAD — i.e. the productive
# work is durable in git and the continued aliveness is pure waste (the
# post-commit re-verify / re-commit limit-cycle). The upper skill should
# TaskStop it and classify the iteration from git ancestry, not keep waiting.
CHILD_CHURNING = "child-churning"


def parse_iso(s: str) -> _dt.datetime | None:
    """Parse an ISO stamp → aware UTC datetime; None on malformed input.

    Accepts BOTH resolutions the lane stack produces:
      * minute  ``%Y-%m-%dT%H:%MZ``    — the host stamp, the common case;
      * second  ``%Y-%m-%dT%H:%M:%SZ`` — what a journal ``replay()`` writes into
        a reconstructed lease's ``heartbeat_at``.
    Accepting the second form is FORWARD-SAFETY, not cosmetics: a replay-restored
    second-resolution ``heartbeat_at`` fed back to a minute-only parser returns
    None, which makes the TTL backstop silently skip — an immortal-by-TTL lease.
    The minute branch is tried first so the hot path is unchanged; second is a
    strict superset, so existing minute-resolution callers are unaffected.
    """
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return _dt.datetime.strptime(s, fmt).replace(tzinfo=_dt.timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


@dataclass(frozen=True)
class LeaseHealthPolicy:
    """The TTL + stall windows that separate the lease-health verdicts — policy.

    Defaults reproduce the job's historical constants exactly (LANE_LEASE_TTL =
    50 min, stall threshold = 8 min), so a caller passing ``DEFAULT_POLICY`` (or
    nothing) is byte-identical to the pre-lift code.

      ttl_minutes             — past this heartbeat age the lease is unambiguously
                                DEAD (the hard TTL backstop, wins over activity).
      stall_threshold_minutes — at or below this, the lease is LIVE; between this
                                and the TTL the activity probe decides
                                STALLED-vs-ORPHANED_WORKING.
    """

    ttl_minutes: float = 50.0
    stall_threshold_minutes: float = 8.0

    def __post_init__(self) -> None:
        if self.ttl_minutes < 0 or self.stall_threshold_minutes < 0:
            raise ValueError("lease-health windows must be non-negative (minutes)")


DEFAULT_POLICY = LeaseHealthPolicy()


def classify_lease_health(
    lease: dict,
    *,
    now: _dt.datetime,
    activity_state: str,
    policy: LeaseHealthPolicy = DEFAULT_POLICY,
) -> str:
    """Pure classifier — combine heartbeat age + activity state into a verdict.

    Inputs are the (already-computed) ``activity_state`` and the lease's
    heartbeat, so the function is unit-testable without any filesystem I/O.

    Returns one of ``LEASE_LIVE`` / ``LEASE_STALLED`` / ``LEASE_ORPHANED_WORKING``
    / ``LEASE_DEAD``.

      * No timestamp at all → treat as immediately stale (age = inf): a malformed
        lease must not block forever.
      * age > ttl → DEAD (hard backstop).
      * age ≤ stall_threshold → LIVE.
      * stall_threshold < age ≤ ttl → the activity probe decides:
          LIVE_DOWNSTREAM / UNKNOWN → ORPHANED_WORKING (never reclaim on missing
          evidence); QUIET → STALLED (genuinely dead → reclaim).
    """
    hb = parse_iso(lease.get("heartbeat_at", "") or lease.get("acquired_at", ""))
    if hb is None:
        age_min = float("inf")
    else:
        age_min = (now - hb).total_seconds() / 60.0
    if age_min > policy.ttl_minutes:
        return LEASE_DEAD
    if age_min <= policy.stall_threshold_minutes:
        return LEASE_LIVE
    if activity_state == "LIVE_DOWNSTREAM":
        return LEASE_ORPHANED_WORKING
    if activity_state == "UNKNOWN":
        return LEASE_ORPHANED_WORKING
    # activity_state == "QUIET" — genuinely dead.
    return LEASE_STALLED


@dataclass
class ChildStallResult:
    """Typed verdict of the AST4 child-stall guard — what /dispatch-loop's upper
    skill should do before taking over a child /dispatch's Steps 8-9.

    ``verdict`` is one of CHILD_ALIVE / CHILD_DEAD / CHILD_DOUBLE_ARCHIVE /
    CHILD_CHURNING.
    ``log_age_seconds`` is how long the log has been quiet (None if absent).
    ``archive_count`` is the number of archive commits seen for the run-ts.
    ``shipped_pick_count`` / ``registered_pick_count`` are the ancestry facts
    that drive the CHURNING verdict (how many of this run's registered picks are
    already ancestors of HEAD, vs how many it registered). Both 0 on a path that
    did not supply them, so the churn check is inert unless the caller measured.
    ``reason`` is a one-line human explanation.
    """

    verdict: str
    log_age_seconds: float | None = None
    log_grew: bool = False
    new_commit: bool = False
    archive_count: int = 0
    archive_shas: list[str] | None = None
    shipped_pick_count: int = 0
    registered_pick_count: int = 0
    reason: str = ""

    def __post_init__(self) -> None:
        if self.archive_shas is None:
            self.archive_shas = []

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "log_age_seconds": self.log_age_seconds,
            "log_grew": self.log_grew,
            "new_commit": self.new_commit,
            "archive_count": self.archive_count,
            "archive_shas": self.archive_shas,
            "shipped_pick_count": self.shipped_pick_count,
            "registered_pick_count": self.registered_pick_count,
            "reason": self.reason,
        }


def classify_child_stall(
    *,
    log_age_seconds: float | None,
    last_commit_sha: str | None,
    current_head_sha: str | None,
    archive_shas: list[str] | None = None,
    quiet_window_s: float = 600.0,
    registered_pick_count: int = 0,
    shipped_pick_count: int = 0,
) -> ChildStallResult:
    """PURE verdict logic for the AST4 child-stall guard. No I/O — every input is
    a pre-collected fact, the typed verdict is returned.

    Decision order:
      1. double-archive first — if the child already shipped its archive, the
         takeover is moot regardless of liveness; reconcile to the child's.
      2. churn — the child is ALIVE (log grew and/or HEAD advanced) but every
         registered pick is already an ancestor of HEAD, so the continued
         aliveness is pure waste; TaskStop it and classify from git ancestry.
         Checked BEFORE the alive branches precisely because churn IS alive —
         the only thing separating it from healthy progress is "is the work
         already shipped", and once that holds the aliveness is definitionally
         waste. ``shipped_pick_count``/``registered_pick_count`` are the
         caller's ancestry measurement; a path that does not measure leaves
         both 0 and this branch is inert (byte-identical to the old behaviour).
      3. log-grew (a-fail) → alive. A growing log is unambiguous liveness.
      4. new-commit-since-last-check (b-fail) → alive. The child committed.
      5. BOTH quiet AND no new commit → dead; takeover may proceed.

    ``quiet_window_s`` default (600s) matches the job's
    CHILD_STALL_QUIET_WINDOW_SECONDS; override for tests / operator tuning.

    The churn check's kill-safety rests on the caller's ``shipped_pick_count``
    being NEVER-OVER-counted (a foreign-lane commit in the window must not
    inflate it); the job's ``ship_oracle.ancestry_ship_count`` guarantees that
    (it counts only commits whose subject names a registered phase AND that are
    ancestors of HEAD). With ``shipped < registered`` the verdict falls through
    to alive — a still-producing child is never killed.
    """
    shas = [s for s in (archive_shas or []) if s]
    if len(set(shas)) >= 2:
        return ChildStallResult(
            CHILD_DOUBLE_ARCHIVE, log_age_seconds=log_age_seconds,
            archive_count=len(set(shas)), archive_shas=shas,
            shipped_pick_count=shipped_pick_count,
            registered_pick_count=registered_pick_count,
            reason=(f"{len(set(shas))} archive commits exist for this run-ts "
                    f"({', '.join(s[:8] for s in sorted(set(shas)))}) — child "
                    f"self-recovered and shipped its own archive; reconcile to "
                    f"the child's artefacts, do NOT produce a competing one."))
    # (a) log-growth test: a log that grew within the quiet window → alive.
    log_grew = log_age_seconds is not None and log_age_seconds < quiet_window_s
    # (b) new-commit test: a commit since the last check → still committing.
    new_commit = bool(
        current_head_sha and last_commit_sha
        and current_head_sha != last_commit_sha
    )
    # Churn: alive (by either signal) AND every registered pick already shipped.
    # registered_pick_count > 0 guards against the no-picks iteration (a drain /
    # a /replan has nothing to ship, so it can never be "all shipped").
    work_all_shipped = (
        registered_pick_count > 0
        and shipped_pick_count >= registered_pick_count
    )
    if work_all_shipped and (log_grew or new_commit):
        signal = "writing" if log_grew else "committing"
        return ChildStallResult(
            CHILD_CHURNING, log_age_seconds=log_age_seconds,
            log_grew=log_grew, new_commit=new_commit,
            archive_count=len(set(shas)), archive_shas=shas,
            shipped_pick_count=shipped_pick_count,
            registered_pick_count=registered_pick_count,
            reason=(f"all {registered_pick_count} registered pick(s) are "
                    f"ancestors of HEAD ({shipped_pick_count} shipped) yet the "
                    f"child is still {signal} — post-commit churn, not progress; "
                    f"TaskStop it and classify the iteration from git ancestry."))
    if log_grew:
        return ChildStallResult(
            CHILD_ALIVE, log_age_seconds=log_age_seconds, log_grew=True,
            archive_count=len(set(shas)), archive_shas=shas,
            shipped_pick_count=shipped_pick_count,
            registered_pick_count=registered_pick_count,
            reason=(f"child log grew {log_age_seconds:.0f}s ago "
                    f"(< {quiet_window_s:.0f}s quiet window) — still writing, "
                    f"not stalled."))
    if new_commit:
        return ChildStallResult(
            CHILD_ALIVE, log_age_seconds=log_age_seconds, new_commit=True,
            archive_count=len(set(shas)), archive_shas=shas,
            shipped_pick_count=shipped_pick_count,
            registered_pick_count=registered_pick_count,
            reason=(f"HEAD advanced {last_commit_sha[:8]} → "
                    f"{current_head_sha[:8]} since last check — child still "
                    f"committing, not stalled."))
    # Both signals quiet → genuinely dead; the takeover precondition holds.
    age_txt = (f"quiet {log_age_seconds:.0f}s" if log_age_seconds is not None
               else "log absent")
    return ChildStallResult(
        CHILD_DEAD, log_age_seconds=log_age_seconds,
        archive_count=len(set(shas)), archive_shas=shas,
        shipped_pick_count=shipped_pick_count,
        registered_pick_count=registered_pick_count,
        reason=(f"child genuinely dead: {age_txt} (≥ {quiet_window_s:.0f}s "
                f"window) AND no new commit since last check — takeover of "
                f"Steps 8-9 may proceed."))

"""dos.drivers.watchdog — the push-model supervisor that polls `liveness()`.

`liveness.classify` (docs/82) mints the in-flight verdict — is THIS run ADVANCING,
SPINNING, or STALLED? — but it is a *pull* verdict: something has to ask it. The
self-stop seam (`loop_decide.StopReason.SPINNING`) lets a loop ask it about itself;
the stop-recorder (`lane_lease.halt`) lets a verb record a stop decision. What was
still missing is the actor that asks the question **on a timer, from outside the
watched run's own process** — and acts on the answer. This driver is that actor.

It directly answers the most expensive incident in the historical record
(docs/99 §2.1): eight jobs hung ~4.4 h each because the wall-clock budget fired
2.2 h late — the orchestrator loop stalled inside a long poll, so the timer meant
to kill the stuck run never got a turn. The fix is structural: a poller in its OWN
process, whose clock keeps ticking no matter what the watched runs do. That is why
the watchdog is a separate long-lived process, not a callback the dispatch loop
runs on itself (the thing that already failed).

## Why this is a DIFFERENT driver from `drivers/supervisor.py`

Two axes, deliberately kept apart (docs/101 §1):

  * `supervisor.py` — the POPULATION axis. `supervise()` → is the roster full?
    SPAWN free lanes / REAP STALLED *leases* / FLAG spinners. It frees a lane so a
    replacement can take it; it does NOTHING about a spinner beyond FLAG, because a
    spinner still holds a live lease and the supervisor has no standing to halt a
    peer's control flow (docs/99 §3.1).
  * `watchdog.py` (THIS) — the PER-RUN-HEALTH axis. `liveness.classify` → is THIS
    run moving? A SPINNING / hung-past-budget run → record an `OP_HALT` and propose
    the stop command. The operator delegated the watchdog to watch a NAMED set of
    runs, so (unlike the supervisor over a peer) it has standing to record the stop
    decision and propose the kill.

The §2.1 incident is a per-run-health failure, not a population one: the roster was
*full* (eight workers alive); a supervisor would have reported AT_TARGET. Each of
those runs was hung, and the timer was asleep inside their loop. The watchdog,
independent by construction, is immune to that.

## The actuation boundary holds (docs/99 §3, §5)

"Auto-halt-record" means the watchdog itself calls `lane_lease.halt` to RECORD the
`OP_HALT` and EMIT the host-supplied stop command — so the proposed stop is one
paste away (in the journal + the `dos decisions` queue). It does NOT mean the
watchdog kills anything: `lane_lease.halt` records intent and proposes a command
and NEVER signals a process, because *delivering* the signal requires knowing what
the opaque `handle` IS (a pid? a container? a remote task?), and that domain
knowledge is a driver's, never a domain-free kernel's. The watchdog (a driver)
*could* in principle carry that knowledge — but it deliberately does not: it stops
at the propose line, exactly where the supervisor stops (journal the decision, let
a human/driver enact). Enacting the kill is a separate, even-more-host-specific
act left to the operator's paste or a further driver that consumes `OP_HALT`. This
driver NEVER calls `os.kill`/`subprocess`/`TaskStop` (pinned by
`test_watchdog_proposes_does_not_signal`).

## Structure (testable without real I/O — the supervisor-driver idiom)

`assess_run(cfg, tracked, *, now_ms)` is NEAR-PURE: it gathers this run's evidence
by calling the SAME boundary helpers `cmd_liveness` uses (`cli._git_delta_count`,
`cli._journal_delta`, `run_id.ts_ms_of`) and returns `liveness.classify(...)` — NO
effects, and no re-implementation of the git/journal rungs (the LVN-1b no-drift
rule: the watchdog's verdict can never diverge from `dos liveness`). `tick(...)`
calls `assess_run` per run, applies the verdict→action map, and records an
`OP_HALT` (via the injectable `halt`) for each run that warrants one. `run(...)`
loops `tick` + sleep on a long cadence. Tests drive `assess_run`/`tick` with the
evidence helpers and `halt` monkeypatched, so no real git, no real journal, no
real `claude`, and `os.kill`/`Popen` can be made to raise to prove they are never
called.
"""

from __future__ import annotations

import subprocess  # noqa: F401 — imported so a test can monkeypatch it to prove we never Popen
import time
from dataclasses import dataclass, field
from typing import Optional

from dos import config as _config
from dos import lane_lease, liveness, run_id

DEFAULT_INTERVAL_S = 300.0        # a watchdog wakes rarely — not a busy-poll
# One halt proposal per genuine spin episode, not one per tick. A SPINNING run
# stays SPINNING across many ticks; without this memory the watchdog would append
# an OP_HALT every tick forever. A run that recovers to ADVANCING is dropped from
# `proposed`, so a later re-spin earns a fresh proposal. Long by default — a halt
# proposal is not something to spam.
DEFAULT_REPROPOSE_MS = 1_800_000  # 30 min


@dataclass(frozen=True)
class TrackedRun:
    """One run the watchdog watches — the tuple `liveness.classify` needs, plus the
    opaque stop handle/command the proposal carries.

      run_id       — the CID token; decodes `run_started_ms` (the clock is free in
                     the token). REQUIRED — a run with no valid run-id is skipped.
      start_sha    — the git SHA the run started at (the commit-rung floor). "" ⇒
                     the commit rung is silent (0 commits) and the run is judged on
                     the journal rung alone (the discovered-run honest floor).
      lane/loop_ts — the lease's `(loop_ts, lane)` identity; both required for the
                     journal rung to be attributed to this run (the LVN P2
                     identity rule). Also carried onto the OP_HALT for correlation.
      handle       — the OPAQUE stop handle (a pid string / container id / task
                     token). The kernel records it verbatim, interprets nothing.
                     Defaults to the lease pid when discovered; "" is recorded fine.
      budget_ms    — wall-clock budget. A STALLED run past it → halt; within it →
                     not yet (the grace guard, lifted to the budget axis). None ⇒
                     no budget, so any STALLED run is treated as past-budget (a
                     hung run with no declared budget is still hung).
      stop_command — the host-supplied stop command echoed in the OP_HALT proposal
                     (the paste-to-stop). "" records the proposal with no command
                     (the operator supplies the kill by hand).
    """

    run_id: str
    start_sha: str = ""
    lane: str = ""
    loop_ts: str = ""
    handle: str = ""
    budget_ms: Optional[int] = None
    stop_command: str = ""


@dataclass
class WatchActions:
    """What a tick did — the audit record a test asserts on."""

    proposed_halts: list[str] = field(default_factory=list)   # run-ids an OP_HALT was recorded for
    advancing: list[str] = field(default_factory=list)        # run-ids classified ADVANCING
    spinning: list[str] = field(default_factory=list)         # run-ids classified SPINNING
    stalled_within_budget: list[str] = field(default_factory=list)  # STALLED but too young to halt
    skipped: list[str] = field(default_factory=list)          # bad run-id / unclassifiable


def assess_run(cfg, tracked: TrackedRun, *, now_ms: int) -> Optional[liveness.LivenessVerdict]:
    """Classify ONE tracked run's liveness — NEAR-PURE (the testable seam).

    Gathers this run's evidence by calling the SAME boundary helpers `cmd_liveness`
    uses, so the watchdog's verdict can NEVER drift from `dos liveness` (the LVN-1b
    no-drift rule): the start ms decodes from the run-id, the commit rung is
    `cli._git_delta_count(start_sha)`, the journal rung is `cli._journal_delta(...)`
    scoped to this run's `(loop_ts, lane)` lease. No effects. Returns None for a run
    whose run-id is not a valid CID token (it cannot be timed, so it is skipped).
    """
    from dos import cli  # consumer→consumer import (a driver may import the CLI)

    started_ms = run_id.ts_ms_of(tracked.run_id)
    if started_ms is None:
        return None

    # The commit rung. A run with no start SHA has no commit-delta floor, so the
    # rung is silent (0) and the journal rung carries the signal — the discovered-
    # run honest floor (`_supervise_evidence` lives with the same: "a live lease
    # records no start SHA, so the commit rung is 0").
    commits = cli._git_delta_count(tracked.start_sha, cfg) if tracked.start_sha else 0

    # The journal rung — scoped to THIS run's lease; identity required (the LVN P2
    # rule). Without both lane and loop_ts the journal cannot be attributed to this
    # run, so the rung stays silent (events 0, no journal heartbeat) and the commit
    # rung + age decide.
    lease_key = (
        (tracked.loop_ts, tracked.lane)
        if tracked.lane and tracked.loop_ts
        else None
    )
    jd = cli._journal_delta(cfg, started_ms=started_ms, now_ms=now_ms, lease_key=lease_key)

    ev = liveness.ProgressEvidence(
        run_started_ms=started_ms,
        now_ms=now_ms,
        commits_since_start=commits,
        journal_events_since=jd.events_since_start,
        last_heartbeat_age_ms=jd.newest_heartbeat_age_ms,
        tokens_spent_since=None,
    )
    return liveness.classify(ev)


def _run_age_ms(tracked: TrackedRun, now_ms: int) -> Optional[int]:
    """`now_ms − run_started_ms`, clamped at 0; None for a bad run-id."""
    started_ms = run_id.ts_ms_of(tracked.run_id)
    if started_ms is None:
        return None
    return max(0, now_ms - started_ms)


def _warrants_halt(tracked: TrackedRun, verdict: liveness.Liveness, *, now_ms: int) -> bool:
    """The §3 verdict→action map: does this run warrant an OP_HALT THIS tick?

      ADVANCING                          -> no  (the run is moving)
      SPINNING                           -> yes (alive but landing zero delta — the
                                                 textbook hung-but-narrating shape)
      STALLED, age < budget_ms           -> no  (too young — the grace guard)
      STALLED, age >= budget_ms / no budget -> yes (the §2.1 case: hung past budget)
    """
    if verdict == liveness.Liveness.SPINNING:
        return True
    if verdict == liveness.Liveness.STALLED:
        if tracked.budget_ms is None:
            return True  # no declared budget — a hung run is still hung
        age = _run_age_ms(tracked, now_ms)
        if age is None:
            return True  # cannot age it (shouldn't happen post-assess) — fail toward halt
        return age >= tracked.budget_ms
    return False  # ADVANCING (or an unknown future verdict — never auto-halt on it)


def tick(
    cfg,
    tracked_runs,
    *,
    now_ms: int,
    proposed: dict,
    repropose_ms: int = DEFAULT_REPROPOSE_MS,
    halt=lane_lease.halt,
) -> "tuple[dict, WatchActions]":
    """One watchdog tick: assess each tracked run, record an OP_HALT for the ones
    that warrant one (auto-halt-record + emit-command), return (verdicts, actions).

    Mutates `proposed` in place: records each proposal's ms; DROPS a run that
    recovered to ADVANCING (so a later re-spin earns a fresh proposal). The
    idempotence guard — at most one OP_HALT per run per `repropose_ms` window —
    bounds the journal to one record per genuine spin episode, not one per poll.

    `halt` is injectable (defaults to the kernel boundary verb `lane_lease.halt`,
    which records the OP_HALT + proposes the command and NEVER signals) so a test
    can assert the proposal without a real journal write, and can monkeypatch
    `os.kill`/`subprocess` to raise and prove the watchdog never calls them.
    """
    actions = WatchActions()
    verdicts: dict = {}

    for tracked in tracked_runs:
        verdict = assess_run(cfg, tracked, now_ms=now_ms)
        if verdict is None:
            actions.skipped.append(tracked.run_id)
            continue
        verdicts[tracked.run_id] = verdict
        v = verdict.verdict

        # 1. Tally the verdict + handle the ADVANCING (recovered) case.
        if v == liveness.Liveness.ADVANCING:
            actions.advancing.append(tracked.run_id)
            # Recovered — drop any prior proposal memory so a later re-spin can be
            # re-proposed (the recovered-run-can-be-reproposed property).
            proposed.pop(tracked.run_id, None)
            continue
        if v == liveness.Liveness.SPINNING:
            actions.spinning.append(tracked.run_id)

        # 2. The §3 warrant decision. A STALLED run too young for its budget is
        # tallied as within-budget and skipped; everything else that doesn't
        # warrant a halt (an unknown future verdict) just continues.
        if not _warrants_halt(tracked, v, now_ms=now_ms):
            if v == liveness.Liveness.STALLED:
                actions.stalled_within_budget.append(tracked.run_id)
            continue

        # 3. Idempotence: at most one proposal per run per repropose window.
        last = proposed.get(tracked.run_id)
        if last is not None and (now_ms - last) < repropose_ms:
            continue

        reason = (
            f"watchdog: {v.value} "
            f"({'no forward delta' if v == liveness.Liveness.SPINNING else 'hung past budget'})"
        )
        try:
            halt(
                cfg,
                handle=tracked.handle,
                lane=tracked.lane,
                loop_ts=tracked.loop_ts,
                owner="watchdog",
                reason=reason,
                run_id=tracked.run_id,
                command=tracked.stop_command or None,
            )
            proposed[tracked.run_id] = now_ms
            actions.proposed_halts.append(tracked.run_id)
        except Exception:  # noqa: BLE001 — a failed record is non-fatal; retry next tick
            pass

    return verdicts, actions


def discover_tracked_runs(cfg, *, budget_ms: Optional[int] = None) -> "list[TrackedRun]":
    """Fold the live-lease set into tracked runs (the --discover mode, docs/101 §2).

    Read-only: replays the lane journal's live leases (`lane_lease.live_leases`) and
    derives `lane`/`loop_ts`/`handle`(pid) from each. A discovered run carries NO
    start SHA (a journal lease records none — the honest floor), so it is judged on
    the journal rung alone; that is strictly weaker but never wrong. The lease's
    `loop_ts` doubles as a stand-in run-id ONLY if it parses as a CID token; a lease
    whose `loop_ts` is not a run-id is skipped here (it cannot be timed by
    `liveness`), the no-plan-per-run degrade. A host that wants the commit rung
    passes an explicit `TrackedRun` with a real run-id + start SHA instead.
    """
    out: list[TrackedRun] = []
    try:
        leases = lane_lease.live_leases(cfg)
    except Exception:  # noqa: BLE001 — a bad journal yields no discovered runs
        return out
    for l in leases:
        loop_ts = str(l.get("loop_ts") or "")
        # A discovered run needs a CID-shaped identity to be timed. Prefer an
        # explicit run_id on the lease; fall back to loop_ts only if it decodes.
        rid = str(l.get("run_id") or "")
        if run_id.ts_ms_of(rid) is None:
            rid = loop_ts if run_id.ts_ms_of(loop_ts) is not None else ""
        if not rid:
            continue
        out.append(
            TrackedRun(
                run_id=rid,
                start_sha="",  # the honest floor: a lease records no start SHA
                lane=str(l.get("lane") or ""),
                loop_ts=loop_ts,
                handle=str(l.get("pid") or ""),
                budget_ms=budget_ms,
                stop_command="",
            )
        )
    return out


def run(
    config=None,
    *,
    tracked_runs,
    interval: float = DEFAULT_INTERVAL_S,
    max_ticks: Optional[int] = None,
    repropose_ms: int = DEFAULT_REPROPOSE_MS,
    clock_ms=None,
    sleep=time.sleep,
    halt=lane_lease.halt,
) -> int:
    """Run the watchdog until `max_ticks` or an operator interrupt.

    Each tick assesses every tracked run and records an OP_HALT for the ones that
    warrant one, then sleeps `interval` (long — a watchdog, not a busy-poll). The
    clock keeps ticking in THIS process no matter what the watched runs do — the
    structural independence that answers the §2.1 budget-late incident.
    `clock_ms`/`sleep`/`halt` are injectable for deterministic, journal-free tests.
    `tracked_runs` is fixed for the life of the run (a host re-launches `run` to
    change the set, or passes a callable — kept simple here: a fixed list). Returns
    0 on a clean stop.
    """
    cfg = config if config is not None else _config.active()
    runs = list(tracked_runs)
    proposed: dict = {}
    ticks = 0
    _clock = clock_ms if clock_ms is not None else (lambda: int(time.time() * 1000))
    try:
        while max_ticks is None or ticks < max_ticks:
            now_ms = _clock()
            tick(cfg, runs, now_ms=now_ms, proposed=proposed,
                 repropose_ms=repropose_ms, halt=halt)
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            sleep(interval)
    except KeyboardInterrupt:
        return 0
    return 0

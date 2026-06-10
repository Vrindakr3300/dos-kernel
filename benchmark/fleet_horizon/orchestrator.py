"""The orchestrator seam — make the DRIVER a comparable, pluggable thing.

The first FleetHorizon axis was *trust*: believe self-reports (open loop) vs
adjudicate them with the kernel (closed loop). This module adds the **orchestrator**
axis the operator asked for: the *driver loop* — DOS-native fanout/dispatch vs a
harness/ultracode-style `Workflow` — is itself a pluggable policy, and **both drive
the SAME trust seam** (`arbiter.arbitrate` + `oracle.is_shipped`), so they are
directly comparable on one workload (`docs/98`).

The insight that makes this clean: DOS already splits *mechanism* (the pure
syscalls) from *policy* (the loop around them). So the orchestrator is just another
policy occupying the slot the dispatch skill occupies — and the **one thing that
actually differs** between a DOS-native loop and a harness `parallel()` is *how the
live-lease set is shared between concurrent units of work*:

  * **DOS-native dispatch** runs the fleet in one process and threads `live_leases`
    as an in-memory list (what `closed_loop.py` does): when effort-B arbitrates, it
    sees effort-A's still-held lease *immediately*, so a colliding write is REFUSED
    at contention.

  * **A harness/ultracode flow** fans out concurrent units that do NOT share memory
    (separate `Workflow` branches / separate `dos` invocations). The only honest
    cross-unit channel is the durable lane-journal WAL (`dos lease-lane`). If a unit
    *writes its grant back* before a sibling arbitrates (`writeback=True`, the
    disciplined harness that uses `dos lease-lane acquire`), the sibling sees it and
    the collision is PREVENTED — identical safety to the in-process loop. If it does
    NOT (`writeback=False`, the naive harness that just runs `agent({schema})` in
    `parallel()` and forgets the lease), two siblings arbitrate against a stale view,
    BOTH admit a colliding tree, and the collision is only DETECTED later by
    `verify` — strictly weaker.

So the orchestrator axis reduces to a single, faithfully-modeled variable — the
**lease-visibility model** — captured by the `LeaseBook` protocol below. Everything
else (the workload, the seeded failure model, the real git repo, the kernel calls,
the scorer) is shared verbatim with `closed_loop.py`, so any measured difference is
*purely* the orchestrator's, not a different agent or a different scorer (the
honesty invariant, lifted to this axis).

`LeaseBook` is the seam; `InProcessLeaseBook` and `JournalLeaseBook` are the two
drivers. `closed_loop.run` is the DOS-native arm (in-process); `harness_loop.run`
is the harness/ultracode arm (journal-backed, `writeback`-tunable). Both call
`run_fleet` here — one loop body, two lease books.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Callable, Protocol

from dos import arbiter, oracle, run_id, lane_journal, scope, liveness
from dos.config import SubstrateConfig

from . import metrics
from .agent import FailureModel
from .metrics import Event, Metrics, score
from .trajectory import TrajectoryStep, step_from_claim
from .workload import Workload, interleave, Phase


# --------------------------------------------------------------------------
# The lease-visibility seam — the ONE thing the orchestrator axis varies.
# --------------------------------------------------------------------------
class LeaseBook(Protocol):
    """How concurrent units of work share the live-lease set.

    The whole orchestrator difference lives here. `visible()` returns the leases a
    unit can see when it arbitrates; `record(lease, step)` registers a grant;
    `expire(step)` drops leases whose in-flight window has elapsed. A DOS-native
    loop implements these over an in-memory list (instant visibility); a harness
    flow implements them over the durable WAL with a `writeback` discipline that
    can LAG visibility — which is exactly the gap the benchmark measures.
    """

    def visible(self, step: int) -> list[dict]:
        """The live leases this unit can see right now (pre-arbitrate)."""
        ...

    def record(self, lease: dict, step: int, *, writeback: bool) -> None:
        """Register a granted lease. `writeback` controls whether it becomes
        visible to siblings BEFORE this unit's own work (the disciplined harness)
        or only after (the naive one / the in-process loop's natural behavior)."""
        ...

    def expire(self, step: int) -> None:
        """Drop leases whose in-flight window has elapsed at `step`."""
        ...

    def reset(self) -> None:
        """Clear all leases (used at the drain boundary)."""
        ...


@dataclasses.dataclass
class InProcessLeaseBook:
    """DOS-native dispatch: leases live in an in-memory list, instantly visible.

    This is exactly what `closed_loop.py` does inline — when effort-B arbitrates it
    sees effort-A's still-in-flight lease in the same list, so a collision is
    refused at contention. There is no visibility lag: a grant is visible to the
    next arbitrate the instant it is recorded. `writeback` is irrelevant here (a
    single process always shares memory), so it is ignored — the in-process loop is
    the upper bound the harness arm is measured against.
    """

    _leases: list[dict] = dataclasses.field(default_factory=list)

    def visible(self, step: int) -> list[dict]:
        return list(self._leases)

    def record(self, lease: dict, step: int, *, writeback: bool = True) -> None:
        self._leases.append(lease)

    def expire(self, step: int) -> None:
        self._leases = [l for l in self._leases if l.get("_expires_at", 0) > step]

    def reset(self) -> None:
        self._leases = []


@dataclasses.dataclass
class JournalLeaseBook:
    """Harness/ultracode flow: leases shared ONLY through the durable WAL.

    Models concurrent `Workflow` branches that do not share memory. `visible()`
    folds the lane-journal (`lane_journal.replay`) — the same durable channel
    `dos lease-lane live` exposes — so a sibling learns a grant only if it was
    written back to the WAL. The `writeback` discipline is the measured knob:

      * writeback=True  — `record` journals the ACQUIRE immediately (the disciplined
        harness that calls `dos lease-lane acquire` before doing work). A sibling's
        next `visible()` sees it → collision PREVENTED, matching the in-process book.

      * writeback=False — `record` defers the journal append until AFTER the unit's
        work (the naive harness that runs `agent()` in `parallel()` and only records
        the lease post-hoc, if at all). Within the in-flight window a sibling
        arbitrates against a STALE journal that does not yet contain the grant, so
        BOTH admit a colliding tree → collision DETECTED later by verify, not
        prevented. The `_pending` list holds not-yet-visible grants and is flushed
        to the WAL on `expire` (their work has completed).

    Uses a real lane journal at `journal_path` (the same file `dos lease-lane`
    writes), so this arm exercises the genuine cross-process surface, not a mock.
    """

    journal_path: Path
    writeback: bool = True
    _pending: list[dict] = dataclasses.field(default_factory=list)

    def visible(self, step: int) -> list[dict]:
        entries = lane_journal.read_all(self.journal_path)
        durable = lane_journal.replay(entries)
        # the durable WAL view is what a separate process sees; pending (not-yet-
        # written-back) grants are invisible to siblings — that is the lag.
        return durable

    def record(self, lease: dict, step: int, *, writeback: bool | None = None) -> None:
        wb = self.writeback if writeback is None else writeback
        entry = lane_journal.acquire_entry(lease, reason="harness-flow")
        if wb:
            lane_journal.append(entry, self.journal_path)  # visible NOW
        else:
            self._pending.append(lease)  # invisible until expire flushes it

    def expire(self, step: int) -> None:
        # flush pending grants whose window has elapsed (their work is done, so the
        # lease now lands in the WAL — too late to have prevented a collision).
        still_pending = []
        for lease in self._pending:
            if lease.get("_expires_at", 0) <= step:
                lane_journal.append(
                    lane_journal.acquire_entry(lease, reason="harness-flow-late"),
                    self.journal_path)
                lane_journal.append(
                    lane_journal.release_entry(lease, reason="window-elapsed"),
                    self.journal_path)
            else:
                still_pending.append(lease)
        self._pending = still_pending

    def reset(self) -> None:
        self._pending = []


# --------------------------------------------------------------------------
# Per-step liveness/scope verdicts (reused verbatim from closed_loop's discipline)
# --------------------------------------------------------------------------
_LIVENESS_NOW = liveness.DEFAULT_POLICY.grace_ms + 1
_LIVENESS_HEARTBEAT_FRESH = 0


def _step_verdicts(claim, lane: str, cfg: SubstrateConfig) -> tuple[str, str]:
    """The (scope, advancing) verdict pair — a pure projection over claim/cfg, the
    same one closed_loop uses, so the trajectory is identical across orchestrators."""
    scope_v = scope.classify(scope.ScopeEvidence(
        touched_files=frozenset(claim.wrote_files),
        lane_tree=tuple(cfg.lanes.trees.get(lane, ("**/*",))),
        lane=lane,
    ))
    live_v = liveness.classify(liveness.ProgressEvidence(
        run_started_ms=0,
        now_ms=_LIVENESS_NOW,
        commits_since_start=1 if claim.really_committed else 0,
        last_heartbeat_age_ms=_LIVENESS_HEARTBEAT_FRESH,
    ))
    return scope_v.verdict.value, live_v.verdict.value


# --------------------------------------------------------------------------
# The shared fleet loop — ONE body, parameterized by the lease book.
# --------------------------------------------------------------------------
def run_fleet(
    workload: Workload,
    model: FailureModel,
    *,
    arm: str,
    lease_book: LeaseBook,
    git_repo: "GitGround",
    cfg: SubstrateConfig,
    run_seed: int,
    kappa: float = metrics.DEFAULT_KAPPA,
    review_mu: float = metrics.DEFAULT_REVIEW_MU,
    detect_after: bool = False,
    sink: Callable[[TrajectoryStep], None] | None = None,
) -> tuple[Metrics, list[Event]]:
    """Drive the fleet through the kernel, sharing leases via `lease_book`.

    This is the body both `closed_loop.run` (in-process book) and `harness_loop.run`
    (journal book) call. The ONLY behavioral differences between the two arms come
    from the lease book's visibility model and the `detect_after` flag:

      * `detect_after=False` (DOS-native): a refused write is DEFERRED and drained
        later on a split footprint — no data loss, the collision is PREVENTED.
      * `detect_after=True` (naive harness): because the lease book lagged, two
        units both ADMIT a colliding tree; after both commit, a post-hoc footprint
        check flags the double-write as a DETECTED-after collision (and, if both
        really committed to the same shared file, a surviving SILENT-OVERWRITE that
        even verify cannot undo — you cannot un-clobber after the fact).

    Ground truth is the real git repo (`git_repo`); a lie is "claimed shipped, no
    commit", hand-checkable. Same scorer as every other arm.
    """
    events: list[Event] = []
    emit = sink if sink is not None else (lambda _s: None)
    workers = {e.name: model.worker(e.name) for e in workload.efforts}

    registry: dict = {"recently_completed": []}
    grep_fb = git_repo.grep_fallback()

    root_rid = run_id.mint(f"fleet-{arm}")
    effort_rids = {e.name: run_id.mint(e.name, parent=root_rid,
                                       root_id=root_rid.run_id)
                   for e in workload.efforts}

    deferred: dict[str, list] = {e.name: [] for e in workload.efforts}
    really_shipped: set[tuple[str, str]] = set()
    lane_of = {e.name: e.lane for e in workload.efforts}
    window = max(1, workload.n_efforts - 1)

    # for detect_after: the shared files written while in-flight, to spot a
    # post-hoc double-write the lagging lease book failed to prevent.
    shared_inflight: dict[str, list[tuple[str, int]]] = {}

    def _record_shared_write(effort: str, files, step: int) -> list[str]:
        """Return the shared files this write CLOBBERED (concurrent in-flight writer
        from another effort) — the detection the naive harness does after the fact."""
        clobbered: list[str] = []
        for f in files:
            if not f.startswith("shared/"):
                continue
            holders = [(e, x) for (e, x) in shared_inflight.get(f, []) if x > step]
            if any(e != effort for (e, x) in holders):
                clobbered.append(f)
            holders.append((effort, step + window))
            shared_inflight[f] = holders
        return clobbered

    for step, phase in enumerate(interleave(workload, seed=run_seed)):
        w = workers[phase.effort]
        key = (phase.effort, phase.phase_id)
        lane = lane_of[phase.effort]
        lease_book.expire(step)

        claim = w.attempt(phase, already_shipped=(key in really_shipped))
        events.append(Event("action", phase.effort, phase.phase_id))
        if w.will_thrash():
            events.append(Event("action", phase.effort, phase.phase_id))
            events.append(Event("thrash", phase.effort, phase.phase_id))

        # ---- ARBITRATE against the lease book's CURRENT view ----
        live = lease_book.visible(step)
        decision = arbiter.arbitrate(
            requested_lane=lane,
            requested_kind="keyword",
            requested_tree=list(phase.touches),
            live_leases=live,
            config=cfg,
        )
        candidate_lease = {
            "lane": decision.lane or lane, "lane_kind": "keyword",
            "tree": list(phase.touches), "effort": phase.effort,
            "loop_ts": f"{arm}-{phase.effort}",
            "holder": phase.effort,
            "run_id": effort_rids[phase.effort].run_id,
            "_expires_at": step + window,
        }

        if decision.outcome == "refuse":
            # the kernel refused at contention — the lease book showed the conflict.
            # DOS-native: defer + drain (prevented). This path fires when the lease
            # book made the sibling's lease VISIBLE in time.
            events.append(Event("refused-write", phase.effort, phase.phase_id,
                                detail=decision.reason))
            deferred[phase.effort].append((phase, claim, decision.reason))
            continue

        # admitted — record the grant (writeback discipline decides sibling visibility)
        lease_book.record(candidate_lease, step, writeback=None
                          if isinstance(lease_book, JournalLeaseBook) else True)

        # ---- do the work; commit FOR REAL only if it really shipped ----
        if claim.really_committed:
            # under detect_after, check whether this admitted write CLOBBERS a
            # concurrent in-flight shared write (the collision the lag let through).
            clobbered = _record_shared_write(
                phase.effort, claim.wrote_files, step) if detect_after else []
            sha = git_repo.real_commit(phase, claim.wrote_files)
            events.append(Event("real-ship", phase.effort, phase.phase_id))
            really_shipped.add(key)
            registry["recently_completed"].insert(0, {
                "plan": phase.effort, "phase": phase.phase_id,
                "status": "done", "commit_sha": sha,
            })
            for f in clobbered:
                # a collision DETECTED after the fact (not prevented). If the
                # clobbered file was a real concurrent write, the earlier writer's
                # content is gone — a surviving silent overwrite verify can't undo.
                events.append(Event("detected-collision", phase.effort,
                                    phase.phase_id, detail=f))
                events.append(Event("silent-overwrite", phase.effort,
                                    phase.phase_id, detail=f"{f} (post-hoc)"))
                events.append(Event("conflict-detonation", phase.effort,
                                    phase.phase_id))
        if claim.is_rework:
            events.append(Event("rework", phase.effort, phase.phase_id))

        # ---- VERIFY against ground truth (don't believe) ----
        verdict = oracle.is_shipped(
            phase.effort, phase.phase_id, state=registry, grep_fallback=grep_fb)
        if verdict.shipped:
            events.append(Event("banked-shipped", phase.effort, phase.phase_id))
        elif claim.claimed_shipped:
            events.append(Event("caught-lie", phase.effort, phase.phase_id))
            events.append(Event("human-review", phase.effort, phase.phase_id))

        sc_v, live_v = _step_verdicts(claim, lane, cfg)
        emit(step_from_claim(
            step=step, claim=claim,
            run_id=effort_rids[phase.effort].run_id, root_id=root_rid.run_id,
            verdict_shipped=verdict.shipped, verdict_source=verdict.source,
            arbiter_outcome="acquire",
            verdict_in_scope=sc_v, verdict_advancing=live_v,
        ))

    # ---- drain deferred (collision-rescheduled) phases on a split footprint ----
    lease_book.reset()
    for effort, items in deferred.items():
        for phase, claim, refusal_reason in items:
            events.append(Event("action", effort, phase.phase_id))
            key = (effort, phase.phase_id)
            private = tuple(f for f in phase.touches if not f.startswith("shared/"))
            if claim.really_committed:
                sha = git_repo.real_commit(phase, private)
                events.append(Event("real-ship", effort, phase.phase_id))
                really_shipped.add(key)
                registry["recently_completed"].insert(0, {
                    "plan": effort, "phase": phase.phase_id,
                    "status": "done", "commit_sha": sha,
                })
            verdict = oracle.is_shipped(effort, phase.phase_id,
                                        state=registry, grep_fallback=grep_fb)
            if verdict.shipped:
                events.append(Event("banked-shipped", effort, phase.phase_id))
            elif claim.claimed_shipped:
                events.append(Event("caught-lie", effort, phase.phase_id))
                events.append(Event("human-review", effort, phase.phase_id))

            sc_v, live_v = _step_verdicts(claim, lane_of[effort], cfg)
            emit(step_from_claim(
                step=-1, claim=claim,
                run_id=effort_rids[effort].run_id, root_id=root_rid.run_id,
                verdict_shipped=verdict.shipped, verdict_source=verdict.source,
                arbiter_outcome="refuse", refusal_reason=refusal_reason,
                verdict_in_scope=sc_v, verdict_advancing=live_v,
            ))

    return score(arm, events, total_phases=workload.total_phases,
                 horizon=workload.n_phases_each, kappa=kappa,
                 review_mu=review_mu), events


# --------------------------------------------------------------------------
# The git ground-truth helper (factored out of closed_loop so both arms share it)
# --------------------------------------------------------------------------
import os
import subprocess
import tempfile


class GitGround:
    """A real git repo as ground truth — shared by every adjudicating arm.

    Factored verbatim out of `closed_loop.py` so the DOS-native and harness arms
    use the IDENTICAL ground-truth machinery (a lie is "claimed, no commit",
    hand-checkable). Construct it, use `real_commit`/`grep_fallback`, then `close`.
    """

    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fleet_orch_"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self._init_repo()

    def _git(self, *args: str) -> str:
        res = subprocess.run(["git", *args], cwd=str(self.repo),
                             capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
        return res.stdout.strip()

    def _init_repo(self) -> None:
        self._git("init", "-q")
        self._git("config", "user.email", "fleet@bench.local")
        self._git("config", "user.name", "FleetBench")
        self._git("config", "commit.gpgsign", "false")
        (self.repo / "README.md").write_text("fleet orchestrator bench\n",
                                             encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "root: init")

    def real_commit(self, phase: Phase, files) -> str:
        for rel in files:
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(f"{phase.effort} {phase.phase_id}\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", f"{phase.effort}: {phase.phase_id} — ship")
        return self._git("rev-parse", "--short", "HEAD")

    def grep_fallback(self):
        repo = self.repo

        def fallback(plan: str, phase: str) -> oracle.ShipVerdict:
            token = f"{phase} — ship"
            try:
                out = subprocess.run(
                    ["git", "log", "--all", "--grep", token, "--format=%h %s", "-1"],
                    cwd=str(repo), capture_output=True, text=True, timeout=15)
            except (subprocess.TimeoutExpired, OSError):
                return oracle.ShipVerdict(plan=plan, phase=phase, shipped=False,
                                          source="grep")
            line = out.stdout.strip()
            if out.returncode == 0 and line and token in line:
                return oracle.ShipVerdict(plan=plan, phase=phase, shipped=True,
                                          sha=line.split(" ", 1)[0], source="grep")
            return oracle.ShipVerdict(plan=plan, phase=phase, shipped=False,
                                      source="grep")
        return fallback

    def close(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

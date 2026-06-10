"""sibling_scan — the pure "is another run going to collide with me?" verdicts.

A host's dispatch loop spawns headless children and runs alongside sibling
loops. Three concurrency questions arise, all **domain-free pure verdicts** over
caller-gathered evidence — the `gate_classify.classify_packet` shape: facts in,
a typed verdict out, no I/O, no clock read (the clock is injected):

  1. ORPHAN SWEEP (`scan_for_orphan`) — after an iteration, is any child run-dir
     a *live process nobody is waiting on* (a parent turn ended mid-flight)? A
     run-dir is an ORPHAN iff it has no terminal marker, its log is still
     growing, it is not the current iteration's own child, and it is owned by
     this loop. A live markerless child this loop did NOT spawn is FOREIGN_LIVE
     (record, never adopt — adopting would corrupt that invocation's handoff).

  2. FOREIGN COLLISION (`classify_foreign_collision`) — given the FOREIGN_LIVE
     children, would this loop's next iteration actually *collide* with one? Only
     if a foreign child's lane tree overlaps this loop's lane (or is unknown /
     exclusive). Disjoint lanes run concurrently — the intended fan-out.

  3. SIBLING SCAN (`classify_sibling_scan`) — at startup, after taking a lease,
     is there an un-leased *live* sibling loop the arbiter cannot see (a bare
     `/dispatch`, a manual run)? If so: clear (disjoint), reroute (bare loop →
     free lane), or stop (exclusive sibling, or an explicit-scope loop that must
     not be silently moved).

THE BOUNDARY — what is kernel vs host (so "kernel imports no host" holds):

  * KERNEL (here): the three verdict ladders + the disjointness escape (via the
    sibling-kernel `dos._tree.lane_trees_disjoint`, the same arrow `arbiter` and
    `lane_overlap` use). Evidence is FROZEN DATA: a `RunDirState` carries a
    precomputed `has_terminal_marker` BOOL — the host computes it from ITS stamp
    grammar (the `Saved:` / `docs/fanout:` / `docs/dispatch: archive` markers) at
    the boundary, so the kernel never holds a host marker literal. The
    free-lane pool and the lane→tree lookups are caller-supplied.
  * HOST (the caller): the dir-globbing (`docs/_chained_runs/` etc.), the
    log-tail/mtime reads, the terminal-marker grammar that computes
    `has_terminal_marker`, the auto-pick cluster pool, and the lane→tree map.

⚓ Evidence-over-narrative: every verdict is derived from filesystem artefacts
(a marker bool, a log mtime, a lane tree) the caller gathered — never from a
`result`-envelope prose read.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from dos._tree import lane_trees_disjoint, tree_disjoint_from_all_live

# Default staleness window (seconds). A log whose last write is older than this
# is treated as "not growing" — the process is presumed dead, not orphaned-live.
DEFAULT_STALENESS_S = 90.0

# Default un-leased-sibling liveness window (minutes). A sibling whose newest log
# is older than this is too quiet to be a live collision.
DEFAULT_SIBLING_LIVENESS_WINDOW_MIN = 30.0


def iter_index(iter_dir_name: str) -> int:
    """Sort key for an ``iter-<n>`` dir name (MQ3X P2 lift). Non-numeric tails
    sort LAST (10**9, not 0 — that silently buckets a malformed dir as iteration
    0 and could mask the real highest iteration). Generic dir-name integer
    parse: no host marker grammar, no I/O — the one sibling-dir classifier that
    is genuinely kernel-pure (the README *text* classifiers hold the host's
    verdict-stamp grammar and stay host-side, per this module's boundary §)."""
    tail = iter_dir_name.split("-")[-1]
    return int(tail) if tail.isdigit() else 10**9


# ===========================================================================
# 1. Orphan sweep
# ===========================================================================


class OrphanStatus(str, enum.Enum):
    """The verdict `scan_for_orphan` returns for one run-dir scan.

    `str`-valued so it round-trips as a token into a tally row or log line,
    the same idiom as `gate_classify` verdicts.
    """

    ORPHAN = "ORPHAN"
    FOREIGN_LIVE = "FOREIGN_LIVE"
    TERMINAL = "TERMINAL"
    DEAD = "DEAD"
    CLEAN = "CLEAN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class RunDirState:
    """A snapshot of one child run-dir, collected by the caller.

    The caller does the I/O (globs the run-dirs, reads each log's tail + mtime,
    and — crucially — computes `has_terminal_marker` from ITS OWN stamp grammar)
    and passes these frozen facts here. The scan touches no filesystem and knows
    no host marker literal.

    Fields:
      ts                   — the run-dir's UTC timestamp id, for the operator string.
      has_terminal_marker  — True iff the child reached a closeout (the host
                             checked its log tail against its terminal markers).
      log_mtime_epoch      — the child log's last-modified time (epoch seconds).
      is_current_iteration — True iff this is the iteration the loop is
                             legitimately mid-wait on (never an orphan).
      log_present          — False iff the run-dir has no child log yet (CLEAN).
    """

    ts: str
    has_terminal_marker: bool = False
    log_mtime_epoch: float = 0.0
    is_current_iteration: bool = False
    log_present: bool = True


@dataclass(frozen=True)
class OrphanScanResult:
    """The verdict for one run-dir plus the evidence behind it."""

    ts: str
    status: OrphanStatus
    reason: str

    @property
    def needs_adoption(self) -> bool:
        """True iff the loop must adopt this run-dir's still-live child."""
        return self.status is OrphanStatus.ORPHAN


@dataclass(frozen=True)
class OrphanSweepResult:
    """The result of scanning every run-dir the loop handed in."""

    orphans: list[OrphanScanResult] = field(default_factory=list)
    foreign_live: list[OrphanScanResult] = field(default_factory=list)
    all: list[OrphanScanResult] = field(default_factory=list)

    @property
    def has_orphan(self) -> bool:
        return bool(self.orphans)

    @property
    def has_foreign_live(self) -> bool:
        return bool(self.foreign_live)

    @property
    def summary(self) -> str:
        """One operator-facing line for the iteration's tally row."""
        if not self.all:
            return "no child run-dirs to scan — clean"
        counts: dict[str, int] = {}
        for r in self.all:
            counts[r.status.value] = counts.get(r.status.value, 0) + 1
        parts = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        tags: list[str] = []
        if self.orphans:
            tags.append(f"ADOPT: {', '.join(o.ts for o in self.orphans)}")
        if self.foreign_live:
            tags.append(f"FOREIGN: {', '.join(f.ts for f in self.foreign_live)}")
        if tags:
            return f"{parts} — " + "; ".join(tags)
        return f"{parts} — clean"


def _coerce_run_dir(obj: Any) -> RunDirState:
    """Accept a RunDirState or a plain dict (the JSON / fixture shape).

    `ts` is the only required key; everything else defaults to the safe
    ("not an orphan") value, so a partial dict degrades to CLEAN, not a false
    ORPHAN. Accepts a legacy `log_tail`+marker-list shape is NOT supported here:
    the host computes `has_terminal_marker` at the boundary (the seam change).
    """
    if isinstance(obj, RunDirState):
        return obj
    if not isinstance(obj, dict):
        raise TypeError(
            f"run-dir state must be a RunDirState or dict, got {type(obj).__name__}"
        )
    ts = obj.get("ts")
    if not ts:
        raise ValueError(f"run-dir state is missing 'ts': {obj!r}")
    return RunDirState(
        ts=str(ts),
        has_terminal_marker=bool(obj.get("has_terminal_marker", False)),
        log_mtime_epoch=float(obj.get("log_mtime_epoch", 0.0)),
        is_current_iteration=bool(obj.get("is_current_iteration", False)),
        log_present=bool(obj.get("log_present", True)),
    )


def classify_run_dir(
    state: Any,
    *,
    now_epoch: float,
    staleness_s: float = DEFAULT_STALENESS_S,
    loop_owned_ts: Optional[frozenset[str] | set[str]] = None,
) -> OrphanScanResult:
    """Classify ONE run-dir snapshot into an OrphanStatus.

    PURE — no filesystem, no clock read; the caller passes `now_epoch` once for
    the whole sweep. Decision order (most-specific first, deterministic):

      1. CLEAN        — current iteration's own child, or no log yet.
      2. TERMINAL     — `has_terminal_marker` (the host saw a closeout).
      3. DEAD         — no marker AND log idle > staleness_s.
      4. FOREIGN_LIVE — no marker AND growing AND loop_owned_ts supplied AND ts
                        NOT in it (a different invocation's live child).
      5. ORPHAN       — no marker AND growing AND (no loop_owned_ts OR ts in it).

    `loop_owned_ts=None` preserves the conservative default: every live
    markerless run-dir is ORPHAN (foreign-vs-own left to the operator).
    """
    st = _coerce_run_dir(state)

    if st.is_current_iteration or not st.log_present:
        why = (
            "current iteration's own child — legitimately mid-wait"
            if st.is_current_iteration
            else "run-dir has no child log yet — child not started"
        )
        return OrphanScanResult(ts=st.ts, status=OrphanStatus.CLEAN, reason=why)

    if st.has_terminal_marker:
        return OrphanScanResult(
            ts=st.ts, status=OrphanStatus.TERMINAL,
            reason="child log carries a closeout marker — child reached its terminal step",
        )

    age = now_epoch - st.log_mtime_epoch
    if age > staleness_s:
        return OrphanScanResult(
            ts=st.ts, status=OrphanStatus.DEAD,
            reason=(
                f"no terminal marker and log idle {age:.0f}s (> {staleness_s:.0f}s) "
                "— child died mid-run, treat as a crash"
            ),
        )

    if loop_owned_ts is not None and st.ts not in loop_owned_ts:
        return OrphanScanResult(
            ts=st.ts, status=OrphanStatus.FOREIGN_LIVE,
            reason=(
                f"no terminal marker and log written {age:.0f}s ago — a LIVE child "
                "from a different invocation (ts not in this loop's owned set); "
                "record but do NOT adopt (would corrupt that invocation's handoff)"
            ),
        )

    return OrphanScanResult(
        ts=st.ts, status=OrphanStatus.ORPHAN,
        reason=(
            f"no terminal marker and log written {age:.0f}s ago — a LIVE headless "
            "child nobody is waiting on; adopt it (arm a Monitor, take over handoff)"
        ),
    )


def scan_for_orphan(
    run_dirs: list[Any],
    *,
    now_epoch: float,
    staleness_s: float = DEFAULT_STALENESS_S,
    loop_owned_ts: Optional[frozenset[str] | set[str]] = None,
) -> OrphanSweepResult:
    """Scan every run-dir snapshot the loop collected for an orphaned child.

    PURE — `now_epoch` is required (the caller takes one `time.time()` for the
    whole sweep at the boundary). An empty `run_dirs` returns an all-clean sweep.
    See `classify_run_dir` for the per-dir decision order.
    """
    results = [
        classify_run_dir(
            d, now_epoch=now_epoch, staleness_s=staleness_s,
            loop_owned_ts=loop_owned_ts,
        )
        for d in run_dirs
    ]
    orphans = [r for r in results if r.status is OrphanStatus.ORPHAN]
    foreign = [r for r in results if r.status is OrphanStatus.FOREIGN_LIVE]
    return OrphanSweepResult(orphans=orphans, foreign_live=foreign, all=results)


# ===========================================================================
# 2. Foreign-collision verdict
# ===========================================================================


class ForeignCollisionVerdict(str, enum.Enum):
    """Whether this loop's next iteration collides with a FOREIGN_LIVE child."""

    SAFE_CONCURRENT = "SAFE-CONCURRENT"
    COLLISION = "COLLISION"
    NONE = "NONE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class ForeignCollisionResult:
    """Verdict + the offending lane (if any) for the caller to act on."""

    verdict: ForeignCollisionVerdict
    colliding_lane: str = ""
    colliding_ts: str = ""
    reason: str = ""


def classify_foreign_collision(
    *,
    foreign: list[tuple[str, str]],
    my_tree: list[str],
    lane_tree_lookup: Callable[[str], Optional[list[str]]],
    exclusive_lanes: tuple[str, ...] = ("global",),
) -> ForeignCollisionResult:
    """Decide whether a next iteration collides with any FOREIGN_LIVE child.

    PURE — no I/O. The caller resolves each foreign child's lane and passes:

      foreign           — list of (ts, lane) per FOREIGN_LIVE child.
      my_tree           — this loop's leased lane tree (file globs).
      lane_tree_lookup  — callable(lane) -> list[str] for a foreign lane's tree.
                          Returning [] (unknown) is treated as overlapping.
      exclusive_lanes   — lane names that are whole-portfolio / exclusive
                          (always COLLISION). Caller-supplied (the host passes its
                          `cfg.lanes.exclusive`); defaults to the generic `global`
                          only — a host with extra exclusive lanes (e.g.
                          `orchestration`) passes them, the kernel hardcodes none.

    Verdict (most-conservative wins; first offender drives the result):
      NONE            — no foreign children.
      COLLISION       — a foreign child shares this loop's lane, is exclusive,
                        has an unknown/empty tree, or overlaps `my_tree`.
      SAFE_CONCURRENT — every foreign child's tree is known, non-empty, AND
                        provably disjoint from `my_tree`.

    Both trees must be known and non-empty to clear — an unknown tree refuses
    (the same disjointness discipline as `classify_sibling_scan`).
    """
    if not foreign:
        return ForeignCollisionResult(
            ForeignCollisionVerdict.NONE, reason="no FOREIGN_LIVE children")
    if not my_tree:
        ts0, lane0 = foreign[0]
        return ForeignCollisionResult(
            ForeignCollisionVerdict.COLLISION, colliding_lane=lane0,
            colliding_ts=ts0,
            reason=("this loop's own lane tree is unknown — cannot prove "
                    "disjointness from any foreign child; stop (conservative)"))
    for ts, lane in foreign:
        norm = (lane or "").strip()
        if not norm or norm in exclusive_lanes:
            return ForeignCollisionResult(
                ForeignCollisionVerdict.COLLISION,
                colliding_lane=norm or "(unknown)", colliding_ts=ts,
                reason=(f"foreign child {ts} has scope {norm or '(unknown)'!r} "
                        "— unknown/whole-portfolio blast radius, not provably "
                        "disjoint; stop"))
        try:
            foreign_tree = list(lane_tree_lookup(norm) or [])
        except Exception:
            foreign_tree = []
        if not foreign_tree:
            return ForeignCollisionResult(
                ForeignCollisionVerdict.COLLISION, colliding_lane=norm,
                colliding_ts=ts,
                reason=(f"foreign child {ts} lane {norm!r} resolves to an empty "
                        "tree — unknown blast radius; stop"))
        if not lane_trees_disjoint(list(my_tree), foreign_tree):
            return ForeignCollisionResult(
                ForeignCollisionVerdict.COLLISION, colliding_lane=norm,
                colliding_ts=ts,
                reason=(f"foreign child {ts} lane {norm!r} tree overlaps this "
                        "loop's lane — a next iteration would race its "
                        "soft-claim registry; stop"))
    lanes = ", ".join(f"{ts}:{lane}" for ts, lane in foreign)
    return ForeignCollisionResult(
        ForeignCollisionVerdict.SAFE_CONCURRENT,
        reason=(f"all FOREIGN_LIVE children on disjoint lanes ({lanes}) — "
                "safe to continue concurrently (intended parallel fan-out)"))


# ===========================================================================
# 3. Un-leased-sibling scan
# ===========================================================================


@dataclass(frozen=True)
class SiblingScanResult:
    """Typed verdict of `classify_sibling_scan` — what a loop's Step 0 should do.

    `verdict` is one of:
      'clear'   — no un-leased live sibling (or a disjoint one); proceed.
      'reroute' — a live un-leased cluster/keyword sibling AND this loop was
                  bare; re-acquire excluding the sibling's lane. `sibling_lane`
                  names the lane to avoid; `free_lanes` lists pickable lanes.
      'stop'    — back out: the sibling is on an exclusive lane, OR this loop was
                  invoked with an explicit scope (don't silently move it), OR a
                  bare loop has no free lane left.
    """

    verdict: str
    sibling_ts: str = ""
    sibling_scope: str = ""
    sibling_lane: str = ""
    free_lanes: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict, "sibling_ts": self.sibling_ts,
            "sibling_scope": self.sibling_scope,
            "sibling_lane": self.sibling_lane,
            "free_lanes": list(self.free_lanes), "reason": self.reason,
        }


def _disjoint_from_all_live(
    *,
    requested_tree: list[str],
    live: list[dict],
    sibling_tree_lookup: Callable[[str], Optional[list[str]]],
) -> bool:
    """The disjointness escape's safety predicate — `requested_tree` provably
    disjoint from EVERY live sibling.

    Thin alias over `dos._tree.tree_disjoint_from_all_live` (the single, shared
    definition the lane ARBITER's selection-time filter and this post-acquire
    escape both stand on, so they cannot drift apart). Kept as a module-local name
    because this module's existing call sites and tests reference it directly.
    """
    return tree_disjoint_from_all_live(
        requested_tree=requested_tree,
        live=live,
        sibling_tree_lookup=sibling_tree_lookup,
    )


def live_siblings_subset(
    *,
    siblings: list[dict],
    leased_ts: set[str],
    now_ts: float,
    liveness_window_min: float = DEFAULT_SIBLING_LIVENESS_WINDOW_MIN,
) -> list[dict]:
    """The live, un-leased, un-completed subset of pre-collected sibling facts.

    A sibling counts as a live invisible collision iff: NOT in `leased_ts` (the
    arbiter already sees leased ones), NOT completed, and its newest log was
    touched within `liveness_window_min`. The single definition of "which
    siblings are live right now," shared by `classify_sibling_scan` (the post-
    acquire escape) and the lane ARBITER's FQ-449 selection filter (which must
    feed `tree_disjoint_from_all_live` ONLY genuinely-live siblings, else a long-
    finished run's stale fact would force every bare pick to fall back). Pure —
    `now_ts` injected at the boundary."""
    cutoff = now_ts - liveness_window_min * 60
    out: list[dict] = []
    for s in siblings:
        if s.get("ts") in leased_ts:
            continue
        if s.get("completed"):
            continue
        if (s.get("newest_log_mtime") or 0) < cutoff:
            continue
        out.append(s)
    return out


def classify_sibling_scan(
    *,
    siblings: list[dict],
    leased_ts: set[str],
    invoked_bare: bool,
    now_ts: float,
    free_lane_pool: list[str],
    requested_tree: Optional[list[str]] = None,
    sibling_tree_lookup: Optional[Callable[[str], Optional[list[str]]]] = None,
    liveness_window_min: float = DEFAULT_SIBLING_LIVENESS_WINDOW_MIN,
    exclusive_lanes: tuple[str, ...] = ("global",),
) -> SiblingScanResult:
    """PURE verdict logic for the un-leased-sibling guard. No I/O.

    `siblings` — pre-collected facts: {ts, newest_log_mtime, completed (bool),
        scope ('global'|'orchestration'|'cluster/keyword'), lane (str)}.
    `leased_ts` — loop_ts values that hold a live lease (arbiter saw them).
    `invoked_bare` — True if this loop got no explicit scope.
    `now_ts` — current epoch seconds (injected at the boundary).
    `free_lane_pool` — the caller's auto-pick lane pool a bare loop reroutes onto
        (host taxonomy — the kernel does not hardcode a cluster set).
    `requested_tree` — THIS loop's requested lane tree; enables the disjointness
        escape for BOTH scope modes (the lane's tree, known + provably disjoint
        from every live sibling). An explicit-scope loop passes its scoped tree;
        a BARE loop passes its AUTO-PICKED lane's tree (the caller resolves it
        after acquire). The escape requires disjointness from EVERY live sibling
        (`_disjoint_from_all_live`), not just `live[0]` — clearing on the first
        while colliding with the second would corrupt a real handoff.
    `sibling_tree_lookup` — callable(lane) -> tree, to evaluate disjointness.
    `liveness_window_min` — how recent a sibling's log must be to count as live.
    `exclusive_lanes` — lanes that dominate the verdict (caller-supplied).

    A sibling is a genuine invisible collision iff: not in leased_ts, not
    completed, and its newest log is within the liveness window. An exclusive
    sibling dominates (stop, regardless of trees). Otherwise the disjointness
    escape runs (clear if provably disjoint from ALL live siblings); failing
    that, a bare loop reroutes onto a free lane and an explicit-scope loop stops.
    The FIRST live sibling (exclusive-first sort) labels the verdict's evidence.
    """
    live = live_siblings_subset(
        siblings=siblings, leased_ts=leased_ts, now_ts=now_ts,
        liveness_window_min=liveness_window_min,
    )
    if not live:
        return SiblingScanResult("clear", reason="no un-leased live sibling")
    live.sort(key=lambda s: 0 if s.get("scope") in exclusive_lanes else 1)
    sib = live[0]
    sib_ts = str(sib.get("ts") or "")
    sib_scope = str(sib.get("scope") or "cluster/keyword")
    sib_lane = str(sib.get("lane") or "")
    if sib_scope in exclusive_lanes:
        return SiblingScanResult(
            "stop", sibling_ts=sib_ts, sibling_scope=sib_scope,
            sibling_lane=sib_lane,
            reason=(f"un-leased live sibling {sib_ts} holds exclusive lane "
                    f"{sib_scope!r} — this loop must not run alongside it."))
    # The disjointness escape (both scope modes). Tree-disjointness is the SOLE
    # concurrency gate everywhere else in dos (arbiter admission, the orphan
    # sweep's SAFE-CONCURRENT verdict); the sibling scan must honour it too. The
    # escape requires this loop's `requested_tree` to be provably disjoint from
    # *every* live sibling's tree — checking only `live[0]` would clear a loop
    # that collides with `live[1]`. An explicit-scope loop already passed its
    # tree in; a BARE loop passes its AUTO-PICKED lane's tree (resolved by the
    # caller after acquire) — without that, a bare loop could never run
    # concurrently even when it provably cannot collide (the 2026-06-03
    # non-converging-reroute finding: a bare loop rerouted forever off a
    # lane-less read-only `/replan` sibling it could never collide with).
    if requested_tree and sibling_tree_lookup is not None:
        if _disjoint_from_all_live(
            requested_tree=requested_tree, live=live,
            sibling_tree_lookup=sibling_tree_lookup,
        ):
            return SiblingScanResult(
                "clear", sibling_ts=sib_ts, sibling_scope=sib_scope,
                sibling_lane=sib_lane,
                reason=(f"un-leased live sibling {sib_ts} on lane {sib_lane!r} "
                        f"(+{len(live) - 1} more) but every live sibling's tree "
                        f"is disjoint from the requested lane's tree — safe to "
                        f"run concurrently."))
    if not invoked_bare:
        return SiblingScanResult(
            "stop", sibling_ts=sib_ts, sibling_scope=sib_scope,
            sibling_lane=sib_lane,
            reason=(f"un-leased live sibling {sib_ts} collides and this loop "
                    f"named an explicit scope — not re-routing silently; pick a "
                    f"different scope or wait."))
    free = [c for c in free_lane_pool if c != sib_lane]
    if not free:
        return SiblingScanResult(
            "stop", sibling_ts=sib_ts, sibling_scope=sib_scope,
            sibling_lane=sib_lane,
            reason=(f"un-leased live sibling {sib_ts} on lane {sib_lane!r} and "
                    f"no other lane free — nothing to re-route onto."))
    return SiblingScanResult(
        "reroute", sibling_ts=sib_ts, sibling_scope=sib_scope,
        sibling_lane=sib_lane, free_lanes=tuple(free),
        reason=(f"un-leased live sibling {sib_ts} on lane {sib_lane!r}; bare "
                f"loop re-routes — re-acquire on a free lane: {free}."))

"""`dos trace <run_id>` — the cross-surface join, as a read-only projection (docs/137).

DOS has a correlation **spine** (`run_id` + `parent_id`/`root_id`, sortable,
lineage-carrying — `run_id.py`, docs/64) and three durable surfaces that compose:
the WAL (`lane_journal`), the intent ledger (`intent.jsonl`, docs/107), and git.
What it lacked was a **verb to walk from one part to the others** — "show me
everything this run touched: its lineage, the lanes it held / was refused, the
steps it claimed vs the kernel verified, the commits it landed." This module is
that walk.

It is a **read-only projection**, never a store — the same posture as
`dos decisions` / `dos top` / `dos plan` (`decisions.py`'s module doc states the
contract): it stores nothing of its own, takes no lease, mints no belief, and
adjudicates *nothing new*. `build_trace` joins surfaces that already persist their
own truth, by the id that already exists (`run_id`) — it does NOT mint a second
parallel `correlation_id`/`trace_id`/UUID (that would be a second spine to keep in
sync, the `memory-is-an-unverified-agent` failure at the identity layer). Delete
this module and you lose the reader, not any data.

**The join keys are the existing ones, nothing fabricated** (docs/137 non-goal):

    run_id          spine ↔ intent ledger ↔ WAL (after docs/118 Size S stamped it
                    onto the ACQUIRE — the *grant* side, completing what the
                    *refuse* side already had)
    (loop_ts, lane) within the WAL (a lease's identity)
    SHA             intent ledger (`start_sha`, `STEP_VERIFIED.sha`) ↔ git

**The honesty discipline is inherited verbatim** (docs/103 / docs/118): the
*adjudicated* columns (verified steps, commits, refusals) come from git ancestry +
the WAL, never the agent's self-report; `claimed` is shown as *believed* and
labelled as such, beside the verified column, with the residual (declared −
verified) visible. A lease event that carries no `run_id` (a pre-Build-1 ACQUIRE,
or a writer that didn't pass one) is surfaced under an explicit `(unattributed)`
note — NEVER silently dropped and NEVER guessed onto this run by a time window
(the docs/118 "fail toward no-match" rule). `trace` over a workspace that never
journaled with run-ids therefore honestly reports "0 attributable lease events"
rather than a fabricated lane list.

Pure-stdlib, read-only — the readers (`run_id.read_run_json`,
`intent_ledger.read_all`, `lane_journal.read_all`, `git_delta.commits_since`) are
the only I/O, reused verbatim so `trace` defines no new read; the assembly +
ranking + render are pure and are the unit-test surface (mirrors
`decisions.collect_decisions` / `timeline.build_timeline`).
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass, field

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # pragma: no cover
        pass
elif not isinstance(sys.stdout, io.TextIOWrapper):  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from dos import config as _config
from dos import git_delta as _git_delta
from dos import intent_ledger as _intent
from dos import lane_journal as _lj
from dos import run_id as _run_id


# ---------------------------------------------------------------------------
# The joined value objects — each a pure projection of one surface, plus the
# frame that carries all four. Frozen + `to_dict()` so `--json` round-trips
# (mirrors `decisions.Decision`).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeaseEvent:
    """One WAL event attributed to this run — a row in the lanes column.

    `op` is the journal op (ACQUIRE/RELEASE/HEARTBEAT/SCAVENGE/REFUSE/HALT);
    `lane` + `loop_ts` are the `(loop_ts, lane)` lease identity; `reason` is the
    recorded prose; `attributed_by` names HOW this event was tied to the run —
    `lease.run_id` (the docs/118 grant-side join), `entry.run_id` (a refuse/halt
    that carried it), so a reader can see the join is real, not a time guess.
    """

    op: str
    lane: str
    loop_ts: str
    ts: str
    reason: str
    attributed_by: str  # "lease.run_id" | "entry.run_id"
    reason_class: str = ""

    def to_dict(self) -> dict:
        return {
            "op": self.op,
            "lane": self.lane,
            "loop_ts": self.loop_ts,
            "ts": self.ts,
            "reason": self.reason,
            "reason_class": self.reason_class,
            "attributed_by": self.attributed_by,
        }


@dataclass(frozen=True)
class StepRow:
    """One declared step, with its believed (claimed) vs adjudicated (verified) state.

    The epistemic surface (docs/107 §3.2): `claimed_sha` is the agent's distrusted
    self-report; `verified_sha`/`verified_via` is the kernel's minted belief (the
    only "done"). `state` is the folded verdict: VERIFIED (kernel-confirmed),
    CLAIMED (self-reported but not confirmed — the residual a resume would re-do),
    or PENDING (declared, no claim yet).
    """

    step_id: str
    state: str  # "VERIFIED" | "CLAIMED" | "PENDING"
    claimed_sha: str = ""
    verified_sha: str = ""
    verified_via: str = ""

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "state": self.state,
            "claimed_sha": self.claimed_sha,
            "verified_sha": self.verified_sha,
            "verified_via": self.verified_via,
        }


@dataclass(frozen=True)
class TraceFrame:
    """The full cross-surface join for one run — what every reader/renderer consumes.

    Assembled by `build_trace`. Carries the four surfaces side by side:
      * spine    — the run's own id + lineage (parent/root/process), + the
                   ancestors/descendants found by a `root_id` scan.
      * intent   — the declared goal/plan/phase + `start_sha`, and the step rows
                   (claimed-vs-verified, the residual).
      * wal      — the lease events attributed to this run + the count of
                   ACQUIREs seen on the workspace that carried NO run_id
                   (`unattributed_acquires`, the honest "couldn't join" tally).
      * git      — the commits since `start_sha` (the forward git delta).
    Every list is empty-on-missing-surface (the reader degrades, never crashes).
    """

    run_id: str
    found: bool                       # was there ANY surface for this run_id?
    # spine
    run_json: dict = field(default_factory=dict)
    parent_id: str = ""
    root_id: str = ""
    process_id: str = ""
    ancestors: tuple[str, ...] = ()   # run_ids up the lineage (parent → root)
    descendants: tuple[str, ...] = ()  # run_ids whose parent chain reaches this one
    # intent
    has_intent: bool = False
    goal: str = ""
    plan: str = ""
    phase: str = ""
    start_sha: str = ""
    steps: tuple[StepRow, ...] = ()
    corrupt_ledger_lines: int = 0
    unreadable_newer: bool = False
    # wal
    lease_events: tuple[LeaseEvent, ...] = ()
    unattributed_acquires: int = 0
    # git
    commits: tuple[dict, ...] = ()

    @property
    def residual(self) -> tuple[str, ...]:
        """Declared steps NOT kernel-verified — the resume residual (docs/107)."""
        return tuple(s.step_id for s in self.steps if s.state != "VERIFIED")

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "found": self.found,
            "spine": {
                "run_json": self.run_json,
                "parent_id": self.parent_id,
                "root_id": self.root_id,
                "process_id": self.process_id,
                "ancestors": list(self.ancestors),
                "descendants": list(self.descendants),
            },
            "intent": {
                "has_intent": self.has_intent,
                "goal": self.goal,
                "plan": self.plan,
                "phase": self.phase,
                "start_sha": self.start_sha,
                "steps": [s.to_dict() for s in self.steps],
                "residual": list(self.residual),
                "corrupt_ledger_lines": self.corrupt_ledger_lines,
                "unreadable_newer": self.unreadable_newer,
            },
            "wal": {
                "lease_events": [e.to_dict() for e in self.lease_events],
                "unattributed_acquires": self.unattributed_acquires,
            },
            "git": {"commits": list(self.commits)},
        }


# ---------------------------------------------------------------------------
# Surface readers — each returns its slice; all degrade to empty on a missing /
# malformed surface (the `decisions.py` defensive-loader posture).
# ---------------------------------------------------------------------------


def _read_spine(run_id: str, cfg) -> dict:
    """The run's own `run.json` (or {} if the run-dir/stamp is absent)."""
    run_dir = _intent.run_dir_for(run_id, cfg=cfg)
    return _run_id.read_run_json(run_dir) or {}


def _scan_lineage(run_id: str, root_id: str, cfg) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(ancestors, descendants) for `run_id` from a single scan of the run-dirs.

    Reads every sibling run-dir's `run.json` once and builds the parent map, then:
      * ancestors    — walk `parent_id` up from this run to its root.
      * descendants  — every run whose ancestor chain passes through this run.
    Pure over the materialized map. Cheap (one stat+read per run-dir) and OPTIONAL —
    a missing runs/ dir yields ((), ()), the same empty degrade as every reader.
    The `root_id` narrows the scan to this run's tree when set.
    """
    runs_dir = cfg.paths.fanout_runs
    if not runs_dir.exists():
        return ((), ())
    parent_of: dict[str, str] = {}
    root_of: dict[str, str] = {}
    try:
        children = list(runs_dir.iterdir())
    except OSError:
        return ((), ())
    for d in children:
        if not d.is_dir():
            continue
        data = _run_id.read_run_json(d)
        if not isinstance(data, dict):
            continue
        rid = str(data.get("run_id") or d.name)
        parent_of[rid] = str(data.get("parent_id") or "")
        root_of[rid] = str(data.get("root_id") or "")

    # Ancestors: walk parent links up from this run (guard against a cycle).
    ancestors: list[str] = []
    seen: set[str] = {run_id}
    cur = parent_of.get(run_id, "")
    while cur and cur not in seen:
        ancestors.append(cur)
        seen.add(cur)
        cur = parent_of.get(cur, "")

    # Descendants: a run is below us iff walking ITS parent chain reaches us.
    def _reaches(rid: str) -> bool:
        hops = 0
        cur = parent_of.get(rid, "")
        local: set[str] = set()
        while cur and cur not in local and hops < 10000:
            if cur == run_id:
                return True
            local.add(cur)
            cur = parent_of.get(cur, "")
            hops += 1
        return False

    descendants = sorted(
        rid for rid in parent_of
        if rid != run_id and _reaches(rid)
    )
    return (tuple(ancestors), tuple(descendants))


def _read_intent(run_id: str, cfg) -> tuple[_intent.LedgerState, tuple[StepRow, ...]]:
    """Replay the run's intent ledger → (LedgerState, step rows).

    The step rows fold claimed-vs-verified into a single per-step verdict: a step
    in `verified` is VERIFIED (the minted belief); else in `claimed` is CLAIMED
    (self-reported, not confirmed — the residual); else PENDING. Declared order is
    preserved; a claimed/verified step NOT in `declared_steps` (a run that claimed
    a step it never declared) is appended after, so nothing is hidden.
    """
    entries = _intent.read_all(run_id, cfg=cfg)
    state = _intent.replay(entries)
    rows: list[StepRow] = []
    seen: set[str] = set()

    def _row_for(sid: str) -> StepRow:
        v = state.verified.get(sid)
        if v is not None:
            return StepRow(step_id=sid, state="VERIFIED",
                           claimed_sha=state.claimed.get(sid, ""),
                           verified_sha=v.sha, verified_via=v.via)
        if sid in state.claimed:
            return StepRow(step_id=sid, state="CLAIMED",
                           claimed_sha=state.claimed.get(sid, ""))
        return StepRow(step_id=sid, state="PENDING")

    for sid in state.declared_steps:
        rows.append(_row_for(sid))
        seen.add(sid)
    # Claimed/verified steps the run never declared — surface them, don't hide.
    for sid in list(state.verified.keys()) + list(state.claimed.keys()):
        if sid not in seen:
            rows.append(_row_for(sid))
            seen.add(sid)
    return state, tuple(rows)


def _read_wal(run_id: str, cfg) -> tuple[tuple[LeaseEvent, ...], int]:
    """(lease events attributed to this run, count of unattributed ACQUIREs).

    Joins the WAL to the spine on `run_id`, two ways:
      * a lease event (ACQUIRE/RELEASE/HEARTBEAT/SCAVENGE) whose reconstructed
        live-lease carries `run_id` (the docs/118 grant-side join) — attributed
        via "lease.run_id".
      * a REFUSE/HALT entry whose top-level `run_id` matches — attributed via
        "entry.run_id" (the refuse side already carried it).

    An ACQUIRE seen on the workspace that carries NO `run_id` is COUNTED (so the
    operator sees the join's coverage) but NEVER attributed to this run by time —
    the docs/118 "fail toward no-match" rule. RELEASE/HEARTBEAT carry no lease body
    of their own, so they are attributed via the live lease they fold against:
    `replay` is what propagates the ACQUIRE's `run_id` onto the live lease, so we
    match a RELEASE/HEARTBEAT by its `(loop_ts, lane)` identity belonging to a
    run-attributed live lease.
    """
    path = cfg.paths.lane_journal
    try:
        entries = _lj.read_all(path)
    except Exception:
        return ((), 0)

    # First pass: which (loop_ts, lane) identities belong to THIS run, learned from
    # any ACQUIRE that carries the run_id (on the nested lease or inline). This lets
    # a later RELEASE/HEARTBEAT — which has no lease body — be attributed by identity.
    identities: set[tuple[str, str]] = set()
    unattributed_acquires = 0
    for e in entries:
        if str(e.get("op") or "") != _lj.OP_ACQUIRE:
            continue
        lease = e.get("lease") if isinstance(e.get("lease"), dict) else e
        rid = str((lease.get("run_id") if isinstance(lease, dict) else "") or e.get("run_id") or "")
        if rid == run_id:
            identities.add(_lj._lease_identity(e))
        elif not rid:
            unattributed_acquires += 1

    out: list[LeaseEvent] = []
    for e in entries:
        op = str(e.get("op") or "")
        ts = str(e.get("ts") or "")
        reason = str(e.get("reason") or "")
        if op in (_lj.OP_REFUSE, _lj.OP_HALT):
            # The refuse/halt side already carries run_id at the top level.
            if str(e.get("run_id") or "") != run_id:
                continue
            out.append(LeaseEvent(
                op=op, lane=str(e.get("lane") or ""),
                loop_ts=str(e.get("loop_ts") or ""), ts=ts, reason=reason,
                attributed_by="entry.run_id",
                reason_class=str(e.get("reason_class") or ""),
            ))
            continue
        if op in (_lj.OP_ACQUIRE, _lj.OP_RELEASE, _lj.OP_HEARTBEAT,
                  _lj.OP_SCAVENGE):
            ident = _lj._lease_identity(e)
            if ident not in identities:
                continue  # not this run's lease (or an unattributed ACQUIRE)
            out.append(LeaseEvent(
                op=op, lane=ident[1], loop_ts=ident[0], ts=ts, reason=reason,
                attributed_by="lease.run_id",
            ))
    return (tuple(out), unattributed_acquires)


def build_trace(run_id: str, config=None) -> TraceFrame:
    """Assemble the full cross-surface join for `run_id` (docs/137). Read-only.

    Joins the spine (`run.json` + lineage), the intent ledger (claimed-vs-verified),
    the WAL (lease events attributed by `run_id`), and git (commits since
    `start_sha`) — every join by an id that already exists, nothing fabricated.
    `found` is True iff ANY surface had something for this run (a stamp, a ledger,
    or a WAL event); a wholly unknown run_id yields `found=False` and empty slices.
    """
    cfg = config if config is not None else _config.active()

    spine = _read_spine(run_id, cfg)
    parent_id = str(spine.get("parent_id") or "")
    root_id = str(spine.get("root_id") or run_id)
    process_id = str(spine.get("process_id") or "")
    ancestors, descendants = _scan_lineage(run_id, root_id, cfg)

    state, steps = _read_intent(run_id, cfg)
    lease_events, unattributed = _read_wal(run_id, cfg)
    commits = tuple(_git_delta.commits_since(state.start_sha, root=cfg.root)) \
        if state.start_sha else ()

    found = bool(spine) or state.has_intent or bool(lease_events) \
        or bool(state.claimed) or bool(state.verified)

    return TraceFrame(
        run_id=run_id,
        found=found,
        run_json=spine,
        parent_id=parent_id,
        root_id=root_id,
        process_id=process_id,
        ancestors=ancestors,
        descendants=descendants,
        has_intent=state.has_intent,
        goal=state.goal,
        plan=state.plan,
        phase=state.phase,
        start_sha=state.start_sha,
        steps=steps,
        corrupt_ledger_lines=state.corrupt_lines,
        unreadable_newer=state.unreadable_newer,
        lease_events=lease_events,
        unattributed_acquires=unattributed,
        commits=commits,
    )


# ---------------------------------------------------------------------------
# Rendering — the plain text floor (provenance-first) + JSON.
# ---------------------------------------------------------------------------


_STEP_GLYPH = {"VERIFIED": "OK ", "CLAIMED": "?? ", "PENDING": "···"}


def render_text(t: TraceFrame) -> str:
    """The operator-facing walk: lineage → intent → lanes → commits.

    Provenance-first: who the run is, what it tried, what it touched, what it
    actually shipped — believed (claimed) beside adjudicated (verified). Reuses the
    small-column idiom of `decisions.render_list_plain` / `timeline.render_text`.
    """
    out: list[str] = []
    out.append(f"# trace · {t.run_id}")
    if not t.found:
        out.append(f"  no surface found for run {t.run_id} "
                   f"(no run.json, no intent ledger, no attributed WAL event)")
        return "\n".join(out)

    # --- spine / lineage ---------------------------------------------------
    out.append("")
    out.append("## spine")
    out.append(f"  process  {t.process_id or '-'}")
    out.append(f"  parent   {t.parent_id or '-(root)'}")
    out.append(f"  root     {t.root_id or t.run_id}"
               + ("  (this run is the root)" if t.root_id in ("", t.run_id) else ""))
    if t.ancestors:
        out.append(f"  ancestry {' → '.join(t.ancestors)}")
    if t.descendants:
        shown = list(t.descendants[:6])
        more = f"  (+{len(t.descendants) - 6} more)" if len(t.descendants) > 6 else ""
        out.append(f"  children {', '.join(shown)}{more}")

    # --- intent (claimed vs verified) -------------------------------------
    out.append("")
    out.append("## intent")
    if not t.has_intent:
        out.append("  (no INTENT declared — this run recorded no goal/plan/steps)")
    else:
        if t.goal:
            out.append(f"  goal     {t.goal[:120]}")
        if t.plan or t.phase:
            out.append(f"  target   {t.plan or '-'} :: {t.phase or '-'}")
        out.append(f"  start    {t.start_sha or '-'}")
        if t.steps:
            n_ver = sum(1 for s in t.steps if s.state == "VERIFIED")
            out.append(f"  steps    {n_ver}/{len(t.steps)} kernel-verified "
                       f"(believed-claimed shown beside adjudicated-verified):")
            for s in t.steps:
                glyph = _STEP_GLYPH.get(s.state, s.state)
                detail = ""
                if s.state == "VERIFIED":
                    detail = f"sha={s.verified_sha[:10]} via={s.verified_via or '?'}"
                elif s.state == "CLAIMED":
                    detail = f"claimed sha={s.claimed_sha[:10]} — NOT kernel-verified"
                out.append(f"    {glyph} {s.step_id:<22} {detail}")
            if t.residual:
                out.append(f"  residual {len(t.residual)} step(s) not verified: "
                           f"{', '.join(t.residual[:8])}"
                           + (" …" if len(t.residual) > 8 else ""))
    if t.corrupt_ledger_lines:
        note = " (incl. a record this kernel is too OLD to read — migrate)" \
            if t.unreadable_newer else ""
        out.append(f"  ⚠ ledger {t.corrupt_ledger_lines} corrupt/unreadable line(s){note}")

    # --- WAL (lanes held / refused) ---------------------------------------
    out.append("")
    out.append("## lanes (WAL)")
    if not t.lease_events:
        out.append("  (no lease event attributed to this run by run_id)")
    else:
        header = f"  {'op':<10} {'lane':<12} {'loop_ts':<22} via"
        out.append(header)
        out.append("  " + "-" * (len(header) - 2))
        for e in t.lease_events:
            out.append(f"  {e.op:<10} {(e.lane or '-'):<12} "
                       f"{(e.loop_ts or '-'):<22} {e.attributed_by}")
    if t.unattributed_acquires:
        out.append(f"  note: {t.unattributed_acquires} ACQUIRE(s) on this workspace "
                   f"carried NO run_id and were NOT attributed by time "
                   f"(stamp --run-id to join them; docs/137)")

    # --- git --------------------------------------------------------------
    out.append("")
    out.append("## commits since start")
    if not t.commits:
        out.append(f"  (none since {t.start_sha or '-'})")
    else:
        for c in t.commits[:20]:
            out.append(f"  {str(c.get('sha',''))[:10]}  {str(c.get('subject',''))[:72]}")
        if len(t.commits) > 20:
            out.append(f"  (+{len(t.commits) - 20} more)")
    return "\n".join(out)

"""`dos plan` — the work-terrain projection: every phase, claimed vs oracle-confirmed.

The **third projection** of the trust substrate, beside `dos top` and `dos decisions`:

  * `dos top`       — what is *running* now (leases · liveness · verdicts · git).
  * `dos decisions` — what is waiting on *me* now (the four refusal sources).
  * `dos plan`      — what is the *shape of the work*, and how far has it shipped.

The kernel-honest reframe (CLAUDE.md: the plan schema is NOT in the kernel): a plan
view is a **verify()-fan-out, not a plan reader**. The reference userland app paints a
status board from the plan's own self-report (`execution-state.yaml` says IF4.1 is
done); the kernel is built to distrust exactly that. So here the plan supplies only
candidate ``(plan, phase)`` rows (via the declared `plan_source` seam), and the *status*
of every row comes from `oracle.is_shipped` — the truth syscall, registry-first,
ancestry-checked, never the stamp. The screen exists for one cell: the **divergence
flag**, where the plan CLAIMS shipped but the oracle says not (or the reverse). That is
the believed-vs-adjudicated thesis at plan altitude — the one cell a self-reporting view
structurally cannot show.

It is a **read-only projection** (the `dispatch_top` / `decisions` discipline restated):
it stores nothing, mutates nothing, acquires no lease, launches no agent. Every panel is
a pure function over an in-memory payload; the only I/O is `snapshot()` at the boundary,
which reads three already-persisted sources and freezes them:

    rows      <- plan_source.default_source(cfg) (the dos.toml-declared source —
                                                  `[plan] source`, docs/293 — else the
                                                  built-in markdown; or an explicit
                                                  phase list / --source override)
    oracle    <- oracle.is_shipped(plan, phase)  (the verdict — the WHOLE point)
    leases    <- lane_journal.replay(...)        (which phase's lane a live lease holds)
    decisions <- decisions.collect_decisions(..) (which phase's lane a gate blocks)

It does NOT re-read the world `dos top`/`dos decisions` already read — it COMPOSES them:
the oracle cross-check reuses `dispatch_top.attach_trust`'s injected-`verify` boundary
(promoted from a column to the whole screen), the live-lease join reuses
`dispatch_top.build_lane_states`, and the gate join reuses `decisions.collect_decisions`.
A plan-row is the spine that ties the other two projections together.

Nothing here imports a host. In a repo with **no plans at all** (`plan_source` yields
``[]``), every row reader returns empty and the screen shows "(no plans declared)" plus
the `git_delta` recent-ships strip — the same fresh-repo floor `dos top` has, pinned in
`tests/test_plan_board.py`. The rich live skin lives in `plan_board_tui` (behind the
`[tui]` extra); this module is import-light so the plain-text renderers are always the
available floor — the `dispatch_top` / `dispatch_top_tui` split.
"""

from __future__ import annotations

import datetime as dt
import io
import sys
from dataclasses import dataclass

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # pragma: no cover
        pass
elif not isinstance(sys.stdout, io.TextIOWrapper):  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from dos import config as _config
from dos import dispatch_top as _dtop
from dos import git_delta
from dos import lane_journal
from dos import plan_source as _plan_source


# ---------------------------------------------------------------------------
# Divergence — the headline. The plan's CLAIM vs the oracle's VERDICT, collapsed
# to one token the operator reads at a glance. This is the believed-vs-adjudicated
# cell the whole screen is built around; everything else is context for it.
# ---------------------------------------------------------------------------

DIV_OK_SHIPPED = "✓shipped"       # claim shipped & oracle confirms — agreed, done
DIV_PENDING = "·pending"          # claim open/blocked & oracle says not-yet — agreed, in flight
DIV_OVERCLAIM = "⚠over-claim"     # claim SHIPPED but oracle says NOT — the plan is lying (the headline)
DIV_UNDERCLAIM = "✓under-claim"   # claim open/blocked but oracle CONFIRMS shipped — plan stamp lags
DIV_UNKNOWN = "—"                 # the plan claimed nothing — oracle verdict stands alone

# The two values that mean "the plan and the oracle DISAGREE" — what the screen tallies
# as DIVERGENT and what the rich skin paints loud. An over-claim is the dangerous one (a
# phase the plan calls done that did not ship); an under-claim is benign (stamp drift) but
# still a divergence worth surfacing.
_DIVERGENT = frozenset({DIV_OVERCLAIM, DIV_UNDERCLAIM})


def divergence(claimed_status: str, oracle_shipped: bool) -> str:
    """The claimed-vs-oracle cell for one phase. Pure.

    The four-way truth table over (plan claims shipped?) × (oracle confirms shipped?):

      claim shipped + oracle yes  → ✓shipped   (agreed done)
      claim shipped + oracle NO   → ⚠over-claim (the plan is lying — the headline cell)
      claim not     + oracle yes  → ✓under-claim(plan stamp lags reality — benign drift)
      claim not     + oracle no   → ·pending    (agreed in flight)
      claim UNKNOWN               → —           (plan said nothing; oracle stands alone)

    The oracle is ALWAYS the authority — `claimed_status` only selects which of the four
    cells we are in, it never overrides the verdict. A plan view that trusted the claim
    would be a self-narrating worker; this makes the disagreement the visible artifact.
    """
    claim_shipped = claimed_status == _plan_source.CLAIMED_SHIPPED
    if claimed_status == _plan_source.CLAIMED_UNKNOWN:
        # The plan claimed nothing — there is no claim to diverge FROM. Report the bare
        # oracle verdict; never call a no-claim row an over/under-claim.
        return DIV_OK_SHIPPED if oracle_shipped else DIV_UNKNOWN
    if claim_shipped and oracle_shipped:
        return DIV_OK_SHIPPED
    if claim_shipped and not oracle_shipped:
        return DIV_OVERCLAIM
    if not claim_shipped and oracle_shipped:
        return DIV_UNDERCLAIM
    return DIV_PENDING


# ---------------------------------------------------------------------------
# Time helper (compact age — mirrors dispatch_top / decisions).
# ---------------------------------------------------------------------------


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------------------
# The rendered phase row — pure data, no rich objects, carries the oracle verdict
# + the joins to the other two projections.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseRow:
    """One rendered phase — the candidate, the oracle verdict, and the cross-refs.

    ``claimed_status`` is the plan's self-report (from the source); ``oracle_shipped``
    /``oracle_source``/``oracle_sha`` are the verdict (from `oracle.is_shipped`);
    ``divergence`` is the headline cell over the two. ``lane_chip`` is the live-lease
    state of the phase's lane (the join to `dos top`, "" when no lane / no lease);
    ``decision_ref`` names a pending gate on the phase's lane (the join to
    `dos decisions`, "" when none). The joins are LANE-KEYED and conservative — a row
    links to a lease/decision only when its lane is known and matches.
    """

    plan: str
    phase: str
    doc_path: str = ""
    claimed_status: str = _plan_source.CLAIMED_UNKNOWN
    oracle_shipped: bool = False
    oracle_source: str = ""          # "registry" | "grep" | "none"
    oracle_sha: str = ""
    divergence: str = DIV_UNKNOWN
    lane: str = ""
    lane_chip: str = ""              # a dispatch_top CHIP_* when a live lease holds the lane
    decision_ref: str = ""           # a pending-decision reason token on the lane, or ""

    @property
    def is_divergent(self) -> bool:
        """True iff plan and oracle DISAGREE (over- or under-claim) — the tally key."""
        return self.divergence in _DIVERGENT

    def to_dict(self) -> dict:
        return {
            "plan": self.plan,
            "phase": self.phase,
            "doc_path": self.doc_path,
            "claimed_status": self.claimed_status,
            "oracle_shipped": self.oracle_shipped,
            "oracle_source": self.oracle_source,
            "oracle_sha": self.oracle_sha,
            "divergence": self.divergence,
            "is_divergent": self.is_divergent,
            "lane": self.lane,
            "lane_chip": self.lane_chip,
            "decision_ref": self.decision_ref,
        }


# ---------------------------------------------------------------------------
# The pure adapter — (plan rows, oracle verify, lane states, decisions) → PhaseRows.
# This is the unit-test surface; the I/O all lives in snapshot().
# ---------------------------------------------------------------------------


def build_phase_rows(
    rows,
    *,
    verify,
    lane_states=(),
    decisions=(),
) -> list[PhaseRow]:
    """Pure: join candidate plan rows with the oracle verdict + the two cross-refs.

    ``rows`` is the `plan_source.PlanRow` list. ``verify`` is the injected
    ``(plan, phase) -> ShipVerdict`` (the live path wires `oracle.is_shipped`; tests
    inject a fake) — the SAME boundary `dispatch_top.attach_trust` uses, here fanned over
    every row instead of one verdict. ``lane_states`` are `dispatch_top.LaneState`s (so a
    row whose lane holds a live lease shows its chip); ``decisions`` are
    `decisions.Decision`s (so a row whose lane has a pending gate shows it). Both joins are
    lane-keyed and degrade to "" when the row carries no lane.

    Never raises on a verify fault — a `verify` that throws or returns a non-verdict
    degrades that row to a NOT-shipped oracle reading (fail-safe, the `attach_trust`
    posture: the screen never crashes on a flaky oracle).
    """
    chip_by_lane: dict[str, str] = {}
    for s in lane_states:
        lane = getattr(s, "lane", "")
        chip = getattr(s, "chip", "")
        # Only a HELD lane contributes a chip — a FREE lane is no join signal.
        if lane and chip and chip != _dtop.CHIP_FREE:
            chip_by_lane[lane] = chip

    decision_by_lane: dict[str, str] = {}
    for d in decisions:
        lane = getattr(d, "lane", "")
        if not lane or lane in decision_by_lane:
            continue
        token = getattr(d, "reason_token", "") or getattr(d, "reason_text", "")
        decision_by_lane[lane] = str(token)[:40]

    out: list[PhaseRow] = []
    for r in rows:
        plan = getattr(r, "plan", "")
        phase = getattr(r, "phase", "")
        claimed = getattr(r, "claimed_status", _plan_source.CLAIMED_UNKNOWN)
        lane = getattr(r, "lane", "") or ""
        shipped, source, sha = _verify_row(verify, plan, phase)
        out.append(PhaseRow(
            plan=plan,
            phase=phase,
            doc_path=getattr(r, "doc_path", ""),
            claimed_status=claimed,
            oracle_shipped=shipped,
            oracle_source=source,
            oracle_sha=sha,
            divergence=divergence(claimed, shipped),
            lane=lane,
            lane_chip=chip_by_lane.get(lane, ""),
            decision_ref=decision_by_lane.get(lane, ""),
        ))
    return out


def _verify_row(verify, plan: str, phase: str) -> tuple[bool, str, str]:
    """Run one row through the injected verify, fail-safe → (shipped, source, sha).

    ``verify`` may return a `ShipVerdict` (the live `oracle.is_shipped`) OR a bare bool
    (the simplest test fake / the `dispatch_top.attach_trust` contract). Both are read
    uniformly here so a caller can inject either. Any raise / unexpected return degrades
    to ``(False, "none", "")`` — a flaky oracle never crashes the board.
    """
    if verify is None:
        return (False, "", "")
    try:
        res = verify(plan, phase)
    except Exception:
        return (False, "none", "")
    if isinstance(res, bool):
        return (res, "" if not res else "registry", "")
    shipped = bool(getattr(res, "shipped", False))
    source = str(getattr(res, "source", "") or "")
    sha = str(getattr(res, "sha", "") or "")
    return (shipped, source, sha)


# ---------------------------------------------------------------------------
# The frame — everything one screen shows, as pure data. snapshot() builds it from
# disk; the renderers + the TUI consume it.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    """A single rendered moment of `dos plan` — pure, serializable, testable."""

    workspace: str
    now_iso: str
    phases: tuple[PhaseRow, ...] = ()
    activity: tuple[dict, ...] = ()       # recent commits [{sha, subject}, …] — the floor
    plan_source: str = "markdown"         # which source produced the rows
    initialized: bool = True              # did a dos.toml exist (vs. bare repo)?

    def to_dict(self) -> dict:
        return {
            "workspace": self.workspace,
            "now": self.now_iso,
            "plan_source": self.plan_source,
            "initialized": self.initialized,
            "phases": [p.to_dict() for p in self.phases],
            "activity": [dict(c) for c in self.activity],
            "summary": self.summary(),
        }

    def summary(self) -> dict:
        """The one-line tally the footer + `--json` consumers read."""
        total = len(self.phases)
        shipped = sum(1 for p in self.phases if p.oracle_shipped)
        divergent = sum(1 for p in self.phases if p.is_divergent)
        overclaim = sum(1 for p in self.phases if p.divergence == DIV_OVERCLAIM)
        in_flight = sum(1 for p in self.phases if p.lane_chip)
        gated = sum(1 for p in self.phases if p.decision_ref)
        return {
            "phases": total,
            "shipped": shipped,
            "divergent": divergent,
            "over_claims": overclaim,
            "in_flight": in_flight,
            "gated": gated,
        }


def snapshot(
    config=None,
    *,
    verify=None,
    rows=None,
    source_name: str | None = None,
    activity_limit: int = 10,
    now: dt.datetime | None = None,
) -> Frame:
    """Read the sources and freeze one `Frame`. The only I/O in this module.

    Resolution of the candidate rows (the one host-shaped choice):
      * an explicit ``rows`` list (the CLI's phase-list escape hatch / a test) wins;
      * else a named source (``source_name``, resolved through `plan_source`), run
        fail-safe;
      * else the workspace's DECLARED source (`dos.toml [plan] source`, docs/293),
        else the built-in markdown — both via `plan_source.default_source`; a
        declared name that does not resolve renders no rows (fail-to-empty).

    ``verify`` defaults to the live `oracle.is_shipped` bound to this workspace; tests
    inject a fake. Every reader degrades to empty on a missing/torn source, so this
    returns a renderable frame in a **repo with no plans at all** (the headline contract):
    no plan docs → no phase rows → the screen shows "(no plans)" and the
    `git_delta.recent_commits` strip carries it, exactly as `dos top` degrades.
    """
    cfg = _config.ensure(config)
    now = now or _now()

    # --- candidate rows (explicit > named source > default markdown) ----------
    src_label = source_name or "markdown"
    if rows is not None:
        plan_rows = list(rows)
        # Explicit rows ALWAYS come from the CLI's positional-phase escape hatch, never a
        # named source — so the provenance label is "explicit" regardless of any --source
        # flag that rode along unused. (Labeling it with the unused source_name would have
        # the header/JSON claim a source that produced none of the shown rows.)
        src_label = "explicit"
    elif source_name:
        try:
            src = _plan_source.resolve_plan_source(source_name)
            plan_rows = _plan_source.run_plan_source(src, cfg)
        except ValueError:
            plan_rows = []
    else:
        # The declared-or-builtin default (docs/293). The label carries the
        # DECLARED name even when it failed to resolve (rows then stay empty) —
        # the header/JSON must say which source the workspace asked for, not
        # silently relabel the floor as `markdown`.
        src_label, src = _plan_source.default_source(cfg)
        plan_rows = _plan_source.run_plan_source(src, cfg) if src is not None else []

    # --- the oracle verdict per row (the whole point) -------------------------
    if verify is None:
        verify = _make_oracle_verify(cfg)

    # --- the two cross-ref joins (compose dos top + dos decisions readers) ----
    lane_states = _live_lane_states(cfg, now=now)
    decisions = _pending_decisions(cfg)

    phase_rows = build_phase_rows(
        plan_rows, verify=verify, lane_states=lane_states, decisions=decisions
    )

    # --- git-activity strip (the no-plan floor content) -----------------------
    try:
        activity = git_delta.recent_commits(activity_limit, root=cfg.root)
    except Exception:
        activity = []

    return Frame(
        workspace=str(cfg.root),
        now_iso=now.replace(microsecond=0).isoformat(),
        phases=tuple(phase_rows),
        activity=tuple(activity),
        plan_source=src_label,
        initialized=(cfg.root / "dos.toml").exists(),
    )


def _make_oracle_verify(cfg):
    """Build the live ``(plan, phase) -> ShipVerdict`` over `oracle.is_shipped`, bound to cfg.

    Imported lazily (oracle pulls a heavier chain) and wrapped so a missing oracle
    degrades a row to a NOT-shipped reading rather than crashing the screen. Returns a
    full `ShipVerdict` (not a bool) so the board can show the verdict's `source`/`sha` —
    the richer surface a plan board wants over `dispatch_top`'s bool trust column.
    """
    try:
        from dos import oracle
    except Exception:
        return None

    def _verify(plan: str, phase: str):
        try:
            return oracle.is_shipped(plan, phase, cfg=cfg)
        except Exception:
            # Return a full NOT-shipped verdict (not a bare False) so a live oracle that
            # throws internally labels its row `source="none"` — consistent with
            # `_verify_row`'s boundary-raise path, rather than the bool branch's "".
            return oracle.ShipVerdict(plan=plan, phase=phase, shipped=False, source="none")

    return _verify


def _live_lane_states(cfg, *, now):
    """The live-lease lane states — reuse `dispatch_top`'s reader, never re-derive.

    Folds the lane journal to the live-lease set and builds `dispatch_top.LaneState`s so
    a phase row can show whether its lane holds a moving lease. Degrades to ``()`` on any
    torn source (the board then shows no lane chips — never crashes)."""
    try:
        entries = lane_journal.read_all(cfg.paths.lane_journal)
    except Exception:
        entries = []
    try:
        leases = lane_journal.replay(entries)
    except Exception:
        leases = []
    if not leases:
        return ()
    live_by_lane = {str(l.get("lane") or ""): l for l in leases}
    payload = {
        "leases": leases,
        "events_by_lane": _dtop._events_by_lane(entries, live_by_lane),
    }
    try:
        roster = _dtop.lane_roster(cfg)
        return tuple(_dtop.build_lane_states(
            payload, roster=roster, exclusive=tuple(cfg.lanes.exclusive), now=now,
        ))
    except Exception:
        return ()


def _pending_decisions(cfg):
    """The pending operator decisions — reuse `decisions.collect_decisions`, all kinds.

    We want EVERY pending decision (not just HUMAN-resolvable) so a phase row reflects an
    ORACLE/JUDGE-owned gate too; hence `resolver=None`. Degrades to ``()`` on any fault."""
    try:
        from dos import decisions as _decisions
        return tuple(_decisions.collect_decisions(cfg, resolver=None))
    except Exception:
        return ()


# ---------------------------------------------------------------------------
# Rendering — the plain-text floor (always available; the rich skin is in
# plan_board_tui). Each renderer is pure over its data, so the tests assert
# byte-stable output (the dispatch_top renderer discipline).
# ---------------------------------------------------------------------------

_WIDTH = 88


def render_phases_text(phases: tuple[PhaseRow, ...]) -> str:
    out = ["PHASES                 [oracle = truth syscall · ⚠ = plan claim diverges from oracle]"]
    if not phases:
        out.append("  (no plans declared — set [paths].plans_glob in dos.toml, or pass phases)")
        return "\n".join(out)
    header = (f"  {'plan':<8} {'phase':<14} {'claimed':<8} {'oracle':<14} "
              f"{'lane':<10} gate")
    out.append(header)
    out.append("  " + "-" * (len(header) - 2))
    for p in phases:
        claimed = p.claimed_status or "-"
        lane = p.lane or "-"
        # The lane cell shows the live chip glyph when a lease holds it, else the bare name.
        lane_cell = (p.lane_chip.split()[0] + " " + lane) if p.lane_chip else lane
        gate = p.decision_ref or ""
        out.append(
            f"  {p.plan:<8} {p.phase:<14} {claimed:<8} {p.divergence:<14} "
            f"{lane_cell:<10} {gate}".rstrip()
        )
    s = Frame(workspace="", now_iso="", phases=phases).summary()
    out.append(
        f"  {s['phases']} phases · {s['shipped']} shipped · {s['divergent']} DIVERGENT "
        f"({s['over_claims']} over-claim) · {s['in_flight']} in-flight · {s['gated']} gated"
    )
    return "\n".join(out)


def render_activity_text(commits: tuple[dict, ...], *, limit: int = 10) -> str:
    out = ["RECENT COMMITS        [ground truth — git history]"]
    if not commits:
        out.append("  (no commits — empty or non-git workspace)")
    for c in commits[:limit]:
        sha = str(c.get("sha") or "")[:9]
        subject = str(c.get("subject") or "")
        out.append(f"  {sha:<9}  {subject}"[: _WIDTH + 2])
    return "\n".join(out)


def render_frame_text(frame: Frame) -> str:
    """The whole `dos plan --once` screen as plain text — the always-available floor."""
    head = f"┌─ dos plan · {frame.workspace} · {frame.now_iso} "
    out = [head + "─" * max(0, _WIDTH - len(head))]
    if not frame.initialized:
        out.append("  (no dos.toml — generic main/global; `dos init` to declare lanes/plans)")
    out.append("")
    out.append(render_phases_text(frame.phases))
    out.append("")
    out.append(render_activity_text(frame.activity))
    out.append("─" * _WIDTH)
    div = frame.summary()["divergent"]
    if div:
        out.append(f"⚠ {div} phase(s) where the plan's claim DISAGREES with the oracle — "
                   f"the cell this screen exists to surface.")
    out.append("read-only · q quit · this screen mutates nothing")
    return "\n".join(out)

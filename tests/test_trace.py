"""Tests for `dos trace` — the cross-surface join (docs/137).

`dos.trace.build_trace` is a read-only projection that walks one run across the
four DOS surfaces, joined by its `run_id`: the spine (`run.json` + lineage), the
intent ledger (claimed-vs-verified steps + the residual), the WAL (lanes the run
held / was refused — joinable since docs/118 Size S stamped `run_id` onto the
ACQUIRE), and git (commits since the run's start SHA). These tests pin:

  * the join assembles all four surfaces for a seeded run (spine, intent, WAL);
  * the epistemic fold: a VERIFIED step vs a CLAIMED-but-not-verified one, and the
    residual = declared − verified (the docs/107 surface `resume` also reads);
  * **the honesty rule (docs/118 / docs/103):** an ACQUIRE that carries NO `run_id`
    is COUNTED as `unattributed_acquires` but NEVER attributed to a named run by a
    time window — the load-bearing "fail toward no-match" guarantee;
  * Build 1 (docs/118 S): `acquire_entry(run_id=…)` round-trips the id through
    `replay` onto the reconstructed live lease (additive — absent replays unchanged);
  * lineage: a child run is found via the `root_id` scan;
  * `--json` round-trips and an unknown run_id yields `found=False` (exit 1).

All pure — the only I/O is seeding files under a tmp workspace; no real terminal.
"""

from __future__ import annotations

import json

from dos import intent_ledger as IL
from dos import lane_journal as LJ
from dos import run_id as R
from dos import trace as TR
from dos.config import default_config


# ---------------------------------------------------------------------------
# Fixtures — seed the surfaces under a tmp workspace (the `test_decisions` idiom).
# ---------------------------------------------------------------------------


def _stamp_run(cfg, rid: R.RunId) -> None:
    """Write run.json into the run's dir (the spine stamp)."""
    R.write_run_json(cfg.paths.fanout_runs / rid.run_id, rid)


def _seed_acquire(cfg, *, lane, loop_ts, run_id="", holder="wf-1",
                  ts="2026-06-04T12:00:00Z") -> None:
    """Append an ACQUIRE to the WAL, optionally carrying a run_id (Build 1)."""
    lease = {
        "lane": lane, "lane_kind": "cluster", "tree": [f"{lane}/**"],
        "loop_ts": loop_ts, "host_id": "h", "pid": 1, "holder": holder,
        "acquired_at": ts,
    }
    e = LJ.acquire_entry(lease, reason=f"lane-lease:{holder}",
                         run_id=run_id or None)
    e["ts"] = ts
    LJ.append(e, cfg.paths.lane_journal)


def _seed_refuse(cfg, *, lane, run_id, loop_ts, ts="2026-06-04T12:00:05Z") -> None:
    """Append an OP_REFUSE carrying run_id (the refuse side already had it)."""
    e = {
        "op": LJ.OP_REFUSE, "lane": lane, "loop_ts": loop_ts, "host_id": "h",
        "run_id": run_id, "holder": "wf-1", "reason": "lane busy",
        "reason_class": "", "ts": ts,
    }
    LJ.append(e, cfg.paths.lane_journal)


# ---------------------------------------------------------------------------
# Build 1 — run_id round-trips through acquire_entry + replay (additive).
# ---------------------------------------------------------------------------


def test_acquire_entry_carries_run_id_through_replay():
    """`acquire_entry(run_id=…)` nests the id on the lease; replay reconstructs it."""
    lease = {"lane": "src", "lane_kind": "cluster", "tree": ["src/**"],
             "loop_ts": "2026-06-04T12:00:00Z", "host_id": "h", "pid": 1,
             "holder": "wf-1", "acquired_at": "2026-06-04T12:00:00Z"}
    e = LJ.acquire_entry(lease, run_id="RID-ABCD1234567")
    assert e["lease"]["run_id"] == "RID-ABCD1234567"
    live = LJ.replay([e])
    assert live[0]["run_id"] == "RID-ABCD1234567"


def test_acquire_entry_without_run_id_is_byte_unchanged():
    """The additive contract: no run_id ⇒ no run_id key, replays identically."""
    lease = {"lane": "src", "lane_kind": "cluster", "tree": ["src/**"],
             "loop_ts": "2026-06-04T12:00:00Z", "host_id": "h", "pid": 1,
             "holder": "wf-1", "acquired_at": "2026-06-04T12:00:00Z"}
    e = LJ.acquire_entry(lease)
    assert "run_id" not in e["lease"]
    live = LJ.replay([e])
    assert [l["lane"] for l in live] == ["src"]
    assert "run_id" not in live[0]


# ---------------------------------------------------------------------------
# The full join — spine + intent + WAL on a seeded run.
# ---------------------------------------------------------------------------


def test_build_trace_joins_all_surfaces(tmp_path):
    cfg = default_config(tmp_path)
    rid = R.mint("dispatch-loop", clock_ms=lambda: 1_700_000_000_000,
                 entropy=lambda: 7)
    _stamp_run(cfg, rid)
    # intent: one verified step, one claimed-not-verified step.
    IL.append(rid.run_id, IL.intent_entry(
        goal="wire trace", plan="docs/137", phase="trace", start_sha="BEEF",
        declared_steps=["s1", "s2"]), cfg=cfg)
    IL.append(rid.run_id, IL.step_claimed_entry("s1", "AAA111"), cfg=cfg)
    IL.append(rid.run_id, IL.step_verified_entry("s1", "AAA111", via="file-path"),
              cfg=cfg)
    IL.append(rid.run_id, IL.step_claimed_entry("s2", "BBB222"), cfg=cfg)
    # WAL: a held lane carrying this run_id.
    _seed_acquire(cfg, lane="src", loop_ts="2026-06-04T12:00:00Z",
                  run_id=rid.run_id)

    t = TR.build_trace(rid.run_id, cfg)

    assert t.found is True
    # spine
    assert t.process_id == "PROC-dispatch-loop"
    assert t.root_id == rid.run_id  # a root is its own root
    # intent — claimed vs verified
    assert t.has_intent and t.goal == "wire trace" and t.plan == "docs/137"
    states = {s.step_id: s.state for s in t.steps}
    assert states == {"s1": "VERIFIED", "s2": "CLAIMED"}
    assert t.residual == ("s2",)
    # WAL — the held lane, attributed via the lease's run_id (the docs/118 join)
    assert [(e.op, e.lane, e.attributed_by) for e in t.lease_events] == [
        ("ACQUIRE", "src", "lease.run_id")
    ]
    assert t.unattributed_acquires == 0


def test_refuse_is_attributed_by_entry_run_id(tmp_path):
    cfg = default_config(tmp_path)
    rid = R.mint("fanout", clock_ms=lambda: 1_700_000_000_000, entropy=lambda: 1)
    _stamp_run(cfg, rid)
    _seed_refuse(cfg, lane="src", run_id=rid.run_id,
                 loop_ts="2026-06-04T12:00:00Z")
    t = TR.build_trace(rid.run_id, cfg)
    assert [(e.op, e.lane, e.attributed_by) for e in t.lease_events] == [
        ("REFUSE", "src", "entry.run_id")
    ]


# ---------------------------------------------------------------------------
# The honesty rule — an unattributed ACQUIRE is COUNTED, never time-attributed.
# ---------------------------------------------------------------------------


def test_unattributed_acquire_is_counted_never_attributed(tmp_path):
    """A lease with NO run_id must not appear under a named run's lanes; it is
    only tallied as `unattributed_acquires` (docs/118 fail-toward-no-match)."""
    cfg = default_config(tmp_path)
    rid = R.mint("dispatch-loop", clock_ms=lambda: 1_700_000_000_000, entropy=lambda: 5)
    _stamp_run(cfg, rid)
    # This run's OWN attributed acquire on lane 'src'…
    _seed_acquire(cfg, lane="src", loop_ts="2026-06-04T12:00:00Z", run_id=rid.run_id)
    # …and a DIFFERENT acquire on lane 'docs' that carries NO run_id, in the same
    # time window. The honest reader must NOT pull 'docs' under this run.
    _seed_acquire(cfg, lane="docs", loop_ts="2026-06-04T12:00:01Z", run_id="")

    t = TR.build_trace(rid.run_id, cfg)

    lanes = {e.lane for e in t.lease_events}
    assert lanes == {"src"}            # 'docs' is NOT attributed by time
    assert "docs" not in lanes
    assert t.unattributed_acquires == 1  # but it IS counted, honestly


def test_acquire_for_a_different_run_is_not_attributed(tmp_path):
    """An ACQUIRE carrying ANOTHER run's id is neither attributed here nor counted
    as unattributed (it is attributed — just to someone else)."""
    cfg = default_config(tmp_path)
    mine = R.mint("dispatch-loop", clock_ms=lambda: 1_700_000_000_000, entropy=lambda: 2)
    other = R.mint("fanout", clock_ms=lambda: 1_700_000_000_001, entropy=lambda: 3)
    _stamp_run(cfg, mine)
    _seed_acquire(cfg, lane="src", loop_ts="2026-06-04T12:00:00Z", run_id=mine.run_id)
    _seed_acquire(cfg, lane="docs", loop_ts="2026-06-04T12:00:01Z", run_id=other.run_id)

    t = TR.build_trace(mine.run_id, cfg)
    assert {e.lane for e in t.lease_events} == {"src"}
    assert t.unattributed_acquires == 0  # the other acquire IS attributed (elsewhere)


# ---------------------------------------------------------------------------
# Lineage — a child is found via the root_id scan.
# ---------------------------------------------------------------------------


def test_lineage_finds_child_run(tmp_path):
    cfg = default_config(tmp_path)
    root = R.mint("dispatch-loop", clock_ms=lambda: 1_700_000_000_000, entropy=lambda: 1)
    child = R.mint("fanout", parent=root, clock_ms=lambda: 1_700_000_000_500,
                   entropy=lambda: 2)
    _stamp_run(cfg, root)
    _stamp_run(cfg, child)

    t_root = TR.build_trace(root.run_id, cfg)
    assert child.run_id in t_root.descendants

    t_child = TR.build_trace(child.run_id, cfg)
    assert root.run_id in t_child.ancestors
    assert t_child.parent_id == root.run_id


# ---------------------------------------------------------------------------
# JSON round-trip + the not-found path.
# ---------------------------------------------------------------------------


def test_to_dict_round_trips(tmp_path):
    cfg = default_config(tmp_path)
    rid = R.mint("dispatch-loop", clock_ms=lambda: 1_700_000_000_000, entropy=lambda: 9)
    _stamp_run(cfg, rid)
    IL.append(rid.run_id, IL.intent_entry(goal="g", start_sha="BEEF",
              declared_steps=["s1"]), cfg=cfg)
    t = TR.build_trace(rid.run_id, cfg)
    d = t.to_dict()
    blob = json.dumps(d)  # must be JSON-serializable
    again = json.loads(blob)
    assert again["run_id"] == rid.run_id
    assert again["intent"]["residual"] == ["s1"]
    assert again["found"] is True


def test_unknown_run_id_is_not_found(tmp_path):
    cfg = default_config(tmp_path)
    t = TR.build_trace("RID-NOSUCHRUN0000", cfg)
    assert t.found is False
    assert t.lease_events == ()
    assert t.steps == ()
    txt = TR.render_text(t)
    assert "no surface found" in txt

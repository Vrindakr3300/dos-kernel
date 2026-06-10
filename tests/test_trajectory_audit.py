"""Tests for the combined trajectory-audit dev tool (`scripts/trajectory_audit.py`).

This is DOS dev tooling, not a kernel module — it `import dos` and lives under
`scripts/`, the same one-way arrow as `release_context.py`. The suite pins the
parts that carry judgement:

  * the per-session waste-flag fold fires at its thresholds (the job-lifted half);
  * the journal layer is HONEST — it detects a benchmark-only journal, recovers a
    refusal whether recorded as `op:REFUSE` or `op:ACQUIRE`+`REFUSED:` reason, and
    NEVER guesses an ambiguous join (1:1 → triple; otherwise → AMBIGUOUS_JOIN);
  * the time-window join respects the ±slack boundary and degrades to
    trajectory-only / journal-only rows;
  * the headline cross-signal fires only on a confidently-attributed triple;
  * `--route-findings` is OFF by default (writes nothing, creates no `.dos/`) and,
    when on, appends idempotently to the decisions sink.

Everything is fixture-driven with an injected clock/stamp and temp dirs — the
`journal_delta`/`loop_decide` replay-testability discipline, no live transcripts.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# Import the script-under-test by path (it is not an installed package).
_HELPER_PATH = Path(__file__).resolve().parent.parent / "scripts" / "trajectory_audit.py"
_spec = importlib.util.spec_from_file_location("trajectory_audit", _HELPER_PATH)
ta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ta)


# ---------------------------------------------------------------------------
# Fixtures — craft a session .jsonl and a journal entry list by hand.
# ---------------------------------------------------------------------------
def _assistant_line(*, ts: str, tools: list[dict], usage: dict | None = None) -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "version": "1.0.0",
        "gitBranch": "feat/x",
        "cwd": "/ws",
        "message": {
            "usage": usage or {},
            "content": [{"type": "tool_use", "name": t["name"], "input": t.get("input", {})}
                        for t in tools],
        },
    }


def _user_line(*, ts: str, text: str, cwd: str = "/ws") -> dict:
    return {
        "type": "user", "timestamp": ts, "cwd": cwd, "gitBranch": "feat/x",
        "message": {"content": [{"type": "text", "text": text}]},
    }


def _write_session(path: Path, lines: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(o) for o in lines) + "\n", encoding="utf-8")


_DEFAULT_CFG = {
    "read_loop_threshold": 4, "poll_threshold": 3, "keepalive_threshold": 5,
    "glob_storm_threshold": 10, "cache_miss_ratio": 0.30, "min_turns": 5,
    "slack_ms": 1000,
}


# ---------------------------------------------------------------------------
# Per-session fold (the job-lifted half).
# ---------------------------------------------------------------------------
def test_read_loop_flag_fires_at_threshold(tmp_path: Path):
    p = tmp_path / "s1.jsonl"
    # Read the same file 4× (== threshold) → read_loop.
    lines = [_user_line(ts="2026-06-01T14:00:00.000Z", text="go")]
    for i in range(4):
        lines.append(_assistant_line(
            ts=f"2026-06-01T14:0{i}:00.000Z",
            tools=[{"name": "Read", "input": {"file_path": "/ws/a.py"}}]))
    _write_session(p, lines)
    s = ta.audit_session(p, _DEFAULT_CFG)
    assert s is not None
    assert any(f["name"] == "read_loop" for f in s["flags"])
    # 3× is below threshold → no flag.
    p2 = tmp_path / "s2.jsonl"
    lines2 = [_user_line(ts="2026-06-01T14:00:00.000Z", text="go")]
    for i in range(3):
        lines2.append(_assistant_line(
            ts=f"2026-06-01T14:0{i}:00.000Z",
            tools=[{"name": "Read", "input": {"file_path": "/ws/a.py"}}]))
    _write_session(p2, lines2)
    s2 = ta.audit_session(p2, _DEFAULT_CFG)
    assert not any(f["name"] == "read_loop" for f in s2["flags"])


def test_shell_poll_and_glob_storm_and_keepalive_flags(tmp_path: Path):
    p = tmp_path / "s.jsonl"
    lines = [_user_line(ts="2026-06-01T14:00:00.000Z", text="go")]
    # 3 polls of the same path → shell_poll
    for _ in range(3):
        lines.append(_assistant_line(ts="2026-06-01T14:00:01.000Z",
            tools=[{"name": "Bash", "input": {"command": "tail -f /ws/out.log"}}]))
    # 10 Glob calls → glob_storm
    for _ in range(10):
        lines.append(_assistant_line(ts="2026-06-01T14:00:02.000Z",
            tools=[{"name": "Glob", "input": {"pattern": "**/*.py"}}]))
    # 5 keepalive markers → keepalive_poll
    for _ in range(5):
        lines.append(_assistant_line(ts="2026-06-01T14:00:03.000Z",
            tools=[{"name": "Bash", "input": {"command": "echo wait-marker"}}]))
    _write_session(p, lines)
    s = ta.audit_session(p, _DEFAULT_CFG)
    names = {f["name"] for f in s["flags"]}
    assert {"shell_poll", "glob_storm", "keepalive_poll"} <= names


def test_cache_miss_flag(tmp_path: Path):
    p = tmp_path / "s.jsonl"
    lines = [_user_line(ts="2026-06-01T14:00:00.000Z", text="go")]
    # 5 turns, all billed-input (no cache_read) → 100% miss ratio over min_turns.
    for i in range(5):
        lines.append(_assistant_line(
            ts=f"2026-06-01T14:0{i}:00.000Z", tools=[],
            usage={"input_tokens": 1000, "cache_read_input_tokens": 0}))
    _write_session(p, lines)
    s = ta.audit_session(p, _DEFAULT_CFG)
    assert any(f["name"] == "cache_miss" for f in s["flags"])
    assert s["first_ts_ms"] is not None and s["last_ts_ms"] is not None


def test_empty_or_unparseable_session_returns_none(tmp_path: Path):
    p = tmp_path / "empty.jsonl"
    p.write_text("\n\n", encoding="utf-8")
    assert ta.audit_session(p, _DEFAULT_CFG) is None


# ---------------------------------------------------------------------------
# Journal layer — benchmark detection, refusal recovery.
# ---------------------------------------------------------------------------
def test_benchmark_only_detection():
    # All null loop_ts + lane-NN → benchmark-only.
    bench = [
        {"op": "ACQUIRE", "lane": "lane-04", "loop_ts": None,
         "ts": "2026-06-01T14:46:00Z", "lease": {"run_id": "RID-1KT1TC5V0JDH0G5"}},
        {"op": "ACQUIRE", "lane": "lane-03", "loop_ts": None,
         "ts": "2026-06-01T14:46:01Z", "lease": {"run_id": "RID-1KT1TC5V0JDX9G4"}},
    ]
    assert ta.fold_journal(bench, since_ms=None)["benchmark_only"] is True
    # A real lane + non-null loop_ts → NOT benchmark-only.
    real = [{"op": "ACQUIRE", "lane": "backend", "loop_ts": "2026-06-01T14:46Z",
             "ts": "2026-06-01T14:46:00Z", "lease": {"run_id": "RID-1KT1TC5V0JDH0G5"}}]
    assert ta.fold_journal(real, since_ms=None)["benchmark_only"] is False
    # Empty journal is NOT benchmark-only (nothing to misread).
    assert ta.fold_journal([], since_ms=None)["benchmark_only"] is False


def test_refusal_recovery_both_shapes():
    entries = [
        # benchmark shape: op:ACQUIRE carrying a REFUSED: reason
        {"op": "ACQUIRE", "lane": "lane-01", "loop_ts": None,
         "ts": "2026-06-01T14:46:00Z", "reason": "REFUSED: lane held",
         "lease": {"run_id": "RID-1KT1TC5V0JDH0G5"}},
        # future real shape: op:REFUSE
        {"op": "REFUSE", "lane": "lane-02", "loop_ts": None,
         "ts": "2026-06-01T14:46:01Z", "reason": "overlap",
         "lease": {"run_id": "RID-1KT1TC5V0JDX9G4"}},
        # a plain acquire is NOT a refusal
        {"op": "ACQUIRE", "lane": "lane-03", "loop_ts": None,
         "ts": "2026-06-01T14:46:02Z", "reason": "",
         "lease": {"run_id": "RID-1KT1TC5V0JDX9G4"}},
    ]
    folded = ta.fold_journal(entries, since_ms=None)
    assert len(folded["refusals"]) == 2
    assert len(folded["leases"]) == 3


def test_since_floor_drops_old_entries():
    entries = [
        {"op": "ACQUIRE", "lane": "lane-01", "loop_ts": None,
         "ts": "2026-06-01T10:00:00Z", "lease": {"run_id": "RID-1KT1TC5V0JDH0G5"}},
        {"op": "ACQUIRE", "lane": "lane-02", "loop_ts": None,
         "ts": "2026-06-01T15:00:00Z", "lease": {"run_id": "RID-1KT1TC5V0JDX9G4"}},
    ]
    # floor between the two → only the later entry survives.
    from dos import journal_delta
    floor = journal_delta._parse_journal_ts("2026-06-01T12:00:00Z")
    folded = ta.fold_journal(entries, since_ms=floor)
    assert len(folded["leases"]) == 1
    assert folded["leases"][0]["lane"] == "lane-02"


def test_corrupt_sentinel_is_observed_not_fatal():
    entries = [{"op": "_CORRUPT", "_raw": "junk", "_line": 3}]
    folded = ta.fold_journal(entries, since_ms=None)
    assert folded["saw_corrupt"] is True
    assert folded["leases"] == []


# ---------------------------------------------------------------------------
# The honest join.
# ---------------------------------------------------------------------------
def _session(stem: str, first_ms: int, last_ms: int, flags=None) -> dict:
    return {
        "session": stem, "first_ts": "t0", "last_ts": "t1",
        "first_ts_ms": first_ms, "last_ts_ms": last_ms,
        "flags": flags or [], "cache_read": 0, "first_user": "",
    }


def _lease(ts_ms: int, lane: str, run_id: str, *, refused=False) -> dict:
    return {
        "ts_ms": ts_ms, "lane": lane, "run_id": run_id,
        "run_started_ms": None, "seq": 1,
        "op": "ACQUIRE", "reason": "REFUSED: held" if refused else "",
    }


def test_join_one_to_one_emits_triple():
    sessions = [_session("sessA", 1000, 2000)]
    journal = {"leases": [_lease(1500, "backend", "RID-AAA")], "refusals": [],
               "benchmark_only": False, "saw_corrupt": False, "total_entries": 1}
    j = ta.join_sessions_to_leases(sessions, journal, slack_ms=1000)
    assert len(j["triples"]) == 1
    tr = j["triples"][0]
    assert tr["session"] == "sessA" and tr["lane"] == "backend" and tr["run_id"] == "RID-AAA"
    assert j["ambiguous"] == []
    assert j["trajectory_only"] == []


def test_raw_acquire_with_run_id_folds_and_joins_to_one_triple():
    """End-to-end (docs/139): a RAW ACQUIRE carrying loop_ts AND a nested
    lease.run_id folds through fold_journal (exercising _lease_run_id + the ts
    parse) and joins to exactly one (session, run_id, lane) triple — the docs/118
    acceptance shape that measured 0 join-ready ACQUIREs on real data.

    Unlike test_join_one_to_one_emits_triple (which starts from a pre-folded
    _lease() dict and bypasses fold_journal), this proves the producer→consumer
    path: a raw WAL entry with run_id nested on the lease survives the fold and is
    named in the triple. Guards the two red-team-confirmed traps: the
    benchmark-pollution poison (benchmark_only must be False) and the window-floor
    pass-on-empty (a too-high since_ms must empty the fold, asserted explicitly so a
    silent empty can never masquerade as a pass), plus a length guard on the [0]
    index.
    """
    raw = {
        "op": "ACQUIRE", "lane": "apply",
        "loop_ts": "20260601T150045Z",
        "ts": "2026-06-01T15:00:45Z",
        "lease": {"run_id": "RID-1KT1TC5V0JDH0G5", "lane": "apply",
                  "loop_ts": "20260601T150045Z", "tree": ["agents/apply_*.py"]},
    }
    folded = ta.fold_journal([raw], since_ms=None)
    assert folded["benchmark_only"] is False          # benchmark-pollution guard
    assert len(folded["leases"]) == 1                  # [0]-fragility guard
    assert folded["leases"][0]["run_id"] == "RID-1KT1TC5V0JDH0G5"
    # Build the session window AROUND the parsed ts (robust to _parse_journal_ts's
    # exact epoch mapping — do not hardcode the ms).
    lts = folded["leases"][0]["ts_ms"]
    sess = [_session("sessA", lts - 1000, lts + 1000)]
    j = ta.join_sessions_to_leases(sess, folded, slack_ms=1000)
    assert len(j["triples"]) == 1
    assert j["triples"][0]["run_id"] == "RID-1KT1TC5V0JDH0G5"
    assert j["triples"][0]["lane"] == "apply"
    # WINDOW-FLOOR TRAP: a since_ms ABOVE the entry's ts drops every lease, so the
    # fold is empty. Pin that the floor actually empties the leases, so a harness can
    # never treat a window-floored-empty fold as a silent pass.
    floored = ta.fold_journal([raw], since_ms=lts + 1)
    assert floored["leases"] == []


def test_join_multiple_lanes_in_window_is_ambiguous():
    sessions = [_session("sessA", 1000, 5000)]
    journal = {"leases": [_lease(1500, "backend", "RID-AAA"),
                          _lease(2500, "frontend", "RID-BBB")],
               "refusals": [], "benchmark_only": False, "saw_corrupt": False,
               "total_entries": 2}
    j = ta.join_sessions_to_leases(sessions, journal, slack_ms=1000)
    assert j["triples"] == []
    assert len(j["ambiguous"]) == 1
    assert set(j["ambiguous"][0]["candidate_lanes"]) == {"backend", "frontend"}


def test_join_shared_lane_across_sessions_is_ambiguous():
    # Two sessions overlap the SAME lease → contended → neither gets a triple.
    sessions = [_session("sessA", 1000, 3000), _session("sessB", 2000, 4000)]
    journal = {"leases": [_lease(2500, "backend", "RID-AAA")], "refusals": [],
               "benchmark_only": False, "saw_corrupt": False, "total_entries": 1}
    j = ta.join_sessions_to_leases(sessions, journal, slack_ms=1000)
    assert j["triples"] == []
    assert len(j["ambiguous"]) == 2


def test_join_no_overlap_is_trajectory_only_and_journal_only():
    sessions = [_session("sessA", 1000, 2000)]
    # lease is far outside the session window + slack
    journal = {"leases": [_lease(99999, "backend", "RID-AAA")], "refusals": [],
               "benchmark_only": False, "saw_corrupt": False, "total_entries": 1}
    j = ta.join_sessions_to_leases(sessions, journal, slack_ms=1000)
    assert j["triples"] == []
    assert len(j["trajectory_only"]) == 1
    assert j["journal_only_lease_count"] == 1


def test_join_slack_boundary():
    # session [1000,2000]; slack 1000 → window [0,3000]. A lease at 3000 is IN,
    # at 3001 is OUT.
    sessions = [_session("sessA", 1000, 2000)]
    in_journal = {"leases": [_lease(3000, "backend", "RID-AAA")], "refusals": [],
                  "benchmark_only": False, "saw_corrupt": False, "total_entries": 1}
    out_journal = {"leases": [_lease(3001, "backend", "RID-AAA")], "refusals": [],
                   "benchmark_only": False, "saw_corrupt": False, "total_entries": 1}
    assert len(ta.join_sessions_to_leases(sessions, in_journal, slack_ms=1000)["triples"]) == 1
    assert ta.join_sessions_to_leases(sessions, out_journal, slack_ms=1000)["triples"] == []


# ---------------------------------------------------------------------------
# The headline cross-signal.
# ---------------------------------------------------------------------------
def test_contention_vs_waste_fires_only_on_attributed_triple_with_refusal_and_flag():
    sessions = [_session("sessA", 1000, 2000, flags=[{"name": "read_loop", "detail": "x"}])]
    journal = {"leases": [_lease(1500, "backend", "RID-AAA", refused=True)],
               "refusals": [_lease(1500, "backend", "RID-AAA", refused=True)],
               "benchmark_only": False, "saw_corrupt": False, "total_entries": 1}
    j = ta.join_sessions_to_leases(sessions, journal, slack_ms=1000)
    cw = ta.contention_vs_waste(sessions, j)
    assert len(cw) == 1
    assert cw[0]["session"] == "sessA" and cw[0]["refusal_events"] == 1
    assert cw[0]["waste_flags"] == ["read_loop"]


def test_contention_vs_waste_silent_without_a_flag():
    sessions = [_session("sessA", 1000, 2000, flags=[])]  # no waste flag
    journal = {"leases": [_lease(1500, "backend", "RID-AAA", refused=True)],
               "refusals": [_lease(1500, "backend", "RID-AAA", refused=True)],
               "benchmark_only": False, "saw_corrupt": False, "total_entries": 1}
    j = ta.join_sessions_to_leases(sessions, journal, slack_ms=1000)
    assert ta.contention_vs_waste(sessions, j) == []


# ---------------------------------------------------------------------------
# End-to-end main() — JSON emit + the --route-findings rail.
# ---------------------------------------------------------------------------
def _seed_workspace(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """A temp DOS workspace (.dos style) + a transcript dir + a redirected
    DOS_HOME, so a full main() run touches nothing real."""
    ws = tmp_path / "ws"
    ws.mkdir()
    # the transcript dir the helper derives from this workspace root
    from dos import config as _config
    cfg = _config.default_config(ws)
    pdir = ta._default_projects_dir(cfg.paths.root)
    pdir.mkdir(parents=True, exist_ok=True)
    # a single realistic session with a read_loop flag, in a known time window
    sp = pdir / "00000000-aaaa-bbbb-cccc-000000000000.jsonl"
    lines = [_user_line(ts="2026-06-01T14:00:00.000Z", text="do the thing", cwd=str(cfg.paths.root))]
    for i in range(4):
        lines.append(_assistant_line(
            ts=f"2026-06-01T14:0{i}:00.000Z",
            tools=[{"name": "Read", "input": {"file_path": "/ws/a.py"}}]))
    _write_session(sp, lines)
    # Redirect the home override so the central projection is hermetic. NOTE the
    # env var is `DISPATCH_HOME` (config.ENV_DOS_HOME) — this line set the literal
    # "DOS_HOME" for months, which nothing reads, so the routing-on test below was
    # silently appending to the operator's REAL central index (the 2026-06-10
    # pollution audit). Import the constant; never re-type the name.
    from dos.config import ENV_DOS_HOME
    monkeypatch.setenv(ENV_DOS_HOME, str(tmp_path / "dos_home"))
    return ws, pdir


def test_main_json_runs_and_emits_valid_json(tmp_path: Path, monkeypatch, capsys):
    ws, _pdir = _seed_workspace(tmp_path, monkeypatch)
    rc = ta.main(["--workspace", str(ws), "--format", "json",
                  "--stamp", "T", "--now-ms", "1780000000000"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["workspace"] == str(ws.resolve())
    assert out["routed_findings"] == 0           # routing OFF by default
    assert "dos" in out and "join" in out["dos"]
    # the seeded read_loop should show up as a systemic finding
    assert any(f["flag"] == "read_loop" for f in out["rollup"]["systemic_findings"])


def test_route_findings_off_writes_no_dot_dos(tmp_path: Path, monkeypatch, capsys):
    ws, _pdir = _seed_workspace(tmp_path, monkeypatch)
    ta.main(["--workspace", str(ws), "--format", "json", "--stamp", "T",
             "--now-ms", "1780000000000"])
    capsys.readouterr()
    # read-only run: no .dos/ created under the workspace, no DOS_HOME tree
    assert not (ws / ".dos").exists()
    assert not (tmp_path / "dos_home").exists()


def test_route_findings_on_appends_idempotently(tmp_path: Path, monkeypatch, capsys):
    ws, _pdir = _seed_workspace(tmp_path, monkeypatch)
    rc = ta.main(["--workspace", str(ws), "--format", "json", "--stamp", "T",
                  "--now-ms", "1780000000000", "--route-findings"])
    assert rc == 0
    first = json.loads(capsys.readouterr().out)["routed_findings"]
    assert first >= 1                              # the read_loop finding routed
    # the local mirror exists now
    assert (ws / ".dos" / "decisions" / "resolved.jsonl").exists()
    # re-run → idempotent (deduped by identity) → zero NEW rows
    ta.main(["--workspace", str(ws), "--format", "json", "--stamp", "T",
             "--now-ms", "1780000000000", "--route-findings"])
    second = json.loads(capsys.readouterr().out)["routed_findings"]
    assert second == 0


def test_main_no_sessions_returns_2(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    from dos import config as _config
    cfg = _config.default_config(ws)
    ta._default_projects_dir(cfg.paths.root).mkdir(parents=True, exist_ok=True)  # empty dir
    rc = ta.main(["--workspace", str(ws), "--format", "json", "--stamp", "T"])
    assert rc == 2


# ---------------------------------------------------------------------------
# Token pricing (docs/130 Prong C — the $0 observe tier). Pure math over a token
# vector + the cache-miss premium; overridable rate. No I/O.
# ---------------------------------------------------------------------------
class TestPriceTokens:
    def test_known_vector_opus_list(self):
        # 8M cold input + 2M cache_creation = 10M billed input @ $5 = $50;
        # 100M cache-read @ $0.50 = $50; 2M output @ $25 = $50; total $150.
        tv = {"input": 8_000_000, "cache_creation": 2_000_000,
              "cache_read": 100_000_000, "output": 2_000_000}
        out = ta.price_tokens(tv, ta.DEFAULT_PRICE)
        assert out["input_cost"] == 50.0
        assert out["cache_read_cost"] == 50.0
        assert out["output_cost"] == 50.0
        assert out["total_cost"] == 150.0

    def test_cache_miss_premium_is_the_avoidable_overpay(self):
        # premium = billed_input × (in_rate − cache_read_rate); here 10M × $4.50.
        tv = {"input": 10_000_000, "cache_creation": 0, "cache_read": 0, "output": 0}
        out = ta.price_tokens(tv, ta.DEFAULT_PRICE)
        assert out["cache_miss_premium"] == 45.0
        # all-cache-read spend has ZERO premium (nothing was re-paid cold).
        warm = ta.price_tokens(
            {"input": 0, "cache_creation": 0, "cache_read": 10_000_000, "output": 0},
            ta.DEFAULT_PRICE)
        assert warm["cache_miss_premium"] == 0.0

    def test_price_override_scales_linearly(self):
        tv = {"input": 1_000_000, "cache_creation": 0, "cache_read": 0, "output": 1_000_000}
        haiku = {"in": 1.0, "out": 5.0, "cache_read": 0.10}   # Haiku 4.5 list
        out = ta.price_tokens(tv, haiku)
        assert out["input_cost"] == 1.0
        assert out["output_cost"] == 5.0
        assert out["total_cost"] == 6.0

    def test_empty_vector_is_zero(self):
        out = ta.price_tokens({}, ta.DEFAULT_PRICE)
        assert out["total_cost"] == 0.0
        assert out["cache_miss_premium"] == 0.0

    def test_rollup_carries_spend_block(self):
        # a minimal session dict shaped like audit_session's return.
        sess = {
            "session": "deadbeefcafe", "cache_read": 100_000_000,
            "tokens": {"input": 10_000_000, "cache_creation": 0,
                       "cache_read": 100_000_000, "output": 2_000_000},
            "tool_calls": {}, "flags": [], "top_read_targets": [],
            "assistant_turns": 10, "first_user": "hi",
        }
        cfg = {"read_loop_threshold": 4, "price": ta.DEFAULT_PRICE}
        roll = ta.rollup([sess], cfg)
        # 10M input@$5=$50 + 100M cache-read@$0.50=$50 + 2M output@$25=$50 = $150
        assert roll["spend"]["total_cost"] == 150.0
        assert roll["spend"]["cache_miss_premium"] == 45.0
        assert roll["heaviest_sessions"][0]["cost"] == 150.0

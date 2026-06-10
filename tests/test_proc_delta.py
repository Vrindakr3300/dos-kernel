"""The OS proc-liveness rung (`dos.proc_delta`) + its demote-only wiring into
`dos.liveness` — C12 of the git-issues→DOS audit (docs/95).

The load-bearing properties:
  * `probe` NEVER raises and NEVER fabricates True — every failure mode degrades
    to alive=None ("could not tell"), the fail-safe direction.
  * In `liveness.classify`, a confident `process_alive=False` DEMOTES an
    otherwise-SPINNING run to STALLED (the forgeable-heartbeat fix); True/None
    leave the verdict byte-identical to before the field existed (zero regression).
"""
from __future__ import annotations

import os

from dos import proc_delta
from dos.liveness import (
    DEFAULT_POLICY,
    Liveness,
    ProgressEvidence,
    classify,
)

_MIN = 60 * 1000


# ── proc_delta.probe — the boundary reader ──────────────────────────────────


def test_live_self_pid_is_alive():
    # This very process is, definitionally, alive.
    r = proc_delta.probe(os.getpid())
    assert r.alive is True
    assert "alive" in r.detail


def test_impossible_pid_is_confidently_gone():
    # A pid that cannot be running (huge) → confidently False on this host.
    r = proc_delta.probe(2_000_000_000)
    assert r.alive is False


def test_no_pid_is_none():
    assert proc_delta.probe(None).alive is None
    assert proc_delta.probe(0).alive is None      # the lease ≤0 TTL-only sentinel
    assert proc_delta.probe(-1).alive is None


def test_foreign_host_is_none():
    # A pid recorded on another host says nothing about ours — never fabricate.
    r = proc_delta.probe(os.getpid(), host_id="other-box", this_host="this-box")
    assert r.alive is None
    assert "foreign host" in r.detail


def test_same_host_probes_normally():
    # host_id == this_host → the foreign guard does not fire; a real probe runs.
    r = proc_delta.probe(os.getpid(), host_id="box", this_host="box")
    assert r.alive is True


def test_hostless_pid_is_not_refused():
    # Both host fields empty (a single-box workspace) → pure pid probe, never None
    # on the host guard (the guard only fires when BOTH are set and differ).
    assert proc_delta.probe(os.getpid()).alive is True


def test_probe_never_raises_on_any_input():
    for pid in (None, 0, -5, 1, os.getpid(), 2_000_000_000):
        for hid, this in (("", ""), ("a", "b"), ("a", "a")):
            r = proc_delta.probe(pid, host_id=hid, this_host=this)
            assert r.alive in (True, False, None)
            assert isinstance(r.detail, str) and r.detail


# ── liveness.classify — the demote-only branch ──────────────────────────────


def _spinning_evidence(**over):
    """Evidence that classifies SPINNING absent any proc signal: no commits, no
    events, a fresh heartbeat, past the grace age."""
    base = dict(
        run_started_ms=0,
        now_ms=DEFAULT_POLICY.grace_ms + _MIN,   # old enough to judge
        commits_since_start=0,
        journal_events_since=0,
        last_heartbeat_age_ms=_MIN,              # 1 min — fresh (≤ spin window)
    )
    base.update(over)
    return ProgressEvidence(**base)


def test_proc_dead_demotes_spinning_to_stalled():
    # The headline: a fresh heartbeat says alive, but the OS says the process is
    # gone → STALLED, not SPINNING (the forgeable-beat gap docs/95 closes).
    assert classify(_spinning_evidence(process_alive=None)).verdict is Liveness.SPINNING
    v = classify(_spinning_evidence(process_alive=False))
    assert v.verdict is Liveness.STALLED
    assert "process is gone" in v.reason


def test_proc_alive_true_leaves_spinning():
    # A confirmed-alive process does not change the spinning verdict (True only
    # corroborates; it never promotes, and here there's nothing to promote).
    assert classify(_spinning_evidence(process_alive=True)).verdict is Liveness.SPINNING


def test_proc_none_is_byte_identical_to_absent():
    # The whole no-regression claim: process_alive=None must give the exact same
    # verdict as omitting the field (the default).
    with_none = classify(_spinning_evidence(process_alive=None))
    without = classify(_spinning_evidence())
    assert with_none.verdict is without.verdict
    assert with_none.reason == without.reason


def test_proc_dead_never_promotes_advancing():
    # A run that ADVANCED (a real commit) stays ADVANCING even if the process is
    # gone — the proc rung is DEMOTE-ONLY and never touches the forward-delta rung
    # (a finished run that committed then exited is not "stalled").
    ev = _spinning_evidence(commits_since_start=3, process_alive=False)
    assert classify(ev).verdict is Liveness.ADVANCING


def test_proc_dead_demotes_even_young_run():
    # A confidently-dead process is dead regardless of run-age: the young-and-alive
    # grace exists to spare a LIVE young run a false SPINNING, and the OS just
    # refuted "live". So process_alive=False demotes to STALLED even under grace.
    young = _spinning_evidence(
        now_ms=_MIN,                  # only 1 min into the run (< grace)
        process_alive=False,
    )
    # Sanity: without the proc signal this young run is the benign ADVANCING guard.
    assert classify(_spinning_evidence(now_ms=_MIN)).verdict is Liveness.ADVANCING
    assert classify(young).verdict is Liveness.STALLED


def test_proc_dead_on_already_stalled_stays_stalled():
    # No fresh heartbeat (already STALLED by the heartbeat rung) + dead process →
    # still STALLED (the demote branch is unreached; the verdict is unchanged).
    ev = ProgressEvidence(
        run_started_ms=0,
        now_ms=DEFAULT_POLICY.grace_ms + _MIN,
        commits_since_start=0,
        last_heartbeat_age_ms=DEFAULT_POLICY.spin_ms + _MIN,  # stale → not alive
        process_alive=False,
    )
    assert classify(ev).verdict is Liveness.STALLED


def test_process_alive_echoed_in_to_dict():
    v = classify(_spinning_evidence(process_alive=False))
    assert v.to_dict()["evidence"]["process_alive"] is False
    # absent → None in the json, never missing the key
    assert classify(_spinning_evidence()).to_dict()["evidence"]["process_alive"] is None


# ── the operator surface (dos liveness --pid) ───────────────────────────────


def _run_liveness(*extra):
    """Drive `dos liveness` in-process against a SPINNING-shaped run; return (rc, out)."""
    import contextlib
    import io

    from dos import cli, run_id

    rid = run_id.mint("test", clock_ms=lambda: 0).run_id
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main([
            "liveness", "--run-id", rid,
            "--now-ms", str(31 * _MIN),          # past the 30-min grace
            "--last-heartbeat-age-ms", str(_MIN),  # 1-min fresh → alive
            *extra,
        ])
    return rc, buf.getvalue().strip()


def test_cli_dead_pid_demotes_to_stalled():
    # The end-to-end proof: a fresh-heartbeat run whose pid the OS says is gone
    # reads STALLED (exit 4), not SPINNING (exit 3).
    rc_alive, out_alive = _run_liveness("--pid", str(os.getpid()))
    assert rc_alive == 3 and "SPINNING" in out_alive

    rc_dead, out_dead = _run_liveness("--pid", "2000000000")
    assert rc_dead == 4 and "STALLED" in out_dead

    # No --pid ⇒ the rung is silent ⇒ byte-identical to the alive case's verdict.
    rc_none, out_none = _run_liveness()
    assert rc_none == 3 and "SPINNING" in out_none


def test_cli_no_proc_flag_disables_the_rung():
    # --no-proc keeps the rung silent even with a dead --pid → SPINNING stands.
    rc, out = _run_liveness("--pid", "2000000000", "--no-proc")
    assert rc == 3 and "SPINNING" in out


def test_cli_foreign_host_keeps_rung_silent():
    # A --host-id that differs from this host ⇒ proc_delta refuses ⇒ None ⇒ the
    # dead pid does NOT demote (we can't trust a cross-host pid).
    rc, out = _run_liveness("--pid", "2000000000", "--host-id", "some-other-box")
    assert rc == 3 and "SPINNING" in out

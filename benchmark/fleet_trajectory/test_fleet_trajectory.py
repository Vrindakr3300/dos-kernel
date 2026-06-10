"""Pinning tests for the fleet-trajectory benchmark (docs/243).

These are DETERMINISTIC — they build synthetic Session objects, never read the
live (non-stationary) corpus. They pin the load-bearing invariants:

  - Track A's CLOBBER vs SERIALIZED vs DISJOINT classification is correct on
    constructed windows.
  - The self-witness guard (docs/243 caveat #1) actually excludes a session.
  - The kernel never FALSE-REFUSES a region-disjoint concurrent pair (the
    specificity floor — a referee that refuses safe parallelism is useless).
  - Track B's claim/witness binning abstains when no downstream witness exists
    (the UNWITNESSABLE bin, docs/192 ~38%).
"""
from __future__ import annotations

import datetime as dt

from benchmark.fleet_trajectory.corpus import (
    Claim, Mutation, Session, ToolEvent, in_dos_tree, _extract_claims, _input_signature, _norm,
)
from benchmark.fleet_trajectory import track_a, track_b, track_c, track_d, track_e


UTC = dt.timezone.utc


_BASE = dt.datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)


def _ts(minute: int) -> dt.datetime:
    return _BASE + dt.timedelta(minutes=minute)


# A NEUTRAL, machine-independent repo root for the synthetic fixtures — the
# default DOS_TREE_ROOT basename ("dos") under a generic parent. The benchmark no
# longer assumes the author's local `…/work/dos` checkout; `/repo/dos` exercises the
# SAME in-tree-vs-sibling discrimination (component `…/dos/…` is in-tree, a
# sibling-prefix `…/dos-strategy/…` is not) without naming any real machine path.
REPO = "/repo/dos"


def _session(sid, edits) -> Session:
    """edits: list of (minute, path). The session's start/end span the edits."""
    muts = [Mutation(ts=_ts(m), tool="Edit", path=_norm(p), in_tree=in_dos_tree(_norm(p))) for m, p in edits]
    times = [m.ts for m in muts]
    return Session(
        sid=sid, path_file=f"{sid}.jsonl", branch="master", cwd=REPO,
        start=min(times), end=max(times), nass=5, sidechain=False, mutations=muts,
    )


P = f"{REPO}/src/dos/cli.py"
Q = f"{REPO}/docs/82_liveness.md"


def test_interleaved_same_path_is_clobber():
    # i writes P at 0 and 30; j writes P at 10 — inside i's window, no commit between.
    si = _session("i", [(0, P), (30, P)])
    sj = _session("j", [(10, P)])
    pl = track_a.classify_pair(si, sj, repo=".", use_git=False)
    assert pl is not None
    assert pl.label == "CLOBBER"
    assert P.lower() in pl.interleaved_paths
    assert pl.kernel_would_refuse is True  # same path => REFUSE_EXACT_GLOB


def test_non_interleaved_same_path_is_serialized():
    # i writes P at 0..5; j writes P at 20 — strictly after, no interleave.
    si = _session("i", [(0, P), (5, P)])
    sj = _session("j", [(20, P)])
    # they still temporally overlap only if windows touch; force overlap via a
    # second disjoint edit that extends i's session span past j's start.
    si = _session("i", [(0, P), (25, Q)])
    sj = _session("j", [(20, P)])
    pl = track_a.classify_pair(si, sj, repo=".", use_git=False)
    assert pl is not None
    # P windows: i=[0,0] (only one P edit), j=[20,20] -> not interleaved -> SERIALIZED
    assert pl.label == "SERIALIZED"


def test_disjoint_paths_admitted_no_false_refuse():
    # the specificity floor: different files, concurrent -> kernel must ADMIT.
    si = _session("i", [(0, P), (10, P)])
    sj = _session("j", [(5, Q), (15, Q)])
    pl = track_a.classify_pair(si, sj, repo=".", use_git=False)
    assert pl is not None
    assert pl.label == "DISJOINT"
    assert pl.kernel_would_refuse is False  # disjoint regions are safe parallelism


def test_sibling_repo_paths_excluded_from_tree():
    # a path in a sibling repo must NOT count as an in-tree mutation. The neutral
    # `/repo/dos…` roots exercise the same component-vs-sibling-prefix split the
    # author's `…/work/dos…` paths used to, without naming a real machine.
    assert in_dos_tree(_norm("/repo/dos/src/dos/cli.py")) is True
    assert in_dos_tree(_norm("/repo/dos-concept-video/render.py")) is False
    assert in_dos_tree(_norm("/repo/dos-strategy/readme.md")) is False
    # dos_mcp lives INSIDE the repo, stays in
    assert in_dos_tree(_norm("/repo/dos/src/dos_mcp/server.py")) is True
    # explicit tree_root override is honored (portability: any clone basename)
    assert in_dos_tree(_norm("/home/me/proj/src/x.py"), tree_root="proj") is True
    assert in_dos_tree(_norm("/home/me/proj-notes/x.py"), tree_root="proj") is False


def test_self_witness_guard_excludes_session(tmp_path, monkeypatch):
    # build a tiny 2-session corpus on disk and confirm exclude_sids drops one.
    import json
    from benchmark.fleet_trajectory import corpus as C

    def write_session(name, sid, edits):
        recs = []
        for i, (minute, path) in enumerate(edits):
            recs.append({
                "type": "assistant", "uuid": f"{sid}-{i}", "sessionId": sid,
                "cwd": REPO, "gitBranch": "master",
                "timestamp": _ts(minute).isoformat().replace("+00:00", "Z"),
                "message": {"content": [
                    {"type": "tool_use", "name": "Edit", "id": f"t{i}", "input": {"file_path": path}}
                ]},
            })
        # pad to >=3 assistant turns
        while sum(1 for r in recs if r["type"] == "assistant") < 3:
            n = len(recs)
            recs.append({"type": "assistant", "uuid": f"{sid}-pad{n}", "sessionId": sid,
                         "cwd": REPO, "timestamp": _ts(n).isoformat().replace("+00:00", "Z"),
                         "message": {"content": [{"type": "text", "text": "ok"}]}})
        f = tmp_path / name
        f.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")

    write_session("a.jsonl", "sid-a", [(0, P), (10, P)])
    write_session("b.jsonl", "sid-b", [(5, P)])

    allS = C.load_corpus(corpus_dir=str(tmp_path))
    assert {s.sid for s in allS} == {"sid-a", "sid-b"}
    excl = C.load_corpus(corpus_dir=str(tmp_path), exclude_sids={"sid-a"})
    assert {s.sid for s in excl} == {"sid-b"}


def test_freeze_before_cutoff_drops_later_sessions(tmp_path):
    import json
    from benchmark.fleet_trajectory import corpus as C

    def write_session(name, sid, start_min):
        recs = []
        for i in range(3):
            recs.append({"type": "assistant", "uuid": f"{sid}-{i}", "sessionId": sid,
                         "cwd": REPO,
                         "timestamp": _ts(start_min + i).isoformat().replace("+00:00", "Z"),
                         "message": {"content": [{"type": "text", "text": "x"}]}})
        (tmp_path / name).write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")

    write_session("early.jsonl", "sid-early", 0)
    write_session("late.jsonl", "sid-late", 40)
    cut = _ts(30)
    frozen = C.load_corpus(corpus_dir=str(tmp_path), before=cut)
    assert {s.sid for s in frozen} == {"sid-early"}


# ----------------------------------------------------------------------------
# Track B — claim extraction tightness + witness soundness
# ----------------------------------------------------------------------------

def test_claim_extractor_rejects_adjectival_committed():
    # the measured failure mode: "committed" as an ADJECTIVE is not a claim.
    assert _extract_claims("This is a committed phased plan, not directional.", _ts(0), "u") == []
    assert _extract_claims("The working tree has uncommitted changes.", _ts(0), "u") == []
    assert _extract_claims("They committed the fix while I was editing.", _ts(0), "u") == []  # third-party
    # but a real first-person announcement IS a claim
    got = _extract_claims("I committed the fix on master.", _ts(0), "u")
    assert any(c.kind == "committed" for c in got)


def test_claim_extractor_rejects_intent_tests_pass():
    # "let me check the tests pass" is INTENT, not an assertion.
    assert _extract_claims("Let me verify the tests pass before moving on.", _ts(0), "u") == []
    assert _extract_claims("Now I need to make the tests pass.", _ts(0), "u") == []
    # a bare assertion IS a claim
    got = _extract_claims("All 34 tests pass.", _ts(0), "u")
    assert any(c.kind == "tests_pass" for c in got)


def test_claim_extractor_rejects_negated_done_shipped():
    assert _extract_claims("This is not done yet.", _ts(0), "u") == []
    assert _extract_claims("dos complete is not yet shipped.", _ts(0), "u") == []
    assert any(c.kind == "done" for c in _extract_claims("This is done.", _ts(0), "u"))


def _claim_session(kind, span, events):
    c = Claim(ts=_ts(0), turn_uuid="u", kind=kind, span=span)
    s = Session(sid="s", path_file="s.jsonl", branch="m", cwd=REPO,
                start=_ts(0), end=_ts(99), nass=5, sidechain=False, claims=[c], tool_events=events)
    return s, c


def test_tests_pass_witness_is_sound_against_shell_artifact():
    # a non-zero EXIT with passing dots and NO 'failed' line is a shell artifact
    # (truncating pipe), NOT an over-claim -> must abstain, not WITNESSED_FALSE.
    ev = ToolEvent(ts=_ts(1), name="Bash", tool_use_id="t", input_repr="python -m pytest -q | head",
                   is_error=True, result_excerpt="Exit code 255\n....... [100%]\n(truncated)")
    s, c = _claim_session("tests_pass", "All tests pass.", [ev])
    lbl = track_b.label_claim(s, c, sorted(s.tool_events, key=lambda e: e.ts))
    assert lbl.verdict == track_b.VERDICT_NONE  # abstain, not FALSE


def test_tests_pass_witness_fires_on_real_failure():
    ev = ToolEvent(ts=_ts(1), name="Bash", tool_use_id="t", input_repr="python -m pytest -q",
                   is_error=True, result_excerpt="Exit code 1\nFAILED tests/test_x.py::test_y - assert 0\n1 failed, 5 passed")
    s, c = _claim_session("tests_pass", "519 tests pass, suite is green.", [ev])
    lbl = track_b.label_claim(s, c, sorted(s.tool_events, key=lambda e: e.ts))
    assert lbl.verdict == track_b.VERDICT_FALSE


def test_tests_pass_witness_true_on_clean_run():
    ev = ToolEvent(ts=_ts(1), name="Bash", tool_use_id="t", input_repr="python -m pytest -q",
                   is_error=False, result_excerpt="")
    s, c = _claim_session("tests_pass", "All tests pass.", [ev])
    lbl = track_b.label_claim(s, c, sorted(s.tool_events, key=lambda e: e.ts))
    assert lbl.verdict == track_b.VERDICT_TRUE


def test_commit_claim_errored_commit_abstains_not_false():
    # a git commit that errored on malformed args / permission is NOT sound
    # evidence the commit claim was false.
    ev = ToolEvent(ts=_ts(1), name="Bash", tool_use_id="t", input_repr="git commit -m the msg",
                   is_error=True, result_excerpt="error: pathspec 'msg' did not match any file(s)")
    s, c = _claim_session("committed", "I committed the fix.", [ev])
    lbl = track_b.label_claim(s, c, sorted(s.tool_events, key=lambda e: e.ts))
    assert lbl.verdict == track_b.VERDICT_NONE


def test_bare_verified_is_unwitnessable():
    # "I verified X" has no separable downstream byte -> the honest ~38% bin.
    s, c = _claim_session("verified", "I verified the registry refactor.", [])
    lbl = track_b.label_claim(s, c, [])
    assert lbl.verdict == track_b.VERDICT_NONE
    assert lbl.witness_kind == "none"


# ----------------------------------------------------------------------------
# corpus — CC project-dir encoding + command signature uniqueness
# ----------------------------------------------------------------------------

def test_cc_project_dir_encoding():
    # CC encodes the workspace abspath into its project-dir name: each of : \ /
    # becomes a single dash, runs NOT collapsed. `D:\proj\app` -> `D--proj-app`.
    # (Regression guard: a portability refactor once defaulted to a non-existent
    # `~/.claude/projects/dos` placeholder and the benchmark loaded 0 sessions.)
    from benchmark.fleet_trajectory.corpus import _cc_project_dir
    import os
    got = _cc_project_dir(r"D:\proj\app")
    assert got.endswith(os.path.join(".claude", "projects", "D--proj-app"))
    got2 = _cc_project_dir("/home/me/work/dos")
    assert got2.endswith(os.path.join(".claude", "projects", "-home-me-work-dos"))


def test_command_signature_distinguishes_shared_prefix():
    # the measured bug: two DIFFERENT multi-line commands sharing a PYTHONPATH
    # setup prefix must NOT collide into one signature (else false thrash).
    a = _input_signature("PowerShell", {"command": '$env:PYTHONPATH="src"\npython -m pytest tests/test_a.py'})
    b = _input_signature("PowerShell", {"command": '$env:PYTHONPATH="src"\npython -m pytest tests/test_b.py'})
    assert a != b
    # but an identical command signs identically (a real repeat)
    c = _input_signature("PowerShell", {"command": '$env:PYTHONPATH="src"\npython -m pytest tests/test_a.py'})
    assert a == c


# ----------------------------------------------------------------------------
# Track C — recovery shape + the two kernel lenses
# ----------------------------------------------------------------------------

def _err(minute, name, sig, is_error):
    return ToolEvent(ts=_ts(minute), name=name, tool_use_id=f"t{minute}", input_repr=sig, is_error=is_error)


def _err_session(events):
    return Session(sid="s", path_file="s.jsonl", branch="m", cwd=REPO,
                   start=_ts(0), end=_ts(99), nass=5, sidechain=False, tool_events=events)


def test_repeated_identical_failure_is_thrash():
    ev = [_err(0, "Bash", "boom#aaa", True), _err(1, "Bash", "boom#aaa", True),
          _err(2, "Bash", "boom#aaa", True), _err(3, "Read", "x", False)]
    s = _err_session(ev)
    lbl = track_c.label_error(s, 0, sorted(s.tool_events, key=lambda e: e.ts))
    assert lbl.label == track_c.THRASHED
    assert lbl.n_repeats >= track_c.THRASH_MIN


def test_error_then_mutation_is_recovered():
    ev = [_err(0, "Bash", "boom#aaa", True), _err(1, "Edit", "/repo/dos/x.py", False)]
    s = _err_session(ev)
    lbl = track_c.label_error(s, 0, sorted(s.tool_events, key=lambda e: e.ts))
    assert lbl.label == track_c.RECOVERED
    assert lbl.mutation_after is True


def test_error_at_session_end_is_gave_up():
    ev = [_err(0, "Bash", "boom#aaa", True)]  # nothing after
    s = _err_session(ev)
    lbl = track_c.label_error(s, 0, sorted(s.tool_events, key=lambda e: e.ts))
    assert lbl.label == track_c.GAVE_UP


def test_breaker_opens_on_sustained_consecutive_run():
    # 3 consecutive failures trips the default max_consecutive=3 breaker, even
    # though productivity (a trend) would not call a recovering blip a stall.
    assert track_c._breaker_opens(3) is True
    assert track_c._breaker_opens(2) is False
    # the consecutive-run counter stops at the first success
    ev = [_err(0, "Bash", "a#1", True), _err(1, "Bash", "b#2", True),
          _err(2, "Bash", "c#3", True), _err(3, "Read", "x", False)]
    s = _err_session(ev)
    assert track_c._consecutive_fail_run(sorted(s.tool_events, key=lambda e: e.ts), 0) == 3


# ----------------------------------------------------------------------------
# Track D — peer-B handoff verdict (the docs/229 forgeable window)
# ----------------------------------------------------------------------------

def test_handoff_witnessed_true_when_committed_before_b():
    # docs/NN committed at t=5; A claimed at t=10; B started at t=20 -> B inherited
    # a git-real artifact -> WITNESSED_TRUE, no forgeable window.
    fc, claim, bstart = _ts(5), _ts(10), _ts(20)
    v, before_claim, before_b, win = track_d.decide_verdict(fc, claim, bstart)
    assert v == track_d.WITNESSED_TRUE
    assert before_claim is True and before_b is True
    assert win is None


def test_handoff_premature_but_landed_before_b_is_near_miss():
    # A claimed "shipped" at t=10, but docs/NN didn't land until t=12 (a 120s
    # forgeable window); B started at t=30 (after the commit) -> still
    # WITNESSED_TRUE for B, but the forgeable window is recorded (docs/229 near-miss).
    fc, claim, bstart = _ts(12), _ts(10), _ts(30)
    v, before_claim, before_b, win = track_d.decide_verdict(fc, claim, bstart)
    assert v == track_d.WITNESSED_TRUE
    assert before_claim is False  # premature at claim time
    assert before_b is True
    assert win == 120.0  # 2 minutes the unbacked claim was inheritable


def test_handoff_on_forged_when_uncommitted_at_b_start():
    # A claimed at t=10, docs/NN didn't land until t=40, but B started at t=20 ->
    # B inherited a claim with NO git backing -> HANDOFF_ON_FORGED.
    fc, claim, bstart = _ts(40), _ts(10), _ts(20)
    v, before_claim, before_b, win = track_d.decide_verdict(fc, claim, bstart)
    assert v == track_d.HANDOFF_ON_FORGED
    assert before_b is False


def test_handoff_unwitnessable_when_never_committed():
    # docs/NN has no git commit at all -> the handoff cannot be witnessed.
    v, before_claim, before_b, win = track_d.decide_verdict(None, _ts(10), _ts(20))
    assert v == track_d.UNWITNESSABLE
    assert win is None


# ----------------------------------------------------------------------------
# Track E — the sliding kernel stream verdict + the unpaired-result fail-safe
# ----------------------------------------------------------------------------

def _tev(minute, name, sig, digest):
    return ToolEvent(ts=_ts(minute), name=name, tool_use_id=f"t{minute}",
                     input_repr=sig, is_error=False, result_digest=digest)


def test_worst_stream_state_finds_midstream_loop_the_tail_misses():
    # a loop in the MIDDLE (steps 1-5 identical), then the agent moves on (advancing
    # tail). classify_stream on the whole stream reads ADVANCING (tail); the sliding
    # worst-state must find the STALLED middle (docs/171's lesson).
    ev = ([_tev(i, "Read", "f#a", "same") for i in range(5)] +
          [_tev(5 + i, "Read", f"g{i}", f"r{i}") for i in range(4)])
    state, run = track_e._worst_stream_state(ev)
    assert state == "STALLED"
    assert run >= 5


def test_unpaired_result_breaks_the_run_no_false_stall():
    # five identical-arg calls but each with an EMPTY result digest (unpaired) must
    # NOT count as a loop — an absent result is not 'the same result' (the kernel
    # fail-safe). Without this, unpaired calls collide into a phantom stall.
    ev = [_tev(i, "Read", "f#a", "") for i in range(5)]
    state, run = track_e._worst_stream_state(ev)
    assert state == "ADVANCING"
    assert run == 0


def test_real_repeated_identical_edit_is_stalled():
    # the measured real case: 8 identical Edits to the same path with the SAME
    # result digest (an idempotent edit landing nothing) -> STALLED.
    ev = [_tev(i, "Edit", "docs/81.md", "0e63a830") for i in range(8)]
    state, run = track_e._worst_stream_state(ev)
    assert state == "STALLED"
    assert run >= 5


def test_advancing_when_results_differ():
    ev = [_tev(i, "Read", f"f{i}", f"r{i}") for i in range(8)]
    state, run = track_e._worst_stream_state(ev)
    assert state == "ADVANCING"

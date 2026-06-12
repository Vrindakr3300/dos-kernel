"""Fault-injection fixtures for the durable JSONL readers (issue #62).

SQLite's anomaly-injection discipline (https://www.sqlite.org/testing.html)
applied to the kernel's two write-ahead files — the lane journal (the lease
registry `arbitrate` admits against) and the intent ledger (the fossil `resume`
re-enters from). Corrupt a valid file SYSTEMATICALLY — at every byte, every
line — and assert the readers degrade SAFELY:

  * never an unhandled traceback (`read_all` / `replay` / `next_seq` /
    `compact` / `resume_plan` are total over arbitrary bytes);
  * line damage is SURFACED as a typed `_CORRUPT` sentinel, never silently
    swallowed, and a sentinel never folds into state;
  * truncation is a PREFIX: it can only forget a suffix of decisions, never
    invent, reorder, or resurrect one;
  * corruption can only SHRINK the believed set — never a false admit out of
    the lease fold, never a false COMPLETE / grown verified set out of the
    resume fold (the verified set is gated on `steps_verified_at_read`,
    env-authored facts no ledger byte can reach);
  * a torn tail never swallows the NEXT successful append (the issue's writer
    bug, found by these fixtures: O_APPEND concatenated a durably-acknowledged
    record onto a terminator-less fragment, and a granted lease became
    invisible to replay — a lost live lease is exactly the false-admit
    `compact`'s docstring calls catastrophic; both writers now newline-repair).

Scope line: the kernel's integrity unit is the LINE. An in-payload byte flip
that KEEPS a line parseable is semantic tamper the reader cannot detect without
checksums (issue #35, design) — for byte flips this file asserts totality, the
closed vocabulary, and the env-authored gates, not byte-exact recovery. The
step ids below are pairwise ≥2 byte-edits apart, so a SINGLE flip can never
mutate one declared step into another verified one and mint a false COMPLETE.
"""
from __future__ import annotations

import json

from dos import arbiter
from dos import intent_ledger as il
from dos import lane_journal as lj
from dos.config import job_config
from dos.resume import AncestryFacts, Resume, ResumePolicy, resume_plan

CFG = job_config("/work/userland-app")

# ── lane-journal fixture ──────────────────────────────────────────────────────

_LEASE_A = {"lane": "alpha", "lane_kind": "cluster", "tree": ["agents/a_*.py"],
            "loop_ts": "T0001", "host_id": "h", "pid": 1}
_LEASE_B = {"lane": "beta", "lane_kind": "cluster", "tree": ["playbooks/p/"],
            "loop_ts": "T0002", "host_id": "h", "pid": 2}
_LEASE_C = {"lane": "gamma", "lane_kind": "cluster", "tree": ["docs/d.md"],
            "loop_ts": "T0003", "host_id": "h", "pid": 3}


def _mk_wal(p):
    """A realistic decision sequence; final live set = {alpha, gamma}."""
    entries = [
        lj.acquire_entry(_LEASE_A),
        lj.acquire_entry(_LEASE_B),
        lj.heartbeat_entry(_LEASE_A),
        lj.release_entry(_LEASE_B),
        lj.acquire_entry(_LEASE_C),
    ]
    return [lj.append(e, path=p) for e in entries]


def _keys(leases):
    return {(str(l.get("loop_ts") or ""), str(l.get("lane") or ""))
            for l in leases}


def _expected_sentinels(raw: bytes) -> int:
    """How many `_CORRUPT` sentinels `read_all` must surface for these bytes:
    one per NON-TRAILING unparseable line (the trailing one is the torn tail,
    skipped as didn't-happen). Mirrors the reader's two arms so the test pins
    that no damaged line is ever SILENTLY dropped from the middle."""
    lines = raw.decode("utf-8", errors="replace").splitlines()
    n = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        try:
            json.loads(s)
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                break
            n += 1
    return n


def _arbitrate_over(live):
    return arbiter.arbitrate(
        requested_lane="alpha", requested_kind="cluster",
        requested_tree=["x/**"], live_leases=live, config=CFG,
    )


class TestJournalTruncation:
    def test_truncation_at_every_byte_is_a_prefix(self, tmp_path):
        """Cutting the file at ANY offset yields the live set of some PREFIX of
        the decision sequence — a truncated WAL forgets a suffix, it never
        invents, reorders, or resurrects a lease. And every fold is total."""
        p = tmp_path / "wal.jsonl"
        stamped = _mk_wal(p)
        prefix_sets = [_keys(lj.replay(stamped[:k]))
                       for k in range(len(stamped) + 1)]
        raw = p.read_bytes()
        q = tmp_path / "cut.jsonl"
        for cut in range(len(raw) + 1):
            q.write_bytes(raw[:cut])
            live = lj.replay(lj.read_all(path=q))   # must not raise
            assert _keys(live) in prefix_sets, f"non-prefix live set at cut={cut}"
            assert lj.next_seq(q) >= 1              # total, never negative/raising


class TestJournalByteFlips:
    def test_every_single_byte_flip_degrades_safely(self, tmp_path):
        """Flip each byte (three replacement patterns): the readers stay total,
        every damaged line is surfaced as a sentinel (never silently dropped),
        sentinels never fold into state, compaction preserves them, and the
        arbiter's verdict over the surviving set stays in the closed vocabulary."""
        p = tmp_path / "wal.jsonl"
        _mk_wal(p)
        raw = p.read_bytes()
        q = tmp_path / "flip.jsonl"
        for i in range(len(raw)):
            for pattern in (raw[i] ^ 0x01, 0x58, 0x39):  # bit-flip, 'X', '9'
                b = bytearray(raw)
                b[i] = pattern
                q.write_bytes(bytes(b))
                entries = lj.read_all(path=q)        # must not raise
                assert all(isinstance(e, dict) for e in entries)
                got = sum(1 for e in entries if e.get("op") == "_CORRUPT")
                assert got == _expected_sentinels(bytes(b)), (
                    f"sentinel mismatch at byte {i} pattern {pattern:#x}"
                )
                live = lj.replay(entries)            # must not raise
                assert all(l.get("lane") != "_CORRUPT" for l in live)
                folded = lj.compact(entries)         # must not raise
                assert sum(1 for e in folded if e.get("op") == "_CORRUPT") == got
                assert _arbitrate_over(live).outcome in ("acquire", "refuse")
                assert lj.next_seq(q) >= 1


class TestJournalLineOps:
    def test_duplicating_any_line_in_place_changes_nothing(self, tmp_path):
        """The replay fold is idempotent under an adjacent duplicate of ANY
        record — a doubled write can never double-grant or double-evict."""
        p = tmp_path / "wal.jsonl"
        _mk_wal(p)
        baseline = _keys(lj.replay(lj.read_all(path=p)))
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        q = tmp_path / "dup.jsonl"
        for i in range(len(lines)):
            q.write_text(
                "".join([*lines[: i + 1], lines[i], *lines[i + 1:]]),
                encoding="utf-8",
            )
            assert _keys(lj.replay(lj.read_all(path=q))) == baseline, (
                f"duplicate of line {i} changed the live set"
            )

    def test_dropping_the_trailing_terminator_changes_nothing(self, tmp_path):
        """A COMPLETE final record that merely lost its newline is still read —
        the torn-tail skip applies to unparseable fragments, not whole records."""
        p = tmp_path / "wal.jsonl"
        _mk_wal(p)
        baseline = _keys(lj.replay(lj.read_all(path=p)))
        p.write_bytes(p.read_bytes().rstrip(b"\r\n"))
        assert _keys(lj.replay(lj.read_all(path=p))) == baseline

    def test_garbage_line_insertion_is_surfaced_and_never_folds(self, tmp_path):
        """A foreign line between any two records becomes a sentinel (mid-file)
        or a skipped torn tail (at the end); the live set never moves. A torn
        ghost-ACQUIRE fragment must never mint a ghost lease; a parseable
        NON-dict line is skipped without a sentinel (it is not a record)."""
        p = tmp_path / "wal.jsonl"
        _mk_wal(p)
        baseline = _keys(lj.replay(lj.read_all(path=p)))
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        q = tmp_path / "ins.jsonl"
        cases = [
            ("@@not json at all@@\n", 1),       # damaged line -> sentinel
            ('{"op": "ACQUIRE", "lane": "ghost"\n', 1),  # torn record -> sentinel
            ("[1, 2, 3]\n", 0),                 # valid non-dict -> skipped quietly
        ]
        for garbage, mid_sentinels in cases:
            for pos in range(len(lines) + 1):
                q.write_text(
                    "".join([*lines[:pos], garbage, *lines[pos:]]),
                    encoding="utf-8",
                )
                entries = lj.read_all(path=q)
                live = lj.replay(entries)
                assert _keys(live) == baseline
                assert all(l.get("lane") != "ghost" for l in live)
                expected = mid_sentinels if pos < len(lines) else 0
                got = sum(1 for e in entries if e.get("op") == "_CORRUPT")
                assert got == expected


class TestTornTailThenAppend:
    """The writer-repair regressions (the bug these fixtures found): a crash's
    terminator-less tail must never swallow the NEXT durably-acknowledged
    append. Pre-fix, O_APPEND concatenated the new record onto the fragment —
    one unparseable line — and a GRANTED lease vanished from replay."""

    def test_journal_append_after_torn_tail_recovers_the_new_record(self, tmp_path):
        p = tmp_path / "wal.jsonl"
        lj.append(lj.acquire_entry(_LEASE_A), path=p)
        with open(p, "ab") as f:  # a writer died mid-append
            f.write(b'{"op": "ACQUIRE", "lane": "ghost", "loop_ts": "TGHOST"')
        lj.append(lj.acquire_entry(_LEASE_B), path=p)  # acknowledged: must survive
        entries = lj.read_all(path=p)
        live = lj.replay(entries)
        assert _keys(live) == {("T0001", "alpha"), ("T0002", "beta")}
        # The fragment is auditable (a mid-file sentinel now), never a lease.
        assert sum(1 for e in entries if e.get("op") == "_CORRUPT") == 1
        assert all(l.get("lane") != "ghost" for l in live)

    def test_journal_repair_never_destroys_a_terminatorless_complete_record(
        self, tmp_path
    ):
        """The repair is a SEPARATOR, not a trim: a complete record that merely
        lost its terminator is preserved as its own line, not deleted."""
        p = tmp_path / "wal.jsonl"
        lj.append(lj.acquire_entry(_LEASE_A), path=p)
        p.write_bytes(p.read_bytes().rstrip(b"\r\n"))
        lj.append(lj.acquire_entry(_LEASE_B), path=p)
        live = lj.replay(lj.read_all(path=p))
        assert _keys(live) == {("T0001", "alpha"), ("T0002", "beta")}

    def test_ledger_append_after_torn_tail_recovers_the_new_record(self, tmp_path):
        p = tmp_path / "ledger.jsonl"
        il.append("RID-1", il.intent_entry(
            goal="g", plan="p", phase="P1", start_sha=_SHA0,
            declared_steps=["step-one"]), path=p)
        with open(p, "ab") as f:
            f.write(b'{"op": "STEP_VERIFIED", "step_id": "step-')
        il.append("RID-1", il.step_verified_entry(
            "step-one", _SHA1, via="file-path"), path=p)
        state = il.replay(il.read_all(path=p))
        assert state.goal == "g"
        assert "step-one" in state.verified  # the acknowledged record survived
        assert state.corrupt_lines == 1      # the fragment stayed auditable


# ── intent-ledger / resume fixture ────────────────────────────────────────────
# Step ids pairwise ≥2 byte-edits apart (see the module docstring's scope line);
# SHAs are full-width hex so the ≥7-char prefix guard in AncestryFacts applies.

_SHA0 = "a0" * 20
_SHA1 = "b1" * 20
_SHA2 = "c2" * 20

_STEPS = ("step-one", "step-two", "step-three")
_ANCESTRY = AncestryFacts(
    shas_in_ancestry=frozenset({_SHA0, _SHA1, _SHA2}),
    steps_verified_at_read=frozenset({"step-one", "step-two"}),
    head_sha=_SHA2,
)


def _mk_ledger(p):
    recs = [
        il.intent_entry(goal="ship the widget", plan="docs/9", phase="P1",
                        start_sha=_SHA0, declared_steps=list(_STEPS)),
        il.step_claimed_entry("step-one", _SHA1),
        il.step_verified_entry("step-one", _SHA1, via="file-path"),
        il.step_claimed_entry("step-two", _SHA2),
        il.step_verified_entry("step-two", _SHA2, via="file-path"),
    ]
    return [il.append("RID-1", e, path=p) for e in recs]


def _resume_over(path, policy=None):
    state = il.replay(il.read_all(path=path))
    return resume_plan(state, _ANCESTRY, policy or ResumePolicy())


class TestLedgerFaultInjection:
    def test_baseline_is_resumable_with_a_two_step_prefix(self, tmp_path):
        p = tmp_path / "ledger.jsonl"
        _mk_ledger(p)
        plan = _resume_over(p)
        assert plan.verdict is Resume.RESUMABLE
        assert plan.verified == ("step-one", "step-two")
        assert plan.residual == ("step-three",)
        assert plan.resume_sha == _SHA2

    def test_truncation_at_every_byte_never_grows_the_belief(self, tmp_path):
        """Cutting the ledger anywhere: total, closed-vocab, the verified set
        only shrinks, and a run with unfinished declared work can never read
        COMPLETE off a damaged fossil."""
        p = tmp_path / "ledger.jsonl"
        _mk_ledger(p)
        raw = p.read_bytes()
        q = tmp_path / "cut.jsonl"
        for cut in range(len(raw) + 1):
            q.write_bytes(raw[:cut])
            plan = _resume_over(q)               # must not raise
            assert plan.verdict in set(Resume)
            assert plan.verdict is not Resume.COMPLETE
            assert set(plan.verified) <= {"step-one", "step-two"}
            assert plan.resume_sha in ("", _SHA0, _SHA1, _SHA2)

    def test_every_single_byte_flip_never_grows_the_belief(self, tmp_path):
        """Flip each byte (three patterns): total, closed-vocab, and the
        non-forgeability floor — no ledger byte can GROW the verified set,
        because "done" is gated on `steps_verified_at_read` (env-authored,
        not in the file) and the in-ancestry SHA check. With step ids ≥2
        edits apart, a single flip can also never mint a false COMPLETE."""
        p = tmp_path / "ledger.jsonl"
        _mk_ledger(p)
        raw = p.read_bytes()
        q = tmp_path / "flip.jsonl"
        for i in range(len(raw)):
            for pattern in (raw[i] ^ 0x01, 0x58, 0x39):  # bit-flip, 'X', '9'
                b = bytearray(raw)
                b[i] = pattern
                q.write_bytes(bytes(b))
                plan = _resume_over(q)           # must not raise
                assert plan.verdict in set(Resume)
                assert plan.verdict is not Resume.COMPLETE, (
                    f"byte {i} pattern {pattern:#x} minted a false COMPLETE"
                )
                assert set(plan.verified) <= {"step-one", "step-two"}, (
                    f"byte {i} pattern {pattern:#x} GREW the verified set"
                )

    def test_removing_any_line_never_grows_the_belief(self, tmp_path):
        p = tmp_path / "ledger.jsonl"
        _mk_ledger(p)
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        q = tmp_path / "drop.jsonl"
        for i in range(len(lines)):
            q.write_text("".join([*lines[:i], *lines[i + 1:]]), encoding="utf-8")
            plan = _resume_over(q)
            assert plan.verdict in set(Resume)
            assert plan.verdict is not Resume.COMPLETE
            assert set(plan.verified) <= {"step-one", "step-two"}

    def test_duplicating_any_line_in_place_changes_nothing(self, tmp_path):
        p = tmp_path / "ledger.jsonl"
        _mk_ledger(p)
        baseline = _resume_over(p)
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        q = tmp_path / "dup.jsonl"
        for i in range(len(lines)):
            q.write_text(
                "".join([*lines[: i + 1], lines[i], *lines[i + 1:]]),
                encoding="utf-8",
            )
            plan = _resume_over(q)
            assert plan.verdict is baseline.verdict
            assert plan.verified == baseline.verified
            assert plan.residual == baseline.residual

    def test_garbage_line_is_counted_and_the_strict_policy_refuses(self, tmp_path):
        """A foreign mid-file line is COUNTED (`corrupt_lines`), the default
        fold rides past it unchanged, and the strict policy turns the count
        into the typed UNRESUMABLE refusal — the refuse-don't-guess rung."""
        p = tmp_path / "ledger.jsonl"
        _mk_ledger(p)
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        p.write_text(
            "".join([lines[0], "@@damaged@@\n", *lines[1:]]), encoding="utf-8"
        )
        state = il.replay(il.read_all(path=p))
        assert state.corrupt_lines == 1
        relaxed = resume_plan(state, _ANCESTRY, ResumePolicy())
        assert relaxed.verdict is Resume.RESUMABLE   # default: ride past, shrunk-safe
        strict = resume_plan(
            state, _ANCESTRY, ResumePolicy(treat_untagged_as_corrupt=True)
        )
        assert strict.verdict is Resume.UNRESUMABLE  # typed refusal, never a guess

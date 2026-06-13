"""The docs/327 spike, pinned — the worktree lifecycle's three kernel-backed moments.

docs/327 argues a worktree is a *transaction* (BEGIN at spawn, COMMIT at merge),
and the kernel already owns a mechanism at all four of its lifecycle moments. This
file is the ~30-line falsifier the doc's §6 promised, frozen as a regression so the
three buildables stay grounded on *shipped* purity rather than on a new mechanism:

  * BIRTH (§1)     — `arbiter.arbitrate` over a worktree's *future merge target* is
                     a thin re-aim: an overlapping target refuses at spawn, a
                     disjoint one acquires. PURE, zero kernel edit.
  * DEATH (§3)     — `lease_health.classify_lease_health` is a shipped four-valued,
                     two-banded read: `DEAD` past the hard TTL *regardless of
                     activity*, `ORPHANED_WORKING` (spare it) only INSIDE the stall
                     band with activity. Proves the activity grace is BOUNDED.
  * JUDGMENT (§4)  — `testwitness.classify` joins the runner's outcome on BOTH trees
                     (only a worktree materializes both): two real OS-recorded
                     outcomes DISCRIMINATE; the SAME two bits narrated ABSTAIN.

None of these touches the kernel — they exercise the unmodified pure leaves, which
is the whole point: `dos merge-gate` (docs/327 build #1) is `run_cycle` with a
generalized metric, a driver + CLI verb, not a kernel change.
"""

from __future__ import annotations

import datetime as _dt

from dos import arbiter, lease_health, testwitness


# ---------------------------------------------------------------------------
# §1 BIRTH — the worktree path is a lease region (a thin re-aim, zero kernel code).
# ---------------------------------------------------------------------------


class TestBirthLeaseFutureMergeTarget:
    """A worktree's eventual merge target, leased at spawn, refuses surface-2 early."""

    def test_overlapping_merge_target_refuses_at_spawn(self) -> None:
        # Agent B wants a worktree whose branch will land on src/dos/** — already
        # the live merge target of agent A's lane. The collision is caught at BIRTH.
        decision = arbiter.arbitrate(
            requested_lane="worktree:src-auth",
            requested_kind="keyword",
            requested_tree=["src/dos/**"],
            live_leases=[{"lane": "src", "lane_kind": "cluster", "tree": ["src/dos/**"]}],
        )
        assert decision.outcome == "refuse"

    def test_disjoint_merge_target_acquires(self) -> None:
        decision = arbiter.arbitrate(
            requested_lane="worktree:docs",
            requested_kind="keyword",
            requested_tree=["docs/**"],
            live_leases=[],
        )
        assert decision.outcome == "acquire"


# ---------------------------------------------------------------------------
# §3 DEATH — the abandoned worktree is a reclaimable lease, two-banded on age.
# ---------------------------------------------------------------------------

# Spike trap, recorded so the next author skips it: `lease_health.parse_iso`
# accepts only a `…Z`-suffixed heartbeat. A `+00:00` offset (what
# `datetime.isoformat()` emits for an aware UTC dt) parses to None → age `inf` →
# DEAD for every case. Stamp the heartbeat with an explicit trailing `Z`.
_NOW = _dt.datetime(2026, 6, 13, 12, 0, 0, tzinfo=_dt.timezone.utc)
_POLICY = lease_health.LeaseHealthPolicy(ttl_minutes=50.0, stall_threshold_minutes=10.0)


def _verdict(age_minutes: float, activity_state: str) -> str:
    heartbeat = (_NOW - _dt.timedelta(minutes=age_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return lease_health.classify_lease_health(
        {"heartbeat_at": heartbeat},
        now=_NOW,
        activity_state=activity_state,
        policy=_POLICY,
    )


class TestDeathWorktreeGc:
    """`classify_lease_health` is the sound worktree-GC read — and its grace is bounded."""

    def test_past_ttl_is_dead_even_while_churning(self) -> None:
        # The load-bearing correction the spike forced: past the hard TTL the lease
        # is DEAD regardless of activity. A worktree that churns useless commits
        # forever is still reclaimed — the activity grace is BOUNDED by the TTL.
        assert _verdict(age_minutes=120, activity_state="LIVE_DOWNSTREAM") == lease_health.LEASE_DEAD

    def test_stall_band_with_activity_is_orphaned_working(self) -> None:
        # Inside the stall band (10 < age <= 50) WITH activity: spare it — this is
        # the case a naive "old dir -> delete" GC gets wrong.
        assert _verdict(age_minutes=30, activity_state="LIVE_DOWNSTREAM") == lease_health.LEASE_ORPHANED_WORKING

    def test_stall_band_unknown_activity_is_orphaned_working(self) -> None:
        # Never reclaim on missing evidence.
        assert _verdict(age_minutes=30, activity_state="UNKNOWN") == lease_health.LEASE_ORPHANED_WORKING

    def test_stall_band_quiet_is_stalled(self) -> None:
        # Same band, genuinely quiet: STALLED -> safe to reclaim.
        assert _verdict(age_minutes=30, activity_state="QUIET") == lease_health.LEASE_STALLED

    def test_fresh_heartbeat_is_live(self) -> None:
        assert _verdict(age_minutes=5, activity_state="LIVE_DOWNSTREAM") == lease_health.LEASE_LIVE


# ---------------------------------------------------------------------------
# §4 JUDGMENT — the merge rung needs BOTH trees, and only joins env-authored bits.
# ---------------------------------------------------------------------------


class TestJudgmentTwoTreeWitness:
    """test-witness DISCRIMINATES only on two real tree-outcomes; narration ABSTAINs."""

    def test_real_two_tree_outcomes_discriminate(self) -> None:
        # baseline FAILED, candidate PASSED, both OS-recorded: red->green across the
        # change. Only a worktree materializes the baseline tree to run the test on.
        verdict = testwitness.classify(testwitness.TestRunEvidence.of("fail", "pass"))
        assert verdict.verdict is testwitness.DISCRIMINATES
        assert verdict.witnesses is True

    def test_same_bits_narrated_abstain(self) -> None:
        # The SAME two bits, agent-authored ("it failed before and passes now") —
        # the forgeable rung. The floor is structural: narration cannot mint a
        # witness, so the verdict ABSTAINs.
        verdict = testwitness.classify(
            testwitness.TestRunEvidence.of("fail", "pass", forgeable=True)
        )
        assert verdict.verdict is testwitness.ABSTAIN
        assert verdict.witnesses is False

"""Property-based proof of the arbiter + lease-WAL pair (issue #62, docs/272 family).

`test_prop_overlap_soundness` pins the overlap FLOOR; `test_prop_breaker` pins the
one stateful pure verdict. This file pins the pair the kernel actually schedules
with: `arbiter.arbitrate` admitting against a live-lease set that is REPLAYED from
the write-ahead log (`lane_journal`) — the production shape, where the journal IS
the registry. A Hypothesis `RuleBasedStateMachine` drives a random interleaving of
acquire / release / scavenge / heartbeat / forensic noise / torn crash-writes /
compaction against a REAL journal file, and after every step asserts the three
laws the issue names:

  * **WAL recovery** — `replay(read_all(journal))` reconstructs the live-lease set
    exactly (the LJ5 hero invariant, here under adversarial interleavings + torn
    tails + mid-run compaction, not just the unit tests' frozen lists).
  * **No two live leases collide under the floor** — every pair of live leases is
    pairwise admissible by `lane_overlap.overlap_verdict` in admit order (the
    later-admitted tree was checked against the earlier live one). A torn or
    compacted journal must never resurrect/forget a lease into a colliding state.
  * **Closed verdict vocabulary** — every `arbitrate` outcome is exactly
    'acquire' | 'refuse', and the decision envelope stays JSON-serializable.

Plus the `@given` laws where they pay most (the issue's third bullet):

  * **Refusal monotonicity** — MORE refusal evidence (an extra live lease) can
    never flip a refuse into an admit. The lease-set analogue of the overlap
    floor's net_admit ⟹ floor_admit.
  * **Closed vocabulary, ∀ requests** — arbitrary lane names / kinds / trees /
    lease sets still land in the two-token outcome set, never a third state or
    an exception.

The machine's config is a SYNTHETIC taxonomy (the `test_arbiter.CLUSTERED_CFG`
discipline): four concurrent lanes with caller-supplied trees (the
dynamic-claim-space shape), no autopick ladder (so a blocked request refuses
crisply instead of redirecting), and the generic exclusive `global` lane.
"""
from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
from pathlib import Path

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from hypothesis.stateful import (  # noqa: E402
    RuleBasedStateMachine,
    invariant,
    precondition,
    rule,
)

from dos import arbiter  # noqa: E402
from dos import lane_journal as lj  # noqa: E402
from dos.config import job_config  # noqa: E402
from dos.lane_overlap import overlap_verdict  # noqa: E402

# A hermetic config (never the active workspace): workspace facts are built for a
# path with no kernel files, so SELF_MODIFY is inert and the machine exercises the
# disjointness/exclusivity mechanism itself. Trees are supplied per-request.
_BASE_CFG = job_config("/work/userland-app")
CFG = dataclasses.replace(
    _BASE_CFG,
    lanes=dataclasses.replace(
        _BASE_CFG.lanes,
        concurrent=("alpha", "beta", "gamma", "delta"),
        autopick=(),
        trees={},
        aliases={},
    ),
)

_LANES = ("alpha", "beta", "gamma", "delta")

# Small-alphabet glob segments so collisions are LIKELY (the
# test_prop_overlap_soundness discipline — a large alphabet would make every
# generated pair trivially disjoint and the floor invariant vacuous).
_segments = st.sampled_from(
    ["agents", "playbooks", "docs", "a", "b", "c", "x_*.py", "*.py"]
)


@st.composite
def _path_glob(draw) -> str:
    n = draw(st.integers(min_value=1, max_value=3))
    return "/".join(draw(_segments) for _ in range(n))


# Non-empty trees only: the empty-tree asymmetry is the DisjointnessPredicate's
# documented special case, pinned elsewhere — here it would only blur the
# pairwise-floor invariant.
_trees = st.lists(_path_glob(), min_size=1, max_size=4)


def _key(lease: dict) -> tuple[str, str]:
    return (str(lease.get("loop_ts") or ""), str(lease.get("lane") or ""))


class ArbiterWalMachine(RuleBasedStateMachine):
    """Random acquire/release/crash/compact interleavings against a real WAL file.

    Shadow state: `self.live_shadow` maps (loop_ts, lane) -> tree for every lease
    the arbiter ADMITTED and the journal durably recorded, in admit order. Every
    arbitrate call reads its live set by REPLAYING the journal file (the
    production loop's shape), so any drift between the WAL fold and the admission
    kernel is a falsifying trace Hypothesis will shrink.
    """

    def __init__(self):
        super().__init__()
        self.tmpdir = Path(tempfile.mkdtemp(prefix="dos-prop-wal-"))
        self.path = self.tmpdir / "lane-journal.jsonl"
        self.live_shadow: dict[tuple[str, str], list[str]] = {}
        self.admit_order: list[tuple[str, str]] = []
        self.n = 0  # loop_ts mint — unique lease identity per acquire

    def teardown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _wal_live(self) -> list[dict]:
        return lj.replay(lj.read_all(path=self.path))

    def _held(self) -> list[tuple[str, str]]:
        return list(self.admit_order)

    def _shadow_lease(self, key: tuple[str, str]) -> dict:
        loop_ts, lane = key
        return {"lane": lane, "loop_ts": loop_ts, "host_id": "prop-host"}

    # ── rules ────────────────────────────────────────────────────────────────
    @rule(lane=st.sampled_from(_LANES), tree=_trees)
    def acquire(self, lane, tree):
        """Ask the arbiter for a named cluster lane; journal an admitted grant."""
        held_lanes = {k[1] for k in self.admit_order}
        d = arbiter.arbitrate(
            requested_lane=lane, requested_kind="cluster",
            requested_tree=list(tree), live_leases=self._wal_live(), config=CFG,
        )
        assert d.outcome in ("acquire", "refuse")  # the closed vocabulary
        if lane in held_lanes:
            # Same-lane single holder: a held name must never be granted again
            # (no autopick ladder in this taxonomy, so no redirect either).
            assert d.outcome == "refuse"
            return
        if d.outcome == "refuse":
            return
        assert d.lane == lane and not d.auto_picked
        self.n += 1
        loop_ts = f"T{self.n:05d}"
        lease = {
            "lane": d.lane, "lane_kind": d.lane_kind, "tree": list(d.tree),
            "loop_ts": loop_ts, "host_id": "prop-host", "pid": self.n,
            "holder": f"h-{self.n}",
        }
        lj.append(lj.acquire_entry(lease), path=self.path)
        self.live_shadow[(loop_ts, d.lane)] = list(d.tree)
        self.admit_order.append((loop_ts, d.lane))

    @rule()
    def acquire_global(self):
        """The exclusive lane: admitted alone, refuses everything while held."""
        d = arbiter.arbitrate(
            requested_lane="global", requested_kind="global",
            requested_tree=["**/*"], live_leases=self._wal_live(), config=CFG,
        )
        assert d.outcome in ("acquire", "refuse")
        if self.live_shadow:
            assert d.outcome == "refuse"  # exclusive must run alone
            return
        assert d.outcome == "acquire"
        self.n += 1
        loop_ts = f"T{self.n:05d}"
        lease = {
            "lane": "global", "lane_kind": d.lane_kind, "tree": ["**/*"],
            "loop_ts": loop_ts, "host_id": "prop-host", "pid": self.n,
        }
        lj.append(lj.acquire_entry(lease), path=self.path)
        self.live_shadow[(loop_ts, "global")] = ["**/*"]
        self.admit_order.append((loop_ts, "global"))

    @precondition(lambda self: bool(self.admit_order))
    @rule(i=st.integers(min_value=0, max_value=7))
    def release(self, i):
        key = self.admit_order[i % len(self.admit_order)]
        lj.append(lj.release_entry(self._shadow_lease(key)), path=self.path)
        self.live_shadow.pop(key, None)
        self.admit_order.remove(key)

    @precondition(lambda self: bool(self.admit_order))
    @rule(i=st.integers(min_value=0, max_value=7))
    def scavenge(self, i):
        key = self.admit_order[i % len(self.admit_order)]
        lj.append(
            lj.scavenge_entry(self._shadow_lease(key), reason="orphan_ttl"),
            path=self.path,
        )
        self.live_shadow.pop(key, None)
        self.admit_order.remove(key)

    @precondition(lambda self: bool(self.admit_order))
    @rule(i=st.integers(min_value=0, max_value=7))
    def heartbeat(self, i):
        """A beat refreshes freshness; it must never change set membership."""
        key = self.admit_order[i % len(self.admit_order)]
        lj.append(lj.heartbeat_entry(self._shadow_lease(key)), path=self.path)

    @rule(which=st.sampled_from(("refuse", "spawn", "halt", "attempt")))
    def forensic_noise(self, which):
        """Non-state ops are recorded history — replay must ignore them all."""
        if which == "refuse":
            d = arbiter.LaneDecision("refuse", lane="alpha", reason="prop-noise")
            e = lj.refuse_entry(d, owner="prop-host")
        elif which == "spawn":
            e = lj.spawn_entry(lane="beta", reason="prop-noise")
        elif which == "halt":
            e = lj.halt_entry("prop-handle", reason="prop-noise")
        else:
            e = lj.attempt_entry("prop-unit", outcome="drained")
        lj.append(e, path=self.path)

    @rule()
    def crash_torn_write(self):
        """A writer dies mid-append: a terminator-less fragment hits the file.

        The fragment is a half-written ACQUIRE for a 'ghost' lane — if any fold
        path ever parsed it into state, the ghost invariant below catches it.
        Later appends must survive it (the torn-tail repair in `lj.append`).
        """
        with open(self.path, "ab") as f:
            f.write(b'{"op": "ACQUIRE", "lane": "ghost", "loop_ts": "TGHOST"')

    @rule()
    def compact_journal(self):
        """Fold the WAL to a CHECKPOINT and rewrite the file — the live set must
        ride through (`replay(compact(E)) == replay(E)`), mid-run."""
        folded = lj.compact(lj.read_all(path=self.path))
        text = "".join(
            json.dumps(e, sort_keys=True, default=str, ensure_ascii=False) + "\n"
            for e in folded
        )
        self.path.write_text(text, encoding="utf-8")

    # ── invariants (checked after every step) ────────────────────────────────
    @invariant()
    def wal_replay_reconstructs_the_live_set_exactly(self):
        live = self._wal_live()
        got = {_key(l): list(l.get("tree") or []) for l in live}
        assert got == self.live_shadow, (
            f"WAL replay drifted from the admitted set: replay={sorted(got)} "
            f"shadow={sorted(self.live_shadow)}"
        )
        # Admit ORDER is part of the contract (replay returns first-acquired
        # order; compaction snapshots must preserve it).
        assert [_key(l) for l in live] == self.admit_order

    @invariant()
    def no_two_live_leases_collide_under_the_floor(self):
        live = self._wal_live()
        for j in range(len(live)):
            for i in range(j):
                later, earlier = live[j], live[i]
                v = overlap_verdict(
                    list(later.get("tree") or []), list(earlier.get("tree") or [])
                )
                assert v.admissible, (
                    f"live pair collides under the floor: {later.get('lane')} "
                    f"{later.get('tree')} vs {earlier.get('lane')} "
                    f"{earlier.get('tree')} -> {v.verdict.value}"
                )

    @invariant()
    def torn_ghost_never_becomes_a_lease(self):
        assert all(l.get("lane") != "ghost" for l in self._wal_live())

    @invariant()
    def at_most_one_holder_per_lane_and_exclusive_alone(self):
        lanes = [k[1] for k in self.admit_order]
        assert len(lanes) == len(set(lanes))
        if any(k[1] == "global" for k in self.admit_order):
            assert len(self.admit_order) == 1


TestArbiterWalMachine = ArbiterWalMachine.TestCase
TestArbiterWalMachine.settings = settings(
    max_examples=40, stateful_step_count=20, deadline=None
)


# ── the @given laws ───────────────────────────────────────────────────────────

_lease_st = st.builds(
    lambda lane, tree, kind: {
        "lane": lane, "lane_kind": kind, "tree": list(tree), "loop_ts": "T-prop",
    },
    lane=st.sampled_from(_LANES),
    tree=_trees,
    # Mostly cluster; the occasional exclusive-kind lease exercises the
    # everything-refused arm of the monotonicity claim too.
    kind=st.sampled_from(("cluster", "cluster", "cluster", "global")),
)


class TestRefusalMonotonicity:
    """More refusal evidence never flips refuse → admit (the issue's law).

    Adding a live lease can only ADD constraints (a busier same-lane set, a new
    tree to collide with, an exclusive hold) — a request the arbiter refused must
    stay refused under the larger lease set. Equivalently: an admitted request
    stays admitted when any lease is removed."""

    @given(
        req_lane=st.sampled_from(_LANES),
        req_tree=_trees,
        base=st.lists(_lease_st, max_size=3),
        extra=_lease_st,
    )
    @settings(max_examples=400, deadline=None)
    def test_adding_a_lease_never_flips_refuse_to_admit(
        self, req_lane, req_tree, base, extra
    ):
        d1 = arbiter.arbitrate(
            requested_lane=req_lane, requested_kind="cluster",
            requested_tree=list(req_tree), live_leases=list(base), config=CFG,
        )
        if d1.outcome != "refuse":
            return
        d2 = arbiter.arbitrate(
            requested_lane=req_lane, requested_kind="cluster",
            requested_tree=list(req_tree), live_leases=[*base, extra], config=CFG,
        )
        assert d2.outcome == "refuse", (
            f"refusal flipped to admit when a lease was ADDED: req={req_lane} "
            f"{sorted(req_tree)} base={len(base)} extra={extra['lane']}"
        )


class TestClosedVocabulary:
    """∀ requests — arbitrary names, kinds, trees, lease sets — the decision is
    exactly 'acquire' | 'refuse' and the envelope serializes (the CLI prints it)."""

    @given(
        lane=st.text(alphabet="abgdl-", min_size=0, max_size=10),
        kind=st.sampled_from(("", "cluster", "keyword", "global")),
        tree=st.one_of(st.just([]), _trees),
        live=st.lists(_lease_st, max_size=3),
    )
    @settings(max_examples=400, deadline=None)
    def test_every_decision_stays_in_the_closed_vocabulary(
        self, lane, kind, tree, live
    ):
        d = arbiter.arbitrate(
            requested_lane=lane, requested_kind=kind,
            requested_tree=list(tree), live_leases=list(live), config=CFG,
        )
        assert d.outcome in ("acquire", "refuse")
        assert isinstance(d.reason, str)
        json.dumps(d.to_dict())  # never an unserializable envelope

"""The deterministic worker + its failure model — identical across both arms.

The honesty invariant (`README.md`): DOS is not given a better agent. Both arms
run the SAME `FailureModel` seeded the SAME way, so they attempt the same lies
and the same colliding writes in the same order. The arms differ only in whether
those attempts are *believed* (open) or *adjudicated* (closed).

Why simulated, not an LLM:
  * Determinism — a benchmark whose result changes run-to-run proves nothing; an
    LLM agent makes lie/collision rates unrepeatable and the A/B unfalsifiable.
  * Verifiability — the whole point is that a "lie" is checkable against git by
    hand. A simulated lie ("claim shipped, write no commit") is exactly that,
    with no model in the loop to argue about.
  * Honesty of claim — we are NOT measuring "how often does Claude lie." We are
    measuring: GIVEN a fleet that lies at rate L and collides at rate C (both
    swept, both observed in real fleets — see calibration note), what does the
    open loop bank that the closed loop catches, as a function of horizon×fanout.
    That is a property of the *kernel*, and it is the defensible claim.

Calibration note (why the default rates are not made up): the repo's own field
record gives order-of-magnitude anchors — METR's maintainer study found ~half of
test-passing SWE-bench-Verified PRs would not be merged (a ~24pp grader
over-optimism), and PAE found 27-78% of tau-bench "successes" procedurally
corrupt. The defaults below (lie≈0.12, collide-attempt governed by the
workload's shared_ratio) sit at the conservative low end of that range; the
sweep covers the rest. Lower rates make DOS look *less* valuable, not more — the
honest direction.
"""
from __future__ import annotations

import dataclasses
import random
import zlib

from .workload import Phase


# A claim is what a worker REPORTS after attempting a phase. In open-loop this is
# believed verbatim; in closed-loop it is re-adjudicated against ground truth.
@dataclasses.dataclass(frozen=True)
class Claim:
    phase: Phase
    claimed_shipped: bool   # what the worker SAYS happened
    claimed_sha: str        # the sha it reports (may be fabricated)
    really_committed: bool  # GROUND TRUTH: did it actually write a real commit?
    real_sha: str           # the real sha if it committed, else ""
    wrote_files: tuple[str, ...]   # files it actually wrote (for collision check)
    is_lie: bool            # really_committed is False but claimed_shipped is True
    is_rework: bool         # this phase was already shipped — re-doing it is waste
    scope_violation: bool = False  # its footprint spilled OUTSIDE its effort's lane
                                   # (docs/86 §3 — the dimension scope.classify catches)


@dataclasses.dataclass(frozen=True)
class FailureModel:
    """The tunable, seeded failure model. Identical object → identical behavior."""

    seed: int
    lie_rate: float = 0.12       # P(claim shipped without a real commit)
    flake_rate: float = 0.08     # P(a real attempt silently fails to commit)
    thrash_rate: float = 0.05    # P(a worker busy-waits / re-reads instead of progressing)
    # docs/86 §3 — P(a real success's footprint SPILLS outside its effort's lane:
    # a cross-lane stomp scope.classify catches). DEFAULT 0.0 so the headline A/B
    # cell is byte-identical to pre-SCF; a sweep opts in (a violation is a NEW
    # banked defect in the open loop, a SCOPE_CREEP verdict in the closed loop).
    scope_violation_rate: float = 0.0

    def worker(self, effort: str) -> "Worker":
        # derive a per-effort RNG so efforts are independent but the whole run is
        # reproducible from the one model seed. We MUST NOT use the built-in
        # hash(effort): CPython salts str hashing per-process (PYTHONHASHSEED), so
        # hash("effort-00") differs every interpreter run — which silently broke the
        # benchmark's headline honesty promise ("same seed → same lies"; the metrics
        # drifted run-to-run). zlib.crc32 is stdlib, unsalted, and stable across
        # processes, so the seed is a pure function of (model seed, effort name).
        effort_salt = zlib.crc32(effort.encode("utf-8")) & 0xFFFFFFFF
        return Worker(self, random.Random(self.seed ^ effort_salt))


class Worker:
    """One effort's worker. `attempt` decides ground truth + what it claims."""

    def __init__(self, model: FailureModel, rng: random.Random):
        self.model = model
        self.rng = rng
        self._counter = 0

    def attempt(self, phase: Phase, *, already_shipped: bool) -> Claim:
        """Attempt a phase. Returns the Claim (what it says) + ground truth.

        Ground-truth outcomes:
          * lie         — claims shipped, writes NO commit (the banked falsehood)
          * flake       — really tries, but the commit silently fails (claims
                          shipped anyway — an *honest mistake*, still false)
          * rework      — the phase was already shipped; doing it again is waste
                          (it may still "succeed", but the work was redundant)
          * success     — claims shipped AND writes a real commit
        """
        self._counter += 1
        r = self.rng.random()
        fabricated_sha = f"fake{self._counter:04d}{self.rng.randrange(0xFFFF):04x}"

        # A lie: claims shipped, no real commit. The open loop banks this.
        if r < self.model.lie_rate:
            return Claim(
                phase=phase, claimed_shipped=True, claimed_sha=fabricated_sha,
                really_committed=False, real_sha="", wrote_files=(),
                is_lie=True, is_rework=already_shipped,
            )

        # A flake: tried for real but the commit didn't land; still reports success
        # (the worker believes it succeeded). Indistinguishable from a lie by
        # shape — only the oracle's git check separates them. Counts as false.
        if r < self.model.lie_rate + self.model.flake_rate:
            return Claim(
                phase=phase, claimed_shipped=True, claimed_sha=fabricated_sha,
                really_committed=False, real_sha="", wrote_files=phase.touches,
                is_lie=True, is_rework=already_shipped,
            )

        # A real success: it actually writes its files and commits. With
        # `scope_violation_rate`, its footprint ALSO spills outside its effort's
        # lane — a cross-lane stomp (docs/86 §3): the commit is real (so `verify`
        # passes), but the blast radius overran the lane it is stamped against,
        # which only `scope.classify` catches. We append a file under a foreign
        # subtree (`effort-99/` — owned by no real effort, so it is outside this
        # effort's `effort-NN/` tree and outside `shared/`): a genuine SCOPE_CREEP.
        real_sha = f"real{self._counter:04d}{self.rng.randrange(0xFFFF):04x}"
        wrote = phase.touches
        scope_violation = self.rng.random() < self.model.scope_violation_rate
        if scope_violation:
            intruder = f"effort-99/intrusion_{self._counter:04d}.txt"
            wrote = tuple(phase.touches) + (intruder,)
        return Claim(
            phase=phase, claimed_shipped=True, claimed_sha=real_sha,
            really_committed=True, real_sha=real_sha, wrote_files=wrote,
            is_lie=False, is_rework=already_shipped, scope_violation=scope_violation,
        )

    def will_thrash(self) -> bool:
        """Whether this step burns spend without progress (the busy-wait class)."""
        return self.rng.random() < self.model.thrash_rate

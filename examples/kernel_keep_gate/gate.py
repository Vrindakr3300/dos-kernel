"""The kernel keep-gate HOST — wire propose→gather→classify for a generated kernel (#107).

This is the layer-4 host issue #107 asks for: it aims the shipped `dos improve`
keep-gate (docs/280) at the hottest self-narrating optimizer in the field — an
LLM-generated GPU kernel claiming "I am faster and numerically correct." The
kernel mechanism is untouched; the host only GATHERS the env-authored witnesses
and folds in the one floor the engine does not yet carry — the #35
harness-tamper check — then hands the facts to the pure kernel.

THE FOUR FACTS, EVERY ONE ENV-AUTHORED (docs/138)
=================================================

`improve.CandidateEvidence` reads four facts; the candidate authors none:

  suite_passed  — the NUMERICS witness: does the candidate's output match the
                  authoritative reference (computed in the harness, where the
                  candidate can't read it) on vectors MINTED AFTER the candidate
                  is frozen, under a TIGHT tolerance the harness sets? (#35-clean
                  is AND-ed in here too — see below.)
  truth_clean   — the TAMPER witness: the candidate diff stays inside the
                  kernel-source lane; the harness/verify tree is byte-identical.
                  A candidate that edits its own measurement harness is
                  structurally unkeepable, not merely suspicious (issue #35).
  work          — the env-timed latency speed score AFTER the candidate (the
                  harness's clock, never the candidate's claim).
  baseline_work — the same score for the baseline kernel.

THE #35 FLOOR — a tree check, not a convention
==============================================

The keep-gate's witnesses (the reference, the minter, the tolerance, the timer)
all live in `harness/`. A candidate whose diff reaches `harness/` could weaken
any of them — loosen the tolerance, mint only easy vectors, time a no-op — and
then measure green-and-fast on its own rigged harness. So the host computes one
extra env-authored fact, `harness_untouched: bool`, from the candidate's
changed-file set against the declared witness tree, and REFUSES (folds it into
`truth_clean=False` → REGRESSED) before any improvement is weighed. This is
SELF_MODIFY generalized from "the kernel's own running code" to "whatever
authors this loop's witnesses." Widening the witness tree (protecting more) is
mechanical; narrowing it is a human-rung act — the tighten-freely/loosen-signed
asymmetry the #35 sketch names.

THE METRIC SEAM — why the timer is injectable
==============================================

Wall-clock latency is noisy; two kernels doing identical work differ only by
scheduler jitter. A keep-gate that let that jitter flip a no-op to KEEP would be
a flaky witness — the very thing it exists to refuse. So the metric is gathered
through an injected `measure` callback: the DEMO path passes the real
`harness.timing.speed_score` (the env clock at the I/O boundary); a TEST pins
the verdicts on frozen, deterministic measured latencies. The verdict itself
stays pure — no clock inside `classify`, the arbiter rule. This is the same
"testable on fakes, the clock lives at the boundary" split as
`dos.drivers.self_improve`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Iterable, Sequence

from dos import improve

from harness import numerics
from harness.timing import speed_score
from harness.vectors import mint

# The witness tree: every path prefix the candidate may NOT touch. The reference,
# the minter, the tolerance, and the timer all live under here. Declared as data
# (the #35 "host declares a witness tree in dos.toml [improve]" sketch — inlined
# for the example); widening this set is mechanical, narrowing it is human-rung.
WITNESS_TREE: tuple[str, ...] = ("harness/",)

# The kernel-source lane: the ONLY prefix a candidate's diff may live under.
KERNEL_SOURCE: tuple[str, ...] = ("kernels/",)


# A kernel candidate is any callable taking a batch of logit rows and returning a
# batch of softmax rows.
KernelFn = Callable[[Sequence[Sequence[float]]], Sequence[Sequence[float]]]
MeasureFn = Callable[[KernelFn, Sequence[Sequence[float]]], int]


@dataclass(frozen=True)
class Candidate:
    """One generated-kernel candidate the gate judges.

    `fn` is the candidate kernel (its public entry point). `narrated` is the
    candidate's own description — carried to the operator surface and parsed for
    NOTHING (docs/234). `changed_paths` is the candidate's diff file-set as git
    would report it (`git diff --name-only`); the host reads the TAMPER witness
    from it, never from the candidate's word about what it touched.
    """

    fn: KernelFn
    narrated: str = ""
    changed_paths: tuple[str, ...] = KERNEL_SOURCE


def harness_untouched(changed_paths: Iterable[str]) -> bool:
    """The #35 tamper witness: True iff NO changed path reaches the witness tree.

    A pure, env-authored fact (git authored `changed_paths`; the loop authored
    zero bytes of it). Any path under `WITNESS_TREE` → False → the candidate is
    structurally unkeepable. Note this is asymmetric to `KERNEL_SOURCE`: a
    candidate may touch fewer paths, but touching the harness at all is refused.
    """
    return not any(
        p.replace("\\", "/").startswith(w) for p in changed_paths for w in WITNESS_TREE
    )


def gather(
    candidate: Candidate,
    *,
    freeze_seed: int,
    baseline: KernelFn,
    measure: MeasureFn = speed_score,
) -> improve.CandidateEvidence:
    """Gather the four env-authored facts for one candidate — the host's I/O boundary.

    Order matters and mirrors the gate's floor structure:

      1. TAMPER FIRST. Read `harness_untouched` from the candidate's diff. If the
         candidate reached the witness tree, the witnesses it would produce are
         not trustworthy — so we DO NOT even run them. We mint the tamper failure
         straight into `truth_clean=False` and return; the kernel will REGRESS it.
         (Running a rigged harness to "see what it says" would be believing the
         candidate's chosen measurement — the exact move #35 refuses.)

      2. MINT AFTER FREEZE. Only for a harness-clean candidate: mint the test
         vectors now, seeded by the environment. The candidate is already frozen
         (its source committed), so it authored none of these inputs.

      3. NUMERICS. Run the candidate on the minted vectors and check the output
         against the harness reference under the tight tolerance — the
         `suite_passed` witness.

      4. LATENCY. Time the candidate and the baseline on the same minted vectors
         through the injected `measure` — `work` and `baseline_work`.

    Returns the frozen `CandidateEvidence`; the caller hands it to
    `improve.classify`. The candidate's `narrated` rides along, read by nothing.
    """
    # 1. TAMPER FIRST — a harness-touching candidate is unkeepable; don't trust its witnesses.
    if not harness_untouched(candidate.changed_paths):
        return improve.CandidateEvidence(
            suite_passed=False,  # we refuse to run a harness the candidate rigged
            truth_clean=False,  # the #35 floor: structurally unkeepable
            work=0,
            baseline_work=1,  # baseline > work so even a "fast" claim can't read as a gain
            narrated=candidate.narrated,
        )

    # 2. MINT AFTER FREEZE — env-seeded inputs the candidate never saw.
    rows = mint(seed=freeze_seed)

    # 3. NUMERICS — the suite witness, against the harness reference, tight tolerance.
    try:
        out = candidate.fn(rows)
        suite_passed = numerics.check(out, rows)
    except Exception:
        # A candidate that crashes on the env vectors is not numerically correct.
        suite_passed = False

    # 4. LATENCY — the env-timed metric, through the injected measure (real clock in the demo).
    work = measure(candidate.fn, rows)
    baseline_work = measure(baseline, rows)

    return improve.CandidateEvidence(
        suite_passed=suite_passed,
        truth_clean=True,  # harness untouched; truth witnesses trustworthy
        work=work,
        baseline_work=baseline_work,
        narrated=candidate.narrated,
    )


def judge(
    candidate: Candidate,
    *,
    freeze_seed: int,
    baseline: KernelFn,
    measure: MeasureFn = speed_score,
    policy: improve.ImprovePolicy = improve.DEFAULT_POLICY,
    consecutive_reverts: int = 0,
) -> improve.CandidateVerdict:
    """Gather the witnesses and hand them to the PURE kernel keep-gate.

    The whole host in one call: `gather` does the I/O, `improve.classify` does
    the verdict. The verdict is a function only of env-authored facts; the
    candidate's narration moved nothing.
    """
    evidence = gather(
        candidate, freeze_seed=freeze_seed, baseline=baseline, measure=measure
    )
    # consecutive_reverts is loop state, not a witness — thread it in here, where
    # the gather (which only produces witnesses) does not own it.
    evidence = replace(evidence, consecutive_reverts=consecutive_reverts)
    return improve.classify(evidence, policy)

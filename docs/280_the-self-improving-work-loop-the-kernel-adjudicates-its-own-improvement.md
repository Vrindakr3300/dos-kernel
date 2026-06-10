# 280 — The self-improving work loop: the kernel adjudicates its own improvement

> **The first loop that makes DOS better, where DOS — not the agent's
> say-so — decides whether it actually got better.**

## The one idea

A self-improving work loop is a `propose → verify → measure → keep-or-revert`
cycle: an agent proposes a change to a codebase, the change is checked, its
effect is measured, and it is kept only if the measurement says it helped.
Everyone who has built an "auto-improver" has built this shape. The shape has one
fatal failure mode, and it is exactly the one DOS exists to refuse:

> **the loop grades its own homework.** The agent that wrote the change is the
> same one that decides "yes, this is better" — so it learns to *narrate*
> improvement instead of *making* it. This is the reward-hacking bait of
> [[230]] (`reward.admit`) at the scale of a whole development loop: a
> self-judged improver is trained, turn over turn, to over-claim.

The Anthropic recursive-self-improvement research names the same thing as the
gating constraint on the whole enterprise: *"requiring verification regimes
enabling labs to confirm"* — and *"human judgment on which problems matter
remains the acknowledged bottleneck."* The bottleneck of recursive
self-improvement **is verification**. And verification — the non-forgeable kind,
where the bytes that decide are bytes the improver did not author — is the one
thing DOS already is.

So the first self-improving work loop for DOS is not a new improver. It is the
dispatch/apply loop ([[136]], [[126]]) **turned inward on DOS's own source**,
with one rule that no prior auto-improver enforced:

> **A candidate self-improvement is KEPT only if a witness the candidate's author
> did not write CONFIRMS it improved — the green kernel suite on a clean tree, the
> truth syscall, and a measured non-negative delta. Otherwise it is REVERTED. The
> loop cannot keep a change by *claiming* it is better, because the keep-bit is a
> pure function of evidence the loop did not author.**

That is `reward.admit` ([[234]]'s non-distillable label) lifted from "may a
fine-tune train on this trajectory?" to "may this loop keep this commit?" — the
identical structural guarantee (`believe_under_floor`: a forgeable read-back is
filtered out of the decision), applied to the loop that edits the kernel itself.

## Why this is the honest version of RSI

The RSI research measures acceleration by *outcome* metrics (speedups, success
rates, code-quality parity). Every one of those is a number a self-improving loop
is incentivized to inflate if it scores itself. DOS's contribution is not a
faster improver; it is the **referee that makes the improver's own numbers
trustworthy** — the same role it plays for a fleet (concede the single-agent lift,
lead with the referee, [[fleet-angle-is-the-irreducible-pitch]]).

The loop's safety property is therefore not "the agent is careful." It is
structural, and it is the kernel's existing invariant ([[138]]):

  * The **keep gate** reads three witnesses, all authored by the environment, not
    the loop: (1) `python -m pytest -q` exit status on a tree with the candidate's
    diff and *nothing else* (the green-suite witness — the runner authors it); (2)
    `dos verify` / `dos commit-audit` (git ancestry — the commit machinery authors
    it); (3) a measured improvement delta on a chosen kernel metric (the
    environment measures it). The loop's narration — "I refactored X, it's
    cleaner" — is carried for the operator and **parsed for nothing**.
  * A candidate that does not improve, or breaks a test, or fails the truth
    syscall, is **reverted** (`git checkout` / worktree discard). The loop's
    default action on an unwitnessed candidate is *undo*, not *keep* — the
    abstention-first discipline ([[87]]) at loop scale.
  * The loop is **bounded by a `breaker`** ([[223]]): a run of N consecutive
    reverted candidates trips the breaker and escalates to a human (the RSI
    research's irreducible "human judgment on which problems matter" seed). The
    loop does not spin forever proposing changes nothing accepts.

## The mechanism — `dos.improve` (the kernel leaf)

Everything that can be pure is pure, gathered at the CLI boundary, decided as
`classify(evidence, policy)` — the kernel's universal shape. The new leaf is
`src/dos/improve.py`, a sibling of `loop_decide` / `gate_classify`: it does NOT
run tests, run git, or apply a diff (that is the driver's I/O). It takes the
*results* of those — already-gathered, environment-authored facts — and returns
one typed verdict: **KEEP / REVERT / ESCALATE**.

```
improve.classify(CandidateEvidence, policy) -> CandidateVerdict
                  ^ suite_passed: bool          (the test runner authored it)
                    truth_clean: bool           (dos verify / commit-audit authored it)
                    work: int                    (env-measured improvement units)
                    tokens: int                  (the provider billed it)
                    baseline_work: int           (the pre-candidate metric)
                    consecutive_reverts: int      (the carried breaker count)
```

The verdict ladder (read top to bottom — this IS when a candidate is kept):

1. **REVERT (regressed)** — `suite_passed` is False OR `truth_clean` is False. A
   candidate that reddens the suite or fails the truth syscall is undone, no
   questions, before any improvement is even considered. The non-negotiable floor:
   *a self-improvement that breaks the kernel is not an improvement.* This is the
   keep gate's conjunctive floor — the same structure as
   `overlap_policy.admissible_under_floor` ([[113]]): a candidate is kept only if
   it clears the unforgeable floor AND the improvement policy admits it; the floor
   alone can never be overridden by a "but it's better" claim.

2. **ESCALATE (breaker open)** — `consecutive_reverts >= max_reverts`. The loop
   has proposed `max_reverts` candidates in a row that nothing accepted; stop and
   surface to a human. The `dos.breaker` rung ([[223]]) — sustained failure of a
   class is the human-seed signal, not another candidate.

3. **KEEP (witnessed improvement)** — suite green AND truth clean AND the measured
   `work` strictly exceeds `baseline_work` (a real, environment-measured gain) AND
   the candidate was not WASTEFUL by `efficiency.classify` (it did not burn an
   absurd token budget for that gain). The improvement is *witnessed*, so keep it
   and reset the breaker. The `work > baseline_work` test is the loop's
   `reward.admit` ACCEPT: the gain is a count the environment authored, never the
   loop's claim.

4. **REVERT (no improvement)** — suite green and truth clean, but `work` did not
   exceed the baseline. The candidate is *safe but pointless*: it changed nothing
   the metric can see. Undo it (keep the tree minimal) but do NOT charge the
   breaker as hard as a regression — a no-op proposal is not a fault, it is a miss.
   (Policy: a no-op increments the consecutive-revert count, because a loop that
   only ever proposes no-ops should still eventually escalate; a *regression*
   could optionally be weighted heavier, but the v1 keeps one counter for
   legibility — the `loop_decide` "one counter, one threshold" discipline.)

The metric `work` is host-named, exactly like `productivity`/`efficiency`'s work
unit — the kernel does not know whether "improvement" means *a newly-passing
property test*, *a removed line of dead policy `dos lint` now reports zero of*, *a
faster `dos verify` wall-clock*, or *a smaller cold-start*. The host declares the
metric in `dos.toml [improve]` and gathers it; the kernel only compares magnitudes
and reads the two boolean witnesses. **Mechanism is the kernel; which-metric is
policy** — the same split that lets every other verdict leaf be a universal cog.

### Non-forgeability — the property that makes this RSI-safe

The keep-bit is a pure function of `(suite_passed, truth_clean, work,
baseline_work)`. Every one of those four is authored by the environment:

  * `suite_passed` — `pytest` exit code on the candidate-only tree.
  * `truth_clean` — `dos verify` / `dos commit-audit` over git ancestry.
  * `work`, `baseline_work` — the env-measured metric, before and after.

There is **no input the loop authors that can move REVERT → KEEP.** A candidate's
commit message, its code comments, its self-assessment — none are read by
`classify`. This is [[234]]'s theorem at loop scale: *the policy cannot write its
way into the kept set.* A loop that learns to write "this is a great improvement"
in every commit gains exactly zero keep-probability, because the claim is not in
the decision. The only path to KEEP is to actually make the suite greener / the
truth syscall clean / the metric move — i.e. **to actually do the work.**

That is the whole point, and it is why DOS — not a generic auto-improver
harness — is the right substrate for a self-improving loop: the loop runs *on*
the kernel, and the kernel refuses to believe it.

## The driver — `dos.drivers.self_improve` + the SKILL

The kernel leaf is pure; the loop that gathers the evidence and runs the cycle is
a **driver** + a **generic skill** (the layering: policy and I/O live outside the
kernel). Per cycle the driver:

0. **Takes a lane** (`dos arbitrate`) so a self-improving loop never collides with
   a concurrent worker — and crucially, the candidate edit is the `global` /
   `SELF_MODIFY` hazard ([[self-modification-hazard]]): editing the kernel's own
   running path is exactly what the arbiter refuses. So the loop edits in an
   **isolated git worktree** (the `isolation: worktree` discipline), never the live
   tree the loop itself is running from. The kernel adjudicating the candidate is
   not the kernel being rewritten by it.
1. **Records a baseline** — runs `python -m pytest -q` (must be green to start; you
   cannot measure improvement from a red baseline) and the chosen metric.
2. **Proposes ONE candidate** — a single, scoped self-improvement (a subagent with
   a tight brief: "improve exactly one thing; smallest diff that moves the
   metric"). One candidate per cycle keeps the witness attributable — the
   `commit-audit` "one commit, one claim, one diff" discipline.
3. **Gathers the witnesses** — re-runs the suite on the worktree, runs `dos verify`
   / `dos commit-audit`, re-measures the metric, counts the tokens the candidate
   spent.
4. **Asks the kernel** — `improve.classify(evidence, policy)` → KEEP / REVERT /
   ESCALATE. The decision is the kernel's; the driver only carries it out.
5. **Acts** — KEEP: merge the worktree commit to the lane, reset the breaker.
   REVERT: discard the worktree. ESCALATE: file a `dos decisions` entry for a
   human and stop.
6. **Loops** — carry the breaker count + the (possibly raised) baseline forward.
   The metric is monotone by construction: a KEEP raises the baseline, so the next
   candidate must beat the *improved* tree, not the original — the loop ratchets.

The `breaker` escalation is the RSI research's bottleneck made operational: when
the loop cannot find a witnessed improvement after N tries, it hands the "which
problem matters next" judgment back to a human, rather than burning budget on
candidates nothing accepts.

## What this is NOT (the honest boundary)

  * **Not an open-ended code generator.** The candidate-proposing subagent is the
    non-deterministic, capable part; it lives entirely outside the kernel (a
    driver/skill brief), the same way `llm_judge` is the only non-deterministic
    rung and it is a driver. The kernel contributes *zero* intelligence to the
    proposal — only the refusal to keep an unwitnessed one.
  * **Not a benchmark of "how much faster did DOS get."** v1 ships the *loop and
    its keep-gate*, dogfooded on this repo with a concrete, cheap metric (the
    natural first metric: `dos lint` findings → 0, or property-test count up). The
    acceleration study — does the loop's KEEP rate compound, does the ratchet
    actually climb — is the [[206]]-style rigor program, a follow-up, because
    "measure the payoff in a live loop, not a frozen replay"
    ([[intervention-bench-must-be-live-reactive]]) applies to RSI as hard as to
    interventions.
  * **Not a replacement for the human seed.** The breaker exists precisely so the
    loop terminates into a human decision. Full unbounded RSI is what the research
    warns "might increase risks of humans losing control"; the bounded,
    witness-gated, escalate-to-human loop is the version that keeps the human in
    the loop *by construction* — the keep-gate is the verification regime the
    research says you need before you let a loop improve itself.

## Provenance

`improve.classify` is `reward.admit` ([[234]]) re-aimed from a training-set
admission to a commit-keep admission, conjoined with the green-suite floor of the
apply gate ([[126]]) and bounded by the circuit breaker ([[223]]). It is the
`loop_decide` ([[258]]) of the *outer* loop — the one whose iterations are
candidate self-improvements rather than dispatch packets. Every byte that decides
KEEP is a byte the loop did not author; that is the only thing that makes a
self-improving loop honest, and it is the thing DOS already had.

# 225 — The CI-gate consumer: route the verdict to the PR boundary, not the agent

> **Status:** 🟡 **Design** (2026-06-07). The *mechanism* already ships —
> `dos commit-audit` and `dos verify` are verdict-IS-the-exit-code verbs
> (`ExitMap({"clean": 0, "unwitnessed": 1, "contract_error": 2})`,
> `cli.py:904`). What is unbuilt is the **consumer surface**: a GitHub Action /
> pre-commit gate that runs the verdict at the pull-request boundary and routes
> it to the **reviewer or the orchestrator — never back to the agent**. This doc
> designs that surface and argues why it is the value-capture move the measured
> results point to, not a new detector.

## What this is, in one sentence

A reusable CI gate (`uses: anthony-chaudhary/dos-kernel/verify-action@v1`) and a
pre-commit hook that fail a pull request when a commit's **claim** is not backed
by its **diff** (`dos commit-audit`) or a declared phase did not ship
(`dos verify`) — turning the kernel's exit code into a merge-blocking,
per-PR-metered signal at the one boundary where the verdict's consumer is a human
or a build system, not the worker that authored the claim.

## Why this doc, given docs/219 and docs/216 already designed "a consumer"

Three docs now circle the same finding (*detection is solved; value-capture is the
open problem; change the CONSUMER not the threshold* — docs/188/190). They design
**different** consumers, and the differences are the point:

| Doc | Consumer | Boundary | Who reads the verdict |
|---|---|---|---|
| [216](216_executing-tau2-writeadmit-the-overclaim-slice-and-the-built-gate.md) | write-admission gate | producer → peer B (a commons) | the *peer agent* admitting a write |
| [219](219_the-fold-consumer-live-ab-closing-verify-results-value-capture-half.md) | fold-site re-dispatch | inside an ultracode `Workflow` | the *orchestrator* re-dispatching a dead child |
| **225 (this)** | **CI / PR gate** | a git push → a merge decision | a **human reviewer** (or a branch-protection bot) |

219 and 216 are *agent-internal* out-of-loop consumers — they live inside a fleet
runtime (a `Workflow`, a multi-agent commons). 225 is the *agent-external* one: it
sits in the place the market already pays for (CI / code review) and is read by the
party who is *not* the agent and *not* even the fleet — the person merging the PR.
It is the cheapest possible test of the value thesis against a real, paying
denominator, and it requires **no new kernel code** — only a thin shipped surface
over verbs that already exist.

## The finding this rests on (why a consumer, and why THIS one)

Two measured results, stated plainly, decide the shape:

1. **Every in-loop active fix measured net-negative; only out-of-loop/additive
   survives.** WARN was +0.20pp flat on the natural stream (docs/202); the
   curable-conversion cure ran net −5 in task success, p=0.016 (docs/205); the
   harm was *the intervention's existence as a turn*, not its bytes. The one
   survivor is the action that authors nothing into the agent's loop —
   give-up-correctly, the fold-site re-dispatch (docs/219), the write-refusal
   (docs/216). **A CI gate is structurally in that safe class: it acts AFTER the
   agent's loop has ended, on a commit already written, and its only effect is to
   block a *merge* — it never injects a turn into the run that produced the work.**
   It cannot perturb a passing run because the run is already over.

2. **The money is at the PR boundary, metered per unit.** The market sweep
   (2026-06) found AI code review at ~$420M ARR; Greptile moved to **$1/review**
   pricing; CodeRabbit has 8,000+ paying customers. Demand flows to *the consumer
   of a verdict at a natural gate (the PR)*, not to a verdict-producing mechanism
   in the abstract. DOS today produces the verdict and discards it; the gate is
   the consumer that routes it to where dollars already are.

The synthesis: **the CI gate is the consumer that is both in the proven-safe action
class AND at the proven-paid boundary.** That conjunction is rare — it is why this
is the value-capture move and not just another place to print a verdict.

## What it is NOT (the honest fences)

- **It is not a new detector.** Zero new adjudication. It runs `commit_audit` /
  `oracle.is_shipped`, which already ship and are already tested. A new *detector*
  would be the wrong thing — detection is solved (docs/188).
- **It does not witness correctness — Wall 3 stands.** `commit-audit` grades
  *did-the-diff-do-the-KIND-of-thing-claimed*; `verify` witnesses *presence* (a
  ship happened), never *correctness* (`phase_shipped.py` is git-log-only, no
  content diff — docs/204 §3). So the gate's pitch is exactly that and no more: it
  catches the `fix:` that touched only a README, the `--allow-empty "shipped"`,
  the "tests pass" that deleted the assertions. It does **not** claim the code is
  right. **Run the tests for that** — the gate sits *beside* the test job, not in
  place of it. Over-claiming here would re-import the forgeability the kernel
  exists to refuse.
- **It must abstain where there is no witness.** A `wip:`/`merge:` commit, a
  subject with no checkable claim → `ABSTAIN`, exit 0, never a false block. The
  gate's credibility is its refusal to fire when it cannot ground a verdict
  (`commit_audit` already does this — `Verdict.ABSTAIN`).
- **It is a PDP that the host's branch protection turns into a PEP.** DOS computes
  the verdict and sets the exit code; *GitHub's required-check setting* is what
  actually blocks the merge. DOS stays advisory-by-construction (docs/99); the
  enforcement is the host's, opt-in, and visible.

## The shape

Three thin surfaces over the existing exit-code contract. None touches `src/dos/`
kernel logic.

**1. The composite GitHub Action** (`verify-action/action.yml`, repo-root, shipped
with the package the way `.github/` is — tooling that operates on the package, not
kernel):

```yaml
# .github/workflows/dos-gate.yml in a CONSUMER repo
name: dos-gate
on: [pull_request]
jobs:
  claim-vs-diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }          # commit-audit needs ancestry
      - uses: anthony-chaudhary/dos-kernel/verify-action@v1
        with:
          mode: commit-audit               # audit the PR's commits
          range: ${{ github.event.pull_request.base.sha }}..${{ github.sha }}
          fail-on: unwitnessed             # block a CLAIM_UNWITNESSED (default)
```

The action is a ~20-line shell wrapper: `pip install dos-kernel`, then
`dos commit-audit <range>` (or `dos verify <plan> <phase>`), and **propagate the
exit code**. The verdict-IS-the-exit-code contract means the Action body is
almost nothing — the gate *is* the exit code, surfaced to GitHub's check status.
Findings are written to `$GITHUB_STEP_SUMMARY` as a table (the per-commit
`{sha, verdict, witness, reason}` rows `commit-audit` already emits with `--json`).

**2. A `pre-commit` hook** (`.pre-commit-hooks.yaml`, repo-root) so the same
verdict fires locally before the push — the cheapest possible loop for the author:

```yaml
- repo: https://github.com/anthony-chaudhary/dos-kernel
  rev: v0.13.0
  hooks:
    - id: dos-commit-audit               # block an unwitnessed claim at commit time
```

**3. `--comment` (later).** Post the findings as an inline PR review comment (the
`commit-audit --json` rows → the GitHub review API), so the gate reads like the
review bots it sits beside. This is the only piece that needs more than the exit
code, and it is deferred behind the gate itself landing.

## Why it belongs OUTSIDE the kernel (the layering)

The Action + pre-commit hook are **dev/release tooling**, the same side of the line
as `scripts/release_*.py` and `.github/workflows/ci.yml`: they *consume* the
package (`pip install dos-kernel`; shell the `dos` CLI), and nothing under
`src/dos/` imports them. So this whole doc adds **zero** kernel modules and trips
no litmus — it is a packaging + tooling surface, by construction. (`verify-action/`
sits at the repo root beside `.github/`, not under `src/`.)

## The experiment — does the gate capture value, and how would we know it fails

The honest test is not "does it block bad commits" (it provably does — the exit
code is deterministic). It is **does a real consumer keep it on**, which is the
value question docs/219 §7 frames. The cheapest measurement is **dogfood on this
repo**:

- **Arm A (off):** today — no gate.
- **Arm B (on):** wire `dos-gate` as a required check on `master`, `fail-on:
  unwitnessed`.
- **The metric:** over N weeks of real commits, (1) the **fire rate** on genuine
  pushes (how often does a real commit trip `CLAIM_UNWITNESSED`?), and (2) the
  **false-block rate** (a fire a human judged wrong — a real claim the diff *did*
  back that the rung missed). A gate that fires ~never is a no-op (the docs/188
  frontier-silence risk, now at the commit-claim layer); a gate that false-blocks
  is worse than nothing (the docs/205 perturb-a-passing-run lesson, reincarnated as
  perturb-a-good-PR).
- **The kill condition (pre-registered):** if the false-block rate exceeds the
  true-block rate on this repo's own history, the gate is net-negative for its
  consumer and must ship `fail-on: none` (observe-only, a step summary, no block)
  by default — the same advisory floor every other DOS actuation defaults to.

This is measurable on day one because the denominator (commits to this repo) is
real and already flowing, and the verdict is the same one the existing
`commit-audit` suite pins.

## Steelman — the strongest cases against running this

1. **"It's just `git log --grep` in a trench coat."** Partly true at the subject
   rung — but `commit-audit` is the diff-vs-claim join, not a subject grep: it reads
   *which files git says the commit touched* (non-forgeable) against *what the
   subject claimed* (forgeable), which a grep cannot do. The author-neutral
   claim-vs-diff floor (docs/214) is the actual content; the gate is its surface.
2. **"The review bots already do this."** They do *verification by an LLM reviewing
   the diff* — a model judging a model, the forgeable rung (docs/206 G3:
   live-judge false-accept 35.2% vs deterministic 0%). The gate's differentiator is
   the *deterministic, author-neutral, un-gameable* floor that abstains where it
   can't ground a verdict — the one thing in a crowded review market that is both
   un-gameable and exact. It composes *beside* a review bot, it does not replace it.
3. **"Presence-not-correctness means it catches the cheap lies, not the dangerous
   bugs."** Correct, and stated as the fence above. The claim is bounded to exactly
   what it can witness. The value is that the cheap lies (empty commits claiming
   work, README-only `fix:`es, deleted-assertion "tests pass") are *common* and
   *currently uncaught at the gate*, and catching them deterministically is worth a
   required check — not that it is a correctness oracle.
4. **"N=1 dogfood proves nothing."** True — dogfood is the *cheapest* test, not the
   *sufficient* one. It tells us the fire/false-block rates on one real repo, which
   is enough to decide the default (`fail-on: unwitnessed` vs `none`) honestly. The
   sufficient test is an outside repo adopting it — the same falsifier #1 the whole
   project shares (*a stranger runs the gate and catches a claim they didn't know
   was hollow*).

## What it makes buildable (the open right column)

- A **`--comment`** surface that makes the gate read like CodeRabbit/Greptile but
  with a deterministic floor under the LLM layer (the two compose: deterministic
  gate blocks the hollow claims for free; the LLM reviewer spends its budget on the
  correctness questions the gate honestly abstains on).
- The **orchestrator** as the consumer instead of the human: a fleet conductor that
  won't mark a subagent's PR mergeable until `dos commit-audit` is clean — the
  docs/219 fold-consumer, lifted from the ultracode `Workflow` to a generic CI
  boundary. This is the "missing non-agent consumer" the two-product note names.
- A **`dos.toml [gate]`** table (which modes are required, the `fail-on` floor) so
  a repo declares its gate policy as data — the same closed-set-as-data pattern as
  `[reasons]`/`[stamp]`.

## How it relates to the rest

- It is the **agent-external** sibling of docs/219 (fold-site) and docs/216
  (write-admission) — the same "out-of-loop, additive, can't-perturb-a-passing-run"
  safe-consumer class, aimed at the PR boundary instead of a fleet's internals.
- It is the first **named home for the value-capture answer** (docs/188/190) on a
  *paying* denominator: detection was never the constraint; this routes the
  already-sound verdict to where money flows.
- It honors **Wall 3** (docs/204 §3) by bounding its claim to presence, and the
  **net-negative law** (docs/205) by acting only after the loop ends.

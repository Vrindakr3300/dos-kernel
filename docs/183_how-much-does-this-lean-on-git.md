# How much does this lean on git? — the floor of ground truth, and why a floor is still load-bearing

> **`verify()` does not consult "the truth." It consults the one tamper-evident
> fossil a code fleet happens to leave — a commit object — and reports *which rung*
> of that fossil it could stand on. Git is necessary and not sufficient, and the
> kernel is shaped by exactly that gap.**

This note is the honest counterweight to [`81_velocity-economics-and-the-fleet-benchmark.md`](81_velocity-economics-and-the-fleet-benchmark.md).
That note argues DOS attacks the *review problem* by moving the **completeness**
question off the human's plate — the human stops fact-checking self-reports and
reviews only judgement. The whole argument rests on one move: *don't read the
agent's claim, read the artifact.* For a code repo that artifact is **git**. So the
fair question — the one a skeptic asks immediately — is: **how heavily is the whole
edifice leaning on git, and is reading git actually enough?**

The short answer, which the rest of this note earns: **git is the *floor* of ground
truth, not the ceiling.** It is necessary — §2 shows you provably *cannot* replace it
with a cleverer reader of claims. It is also not sufficient — §3 shows a clean
`verify()` means *a commit of the right shape exists in ancestry*, which is a long way
from *the work is real, correct, and complete*, and an even longer way from *the done
thing that wasn't a commit at all*. §4 is the resolution: the kernel does not pretend
git is the truth; it returns a **typed verdict with stated provenance** (`source=` /
`via=`) so the human's job becomes *deciding which rungs to trust for which work* —
trust made graduated and legible instead of binary. That graduation **is** the
incompleteness, surfaced rather than hidden.

This is a theory note in the family of [`79`](79_primitives-not-features.md) (why the
syscalls are small), [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) (every syscall
is a refusal), and [`76`](76_flexible-goals-and-verification.md) (where the give
lives). It carries no litmus and is not in the `next-stage-plan` table; the
distillation experiment in §2 is implemented today in
[`benchmark/fleet_horizon/verifier.py`](../benchmark/fleet_horizon/verifier.py), and
the §3 scar tissue is real annotations in
[`src/dos/phase_shipped.py`](../src/dos/phase_shipped.py).

---

## 1. The dependency, stated plainly

Of the four syscalls, the dependence on git is **not uniform** — and seeing where it
concentrates is the first step to bounding it:

| Syscall | Leans on git? | What it actually reads |
|---|---|---|
| `verify()` | **heavily** | commit existence + ancestry + subject grammar (the grep rung); optionally a plan registry cross-checked *against* git (`dos.phase_shipped`). |
| `liveness()` | **heavily** | the commits-since-start-SHA delta (`dos.git_delta`) — "is the run moving?" is a git-delta question. |
| `arbitrate()` | **not at all** | live leases in / decision out. Pure. State, not history. |
| `spawn()` / `reap()` | **not at all** | a sortable run-id + a write-ahead journal record. Identity, not history. |

So the git-dependence is concentrated in the **epistemic** half of the kernel — the
two syscalls that adjudicate *truth over time* (did it ship; is it advancing). That is
not an accident or a wart: the epistemic half is precisely the half that needs an
**external referent the agent cannot author**, and git is the one such referent a code
fleet leaves lying around for free. The *effect* and *identity* halves
(`arbitrate`/`spawn`) need no history, so they touch no git. The honest framing of
"how much does DOS lean on git" is therefore: **the truth syscalls lean on it
entirely, and they lean on it because a self-narrating agent cannot retroactively
forge a reachable commit object — but only the *object*, not its meaning** (§3).

---

## 2. Necessary: you cannot distill the git check away

The first thing a skeptic proposes is to *remove* the git dependence: "if checking
completeness is mechanical, train a cheap model to read the PR and predict whether it
really shipped — then you don't need a deterministic git-reading kernel at all, you
need a better classifier." This is the right experiment to run, and DOS runs it.

[`verifier.py`](../benchmark/fleet_horizon/verifier.py) takes a FleetHorizon
trajectory where every step carries a **label** (`really_committed`, adjudicated
against git) separate from the **claim-side features** a believer can see
(`claimed_shipped`, `n_files_written`, `touches_shared`, `is_rework`). It trains a
dependency-free logistic regression on a train split and scores a held-out split, and
asks: *can claim-side shape reproduce the git-adjudicated label?* The designed —
and most interesting — result (the experiment's hypothesis under test, not yet a
written-up headline number):

- A claim-side model **recovers the pure lies.** A lie that wrote zero files has a
  *shape* — `claimed_shipped=1, n_files_written=0` — and the model learns it. That part
  of the referee *is* distillable into an inference-time pre-filter.
- It then hits a **hard floor at the flake rate.** A **flake** — really tried, files
  written, commit silently failed — is **shape-identical to a success.** Same claim,
  same files touched, same everything a believer can observe. No claim-side feature
  separates a flake from a real ship. *Only reading git does.*

The conclusion is the strong result for DOS: **you can pre-filter with a learned model,
but you cannot remove the referee.** There is an irreducible residue — work that looks
exactly like success from the outside, where the only thing that distinguishes it is
whether a commit actually landed — and that residue is settleable *only* against ground
truth. The flake floor "is a property of the data, not a knob" (the verifier's words);
turn up the flake rate and the distillable fraction shrinks toward zero.

This is the deepest reason the review problem needs a **kernel** and not just a smarter
reviewer-model: the irreducible part of completeness-confirmation is exactly the part
that is **unforgeable-from-narration**, and a model that reads narration (even a very
good one) is structurally the wrong instrument for it. The fix is not *reading claims
better*; it is *not reading claims at all* for the existence question, and consulting
the fossil instead. **That is why git is necessary.** Removing it does not get cheaper —
it gets blind exactly where the lie is shaped like the truth.

---

## 3. Not sufficient: a clean `verify()` is narrower than "the work is real"

Now the harder direction, and the one the §1/§81 story must not paper over. Granting
that git is necessary, *is reading it enough?* No — and the gap has four layers, each a
place where "git says yes" and the work is still absent, wrong, or invisible.

### 3.1 A commit subject is itself a self-report

The cheapest rung of `verify()` — the one that runs when there is **no plan**
(`source="none"`) — is a grep of `git log` subjects against a declared **stamp grammar**
(`dos.stamp`). But a commit subject is *a string the agent authored*. `git commit
--allow-empty -m "docs/foo: ship phase 3"` satisfies a subject-grep predicate over a
no-op diff. So the genuinely unforgeable core is narrower than "the artifact": it is
**existence + reachability + ancestry + authorship of a commit object** — you cannot
*say* a reachable commit into being — but the **mapping** from "phase X is done" to
"a commit like this exists" is a *convention*, and conventions are matched by strings,
and strings are narration.

You do not have to take this as hypothetical. [`phase_shipped.py`](../src/dos/phase_shipped.py)
is a **museum of this exact gap** — every `FQ-NN` annotation is a logged case where
subject-matching gave the wrong answer in production and needed a patch:

- **False positives** (git "said shipped," nothing shipped): a `working-dir snapshot:`
  commit sweeps hundreds of files and incidentally touches a phase's files (`1647b0c0`
  flagged `OC4` shipped); a `docs/fanout:` archive rollup *quotes* another run's history
  and names a phase that was actually halted (`8d4d2851` counted as an `FB2` ship and
  culled the only live pick → empty packet). The fix was an ever-growing
  **bookkeeping-subject exclusion** and a `_PROGRESS_MARKER_WORDS` set (`<PHASE> week-1`,
  `<PHASE> audit`, `<PHASE> baseline` are *progress on* a phase, not a *ship of* it).
- **False negatives** (git "said not shipped," it shipped): the `LF` series shipped in
  real commits but archive churn pushed them past the `-1500` oneline window in ~18 days,
  so every `LF` phase false-NEGATIVED and re-appeared as a phantom pick (FQ-409 — the fix
  was to widen the window to `-4000` and add a slower-moving file-path backstop).

The lesson is not "the rung is buggy" — it is hardened now. The lesson is **structural**:
a subject-grep rung is an *approximation* of ship-truth that drifts with every commit
habit, and the drift is two-directional. Truth-from-subjects is a ladder of patches, not
a clean oracle.

### 3.2 The "registry" rung is also a self-report (cross-checked, which is the point)

`verify()` is "registry-first, ancestry-checked." But the registry — a plan body's
`SHIPPED` stamp, an `execution-state.yaml` — is *another written file*, a richer
self-report. What makes it more than narration is precisely that the kernel does **not**
trust it alone: `_consult_plan_body` uses the stamp only to **demote** a weak git verdict
(a release-prefix or body-mention match) when the plan body has the phase's section and
*no* stamp. The architecture's honesty is in the cross-check — *self-report confirmed
against the git fossil*, never self-report believed. Which means the registry rung
inherits git's sufficiency ceiling exactly: it can only ever confirm *a commit exists*,
dressed up with the operator's stated intent.

### 3.3 Ship ≠ correct ≠ working

Even granting a real, distinctive, ancestry-confirmed commit that genuinely implements
the phase — **a clean `verify()` means *shipped*, not *correct*.** It is the same gap as
a clean *textual* merge that still breaks the build ([`81`](81_velocity-economics-and-the-fleet-benchmark.md) §2.2's
silent-conflict finding): git confirms the bytes exist and are reachable; it says nothing
about whether they compile, pass tests, honor the API contract, or are the *right* design.
`verify()` against git is an **artifact-existence** check, not a **behavior** check. The
file-path backstop (`_check_phase_by_filepath`: does one commit touch ≥2 of the phase's
named load-bearing files?) is a real step *toward* the artifact's content and away from
its subject line — but it still confirms *files were touched*, not *the touch was correct*.

This is also where the §81 completeness claim is bounded honestly: DOS adjudicates
*completeness against a declared predicate*; the strength of the verdict equals the
strength of that predicate. "A commit closing the phase exists" is a **weak** predicate;
"tests pass *and* a commit closing the phase exists" is a **stronger** one. The kernel
does not pick the strength — it adjudicates deterministically against whatever the host
*declared*. Wiring the completion predicate to build/test oracles is what pushes
"complete" toward "correct," and that is a host's predicate to declare, not the kernel's
to assume. **DOS ships the socket; the host chooses how close to "correct" to plug in.**

### 3.4 Git only sees the done-things that fossilize in git

The widest gap, and the one most worth saying out loud because the vision essay invites
it: the [`CLAUDE.md`](../CLAUDE.md) framing is a fleet touching one organization's
"repos, **calendars, and money**." But a fleet's "done"s are not all commits. A deploy
landed (state in a cloud control plane). A migration ran (state in a database). An email
went out, a payment moved, a calendar invite was created, a file was written *outside* the
repo. For **all** of these, git is silent. `verify()` as shipped can only adjudicate the
slice of "done" that leaves a *git-shaped* fossil. The honest general statement is
therefore not "DOS consults ground truth" but **"DOS consults the git slice of ground
truth, and reports when it could not"** (`source="none"`/`via=""`). Everything outside
that slice still routes to a human — or needs a *different oracle* on the same rung-ladder
(§4). This is not a defect to hide; it is the boundary of the *currently shipped* truth
rung, and the architecture is explicitly built to extend past it rather than to pretend
git is universal.

---

## 4. The resolution: a typed verdict with stated provenance *is* the incompleteness, surfaced

Put §2 and §3 together and the position is precise: **git is necessary (you cannot
distill it away) and not sufficient (existence ≠ correctness ≠ the non-git surface).**
A naive design would respond to "not sufficient" by either over-claiming (treat a clean
grep as gospel — the FQ-* false-positive disasters) or giving up (decide truth is
unknowable and trust the agent — back to the open loop). DOS does neither, because of a
choice that runs through the whole kernel (the *typed verdict over binary gate* design
law, and [`76`](76_flexible-goals-and-verification.md)'s *the give lives in provenance,
never the adjudication*):

**`verify()` does not return `shipped: true`. It returns `shipped: true, via:
"direct"` — or `via: "release-prefix"` (weaker), or `via: "demoted-by-plan-body"`, or
`source: "none"` (I had no plan; this is git history alone), or `via: ""` (I could not
confirm at all).** The `via`/`source` field is not metadata garnish — it is the
**rung of the ladder the verdict is standing on**, and the ladder is ordered by
strength:

```
non-git oracle (build/test/deploy)   ← strongest "complete ≈ correct"; host-declared
  registry stamp ⋈ git ancestry      ← intent cross-checked against the fossil
    distinctive file-path overlap     ← the artifact's content, not its subject
      direct-ship subject match       ← the subject line (authored, but ship-shaped)
        release/body mention          ← a bundled mention (weak; demotable)
          source="none"               ← git history alone, no plan to anchor
            via=""                     ← could not confirm; this is a human's call
```

This is the move that converts an *incomplete* truth source into an *honest* one. The
human's job stops being "fact-check every `{shipped:true}`" and becomes **"decide which
rungs you trust for which kinds of work."** Auto-pass the strongly-confirmed (a direct
ship under a strict stamp grammar, or a build-oracle predicate); route the
weakly-confirmed (`source="none"`, `via=""`, a demoted match) to a human via the
`dos decisions` queue, *tagged with the reason it is weak*. The review
problem shrinks not because git is complete, but because the **provenance is legible**:
you triage by confidence rung instead of reading everything at uniform suspicion.

So the answer to "isn't this leaning awfully hard on git, and git isn't a complete
solution?" is: **yes, and the kernel is built from that yes.** Git is the necessary,
cheap, unforgeable-at-the-object-level floor. The rung-ladder above it — file-path
overlap, the registry cross-check, and ultimately host-declared build/test/non-git
oracles — is the *staircase toward sufficiency*, and the typed `via`/`source` verdict is
the kernel **telling you which step it is standing on** so you never mistake the floor
for the ceiling. DOS does not claim to know the truth. It claims to never *believe* a
claim, to consult the best fossil available, and to **report how good that fossil was** —
which is a strictly more honest thing than either blind trust or a fabricated certainty.

---

## 5. What this note does and does not claim

- **Does claim:** the git check is *necessary* — provably non-distillable past the flake
  floor (§2); the *shipped* truth rung is real, hardened, and shipped; and the
  typed-verdict-with-provenance design (§4) is what makes an admittedly-incomplete source
  honest and triageable.
- **Does not claim:** that git is *the* truth, that a clean `verify()` implies
  correctness or a working build (§3.3), that subject-grep is unforgeable (§3.1), or that
  DOS today adjudicates the non-git surface — deploys, DBs, money, calendars (§3.4). Those
  are rungs the ladder is *designed to grow*, not rungs it already has.
- **The honest one-liner:** DOS's solution to the review problem is only as broad as the
  set of "done"s that leave a checkable, git-like fossil, and only as deep as the predicate
  the host declares — and the kernel's contribution is to make *both* of those bounds
  explicit in the verdict, instead of hiding them behind a boolean.

---

## References (pointers to the code and sibling notes that ground each claim)

*The necessity argument (§2):*
- [`benchmark/fleet_horizon/verifier.py`](../benchmark/fleet_horizon/verifier.py) — the
  distillation experiment: claim-side logistic regression vs the git-adjudicated label,
  with the `sha_looks_real` ablation and the flake-residue breakdown. The flake floor is
  the falsifier.
- [`benchmark/fleet_horizon/trajectory.py`](../benchmark/fleet_horizon/trajectory.py) —
  where the per-step `(features, really_committed)` record is emitted (claim side separated
  from ground-truth label).

*The insufficiency scar tissue (§3):*
- [`src/dos/phase_shipped.py`](../src/dos/phase_shipped.py) — the grep rung; the `FQ-77`
  (bookkeeping false-positive, both directions), `FQ-409` (windowing false-negative),
  `_PROGRESS_MARKER_WORDS`, `_is_shared_infra`, and `_consult_plan_body` annotations are the
  logged record of subject-truth drifting in production.
- [`src/dos/stamp.py`](../src/dos/stamp.py) — the ship-stamp grammar as per-workspace data
  (the SCV seam): what a subject must look like to count, declarable in `dos.toml [stamp]`.
- [`src/dos/git_delta.py`](../src/dos/git_delta.py) — the shared commits-since-SHA reader
  `verify` and `liveness` both lean on; the concrete locus of the git dependence.

*The resolution (§4):*
- [`81_velocity-economics-and-the-fleet-benchmark.md`](81_velocity-economics-and-the-fleet-benchmark.md) §2.3–2.4 — the
  review-problem claim this note bounds (completeness off the human's plate; the honest
  completeness-vs-correctness boundary).
- [`76_flexible-goals-and-verification.md`](76_flexible-goals-and-verification.md) — the give
  lives in *provenance* (the rung-ladder) and *which-signals* (the host predicate), never the
  adjudication. §4's staircase is that law made concrete.
- [`79_primitives-not-features.md`](79_primitives-not-features.md) §5 — what to *do* after a
  weak/`none` verdict (replan, escalate, soak) is host workflow, not kernel; the kernel's job
  ends at the typed verdict.
- [`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md) —
  `verify()`'s load-bearing return is the *refusal to believe narration*; `source`/`via` is the
  shape of *how strong* that refusal could be.
- [`102_when-to-trust-an-agent.md`](102_when-to-trust-an-agent.md) — the converse: where
  the kernel *does* trust an agent (prior commitments, not reports). The flake floor (§2 here)
  is 102's §6.2 win; the necessary-not-sufficient ceiling (§3 here) is why correctness is a
  judge's call, not the kernel's, in 102's detectable×reversible map.

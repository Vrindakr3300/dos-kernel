# The adjudicator population — two open axes, one router, one instrument

> **The driver layer's reframe — "where the kernel composes adjudicators it
> doesn't fully trust, under a discipline that keeps the untrusted from corrupting
> the trusted, and an instrument that scores them" ([`87`](87_the-adjudicator-trust-ladder.md))
> — has a second half that only became true on disk. The adjudicators are not one
> kind growing in one place. They are a *population* that grows along **two
> mirror-image axes**: kernel-grade verdicts that earn their way *in* (the typed
> contract, [`86`](86_the-typed-verdict-surface.md)), and provider-backed judges
> that are structurally kept *out* (the judge seam, [`87`](87_the-adjudicator-trust-ladder.md)).
> One test routes a proposed adjudicator to its axis. One instrument scores both
> against the same ground-truth-labeled run. This note names the population, the
> router, and the instrument — the synthesis the two prior notes describe one side
> of each.**

A theory + how-to note in the family of [`79`](79_primitives-not-features.md) (the
syscalls are small so a buildable space opens above them),
[`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) (every syscall is a kind of "no"),
[`85`](85_extending-the-verifiable-surface.md) (extend the verifiable surface deeper
before broader), [`86`](86_the-typed-verdict-surface.md) (the typed-verdict ABI), and
[`87`](87_the-adjudicator-trust-ladder.md) (the trust-ladder / scalable-oversight
framing). It carries no litmus and is not in the `next-stage-plan` table. Unlike its
two parents, **everything it synthesizes is built** on this branch: the typed-verdict
contract (`src/dos/verdict.py`), the first new verdict on it (`src/dos/scope.py`), the
judge seam (`src/dos/judges.py`), the two instruments (`dos judge-eval` and the
FleetHorizon trajectory columns `verdict_in_scope` / `verdict_advancing`). The honest
gaps — the registry is specced-not-shipped, the study is unrun — are §5.

---

## 1. Two notes, one missing sentence

[`86`](86_the-typed-verdict-surface.md) and [`87`](87_the-adjudicator-trust-ladder.md)
were written days apart and each looks at the driver-layer reframe through one lens:

- **`86` (the ABI lens).** Four kernel verdicts already almost share one
  `classify(Evidence, Policy) -> Verdict[V]` shape. Name the contract; let a third
  party register a *sixth* verdict the way you add a device driver. The new adjudicators
  here are **deterministic, forgery-proof, kernel-grade** — they get a `dos <verb>`
  subcommand, a decisions-queue row, an MCP tool. They join the kernel.

- **`87` (the trust-ladder lens).** A blocked claim escalates ORACLE → JUDGE → HUMAN.
  The JUDGE rung is a model/heuristic/debate ruling on the residue the deterministic
  oracle abstained on. The new adjudicators here are **non-deterministic,
  provider-backed, not forgery-proof** — they are *structurally kept out of the kernel*
  and contained in `drivers/` under four disciplines. They never join the kernel.

Read together, the missing sentence is obvious in hindsight: **these are not two
separate stories about two separate features. They are the two ways one population —
the set of all adjudicators DOS can compose — is allowed to grow.** `86`'s registry is
the *in-door*; `87`'s seam is the *out-house*. The thing that decides which door a
proposed adjudicator walks through is a single test both notes already cite but neither
frames as the router: the [`85 §2`](85_extending-the-verifiable-surface.md) four-gate
test.

This note's whole content is that one diagram and its consequences:

```
                    a proposed new adjudicator
                              │
                  ┌───────────┴───────────┐
                  │  the four-gate test    │   (docs/85 §2, the router)
                  │  1 ground-truth claim? │
                  │  2 unforgeable ev.?    │
                  │  3 domain-free?        │
                  │  4 mechanical enum?    │
                  └───────────┬───────────┘
            all four pass     │     any of 1/2/4 fails
        (deterministic,       │     (judgment, provider,
         forgery-proof)       │      non-determinism)
                  │           │           │
                  ▼           │           ▼
        ┌──────────────────┐  │  ┌────────────────────────┐
        │ KERNEL VERDICT   │  │  │ DRIVER JUDGE           │
        │ in-door: register│  │  │ out-house: dos.judges  │
        │ on the verdict   │  │  │ seam, four disciplines │
        │ contract (86)    │  │  │ (87)                   │
        │ → dos <verb>,    │  │  │ → advisory, abstains,  │
        │   queue row, MCP │  │  │   never acts           │
        └──────────────────┘  │  └────────────────────────┘
                              │
              gate 3 fails only (domain-specific
              but still deterministic & forgery-proof)
                              ▼
                  ┌────────────────────────┐
                  │ DRIVER ORACLE          │
                  │ a host's seam, not a   │
                  │ kernel verb (drivers/) │
                  └────────────────────────┘
```

The four-gate test was introduced in `85` as a *guard* ("may this register as a kernel
verb?"). Its real job is bigger: it is the **classifier for the whole population** —
not a yes/no on kernel membership but a three-way sort into *kernel verdict* / *driver
oracle* / *driver judge*. The same predicate that admits `scope` to the kernel is what
exiles `llm_judge` to `drivers/`. One rule, read two ways, is what keeps the two
growth-axes from blurring into each other.

---

## 2. The two axes are mirror images — and the symmetry is the design, not a coincidence

Set the two extension axes side by side and the mirroring is exact. This is the table
that should have been in `86` and `87` both, and could be in neither because it needs
both to exist:

| | **Verdict axis** (in-door, `86`) | **Judge axis** (out-house, `87`) |
|---|---|---|
| **Lives in** | the kernel (`src/dos/<verb>.py`) | a driver (`src/dos/drivers/<judge>.py`) |
| **Determinism** | pure `classify` — no I/O, no clock, no provider | non-deterministic — a model / debate / heuristic |
| **Forgery-proof** | **yes** — reads artifacts (git, footprint) | **no** — a model verifying a model |
| **Open set, closed shape** | open verbs, closed `Verdict[V]` shape per verb | open judges, closed `JudgeVerdict` (3-valued) per judge |
| **The fallback** | the `none`/ABSTAIN provenance rung — answer from less | `AbstainJudge` — the unshadowable always-abstain baseline |
| **Fail-safe direction** | a verdict that can't tell answers **from a weaker rung** (`verify`: `registry`→`grep`→`none`; `liveness`: journal→commit→heartbeat; `scope`: → the conservative `WRONG_TARGET` on an undeclared lane) | a judge that can't tell **abstains** (`run_judge` fails to ABSTAIN, never AGREE) |
| **The discipline** | four-**gate** test (admission to the kernel) | four-**discipline** rule (det-first / advisory / fail-abstain / abstain-first) |
| **Registered via** | `dos.verdicts.register` (specced, §5) | `dos.judges` entry-point group (shipped) |
| **Scored by** | trajectory `verdict_*` columns (shipped) | `dos judge-eval` false-clear rate (shipped) |

Read the rows as pairs and the same five invariants appear on both sides, *pointed in
opposite directions because the two axes carry opposite trust*:

1. **Both are "open set, closed shape."** This is the `HACKING.md`
   closed-enum-as-data pattern at the *adjudicator* level. You may add any number of
   verdicts or judges (open); each must return exactly the kernel's typed answer
   (closed) — `Verdict[V]` for a verdict, the three-valued `JudgeVerdict` for a judge.
   Neither axis lets a plugin invent a new *kind of answer*, only a new *source* of the
   existing answer. That is what makes the population safe to grow: the consumers (CLI,
   queue, MCP, the bench) never learn a plugin's name, only its conformance.

2. **Both have an unshadowable trusted floor.** A verdict's floor is its *weakest
   rung* — when the registry and grep both abstain, `verify` answers `source="none"`
   from git history alone; when the journal and commit signals are absent, `liveness`
   answers from the caller-supplied heartbeat alone ([`liveness.py:62-64`](../src/dos/liveness.py));
   when a lane declares no tree, `scope` falls to the conservative `WRONG_TARGET`
   rather than certifying containment it can't prove ([`scope.py`](../src/dos/scope.py)).
   None of them *fails*; each answers **from less**. A judge's floor is `AbstainJudge`,
   which a `dos.judges` plugin can never displace ([`judges.py:61`](../src/dos/judges.py)).
   Both floors share one property: **a plugin can add capability above the floor but can
   never remove the floor.** A bad verdict can't make `verify` crash; a bad judge can't
   make the system stop abstaining. (This is the `text`-renderer rule — a trusted
   fallback no plugin can knock out — applied to adjudicators.)

3. **Both fail toward the safe pole — but the poles are mirror images.** A verdict
   degrades its *confidence* (a weaker rung, or the conservative verdict) when evidence
   runs out; a judge degrades its *commitment* (abstain) when judgment runs out. Note
   the deliberate inversion from the **predicate** rule, which fails to **refuse**
   (deny — safe for admission): a safety predicate that can't answer denies the lease;
   an advisory judge that can't answer punts to a human; a verdict that can't answer
   drops a rung. Three syscalls, three "safe directions," each chosen so the dangerous
   cell — *approving a falsehood* — is structurally unreachable by accident. The verdict
   axis can't approve a falsehood because it reads artifacts, not claims; the judge axis
   can't because `run_judge` converts every failure to ABSTAIN, never AGREE.

4. **Both are scored, not asserted.** `86`'s verdict columns and `87`'s `judge-eval`
   are *the same instinct* — a seam is only research-interesting if it yields a number.
   §3 is the punchline: on this branch they became *literally the same instrument*.

The symmetry is not decoration. It is the evidence that the four-gate router is real:
if the two axes were ad-hoc, their invariants wouldn't line up. They line up because
each axis is the same population-growth rule projected onto opposite sides of the trust
line the router draws.

---

## 3. One instrument scores both axes against one labeled run

Here is what the branch made true that neither parent note could claim: **the verdict
axis and the judge axis are now measured by the same artifact** — the FleetHorizon
trajectory, against a single ground-truth-labeled run.

The chain, now built end to end:

- `TrajectoryStep` ([`trajectory.py`](../benchmark/fleet_horizon/trajectory.py)) keeps
  three columns rigidly apart: claim-side **features**, the git-checkable **label**
  (`really_committed`), and the kernel's **verdict + provenance**. The branch added two
  verdict columns — `verdict_in_scope` (the `scope` axis) and `verdict_advancing` (the
  `liveness` axis) — on the verdict side of the line, deliberately absent from
  `to_features()` so they can't leak into the distillation X ([`trajectory.py:83-90`](../benchmark/fleet_horizon/trajectory.py)).
- Those two columns are exactly the [`86 §3`](86_the-typed-verdict-surface.md) fix: the
  failure modes the fleet *simulated* (scope reach via `Phase.touches`; thrash via
  `Worker.will_thrash()`) but the trajectory previously **banked silently**. Now every
  registered verdict's adjudication of the *same simulated run* is on the record.

So the verdict axis (`86`) is scored by **how much silent corruption the trajectory
stops banking** — each new `verdict_*` column widens the believed-vs-adjudicated delta
toward the full failure space, and gives the distillation experiment a *separate*
irreducibility question per column (predict scope-violation? predict spin?), not just
`really_committed`. And the judge axis (`87`) is scored by **false-clear rate on the
residue** — `dos judge-eval`'s rung-occupancy table measures how much human-review load
a judge removes and the integrity cost of removing it.

The two scores answer two halves of one question, against one run:

> **Verdict axis:** *how much of the failure space can a forgery-proof, deterministic
> rung adjudicate at all?* (coverage of the cheap floor)
>
> **Judge axis:** *of the residue the floor can't reach, how safely does a model rung
> rule on it?* (false-clear rate on the expensive top)

This is the scalable-oversight decomposition `87 §6` claims, now with the instrument
wired: a **floor you cannot fool** (the verdict axis, grounded in git) whose *coverage*
is measured by the trajectory, **plus a measured judge above it** whose *marginal risk*
is measured by `judge-eval`. The reason that decomposition is hard to get from a single
end-to-end verifier is precisely that it needs two instruments on two axes — and the
branch built both, reading the same ground truth.

A concrete way to see the join: a step's `verdict_in_scope == "SCOPE_CREEP"` is the
deterministic floor *catching* a footprint violation (verdict axis, coverage↑). A step
the floor *can't* settle — a claim of correctness, of taste, of "this is the right
abstraction" — is routed to a judge, whose ruling shows up in `judge-eval`'s confusion
grid (judge axis, risk measured). The *same* trajectory run produces the inputs to
both. The population is one; the instrument reads it as one.

---

## 4. What the synthesis buys a reader (and a researcher)

Naming the population, not just its two halves, changes what you do next:

1. **"Where does my adjudicator go?" has a mechanical answer.** Don't argue about
   whether your check is "kernel-worthy." Run it through the four-gate router (§1).
   Deterministic + forgery-proof + domain-free → register it as a verdict; you get a
   CLI verb, a queue row, an MCP tool, and a trajectory column **for free**. Carries
   judgment or a provider → it's a judge; you get `judge-eval` and the four disciplines.
   Deterministic but domain-specific → it's a driver oracle. The decision is the
   router's, not a taste call.

2. **The two extension docs stop competing.** A reader hitting `86` and `87` cold could
   reasonably ask "is the extension story the verdict registry or the judge seam?" The
   answer is *both, and they're mirror images* — `86` is how the trusted population
   grows, `87` is how the untrusted one does, and §2's table is the single mental model
   that holds them together. The OS analogy lands harder here than in either parent: the
   kernel has *device drivers* (verdicts that join it through a vetted ABI) **and**
   *userland* (judges that run outside it under containment). Same kernel, two
   populations, one boundary — the four-gate test is the system-call check that decides
   which side of the boundary your code runs on.

3. **The instrument is one surface, so the research question is one question.** A
   frontier-lab oversight researcher does not have to choose between "measure the
   verifier" and "measure the judge." Bring a labeled FleetHorizon-style run and you get
   the *coverage of the deterministic floor* (verdict columns) and the *false-clear rate
   of the judge above it* (`judge-eval`) from the same harness. The headline isn't "DOS
   is good"; it's the **frontier curve**: as you push more of the failure space onto the
   forgery-proof floor (add verdicts), how much residue is left for the judge, and at
   what false-clear cost? That curve is the scalable-oversight result, and DOS is the
   first substrate that instruments both of its axes against one ground truth.

---

## 5. The honest state — what's built, what's specced, what's unrun

This note synthesizes built code, but the synthesis is ahead of the build in two places,
stated plainly because a reader will find them:

- **The verdict *registry* is specced, not shipped.** `verdict.py` is the *contract* and
  `conforms()` is the gate-4 check ([`86 §2`](86_the-typed-verdict-surface.md)); the
  `dos.verdicts.register` entry-point group that would turn a conforming verdict into a
  CLI verb / queue row / MCP tool **without editing the kernel** is the deliberate
  "generalize last" step (`86 §4` build order, step 4). Today `scope` and `liveness` are
  still hand-wired in `cli.py` like every other verb. So the "in-door is open" claim
  (§1) is *true of the contract* and *not yet true of the plumbing* — the door exists,
  the automatic doorman doesn't. Adding it is the next build, justified now that two real
  instances (`liveness`, `scope`) prove the shape.

- **The router is a discipline, not yet a function.** The four-gate test (§1) is
  enforced today by *review against a documented checklist* (`verdict.py`'s docstring
  spells the four gates; `conforms()` mechanically checks only gate 4 — the others are
  design properties a runtime check can't see). The "mechanical answer" of §4.1 is
  mechanical for gate 4 and *human* for gates 1–3. That is honest and probably correct
  — "does this read unforgeable evidence" is a judgment about the *design*, not a
  property of a *value* — but it means the router is a rule a maintainer applies, not an
  assertion a CI job fails on. (The grep-checkable litmus *"kernel imports no judge
  implementation"* is the one piece of the router that *is* enforced by a test —
  `tests/test_judges.py` — because import structure is mechanically visible where design
  intent is not.)

- **The frontier curve of §4.3 is an instrument without a study.** Both axes are
  measured; the *joint* sweep — push N verdicts onto the floor, watch the judge's
  residue and false-clear rate move — is unrun. `86 §3`'s multi-label distillation and
  `87 §5`'s "ORACLE→JUDGE handoff is a single `UNCLASSIFIED` enum, not a studied
  frontier" are the same unrun study from the two axes. The branch built the apparatus;
  nobody has turned the crank. That is the invitation, not a result.

---

## 6. What this note claims

- **Does claim:** the driver-layer reframe has *two* extension axes, not one — a trusted
  verdict axis (`86`) and an untrusted judge axis (`87`) — that are mirror images of one
  population-growth rule (§2); the [`85 §2`](85_extending-the-verifiable-surface.md)
  four-gate test is the *router* that sorts a proposed adjudicator onto its axis (§1);
  and on this branch a single instrument (the FleetHorizon trajectory + `judge-eval`)
  scores both axes against one ground-truth-labeled run, which is the scalable-oversight
  decomposition made measurable (§3).
- **Does not claim:** that the verdict registry or the mechanical router are shipped
  (§5 — contract yes, plumbing no); that the joint frontier study has been run (§5 — the
  apparatus exists, the crank is unturned); or that the four-gate router mechanically
  decides all three gates (only gate 4; 1–3 stay review, §5).
- **The one-liner:** *the adjudicators are one population growing along two mirror-image
  axes — verdicts that earn their way into the kernel, judges that are kept structurally
  out of it — and the four-gate test is the single rule that routes a new one to its
  axis while one instrument scores both against the same ground truth.*

---

## See also

- [`86_the-typed-verdict-surface.md`](86_the-typed-verdict-surface.md) — the verdict
  axis (in-door): the `classify(Evidence, Policy) -> Verdict[V]` ABI, the registry spec,
  the four-gate guard, and the trajectory-column bench proof this note reads as one half
  of the population.
- [`87_the-adjudicator-trust-ladder.md`](87_the-adjudicator-trust-ladder.md) — the judge
  axis (out-house): the ORACLE→JUDGE→HUMAN ladder, the four disciplines, and the
  `judge-eval` instrument this note reads as the other half.
- [`85_extending-the-verifiable-surface.md`](85_extending-the-verifiable-surface.md) §2 —
  the four-gate test, introduced as a kernel-admission guard, promoted here to the
  population router.
- [`79_primitives-not-features.md`](79_primitives-not-features.md),
  [`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md)
  — the small-primitives / expand-by-composition stance the two-axis growth honors.
- `src/dos/verdict.py` (the contract + `conforms`), `src/dos/scope.py` (the first new
  verdict on it), `src/dos/judges.py` (the seam), `src/dos/judge_eval.py` (the judge
  instrument), `benchmark/fleet_horizon/trajectory.py` (the verdict instrument) —
  everything §1–§3 synthesizes, all on this branch.
- `tests/test_verdict_contract.py`, `tests/test_scope.py`, `tests/test_judges.py`,
  `tests/test_judge_eval.py` — the 47 green tests that pin the population's two axes.
- memory `project-dos-judge-seam`, `project-dos-review-problem-and-git-reliance` — the
  judge-rung framing and the typed-verdict-with-provenance resolution this note's
  population sits inside.

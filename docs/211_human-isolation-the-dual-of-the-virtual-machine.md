# Human isolation — the dual of the virtual machine

> **The arbiter never believed what a glob *meant*, so it will referee a fleet's claim
> on a human's attention exactly as it referees a claim on a file — but only up to the
> skin: it can refuse the colliding write and surface the addressed fault, it can never
> reach inside and isolate the mind it is faulting to.**

This is a design note, not a shipped mechanism. It takes one inversion seriously and
follows it until it breaks. A virtual machine (VM) isolates the **agent**: it cages an
untrusted guest so the guest cannot corrupt the host's memory. DOS does the opposite —
it lets the agents run free and *distrusts what they report*. So the dual question is:
if you are not caging the agent, **what are you protecting, and from what?**

The answer this note argues for: in a fleet, the silicon is cheap and forkable; the
scarce, non-forkable, corruptible resource is the **operator** — their attention, their
map of what is true, their authority to decide. "Isolate the human" means: put a
boundary around *that*, the way a VM puts a boundary around RAM. The brainstorm had five
readings of what that boundary is; an adversarial pass (`wf_955b703d-1c1`, 2026-06-07,
every claim re-grounded against `src/dos/` at HEAD) kept three readings, demoted two to
metaphor, and surfaced three the brainstorm missed. This note records the survivors and,
just as importantly, the **exact lines where the analogy stops being mechanism and
becomes a vibe** — because the project's cardinal sin is overclaiming, and this frame is
unusually easy to overclaim.

A word on terms used throughout. **PDP / PEP** — a *Policy Decision Point* decides a
verdict; a *Policy Enforcement Point* acts on it. The DOS kernel is a PDP with no PEP
([`99`](99_runtime-validation-and-the-actuation-boundary.md)): it **records** a verdict
and **proposes** a command, it never delivers a signal. **Wall 3** — the deepest of the
four walls ([`204`](204_the-four-walls-where-verification-runs-out.md)): the kernel can
witness *presence* ("did this happen / does a SHA exist?") but not *correctness* ("is it
right?"), because correctness can only be judged from bytes the agent authored, which
the kernel refuses to believe. **The HUMAN rung** — the trust ladder is ORACLE → JUDGE →
HUMAN (`judges.py`): a deterministic verdict first, an advisory adjudicator on the
residue it abstained on, a human only at the irreducible seed.

---

## §0. The one true claim, and the three honest cuts

The whole frame rests on a single verified fact:

> **The arbiter is domain-blind about what a glob *means*.** Its docstring calls it "a
> lock manager whose granularity is a glob-set" (`arbiter.py:25`) and says outright:
> "point it at a benchmark repo's lanes, or a calendar's, or a k8s namespace's, and it
> arbitrates those unchanged" (`arbiter.py:16`). A region is literally a `list[str]` of
> globs (`arbiter.py:68/74`), and the default admission path is pure — no I/O
> (`arbiter.py:218-220`). The globs are uninterpreted tokens to which a disjointness
> algebra is applied.

So one legitimate interpretation of those tokens is **not a file-set but a concept-set,
or a decision's identity**. Re-aim `region = ["auth/session/*"]` to mean "the slice of
comprehension a human currently holds," or `region = "decision:abc123"` to mean "the
decision one operator is resolving," and the arbiter's core guarantee — *never admit two
leases over a non-disjoint region* — becomes *never let two operators collide on the
same concept or decision*. **Zero new kernel code.** This is the same inward-aim move
[`103`](103_memory-is-an-unverified-agent.md) already blessed for the memory store,
pointed now at the human.

That is the load-bearing truth. Everything else is bounded by three cuts the adversarial
pass forced, and by Wall 3.

- **Cut 1 — "N concepts per head is already shipped" is FALSE.** The tempting claim is
  that `class_budgets={human:N}` + the shipped `CLASS_BUDGET_EXHAUSTED` refuse already
  caps "how many concepts in one head at once." It does not. That gate fires *only* on
  the bare auto-pick walk (inside `if auto_pick_order is not None: if bare:`,
  `arbiter.py:709-710`; `_budget_exhausted` at `arbiter.py:678`). A directly **named**
  region — the only honest model of a working set a person is deliberately holding —
  takes the keyword/cluster/exclusive admit path (`arbiter.py:510-586`), which never
  calls the budget gate. A human naming a sixth concept gets `acquire`, not the cap.
  Capping named concepts needs a **small kernel edit** (extend the budget count to the
  named path), not zero code.

- **Cut 2 — the decision-lease is an *advisory* mutex, not authenticated isolation.**
  The decisions queue is a read-only projection today (`decisions.py` — it "stores
  nothing of its own"), so serializing *which operator owns a decision* is a genuine
  gap, and closing it is a thin re-aim (§R3). But the lease owner is a free-form,
  **unauthenticated** string (`lane_lease.py:285` records it verbatim), and `--force`
  converts any same-region refuse into an `acquire` for any caller
  (`arbiter.py:481-494`). So it closes the *accidental* double-decision between two
  cooperating operators who both use the queue. It does **not** stop a `--force`, a
  hand-run `git push`, or a forged owner string.

- **Cut 3 — a "resumable decision-context" inherits resume's name, not its mechanism.**
  `resume.resume_plan`'s only non-trivial verdicts (DIVERGED, COMPLETE,
  RESUMABLE-with-a-SHA) are all computed against git fossils — `ancestry.contains`
  (`resume.py:341`), `lane_advanced_past_resume` (`resume.py:350`),
  `_verified_on_safe_rung` (`resume.py:381`). A human's half-loaded belief-state has
  **no fossil**. So a re-aimed "resume" can only ever return a degenerate RESUMABLE
  carrying re-surfaced prose, and can **never** emit DIVERGED. It is advisory
  re-presentation, not a checkpoint.

And the ceiling over all of it, **Wall 3**: every isolation claim here is bounded to
*false claims of presence*. The kernel can refuse an unbacked "it shipped" from updating
the operator's map; it cannot relieve the operator of judging whether the in-region work
is *correct*. That judgment **is** the irreducible HUMAN rung. Any sentence implying a
lease lets a human "not have to understand" their region, or that the kernel "isolates
the human from bad work," is the overclaim to cut.

---

## §1. The duality table

`exists` = shipped kernel mechanism, used as-is. `reaim` = a legitimate re-pointing of a
shipped pure mechanism (zero / near-zero new kernel code). `new-small` = a real
buildable gap, additive and thin (rides the existing WAL/arbiter, no new subsystem).
`metaphor` = a design north-star the kernel structurally **cannot** enforce.

| Virtual machine | Human-isolation dual | Kernel surface | Status |
|---|---|---|---|
| Address space split into pages, each mapped to one process | Comprehension/decision space split into regions, each held by one operator | `arbiter.arbitrate(request, live_leases, config)` over `region=list[str]` (`arbiter.py:68/74,146`); re-aim a glob to a concept-set or decision-id | reaim |
| MMU page-table entry records the backing frame; no frame → fault | Every operator-facing fact records the rung that backs it; an unbacked claim is demoted to narration | `oracle.is_shipped` `source=registry\|grep\|none`; `verify()`/`liveness()` answer from git ancestry + git/journal delta, never self-report | exists |
| The MMU itself — write-protection; a bad write faults | The syscall set as write-protection on the operator's belief-state; `refuse()` is the page-fault | `oracle`/`liveness`/`arbiter` all refuse a self-report from updating the typed map ([`182`](182_the-kernel-is-a-taxonomy-of-refusal.md), all syscalls are kinds of "no") | exists |
| Disjointness: no two overlapping regions mapped at once — exact, checkable | No two overlapping concept/decision-regions admitted to two operators | `lane_overlap.overlap_verdict` + `overlap_policy.admissible_under_floor` (refuse-MORE only, under a deterministic prefix floor). **Exact for files; for a self-tagged concept-glob the floor has no checkable byte-fact** ([`138`](138_what-is-truth-the-throughline.md)) | reaim |
| No fungible substitution of a named region | A second operator wanting THIS decision is refused, never handed a different one | same-region-held refuse (`arbiter.py:498-507`); exclusive/keyword kind never auto-picks (the UNKNOWN_LANE / false-busy discipline) — unlike lane auto-pick (`arbiter.py:329`) | reaim |
| Mutual isolation of two guests | Two operators can't both own the same queue item (`DECISION_HELD`) | NEW thin: `decision_id` = hash of the existing `decisions._dedup` tuple; `dos decisions take` writes through the existing `lane_lease` WAL. Queue is read-only today — a real gap | new-small |
| Page fault traps to the owning handler | An unresolved claim surfaces as a refusal addressed to the region's holder | `DecisionKind.ARBITER_REFUSE` row (`decisions.py:80`), `resolver_kind=HUMAN`. The kernel **emits** the row; it cannot **deliver** it — no interrupt (PDP-no-PEP) | reaim |
| Privilege rings — cheapest handler first; page in only on a fault | ORACLE → JUDGE → HUMAN: the operator is reached only on the residue both cheaper rungs abstained on | `judges.py` + `decisions._resolver_for` (`decisions.py:167-195`) stamps HUMAN only for the irreducible residue | exists |
| Bounded resident set / CPU-share cap; (N+1)th refused with wait-don't-retry | At most N concepts/decisions in one head; (K+1)th refused "your share is full" | `class_budgets` + `CLASS_BUDGET_EXHAUSTED` (`arbiter.py:160,356-375`). **Fires only on the bare auto-pick path; a NAMED region is never budget-gated** — see Cut 1 | metaphor |
| An admission filter that can only WITHHOLD, never inject (safe direction) | The reach-the-human filter can only suppress an item, never manufacture one — over-admitting *is* manufactured consent | the conjunctive-only admission rule (`run_predicates`) + `overlap_policy.admissible_under_floor`, re-aimed | reaim |
| The page-fault RATE — a measurable property of the boundary | Human-isolation leak rate / operator backlog | NEW small: a pure read-only fold over `collect_decisions(resolver="HUMAN")`. **Honest only over DOS-mediated bytes** (§3) | new-small |
| Durable lock table + lease expiry; a crashed holder is reclaimed | A held decision survives one `dos` run; an abandoned hold is reclaimed | `lane_journal` WAL + `OP_HEARTBEAT`/`OP_SCAVENGE` + TTL. Owner is a free-form **unauthenticated** string; `--force` bypasses (Cut 2) | new-small |
| Checkpoint / restore a guest; DIVERGED if the world moved | Suspend a half-finished decision-context, swap the operator back in | NEW re-aim of `resume.resume_plan` + `intent_ledger` SUSPEND, re-keyed by `decision_id`. **Inherits the name, not the mechanism** — no fossil, so never DIVERGED (Cut 3) | metaphor |
| Kernel-page write protection — the most-privileged region, gated hardest | Output that would rewrite the operator's own map-of-truth is gated hardest | `SelfModifyPredicate` (`arbiter.py:523`) re-aimed — but no mechanism distinguishes a leaf-concept output from a map-rewriting one; pure analogy | metaphor |
| A HUMAN is the guest/holder that can hold a region and fault | A human holds a lease / is paged in as the guest | DOS has **no** human-identity lease (holders are run-ids, `run_id.py`; owner unauthenticated). Human-as-holder is a NEW host convention | new-small |
| The hypervisor EXECUTES, preempts, and constrains the guest | The kernel "runs the human as a process" / "isolates the operator from bad work" | **UNBUILDABLE**: PDP-no-PEP — cannot interrupt, serialize cognition, or force a switch. Wall 3 — isolates from false *presence* only | metaphor |

---

## §R1. Concept-lease — partitioning comprehension the way the arbiter partitions the workspace

*Verdict: design-north-star (the headline is metaphor; a narrow part is a real re-aim).*

A page is mapped into one address space; the dual is a **comprehension lease** — one
operator holds an exclusive region of *concept* space. Because the arbiter is glob-blind
(§0), this is an ordinary lease whose `tree` is a concept-glob-set, and the disjointness
guarantee becomes "two distinct concepts cannot be paged into the same head without an
explicit overlap decision." That much is a real re-aim.

**Where it collapses.** Two points. First, **the budget**: the vivid claim "Miller's
7±2 working-memory bound expressed as a kernel verdict" rests on `class_budgets`, but per
Cut 1 the cap fires only on the auto-pick path — a human deliberately *naming* the
concepts they hold is never budget-gated, so there is no shipped code that refuses
alice's sixth named concept. Second, **the fault**: "an out-of-region output *traps* to
the owning human" is mechanism only up to *emitting* an addressed `ARBITER_REFUSE` row;
the verb "trap," with its OS sense of preemption, is unbuildable — PDP-no-PEP means the
kernel cannot interrupt a person or guarantee they read the row. And deepest: a
file-glob is a checkable byte-fact; a **concept-glob is an assertion about what an output
is "about."** If the agent self-tags its own concept-region, the lease admits on a
self-report — the exact thing the kernel exists to distrust ([`138`](138_what-is-truth-the-throughline.md)). The
disjointness floor, the one thing that keeps a swappable scorer honest, has nothing exact
to stand on ("is `token-refresh` inside `session`?" has no deterministic prefix answer).

**What survives.** Re-aiming `region=concept-set` is legitimate; structural prevention of
*unassigned-concept intrusion* (output about a region you never took) is a real
presence-level property, the same class as Wall-1's "overwrites-prevented structurally."
The honest artifact is *not* the one the brainstorm proposed (a budget test, which would
fail at HEAD) but a disjointness test: two prefix-colliding concept regions refuse,
disjoint ones acquire. The win is a smaller working set surfaced as addressed rows — not
a capped or removed judgment.

## §R2. The belief-firewall — the kernel as an MMU around the operator's belief-state

*Verdict: design-north-star (the per-verdict floor is real; the "firewall" headline is not).*

The sharpest framing of the whole note: an MMU does not protect RAM cells (fungible); it
protects *one address space's view of memory*. The dual — the scarce corruptible thing
is the operator's **belief-state**, their map of what shipped, what's held, what's
progressing. Every syscall is already a write-protection rule on that map:
`oracle.is_shipped` refuses an unbacked "done" from writing SHIPPED; `liveness.classify`
refuses an unbacked "progressing"; `arbitrate` refuses a self-asserted "I hold the lane."
The verdict even tags *which rung answered* (`source`), exactly as a page-table entry
records the backing frame. There is a real precedent shipped in one place:
`decisions._clean_token` (`decisions.py:213-228`) *demotes* agent prose — shows it, but
strips its authority to become a closed token. That is the firewall in microcosm:
narration is displayed, never believed.

**Where it collapses.** At the word **"channel."** An MMU works because there is exactly
*one* mandatory translation path and hardware faults anything off it. DOS has no
mandatory path to a human: `cli.py` alone has hundreds of independent print sites, plus
MCP results, plus — fatally — channels entirely outside the syscall ABI (an agent DMs a
human, writes a PR body, talks in a meeting). The claim "the decisions queue *is* the
chokepoint, so the firewall already ships" is false: `collect_decisions` covers only four
refusal sources and never sees verify/liveness/doctor/plan/MCP output. There is also no
uniform `Verdict.provenance` field — provenance is carried differently per verdict
(`ShipVerdict.source`, liveness `evidence`, scope spill-lists), so "classify a message by
reading its provenance field" tests a field that does not uniformly exist.

**What survives.** A narrow, real discipline: per-verdict provenance *does* exist and is
testable (`source="none"` for an unbacked SHIPPED claim is a genuine demotion). The
honest hardening is (1) unify provenance into one explicit field on the `TypedVerdict`
contract, then (2) add a grep-checkable litmus (like "kernel imports no host") that no
operator-facing renderer emits a fact-claim without a populated backing-rung field — over
DOS-mediated output only. The "leak rate" (§3) is the meter for that, scoped honestly.

## §R3. Decision-lease — isolating operators from each other

*Verdict: **buildable mechanism** (the one real new feature in this note).*

This is the reading with a genuine, buildable gap. The decisions queue answers "what
needs a human" but not "which human is on it." Two operators both open `dos decisions`,
both see the top row, both act — one runs `arbitrate --force`, the other `/replan` — and
the substrate is written twice on conflicting intents. This is
[`116`](116_the-durable-commons-and-the-constrained-a2a-problem.md)'s "the blackboard is the
disease," with the unreliable readers/writers being **humans**. The fix is the same:
human-to-**substrate** adjudication, not human-to-human Slack coordination.

The mechanism is `arbitrate` pointed at a different region algebra. The decisions module
already computes a dedup identity tuple `(kind, lane, reason_token, reason_text)`
(`decisions.py:602`) — hash it to a stable `decision_id` and *that is the region*. `dos
decisions take <#>` writes an acquire through the existing `lane_lease` path
(`cli.py:2531`) as a **`keyword`-kind** request whose `tree` is `["decision:<id>"]`; the
keyword path (`arbiter.py:570-586`) runs the admission conjunction and acquires when the
tree is disjoint from every live lease. A second operator's `take` reconstructs
`live_leases` from the WAL and gets the existing same-region-held refuse
(`arbiter.py:498-507`), surfaced as a new typed `DECISION_HELD` reason. **(Verified
against HEAD by the §3 spike: take-of-held → `refuse "already held"`; disjoint take →
`acquire`, `auto_picked=False`.)** **It must not
auto-pick** — a decision is a named concern, not a fungible work-slot; substituting a
different decision is the UNKNOWN_LANE disease. Abandoned holds are reclaimed for free by
the existing TTL + `OP_HEARTBEAT`/`OP_SCAVENGE` machinery — which is why riding the WAL,
not a new store, is load-bearing.

New surface is small and additive: one `DECISION_HELD` entry in `BASE_REASONS`, one
`decision_id` hash, one CLI branch. **No edit to the pure arbiter.**

**The honest guarantee (Cut 2).** This serializes *who decides*; it cannot serialize
*whether the decision is right* (Wall 3) and it is advisory (PDP-no-PEP). The owner is a
free-form unauthenticated string and `--force` bypasses the refuse, so it closes the
*accidental* double-decision between cooperating operators who both use the queue — never
a determined bypass, a forged owner, or the underlying git/shell act. Do not write "at
most one operator owns this decision"; write "at most one self-asserted owner *via the
queue*."

## §R4. Authority-rationing — operator decision-share as a scheduled resource

*Verdict: measurable-now (a read-only metric survives; the "ration" is R3 wearing a count).*

A VM scheduler caps a guest's CPU share so a fork-bomb can't starve the host. The dual:
a fleet emitting endless plausible "please approve" surfaces is a fork-bomb against
operator attention, and the failure is **manufactured consent** — when items arrive
faster than a human can adjudicate, "approve" collapses to a reflex.

The seductive claim is "the human is just another budgeted class, byte-for-byte the
[`97`](97_concurrency-class-model-plan.md) pattern, no new subsystem." **This is the
weakest claim in the note, and it is verified false.** `arbiter.class_budgets` counts
**live leases** — held, releasable, WAL-backed objects with a spawn/reap lifecycle
(`arbiter.py:362-364`). The decisions queue holds **nothing** (read-only, recomputed each
call). There is no holder-set to count and nothing for "wait for a slot to free" to wait
on. The moment you add the holder-set + release that would make the budget real, **you
have built R3's decision-store** — so R4 is not "no new subsystem," it is R3 wearing a
count.

**What survives** is a read-only instrument, not a ration: `decisions.collect_decisions
(resolver="HUMAN")` already routes only the oracle+judge-abstained residue to the human
(the trust ladder made visible). A pure fold `operator_load(rows) -> {open_human_count,
oldest_age_s}` over that output is buildable today with zero new state — it makes
operator backlog *measurable*. The conceptual contribution that survives is the framing:
*the operator is a finite serial resource, and surfacing items faster than a human can
adjudicate degrades the verdict to a constant* — which motivates **measuring** backlog,
not metering authority. Cut "ration the human's authority"; the honest verb is "measure
operator backlog."

## §R5. The hypervisor inversion — the human as a paged-in guest

*Verdict: relabel-of-existing (a real lifecycle ordering; the one new object is hollow).*

The sharpest "opposite": flip which side is the host. "Human-in-the-loop" silently casts
the human as the always-on host and agents as transient guests scheduled inside their
oversight. Invert it — the **fleet** is the host (cheap, forkable, holds the durable
state: git, the WAL, the intent ledger); the **human** is the scarce guest, paged in only
on a sound fault, run in a certified context, swapped back out. "Human-in-the-loop"
becomes "human-as-paged-guest."

Three of the four lifecycle phases are already real: the **page-in trigger** is the trust
ladder (reached only on the oracle-abstain → judge-abstain residue); the **protected
context** is R2's per-verdict floor (git-backed claims, not narration); the **scope** is
R1's concept-lease. R5 adds no fifth mechanism — its real content is the *ordering* of
R1–R4 into one swap-in/swap-out discipline (and the page-in must clear R1+R2+R4 first, or
it has merely rebuilt the R4 interrupt-storm).

**Where it collapses (Cut 3).** Its one nominally-new object — a suspendable
decision-context modeled on `resume.resume_plan` — is exactly where it is most novel and
most hollow. `resume_plan`'s entire power is re-adjudicating each step against git
ancestry; strip the fossil and it degenerates to "here is the prose you left, trust it."
A human belief-state *has* no fossil, so the re-aim inherits the name but not the
mechanism: only a degenerate RESUMABLE-carrying-prose, **never** DIVERGED (the tell: the
proposed test asserts RESUMABLE, never a DIVERGED case). It also quietly inverts the
kernel's trust posture: the fleet/agents are the *distrusted* narrators, not a "trusted
host" — git/WAL/ledger are trusted because they are **fossils**, not because the fleet
is. A careless author who writes "the trusted fleet runs the untrusted human" has the
arrows backwards.

**What survives:** a correct consolidation (the lifecycle ordering of existing
mechanisms) plus R3's small new lease, with one explicitly-labeled north-star
(decision-context suspend) that is advisory re-presentation, not a checkpoint.

---

## §R6–R8. Three readings the brainstorm missed

The completeness critic surfaced three angles materially different from R1–R5.

**§R6 — Copy-on-write: fork-on-write, not eager exclusivity.** R1 and R3 both take an
*eager exclusive* lease, which collides with the common case: many operators
*co-observing* the same region ("we're all watching the auth subsystem"). The VM dual of
COW is **shared read-only, fork only on write-intent**: the lease is taken *lazily*, at
the moment one operator wants to *act*, not when they look. `overlap_policy.
admissible_under_floor` (refuse-MORE-never-admit) is exactly the compatibility-function
substrate for this. R6 is the strongest missing angle because it dissolves R1/R3's worst
objection (forcing exclusivity where humans naturally co-watch) and it is a re-aim, not
metaphor — read is free and concurrent; only the write-intent contends.

**§R7 — Priority / rank: the honest answer to the interrupt storm.** R4 frets about a
budget deferring a high-urgency item behind stale ones, but the real OS dual of "a
high-priority interrupt preempts a low-priority handler" is not a *budget*, it is a
*rank*. `_bare_pass` already takes a `rank_key` that orders the auto-pick ladder
(`arbiter.py:659-664`), and `decisions._KIND_RANK` already ranks a LIVENESS halt (a run
burning budget *now*) above a refusal. The interrupt-storm answer is: don't defer by
count, **order by rank** — a burning-budget fault jumps the queue ahead of K stale
WEDGEs. Buildable now as a pure fold, no new state.

**§R8 — Read / write / execute bits: a region is not one "hold."** A page has three
independent protection bits; every reading above collapses the human's relationship to a
region into a single exclusive hold. Separate them and the design gets sharp: being
**surfaced** a decision (R2/R4 reach-filter) is the *read* bit; being allowed to **take**
it (R3 lease) is the *write* bit; actually **running** the proposed command (`--force`,
`git push`) is the *execute* bit. This exposes the most important unguarded hole in the
note: **`--force` is an unguarded execute-bit escalation** — it grants execute without
ever checking read or write. Naming the three bits lets the doc say precisely which bit
each mechanism governs.

---

## §2. The leak rate — the one number this frame produces

The value-capture lesson on file is "change the *consumer*, not the threshold — the
human *is* the consumer." The metric that operationalizes that, without re-tuning any
detector, is the **human-isolation leak rate**: at the one boundary where the fleet
writes to the operator's belief-state, how often is a completion claim *backed* vs.
*leaked*?

Every "I'm done / it shipped" claim that reaches a human is exactly one cell:

- **GIT_BACKED** — `oracle.is_shipped` returns `shipped=True` with `source ∈ {registry,
  grep, grep-subject}`. A SHA in ancestry backs it. Not a leak.
- **DEMOTED** — the claim was emitted but the firewall fired: `dos hook stop` returned
  `{ok:false}` because the oracle returned `source="none"`. The false-presence claim was
  stopped before it updated the operator's map. Not a leak — the firewall worked.
- **LEAKED** — a completion claim reached the operator *without passing the verifier at
  all* (raw chat, PR body, an un-backed verb stdout). No oracle verdict ever gated it.

`leak_rate = LEAKED / (GIT_BACKED + DEMOTED + LEAKED)`, always reported beside
`mediation_coverage = (GIT_BACKED + DEMOTED) / all-completion-claims-that-reached-a-human`.

**Measured on surface that already exists.** `dos hook stop` (`cmd_hook_stop`) *already*
extracts confident completion claims (`claim_extract`) and runs `oracle.is_shipped` per
claim, recording `{shipped, source}` and emitting `{ok:false}` on a false claim. A wired
Stop hook **is** the meter: each firing is one fleet→human stop-event; each `results` row
is one cell. Append one OP-record per firing to the lane-journal WAL and fold it. The
classifier `leak_eval.classify_reach(ReachEvidence) -> {GIT_BACKED, DEMOTED, LEAKED}` is
a pure function beside `intervention_eval`/`overlap_eval` — but call it a **counter**, not
an eval: the label *is* the predicate, so the confusion grid is degenerate by
construction. It is a regression guard ("no new channel ships an unbacked human-facing
completion claim") and a trend chart, not a precision/recall instrument.

**The caveats that keep it honest:**

- **Wall 3, and the asymmetry the critic caught:** a 0% leak rate means every claim is
  *presence*-backed, not *correct*. Worse — for the ~38% of goals that reach no sound
  witness, a completion claim can be GIT_BACKED (a SHA exists) and still be a lie about
  correctness, classified *not-a-leak*. **The meter reads cleanest on exactly the work
  where the human most needs protection.** Surface every GIT_BACKED claim as
  "presence-backed, NOT correctness-checked" so the operator keeps correctness vigilance.
- **Denominator honesty (PDP-no-PEP):** the rate is meaningful only over DOS-mediated
  channels. An agent that DMs a human bypasses the ABI; the kernel records and proposes,
  it never intercepts. `leak_rate=0%` over a 5%-mediated channel is near-meaningless —
  and `mediation_coverage`, the number a buyer most wants, is the one the kernel can
  *least* measure. **Never print `leak_rate` without `mediation_coverage` beside it.**
- **The hook must be wired** to see anything; early numbers reflect *integration*, not
  fleet honesty — which is also the honest adoption funnel (coverage up, leak down).

---

## §3. What to actually build (and the one spike that decides it)

Ranked by honesty-of-payoff:

1. **The decision-lease (§R3)** — the one real new feature. `dos decisions take/release
   <#>` + a `DECISION_HELD` reason + a `decision_id` hash, all riding existing arbiter +
   WAL + scavenge. Scope the claim to "accidental double-decision between cooperating
   operators."
2. **The operator-load metric (§R4) and the leak counter (§2)** — read-only folds over
   `collect_decisions(resolver="HUMAN")` and the Stop-hook journal. Zero new state. The
   measurable half of the whole frame.
3. **The named-path budget edit (Cut 1 / §R1)** — the small kernel edit to make "N
   concepts per head" real for *named* regions, gated by the existing `_budget_exhausted`.
4. **R6 (COW) and R7 (rank)** — both re-aims, both dissolve real objections to 1–3.

Everything else (page-the-human-in/out, checkpoint-the-belief-state, ration-authority,
the belief-firewall as a single chokepoint) is **design north-star** — keep it as the
why, quarantine it from any "buildable" sentence.

**The spike that settles real-vs-metaphor in ~30 lines, against HEAD, no I/O** —
`tests/test_decision_lease.py` exercising only the *unmodified* pure kernel:

1. `arbitrate(requested_lane="decision:abc", requested_kind="exclusive",
   requested_tree=["decision:abc"], live_leases=[{lane:"decision:abc",
   lane_kind:"exclusive", tree:["decision:abc"]}], config)` → assert `outcome=="refuse"`
   and "already held" in the reason. *Proves R3's core is a thin re-aim, zero kernel edit.*
2. Same call, different id, empty `live_leases` → `outcome=="acquire"`; and a non-cluster
   kind never auto-picks onto the held one. *Proves no-fungible-substitution.*
3. **The falsifier that kills R1's headline:** `class_budgets={"human:alice":5}`, five
   live exclusive leases held, then a sixth *disjoint named* region for alice → assert
   `outcome=="acquire"` (NOT `CLASS_BUDGET_EXHAUSTED`). *Demonstrates the shipped budget
   gate does not bind the named path.*

If 1–2 pass and 3 confirms the acquire: R3 is buildable-now, R1/R4 are reaim-small
(named-path wiring), and R2/R5's "page/firewall/checkpoint the human" are conclusively
metaphor — settled by code, not by argument.

**This spike was run (2026-06-07).** Result, against the unmodified arbiter: (1)
take-of-held `decision:abc` → `refuse "lane 'decision:abc' is already held by a live
loop"`; (2) disjoint `decision:xyz` → `acquire`, `auto_picked=False`; (3) sixth disjoint
*named* region for alice with `class_budgets={"human:alice":5}` → **`acquire`** (the
keyword path never calls the budget gate), NOT `CLASS_BUDGET_EXHAUSTED`. So R3's core is
real with zero kernel edit, and Cut 1 holds: the shipped budget does not cap named
concepts. The one refinement the spike forced into §R3: the decision-lease is a
`keyword`-kind request, not `exclusive` (which carries orchestration/global semantics).

---

## §4. The three objections still open

The adversarial pass left three unanswered, and the note is more honest for naming them.

1. **Does the kernel distrust the *operator* too?** The kernel's thesis is "the part that
   doesn't believe the *agents*," and [`103`](103_memory-is-an-unverified-agent.md) aims that same distrust inward at
   a human-authored memory store. But every reading here makes the kernel *protect* the
   human — and a human is a self-reporting agent. A concept-lease self-tagged by a human,
   a decision-lease owned by a self-asserted string: these *import the human as a trusted
   authority*, the exact move the kernel refuses elsewhere. So is "isolate the human"
   protecting a *trusted* human (a category error against the thesis), or *serializing an
   unreliable* human too (consistent — but then "isolation" is the wrong word; it is the
   same adjudication aimed at one more unreliable narrator)?

2. **The identity/auth gap is a soundness hole, not a future hardening.** Every
   human-as-holder claim rides an unauthenticated owner string. "At most one operator
   owns this decision" is *false today* and cannot be made true without an auth surface
   the kernel deliberately lacks (auth is host concern). The doc must scope every
   human-holder claim to "cooperating operators passing honest owner strings," uniformly
   — not bury it in R3.

3. **Wall 3's consequence for the value story.** If the kernel isolates only from false
   *presence* and ~38% of goals reach no sound witness, the leak meter is structurally
   blind on exactly that 38% — most confident precisely where it is least meaningful (§2).
   No caveat fully closes this asymmetry; it is a property of the witness, not a bug in
   the meter.

---

*Provenance: developed and adversarially pressured by workflow `wf_955b703d-1c1`
(2026-06-07); every kernel claim re-grounded against `src/dos/` at HEAD. The five
brainstorm readings, the three the critic added (R6–R8), the duality table, the leak-rate
metric, and the buildability triage are all recorded above with the mechanism-vs-metaphor
line marked per reading. This is a kernel design plan (how kernel modules behave), so it
lives in `dos/docs/`, not the strategy repo.*

# The durable commons — the constrained agent-to-agent problem the kernel already solves

> **The longer an agent runs undirected, the more its status must become a *fact
> others can read*, not a *message others must believe*. Free-form agent-to-agent
> (A2A) communication stays hard because it is trust-under-self-narration — the
> receiver cannot verify the sender, who is exactly the unreliable self-reporting
> worker the kernel was built around. DOS sidesteps that wall for the *coordinating*
> subset by never asking anyone to believe anyone: a fleet shares a durable commons
> of kernel-adjudicated effects (leases, verified steps, liveness verdicts, resume
> points), and each agent reads the others' *ground truth* instead of their *claims*.
> That is a narrow, real capability a message bus and a blackboard both lack — the
> blackboard especially, because believing its writers is the very failure mode the
> kernel exists to refuse. What stays unsolved, and what this note refuses to
> pretend otherwise about, is collaboration over *judgment* — the advice and
> rationale that never become an adjudicable artifact.**

This is a theory note in the family of [`79`](79_primitives-not-features.md) (the
syscalls are small), [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) (every
syscall is a *no*), and especially [`102`](102_when-to-trust-an-agent.md) (the
trust law: structure-not-content, commitments-not-reports, only-where-wrong-yes-is-cheap).
It carries no new mechanism *yet* — it ships a frame and one small, buildable
surface (§5) that composes readers DOS already has. Its purpose is to name, in
mechanism terms, a capability the kernel has by accident of its design and has
never been positioned as: **DOS is the durable shared-state plane for a fleet, and
the thing that makes that plane sound is the same distrust that makes every syscall
a refusal.** The positioning sibling — *why anyone outside this repo cares* — is the
strategy essay
[`dispatch-os-the-durable-commons-for-a-fleet.md`](https://github.com/anthony-chaudhary/dos-private)
in `dos-private`; this note is the *how a fleet shares state* half, that note is
the *why a buyer wants it* half.

---

## 1. The status tax is super-linear, and that is the forcing function

Start from the operator observation that prompted this note: **agents can work for
long stretches undirected, but the longer they run, the more they must communicate
status.** This is true, and it is worse than linear. The need for an agent to emit
status scales with the *product* of two things:

- **How long it runs.** A 30-second agent owes nobody an update. A 6-hour agent
  that silently went wrong at hour 1 wasted six hours before anyone could know.
- **How many things depend on its answer.** A leaf agent no one waits on can stay
  mute. An agent three other agents (and a human) are downstream of owes status
  *continuously*, because the cost of discovering its failure late is the whole
  dependent subtree.

The product is the tax. "Fire and forget for a long time" is a lie the moment
something depends on the answer — you could forget *until* the dependency formed,
and then you needed the status all along. So a fleet that runs agents long and
undirected is *forced* into a status-sharing problem. The question this note
answers is **what *shape* that shared status should take**, and the answer the
kernel already implies is: not a message, a fact.

The whole note compresses to one paragraph — the canonical statement, kept here so
it is found at the top and quoted from one place:

> **The longer an agent runs undirected, the more its status must become a fact
> others can read, not a message others must believe. Free-form agent-to-agent
> communication stays hard because it's trust-under-self-narration — the receiver
> can't verify the sender. DOS sidesteps that for the *coordinating* subset by never
> asking anyone to believe anyone: agents share a durable commons of
> kernel-adjudicated effects (leases, verified steps, liveness verdicts, resume
> points), and read each other's *ground truth* instead of each other's *claims*.
> That's a narrow, real capability that a message bus and a blackboard both lack —
> the blackboard especially, because believing its writers is the very failure mode
> DOS exists to refuse. What stays unsolved is collaboration over *judgment* — the
> advice and rationale that never become an adjudicable artifact.**

---

## 2. Why the *general* A2A problem is hard — and may stay hard

The instinct is to let the agents talk: a message bus, a chat channel, a shared
natural-language scratchpad. Agent A finishes the auth refactor and tells agent B
"auth is done, you can build on it." B proceeds.

The hard part of A2A is **not transport.** Agents can trivially exchange bytes. The
hard part is that **the message is a self-report, and the receiver has no
independent way to verify it.** A's "auth is done" is exactly the kind of claim
[`102`](102_when-to-trust-an-agent.md) §1 says the kernel must not believe: a
*report made after the work, when "done" is the rewarded answer.* B believing it is
B inheriting A's confabulation. This is the same wall that makes multi-agent
systems hard in general — every agent is, to every other agent, an unreliable
self-narrating worker. Free-form A2A (negotiate, delegate, persuade, explain in
natural language) is *trust-under-self-narration at full bandwidth*, and there is
no general mechanism that makes the receiver able to trust the sender. That problem
may stay open for a long time, possibly forever, because it is not an engineering
gap — it is the absence of a ground truth inside the channel.

**The move DOS makes is to refuse to play that game.** It does not make the message
trustworthy. It removes the requirement that anyone trust a message at all.

### 2.5 What "self-report" actually means in an agentic context

The word *self-report* is doing all the work in this note and the ones around it
([`102`](102_when-to-trust-an-agent.md), [`103`](103_memory-is-an-unverified-agent.md),
[`108`](108_the-cheap-lie-and-the-narration-taxonomy.md)), so pin it precisely,
because the intuition imported from human teams is *wrong* here in a way that makes
the agentic version far more dangerous.

A human's "I finished the auth refactor" and an agent's "I finished the auth
refactor" are byte-identical strings and **epistemically different animals.** When a
human says it, the words are a *readout of* a separate internal state — the human
has a metacognitive channel that actually knows whether the work is done, and even a
human who lies *knows they are lying* against that channel. The report is downstream
of a ground truth the speaker holds.

An agent's self-report has no such upstream. It has five properties that, together,
are the whole reason the kernel exists:

1. **It is generated by the same process that did (or didn't do) the work — there is
   no independent faculty to consult.** "I completed the refactor" comes out of the
   same next-token machinery as the refactor attempt itself. There is no separate
   *knower* the sentence is a readout of; the report is **another generation**, not
   an observation of an internal fact. This is the deepest difference from a human
   report and the one the human-team intuition silently violates.
2. **It is pulled toward the rewarded answer, not the true one.** "Done / success /
   it works / making progress" is the shape both the prompt and the training
   gradient reward. The self-report drifts toward *what was asked for*, not *what
   happened* — [`102`](102_when-to-trust-an-agent.md) clause 2 (a claim made after
   the work, when "done" is the rewarded answer) and [`108`](108_the-cheap-lie-and-the-narration-taxonomy.md)'s
   cheap lie.
3. **Its confidence is itself a self-report.** You cannot rescue a self-report by
   asking the agent how sure it is — "I'm certain" is produced by the same machinery
   as "done," so calibration cannot be recovered from inside. *A model's expression
   of confidence is as much narration as the claim it qualifies* — the
   [`108`](108_the-cheap-lie-and-the-narration-taxonomy.md) §3 regress: narration
   that bottoms out on another narrator has bottomed out on nothing.
4. **It is fluent and plausible — the lie and the truth are indistinguishable to a
   reader.** Fluency is the single thing the model is best at, so a false self-report
   reads *exactly* like a true one. A human's false report often has tells; an
   agent's does not. There is no surface signal to filter on.
5. **Its failure is silent.** A wrong self-report throws no exception and emits no
   error. It just propagates — into the next agent that builds on it, into the
   memory that records it, into the human who reads the status line and relaxes.

Now the pivot that reframes the entire problem:

> **In an agentic context, "self-report" is not a *category of message* an agent
> sometimes sends. It is the default mode of *everything an agent emits about its
> own effects.*** Every "I did X," every "this works," every "I'm making progress,"
> every recalled memory, every status line — all of it is self-report, because the
> agent has no non-self-report channel for describing what it did. The *only* thing
> that is not a self-report is **the effect itself — the commit, the file, the lease,
> the env print — read by something that did not author it.**

That last sentence is the kernel in one line. DOS's entire posture is the refusal to
read the self-report (any of the five-property generations above) and the insistence
on reading the *un-authored effect* instead. "Don't believe the agents" was never
about catching liars; it is about recognizing that an agent's account of itself is
*structurally* not evidence — it is generation #2 about generation #1 — and that the
only evidence is the residue the agent could not generate its way around: the thing
that actually landed, checked by a reader the agent did not control.

---

## 3. The reframe: agent-to-substrate adjudication replaces agent-to-agent messaging

> **The agents never have to talk to each other, and — the load-bearing part —
> they never have to *believe* each other, because they read the same
> kernel-adjudicated state instead of exchanging self-reports.**

Take the thing one agent would otherwise have to *tell* another, and turn it into a
fact the second agent *reads and re-verifies from a durable commons.* The
communication channel becomes the substrate, and the substrate's defining property
is that it **does not believe the sender** ([`102`](102_when-to-trust-an-agent.md)'s
trust law, applied to the channel rather than to a single call). Every coordinating
A2A primitive collapses onto a shipped surface:

| What A would *say* to B (A2A — self-reported, untrusted) | What DOS makes a *shared durable fact* (substrate-adjudicated, no belief required) | Surface |
|---|---|---|
| "I'm working on the auth files, stay out." | A **lease**. B does not take A's word — B `arbitrate`s and the kernel *refuses* B the colliding region. Coordination happens with no message and no trust. | `arbiter.arbitrate` over `lane_journal.replay` (the live-lease WAL) |
| "I finished phase 3." | A **`STEP_VERIFIED`** — but note the structure: A can only *claim* (`STEP_CLAIMED`, forgeable); the "done" B reads is the kernel's minted belief over git ancestry, never A's say-so. | `intent_ledger` (`STEP_CLAIMED` vs `STEP_VERIFIED`, the §3.2 epistemic split) |
| "I'm still alive and making progress." | A **liveness verdict** B computes from A's git/journal delta — ADVANCING / SPINNING / STALLED — *without asking A*, and explicitly not from A's "making progress" self-report. | `liveness.classify` over `git_delta` + `journal_delta` |
| "I died at step 4; here's where I got." | A **`LedgerState`** a successor folds from A's `intent.jsonl`; the re-entry SHA is re-verified against ancestry, not read from the dead run's last claim. | `intent_ledger.replay` → `resume.resume_plan` |
| "Don't bother replanning — I already did." | A veto routed off journal + verdict state, not off another agent's assertion. | `dos.scout` over the WAL + verdict envelopes |

Every row is the same gesture. The receiver's confidence does **not** come from the
sender's honesty; it comes from a deterministic re-derivation over a commons the
sender could not forge. That is why this slice is *solvable* while general A2A is
not: DOS did not make the agents trustworthy to each other — it made their
trustworthiness *irrelevant* to coordination, by routing every coordinating signal
through an adjudicator that re-checks it.

---

## 4. What the commons is — and the hard edge it has

State the capability precisely, because the precise version is both more defensible
and more useful than "DOS lets agents share state."

> DOS does not let agents share state. It lets them share **adjudicated facts about
> effects on a commons, without trusting each other's narration.**

Two contrasts make the narrowness clear, and both are uncommon enough to justify the
claim that this "otherwise doesn't really exist":

- **A message bus** is transport with no adjudication. It moves the self-report
  faster; it does nothing about its truth.
- **A blackboard / shared scratchpad** is a store that *believes whatever is written
  to it.* This is not the cure — it amplifies the failure it appears to address. A
  shared store that trusts its writers is a faster way to propagate one agent's
  confabulation to all the others.
  This is exactly [`103`](103_memory-is-an-unverified-agent.md)'s finding turned
  outward: *the memory store IS the DOS problem* — frozen self-reports recalled as
  fact. A blackboard for a fleet is `103` at fleet scale.

What is genuinely rare, and what DOS has, is a **shared store where every durable
record is either an effect the kernel adjudicated, or a self-report explicitly
tagged distrusted-until-verified.** The intent ledger's `STEP_CLAIMED`/`STEP_VERIFIED`
split *is* that discipline frozen into a data shape (`intent_ledger.py:81-93`,
`235-316`); the lane journal's "log only the effect the arbiter decided, never the
agent's narration of the effect" is the same discipline on the lease side
(`lane_journal.py:126-137` — `REFUSE`/`HALT` are recorded but mutate no state; only
adjudicated effects fold).

But the constrained problem has a **hard edge**, and naming it is more useful than
over-claiming past it:

> DOS shares the *adjudicable residue* of what an agent did — the part that lands as
> a commit, a lease, a verdict, an env print. It does not, and structurally cannot,
> share the part that didn't.

"I tried approach X, it felt wrong, here's my hunch why, you should try Y" is the
high-bandwidth content of real collaboration, and it is **pure unadjudicable
narration.** DOS has nothing to say about it by design — it is content, not
structure ([`102`](102_when-to-trust-an-agent.md) §1 clause 1). So:

- **Solved (the coordinating subset):** continuity and coordination over a shared
  commons — who holds what region, what actually shipped, is a run still moving,
  where did a dead run get to. Every one of these has an independent re-derivation,
  so none requires trusting a peer.
- **Not solved (and out of scope):** collaboration over *judgment* — advice,
  intuition, persuasion, design rationale. None of it becomes an adjudicable
  artifact, so the kernel can neither verify it nor refuse it. That is the open A2A
  problem, and it stays open.

The discipline this note adds to the contract: **a future "let agents share X"
feature is in-scope only if X is an adjudicable effect.** The moment a proposal
routes a peer's *judgment* through the commons as if it were a fact, it has
reintroduced the blackboard, and `103` says how that ends.

---

## 5. The one buildable surface: status as a folded fact, not a self-report

The commons is *readable* today — a peer agent or a human can already call
`liveness`, `replay` the ledger, `replay` the WAL, and `resume_plan`. But it is not
*legible*: there is no single verb that folds "where is run R right now?" into one
A2A-shaped fact. The status tax of §1 wants exactly that — a peer that depends on R
should be able to poll **one** adjudicated status, not stitch four reads together
and risk reading a self-report by mistake.

Propose a thin Layer-3 projection (the [`CLAUDE.md`](../CLAUDE.md) helper rule: it
*carries no policy of its own*; it only composes shipped kernel readers), shaped
like the other projections (`decisions` over the four refusal sources, `dispatch_top`
over the live fleet):

- **A pure `StatusDigest(run_id)`** that folds, for one run:
  - its **liveness verdict** (`liveness.classify` — ADVANCING/SPINNING/STALLED, the
    in-flight "is it moving" fact);
  - its **declared intent + verified progress** (`intent_ledger.replay` →
    `LedgerState`: goal, declared steps, and crucially the `verified` map — *not*
    the `claimed` map, so the digest reports adjudicated progress, never the
    agent's say-so);
  - its **held region** (the run's live lease from `lane_journal.replay`, so a peer
    sees what is fenced off);
  - its **resumability** if it has stopped (`resume.resume_plan` —
    RESUMABLE/COMPLETE/DIVERGED/UNRESUMABLE).
- **A `dos status <run_id>` verb** that prints it (and `--json` for a peer agent /
  the MCP surface to consume). Read-only, takes no lease, launches nothing — the
  same posture as `dos top` and `dos decisions`.

The whole point of routing it through one verb is the **fail-closed default**: the
digest reads `verified`, never `claimed`; it reads the liveness *verdict*, never a
"progress" field; it reads the resume *verdict*, never the dead run's last
`STEP_CLAIMED`. A peer that polls `dos status` therefore cannot accidentally consume
a self-report, because the digest's construction never exposes one. That is the
mechanism contribution: **legibility without re-opening the trust hole** — the
A2A-shaped fact is, by construction, only ever the adjudicated residue.

This is deliberately small. It mints no new evidence and no new durable record; it
is a projection over four shipped folds, exactly as `103`'s recall driver is a
re-verification over shipped readers rather than a new store. The heavier questions
it gestures at — a *push* status channel (a peer subscribes to R's transitions
rather than polling), cross-run status in one fleet view, the env-print
([`115`](115_the-under-what-axis-environment-and-version-provenance.md)) folded in
as "under what did R declare its intent" — are follow-ups, and each is a fold over
state that already exists, never a new thing to trust.

---

## 6. Why this is the kernel's shape, not a bolt-on

It would be easy to read §5 as "add a status feature." It is the opposite: the
status digest is *forced* by the kernel's existing design and is sound *only*
because of it. A blackboard could also offer a "status" read — and it would be
worthless, because it would report what the agent wrote about itself. DOS's status
read is worth polling for exactly one reason: **the same distrust that makes every
syscall a refusal makes every field in the digest a re-derivation.** The four folds
the digest composes are each a *no* in disguise (`82`'s taxonomy): liveness refuses
to believe "I'm making progress"; the ledger refuses to read `claimed` as done; the
WAL refuses to record a narration as an effect; resume refuses to trust the dead
run's last claim.

So the durable commons is not a second thing DOS does alongside refusing. **It is
what refusing produces.** A fleet sharing state through DOS is a fleet that has
agreed to coordinate on ground truth instead of on each other's word — and the only
reason that is possible is that something in the middle ([`102`](102_when-to-trust-an-agent.md)'s
structure-trusting, content-distrusting kernel) re-checks every signal before any
agent acts on it. The constrained A2A problem is solved not by a communication
feature but by the absence of one: there is nothing to communicate, only state to
adjudicate and read.

---

## 6.5 What has sharpened since this note (added 2026-06-07)

This note (and its strategy sibling) were written 2026-06-03. Three things have
moved since — two are kernel facts that have landed, one is a benchmark result —
and each sharpens the commons claim rather than revising it. They are folded in here
so the original argument above stays as it was written.

**(1) The common thing is not the *state* — it is the shared *vocabulary*.** §3–§4
sell *distrust* as the novelty (the store refuses to believe its writers). True, but
incomplete: two agents can only coordinate on a fact if they *parse it the same way*.
A blackboard fails not only because it believes its writers but because it has **no
agreed schema** — agent A's "done" and agent B's reading of "done" are different
predicates, so even an honest write miscoordinates. What makes the commons a commons
is that all four syscalls emit a **closed verdict vocabulary** with a fixed,
machine-checkable meaning per term (`SHIPPED`/`NOT_SHIPPED`,
ADVANCING/SPINNING/STALLED, the typed refusal enum, RESUMABLE/COMPLETE/DIVERGED/
UNRESUMABLE) — and the meaning is pinned to *ground truth*, not to whoever wrote the
record. So the precise capability is **distrust *plus* a shared closed vocabulary**;
neither alone is the commons. This is not aspirational — it is enforced:
[`durable_schema`](../src/dos/durable_schema.py) tags every durable record with a
`schema:` family+version and is **refuse-don't-guess** (a record a newer kernel wrote
is classified `UNREADABLE_NEWER`, never silently misparsed). That is the literal
mechanism by which two agents on different kernel versions cannot quietly disagree on
what a term *means* — the vocabulary is versioned, and a reader that would have to
guess refuses instead. The commons has a lingua franca, and the lingua franca
fails-closed.

**(2) The commons is *cross-vendor* — and that is the edge isolation and the labs
cannot copy.** The operator's prompt asks about a common thing between *various*
agents, and "various" is doing real work the original note did not pick up. A Claude
agent, a Codex agent, and a Cursor agent **cannot share Anthropic's or OpenAI's
internal scratchpad** — each vendor's own coordination layer stops at its own
boundary. But they can all read the same lease WAL and the same git ship-verdict,
because **the kernel names no vendor in code** (the litmus is enforced by
[`tests/test_vendor_agnostic_kernel.py`](../tests/test_vendor_agnostic_kernel.py): no
non-driver kernel module may name a vendor as an identifier or branch on which vendor
is acting). A vendor's hook *dialect* is OUTPUT chosen downstream of an
already-decided verdict ([`217`](217_the-cross-vendor-hook-dialect-seam.md) — the
`HookVerdict` seam + the `ClaudeCodeDialect` default; the installer that wires it
into any of four runtimes is *The cross-vendor hook installer*,
`docs/221`). So the commons is the **only** shared substrate a *heterogeneous* fleet
has. The original note's neutrality reads as a nice-to-have when every agent is the
same vendor; the moment the fleet is mixed-vendor — which is the realistic 2026 case
— neutrality stops being a nice-to-have and becomes the *whole reason* a common
thing exists at all. (This seam post-dates the note: 217 and the installer landed
after 2026-06-03.)

**(3) The honest edge of §4 has gotten *measured*, and it holds.** §4 draws the line
at the *adjudicable residue* — the commons carries what lands as a commit, a lease, a
verdict, an env print, and structurally cannot carry the rest. The benchmark work
since has put numbers on exactly where "the rest" begins, and they tighten the line
rather than moving it: ~38% of agent goals never reach a sound witness at all (the
*presence-not-goal* wall — `verify`'s file-path rung confirms a path was touched, not
that the goal was met), and the multi-agent *fold* (a lead believing N subagents'
"done") is a **rate** problem, not a token one — ~33% of real subagents die, but they
die cheap. So the commons is sound exactly over **the coordinating subset that
reaches a witness**, which is precisely the §7 line (adjudicate the silent-and-costly
effects; stay out of the loud-and-cheap judgment). The new data does not soften the
hard edge — it draws it with a ruler. The discipline §4 added to the contract stands
unchanged: a future "let agents share X" feature is in-scope only if X is an
adjudicable effect that reaches a witness; share a peer's *judgment* through the
commons and you have rebuilt the blackboard.

The throughline of all three: the commons is **a versioned shared vocabulary of
witness-backed verdicts, neutral across vendors, sound only where a witness exists.**
That is a longer sentence than "DOS lets agents share state," and every added clause
is load-bearing.

---

## 7. See also

- [`102_when-to-trust-an-agent.md`](102_when-to-trust-an-agent.md) — the trust law
  this note rests on (structure-not-content, commitments-not-reports,
  only-where-wrong-yes-is-cheap). This note is "what a fleet can therefore *share*";
  102 is "when is it reasonable to trust at all."
- [`103_memory-is-an-unverified-agent.md`](103_memory-is-an-unverified-agent.md) —
  the blackboard *is* the disease; a shared store that believes its writers is `103`
  at fleet scale. The status digest's fail-closed construction is the antidote.
- [`107_resumable-work-and-the-intent-ledger.md`](107_resumable-work-and-the-intent-ledger.md)
  — the intent ledger (`STEP_CLAIMED` vs `STEP_VERIFIED`), the durable surface that
  carries a run's declared intent + adjudicated progress; the digest's progress
  field reads `verified`, never `claimed`.
- [`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md)
  — every fold the digest composes is a kind of *no*; the commons is what refusing
  produces.
- [`217_the-cross-vendor-hook-dialect-seam.md`](217_the-cross-vendor-hook-dialect-seam.md)
  + *The cross-vendor hook installer* (`docs/221`) — the seam behind §6.5(2): the
  kernel names no vendor, so a *heterogeneous* fleet's only shared substrate is this
  commons. A vendor dialect is OUTPUT downstream of an already-decided verdict.
- [`durable_schema`](../src/dos/durable_schema.py) (the `docs/107` §6 floor) — the
  mechanism behind §6.5(1): every durable record is `schema:`-tagged and
  refuse-don't-guess, so the shared *vocabulary* fails-closed across kernel versions
  rather than two agents silently disagreeing on what a term means.
- `dos-private/dispatch-os-the-durable-commons-for-a-fleet.md` — the positioning
  sibling (why a buyer wants this; the bus-vs-blackboard-vs-adjudicated-commons
  landscape). One-way arrow: that doc references this code; nothing here depends on
  it.
- `dos-private/dispatch-os-team-and-hosted-coordination.md` — the *inter-engineer*
  multiplicity plane (N humans, the PR-to-main merge as arbiter). This note is its
  *intra-fleet* dual: N agents under one operator, the kernel state as the shared
  substrate.
- **docs/155 — this thesis applied to the DOS BUILDERS themselves (the dogfood test).**
  Several Claude agents built the EnterpriseOps arc (docs/143–154) in parallel and
  *coordinated through claims, not effects* — exactly the failure this note says the
  kernel solves: two agents took `docs/151` (a region collision a lease prevents);
  hot files accreted near-duplicate fixes (the lane the agents didn't run); ~41 commits
  all authored "Claude" (the run_id spine they didn't stamp). docs/155 is the ruling +
  the partial fix (a keyed measurements registry = adjudicated effects; the dogfood
  split of which collisions a region-lock catches vs which are semantic). The irony is
  the proof: the kernel that referees a fleet was built by an unrefereed one.

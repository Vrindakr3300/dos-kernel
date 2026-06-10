# 212 — DOS in non-coding domains: the world-witness axis

> **The one-line claim.** Everything DOS does that is *coupled to code* (the git
> rungs — grep-subject, file-path, commit-ancestry) is the **weak** part of the
> kernel anyway: it is a W2 *presence* witness, not a W3 *goal* witness (docs/192,
> [[project-dos-wall-presence-not-goal]]). The **strong** part — the part that
> actually establishes truth without believing the agent — is the **world-state
> witness**: `effect_witness` joins an agent's CLAIMED effect to a read-back of the
> world from a *different byte-author*, and believes only on a non-forgeable rung
> (`believe_under_floor`). That join has **nothing to do with code.** It is the
> general shape "did the world actually change the way you say it did?" — and most
> high-value agent work outside coding is exactly that shape. So the right way to
> read "apply DOS to non-coding domains" is not *port the kernel sideways*; it is
> *the kernel was never really about code — code was just the first domain with a
> cheap, ubiquitous, tamper-evident witness (git).* This doc maps which non-coding
> domains have a witness of the same quality, which don't, and what the kernel needs
> to serve them.

This is an **exploration / design note**, not a build plan with a measured result.
It is grounded against three things, kept honest by citing each: (1) DOS's own
measured findings (the four walls, the witness ladder, the conversion-gap program);
(2) a June-2026 web check on the surrounding field; (3) the one structural test the
project has learned to trust — *split every witness into its evidence-bytes and its
spec-bytes, and ask `byte-author ≠ judged-agent` of each separately* (docs/192 §4).
Where I have only reasoning and no measurement, I say so.

---

## 1. Why the question is the right one — and why "world verification" is the part that travels

Start from what DOS actually is, stripped of the userland that birthed it
(CLAUDE.md): *a small deterministic kernel that adjudicates ground truth across many
unreliable, self-narrating workers, and serializes their effects on shared state
without believing what they say they did.* Nothing in that sentence is about code.
Code entered for one reason: **git is an unusually good witness.** It is

- **ubiquitous** (every software workspace already has one),
- **tamper-evident** (content-addressed; the agent authored the file bytes but did
  not author *whether a commit touched a path* — that is git-authored),
- **cheap to read** (`git log`, no extra infra), and
- **already adopted** (the ship-stamp the oracle reads is just a commit).

That combination is why DOS could be *demonstrated* on code first. But the kernel's
own honest self-audit (docs/192) found that even git only gets you to **W2** — it
witnesses that an artifact *landed*, not that the artifact is *right*. The thing
that reaches toward W3 is `effect_witness` (docs/181, [[project-dos-effect-witness-shipped]]):
a verdict that takes the agent's claimed effect and joins it to a read-back of
world-state *from a different surface*, and is structurally unable to confirm or
refute on a rung the agent could have authored. **That join is domain-free.** The
shipped driver (`drivers/state_diff.py`) already diffs an abstract before/after
state (rows inserted/deleted/updated) — it was written for a database, not a
repository, and the kernel module (`effect_witness.py`) names no code concept at all.

So the user's instinct is exactly right, and I'd put it more sharply: **the world
witness is not "especially useful" in non-coding domains — it is the *only* part of
DOS that was ever domain-general.** The git rungs are the domain-specific driver
that happened to ship first because its witness was free.

### The field is converging on the same idea (web check, June 2026)

Two independent signals say this is not a private intuition:

- **τ-bench** — the standard tool-agent benchmark for *non-coding* domains (retail,
  airline, CRM customer-support) — evaluates by *comparing the database state at the
  end of a conversation against an annotated goal state*, and enforces a
  **closed-world invariant**: every state change must be explained by an assertion;
  any *other* insertion/deletion/mutation is treated as a side effect and **fails
  the task.** That is `effect_witness` + the `state_diff` "claim ⊆ witnessed-delta"
  rule, already operating as a benchmark standard outside code. The same writeups
  report the field-validated lesson DOS is built on: *"replace LLM-based validation
  with deterministic checks; deterministic validators block fabricated IDs at
  near-zero cost"* — the ORACLE→JUDGE ladder, measured by someone else.
- **"Domain verifiability"** is now a named 2026 concept (MindStudio): *"True
  verifiability means there's a ground truth you can check against, not just a
  scoring rubric you can apply,"* used explicitly as the predictor of *where AI
  agents can replace human work.* That is DOS's W3\* gold-provenance axis (docs/192
  §4) arrived at from the product side. The market is already sorting domains by
  exactly the variable this doc is about.

The point of citing them is not "we're not alone" reassurance — it's that **the
classification axis this doc proposes is the one the field is independently using**,
which means a DOS framed around it speaks the emerging vocabulary instead of a
private one.

---

## 2. The transferable abstraction — restated without any code in it

Here is the whole kernel in domain-free words, so the rest of the doc can apply it
to anything:

1. **An agent emits a CLAIM** about a change to shared state ("I refunded the
   customer", "I booked the room", "I filed the form", "I updated the patient's
   chart", "I sent the brief to opposing counsel", "I rebalanced the portfolio").
2. **A claim is forgeable by its author** — generation #2 of bytes about generation
   #1. Believing it is the original sin ([[project-dos-what-is-truth-throughline]]).
3. **A witness is a read-back of the world authored by someone other than the
   claiming agent.** Its grade is *how hard it would be for the claiming agent to
   forge it* — the evidence ladder, carried as the `source=`/`accountability` field.
4. **Truth = the claim survives a join against a non-forgeable witness.** Where no
   such witness can decide → ABSTAIN to a human. This is `believe_under_floor`:
   believe **iff** a non-forgeable surface attests; otherwise degrade, never invent.
5. **The split that makes it sound (docs/192 §4, the sharpest tool in the project):**
   every witness has two halves —
   - **evidence bytes** (the read-back itself: the bank ledger line, the calendar
     entry, the lab result), and
   - **spec/projection bytes** (what we diff the evidence *against*: the expected
     amount, the expected attendee, the reference range).

   Soundness is **conjunctive**: you must ask `byte-author ≠ judged-agent` of *each
   half separately*. DOS's git rung passes for the evidence (the diff is
   git-authored) and *fails* for the spec (the file list comes from the
   agent-authored plan doc). **A domain is well-served by DOS exactly to the degree
   that BOTH halves have a non-agent author.**

That fifth point is the entire predictive content of this doc. Everything below is:
*for domain D, who authors the evidence, and who authors the spec?*

### The world-witness ladder, domain-free (from docs/192 §2)

| rung | what it witnesses | soundness | coding example | non-coding example |
|---|---|---|---|---|
| **W0** narration | the agent's CLAIM | forgeable (agent authored every byte) | "I fixed the bug" | "I issued the refund" |
| **W1** action-ack | the action was ACCEPTED | unsound *as a goal-witness* | "wrote to file" / 200 OK | `refund_api → {"status":"ok"}` |
| **W2** persisted state, read back | the artifact LANDED | conditionally sound — **presence only** | `git log` touched the path | the ledger row exists |
| **W3** state diffed against a gold | GOAL-ACHIEVEMENT | depends on **W3\*** | content == expected | refund amount == owed amount |
| **W3\*** *who authored the gold* | grounding vs consistency | the real axis | — | — |

And the gold-provenance sub-ladder (W3\*, docs/192 §4) — **the same in every domain**:

| gold source | soundness | the test |
|---|---|---|
| **(A) env-enforced structural invariant** (a balance that must sum to zero, a double-booking the calendar refuses, a schema the form rejects) | **sound + scalable** — the only class that needs no per-task human | the world *itself* won't let the wrong state exist |
| **(B) human-authored reference, out-of-band** | sound but **non-scaling** | a per-task gold a human wrote |
| **(C) agent/plan-supplied expected value** | **forgeable** — grading own homework | the agent authored the spec |
| **(D) a verifier-agent (LLM judge)** | **advisory only** — fail-to-abstain | a model checking a model |

Class **(A)** is the prize in any domain: where the *environment's own rules* make
the wrong state un-representable, you get a free, scalable, non-forgeable W3 witness
with no human in the loop. Code's version is "the test suite is green / the build
compiles." The question for each non-coding domain is: **does it have a class-(A)
invariant?**

---

## 3. The map — non-coding domains sorted by witness quality

I'll group domains by *the best witness rung reachable cheaply*, because that, not
"is it interesting", is what decides whether DOS earns its keep. Three tiers.

### Tier 1 — domains with a native class-(A) invariant (DOS transfers almost directly)

These have a system-of-record whose *own* rules forbid the wrong state, so the
read-back is W3 with a non-agent-authored spec. This is the strongest fit and the
shortest path to a real result.

- **Money movement / bookkeeping / payments ops.** Double-entry is a structural
  invariant: debits must equal credits, a ledger must reconcile, a refund cannot
  exceed the original charge. An agent that claims "issued a $40 refund" can be
  joined to the *bank/ledger* read-back (different principal entirely — the payment
  processor authored those bytes, not the agent), and the *spec* ("$40", "≤ original
  charge") is enforced by the accounting system, not supplied by the agent. **Both
  halves non-agent-authored.** This is the cleanest non-code fit in existence; it is
  also where a wrong-but-confident agent is most expensive, which is the
  [[project-dos-effect-witness-shipped]] thesis ("a competent agent fails more
  *silently*") at its highest stakes.
- **Calendar / scheduling / booking (travel, rooms, resources).** The calendar or
  reservation system *refuses* a double-booking — a class-(A) invariant. "I booked
  room 3 at 2pm" joins to a read-back of the resource's own state (the booking
  system authored it), and the conflict-freedom spec is enforced by that system.
  This is also literally reachable in *this* environment — the Google Calendar MCP
  tools are connected, so a believed-vs-witnessed demo is buildable today with no
  benchmark download (see §6).
- **Inventory / supply / logistics.** Stock counts, "shipped → tracking number
  exists in the carrier's system", "reserved units ≤ on-hand". The carrier and the
  WMS author the witness bytes; conservation-of-units is the structural spec.
- **CRM / ticketing state machines (τ-bench's actual domain).** A ticket can only be
  in one state; an order's status transitions are constrained; an ID either exists
  in the DB or doesn't. This is precisely why τ-bench's deterministic DB-hash check
  works and why *"deterministic validators block fabricated IDs at near-zero cost"*
  is a measured result and not a hope. **DOS's `effect_witness` is the same check;
  τ-bench is the ready-made proving ground.** ([[project-dos-out-of-loop-live-payoff]]
  already identified `E-TAU2-WRITEADMIT` as the single cleanest live-payoff
  experiment — tau2's gold DB-hash is the least-gameable witness anywhere, agent
  authors zero bytes of it.)

For Tier 1 the kernel needs *almost nothing new*: a driver per system-of-record that
reads its state back into `evidence.EvidenceFacts`, exactly as `state_diff.py`
already does for a generic before/after. The hard, valuable work is the **read-back
driver**, not the kernel.

### Tier 2 — domains with a W2 witness but a contested or absent class-(A) spec (DOS helps, but only as presence + honesty, like it does for code today)

Here you can cheaply read back *that something landed*, but *whether it's the right
something* needs a spec the agent or a judge supplies. This is **exactly where
code already sits** — W2 presence, W3 gold is plan-authored (docs/192 §3). DOS is
genuinely useful here but should make the *same* honest claim it makes for code: "I
prove it happened, not that it's correct."

- **Computer-use / browser agents (OSWorld, WebArena, GAIA-style).** You can read
  back the DOM / filesystem / screenshot — that the form was submitted, the setting
  changed, the file saved (W2). But "did the agent achieve the *user's goal*"
  usually has no structural invariant; the gold is a human-authored reference state
  (class B, non-scaling) or a judge (class D, advisory). Note the web check surfaced
  **video-based reward models for computer-use agents** (arXiv 2603.10178) — the
  field is reaching for *exactly* a W3 witness here and finding it expensive. DOS's
  contribution: pin the read-back to a non-agent surface (the OS/DOM authored it,
  not the agent's narration), refuse to let the agent's "task complete" close the
  loop, and route the residual correctness question to JUDGE/HUMAN with the
  forgeability grade attached. That is the docs/192 prescription, unchanged.
- **Document/form filing (legal, tax, compliance, HR onboarding).** The filing
  system acknowledges receipt (W1→W2: a confirmation number, the doc now exists in
  the system). Whether the *contents* are correct is often class-B (a reviewer's
  reference) or class-A only for the structured fields (a tax form's arithmetic must
  sum; a required field can't be blank — those are real class-(A) invariants worth
  harvesting). **Split the form:** the structured/arithmetic part is Tier 1; the
  free-text/judgment part is Tier 2/3. This is the docs/192 §4 "split evidence from
  spec" applied *within a single artifact*.
- **Data pipelines / ETL / analytics ops.** Row counts, schema conformance,
  referential integrity, "the dashboard query returns" — these are class-(A)
  structural invariants (Tier 1 for the *shape*). "Is the number *right*" is the
  grounded-RAG problem ([[project-dos-grounded-rag-adoption]]): the `derived_witness`
  primitive already handles "a number is non-forgeable iff its operands are
  non-forgeable AND the op is declared AND the recompute matches" — directly reusable
  for any numeric claim in any domain.

### Tier 3 — domains where the goal is intrinsically judgment, with no non-agent spec (DOS abstains by design; honesty about this is the product)

These are the ~38% residue of docs/192 §4 lifted out of code: **there is no sound
world-state witness at any rung**, because the authoritative "correct" lives in a
human's head or on an absent third principal.

- **Content generation / writing / summarization / "research synthesis".** "Is this
  summary good / is this brief persuasive / is this analysis correct" has no
  class-(A) invariant and no cheap class-(B) gold. This is the q_025 trap from
  [[project-dos-grounded-rag-adoption]] verbatim ("grounded-but-not-an-answer"): you
  can verify every *cited fact* is grounded (Tier 1, via `derived_witness`/citation
  rungs) while the *overall answer* is wrong or non-responsive. **DOS's honest move
  is to verify the verifiable substrate and ABSTAIN on the gestalt** — and to *say
  so*, rather than let a green "all facts grounded" masquerade as "the answer is
  right." Refusing to overclaim here is the docs/138 discipline.
- **Open-ended advisory (medical triage, financial advice, legal opinion).** The web
  check flagged these as the headline 2026 agent domains. They are Tier 3 for the
  *recommendation* but contain Tier 1 *substrate* (a drug-interaction check is a
  class-(A) invariant; a contraindication is structural; a regulatory limit is
  enforced). The right architecture is **the trust ladder, unchanged**: structural
  checks first (ORACLE), advisory judge on the residue (JUDGE, fail-to-abstain),
  human at the irreducible seed (HUMAN). DOS *is* this ladder; the contribution is
  keeping the deterministic floor from being skipped because a fluent model "seems
  confident" (G3's measured result: a live judge is **35.2%** gamed by fluent prose,
  the deterministic floor **0%** — [[project-dos-e1-distillation-on-real-behavior]]).

**The Tier-3 lesson is the same as code's Wall 3:** capability does not create a
witness where none exists. A better model fails *more silently* here, which raises
the value of "verify the substrate, abstain on the gestalt, attach the grade" — it
does not let DOS suddenly grade the gestalt.

---

## 4. What carries over unchanged, what needs a driver, what is genuinely new

Sorting the kernel against the map above:

**Carries over with zero kernel change (it never named code):**
- `effect_witness.witness_effect` (claim ⋈ read-back, `believe_under_floor`).
- `evidence` (the `EvidenceSource` protocol, the forgeability spectrum,
  `derived_witness`).
- `arbiter` / lane leases (concurrency over *any* shared region — a shared calendar,
  a shared ledger, a shared CRM record is a "lane" the same way a file-glob is;
  [[project-dos-lane-is-a-region-lock]]). A fleet of support agents racing on the
  same customer record is the *same* collision DOS measured on files (docs/190).
- `judges` (the JUDGE rung, fail-to-abstain) — domain-free already.
- The whole refusal vocabulary, liveness, resume, the spine/WAL.

**Needs a driver (the real work, but it's userland, not kernel):**
- **A read-back driver per system-of-record** — the non-coding analogue of the git
  rungs. Reads a ledger / calendar / CRM / WMS state into `EvidenceFacts` on the
  *correct forgeability rung* (THIRD_PARTY when a separate principal authored it,
  OS_RECORDED for a system ack, AGENT_AUTHORED — and therefore floor-rejected — when
  it's the agent re-reading its own surface). `drivers/state_diff.py` is the template;
  `drivers/os_acceptance.py` (run a command, read the exit code) is the other.
- **A spec source per domain** — and this is where the soundness lives. The driver
  must mark whether the spec is class-(A) structural (trust), (B) human-reference
  (trust, non-scaling), (C) agent-supplied (degrade to forgeable), or (D) judge
  (advisory). This is just `believe_under_floor` applied to the *spec* half, which
  the kernel already supports; the driver's job is to *classify honestly*.

**Genuinely new / unbuilt (worth naming as gaps):**
- **A live HTTP/API read-back prober** (`drivers/http_readback`, already named as
  follow-on #3 in [[project-dos-effect-witness-shipped]]) — re-GET an idempotent
  effect URL to witness "the refund/booking/filing is actually there." This is the
  single most leverage-y unbuilt driver for Tier 1: it turns "I called the API and
  it said ok" (W1, forgeable-as-goal) into "I independently re-read the resource and
  the effect is present" (W2/W3 depending on the spec). Most Tier-1 systems-of-record
  expose exactly such a read endpoint.
- **The PEP for irreversible non-code actions.** The web check surfaced a whole 2026
  sub-literature on *irreversible actions in tool-agents* (the tau-bench "structure
  multi-agent systems around irreversible actions" writeup; "behavioral contracts
  with runtime enforcement", arXiv 2602.22302). Code's irreversibility is mild (git
  reverts). A refund, a sent email, a booked flight, a filed legal document is
  **not** revertible — which makes the **PRE**-action gate (`dos hook pretool`,
  [[project-dos-tool-call-division-pretool]]) far more valuable here than in code,
  because the cheapest place to be right about an irreversible effect is *before* it
  happens. DOS has the deny-capable seam (`permissionDecision: deny`) and the
  conjunctive admission floor (a gate can only refuse-MORE, never wrongly admit);
  what it lacks is the *pre-condition witness* — "is the world in the state that
  makes this irreversible action safe?" — which is the same read-back driver aimed
  *before* instead of *after*. **This is the most domain-distinctive new direction:**
  in code, DOS's measured value is detect-and-halt *after*; in irreversible
  non-code domains, the value migrates to *admit-or-refuse before*, where it has a
  genuine PEP story.

---

## 5. The honest caveats (the same discipline applied to this doc)

Per docs/138 and the project's own habit of stating weaknesses every time:

1. **This is reasoning, not a measured result.** Every "DOS transfers to X" above is
   a *prediction from the witness-quality test*, not an A/B. The project's hardest-won
   lesson is that static reasoning re-projects and only a **live loop changes an
   outcome** ([[project-dos-out-of-loop-live-payoff]], docs/179). The map tells you
   *where to spend*, not *that it pays*. The one place to actually measure is §6.
2. **Value-capture is unsolved here too, and for the same reason.** The conversion
   gap ([[project-dos-conversion-gap-value-capture]]) is domain-independent: a sound
   verdict handed back to the *same agent's next action* washes to ~0 on a capable
   model. In non-coding domains the winning consumer is the same as in code — a
   **non-agent consumer**: the workflow's coordinator gating an irreversible action,
   a downstream peer refusing to inherit unwitnessed state, a human review queue that
   shrinks. Tier 1 + the pre-action PEP is attractive *precisely because* it has a
   natural non-agent consumer (the gate that blocks the refund), which is the half of
   the problem code struggles with.
3. **Tier 3 is most of the headline market and DOS abstains on its core.** The
   splashy 2026 agent domains (advice, content, research) are largely Tier 3 for the
   deliverable. DOS's value there is *substrate verification + honest abstention*,
   which is real but is not "DOS grades the answer." Selling it as the latter is the
   docs/192 overclaim, one domain over.
4. **"Domain verifiability" cuts both ways.** The same MindStudio framing that
   validates the axis also says: where there's no ground truth, *no* verifier —
   DOS included — can manufacture one. DOS's differentiator is not that it verifies
   the unverifiable; it's that it **grades its own witness** and refuses to dress up
   a W1 ack or an agent-authored spec as a W3 goal-proof. That honesty *is* the
   product across domains, which is the [[project-dos-grounded-rag-adoption]]
   reframe (the standard, not the 40-line function) restated for the non-code case.

---

## 6. The cheapest decision-relevant experiment (if this is worth pursuing)

Following the project's rule — *the cheapest datum that resolves the load-bearing
uncertainty* — there are two $0-to-cheap moves, in order:

1. **A Tier-1 believed-vs-witnessed demo on the connected Google Calendar MCP
   (≈$0, no benchmark download).** This is the non-code twin of
   `live_orchestrator_demo`. Have an agent *claim* a set of bookings; build a
   tiny read-back driver that re-reads the calendar (a different byte-author than
   the agent's narration) and runs `effect_witness.witness_effect` over each claim;
   inject one *silent* failure (claim a booking that the API quietly rejected for a
   conflict — the class-(A) invariant firing) and show DOS returns **REFUTED** where
   the agent's narration says success. That is docs/181's gemini-quiz demo
   ("I successfully created the quiz" → REFUTED) reproduced in a *non-coding*,
   *irreversible-adjacent*, *natively-connected* domain — and it directly de-risks
   the "Tier 1 transfers" claim with real tool calls, not a replay. **It also exercises
   the most-distinctive new direction (the pre-action gate) for free:** the
   conflict-refusal *is* a class-(A) invariant you can witness before committing.
2. **The τ-bench write-admission payoff already scoped in docs/209 /
   [[project-dos-out-of-loop-live-payoff]] (`E-TAU2-WRITEADMIT`, ~$80–200).** This
   is the *measured-payoff* version: tau2 is the ready-made Tier-1 non-coding
   benchmark with a gold DB-hash (least-gameable witness anywhere), a real
   producer self-report to distrust, and a clean non-agent consumer (a peer
   inheriting committed state). It is *already the project's top live-payoff pick* —
   this doc's contribution is the framing that explains *why* it's the right one:
   it is the canonical Tier-1 domain, and Tier-1 is where the witness is sound at
   both halves.

Do #1 first (it's free, it's connected, it proves the transfer mechanically); do #2
only if a believed-vs-adjudicated *payoff* number is wanted (it proves the value,
not just the signal). Everything in Tiers 2–3 is downstream of whether Tier 1
demonstrably works, and #1 settles that for the price of a few calendar calls.

---

## 7. The through-line

DOS is not a code tool that might generalize. It is a **trust substrate that was
demonstrated on code because git is a free, tamper-evident witness** — and the part
that does the actual trusting (`effect_witness` + `believe_under_floor` + the
forgeability ladder) never knew it was looking at code. Apply it to a non-coding
domain by asking one question, the docs/192 §4 question, of that domain:

> **Who authors the evidence, and who authors the spec — and is each a different
> author than the agent making the claim?**

- Both non-agent → **Tier 1**, DOS transfers almost directly; build a read-back
  driver and you have a sound W3 witness (money, calendars, inventory, CRM —
  τ-bench's own turf).
- Evidence yes, spec no → **Tier 2**, DOS gives presence + honesty, the same claim
  it honestly makes for code today (computer-use, form-filing, ETL).
- Neither → **Tier 3**, DOS verifies the substrate and **abstains on the gestalt**,
  and the product is that it tells you it's abstaining (content, advice, research).

The strongest, most distinctive non-coding direction is **irreversible Tier-1
actions** (refunds, bookings, filings): they have a sound class-(A) witness *and*
they make the **pre-action** gate valuable in a way code never did — which is the one
place DOS's missing PEP finds a natural, high-stakes home. That, not a sideways port
of the git rungs, is where "world verification in non-coding domains" actually pays.

---

*Companion strategy framing (who buys this, how it positions against the
"domain-verifiability" and tool-receipt vendors) belongs in `dos-strategy`, not here
— this is the mechanism note. See [[project-dos-two-product-fleet-and-kernel]] for
the product split.*

> **Part of the four-doc "beyond code" arc — index + synthesis in [docs/222](https://github.com/anthony-chaudhary/dos-strategy/blob/master/222_beyond-code-the-domain-and-grounding-exploration-index.md). Forward in the arc: [docs/213](https://github.com/anthony-chaudhary/dos-strategy/blob/master/213_dos-in-regulated-domains-legal-healthcare-life-science.md) (regulated domains), [docs/215](https://github.com/anthony-chaudhary/dos-strategy/blob/master/215_dos-is-not-rag-grounding-the-generation-vs-grounding-the-verdict.md) (RAG vs DOS grounding), [docs/220](https://github.com/anthony-chaudhary/dos-strategy/blob/master/220_why-the-grounding-insight-was-hard-to-see.md) (why it was hard to see). _(This arc relocated to the `dos-strategy` repo; docs/212 stays here as the engineering anchor.)_**

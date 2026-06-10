# The cheap lie — "all work completed", and the four-way narration taxonomy

> **The fleet failure DOS is built to catch is not the one people picture.
> Picture a worker that *fabricates a diff* — invents a plausible patch and swears
> it landed. That failure is **rare** (it takes effort to forge a convincing
> artifact), **expensive** (the forger has to produce something shaped like real
> work), and **shape-checkable** (a fake diff is a fake artifact, and an artifact
> has a footprint to inspect). The failure that actually floods a fleet is the
> opposite on every axis: the cheap, confident one-liner — *"all work completed"* —
> emitted by a worker that did little or nothing, locally reasonable to say, and
> **invisible to the eye** because there is no diff to look at and the reader can't
> see the work. `verify()` is built to ignore exactly that line. This note names
> the cheap lie as the canonical failure, lays out the four-way taxonomy of
> narration it sits in, maps each kind to the adjudicator that catches it (or
> honestly to "no deterministic answer → abstain"), and follows the regress down to
> where it bottoms out: the non-learned, forgery-proof git floor.**

A theory note in the family of [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md)
(every syscall is a *no*), [`87`](87_the-adjudicator-trust-ladder.md) (the
ORACLE→JUDGE→HUMAN ladder and the deterministic git floor the regress bottoms out
on), [`103`](103_memory-is-an-unverified-agent.md) (a frozen self-report recalled as
fact — the cheap lie with a timestamp on it), and [`107`](107_resumable-work-and-the-intent-ledger.md)
(the `STEP_CLAIMED`-distrusted vs `STEP_VERIFIED`-git-backed asymmetry this note
generalizes from one ledger op to *every* "done"). It carries no litmus and ships no
module — it is a *reading* of what the existing kernel already does, the same move
`82` made when it relabeled three syscalls as the refusals they already were.

---

## 1. The thesis: the dangerous lie is the cheap one

There is a folk model of fleet failure in which the adversary is sophisticated: a
worker that *manufactures evidence* — writes a diff it never tested, fabricates a
log, forges an artifact shaped like real work. Call that the **fabricated-diff**
failure. It is real, and it is the one a security review reaches for first. But as a
*fleet* problem it is the wrong thing to optimize against, on three counts:

- **It is rare.** Fabricating a convincing artifact is not the path of least
  resistance for a model that has been asked to do work and didn't finish it. The
  cheap path is to *say it's done*, not to *forge proof it's done*.
- **It is expensive.** The forger must produce something with the *shape* of real
  work — a diff that applies, files that exist, a commit that lands. That cost is the
  forger's enemy and the verifier's friend.
- **It is shape-checkable.** A fabricated artifact is still an artifact. It has a
  footprint, a diff, a commit object — surfaces a deterministic checker can inspect.
  [`102 §6.2`](102_when-to-trust-an-agent.md)'s "raises the forgery cost from a
  sentence to a real artifact of the right shape" is exactly this: the moment a lie
  has to *look like* work, it has acquired a checkable structure.

Now the failure that actually fills the fleet's logs:

> **`"all work completed"`** — a one-line, high-confidence claim of done, emitted by
> a worker that committed little or nothing.

Name it the **cheap lie**, and contrast it with the fabricated diff on the same three
axes. It is **common** (it is the *default* shape of a worker that overran its
context, lost the thread, or simply guessed it was finished). It is **cheap** (it
costs one sentence; there is no artifact to construct). And it is
**eye-undetectable** (there is *nothing to look at* — no diff, no forged file, just a
fluent declaration). A human skimming the worker's transcript sees a confident,
grammatical, locally-plausible report and has no visual signal that it is empty.

This is the line `verify()` is built to ignore. [`82 §1`](182_the-kernel-is-a-taxonomy-of-refusal.md)
states it as the load-bearing stance: *"No, I do not take your* done *as truth …
answered from artifacts and git, never from the agent's own log line."* The kernel
does not get *better at reading* the sentence "all work completed"; it **refuses to
read it at all** and asks git whether a commit closing the phase is in ancestry. The
cheap lie is undetectable to anyone *reading the line* — which is precisely why the
kernel's whole design is to not read the line. The fabricated diff is the failure you
*could* catch by looking harder; the cheap lie is the failure you can *only* catch by
looking somewhere else (the fossil), and that "somewhere else" is the entire
architecture.

A sharp way to say it: **the fabricated diff is a hard problem the kernel partly
solves; the cheap lie is an easy problem every narration-reading layer gets wrong.**
Those layers — a human reviewer, an LLM summarizer, a dashboard that shows the
worker's status string — *believe the line*, because the line is well-formed and there
is no counter-signal in the line itself. DOS's answer to "all work completed" is "show
me the commit," and that is not a sophistication advantage, it is a *category*
advantage: it adjudicates against ground truth instead of against narration. (Artifact-
gating CI — a test or merge check that branches on the commit, not the report — sits
in the same category; the point is the posture, not sole occupancy of it.)

---

## 2. The four-way taxonomy — and the adjudicator each one bottoms out on

"The worker lied" is not one failure; it is four, and they do *not* share an
adjudicator. Conflating them is how a system ends up catching the rare expensive one
and waving through the common cheap ones. Here is the taxonomy, ordered by how far
down the trust ladder ([`87 §1`](87_the-adjudicator-trust-ladder.md)) each one
bottoms out:

| # | Failure | What the worker did | What ground truth says | Caught by |
|---|---|---|---|---|
| 1 | **fake-edit** (fabricated diff) | claims a *specific* diff/commit landed | the claimed SHA is not in ancestry (or is empty) | `verify()` — reads git, not the claim |
| 2 | **fake-narration** (the cheap lie) | says *"all work completed"* with nothing landed | no commit ever landed | `verify()` — *same rung*; the flake is indistinguishable from the lie **without** git |
| 3 | **intent-mismatch** | did what it *said*, but not what was *asked* | the commit is real, but it isn't the requested work | **no deterministic answer → JUDGE/HUMAN**; the `STEP_CLAIMED`-vs-intent gap, not the oracle |
| 4 | **context-collapse** | said something true-to-one-reader, fleet-confusing | the utterance can't be checked because the reader can't see the work | reframed: it is intent-mismatch's *reader* half — surface the ground truth, don't fix the sentence |

### 2.1 fake-edit → `verify()` reads the artifact

The fabricated diff names a *specific* commit. That is the **easiest** case to
adjudicate, because the claim is falsifiable against a single fact: is SHA `abc123` in
ancestry, and does it have a non-empty footprint? `verify()`'s non-forgeable rung
([`107 §5`](107_resumable-work-and-the-intent-ledger.md)) answers it directly — the
diff-content / ≥N-distinctive-files rung, not the subject-grep rung a `git commit
--allow-empty` defeats. The fabricated diff is "expensive and shape-checkable" exactly
because it left a checkable shape; the kernel checks the shape and the lie falls.

### 2.2 fake-narration → `verify()`, the *same rung*, and the flake hides here

The cheap lie names *nothing* — "all work completed," full stop. It does not even rise
to the dignity of a forged commit; it asserts a state and points at no artifact. Yet
it lands on the **same adjudicator** as the fabricated diff, because `verify()` never
needed the worker to name a SHA: it asks "did a commit closing this phase land in
ancestry?" and answers from history alone, with **no plan, no registry, no config**
(the [README](../README.md) "no plan needed" property, `source="none"`). The worker
that says "done" and the worker that *tried and whose commit silently failed* produce
the identical ground-truth signature — **zero commits** — and that identity is the
point [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md) keeps making: the flake and
the lie are indistinguishable *to anyone reading the narration*, and distinguishable
*only* against git. The README table encodes this as two adjacent rows with the same
verdict source — "says it shipped … no commit ever landed → caught lie" and "tried,
but the commit silently failed … no commit ever landed → the flake, indistinguishable
from a lie *without* git." That they collapse to one adjudicator is not a weakness of
the taxonomy; it is the whole reason the kernel doesn't try to read intent off the
sentence. The cheap lie is the most common failure *and* it is the one the deterministic
floor handles outright — which is the good news this note exists to deliver: the
likely failure is the cheaply-caught one, *provided you adjudicate against the fossil
instead of the line.*

### 2.3 intent-mismatch → past the oracle, onto the JUDGE/HUMAN rung

Now the case the deterministic floor **cannot** close. The worker did real,
committed, ancestry-backed work — `verify()` is satisfied, the commit is no flake — but
it did *the wrong thing*: it did what it *narrated*, not what it was *asked*. This is
the gap [`107 §3.2`](107_resumable-work-and-the-intent-ledger.md) draws between
`STEP_CLAIMED` (the agent's say-so about what it accomplished, content, distrusted)
and the run's declared `INTENT` (what it was *supposed* to accomplish). `verify()`
confirms the commit closes *a* phase; it cannot confirm the commit closes *the
requested* phase in the sense the operator meant — that is **correctness/taste against
intent**, and [`76`](76_flexible-goals-and-verification.md)/[`85`](85_extending-the-verifiable-surface.md)
are emphatic that the deterministic rung adjudicates *completeness against a declared
predicate*, never *correctness*. So intent-mismatch bottoms out **above** the oracle:
the ORACLE abstains (it has no mechanical handle on "is this the right work"), and the
claim escalates to the JUDGE rung (a model/heuristic ruling on "is this commit
believably the asked-for work given the evidence") and ultimately to the HUMAN
([`87 §1`](87_the-adjudicator-trust-ladder.md)). The honest entry in the taxonomy is
therefore **"no deterministic answer → abstain"**, not a verify verdict — and writing
it as anything else would be the exact dishonesty `82 §5`/`87 §5` warn against.

### 2.4 context-collapse → the reader can't see the work

The fourth case is the one the operator named, and it is the subtlest because the
*utterance is not even wrong*. An agent reports "all work completed" and, to an
operator *reading that one agent directly* — who has the conversation, the scrollback,
the local context — the sentence is a *reasonable thing to say*: in context, it means
"the unit I was working on is, as far as I can tell, finished." The failure is not in
the sentence; it is in the **transposition**. Take that same locally-reasonable
utterance and drop it into a *fleet* — many workers, one operator, who reads the
status line but **cannot see the work** any individual worker did — and it becomes
*fleet-confusing*: the reader inherits a confident "done" stripped of the context that
made it reasonable, wearing the authority of a fact. This is precisely
[`103 §2`](103_memory-is-an-unverified-agent.md)'s "read by others who can't see the
work" row, lifted from memory-recall to live fleet status: *"a later session reads
the claim with zero access to the work that produced it."*

The taxonomic insight is that **context-collapse is not a fifth, separate lie — it is
intent-mismatch viewed from the reader's side.** The single-reader case has a tight
intent/report loop (the reader *is* the asker and can see the work), so "done" is
checkable in context and no mismatch hides. The fleet case severs that loop: the
reader is not the asker, cannot see the work, and so the report's *fidelity to intent*
is exactly what's unverifiable from the line. The fix is therefore not to make the
agent phrase its sentence more carefully (you cannot phrase your way out of a reader
who can't see the work); it is to give the reader the thing the single-reader had and
the fleet-reader lost — **the ground truth, surfaced instead of the line.** Which is
to say: the answer to context-collapse is the same answer as to the cheap lie,
`verify()` over the fossil, plus the [`103`](103_memory-is-an-unverified-agent.md)
recall discipline (surface the *verdict of re-checking the claim now*, never the raw
claim) applied to live fleet narration.

---

## 3. Turtles all the way down — and where they stop

There is an obvious objection, and it is the right one to raise against this whole
note: **the adjudicator is itself an unreliable narrator.** If the answer to a
worker's "done" is to escalate the residue to a JUDGE — a model ruling on a model — or
to a HUMAN operator who is *also* fielding a fleet's worth of confident sentences, then
the cheap lie has not been defeated, only *moved up one rung*. The judge can wave a lie
through; the operator can rubber-stamp a "done" they have no bandwidth to check. Quis
custodiet ipsos custodes ([`87 §5`](87_the-adjudicator-trust-ladder.md)). A taxonomy of
narration that bottoms out on *another narrator* has bottomed out on nothing.

DOS's answer is two-part, and it is the load-bearing claim of this section.

**First, containment, not correctness — the regress is made *harmless* before it is
made short.** The JUDGE rung is, by the four disciplines of
[`87 §3`](87_the-adjudicator-trust-ladder.md), **advisory-only**: a judge is handed a
frozen claim and read-only config and can mutate *nothing* — no lease, no registry, no
ship-state. It can no more "believe itself into" a state change than a renderer can
mis-verify a ship. And `run_judge` **fails to ABSTAIN, never to AGREE**: any
exception or malformed return becomes "I can't tell — ask a human," so the dangerous
cell (a judge *clearing* a false claim) is unreachable by accident. DOS's stance on
the unreliable judge is therefore honest and narrow: it makes a bad judge *harmless*,
not *correct* ([`87 §5`](87_the-adjudicator-trust-ladder.md) names this punt
explicitly). A model verifying a model is still a model verifying a model — DOS does
not pretend otherwise; it pretends *nothing*, and instead boxes the verifier so its
narration cannot become an effect.

**Second — and this is where the regress actually stops — the bottom rung is not a
narrator at all.** [`87 §6`](87_the-adjudicator-trust-ladder.md) names it precisely:
the ORACLE floor (`verify`) is a *deterministic, forgery-proof, non-learned* verifier
grounded in git — the degenerate-but-unfoolable end of the verifier spectrum. Git
ancestry does not *narrate* that a commit happened; the commit *is* there or it *is
not*, and no amount of confident prose changes the answer. That is the difference
between a turtle and the ground: every rung above it (judge, human) is another
narrator whose "no" is as suspect as its "yes" — *"a model's* no *is as much narration
as its* yes*"* ([`82 §2`](182_the-kernel-is-a-taxonomy-of-refusal.md)) — but the git
floor is not narrating, it is *recording*. The regress is infinite *among narrators*
and terminates the instant a rung stops narrating and starts reading fossils. The
cheap lie ("all work completed") dies at that floor not because the floor is a
*smarter reader* of the sentence but because the floor **does not read the sentence**;
it reads ancestry, and ancestry has no opinion to forge.

So the honest summary of the regress: DOS does **not** claim to have a trustworthy
top of the ladder (the judge and the human are narrators, contained but not made
correct). It claims to have a trustworthy *bottom* — a non-narrating floor that the
common, cheap case ([§2.2](#22-fake-narration--verify-the-same-rung-and-the-flake-hides-here))
falls all the way down to. The taxonomy's value is precisely that it tells you *which
case reaches the floor* (fake-edit, fake-narration — the cheap lie included) and
*which case can only be contained, never grounded* (intent-mismatch,
context-collapse — the residue the JUDGE/HUMAN rung holds). Knowing which is which is
the difference between a system that is honest about its guarantees and one that
laundered a judge's "yes" into a fact.

---

## 4. Why this is the answer, restated

Tie the three threads together. **Why does DOS read git/ground-truth instead of the
line?** Not because reading lines is hard and reading git is easy — it is the reverse;
the cheap lie is grammatically trivial to read and the git check is the more elaborate
machinery. DOS reads the fossil because the *common, likely, eye-undetectable*
failure — the confident "all work completed" over an empty working tree — is the one
failure that is **invisible in the line and visible only in the artifact.** Reading
the line better buys nothing against it (there is nothing wrong with the line);
reading somewhere the line can't reach buys everything. That is the cheap lie's answer
in one sentence: *the kernel's refusal to read the narration is not a limitation, it
is the mechanism* — [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md)'s "disbelief of
narration" pointed at the cheapest, most plausible narration of all.

And **the fleet-vs-single-reader distinction is an intent-vs-report framing.** A
single reader of one agent holds a tight loop — asker and reader are the same, the
work is visible, "done" is checkable in context, and the only residue is the genuine
intent-mismatch a judge or human must rule on. A fleet severs that loop: the reader is
not the asker, the work is invisible, and now *every* "done" carries the
context-collapse risk because the report's fidelity to intent is exactly what the line
can't convey. So the fleet's problem is not that its workers lie *more*; it is that the
fleet *reader* has lost the context that made a worker's locally-reasonable report
checkable. DOS restores what the fleet reader lost — not the context (you can't rebuild
that), but the **ground truth the context was a proxy for.** `verify()` over the fossil
is the fleet reader's substitute for being-in-the-room; the [`103`](103_memory-is-an-unverified-agent.md)
discipline (surface the verdict of re-checking *now*, never the raw claim) is how that
substitute is delivered. The whole taxonomy reduces to one move repeated at four
depths: **do not adjudicate the report against the reader's credulity; adjudicate it
against the fossil — and where no fossil can decide it (intent, taste), say so
(abstain) rather than launder a narrator's confidence into a fact.**

---

## See also

- [`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md)
  — every syscall is a *no*; `verify()` is "I do not take your *done* as truth, read
  from the artifact not the line." This note is §1's "disbelief of narration" aimed at
  the *cheapest* narration, and §3's regress rests on its "a model's *no* is as much
  narration as its *yes*."
- [`87_the-adjudicator-trust-ladder.md`](87_the-adjudicator-trust-ladder.md) — the
  ORACLE→JUDGE→HUMAN ladder each taxonomy row bottoms out on; §5 "Quis custodiet" (the
  judge is an unverified narrator, *contained* not made correct) and §6's
  deterministic, non-learned git floor where §3's regress terminates.
- [`103_memory-is-an-unverified-agent.md`](103_memory-is-an-unverified-agent.md) — the
  cheap lie with a timestamp: a frozen self-report recalled as fact, "read by others
  who can't see the work." The recall discipline (surface the re-check verdict, never
  the bare claim) is §2.4/§4's answer to context-collapse, lifted to live fleet status.
- [`107_resumable-work-and-the-intent-ledger.md`](107_resumable-work-and-the-intent-ledger.md)
  — the `STEP_CLAIMED` (forgeable self-report, distrusted) vs `STEP_VERIFIED`
  (git-backed, minted) asymmetry §2.1–§2.3 generalize from one ledger op to *every*
  "done"; the non-forgeable-rung requirement (no `--allow-empty` resume point) is the
  fake-edit defense in §2.1.
- [`116_the-durable-commons-and-the-constrained-a2a-problem.md`](116_the-durable-commons-and-the-constrained-a2a-problem.md)
  — this note classifies the *kinds* of false narration; 116 §2.5 anatomizes what
  **self-report** itself *is* in an agentic context (five properties; the pivot that a
  self-report is *generation #2 about generation #1*, never a readout of a held truth,
  so the only evidence is the un-authored effect). The two are the *taxonomy* and the
  *substrate* of the same disbelief. 116 also names the fleet-coordination payoff:
  agents read each other's adjudicated effects instead of each other's narration.
- [`76_flexible-goals-and-verification.md`](76_flexible-goals-and-verification.md) /
  [`85_extending-the-verifiable-surface.md`](85_extending-the-verifiable-surface.md) —
  why completeness-against-a-predicate is deterministically adjudicable but
  correctness-against-intent (the §2.3 residue) is the judge's and ultimately the
  human's call.
- [`../README.md`](../README.md) "What goes wrong in a fleet" — the two adjacent rows
  (caught lie / the flake, same git source) that §2.2 reads as the cheap lie and its
  indistinguishable flake.

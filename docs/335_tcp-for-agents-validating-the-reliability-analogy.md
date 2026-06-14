# 335 — "TCP for agents": validating or refuting the reliability analogy

> **The claim under test.** *TCP/IP made unreliable links carry reliable data.
> DOS makes unreliable actors produce trustable effects.* It is a seductive
> one-liner — a famous systems result loaned to a new layer. This note takes it
> at its word and tries to break it. The method is the kernel's own: do not
> believe the slogan because it sounds true; check it against the mechanism, name
> exactly where the mapping holds, where it bends, and where it snaps — and end
> with the one thing that would *refute* it, not just argue about it.

This is a theory note in the family of [`333`](333_verification-as-steering-and-the-verification-first-harness.md)
(verification is the steering wheel — the *control-theory* reframe),
[`138`](138_what-is-truth-the-throughline.md) (what the kernel means by truth),
and [`114`](114_prior-art-audit-where-the-branding-outruns-the-mechanism.md) (the
skeptical audit that already found the load-bearing gap). docs/333 borrowed
*control theory*; this note borrows *networking* — and the two analogies are not
interchangeable. The control-loop frame flatters DOS; the TCP frame, read
honestly, **indicts** it on the one axis that matters, and that is exactly why it
is worth writing down. It carries no litmus and ships no mechanism.

The verdict in one line, so the rest can earn it: **the analogy is true as a
statement of the *problem shape and the architectural ambition*, and false as a
statement of the *mechanism DOS has today* — and the precise size of the gap
between "true" and "false" is the missing enforcement point that
[`114`](114_prior-art-audit-where-the-branding-outruns-the-mechanism.md) already
named (the PDP with no PEP).** TCP did not just *detect* corruption; it *refused
to deliver it*. DOS, today, detects.

---

## 1. State the analogy precisely — what maps to what

A slogan hides its joints. Lay them out before judging them. TCP/IP's
achievement, stripped to mechanism: an IP datagram can be dropped, duplicated,
reordered, or corrupted in flight, and the link makes no promise. TCP turns that
into a byte stream that arrives complete, in order, and uncorrupted — using four
machines:

| TCP mechanism | What it does | DOS's claimed counterpart |
|---|---|---|
| **Checksum** | a number computed over the bytes that a corrupt packet will fail | the **evidence ladder** ([`138`](138_what-is-truth-the-throughline.md)) — a verdict read from an un-authored effect that a false claim fails |
| **Sequence numbers** | detect loss/reorder; reassemble the stream in order | the **intent ledger** + `residual = declared − verified` ([`117`](117_completion-as-a-verdict-the-end-of-working-in-passes.md)) — what was promised vs. what landed, in order |
| **ACK / retransmit** | the receiver only ACKs good data; bad/lost data is re-sent | the **closed loop** ([`333`](333_verification-as-steering-and-the-verification-first-harness.md)) — `NOT_SHIPPED`/`INCOMPLETE` re-dispatches the residual |
| **Drop-on-fail** | a packet failing checksum is **discarded, never delivered up the stack** | *(this row is the whole argument — see §3)* |

The mapping is real on the first three rows. The fourth row is where the analogy
lives or dies, and the table already shows the asymmetry: TCP's fourth mechanism
has no honest DOS counterpart yet. Hold that thought; first give the analogy its
strongest possible case, because a refutation that skips the steelman is just a
preference.

---

## 2. The case FOR — where the mapping is genuinely tight (not just pretty)

Three correspondences are not rhetorical. They are structural, and each one is a
real reason the slogan keeps getting reached for.

**2.1 The substrate-doesn't-promise move is identical.** TCP's founding
concession is that you will *never* make the links reliable — fiber will flip
bits, routers will drop, packets will race. So you stop trying to fix the link
and instead build a layer *above* it that delivers reliability *despite* a
substrate that refuses to. DOS makes the exact same concession about the actor:
you will *never* make the LLM agent reliable — it will hallucinate, over-claim,
collide, spin. [`102`](102_when-to-trust-an-agent.md)'s trust law and
[`138`](138_what-is-truth-the-throughline.md)'s one invariant are that concession
written down: do not try to make the agent honest; build a layer that yields a
*trustable effect* despite an actor that will not be honest. **Both designs
relocate the guarantee from the unreliable component to a layer that wraps it.**
That is not a loose metaphor; it is the same architectural decision, and it is the
true core of the slogan.

**2.2 The guarantee rides on an un-authored check, not on the sender's good
faith.** TCP's checksum works because the *bits decide* — the sender cannot
declare a corrupt packet clean; the arithmetic over the bytes is not something the
sender authors around. This is precisely [`138`](138_what-is-truth-the-throughline.md)'s
one invariant restated: the witness's author is not the judged party. A SHIPPED
stands on git ancestry plus a real file footprint the agent "cannot retroactively
change" — *which files a historical commit touched* is the checksum-grade fact.
The shape — *a guarantee whose validity does not depend on trusting the thing
being guaranteed* — is the same shape in both layers. This is the deepest true
thing in the analogy, and it is worth keeping.

**2.3 The unit of reliability is the *end state*, not the *per-hop behavior*.**
TCP does not promise that any individual packet behaves; it promises the *stream*
arrives. DOS does not promise any individual agent *step* is honest; it promises
the *effect that lands in git* is the one that was adjudicated. Both move the
promise from "every internal action is good" (unachievable) to "the observable
end-state is trustworthy" (achievable by checking). [`333`](333_verification-as-steering-and-the-verification-first-harness.md)'s
`residual = declared − verified` is TCP's "all sequence numbers accounted for":
the stream is complete when nothing promised is still missing against ground
truth. The closed-loop re-dispatch *is* retransmission of the residual. On these
three rows the analogy is not borrowed glamour — it is a genuine isomorphism of
problem shape.

So if the slogan said only *"DOS relocates the reliability guarantee off the
unreliable actor onto an un-authored check of the end state, and re-drives the
unfinished part — the way TCP relocates it off the unreliable link onto a
checksum of the stream, and re-sends the lost part,"* it would be **true**. The
trouble is the verb in the original: *makes* unreliable actors *produce* trustable
effects. "Makes … produce" is an enforcement verb. TCP earns that verb. DOS, today,
does not — and §3 is why.

---

## 3. The case AGAINST — the disanalogy that does the damage

Rank the breaks by how much they cost. The first one is fatal-to-the-verb; the
others are real but survivable.

### 3.1 TCP *enforces* at a chokepoint the data must pass through. DOS *observes* after the effect already landed. (The fatal one.)

This is the fourth table row, and it is the whole game. When a TCP segment fails
its checksum, the receiver **discards it** and it is **never delivered up the
stack** — the application *cannot* read corrupt bytes, because the corrupt bytes
are dropped at a gate every byte must traverse before it becomes "delivered data."
TCP's reliability is **inline, mandatory, and pre-delivery**. The check sits *on
the only path* from wire to application.

DOS does not sit on that path. [`114`](114_prior-art-audit-where-the-branding-outruns-the-mechanism.md)
established the fact and this note only renames it for the analogy: **DOS is a PDP
with no PEP — a decision procedure that observes effects *after the commit already
exists*, and is *voluntarily invoked*.** When an agent writes a bad effect to the
working tree and commits it, the commit is *already in git* before `dos verify`
ever runs. The verdict is `NOT_SHIPPED`, exit 1 — a true, un-authored, valuable
fact — but the corrupt "packet" was *already delivered up the stack*. Nothing
dropped it at a gate, because there is no gate; `verify` is a reader, not a filter.
In TCP terms, **DOS is a checksum you compute on a packet that has already been
handed to the application, and whose only power is to tell you, afterward, that
you should not have trusted it.**

That is not nothing — a receiver that *flags* every corrupt delivered packet is
strictly better than one that flags none, and a fleet gated on exit-1 *does*
refuse the false "done" at the loop boundary. But it is a categorically weaker
guarantee than TCP's, and the slogan's verb hides the difference:

- TCP: *the application never sees corrupt data.* (prevention)
- DOS: *the operator is reliably told which delivered data was corrupt, and a
  cooperating loop re-drives it.* (detection + cooperative correction)

The honest rewrite of the slogan's second half is therefore **"DOS makes
unreliable actors' effects *legible* — it reliably tells trustable from untrustable
*after the fact* — and lets a cooperating loop re-drive the untrustable."** The
word *makes … produce* claims a PEP DOS does not have. The gap between the slogan
and the mechanism is exactly one enforcement point — the same one
[`114 §F`](114_prior-art-audit-where-the-branding-outruns-the-mechanism.md)
reserved as the apply-gate (docs/119, unbuilt) and
[`333 §5`](333_verification-as-steering-and-the-verification-first-harness.md)
conceded as the advisory floor.

*One honest mitigation, so this is not a strawman.* DOS is not purely
post-effect on **every** axis. Admission — `arbitrate` over the lease journal, and
the scope gate at the edit boundary ([`89`](89_the-lane-is-a-region-lock.md),
[`102 §5`](102_when-to-trust-an-agent.md)) — *is* a pre-effect gate where the host
wires it: two agents colliding on a region can be refused *before* the write.
There, DOS does have a small TCP-grade chokepoint. But the *completion* guarantee —
the one the slogan is really about — is post-effect, and a hook the host can
decline to install is not the mandatory gate TCP's checksum is. The chokepoint
exists in patches, not as the spine.

### 3.2 TCP's checksum is binary and mandatory; DOS's check is graded and partly forgeable. (Real, survivable.)

A TCP checksum has one verdict: pass or fail, computed the same way on every
segment, not optional. DOS's evidence ladder ([`138`](138_what-is-truth-the-throughline.md))
is deliberately *graded* — `registry` and `grep-artifact` are checksum-grade
(un-authored), but `grep-subject` is forgeable: an agent that can write a commit
can write one whose *subject* matches the stamp grammar, and an `--allow-empty`
commit on the right SHA satisfies that rung
([`114 §A3`](114_prior-art-audit-where-the-branding-outruns-the-mechanism.md),
[`138 §"Where truth is still forgeable"`](138_what-is-truth-the-throughline.md)).
TCP has no rung an attacker forges by writing a plausible-looking packet, because
the checksum is over the *bytes that matter*, not over a label the sender controls.

This is a real disanalogy, but it is the *survivable* kind, for two reasons.
First, DOS does not hide it — it *grades* the rung (`source=` carried as data) and
colours the forgeable one yellow, so the operator reads the confidence, not just
the verdict. A TCP checksum that announced "I am the weak rung" would be more
honest, not less. Second, the ladder is *hardenable rung by rung*
([`85`](85_extending-the-verifiable-surface.md)): the file-path rung is already
checksum-grade, and an execution rung (OS exit code,
[`drivers/os_acceptance.py`](138_what-is-truth-the-throughline.md)) is strictly
stronger. So the gap here is "the default rung is weaker than a CRC," not "the
mechanism cannot reach CRC strength." It is a tuning ceiling, not a wall.

### 3.3 The "stream" is single-writer and idempotent; the agent's effects are multi-writer and not always idempotent. (The retransmission disanalogy.)

TCP retransmission is safe because re-sending a lost segment is *idempotent at the
receiver* — the sequence number dedupes it, and the bytes are the same bytes. DOS's
"retransmit the residual" rides on the same assumption ([`114`](114_prior-art-audit-where-the-branding-outruns-the-mechanism.md)'s
ARIES critique made this precise): re-driving an unfinished phase is safe *only
when the effect is a git commit*, which is atomic and idempotent. The moment an
agent step has a **non-git or non-idempotent side effect** before it commits — an
external POST, a charged card, a sent email — "re-drive the residual" is
*at-least-once execution of effects*, and TCP's clean retransmission analogy breaks:
TCP never had to worry that re-sending segment 7 would charge a card twice. DOS
inherits the exactly-once problem TCP's layering let it dodge, and it has no
compensator (no Undo —
[`114 §"third ARIES phase"`](114_prior-art-audit-where-the-branding-outruns-the-mechanism.md)).
This is narrower than §3.1 (it bites only on non-git effects), but it is a place the
networking analogy actively *misleads* if taken whole.

---

## 4. The deepest cut — the end-to-end argument, which both *blesses* and *convicts* DOS

The single most important paper behind TCP is not TCP. It is Saltzer, Reed, and
Clark, *End-to-End Arguments in System Design* (1984). Its thesis: **a function
like reliability can only be completely and correctly implemented at the
*endpoints* of a communication system — the application that knows what "correct"
means — not in the intermediate links.** A link-level checksum is a *performance
optimization* (it catches errors early so you re-send a hop, not the whole
stream); the *correctness* guarantee has to live at the end, because only the end
knows the bytes were the *right* bytes for *its* purpose. This argument is the
reason TCP's checksum lives at the receiving host's transport layer and not in the
routers.

Point this lens at DOS and it cuts both ways — which is what makes it the deepest
part of the analysis.

**It blesses DOS.** The end-to-end argument says: put the real check at the
endpoint, the place that knows what done means, *not* inside the unreliable
component or its immediate plumbing. DOS does exactly this. It refuses to put the
completion check *inside the agent* (the agent is the unreliable link; its
self-report is a link-level promise the end-to-end argument tells you to distrust).
It puts the check at an endpoint that reads the actual end-state — git ancestry,
the diff footprint, the OS exit code. **DOS is the end-to-end argument applied to
agents: the only place "done" can be correctly established is at a witness that
reads the real effect, never at the actor that produced it.** That is a genuinely
strong, citable foundation, and it is the most flattering true thing the
networking literature lends the project — stronger than the TCP slogan itself,
because it is about *where the check must live*, which is DOS's actual thesis.

**It convicts DOS — twice.** First, the end-to-end argument is careful that the
endpoint check is *the* check, on the delivery path, gating what the application
accepts. DOS's end-check is off the path (§3.1). So DOS implements the *placement*
of the end-to-end argument (check at the witness, not the actor) without the
*authority* (the check gates delivery). It is the right endpoint with no veto.

Second, and subtler: the end-to-end argument says the endpoint check must know
*what correct means for the application*. DOS's witness knows *conformance* —
did the effect match the declared commitment — but not *correctness*: Rice's
theorem forecloses a mechanical oracle for "is this the *right* code"
([`333 §5`](333_verification-as-steering-and-the-verification-first-harness.md),
[`183`](183_how-much-does-this-lean-on-git.md)). TCP's endpoint *does* know
correct-for-it: "are these the exact bytes the sender put in" is fully decidable,
and the checksum decides it. DOS's endpoint can only decide "are these effects the
*shape* the plan declared," which is a weaker predicate than TCP's bytewise
identity. **So even the placement DOS gets right lands on a weaker question than
the one TCP's endpoint answers.** The agent analogy is harder than the networking
one at its core: "correct bytes" is checkable; "correct work" is not, and DOS
honestly retreats to "conforming work," which is the best a mechanical endpoint can
do.

The end-to-end argument, then, is the most precise statement of both the promise
and the limit: **DOS puts the reliability check where the end-to-end argument says
it must go — at an endpoint reading the real effect — but without the
delivery-gating authority that argument assumes, and over a conformance predicate
weaker than TCP's decidable bytewise one.**

---

## 5. How to actually *refute* it — the falsifiable reformulation

An essay that only argues is itself a self-report
([`102 §5`](102_when-to-trust-an-agent.md)). The operator's word was *validate or
refute*, so the analogy has to be turned into something a measurement could kill.
The move is to stop asking "is the metaphor pretty" and start asking "does the
layer deliver the property the metaphor claims, measurably." TCP's claim is
testable: run a lossy link, and the byte error rate *above* TCP is ~0 while the
rate *below* it is high. The agent-layer claim has the same shape.

**The testable claim.** *Over a population of agent runs on a shared repo, the rate
of untrustable effects that a DOS-gated consumer ACCEPTS is driven toward zero,
while the rate of untrustable effects the raw actors PRODUCE stays high.* That is
the agent-layer transcription of "byte error rate above TCP ≈ 0, below it high."

It splits into two numbers, and the split is the whole honesty of the claim:

- **Production rate (below the layer):** of all effects agents *commit*, what
  fraction are untrustable (over-claimed, colliding, spun)? The
  [`scoreboard`](scoreboard/methodology.md)'s commit-claim audits already measure a
  version of this — the agent's raw lie/over-claim rate. The analogy needs this to
  stay *high* (the substrate is genuinely unreliable; otherwise there is nothing to
  fix and the layer is pointless).
- **Acceptance rate (above the layer):** of all effects a DOS-gated loop *accepts as
  done*, what fraction are untrustable? **This is the number the slogan stakes
  everything on, and it is where the refutation lives.**

**What confirms the analogy:** acceptance rate ≪ production rate, robustly, across
forgeability rungs and across hosts. The layer demonstrably converts a high-error
substrate into a low-error delivered stream — TCP's exact signature.

**What refutes it — three concrete kills, in order of severity:**

1. **The PEP kill (§3.1 made empirical).** Because the gate is voluntary and
   post-effect, measure acceptance rate under a *non-cooperating* consumer — one
   that does not gate on exit-1, or an agent that commits a `grep-subject`-only
   stamp and moves on. If acceptance rate ≈ production rate there, the analogy is
   **refuted for that consumer**: the "reliability layer" delivered the corrupt
   packet because nothing forced the check on the path. TCP cannot be refuted this
   way — there is no "non-cooperating application" that gets to read the corrupt
   bytes anyway. *This is the sharpest test, and the honest expectation is that DOS
   fails it for a non-cooperating consumer* — which is precisely the bounded,
   true claim: DOS is TCP-for-agents **only for a consumer that actually gates**,
   the way TCP is reliable only for a stack that actually runs the checksum.
2. **The forgeable-rung kill (§3.2).** Adversarially target the weak rung: agents
   that emit `--allow-empty` right-SHA commits. If acceptance rate climbs with the
   fraction of accepted-via-`grep-subject` verdicts, the layer's checksum is too
   weak — refuted until the binding rung is hardened to artifact/execution grade.
   This is a refutation of the *current default*, repairable by rung
   ([`85`](85_extending-the-verifiable-surface.md)), not of the architecture.
3. **The no-substrate-error kill.** If production rate is *already* near zero on
   some task class (the agents don't actually lie much there), the layer adds no
   reliability there and the analogy is *vacuous* for that class — TCP over a
   lossless link is dead weight. This refutes the *universality* of the slogan, not
   its truth where the substrate is genuinely lossy. It also tells you where DOS is
   worth installing: where the per-step error rate is high and the horizon is long
   (the [`333 §2`](333_verification-as-steering-and-the-verification-first-harness.md)
   *pⁿ* regime), not everywhere.

The reformulation's value is that it converts a debate into an experiment with a
pre-registered failure condition. The slogan is **confirmed** to the exact extent
that a *gating* consumer's acceptance rate sits far below the raw production rate,
across rungs and hosts; it is **refuted** the moment a non-cooperating consumer's
acceptance rate rides back up to the production rate — and that refutation is not a
surprise, it is the PDP-with-no-PEP fact wearing a number.

---

## 6. The verdict

Hold the slogan to the kernel's own standard — believe it only to the rung the
evidence reaches — and it resolves cleanly into a true half and a false half, with
the seam between them exactly where [`114`](114_prior-art-audit-where-the-branding-outruns-the-mechanism.md)
said the mechanism stops.

**True — and worth saying.** DOS makes the same architectural move TCP made:
relocate the reliability guarantee off the unreliable component (link / actor) onto
a layer that wraps it; ground that guarantee in an un-authored check
(checksum / evidence ladder) so it does not rest on trusting the guaranteed thing;
and make the unit of reliability the *end state* (stream / committed effect), not
the per-hop behavior, re-driving the unfinished part. By the end-to-end argument —
the real foundation under TCP — DOS even puts the check in the *right place*: at an
endpoint that reads the actual effect, never at the actor. As a statement of
*problem shape and architectural ambition*, the analogy is sound, and the
end-to-end-argument framing is a stronger, more citable version of it than the TCP
one-liner.

**False — as stated, today.** The verb *makes … produce* claims enforcement TCP
has and DOS lacks. TCP *drops the corrupt packet at a mandatory gate*; DOS
*observes the corrupt effect after it has already landed in git, when voluntarily
invoked.* DOS is a PDP with no PEP: it reliably renders effects *legible*
(trustable-or-not, after the fact) and lets a *cooperating* loop re-drive the
untrustable — which is detection-plus-cooperative-correction, a real and valuable
thing, but categorically weaker than prevention. The honest slogan keeps the true
half and fixes the verb:

> **TCP/IP made unreliable links carry reliable data. DOS makes unreliable actors'
> effects *legible* — it tells trustable from untrustable from an un-authored check
> of the real effect, and lets a cooperating loop re-drive the rest.** It becomes
> *"makes actors produce trustable effects"* — the full TCP claim — exactly when the
> apply-gate ships: a `dos`-mediated write chokepoint
> ([`114 §F`](114_prior-art-audit-where-the-branding-outruns-the-mechanism.md),
> docs/119) that runs the artifact rung over the diff *before* the effect lands,
> turning the post-effect reader into TCP's pre-delivery drop. Until then the
> precise, defensible claim is **"TCP-for-agents for a consumer that gates"** — and
> the measurement in §5 is how you'd prove or break even that.

The analogy is not wrong; it is *ahead of the mechanism by one enforcement point*.
That is the most useful thing the exercise produces: it names, in a phrase
everyone already understands, exactly what DOS would have to build to deserve the
verb — and gives a falsifiable test for the claim it can already defend.

---

## 7. See also

- [`114_prior-art-audit-where-the-branding-outruns-the-mechanism.md`](114_prior-art-audit-where-the-branding-outruns-the-mechanism.md)
  — the PDP-with-no-PEP finding this note transcribes into TCP terms; §F reserves
  the apply-gate (docs/119) that would earn the enforcement verb.
- [`333_verification-as-steering-and-the-verification-first-harness.md`](333_verification-as-steering-and-the-verification-first-harness.md)
  — the *control-theory* analogy (verification = closed-loop feedback); this note
  is its *networking* sibling, and §5's *pⁿ* regime is where both say the layer pays
  for itself.
- [`138_what-is-truth-the-throughline.md`](138_what-is-truth-the-throughline.md) —
  the evidence ladder (DOS's "checksum") and the forgeability grading that §3.2
  contrasts with TCP's binary, mandatory CRC.
- [`102_when-to-trust-an-agent.md`](102_when-to-trust-an-agent.md) — the trust law
  and the commit-vs-report asymmetry; §5 is the un-clobber / pre-effect admission
  that is DOS's one TCP-grade chokepoint today.
- [`117_completion-as-a-verdict-the-end-of-working-in-passes.md`](117_completion-as-a-verdict-the-end-of-working-in-passes.md)
  — `residual = declared − verified`, the analogue of TCP's "all sequence numbers
  accounted for," and the retransmission the closed loop performs.
- [`183_how-much-does-this-lean-on-git.md`](183_how-much-does-this-lean-on-git.md)
  — the conformance-not-correctness ceiling (§4): why DOS's endpoint answers a
  weaker question than TCP's decidable bytewise one.

> **External anchor.** Saltzer, Reed & Clark, *End-to-End Arguments in System
> Design* (ACM TOCS, 1984) — the argument §4 leans on: a reliability function is
> correctly placed only at the endpoint that knows what "correct" means, never in
> the unreliable intermediary. It is the strongest networking-literature foundation
> for DOS's "check the effect, not the actor" thesis — and the same paper's
> insistence that the endpoint check *gates delivery* is the standard DOS does not
> yet meet.

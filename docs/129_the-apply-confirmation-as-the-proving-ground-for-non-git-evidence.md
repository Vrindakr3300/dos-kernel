# 129 — The apply-confirmation as the proving ground for non-git evidence: the counterparty-is-the-witness law, already shipped

> **[`121 §2.1`](121_first-class-on-devices-and-unattended.md) argued that git is
> one witness for one effect class and that the real un-forgeable witness for an
> outward-facing effect is *whoever received it* — the bank for a payment, the
> recipient for an email, the ATS for a job application. That is not a proposal. It
> is *already built and soaked* in the reference userland app, as the apply
> email-confirmation pipeline (`agents/ev/*`, `docs/email-verification-plan.md`):
> a job is reported `applied` only when an inbound confirmation **the ATS sent —
> a process the fleet does not control** — is joined back to the application, with
> a closed verdict vocabulary graded by accountability (A = deterministic ATS
> auto-ack · B = LLM-classified company mail · C = this ATS never emails, fall
> back to the submit-side artifact · D = unconfirmed), an observation-derived rule
> registry, a read-only advisory stance, and an independent check-the-checker
> audit. The operator stated the thesis exactly: until the email is joined, "we
> applied to N jobs" is a **one-sided claim** — a trust-the-cron failure on the
> *success* side. This note reads that shipped system as the empirical proof of
> the `EvidenceSource` seam, maps each of its disciplines to the kernel law it
> instantiates, and extracts the three lessons EV learned that 121 had not: the
> witness must be *observation-derived not guessed*, "this counterparty never
> witnesses" is itself a *required verdict* (absence of a witness ≠ absence of the
> effect), and the inbound-counterparty channel has a second use — an OTP is a
> *capability* the agent cannot forge, not a proof.**

Status: theory note + worked example, the empirical companion to
[`121`](121_first-class-on-devices-and-unattended.md) and a sibling of
[`93`](93_verifying-live-non-git-sources.md) (which shipped `drivers/ci_status.py`
as *its* one worked non-git witness). Where 93 had one CI example and 121 had a
table of hypotheticals, this note has a **production, soaked, independently-audited
fleet** doing exactly the thing — so it argues from evidence, not design. Nothing
new is built here; §6 is the extraction back into the kernel `EvidenceSource` seam
(the buildable part lives in [`121 §5`](121_first-class-on-devices-and-unattended.md)).
The userland specifics (Gmail, ATS taxonomies) stay userland; the *shape* is the
kernel's.

The job-search fleet is the reference userland app — the same one DOS was lifted
out of (CLAUDE.md). It lives in its own repo; this note references its code as a
downstream consumer, never as a dependency (the one-way arrow).

---

## 1. The setup: a fleet that reports "applied," and a claim with no second source

The apply fleet's job is to submit job applications autonomously and unattended —
the canonical [`121`](121_first-class-on-devices-and-unattended.md) deployment
(no human at submit time; the agent closest to a real, mildly-irreversible
outward-facing effect). For a long time it reported success the way every agent
reports success: from its **own** evidence. The pipeline writes `applied=True` on
a *submit-side verdict* — internally "PSV": the confirmation screenshot
(`06-confirmation.png`) plus the submit-phase transcript plus an audit row
(`docs/22_inspecting-apply-proof.md`, `docs/email-verification-plan.md`).

PSV is real evidence and it is *better than a bare self-report* — but read the
operator's own words on what it is and is not (`email-verification-plan.md`):

> "Today the system trusts the submit-side verdict (PSV artifact + audit row). The
> strongest external ground truth — the ATS or company confirmation email that
> lands in the operator's Gmail seconds-to-minutes after submit — is **not joined
> to `applications.jsonl`** anywhere in the stack. Until we close that join, 'we
> applied to N jobs' is a **one-sided claim**."

And the failure shape, named precisely:

> "a trust-the-cron failure of the same shape as AAR's silent-failure problem, but
> on the **success side**: the metric 'we applied to N' is unchallenged because
> **there is no second source**. … the operator only finds out applies vanished by
> manually scrolling Gmail and noticing that an apply they remember has no
> confirmation in the inbox."

This is [`121 §2.1`](121_first-class-on-devices-and-unattended.md) stated by an
operator who hit it in production, months before 121 generalized it. PSV is the
agent's *own* witness: it "proves the browser saw a success-shaped page," not that
the ATS queued anything. The confirmation email is the **receiver's** witness — a
process (Greenhouse, Lever, Workday, a company mailer) the fleet does not control
and cannot author bytes for. The whole EV pipeline exists to bind the second
source.

**Why this maps to "git is blind."** A job application leaves *no commit*. Git —
the kernel's whole ground-truth rung today — is structurally silent on it, exactly
as it is silent on a payment or a deploy. The apply fleet is therefore the purest
available proving ground for the non-git evidence problem: the effect is real and
outward-facing, git sees nothing, PSV is the agent-adjacent floor, and the
un-forgeable witness is the counterparty's email. If the `EvidenceSource` seam is
right, it should describe what EV already does. It does.

## 2. What EV built — the accountability-graded verdict, in production

The pipeline (`docs/email-verification-plan.md`, phases EV0–EV6, all shipped and
soaked by 2026-05-17) joins each `applied` row to inbound mail and renders a typed
verdict. The verdict vocabulary is **graded by accountability** — byte-identical in
spirit to [`93`](93_verifying-live-non-git-sources.md)'s spectrum and
[`121 §3.1`](121_first-class-on-devices-and-unattended.md)'s witness ranking:

| EV class | What it is | Accountability rung | DOS analogue |
|---|---|---|---|
| **A — ATS auto-ack** | canonical-ATS sender host + `application-received`-shape subject + inside the arrive-window + body carries the job title / req-id. **Deterministic, no LLM.** | immutable-ish third-party record (the ATS sent it; the agent can't forge it on a real inbox) | the **ORACLE** rung — a deterministic verdict on an un-forgeable artifact |
| **B — company direct** | a windowed candidate message the IRM2 classifier calls `auto_ack`/confirmation at `confidence ≥ 0.85` + body carries title/req-id | mutable third-party state, read through a fallible classifier | the **JUDGE** rung — advisory, fail-to-abstain, explicitly weaker than A (docs/87) |
| **C — never-emails (PSV-only certified)** | this `(ATS, company)` cell *never* emails (proven over the corpus); the submit-side artifact is the proof; **an empty inbox is the expected state** | the agent-adjacent floor (PSV) — *used only where the strong witness provably cannot exist* | a deliberate, **scoped** fallback to the weak rung — admissible *because* the strong witness is known-absent, not assumed-absent |
| **D — unconfirmed** | PSV says applied, but no A/B email **and** we don't know this cell never emails | *no witness found* | a **typed refusal** — `verify` returns "cannot establish," surfaced, never silently upgraded |

Three structural facts about this table are the whole lesson:

1. **It is a closed vocabulary, graded, with a "can't tell" member.** A/B/C/D is a
   `wedge_reason`-shaped enum: every application lands in exactly one class, the
   classes are ordered by how much the fleet can trust the source, and **D is a
   first-class verdict, not an error** — "class-D is the *absence* of a matching
   rule plus a missing email … It is a verdict, not a registry entry"
   (`confirmation_rules.py`). This is the kernel's "refusal is the primitive"
   (docs/82) applied to evidence: the honest "I have no second source for this"
   is a *named output*, not a crash and not a silent pass.
2. **The strong rung is deterministic; the model is the fallback.** Class A needs
   no LLM at all. Only class B — where the deterministic sender/subject rule does
   not match — calls the classifier, and even then demands `confidence ≥ 0.85`
   *and* a body title/req-id corroboration. This is **deterministic-first, judge
   second** (docs/87, the ORACLE → JUDGE ladder) — the exact discipline the
   `dos.judges` seam encodes.
3. **It is read-only and changes nothing.** "A D verdict does not re-apply, does
   not transition the application. EV is metric + digest only" (`joiner.py`). The
   pipeline *reports* the trust gap; it never acts on it. This is the
   advisory-only / propose-not-act floor ([`99`](99_runtime-validation-and-the-actuation-boundary.md))
   — the evidence layer adjudicates, a human reads the morning digest, no
   autonomous state change rides on the verdict.

### 2.1 The numbers (the gap quantified)

EV froze a baseline before any code landed (EV0, the measure-then-change
discipline). The pre-soak corpus over **275 applied rows**
(`docs/email-verification-plan.md`, EV5):

- **`application_email_confirmation_share = 0.7673`** — ~77% of "applied" rows
  carry a real inbound confirmation.
- Class histogram: **A = 73 · B = 132 · C = 6 · D = 64.**
- Class-A+B real-email share = **0.7455.**

Read D out loud: **64 of 275 applications the fleet reported `applied` had no
external witness** — a quarter of the success metric was, in the operator's term,
one-sided. EV did not "fix" those (it cannot — it does not re-apply); it made the
gap *visible and counted* where before it was invisible. That is the entire value
proposition of the evidence layer in one number: **it converts an unchallenged
success metric into a witnessed one, and names the residue.**

## 3. The disciplines EV obeys are the kernel's laws, one-to-one

This is the part that matters for DOS: EV was built userland-side, by an operator
solving a concrete pain, with no intent to instantiate kernel theory — and it
landed on **every** load-bearing kernel discipline independently. That convergence
is the evidence that the laws are real, not post-hoc rationalization.

| EV discipline (from its own docstrings/plan) | Kernel law it instantiates |
|---|---|
| "**observation-derived** — seeded from the EV0 baseline audit, **never hand-curated from a guess**" (`confirmation_rules.py`) | evidence over narrative — the rule for *what counts as a witness* is itself grounded in observed fact, not asserted (the [[project-dos-kernel-design-laws]] floor) |
| `join_application` is "a **pure function** that tests can drive without a JSONL side effect"; the event is emitted by the CLI, not the joiner | the boundary-I/O / pure-verdict split (`classify(Evidence,Policy)->Verdict`; I/O at the edge — `git_delta`/`liveness`, docs/93 §1) |
| A=deterministic, B=classifier-only-as-fallback, `confidence ≥ 0.85` + corroboration | ORACLE → JUDGE, deterministic-first, fail-to-abstain (docs/87, `dos.judges`) |
| "**Read-only.** … **No state-machine change.** … metric + digest only" | advisory-only / propose-not-act (docs/99, the actuation boundary) |
| A/B/C/D closed classes; D = "a verdict, not a registry entry" | closed verdict vocabulary + refusal-as-primitive (docs/82) |
| Per-`(ATS, company)` rules — the witness is keyed to the *specific counterparty* | the witness is the *receiver of the effect* (docs/121 §2.1) — and which receiver depends on which effect |
| EV6 "**check the checker**" — an independent verdict audit with bias-isolation (forbidden keys), advisory | the judge-of-the-judge / `judge_eval` confusion-grid discipline (docs/87–88); the referee is itself audited |
| "an **empty inbox is the expected state**" for class C | absence of a witness ≠ absence of the effect — you must *know the witness should exist* before its absence means failure (§5.2 below) |

Nothing in that right column was designed *into* EV. EV reinvented it because the
problem — trust a self-narrating process's claim about an outward effect — *is* the
DOS problem, and the disciplines are what the problem forces. **The apply fleet reads
as the kernel's thesis run as an experiment — and on this one system, every kernel
discipline converged independently.**

## 4. The OTP sub-case — the inbound counterparty channel has a *second* use: capability, not proof

The user named "email auth … not just email, but that another process we don't
control sends it." That points at a distinct mechanism EV's sibling
(`agents/inbox_otp.py`, `fetch_recent_otp`) implements, and it sharpens the law in
a way [`121`](121_first-class-on-devices-and-unattended.md) did not anticipate.

An ATS often gates the application behind an email OTP: it sends a one-time code to
the operator's inbox; the agent must read it to proceed. The agent **cannot forge
the code** — it is minted by the counterparty (the ATS) and delivered through a
channel (the operator's Gmail) the agent does not author. But notice the *use*:

- **An apply-confirmation (EV) is a witness *after* the effect** — proof the thing
  happened. It answers `verify()`.
- **An OTP is an un-forgeable token consumed *before* the effect** — a *capability*
  the agent must present to be *allowed* to act. It is closer to a lease/grant than
  to a verdict.

Same un-forgeable-inbound-counterparty channel; opposite ends of the run. This is
the [`121 §1`](121_first-class-on-devices-and-unattended.md) before/during/after
split made physical: the counterparty can author bytes the agent can't *at both
ends* — to **enable** an action (OTP, an issued credential) and to **witness** one
(the confirmation). The kernel already has both shapes — `arbitrate`/lease for
"may I act," `verify` for "did it happen" — so the `EvidenceSource` seam has a
latent twin: a **capability source** (an un-forgeable inbound grant the agent
presents), which is the authority-plane (docs safety-floor / sudo) read of the
same "the counterparty controls the bytes" asymmetry. EV's OTP path is the proof
that this twin is also real and also already shipped; naming it is future work
(§6, the open thread).

`inbox_otp.py`'s own guard-rails echo the kernel discipline anyway: a
**sender-domain allowlist** (callers "cannot poll an unfiltered inbox"), a tight
code regex so "stray phone numbers / zip codes don't leak," and a cursor that
"does not suppress results … so the apply agent's retry loop stays honest." That
last clause is the liveness/no-self-deception instinct (docs/99 §2.3) applied to a
capability fetch.

## 5. The two lessons EV learned that 121 had not

121 got the *direction* right (the receiver is the witness) but missed two things
the production system had to solve. Both belong back in the seam.

### 5.1 The witness rule must be observation-derived, not declared

121's `EvidenceSource` table reads as if you can *declare* the witness for an
effect class ("payments → the bank's ledger"). EV's hardest-won discipline says
otherwise: **what a real confirmation from `(ATS, company)` looks like is
seeded from an audit of observed mail, never hand-written from a guess**
(`confirmation_rules.py`), and the seeder even refuses to bake in a *known defect*
of the coarse baseline ("baking that defect into substrate the EV2 classifier then
has to un-learn would be wrong" — it leaves class-B `sender_hosts` empty rather
than seed a cross-attributed host). The lesson: a witness recognizer is itself a
*model of the counterparty*, and a wrong model is a forgeable rung wearing a
deterministic costume (a sender-spoof or a misattributed host passes a hand-guessed
rule). So the seam needs not just "plug in a source" but **"derive and re-derive
the source's recognizer from observation, and treat the recognizer as fallible
substrate to be audited"** — which is exactly why EV6 exists.

### 5.2 "This counterparty never witnesses" is a required verdict — absence ≠ failure

The subtle one, and the one a naïve `EvidenceSource` gets dangerously wrong. If the
seam's rule is "no witness found → abstain/refuse," then **every effect whose
counterparty simply doesn't emit a witness is permanently unverifiable** — and an
operator drowning in false D-verdicts will learn to ignore the digest (the
click-through-fatigue failure the safety-floor essay warns of). EV solves this with
**class C**: some `(ATS, company)` cells *provably never email* (established over
the corpus, `evidence_lookback_30d`), and for those "**an empty inbox is the
expected state, not a failure**" — the fleet falls back to the agent-adjacent PSV
artifact *because it has positively established that the strong witness cannot
exist here*, not because it assumed so.

This is a real addition to the seam's logic. The verdict is not binary
(witnessed / unwitnessed); it is **three-valued**:

- **witnessed** — the counterparty's record confirms (A/B);
- **expected-silent** — the counterparty is *known not to witness this effect*, so
  the weak rung is admissible and silence is not evidence of failure (C);
- **unconfirmed** — a witness was *expected and is missing* (D) — the only state
  that is actually a trust gap.

The distinction between C and D is the whole game: it is the difference between "the
bank doesn't issue receipts for this transfer type, so trust the submit artifact"
and "the bank *should* have issued a receipt and didn't — investigate." A seam that
collapses them either cries wolf (everything silent is D) or goes blind (everything
silent is C). **The kernel `EvidenceSource` must carry the `expected-silent` rung
as a first-class, observation-derived verdict** — knowing *whether a witness should
exist* is as load-bearing as reading the witness.

## 6. Extraction back into the kernel — what this hands [`121 §5`](121_first-class-on-devices-and-unattended.md)

EV is userland and stays there (Gmail, ATS taxonomies, `applications.jsonl` are
host policy — a driver, not the kernel). What the kernel should take is the
*shape*, now validated:

- **The `EvidenceSource` verdict is three-valued, not two.** witnessed /
  expected-silent / unconfirmed (§5.2). The "expected-silent" rung — *the
  counterparty is known not to witness this effect* — is the new structural
  requirement EV proves is necessary. Wire it into the seam's verdict alongside
  the floor-can-only-abstain-more discipline of [`121 §5`](121_first-class-on-devices-and-unattended.md):
  expected-silent admits the weak rung *only* on a positively-established
  known-silent fact, never on a guess.
- **An `EvidenceSource`'s recognizer is fallible substrate and must be auditable
  (§5.1).** The seam should expect a `judge_eval`-style confusion grid over each
  source (EV6 is the worked instance), and recognizers should be
  observation-derived where possible — the kernel ships the *protocol + the audit
  harness*, the host derives the recognizer.
- **`drivers/ci_status.py` and an apply-confirmation driver are two instances of
  one population.** The kernel ships the seam + the deterministic git/`fsync`
  floors; CI-status (docs/93), a generic "counterparty-confirmation" source
  (the EV shape, generalized — sender/window/corroboration → a typed
  third-party-receipt source), and an OTP-style **capability source** (§4) are
  drivers. The existing `no dos.drivers import` litmus already fences them out of
  the kernel.
- **Open thread — the capability twin (§4).** The inbound-counterparty channel
  feeds *two* kernel planes: `verify` (an un-forgeable receipt) and the
  authority plane (an un-forgeable grant the agent presents to be allowed to act).
  121 named only the first. A `CapabilitySource` seam — "an un-forgeable token,
  minted by a party the agent doesn't control, consumed before an effect" — is the
  authority-plane dual of `EvidenceSource`, and EV's OTP path is the evidence it is
  real. Worth its own note; not specced here.

## 7. What this note claims, and what it does not

- **Does claim:** the counterparty-is-the-witness law of
  [`121 §2.1`](121_first-class-on-devices-and-unattended.md) is not a proposal —
  it is shipped, soaked, quantified (77% witnessed; 64/275 unconfirmed), and
  independently audited in the reference userland app's apply-confirmation
  pipeline, which converged *independently* on every load-bearing kernel
  discipline (§3). The apply fleet is the ideal proving ground precisely because
  git is blind to a job application, PSV is the agent-adjacent floor, and the email
  is the receiver's witness (§1). EV teaches the kernel two things 121 missed: the
  witness recognizer must be observation-derived and auditable (§5.1), and
  "this counterparty never witnesses" is a required three-valued verdict, because
  absence of a witness is not absence of the effect (§5.2). The inbound channel
  has a capability twin (the OTP) the kernel has not yet named (§4, §6).
- **Does not claim:** that EV's Gmail/ATS specifics belong in the kernel (they are
  driver policy), that the apply confirmation is *sufficient* (it witnesses *that
  the ATS acknowledged receipt*, not that the application was *good* — the intent
  gap of safety-floor §6.4 persists; an A-class confirmation for a job the user
  never wanted is still a confirmed-but-unwanted effect), or that any kernel code
  is written here (the buildable seam is [`121 §5`](121_first-class-on-devices-and-unattended.md),
  now with the §6 three-valued and audit amendments).

The meta-answer: **the strongest existence proof we have for DOS's evidence model is
a fleet that never imported DOS and converged on the same shape anyway — because the moment you put
an autonomous agent in front of a real outward effect and refuse to take its word,
the only honest source left is the one the agent can't author, and the only honest
verdict set is {it happened, it can't have left a trace here, it should have and
didn't}. The apply fleet found that floor the hard way; the kernel's job is to make
it a seam every host gets for free.**

---

## References

*The shipped proving ground (userland — consumed, never depended on):*
- `agents/ev/confirmation_rules.py` — the typed per-`(ATS, company)` confirmation registry; A/B/C classes; "observation-derived, never hand-curated"; D = "a verdict, not a registry entry."
- `agents/ev/joiner.py` — the pure `join_application` verdict (A/B/C/D); "read-only … no state-machine change … metric + digest only."
- `agents/ev/audit_reconcile.py` + `agents/ev/verdict_judge.py` — EV6 "check the checker," the independent verdict audit.
- `agents/inbox_otp.py` — `fetch_recent_otp`; the capability sub-case (§4); the sender-allowlist + honest-cursor guard-rails.
- `docs/email-verification-plan.md` — EV0–EV6, the "one-sided claim" thesis, the "Flexible confirmation definition" A/B/C/D table, the 275-row baseline (0.7673; A73/B132/C6/D64).
- `docs/22_inspecting-apply-proof.md` — the PSV submit-side artifact tree (`06-confirmation.png` the hero) — the agent-adjacent floor EV complements.

*The kernel frame this is the empirical companion to:*
- [`121_first-class-on-devices-and-unattended.md`](121_first-class-on-devices-and-unattended.md) — §2.1 (the receiver is the witness; git is blind), §3.1 (the witness spectrum), §5 (the `EvidenceSource` seam this note amends with the three-valued verdict + audit requirement).
- [`93_verifying-live-non-git-sources.md`](93_verifying-live-non-git-sources.md) — the accountability spectrum + `drivers/ci_status.py`, the *other* worked non-git witness; EV is its second, larger instance.
- [`87_the-adjudicator-trust-ladder.md`](87_the-adjudicator-trust-ladder.md) — ORACLE → JUDGE (A deterministic, B classifier-as-fallback); `judge_eval` is EV6's analogue.
- [`99_runtime-validation-and-the-actuation-boundary.md`](99_runtime-validation-and-the-actuation-boundary.md) — advisory-only / propose-not-act (EV's "metric + digest only").
- [`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md) — refusal-as-primitive (D is a named verdict, not an error).

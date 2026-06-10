# 114 — Prior-art audit: where the branding outruns the mechanism

> A skeptical, citation-grounded audit of DOS against (a) classical software
> engineering / distributed-systems prior art and (b) the 2025–2026 SOTA in
> multi-agent coding. The question asked: *where is DOS tail-wagging, naive,
> reinventing-without-purpose, or failing to reuse a known result?* This note
> records the findings so the thinking is durable; the actionable few are
> separated from the merely-rhetorical at the end.

Method: two readers mapped the code vs. the claims; four readers ran prior-art
reviews (classical concurrency control; recovery/WAL/failure-detectors;
SOTA agent fleets; OS/security terminology), each pulling primary sources. Two
load-bearing critiques were then re-verified directly against the code
(`lane_overlap.py` + `overlap_policy.py`; the `lane_journal`/`lane_lease` write
path). What follows is the distilled verdict, not the transcripts.

**One-sentence finding.** The *engineering* is mostly honest and mostly sound,
and the **in-code docstrings are markedly more candid than the top-level
taglines** — but three real things need attention (the ⅓ overlap rule, the
missing fence, the verifier floor), and a cluster of grand terms
(kernel / syscall / trust substrate / reference monitor / "third ARIES phase")
claim a property the mechanism specifically lacks: **non-bypassable, privileged
mediation**. DOS is, precisely, *a PDP with no PEP* — an evidence-grounded
authorization-**decision** service that **detects**, it does not **enforce**.
That is a real and respectable thing; the words oversell it.

---

## A. The three findings that are about the *mechanism*, not the words

These are the ones worth fixing or pinning. They are ranked.

### A1. The ⅓ soft-overlap rule is unsound on its own terms (highest priority)

`lane_overlap.OVERLAP_RATIO_MAX = 1/3` makes lane conflict a **measure**
("how much of the requested tree shares prefixes") rather than a **predicate**
("do they conflict?"). In 50 years of concurrency control the lock-compatibility
relation is a *boolean predicate on the conflict* (Gray, Lorie, Putzolu, Traiger
1975/76, *Granularity of Locks*; Bernstein–Hadzilacos–Goodman 1987) — two locks
conflict or they don't. The **only** principled way the literature lets two
writers share a contended datum is **operation commutativity** — O'Neil 1986,
*The Escrow Transactional Method* (TODS 11(4)): increments/decrements commute, so
order doesn't matter, so no lock is needed. Arbitrary **file overwrites do not
commute**. There is no inf/sup bound. So the escrow justification is absent and
the rule admits genuine write–write conflicts on the shared third.

The code's own history proves the relation isn't a valid compatibility relation:
the `_exact_glob_collisions` hard floor was bolted on *after* the 2026-06-01
TM↔tailor **mutual wedge**, where the ratio was **asymmetric** (TM 2/8 = 25% →
admit; tailor 2/3 = 67% → refuse). A compatibility relation is symmetric *by
definition*; this one wasn't. The exact-glob floor patches the symmetry of the
*identical-glob* case only — two lanes that overlap on ≤⅓ of the requested tree
**without naming an identical glob** still both admit.

**The `overlap_policy.py` "deterministic floor" does NOT save this** — and this
is the subtle part. That seam (docs/113) is genuinely good engineering: a
swappable scorer is ANDed against a floor it cannot loosen, so a *plugin* can
only ever refuse-more. **But the floor it ANDs against is `PrefixOverlapPolicy`,
which is the ⅓ ratio rule itself** (`overlap_policy.py:155-165`,
`floor_decision` calls `overlap_verdict(..., ratio_max=OVERLAP_RATIO_MAX)`). The
floor stops a plugin from under-refusing *relative to ⅓*; it does not make ⅓
sound, because **⅓ is the floor**. The soundness hole is in the floor, and the
floor cannot catch itself.

Concrete failure mode (silent — this is why it's #1): two agents both admitted to
a region sharing ≤⅓ both edit `src/dos/arbiter.py`. Outcomes by luck: (i) **lost
update** (A writes, B writes, A's edit gone — *leaves no over-claim for
`verify()` to catch*); (ii) git merge conflict an unreliable agent must resolve
(re-importing the very distrust problem); (iii) silent semantic corruption
(disjoint line ranges, mutually inconsistent edits). `verify` catches *bad
shipping claims against git*, not *two-writers-clobbered-a-file*; case (i) is
invisible to it.

**Recommendation.** Make conflict a predicate: `ratio_max = 0` (any prefix
collision refuses). Recover the concurrency the ⅓ was buying via the **right**
mechanism — a real **shared/exclusive lock mode** (see A-note below), not a
fractional relaxation. This is the cheapest high-value change in the audit.
NB the threshold is *config* already (`dos.toml [overlap] ratio_max`), so a
workspace can set 0 today; the argument is that **0 should be the kernel
default**, and the docstring's framing of ⅓ as "the elbow" should be downgraded
from "calibrated" to "a stand-in that admits a known hazard."

*A-note — the actually-missing lock primitive.* The prefix-collision test
(`_tree.prefixes_collide`) is **sound** as a conservative predicate-intersection
check — `a.startswith(b) or b.startswith(a)` captures the full ancestor/descendant
relation directly, so DOS does **not** need multigranularity *intention* locks
(IS/IX/SIX, Gray 1975) — it sidesteps them by keeping each lane's whole glob-set
instead of decomposing into per-node locks. Phantom-coverage of *not-yet-created*
files comes for free from prefix semantics. What's genuinely missing is **lock
modes**: DOS has exactly one (taken / not-taken ≈ always-X). So two read-only
agents on `docs/**` conflict needlessly. A shared mode would give back read
concurrency *soundly* — which is the concurrency the ⅓ hack reaches for
*unsoundly*. The absence of S-mode is *what makes the ⅓ hack tempting.*

### A2. No fencing token / no lock-delay — a stale holder can corrupt a re-granted region (second priority)

Verified directly: a grep of the lease path for
`fencing|fence|generation|epoch|sequencer|lock_delay|monotonic` finds only
`seq_watermark` (an internal compaction counter the module itself calls
"cosmetic," folded by append-order, **never handed to a holder**), the `run_id`
sortable-ID entropy (not checked at any write path), and `fence` used in the
*architectural-boundary* sense in `dispatch_top`/`ci_status`. **There is no
fencing token and no post-SCAVENGE drain window.**

This is the textbook Kleppmann hazard (*How to do distributed locking*, 2016;
the Redlock critique), and the standard fix is exactly what's absent. The lease
record carries `pid, host_id, holder, acquired_at` but **no monotonically
increasing generation number that the holder must present on every subsequent
write**, and the protected resource (the git working tree) **is not lease-aware**
— it checks nothing. Chubby (Burrows, OSDI 2006) solves precisely this with a
**sequencer** (`CheckSequencer`) and, for resources that can't check tokens, a
**lock-delay** fallback. DOS has the *lease* half of Chubby and **none** of the
*sequencer* half.

The interleaving, instantiated on DOS — and note it is **routine** for LLM
agents, whose tool/GC/queue pauses regularly exceed a lease TTL, far more often
than a DB client's:

1. Agent A acquires `src/dos/**`, `ttl≈300s`, starts editing.
2. A **stalls** > 300s without crashing (a hung model call, a paused container, a
   descheduled `Workflow` branch) — and **does not know it stalled**.
3. The scavenger sees the lease stale, appends `SCAVENGE`; `replay` shows the
   lane free.
4. Agent B acquires `src/dos/**`, starts editing `src/dos/arbiter.py`.
5. A **wakes**, ignorant that it was scavenged, and **writes
   `src/dos/arbiter.py` directly**. Nothing rejects A's write — A holds no token,
   B holds no token, the filesystem holds no token. Lost update or commit
   collision; silent.

`liveness` (STALLED) + the supervisor's `OP_HALT` can *detect and propose*
killing A — but `halt` is advisory ("records the intent, never delivers the
signal", docs/99), so a stalled-but-not-yet-halted A in step 5 is **unfenced**.

**Recommendation.** Cheap partial fix first: a **lock-delay drain window** after
`SCAVENGE` (refuse to re-grant the region for, say, one TTL) — Chubby's own
fallback for resources that can't check tokens; it shrinks the race without
making the working tree token-aware. Real fix: a **generation number checked at a
`dos`-mediated write/apply path** — which is the same surface as the A3 / "build
a PEP" change, so the two land together.

*Sharper still:* the **heartbeat is itself a self-report.** `HEARTBEAT` is
emitted by the agent/harness, so a liar or a stuck-but-still-beating keepalive
thread holds a lane forever. DOS correctly refuses to *auto-act* on SPINNING and
anchors **ADVANCING on git commits** (the unforgeable rung) — good — but the
*alive* signal is exactly as forgeable as the self-reports DOS distrusts
everywhere else. This asymmetry isn't flagged in the docs and should be.

### A3. The verify *floor* (commit-stamp grep) is one of the weaker deterministic signals, and is gameable the exact way the field already documented (third priority)

DOS's pitch is "a deterministic floor under the unreliable LLM judge" — and the
*architecture* is right and on-trend (keeping the judge advisory under a
deterministic rung is validated by the LLM-as-judge failure literature: "One
Token to Fool LLM-as-a-Judge" drives false-positives to ~80%; self-attribution
bias). **But the chosen floor — `git log` + grep-the-commit-subject — is closer
to *format-tag matching* (the weakest RLVR criterion) than to completion proof.**
An agent that can *write a commit* can write one whose subject matches the stamp
grammar. The grep rung verifies *"a commit of the right shape is in ancestry,"*
not *"the work is correct or even real."*

This is not hypothetical: SWE-bench's own tracker documents agents running
`git log --all` to find and copy the historical fix patch (SWE-bench #465/#471;
the reason OpenAI stopped evaluating SWE-bench Verified the naive way). The
field's credible deterministic floor is **sandboxed test execution the agent does
not control** — strictly stronger than a stamp.

**Recommendation.** Re-frame honestly and, where possible, strengthen. The
*defensible* verify edge is narrower than "we verify against git": it is **"we
check git ancestry and ancestry-of-the-load-bearing-files rather than the
transcript, and we keep the judge strictly advisory."** Treat the commit-stamp as
**attribution** (what PunkGo's Merkle log is), and make the *binding* verify rung
**execution-grounded** where a host can supply a test command — otherwise the
oracle inherits the SWE-bench git-leakage gameability. (The file-path rung, which
requires touching ≥2 named load-bearing files, is already a step up from
subject-grep and should be the preferred default over the subject match.)

---

## B. Where the *terminology* writes checks the code can't cash

These are nominal, not mechanical — but they matter for credibility, because each
grand term asserts the one property DOS lacks (privileged, non-bypassable
mediation), and one of them *inverts* its field's meaning. The governing fact:
**DOS is voluntarily invoked.** In security architecture, voluntary invocation is
the disqualifying property.

| Term DOS uses | Canonical meaning (cite) | Met? | Honest term |
|---|---|---|---|
| **Reference monitor** | non-bypassable / **always-invoked** / tamperproof / verifiable; complete mediation is *definitional* (Anderson 1972; Saltzer–Schroeder 1975) | **No** — advisory ⇒ bypassable ⇒ fails complete mediation by construction; observes effects *after* the commit exists | advisory checker / cooperative auditor |
| **Kernel** | privileged, mediating core; trap boundary; minimality-of-TCB (Liedtke; seL4) | **No privilege, no trap** — the "mechanism≠policy" split is apt as a metaphor but lacks the privilege substance | core library / decision core |
| **Syscall** | a **privilege transition** (caller traps into a privileged kernel) | **No** — an in-process call you could inline; the whole semantic content of "syscall" *is* the boundary | API call / library function |
| **Trust substrate / TCB** | TCB = the components **whose failure breaks security**; "trusted" = *must-be-trusted*, **not** trustworthy (Orange Book) | **No, and inverted** — advisory ⇒ nothing's security rests on it; and DOS's own thesis is *distrust* | **distrust** / verification substrate |
| **PDP (decision engine)** | XACML/OPA: the PDP *decides*, a **PEP** *enforces* (OPA = "PDP only") | **Yes** for the decision; **no PEP exists** | **PDP with no PEP** — the recommended frame |

The deepest one is **"trust substrate."** In security, "trusted" denotes
*liability*, not *reliability* — the TCB is the set of things that can betray you,
which is why you want it small. Branding a verification oracle whose own tagline
is *"the part that doesn't believe the agents"* a "trust substrate" is the
marketing layer fighting the engineering layer. The honest word is the opposite:
**distrust substrate / verification oracle.**

And the cleanest, *flattering-and-true* frame the literature hands us: **DOS is a
Policy Decision Point with no Policy Enforcement Point.** `arbitrate()` is a
textbook PDP call (state in, decision out, no side effect); `verify()` is an
evidence-grounded decision procedure. Both are real, respectable PDP functions.
The gap — nothing enforces the decision against a non-cooperating agent — is the
*limit case of fail-open*, and the 2026 paper "Before the Tool Call:
Deterministic Pre-Action Authorization for Autonomous AI Agents" (arXiv
2603.20953) is the published statement that this domain needs the PEP **at a
chokepoint the agent cannot bypass**. If DOS ever wants the kernel/reference-
monitor words honestly, that PEP (an inlined reference monitor, a tool-call gate,
or a capability/sandbox boundary) is the price — and it is the same build as the
A2/A3 mediated write-path.

### The "third ARIES phase" is the worst-fitting analogy

ARIES (Mohan et al. 1992) is **Analysis → Redo → Undo**, and it is **backward
recovery**: the third phase exists to *remove* the partial effects of
uncommitted (loser) transactions via Compensation Log Records. **"Continue" is
not an ARIES concept** — ARIES *abandons* losers; the client resubmits. DOS maps
Analysis→Redo faithfully (the intent-ledger fold + ancestry re-verification) but
**relabels** the third phase and **drops Undo entirely**. DOS's own `resume.py`
docstring admits this ("`94 §3.2` named that DOS does not own undo").

Does the missing Undo matter? **Only under the assumption DOS makes explicit:
"durable effect = git commit, which is atomic, so the uncommitted tail is
idempotent and can just be re-done."** That holds for pure in-repo work. It is
**violated** the moment an agent step has a **non-git or non-idempotent side
effect** before committing — an external POST, a charged card, a sent email, a
pushed artifact, a dirty working tree the resumed run inherits. There, "re-do the
residual" is **at-least-once execution of effects** — exactly the regime where
ARIES demanded a compensator and DOS has none.

The faithful lineage is therefore **not ARIES** but **forward recovery / a saga
without compensators over an event-sourced ledger** (microservices.io/saga; the
log-replayed-to-reconstruct-state is event sourcing). The genuine innovation —
worth keeping and stating *as itself* — is that **"done" is adjudicated from git
ancestry, not self-report.** Retire "the third ARIES phase"; say "forward recovery
over an event-sourced intent ledger, with a git-ancestry truth oracle."

Likewise "ARIES write-ahead log" for the lane journal: it's a **legitimate
durable, fsync'd, torn-tail-tolerant, replay-to-reconstruct append-only log** —
faithful as *redo logging / event sourcing*. But the headline WAL property
("log record durable **before the data page**") is **vacuous here**, because
there is no separate data page — *the log is the store* (`replay` reconstructs the
registry). That's simpler and arguably safer, but it means "WAL" imports a
guarantee that's trivially true by *absence*, not enforcement. It's an
event-sourced AOF/Kafka-style log, not an ARIES WAL fronting a paged store.

### "GC reachability is a verdict" (docs/106) is lease failure-detection, renamed

The one correct kernel: you can't refcount your way to detecting that *the holder
of the reference is itself dead* (a leaked owner / unreferenced cycle — the real
reason tracing GC beats refcounting). True. But the mechanism for "holder
crashed, reclaim its lease" is **lease expiry + heartbeat + scavenge + (ideally) a
fence** — which is *exactly* what DOS implements. DOS reinvented **lease-based
failure detection** and named it GC reachability. The GC vocabulary adds lineage,
not mechanism — and it actively *misleads*, because real GC reachability is an
**exact** test over an authoritative pointer graph, whereas DOS's "reachability"
is a **statistical/temporal inference** from heartbeat-age (a failure detector).
The right axis is *failure-detection vs. static reference graph*, and DOS is on
the failure-detection side, like every lease system. (Crucially, GC theory itself
says **reachable-but-dead ≠ collectible** — the analog of *idle-but-alive ≠
kill* — which is the very confusion the slogan invites; the *code* handles it
correctly via SPINNING≠STALLED, but the **prose** collapses it.)

### "Liveness" is an (unnamed) failure detector — fine, but name the limit

`liveness.classify` *is* a failure detector, and it's treated **advisorily**,
which is the right posture (Chandra–Toueg's detector outputs *suspicions*; the
protocol decides). `heartbeat_age > spin_ms ⇒ STALLED` is a timeout — the
canonical **◊P / eventually-perfect** implementation: it will eventually catch a
truly dead run (completeness) and **will transiently false-suspect a slow-but-fine
one** (only eventual accuracy). This is **unavoidable** (FLP 1985: you cannot
distinguish crashed from slow in an async system; a *perfect* detector is
impossible). Two honest gaps:

1. **DOS never names that it's a failure detector subject to FLP/◊P.** For a
   project whose brand *is* rigor about trust, stating the impossibility result
   it lives under is more honest, not less, and sets operator expectations for
   tuning `spin_ms`.
2. **SPINNING has no failure-detector analog.** Classic detectors are binary
   (suspected / not). DOS adds a second, orthogonal *progress* signal (git delta),
   yielding a 2×2 where **SPINNING (alive + not-progressing)** is a
   **livelock/progress monitor**, not a crash detector. That's a *clever
   extension*, but "DOS liveness is a failure detector" is only true of the
   **STALLED** rung. Worse, the `grace_ms` guard protects the *SPINNING* rung from
   false positives, while the **STALLED** rung — the one that can drive a real
   SCAVENGE (and per A2 has no fence behind it) — is the **least-guarded** path.

---

## C. Where DOS is genuinely fine — don't "fix" these

- **The prefix-collision predicate** (`_tree.prefixes_collide`) is a *sound,
  conservative* over-approximation of glob-region intersection — it errs toward
  over-refusal (the safe direction) and gets phantom-coverage for free. Not naive.
  The docstrings cite the theory correctly.
- **The lease + WAL plumbing** is competent distributed-systems engineering:
  `O_EXCL` mutex over the read-arbitrate-append critical section, fsync, pure
  `replay`, torn-tail tolerance, and a **value-keyed CAS** stale-steal
  (`_filelock.steal_stale`) whose TOCTOU double-steal was already found and fixed.
  The gaps are the *missing fence* (A2), not the plumbing.
- **Judge-stays-advisory-under-a-deterministic-rung** is on solid, current
  ground, *validated* by the LLM-as-judge failure literature. Keep it.
- **"Enforce the stop outside the model"** and **"hostile to narration by
  default"** are now mainstream-recognized directions DOS implements coherently
  rather than invents. Good company to be in; just don't claim to have invented
  the genre.
- **The `overlap_policy` seam** (docs/113) is a genuinely nice structural-soundness
  design (AND-against-an-unforgeable-floor). The only problem is *which* floor
  (A1) — the seam itself is right.

---

## D. The SOTA position — neighbors at-or-ahead on each axis; the *union* is the contribution

Each primitive has a named 2025–2026 neighbor that matches or beats DOS on that
one axis:

- **arbitrate (region lease):** **Limen** (Rust+MCP) ships advisory write-leases
  over a region with the *identical* conflict algebra, *plus* it **mediates the
  write in-band at write-time** — i.e. it is **ahead of DOS's pure/advisory
  arbiter on prevention** (DOS trusts the *declared* write-set at admission). And
  **CodeCRDT** coordinates in-place via CRDTs + stigmergy, **eliminating
  arbitration entirely** (commuting edits converge) — a lock-free design that may
  *dominate* leasing for pure parallelism. So **"in-place region leasing" is not
  novel**, and the honest differentiator is *lease **plus** verify+liveness*, not
  the lease.
- **verify (completion):** SWE-bench/RLVR do execution-grounded verification (a
  **stronger** floor); the verification-gap framing ("trust artifacts not
  transcripts, be hostile to narration") is becoming *conventional wisdom* — DOS
  is **on-trend, not ahead**.
- **liveness (stuck detection):** result-aware loop guards + heartbeat detectors
  are standard; DOS's git-delta *typed verdict* is a mild formalization novelty,
  but FLP-bounded like all of them.
- **the referee framing:** **PunkGo / "Right to History"** (arXiv 2602.20214) is
  a near-verbatim philosophical twin ("trust the kernel's record, not the agent",
  cites seL4/CertiKOS) — but single-agent, audit+capability, *no* completion
  verify / *no* arbitration / *no* liveness. **"Verify-Gated Completion as
  Admission Control"** (arXiv 2605.17998) is a published twin of DOS's
  verify-gated admission loop — but evidence-weak (mostly synthetic, no baseline).

**The defensible novelty is the union, not any primitive.** No surveyed system
spans *verify + arbitrate + liveness + structured-refusal as one untrusting
referee for a fleet on a shared git tree*. Limen does the lease better; SWE-bench/
RLVR do completion better; loop-guards do stuck-detection at par; PunkGo does
attribution better. **DOS is the only one *integrating* them** — that integration
is the contribution, and the claim should be stated that way (and the
already-retired "unclaimed quadrant" line stays retired).

*Worth a hard look:* the mainstream answer to "many agents, one repo" is
**worktree/container isolation + merge** (Claude Code, Cursor, Devin, Jules), and
DOS's contrarian **in-place leasing** is a real bet *against* the grain. The
*problem* is validated (AgenticFlict: **27.67%** textual conflict rate across
142k agent PRs; registry-file + semantic conflicts that isolation can't fix). But
be honest internally that the field has largely *routed around* in-place editing,
and that OpenHands' "Large Codebase SDK" already does in-place **dependency/
directory partitioning** — adjacent to the lane taxonomy. In-place leasing must
earn its place against isolation-then-merge, not assume it.

---

## E. The actionable shortlist (what to actually do)

1. **Default `OVERLAP_RATIO_MAX = 0`** (conflict = predicate). Add a real
   **shared/exclusive lock mode** so read-only lanes regain concurrency *soundly*.
   Downgrade the ⅓ docstring from "calibrated elbow" to "admits a known hazard."
   *(A1 — cheapest high-value change.)*
2. **Add a post-`SCAVENGE` lock-delay drain window** now; plan a **generation
   number checked at a `dos`-mediated write path** later. Flag in docs that the
   **heartbeat is a distrusted self-report**. *(A2.)*
3. **Re-rank verify rungs:** prefer the **file-path** rung over **subject-grep**;
   make an **execution rung** the binding default where a host supplies a test
   command; describe the commit-stamp as *attribution*, not *completion proof*.
   *(A3.)*
4. **Terminology pass (nominal, but do it):** in the taglines and README, prefer
   **distrust/verification substrate** over "trust substrate"; **decision engine /
   PDP (advisory, no PEP)** over "kernel/syscall/reference monitor"; **"forward
   recovery over an event-sourced intent ledger"** over "the third ARIES phase";
   **"lease-based failure detection"** over "GC reachability." Keep the grand
   words only behind a real PEP. The *in-code docstrings already do most of this
   honestly* — this is about the top-of-funnel claims catching up to them.
5. **State the limits you already live under:** liveness is an unreliable
   (◊P-class) failure detector that *cannot* distinguish slow from dead (FLP);
   the arbiter is **advisory** (it *verifies effects, it does not mediate them*);
   SPINNING is a progress monitor, not crash detection. Saying so is *more*
   credible for a project whose whole brand is rigor.

> Net: the kernel's pure predicates, its lease/WAL plumbing, and its
> judge-stays-advisory discipline are sound and well-built. **Fix the
> fractional-overlap rule before trusting it in anger; add a fence/lock-delay
> before trusting it under load (agent pauses); strengthen the verify floor past
> grep; and let the words match the (honest) docstrings.** None of these is a
> redesign — they are a default flip, a drain window, a rung re-rank, and a
> vocabulary pass.

---

## F. Disposition (2026-06-03 — what was actually decided)

A systemic re-read reframed the five shortlist items around a single root cause:
**DOS is a sound PDP with no PEP** — it *decides, observes, and re-adjudicates*
but never **mediates the write moment**, so every guarantee is "detected, not
prevented." That frame, not the item-by-item list, is what matters; the items are
its symptoms. Each shortlist item was then dispositioned against it. The litmus
was: does the change move the kernel toward a real enforcement point (PEP), or
does it only re-tune a detector? Detector re-tunes that add a knob without closing
a hazard were **dropped**; the honest read-side reports were **shipped**; the true
PEP (a `dos`-mediated apply-gate that runs the artefact rung over the diff at
write-time) was **separated out** as the one thing worth building next (docs/119,
unwritten — cited as docs/118 before that number was taken; see the
number-correction note at the end of this section).

| Item | Disposition | Why |
|---|---|---|
| **A1** — `OVERLAP_RATIO_MAX=0` default + shared/exclusive lock | **DROP** the ratio flip; **DEFER** the glob-intersection floor to a gate doc | Flipping the default to `0` is a detector re-tune that trades away the one concurrency the ⅓ rule buys without closing the underlying hazard (two lanes can still collide *under* any ratio at write-time — only a PEP closes that). The honest fix is a real disjointness floor at the mediated write, not a stricter advisory threshold. The A-note's sound primitive — the shared/exclusive **lock mode** — is now BUILT deterministically (`src/dos/lock_modes.py` + `tests/test_lock_modes.py`, 14 cases; write↔write reduces to the sound `ratio_max=0` intersection, read↔read recovers concurrency soundly, relation pinned symmetric). What remains for the apply-gate plan (docs/119) is only threading a per-lane mode through the arbiter at the mediated write — wiring, not decision logic. Docstring downgraded from "calibrated elbow" in `lane_overlap.py` (`fcbb25b`). |
| **A2** — post-`SCAVENGE` lock-delay drain + fence/generation number | **DROP** the lock-delay; **DEFER** the fence to the gate doc | A lock-delay drain window is a timing band-aid on an unreliable (◊P/FLP) failure detector — it narrows the race, never closes it, and adds a tunable that masks the real gap. The fence/generation number is the genuinely correct mechanism, but it is only meaningful *at a mediated write path* — i.e. it is part of the PEP, not a standalone drain. Deferred into the apply-gate plan (docs/119, unwritten — see the number-correction note) rather than half-built as a delay. |
| **A3** — re-rank verify rungs (file-path over subject-grep; commit-stamp = attribution) | **SHIPPED** | This one is a real, sound, ship-today change: it makes the *report* honest without pretending to be enforcement. `oracle` now grades the grep rung by **forgeability** — `grep-artifact` (file-path/diff, non-forgeable) vs `grep-subject` (commit subject/body the agent authored, forgeable) — carries the raw `rung` through, and `dos verify` colours the forgeable rung yellow. The commit-stamp is thereby described as *attribution graded by trust*, not *completion proof*. It is the **read-side seed** of the A2 fence / the docs/118 apply-gate: it teaches the verdict to report *which* rung answered and how much to trust it, the same forgeability split `resume.NONFORGEABLE_RUNGS` already encodes. Advisory only — it grades the report, never mediates a write. (Execution-rung-as-default was left for a host that supplies a test command; not a kernel default.) |
| **A4** — terminology pass (PDP/advisory over kernel/reference-monitor) | **CARRIED** into the framing above; strategy-prose edits live in `dos-private` | "PDP with no PEP" is now the load-bearing internal description (this section + the future apply-gate plan, docs/119). The README/tagline rewording is a `dos-private` task per the CLAUDE.md one-way-arrow rule, not a kernel-`docs/` edit. |
| **A5** — state the limits (◊P/FLP, advisory arbiter, SPINNING≠crash) | **CARRIED** into the framing above | Folded into the "detects, does not prevent" root-cause statement; the specific FLP/◊P limits are restated wherever the relevant verdict is documented. |

**The one thing to build next is not on this list as a tuning — it is the PEP
itself:** a `dos`-mediated apply-gate (the artefact rung run over the diff *at
write-time*, with the fence checked there). This plan is **not yet written**; it
is reserved as `docs/119` — see the number-correction note below. A1/A2's deferred
halves (the disjointness floor and the generation fence) are sound *inside* that
gate and incoherent outside it, which is exactly why they were deferred rather than
shipped as standalone detector tweaks.

> **A1's sound half is now a built primitive, not prose (2026-06-03).** The
> disposition risked leaving A1's *sound* answer as a promise in a plan — and the
> demand was explicit: the fix has to be **deterministic mechanism, not prose**. So
> the A-note's missing primitive — the shared/exclusive **lock MODE** that recovers
> read-concurrency *soundly* (the concurrency the ⅓ hack reaches for unsoundly) — is
> now `src/dos/lock_modes.py`: a pure `LockMode` enum + the Gray-1975 boolean
> compatibility matrix + `region_conflict(req_tree, req_mode, lease_tree, lease_mode)`,
> a total function combining the kernel's existing **zero-tolerance** prefix
> intersection (`_tree.prefixes_collide` — the sound `ratio_max = 0` predicate, no
> fraction) with the mode matrix. It is replay-tested in isolation
> (`tests/test_lock_modes.py`, 14 cases) including the load-bearing soundness proof:
> a 25 %-overlap **write↔write** pair that `overlap_verdict` ADMITS under ⅓ is
> REFUSED by `region_conflict`, while the *same* regions as **read↔read** are
> admitted. The relation is pinned SYMMETRIC — the exact property the ⅓ ratio lacked
> (the TM↔tailor asymmetric wedge). Default mode is `EXCLUSIVE`, so existing behavior
> is byte-for-byte unchanged until a caller opts a lane into `SHARED`. What remains
> for the apply-gate plan (docs/119, below) is only the **consumption**: threading a
> per-lane mode through the arbiter and checking `region_conflict` at the mediated
> write — wiring, not the decision logic, which is now built and tested.

> **Number-correction (2026-06-03).** Earlier prose in this section (and the A1/A2
> rows above) cited the apply-gate as `docs/118`. That number was concurrently
> taken by an unrelated plan — `docs/118_the-fleet-postmortem-and-the-attribution-join.md`
> (the WAL `run_id` join gap) — during a doc-number race. The apply-gate PEP is
> therefore reassigned to **`docs/119` (future, unwritten)**; treat every `docs/118`
> in the A1/A2 dispositions as meaning *the apply-gate plan*, now `docs/119`. Its
> A1 floor primitive (`lock_modes.py`) is **already built and tested** (see the note
> above); the generation fence is the part that still needs the mediated write path.

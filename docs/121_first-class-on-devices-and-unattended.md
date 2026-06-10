# 121 — First-class on devices and unattended: where the kernel matters most and is supported least

> **DOS is the part that doesn't believe the agents. That part matters in
> proportion to two things: how far the agent's effects reach before anyone
> looks, and how absent the human is when it decides. A coding agent in a
> reviewed PR loop scores low on both — there is a human, and the blast radius is
> a diff. An agent running *on a device*, *unattended*, scores maximal on both:
> it is closest to real-world effects, unobserved for the longest interval,
> sometimes offline for all of it, with no human reachable at decision time. So
> the kernel is *most* necessary exactly in the deployment it currently supports
> *least* — because its two trust primitives both quietly assume a capable host:
> the non-forgeable rung is `git` (a `subprocess`), and the durability floor is an
> `fsync`'d POSIX JSONL file. The deeper of the two is the git one, and it is not a
> device bug — it is a flaw *everywhere*: git is one witness for one effect class
> (a committed source change), and it is **blind to almost everything an autonomous
> agent actually does** (send a payment, an email, a deploy, an actuation), whose
> un-forgeable witness is *the receiver of the effect*, not git. The device just
> removes the camouflage. This note separates the two axes the prompt fuses
> (unattended = supervision; on-device = topology), shows git-centrism is the
> load-bearing limitation, and shows the fix is not a new subsystem but the *same
> seam move* the kernel already made three times (judges, overlap, log-sources):
> lift "ground truth" and "durable log" from hardcoded `git`/`fsync` into seams
> whose deterministic floor can only refuse-more, never trust-more — which is
> docs/93's accountability spectrum made into a kernel seam.**

Status: theory + spec note, in the family of [`79`](79_primitives-not-features.md),
[`82`](182_the-kernel-is-a-taxonomy-of-refusal.md),
[`94`](94_checkpoints-and-recovery-from-slop.md),
[`99`](99_runtime-validation-and-the-actuation-boundary.md),
[`117`](185_native-log-adapters-and-the-actor-witness-split.md). §1–§4 are the argument (what the two axes
are, which assumption breaks, why the kernel matters more here). §5–§7 are the
buildable spec (the `EvidenceSource` seam, the `DurableLog` seam, the
reconnection adjudication). §8 steelmans the objection that a device should carry
no kernel at all. Nothing here is built; the litmus tests in §9 are the gates.

The positioning half — *why edge/unattended is a market a trust kernel should
own, and who buys it* — is a [`dos-strategy`](../../dos-strategy) concern and is
deliberately not argued here (CLAUDE.md: how-a-module-behaves → `dos/docs`;
why-it-matters → `dos-strategy`). This is the mechanism half.

---

## 1. Two axes, fused in the prompt — pull them apart first

"First-class for agents that run on devices and/or unattended" is one phrase over
two orthogonal axes. Conflating them is the first mistake, because DOS sits at
*opposite ends* of each:

| Axis | Question it asks | Where DOS is today |
|---|---|---|
| **Supervision** (*unattended*) | Is a human in the loop **at decision time**? | **Deep.** `liveness` (the interval verdict), `loop_decide` self-stop ([`99 §4`](99_runtime-validation-and-the-actuation-boundary.md)), the `halt` propose-not-signal boundary verb ([`99 §5`](99_runtime-validation-and-the-actuation-boundary.md)), the watchdog driver (docs/101), `resume` (the ARIES third phase, docs/107), the decisions queue. The kernel was *built* for the no-human-watching case. |
| **Topology** (*on a device*) | Where does the agent **physically run** — datacenter or edge? | **Shallow.** Every trust primitive assumes a capable host: a `git` binary, a `fork`able `subprocess`, a POSIX filesystem that honours `O_APPEND` + `fsync`. None of those is guaranteed on a phone, a robot, an embedded controller, a browser sandbox, or an ephemeral function. |

They correlate — a device agent is *usually* unattended — but they are not the
same axis, and the correlation hides the gap. Almost everything the kernel has
shipped for "autonomy" lives on the **supervision** axis (no human → the kernel
must adjudicate instead of deferring). The **topology** axis is nearly
untouched, and it is the one that actually breaks the implementation.

So the honest decomposition of the prompt is:

1. **Unattended is mostly *consequences*, not new mechanism.** The verdicts
   exist; the work is making the *defaults* fail safe when the human who would
   drain a queue or break the B5 glass is structurally absent (§4).
2. **On-device is a *real mechanism gap*.** The kernel's two ground assumptions
   (git-as-truth, fsync-POSIX-as-durability) do not hold at the edge, and the
   whole trust story collapses to self-report if they silently degrade (§2, §3).

The rest of this note spends most of its length on axis 2, because that is where
the kernel is least finished and the design question is genuinely open.

## 2. The assumptions that break — git-as-truth and fsync-as-durability — and why git-centrism is the deeper one

CLAUDE.md's tagline is *"the kernel is the part that doesn't believe the agents."*
The kernel makes that real with exactly two primitives, and **both reach for a
capable host**:

**(a) The non-forgeable rung is `git`.** `verify()` answers from git ancestry,
never from the agent's `verdict=SHIPPED` line:

- `oracle.py` shells `git show --name-only` and greps `git log` (`oracle.py:370`,
  `oracle.py:1114`).
- `git_delta.commits_since` runs `git log <sha>..HEAD` as the `ADVANCING` floor
  for `liveness` (`git_delta.py`).
- `resume_evidence` proves a claimed SHA is in ancestry — the mint on the
  *non-forgeable rung*, never the dead run's `STEP_CLAIMED` self-report
  (docs/107).

The reason this is unforgeable is precise: **the byte-author of the evidence is
`git`, a deterministic VCS the agent can *append* to but cannot *rewrite the
ancestry of* without the rewrite being detectable.** That is the same principle
docs/117 (the log-source seam) made explicit for logs — *a log is evidence only
when its byte-author is not the judged agent.* git is simply the special case
where the witness is a version-control system.

On a device there may be **no git, no `subprocess`, no repo at all**. A robot's
control loop, a mobile agent in an app sandbox, an MCU running a tinned LLM — none
of these has a `.git` tree, and several cannot `fork`. The instant `git` is
absent, every reader above degrades to its safe floor (`git_delta` returns `[]`,
`oracle` returns `NOT_SHIPPED via none`). That degrade is *honest* — it never
fabricates a ship — but it is also *empty*: **with no git, the kernel has no
ground-truth rung at all, and `verify` can only ever say "I can't tell."** A
referee that can only ever abstain is not refereeing.

**(b) The durability floor is `fsync`'d POSIX JSONL.** The WAL and the intent
ledger are append-only JSONL files made durable with raw POSIX calls:

- `lane_journal.append` logs under the lease mutex and `fsync`s (`lane_journal.py:12`).
- `intent_ledger.append` does `os.open(O_WRONLY|O_APPEND|O_CREAT)` + `flush` +
  `os.fsync`, torn-tail tolerant (`intent_ledger.py:153`).
- Both live at `.dos/runs/<run_id>/…` on a real filesystem.

This is the right floor *on a workstation*. On a device it is an assumption stack:
that there is a writable filesystem, that `O_APPEND` is atomic, that `fsync`
reaches stable storage (it famously does not on some mobile/flash stacks), and
that the process lives long enough to flush. A mobile OS can kill the app between
`write` and `fsync`; a browser agent has IndexedDB, not a file descriptor; an
embedded target may have wear-leveled flash where append-only JSONL is the wrong
shape entirely.

**Why this pair is load-bearing and not incidental.** Everything else the kernel
does is *downstream* of these two. Remove the unforgeable evidence rung and
`verify`/`liveness`/`resume` all collapse to self-report (the agent's word is the
only thing left). Remove durable logging and the WAL/intent-ledger cannot survive
the power-loss/app-kill that is *normal* on a device — so a run that crashes
offline has no fossils to re-adjudicate on recovery, and `resume` has nothing to
read. **The two assumptions are the floor the whole trust substrate stands on,
and the device is precisely the environment that kicks the floor out.**

### 2.1 The deeper flaw: git-centrism is wrong *everywhere*, not just on a device — git is blind to most of what an agent does

The device makes the git assumption *impossible to ignore*, but it is a mistake to
frame git-reliance as a workstation virtue that only fails at the edge. **It is a
limitation on every host, including the most capable one — and the device just
removes the camouflage.** Two repo docs already say this and this note should have
led with them, not buried them: [`84`](183_how-much-does-this-lean-on-git.md) ("git
is necessary and *not sufficient*") and [`93`](93_verifying-live-non-git-sources.md)
("git is load-bearing not because it is git, but because a self-narrating agent
cannot retroactively forge a reachable commit object … the one tamper-evident
fossil a code fleet happens to leave lying around *for free*"). **Git is
incidental.** It is one witness, for one narrow class of effect (a *committed
source change*), that a coding fleet gets at zero cost. It is not "ground truth";
it is "the cheap fossil for the cheap case."

The sharp version of the objection: **the interesting effects of an unattended or
on-device agent leave no git trace at all.** Git sees a commit. It is *silent* on
nearly everything an autonomous agent actually does to the world — and for those
effects git does not "degrade gracefully," it sees **nothing**, so a git-only
referee returns `via none` for an effect that unmistakably happened. That is worse
than the device case: it is a referee that is *blind in exactly the bands where
the stakes are highest* (irreversible, outward-facing) while looking confident
about the one band that is cheapest (a reversible local diff).

The honest way to think about it is **not "what does git see?" but "what did the
agent *do*, and what un-forgeable trace did *that specific kind of effect*
leave?"** The witness is almost never git — it is **whoever or whatever *received*
the effect**, because the agent can narrate having done a thing but cannot forge
the receiver's independent record of having gotten it. This is docs/116's
durable-commons law (read each other's *adjudicated effects*, never claims) and
docs/117's inversion law (witness byte-author ≠ judged agent) pointed at the *full*
effect surface:

| What the agent did | Git sees it? | The un-forgeable witness (the *receiver* of the effect) |
|---|---|---|
| Committed a file change | ✅ | git ancestry — the existing rung; *the* case git is for |
| Edited files, didn't commit | ❌ | working-tree content hash / FS state (weak — agent-adjacent) |
| Ran a command / migration / build | ❌ | **the OS exit code** (docs/117 acceptance verb) + the command's externally-checkable effect |
| Sent email / webhook / API call | ❌ | the *recipient's* record; the provider's sent-log; an HTTP response carrying a **server-issued id** the agent can't mint |
| Spent money / made a transaction | ❌ | the payment processor's ledger — **the bank is the witness** |
| Wrote a DB row / enqueued a message | ❌ | the DB/broker itself (read it back); the broker's committed offset |
| Deployed / changed cloud state | ❌ | the cloud control plane (describe the resource); the actually-running version |
| Filed a PR / merged / commented | ❌ (local git ≠ forge) | the forge's API state (GitHub/GitLab) — *not* the local `.git` |
| Moved a robot / actuated hardware | ❌ | a sensor reading the physical world; controller telemetry; a TEE-signed actuation log |
| Read / exfiltrated data | ❌ | the *system's* access log (not the agent's), an egress record |

The pattern across the whole right-hand column: **the witness is the counterparty
or the system on the other side of the effect — the one the agent does not
control.** Git is the witness in exactly *one* row. So "over-relying on git" is not
a device bug to patch; it is the kernel having shipped the witness for the one
free, cheap, reversible effect class and left the *expensive, irreversible,
outward-facing* effect classes — the ones an unattended agent is most dangerous in
— witnessed by **nothing**. docs/93 already drew the spectrum (immutable
third-party record → mutable third-party state → a probe the agent doesn't own →
self-report dressed as evidence) and shipped one worked non-git example
([`drivers/ci_status.py`](../src/dos/drivers/ci_status.py): "the build is green at
that commit" — the *complete → correct* jump git cannot make). The gap is that the
kernel has no *general seam* to plug those witnesses in, and `verify` has no way to
say which witness answered for *which kind of effect*. That seam (§5) is the real
subject — and it was always more than a device concession.

## 3. The reframe: ground truth is a *seam*, not git — and the kernel already proved the pattern

The fix is not to teach the kernel about phones. It is to notice that the kernel
already separates **boundary I/O (gather the evidence)** from **the pure verdict
(classify it)** — and that *git is just one evidence reader behind that boundary*,
not the boundary itself. `liveness.classify` takes `commits_since_start: int` as
**already-gathered** evidence; it never calls git. The git call lives at the CLI
boundary in `git_delta` (`git_delta.py`: "the subprocess happens HERE … the
already-counted delta is handed to the pure classifier"). The verdict does not
know where its evidence came from.

That is the whole opening. **"Ground truth" is already a seam in everything but
name.** The kernel has made *exactly this move* three times:

| Seam | What was hardcoded | What it became | The floor that keeps it safe |
|---|---|---|---|
| `dos.judges` (docs/86) | one deterministic oracle | a `Judge` protocol; ruling judges in drivers | `AbstainJudge` unshadowable; `run_judge` fails to ABSTAIN, never AGREE |
| `dos.overlap_policies` (docs/113) | the inline 1/3 prefix rule | an `OverlapPolicy` protocol | `PrefixOverlapPolicy` AND-ed under the floor → can only refuse-MORE |
| `dos.log_sources` (docs/117) | "an LLM reads the log" | a `LogSource` protocol keyed by `accountability` | paste/own-stdout is the forgeable floor; routing is a fixed fn of the tag |

The device problem is the **fourth instance of the same pattern**, and docs/117
already wrote its governing law. Generalise it:

> **An `EvidenceSource` is a witness whose byte-author is not the judged agent.
> `git` is the special case where the witness is a VCS and the effect is a commit.
> For every other effect — a payment, an email, a deploy, an actuation — the
> witness is whoever *received* it; on a device with neither git nor network it is
> a local non-forgeable rung (a content hash, the OS, a TEE). In all cases the
> seam's deterministic floor guarantees a swapped witness can only make `verify`
> *abstain more*, never *believe more*. This is docs/93's accountability spectrum
> made into a kernel seam.**

### 3.1 The witnesses, ordered by strength (this is docs/93's spectrum, operationalized)

The witnesses below are **not device-specific** — they are the general answer to
§2.1's effect→witness column, the same spectrum docs/93 drew (immutable
third-party record → mutable third-party state → a probe the agent doesn't own →
self-report). They matter on a workstation too; the device is just where the
weakest ones are all that remain. The point of the seam is that the strongest
*available* witness for *this effect* wins, and where only the forgeable floor is
available the verdict honestly abstains (it never silently trusts the agent). The
ordering is the docs/117 inversion law (*ingestion-ease ⊥ trust*): the witness that
is easiest to produce is the one the agent can
most easily forge, so it sits at the bottom.

1. **The counterparty / receiver of the effect (strongest for outward-facing
   effects — the §2.1 right-hand column).** For the effects git is blind to and an
   unattended agent is most dangerous in, the witness is *whoever got the effect*:
   the bank's ledger for a payment, the recipient's record (or a server-issued id
   in the HTTP response) for an email/API call, the cloud control plane for a
   deploy, the forge's API for a merged PR, the DB read back for a row write. The
   agent narrates the effect; it cannot forge the receiver's independent record of
   having gotten it. This is the most important `EvidenceSource` class for the
   unattended case and the one the kernel ships *no* general support for today
   (only `drivers/ci_status.py`, one instance).
2. **A remote append-only log the device streams to when online (strong).** The
   device can *append* its claimed effects to a server-side log but cannot
   *rewrite* the server's record — the same append-not-rewrite asymmetry that
   makes git unforgeable, relocated to a server the agent doesn't control. This
   is the natural witness for an *intermittently* connected device and it
   composes directly with the durable-commons (docs/116): the commons *is* the
   remote witness. (Often the same object as #1 when the commons records the
   counterparty's acknowledgement.)
3. **Hardware attestation / a TEE (strongest where it exists).** The device's own
   secure element signs an effect record; the agent cannot forge the signature.
   This is a hardware root-of-trust as the byte-author — the un-forgeable rung
   made physical. Most relevant to robots/embedded with a security chip.
4. **The OS itself, as a witness (medium, docs/95 + docs/117).** A process exit
   code, a syscall-level effect record, a file the OS (not the agent) wrote. This
   is docs/95's proc-liveness rung and docs/117's *acceptance verb* (the kernel
   runs a command and reads the OS exit code) — both are "the OS is the
   byte-author." Available on most hosts that can run a process at all.
5. **A content-addressed effect store (medium).** The effect's *hash* is the
   witness: the agent cannot make a different artifact hash to the same digest.
   This is the [[project-dos-claim-vs-lane]] region-digest idea (a durable id that
   is a function of *content*, not a *name*) pointed at evidence. Works with no
   git and no network.
6. **git ancestry (medium — the existing rung, for the one effect it witnesses).**
   A reachable commit object the agent can append to but cannot retroactively
   rewrite. Strong *for committed source* and free for a code fleet — but it
   witnesses **only** that one effect class (§2.1). Listed here, not at the top,
   precisely to break the centrism this note is correcting: git is *a* witness, not
   *the* witness.
7. **A local file mtime / the agent's own stdout (forgeable floor — rejected as a
   rung).** docs/95 already rejected mtimes as forgeable; docs/117 puts
   paste/own-stdout at the bottom. These are the *easiest* to produce and therefore
   the *weakest* — admissible as a hint, never as the rung a verdict stands on.

The seam does not pick; the *deployment* declares which sources it has (in
`dos.toml`, exactly as `[reasons]`/`[stamp]`/log-sources are declared), and the
kernel routes to the strongest present. **Where the only available source is the
forgeable floor, `verify` returns `via none` and the operator surface says so —
the honest "I can't establish this here," never a fabricated SHIPPED.** That is
strictly better than today's behaviour, which is to assume git or silently
abstain.

### 3.2 The durability axis is the same shape

`fsync`'d POSIX JSONL is one `DurableLog` implementation, not the contract. The
kernel already has the *schema* discipline for cross-version durable records
(`durable_schema`, the refuse-don't-guess `schema:` tag, docs §6). What it lacks
is a **`DurableLog` seam** so the same WAL / intent-ledger record can sit on:

- a `fsync`'d POSIX file (today's floor — the workstation default);
- a remote append-only log (the device streams when online — same object as the
  §3.1(2) witness, which is the elegant part: *on a device, the durable log and
  the evidence source can be the same remote append-only thing*);
- a mobile key-value sandbox / IndexedDB (append-as-put, torn-write handled by the
  store, not by torn-tail parsing);
- wear-aware flash (a different physical shape; the seam hides it).

The state-home work already anticipated half of this:
[[project-dos-state-home-layout]] split *project-local scratch* from
*machine-local indices* and called the relationship **projection, not sync** —
which is exactly the device→commons relationship (the device's local log is a
*projection* that reconciles to the commons on reconnect, §4.3). The `DurableLog`
seam is the generalisation of `PathLayout` from "where on this filesystem" to
"on what storage substrate at all."

**The conjunctive-floor discipline carries over verbatim.** A swapped
`DurableLog` that loses a record must degrade to *less* durable in a way that is
*visible* (a `durable_schema`-style refuse on read of a record it can't vouch
for), never silently drop a fossil and let `resume` believe the run did less than
it did. Same law as the overlap floor: a swapped component can only be *more*
conservative, never less.

## 4. The unattended axis — mostly consequences, three of them sharp

The supervision machinery exists (§1). What changes when the human is *not just
out of the loop per-step* but *structurally unreachable* (the device ran offline
overnight; nobody will look until morning, if then) is the **default disposition
of every place the kernel today hands a decision back to a human**. Three are
load-bearing.

### 4.1 A refusal nobody will answer must fail *closed*

The decisions queue (`dos decisions`) is a *projection* of refusals that need a
human; it "emits a shell command and exits, never mutates substrate" (CLAUDE.md).
That is correct *when a human will run the command*. Unattended, **a refusal
routed to an absent operator blocks forever** — and "blocks forever" silently
reads, to anything downstream, as "didn't happen," which is the novice-facing
catastrophe the safety-floor essay names (silent truncation reads as success).

The fix is the docs/120 `dos status` insight applied as a *default*:
**fail-closed when the resolver is absent.** docs/120's status digest is already
specced to report `claimed`-absent as a closed/negative state, not an optimistic
one. Generalise: when a refusal's resolver kind is HUMAN and no human is
reachable (the deployment declares "unattended" in `dos.toml`), the kernel's
default must be the *conservative* branch of the refusal (do-not-proceed,
durably recorded), **not** a timeout that lapses into proceeding. The operator
who *does* eventually look finds a durable, typed record of every refusal that
fired while they were away — the [`82`](182_the-kernel-is-a-taxonomy-of-refusal.md)
"refusal is the primitive" property, persisted across the unattended window.

### 4.2 The B5 non-delegable floor needs *somewhere for the hand to be*

The safety-floor essay's hardest, best result: the irreversible band (B5 — money,
delete-a-record, send-the-irreversible-thing) is **non-delegable — no `NOPASSWD`,
the agent fills the form, a human hand submits.** That design *assumes a human
hand is reachable.* On an unattended device there is no hand. Two honest options,
and the kernel should make the choice *explicit*, never default-permissive:

- **(A) The device holds no B5 grant at all (the safe default).** An unattended
  edge agent simply cannot reach the irreversible band — there is no path,
  exactly as a novice has none (safety-floor §2c). This is the right default and
  the kernel should ship it as the default: *unattended ⇒ B5 ceiling is zero.*
- **(B) B5 escalations queue durably and survive offline until a hand arrives.**
  The agent prepares the irreversible effect; it is recorded as a *pending,
  human-required* intent in a durable log that survives the offline window and
  *pushes* to a reachable human (a phone notification, the §3.1(2) remote log)
  when connectivity returns. The effect fires only on confirmed human assent —
  the propose-not-signal discipline of [`99 §5`](99_runtime-validation-and-the-actuation-boundary.md)
  stretched across a network partition. This is the `halt` verb's harder twin:
  *propose an irreversible effect, never deliver it unattended*.

The `halt` boundary verb already faces a smaller version of this question
("propose the stop command — but who runs it if nobody's there?"). On a device
the answer for both halt and B5 is the same: **the kernel records the proposal in
a durable log that outlives the offline interval; a driver (an online supervisor,
a human's phone) consumes it later.** The kernel never grows a hand.

### 4.3 Reconnection is `resume` pointed at a *partition*, not a *crash*

This is the genuinely new mechanism, and it is the one that ties the two axes
together. A device that ran unattended and offline comes back online holding a
local WAL / intent-ledger of effects it *claims* it produced. It must reconcile
that local record with the central commons (docs/116) — and it must do so
**without believing its own local self-report**, the same way `resume` does not
believe a dead run's `STEP_CLAIMED`.

This is **ARIES's third phase (analysis → redo → continue, docs/107) with the
failure boundary moved from *crash* to *network partition*.** The device's local
intent-ledger is the "fossils"; on reconnect the kernel re-adjudicates which of
the device's claimed effects are *real* against the commons' record, exactly as
`resume_plan` re-adjudicates `STEP_VERIFIED` against git ancestry:

- The device's local `STEP_CLAIMED` records are **hints**, re-verified at
  reconnect against the commons (the §3.1(2) remote witness) — never promoted to
  truth by virtue of being local. (This is the docs/107 adversarial-review
  lesson: the read path *must* re-adjudicate, store-as-hint + re-verify-at-read.)
- A claimed effect present in the commons → confirmed (`RESUMABLE`/`COMPLETE`).
- A claimed effect *absent* from the commons → the device believed it landed an
  effect that the shared record never received: a **`DIVERGED`** verdict, the
  partition analogue of the docs/107 divergence case. The residual
  (`declared − verified`, docs/117) is what the device must re-attempt or
  surrender, *not* what it narrated.
- A region the device leased locally that the commons granted to someone else
  during the partition → the lease arbiter's collision case, adjudicated on
  reconnect: the device's offline work on a now-conflicting region is refused into
  the decisions queue, never silently merged (the docs/116 *read-each-other's-
  adjudicated-effects-never-each-other's-claims* discipline).

The beautiful part is that **almost none of this is new code** — it is `resume` +
the intent-ledger + the durable-commons, with the evidence source being the
remote witness (§3.1) instead of local git, and the trigger being reconnect
instead of process restart. The partition is just a crash whose recovery is
delayed and whose witness is remote.

## 5. The buildable spec — the `EvidenceSource` seam (the throughline)

The throughline-first slice is the `EvidenceSource` seam, because it unblocks
*every* device deployment and reuses the exact apparatus of `dos.judges` /
`dos.overlap_policies` / `dos.log_sources`. It is pure-kernel and ships behind a
floor; the device-specific witnesses are drivers.

- **`dos.evidence` (kernel seam, pure).** An `EvidenceSource` Protocol:
  `gather(query) -> EvidenceFacts` (already-counted/already-read facts, the
  arbiter discipline — no verdict inside) + an `accountability` tag (reusing the
  docs/117 vocabulary: who is the byte-author?). A by-name resolver over a
  `dos.evidence_sources` entry-point group. The built-in **`GitEvidenceSource`**
  wraps today's `git_delta`/`oracle` git reads byte-for-byte — the unshadowable
  deterministic floor, so the whole existing verify/liveness suite stays green.
- **The floor discipline (load-bearing, copied from overlap).** A swapped source
  is AND-ed under the strongest *available verified* source: it can contribute
  *more* abstention or a *stronger* witness, but it can never *upgrade* a verdict
  the floor could not establish. Formally the dual of `admissible_under_floor`:
  `believe ⟺ some non-forgeable source attests`, and a forgeable-floor source
  (mtime, own-stdout) is structurally incapable of being the attesting source.
  This is what makes an *open* evidence-source set safe — the judge/overlap
  fail-safe re-aimed at evidence.
- **Discovery at the boundary, never in the verdict.** Which sources a deployment
  has is gathered *once* at the CLI/MCP boundary (the `active_judges` /
  `active_predicates` rule) and handed to the pure classifier as facts. A device
  with no git and no network resolves to {forgeable-floor} only → `verify` honestly
  returns `via none`.
- **`drivers/` (out of kernel).** `GitEvidenceSource` is the floor; a
  `RemoteLogEvidenceSource` (streams to / reads the commons), an
  `OsAcceptanceEvidenceSource` (docs/117 acceptance verb — runs a command, reads
  the exit code), an `AttestationEvidenceSource` (TEE signature) are drivers, the
  same kernel/driver split as `llm_judge`. The kernel imports no ruling source —
  the existing `no dos.drivers import` litmus covers it.

## 6. The buildable spec — the `DurableLog` seam

Parallel to §5, lifting `fsync`-POSIX from contract to one implementation.

- **`dos.durable_log` (kernel seam).** A `DurableLog` Protocol: `append(record)`
  (durable-on-return) + `read_all()` (torn/loss tolerant, schema-gated via the
  existing `durable_schema`). The built-in **`FsyncJsonlLog`** is today's
  `lane_journal`/`intent_ledger` I/O verbatim — the floor.
- **The loss-visibility discipline.** A swapped log that cannot vouch for a record
  must surface that on read as a `durable_schema`-style refuse (UNREADABLE /
  UNVOUCHED), never silently drop it — so `resume` can never believe a run did
  *less* than it did because a fossil quietly vanished. (Symmetric to §5: a
  swapped component is only ever *more* conservative.)
- **`drivers/`.** A `RemoteAppendLog` (the commons; doubles as the §5 remote
  witness — one object, two roles), an `IndexedDbLog` (browser), a `FlashRingLog`
  (embedded) are drivers. The kernel ships only the seam + the `fsync` floor.

The state-home `PathLayout` swap ([[project-dos-state-home-layout]]) is the
precedent: this generalises it from *where on a filesystem* to *on what storage
substrate*.

## 7. The reconnection adjudicator (mostly assembly)

Per §4.3, this is `resume` + intent-ledger + commons with a remote witness and a
reconnect trigger. The new surface is thin:

- A `reconcile_plan(LocalLedgerState, CommonsFacts, policy) -> ReconcilePlan`
  pure verdict, modelled line-for-line on `resume_plan`: CONFIRMED / DIVERGED /
  CONFLICTED (a region the commons re-granted during the partition) /
  RESIDUAL-TO-RETRY. The `CommonsFacts` (which claimed effects the commons
  received) are gathered at the boundary by a `RemoteLogEvidenceSource` (§5),
  exactly as `resume_evidence` gathers git-ancestry facts.
- A `dos reconcile` verb that *prints* the residual + the conflicts +
  the re-dispatch/surrender proposal (the docs/99 advisory floor — propose, never
  execute), routing CONFLICTED regions into the decisions queue.
- No new durable surface: the device's local ledger is the existing
  intent-ledger; the commons is docs/116. Reconnection is the partition-delayed
  case of the crash-recovery `resume` already ships.

## 8. The steelman — maybe a device should carry *no kernel at all*

The sharpest objection, and the docs here always argue both sides.

**The case against an on-device kernel.** A trust kernel whose ground truth is
*git on a real machine* should perhaps *stay* on a real machine. On this view the
device is not a place to run DOS — it is a **thin, deferred client of a
server-side kernel.** The device does the work, streams its claimed effects to a
server when online, and the *server's* DOS (with real git, real fsync, real
ground truth) adjudicates. There is no on-device kernel; there is an on-device
*reporter* and a server-side referee. This is lighter (no kernel on a
resource-constrained target), and it keeps the unforgeable rung where it is
genuinely unforgeable (the server the agent doesn't control). The whole §5/§6
seam apparatus, on this view, is over-engineering: *don't make ground truth
pluggable, just put the agent's claims where the existing git-backed kernel can
check them.*

**Where it's right.** It is right that **the strongest witness is remote** (§3.1
ranks it #1) and that a resource-constrained target should not carry a server
framework. For a device that is *mostly online* — a phone with good
connectivity, a fleet robot on a factory LAN — the deferred-client model is very
likely the correct architecture, and §4.3's reconciliation is *exactly* the
deferred-client's reconnect protocol. The seam work is not needed to make *that*
case work; the commons (docs/116) + `resume` (docs/107) already nearly do.

**Where it fails — and this is the whole reason the seam is worth building.** The
deferred-client model has a hole precisely in the deployment the prompt is about:
**the long-offline, autonomous device.** Between disconnection and reconnection
the agent is *deciding and acting* with **no referee present at all** — the
server's kernel cannot adjudicate an effect it hasn't received yet, and the
window can be hours. The agent in that window scores *maximal* on both axes (§1):
closest to effects, longest unobserved, no human, no server. The deferred-client
model's answer for that window is "nothing checks it; we sort it out on
reconnect" — which is the open-loop failure DOS exists to refuse, just relocated
into the offline interval. To get *any* trust during the offline window you need
**a local rung that is not the agent's self-report** — which is precisely a local
`EvidenceSource` that is not the forgeable floor (a content-addressed effect
store, the OS exit code, a TEE signature; §3.1 #3–#5, the ones that need no
network). **That is the case the seam exists for: not "git on a phone," but "a
non-forgeable local rung when neither git nor the server is reachable."**

So the synthesis is not either/or:

> **A mostly-online device is a deferred client of the server kernel (use the
> commons + `resume`; the seam is optional). A long-offline autonomous device
> needs a local non-forgeable rung for the offline window (the seam is the point)
> — and on reconnect it becomes a deferred client and reconciles (§4.3). The
> deferred-client model is the steady state; the `EvidenceSource` seam is what
> keeps the offline interval from being a trust vacuum.**

The objection correctly kills "port the git-backed kernel onto an MCU." It does
*not* kill "give the offline interval a witness that isn't the agent's word,"
which is the actual content of §5.

## 9. Litmus tests (the acceptance gates)

Each pins a property the same way the existing seam tests do
(`test_judges.py` / `test_overlap_policy.py` / `test_log_source*.py`):

- **`test_evidence_source_floor_cannot_upgrade`** — a hostile/forgeable
  `EvidenceSource` that *claims* attestation cannot make `verify` return SHIPPED
  for a phase no non-forgeable source attests; the verdict degrades to `via none`.
  (The dual of `test_overlap_policy`'s lying-admit proof.)
- **`test_git_evidence_source_is_byte_identical`** — the built-in
  `GitEvidenceSource` reproduces today's `verify`/`liveness` results
  byte-for-byte; the whole existing suite stays green with the seam interposed.
- **`test_verify_via_none_with_no_git_no_network`** — a deployment whose only
  source is the forgeable floor returns `via none` and the operator surface says
  "cannot establish here," never a fabricated verdict.
- **`test_durable_log_loss_is_visible`** — a `DurableLog` that drops a record
  surfaces UNVOUCHED on read (a `durable_schema`-style refuse); `resume` never
  believes a run did less than it did because a fossil vanished silently.
- **`test_reconcile_diverged`** — a local ledger claiming an effect the commons
  never received folds to `DIVERGED`, residual = `declared − verified`, never the
  device's narration.
- **`test_reconcile_conflicted_routes_to_decisions`** — a region the commons
  re-granted during the partition is refused into the decisions queue, never
  silently merged.
- **`test_unattended_refusal_fails_closed`** — with the deployment declared
  unattended, a HUMAN-resolver refusal defaults to do-not-proceed + durable
  record, never a timeout-into-proceed.
- **`test_unattended_b5_ceiling_is_zero`** — an unattended deployment holds no B5
  grant by default; the irreversible band has no autonomous path.
- **`test_kernel_imports_no_evidence_driver`** — no module under `src/dos/`
  (except `drivers/`) imports `RemoteLogEvidenceSource` / `AttestationEvidenceSource`
  / any ruling source; the existing `no dos.drivers import` litmus extends to cover
  the evidence seam.

## 10. What this note claims, and what it does not

- **Does claim:** the prompt fuses two orthogonal axes; DOS is deep on
  supervision and shallow on topology (§1). The shallowness is one load-bearing
  pair of assumptions — git-as-truth and fsync-POSIX-as-durability (§2) — and the
  deeper, git-centrism, is a limitation *on every host, not just a device*: git
  witnesses one effect class and is blind to the payment/email/deploy/actuation
  effects an unattended agent is most dangerous in, whose witness is the *receiver*
  of the effect (§2.1, the docs/93 spectrum). The fix is the *fourth instance* of a
  seam move the kernel already made three times, with the docs/117 witness-≠-actor
  inversion law as its governing principle (§3).
  The unattended axis is mostly *consequences* — fail-closed refusal defaults, a
  zero-by-default B5 ceiling, and reconnection-as-ARIES-over-partition (§4) — built
  on machinery (`resume`, the commons, the decisions queue) that already exists.
  The whole thing is buildable behind deterministic floors that can only
  refuse-more, never trust-more (§5–§7, §9).
- **Does not claim:** that the git-backed kernel should be ported onto a
  constrained target (§8 concedes the deferred-client model is the right steady
  state for a mostly-online device), that any of this is built, or that the
  offline-window trust problem is *fully* solved by a local rung (a content hash
  or a TEE signature attests *that an effect of a given content occurred*, not
  *that the effect was the right one* — the intent gap of safety-floor §6.4
  persists, and is sharper offline because no human is reachable to be the
  intent check). The local rung bounds the offline window's trust *vacuum*; it
  does not eliminate the intent residue.

The meta-answer to the prompt: **DOS becomes first-class on devices and
unattended not by learning what a phone or a robot is, but by recognising that
its two ground assumptions are seams it already knows how to open — and that the
deployment where the agent is most untrusted and the human most absent is the one
where the kernel's single job, not believing the agents, is worth the most.**

---

## References

*The two assumptions (§2):*
- [`src/dos/oracle.py`](../src/dos/oracle.py) + [`src/dos/git_delta.py`](../src/dos/git_delta.py) — the git ground-truth rung (the witness this note generalises).
- [`src/dos/lane_journal.py`](../src/dos/lane_journal.py) + [`src/dos/intent_ledger.py`](../src/dos/intent_ledger.py) — the `fsync`-POSIX durability floor.
- [`src/dos/resume_evidence.py`](../src/dos/resume_evidence.py) — the mint on the non-forgeable rung (the read-path-re-adjudicates discipline §4.3 reuses).

*The effect→witness frame — git is incidental, the receiver is the witness (§2.1):*
- [`183_how-much-does-this-lean-on-git.md`](183_how-much-does-this-lean-on-git.md) — "git is necessary and *not sufficient*"; the cheap-fossil-for-the-cheap-case framing this note's §2.1 builds on (the *complete → correct* jump git cannot make).
- [`93_verifying-live-non-git-sources.md`](93_verifying-live-non-git-sources.md) — **the accountability spectrum** (immutable third-party record → … → self-report dressed as evidence); the `value(rung) ≈ P(false) × detonation-cost − cost` calculus; the one worked non-git driver. §3.1 is this spectrum operationalized as a kernel seam.
- [`src/dos/drivers/ci_status.py`](../src/dos/drivers/ci_status.py) — the one shipped non-git witness ("the build is green at that commit"); the single instance the general `EvidenceSource` seam (§5) makes a population.

*The seam pattern this is the fourth instance of (§3):*
- [`87_the-adjudicator-trust-ladder.md`](87_the-adjudicator-trust-ladder.md) + `src/dos/judges.py` — the `dos.judges` fail-to-abstain seam.
- [`113_the-overlap-policy-seam-and-eval-per-axis.md`](113_the-overlap-policy-seam-and-eval-per-axis.md) + `src/dos/overlap_policy.py` — the `admissible_under_floor` refuse-more discipline (the structural template for §5's floor).
- [`185_native-log-adapters-and-the-actor-witness-split.md`](185_native-log-adapters-and-the-actor-witness-split.md) + `src/dos/log_source.py` — the *witness byte-author ≠ judged agent* inversion law (the principle §3 generalises).

*The unattended machinery (§4) and the durable surfaces it reuses:*
- [`99_runtime-validation-and-the-actuation-boundary.md`](99_runtime-validation-and-the-actuation-boundary.md) — propose-not-signal (the §4.2 B5-queue / §4.3 reconnect discipline).
- [`107_resumable-work-and-the-intent-ledger.md`](107_resumable-work-and-the-intent-ledger.md) — ARIES third phase + intent ledger (§4.3 reconnect = partition-delayed `resume`).
- [`116_the-durable-commons-and-the-constrained-a2a-problem.md`](116_the-durable-commons-and-the-constrained-a2a-problem.md) — the commons (the §3.1 remote witness + §4.3 reconciliation target).
- [`120_the-status-digest-a-folded-fact-for-a-fleet.md`](120_the-status-digest-a-folded-fact-for-a-fleet.md) — fail-closed-when-absent (the §4.1 default).
- [`75_state-home-plan.md`](75_state-home-plan.md) — `PathLayout` + projection-not-sync (the §6 `DurableLog` precedent).

*External validation (June 2026):*
- `dos-strategy/dispatch-os-aaa-agent-trust-landscape-2026-06` — an adversarially-verified sweep of recent AAA-team work mapped onto these laws. Corroborates the distrust axiom with field numbers (AnalysisBench self-validated 98% vs verified 6%; Factor(U,T) plan-monitor AUROC 0.52 vs implementation 0.96; AgentLeak output-only audits miss 41.7%); confirms on-device edge attestation as a real rung (AgenTEE, Arm-RMM-signed tokens). Two honest exposures it surfaces: (a) the **effect-witness half this note proposes is unclaimed *and unproven*** — every external verifier witnesses code execution / a consensus proof / the runtime, never a non-code counterparty receipt; (b) **DOS is behind on in-band prevention** — Microsoft's Agent Governance Toolkit (a shipped fail-closed PDP+PEP with a kill switch) and the DTF paper both *prevent* the act at admission, where this note's machinery only witnesses afterward.

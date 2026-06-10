# What is truth — the throughline

> **The kernel is the part that doesn't believe the agents.** So truth, in DOS,
> is not "what is the case" — it is the narrower, mechanizable thing the kernel can
> establish *without believing the author of the claim*. A verdict is true when it
> stands on an artifact the judged agent could not have authored its way around.
> Everything else is a self-report: a hint, demoted to a pointer that must clear a
> non-forgeable checkpoint before it anchors any work.

This is a throughline doc, not a new mechanism. It collects the working answer to
the question that keeps recurring — *what does this kernel mean by truth?* — off
the code that already ships it, surface by surface. The thesis is one sentence and
the rest of the doc is its proof: **truth = a claim the kernel can adjudicate
against an un-authored effect; forgeability is the axis; the actor's absence from
the witness is the one invariant; and where neither holds, the kernel says so and
routes to a human rather than pretending to know.**

The strong form, sharpened from the three candidates: *truth in DOS is the
consequence of making most cheap lies expensive* — the lies that stay cheap are the
ladder's bottom rungs, named below (the `grep-subject` rung, the empty commit, the
AGENT_AUTHORED floor). Forging a SHIPPED requires git
ancestry plus a real file footprint; forging an ADVANCING requires a real commit or
a state-mutating lease event; forging a resume step requires ancestry plus a
non-empty diff plus region overlap. Each cheap lie is priced up to "a real artifact
of the right shape," each rung is graded by what it still costs to forge, and the
regress bottoms out at the human operator who adjudicates what the kernel honestly
cannot.

## The evidence ladder

Every truth-surface in the kernel is a **ladder of rungs ordered by forgeability**
— how cheaply the *judged agent* can manufacture evidence that satisfies the rung.
The kernel does not pick "the rung that says yes"; it reports *which rung answered*,
so the operator reads the grade, not just the verdict. The `source=` /
`accountability` field is that grade, carried as DATA on the verdict.

**Top of the ladder — un-authored effect (not forgeable by the judged agent):**

- **`source='registry'`** — the truth syscall's strongest rung. A
  `recently_completed` row with `status: done` is written by the orchestration layer
  at ship time (`fanout_state.py mark done`), *not* by the agent's `git commit`
  (`oracle.py:878-891`). The agent does not author the registry.
- **`source='grep-artifact'` (the `file-path` rung)** — the diff itself. A commit
  that touched ≥2 of a phase's declared load-bearing files, read via
  `git show --name-only` (`oracle.py:1031`, `phase_shipped.py:1146-1209`). The agent
  wrote the commit but cannot retroactively change *which files a historical commit
  touched*. `_NONFORGEABLE_GREP_RUNGS = frozenset({"file-path"})` (`oracle.py:1031`)
  is the entire non-forgeable grep set, kept as data so a new artifact rung is a
  one-line addition.
- **OS_RECORDED — the acceptance verb.** The kernel (not the agent) launches a
  process via `subprocess.run()` and reads the OS-recorded exit code
  (`drivers/os_acceptance.py:130-176`). The agent "did not run the process and does
  not author the OS's record of how it ended" (`os_acceptance.py:17-18`) — it cannot
  forge a `returncode == 0`.
- **THIRD_PARTY — infrastructure attestation.** A cloud audit trail, load-balancer
  log, CI build record — authored by systems the agent does not control
  (`log_source.py:100`, `evidence.py:49`). The witness is the *receiver* of the
  effect (docs/121:156-189).
- **Liveness commit / journal-event rungs.** `commits_since_start ≥ 1` answers
  ADVANCING from immutable git objects (`liveness.py:258-265`, `git_delta.py:38-70`);
  a state-mutating lease event (`ACQUIRE/RELEASE/SCAVENGE/RECONCILE`, never
  `HEARTBEAT`) answers from the append-only lane journal the agent can only read
  (`journal_delta.py:182-308`, `_EVENT_OPS` at `:107`).
- **WAL-journaled leases — the arbiter's input.** `arbitrate()` reads live leases
  replayed from the lane-journal JSONL on disk (`lane_journal.py:286-388`), never the
  agent's `requested_tree` claim, AND-ed under the deterministic prefix floor
  (`overlap_policy.py:155-178`, `_tree.py:67-83`).

**Bottom of the ladder — self-report (forgeable by the judged agent):**

- **`source='grep-subject'` (the `direct`, `release-prefix`, `body-mention`,
  `hyg-slug`, `sub-phase-parent` rungs)** — the phase token appears in commit
  prose *the agent authored* (`_grade_grep_source`, `oracle.py:1034-1046`;
  `phase_shipped.py:738,754-759,877-883`). `git commit --allow-empty -m
  'docs/X: PHASE — done'` satisfies the `direct` rung with zero code shipped —
  documented in the oracle itself (`oracle.py:1013-1014`).
- **AGENT_AUTHORED evidence (the forgeable floor)** — a pasted receipt, the agent's
  own stdout, a local log, an mtime (`evidence.py:50-53`, `log_source.py:34-39`).
  Recorded and shown, structurally incapable of granting belief.
- **`STEP_CLAIMED` / a stored `STEP_VERIFIED` record** — the agent's self-report of
  progress in its intent ledger. Kept as a *hint*, never folded into the verified set
  without re-adjudication (`intent_ledger.py:386-389`, `resume.py:442-447`).
- **The requested tree** — the agent's asserted `requested_tree` to `arbitrate()`
  (`arbiter.py:150`). It is the *lay-out* of the lease being granted, never the
  adjudication input.

The grading is the point: the kernel ships the forgeable rungs (an agent who only
named the phase in a subject line *did* leave a fossil, just a weak one) but it
**labels** them forgeable so a downstream reader — a human, a supervisor, the
`dos plan` over-claim board — sees that a `grep-subject` verdict is one a forged
commit could have produced.

## The one invariant

Strip every surface down and the same rule remains: **evidence counts only when its
byte-author is not the agent being judged.** A self-report is generation #2 about
generation #1 — the same process that did (or did not do) the work, narrating
itself, with no independent faculty to consult (docs/116:112-116). The only
non-self-report is the **un-authored effect** — the commit, the file, the lease, the
exit code — read by something that did not author it (docs/116:140-146). The
canonical form: `An EvidenceSource is **a witness whose byte-author is not the
judged agent**` (`evidence.py:28-33`).

Every truth-surface is one instance of this rule, re-aimed:

| Surface | The un-authored witness | The self-report it refuses |
|---|---|---|
| **oracle** (`verify`) | git ancestry + diff footprint + the registry row | the commit subject/body prose (`oracle.py:1013-1014`) |
| **evidence / acceptance** | OS exit code, third-party attestation (`evidence.py:419-420`) | the agent's stdout, a pasted receipt (`evidence.py:445-453`) |
| **liveness** | commits-since-start, state-mutating journal events (`liveness.py:258-275`) | "I'm making progress" — never read at all |
| **intent ledger / resume** | git ancestry + non-empty footprint + region overlap (`resume_evidence.py:107-157`) | the stored `STEP_VERIFIED` via-tag (`resume.py:230-262`) |
| **arbiter** | WAL-journaled live leases under the prefix floor (`lane_journal.py:286-388`) | the `requested_tree` claim (`arbiter.py:150`) |
| **judge** | the evidence the deterministic kernel gathered for it to rule on | the judge's *own ruling* — contained, never trusted (docs/87:217-226) |
| **log-source** | THIRD_PARTY / OS_RECORDED bytes (`log_source.py:99-100`) | AGENT_AUTHORED bytes (`log_source.py:98`) |

Two implementations make the invariant *structural* rather than aspirational, and
they are the same shape ANDed in opposite directions:

- **`believe_under_floor`** (`evidence.py:411-484`): belief is granted only when a
  source whose `accountability` is non-forgeable was reached and ATTESTED
  (`evidence.py:445-449`). A forgeable-floor source's attestation is recorded in
  `attesting` but filtered out of the decision (`evidence.py:466-473`) — "the worst a
  buggy/hostile/lying AGENT_AUTHORED source can do is claim an attestation that is
  then ignored for belief." The accountability tag is class-level, never a per-call
  choice (`evidence.py:264-268`), and the fail-safe runner reads it via `getattr`
  with a fallback to the floor (`evidence.py:343-370`) so a malformed source cannot
  escape upward.
- **`admissible_under_floor`** (`overlap_policy.py:181-241`): a swappable overlap
  scorer is ANDed under the deterministic prefix floor — `admit ⟺ floor.admissible
  AND policy.admissible` (`overlap_policy.py:37`). A buggy/hostile/raising policy
  degrades to the floor (`overlap_policy.py:217-235`); it can only refuse MORE, never
  admit a collision the prefix algebra forbids.

The resume layer is the invariant taken to its sharpest edge: `STEP_VERIFIED` is
*re-adjudicated at read time*, not trusted from the record. `adjudicate_verified_steps`
re-runs `step_stands_on_nonforgeable_rung` (`resume_evidence.py:107-157`) on every
stored record — ancestry, then non-empty footprint (defeating `--allow-empty`,
`resume_evidence.py:148`), then intersection with the step's declared region
(defeating a real-but-unrelated commit, `resume_evidence.py:150-156`). The pure
verdict trusts only the freshly re-adjudicated set, never the agent-written via-tag
(`resume.py:230-262`). The agent writes the ledger; it cannot write into the
authority set.

## Where truth is still forgeable

A throughline doc that did not name the holes would be a self-report. The kernel
makes the cheap lie expensive — it does not abolish it.

- **The grep-subject rung self-certifies.** A commit subject containing the phase
  token flips `verify() → shipped=True` "via grep-subject" *even when nothing was
  built* (`oracle.py:1013-1014`). The kernel grades it forgeable but **still clears
  it**: a no-op commit is a real fossil, so the class survives — SHIPPING can be
  faked via subject lines just as ADVANCING can be faked via empty commits. The
  release-bump post-filter (`oracle.py:1162-1171`) and the #326 soak demotion
  (`oracle.py:428-439`) demote the worst cases (a grep verdict resting on a commit
  that touched only version/ledger files), but the floor case — a real `--allow-empty`
  on the right SHA — is invisible to a non-empty-file ancestry check (docs/108:359,
  the Goodhart point). Read the RUNG, not the bare verdict.
- **Liveness is indifferent to empty commits — by design.** The commit rung counts
  `git log` lines without filtering by content; `--allow-empty` increments it
  (pinned by `tests/test_liveness.py:284`). This is not a bug: "ADVANCING says bytes
  *moved*, never that they moved *well* — quality is an advisory judge's call, never
  this deterministic kernel verb" (docs/82). The kernel measures *motion*, not
  *quality*. The journal-event rung is harder — it excludes `HEARTBEAT` (a beat is
  not an event) and the lease's establishing `ACQUIRE` by identity
  (`journal_delta.py:288-293`, `tests/test_journal_delta.py:148-169`) — but the
  commit floor remains content-blind.
- **Advisory-only — truth is REPORTED, not ENFORCED.** DOS is a PDP with no PEP: it
  decides a verdict and never enforces it. The JUDGE rung makes a wrong judge
  *harmless* (advisory-only, fail-to-ABSTAIN, deterministic-first), **not correct**
  — a judge deliberately ruling AGREE on a false claim (a false-clear) is unreachable
  by accident but reachable by design (docs/87:217-226, `judges.py:243-276`). The
  kernel outsources its worst problem to containment, not solution.
- **The oracle abstains on intent-mismatch, structurally.** It cannot tell whether a
  commit labeled "FEATURE X" actually implements X — "the artifact exists in git,"
  not "it is the right artifact." Some claims are not deterministically decidable,
  period (docs/102:165, docs/108:126-129); the kernel admits the limit rather than
  pretending to cross it, and routes the residue to a judge or a human.
- **Git witnesses one effect class.** `verify` reads exactly one witness — git —
  and is blind to an email sent, a webhook delivered, a payment made, a deploy
  shipped (`evidence.py:3-11`, docs/121:156-189). The EvidenceSource seam opens the
  witness population, but a host that *mis-declares* a file it does not control as
  `OS_RECORDED`/`THIRD_PARTY` re-forges the floor (docs/117:303 — "the burden on the
  host to justify the rung").
- **A co-resident local model can be self-grading.** Where a model runs is a trust
  fact: if the JUDGE's generator *is* the worker's generator (same weights, same
  box), the judge is grading itself (docs/123). Locality is a measurable
  independence coordinate, not yet a kernel-enforced one.
- **Memory reproduces the disease inward.** A memory can name a real commit but
  mis-describe it (docs/103). Re-verification at read time defeats the `--allow-empty`
  forgery, but a memory pointing at a real-but-unrelated commit has no
  region-intersection gate (the resume ledger has one, `resume_evidence.py:150-156`;
  `memory_recall` does not) — defended only by operator review. The trust problem,
  recursively delegated to the human.

## Collecting more data — how the kernel LEARNS what truth is

The definitions above are *asserted* off the code. To learn what truth *empirically
is* — which rung actually answers, and how often each is gamed — the kernel ships
**an eval harness per axis**, the friendliness instrument that turns each seam into
a measurable surface. These are the next instruments to run and to build:

1. **`dos judge-eval` — the false-clear rate.** The headline metric over the JUDGE
   rung: a confusion grid (AGREE/DISAGREE/ABSTAIN × true/false) whose dangerous cell
   is AGREE-on-a-false-claim (`judge_eval.py:90-95`). This is how the unfixable
   epistemic gap of §"Where truth is still forgeable" is made *visible* — you cannot
   prove a judge correct, but you can measure how often it false-clears on a labeled
   corpus, and pick the judge that minimizes it.
2. **`dos overlap-eval` — the false-admit rate.** The same harness re-aimed at
   admission: a confusion grid + false-ADMIT rate + safe-concurrency-forgone, the
   backtest of how often a swappable disjointness scorer would have double-booked
   (docs/90 §2). It measures the *cost of the floor* (concurrency forgone) against
   the *cost of looseness* (collisions admitted).
3. **A rung-occupancy backtest.** The instrument the kernel does not yet ship: over a
   real commit history, *which `source=` actually answered* each `verify` — and of
   the `grep-subject` answers, how many were later refuted by a `grep-artifact`
   re-check. This measures the forgeability axis empirically: if 80% of green verdicts
   rest on the forgeable rung, the floor is doing little work. (The deterministic-first
   rung-occupancy is already a column in `judge_eval`; the oracle has no equivalent yet.)
4. **Witness-coverage measurement.** Count the effect classes git is blind to
   (payment, email, deploy, actuation) and the fraction of a run's real effects for
   which *any* non-forgeable witness was wired (`evidence.py:3-11`, docs/121). The
   distrust axiom is already field-measured elsewhere (a witnessed-vs-unconfirmed
   split, docs/129 — 0.7673 witnessed, 64/275 unconfirmed); generalizing that count
   to every effect class is how the kernel learns where its eyes are.
5. **The acceptance-verb corpus.** Run real commands through `os_acceptance` and
   record the OS exit code against the agent's claimed outcome
   (`drivers/os_acceptance.py:130-176`) — the cleanest non-forgeable signal, and the
   one whose true/false discrimination is directly measurable.

The common shape: **a verdict is only as good as the rung it stood on, so measure
the rung, not the verdict.** Each eval harness is a microscope on one seam's
forgeability; together they are how DOS replaces "truth is what the kernel
establishes" (a definition) with "here is how often each rung was actually un-forgeable
on real history" (a measurement).

## The throughline, restated

**Truth in DOS is what the kernel can establish without believing the agents** — a
verdict built on an un-authored effect (a commit's footprint, an OS exit code, an
infrastructure attestation) whenever one exists, graded by how forgeable the
answering rung was, with every self-report (memory, claimed SHA, agent narration)
demoted to a hint that must clear a non-forgeable checkpoint before it anchors any
work — and where no un-authored effect can decide, the kernel says ABSTAIN and hands
the irreducible seed to a human, rather than narrate a certainty it does not have.
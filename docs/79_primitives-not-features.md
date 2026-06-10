# Primitives, not features — why the syscalls are deliberately small

> **The kernel's job is not to handle the aftermath of "done" — it is to give
> you a small, checkable, replayable unit to build your own handling out of.**

[`HACKING.md`](HACKING.md) is the *how-to* (the extension axes); [`76_flexible-goals-and-verification.md`](76_flexible-goals-and-verification.md)
is the *theory of where the give lives* (provenance and which-signals, never the
adjudication). This note is the theory **one rung lower**: *why the four syscalls
are each so small*, and why that smallness — which can read like an unfinished
stub — is the actual product. Where a whole-OS framing zooms out, this one zooms
in on a single syscall and asks what makes it a *primitive* rather than a
*feature*.

The thesis in one line: **a feature does something for you; a primitive makes a
*space* of things possible, most of which its author never enumerated — and DOS's
syscalls are built to be the second kind.**

---

## 1. The seam: "done" is a self-report

Strip away every domain and an autonomous agent's last act is almost always the
same: it declares the work **done**. That declaration is a *narration* — a string
the agent emits about the world, not the world. The whole reason DOS exists is the
epigraph in [`CLAUDE.md`](../CLAUDE.md):

> **The kernel is the part that doesn't believe the agents.**

So the natural place to draw the substrate's boundary is *the moment of "done."*
In a single chat session that moment needs no kernel — you read the answer and
move on. But a thousand agents touching one organization's repos, calendars, and
money, each one self-narrating, turns "done" into a claim that has to be
**adjudicated** before anyone acts on it. The four syscalls are exactly the
adjudication primitives for that seam:

- **`verify()`** — *"you said `(plan, phase)` shipped; did it actually?"*
  Registry-first, ancestry-checked, answered from artifacts and git history,
  never from the agent's own log line. The literal "after done" check.
- **`refuse(reason_class)`** — *"you cannot declare done, and here is the
  closed-vocabulary **kind** of no."* The dual of structured output: a typed
  reason an agent (or the kernel) emits *instead of* a false "done."
- **`arbitrate()` / `lease()`** — serialize the **effects** of done-work on shared
  state, so two agents' "done"s do not corrupt each other.
- **`spawn()` / `reap()`** — the correlation spine that ties a claim of "done"
  back to *who* claimed it, sortably and with lineage.

One precision the "after done" intuition misses, worth stating so the boundary is
honest: **`arbitrate()` also fires *before* done.** Admission is a pre-flight gate
("can this lane even be taken?"), not purely post-hoc. So the arbiter straddles
the "done" line — `verify()`/`reap()` are the strictly-after half, the lease
arbiter reaches back before the declaration too. The clean statement is therefore
not "everything after done" but: **DOS is the substrate for the *adjudication* of
"done" — verifying the claim, serializing its effects, refusing it in closed
vocabulary, and correlating it to its author.** What to *do* after a failed
`verify()` — replan, re-dispatch, soak, escalate — is deliberately **not** here;
that is host workflow (see §5).

---

## 2. Feature vs primitive

Here is the distinction the rest of the doc turns on:

> A **feature** does something *for* you. It is finished when it handles the case
> it was built for. You consume it.
>
> A **primitive** makes a *space* of things possible. It is finished when it
> gives that space a fixed, checkable unit — and the interesting things then get
> built in the layer *above* it, without the primitive changing at all. You build
> *on* it.

`refuse()` is the sharpest example, so take it as the type specimen. It is almost
nothing: a closed vocabulary, a structured emission, a verdict you can re-check.
You could mistake it for a stub — "shouldn't a refusal *do* something? retry,
escalate, page a human?" No. That mistake is exactly the feature/primitive
confusion. `refuse()` does something smaller and stronger: it gives *every*
retry policy, escalation queue, SLA, and operator dashboard a **common, closed,
checkable unit of "no"** to be built out of. The moment it grew a retry policy it
would encode *someone's* retry policy — and stop being buildable-upon for everyone
whose policy differs.

The tell of a real primitive: **the interesting things get built in the layer
above without the primitive changing.** §4 shows that this is not aspirational for
`refuse()` — it already happened, twice, in this repo.

---

## 3. The four syscalls, measured by how little they do

The kernel is deliberately under-featured, syscall by syscall. The discipline is
visible if you tabulate *how little each one does* against *what that little thing
makes buildable*:

| Syscall | How little it does | What that little thing makes buildable |
|---|---|---|
| `verify()` | Answers one yes/no (`shipped: bool`) tagged with its provenance (`source: "registry" \| "grep" \| "none"`), off a rung-ladder. No retry, no remediation, no opinion on what to do next. | Every audit, gate, soak-check, "did it really ship" report, CI ratchet. The [stable-release gate](../scripts/stable_release_context.py) is just a stack of `verify()` calls with a soak window. |
| `refuse()` | Emits one closed-vocabulary "no" that is simultaneously **emittable, verifiable, and refusable**. No policy about consequences. | Every escalation queue, retry policy, per-reason SLA, operator dashboard. The `dos decisions` queue (§4) branches on these and nothing else. |
| `arbitrate()` | `arbitrate(request, live_leases, config) -> decision`. State in, decision out, **no I/O**. A closed `outcome` (`acquire \| refuse`) plus a typed abstain. | Every lease scheme, fairness policy, capability lattice. A hardware-placement `place()` verb would be the same shape pointed at GPUs and NVMe — a *new verb on the same pure-arbiter mechanism*, not a new arbiter. |
| `spawn()` / `reap()` | Hands out a sortable, lineage-carrying run-id and appends a lease record to a write-ahead log. That is the whole contribution. | Every correlation, replay, lineage trace, post-hoc audit. `dos journal replay` reconstructs any run because the id sorts and the log is append-only. |

Read the table as a single claim: **each row is a primitive *precisely because*
the right column is open-ended and the left column is fixed.** The kernel stays
small so the buildable space stays large. Three properties make the left column
load-bearing rather than merely terse:

- **Closed, not free-text.** A free-text "reason this is blocked" cannot be built
  upon — every consumer parses it differently and the set drifts under you. A
  *closed* vocabulary lets a downstream tool branch *exhaustively*: every reason
  gets a dashboard color, every reason gets a replan branch, every reason gets
  counted. The closure is the contract. (`reasons.py`'s docstring is explicit:
  hackability is **not** "mutate the enum at runtime"; it is "declare your closed
  set once, as data, and let every consumer derive from that single declaration."
  Closed enough to build on — see §4 — open enough to adapt.)

- **One representation, many vantage points.** `refuse()`'s triality — the same
  vocabulary the worker uses to *say* "blocked," the kernel uses to *check* it,
  and a supervisor uses to *reject* it — means nobody has to agree on a *second*
  representation. `verify()` has the same shape: one `ShipVerdict`, read by the
  emitter, the auditor, and the gate alike.

- **Deterministic and I/O-free.** None of these phone home or read the wall clock.
  So anything built on them inherits **replayability for free** — re-run a refusal
  or an arbitration a year later from the journal and get the byte-identical
  verdict. A feature that reached out to the world could not promise that, and
  nothing above it could either.

---

## 4. `refuse()` as the worked example — it already happened

The claim "the interesting things get built above without the primitive changing"
is checkable, not aspirational. Two things were built on `refuse()` after it
stabilized; neither touched the syscall.

**(a) A new reason was added as *data*, and `refuse()` did not change.** When the
admission-predicate work ([`73_admission-predicate-plan.md`](73_admission-predicate-plan.md))
needed a typed refusal for "this lease would edit the kernel that is adjudicating
it," the `SELF_MODIFY` reason was *declared* — a new `ReasonSpec` appended to
`BASE_REASONS` (`src/dos/reasons.py`) — and it was instantly emittable,
`category_for`-verifiable, `is_refusal`-refusable, and `man`-documentable through
the exact same calls. No edit to the emit/verify/refuse mechanism. (A nice tell:
the `reasons.py` module docstring still says the base set has "seven" reasons; the
code now has **eight**, because adding one is a data change that doesn't ripple
into the prose describing the mechanism. The drift is harmless precisely *because*
the primitive didn't move.) A host adds its own the same way — a `[reasons]` table
in `dos.toml`, no code — which is the whole point of [closed-enums-as-data](HACKING.md).

**(b) An entire UI was built above the vocabulary.** The `dos decisions` queue is
a **read-only projection** that branches on the refusal vocabulary plus a
resolver-kind axis (`HUMAN` / `ORACLE` / `JUDGE`) — it renders what is blocked,
groups it, and emits a shell command for the operator to run. It could be written
*because* the refusal set was closed and structured; nobody had to extend
`refuse()` to make the queue possible, and the TUI mutates no substrate state. The
escalation policy, the resolver routing, the LLM-as-judge advisory lane — all of
it is **layer-above** work that the primitive simply *afforded*.

That is the pattern in miniature: the kernel handed out a fixed unit of "no," and
a registry-driven extension surface, a self-modify guard, an operator queue, and
an advisory judge all grew on top — with the syscall sitting still underneath the
whole time.

---

## 5. Why restraint *is* the substrate — the layering contract, restated

This whole note is the layering contract ([`CLAUDE.md`](../CLAUDE.md): *mechanism
is the kernel; policy is a driver*) viewed from a different angle. The contract is
usually stated as a *dependency rule* (the kernel imports no host). Read through
the primitive/feature lens it is also a **restraint rule**:

> Keep adding features to a primitive and you eventually encode *someone's* policy
> into it — at which point it stops being buildable-upon for everyone whose policy
> differs. The kernel resists that on purpose.

This is why the design is emphatic about what is **not** in the package, and every
exclusion is the same move — refusing to bake a feature into a primitive:

- **The remediation after a failed `verify()` is host concern.** The kernel
  *renders* the verdict; it does not *drive* the recovery. Replan/re-dispatch/soak
  live in the host's own skills, not the substrate. ([`76_*`](76_flexible-goals-and-verification.md):
  flexibility lives in provenance and which-signals, *never* the adjudication.)
- **The phased-plan workflow is not in the kernel.** `verify()` treats the plan
  registry as an *optional* source and answers from git history alone when there
  is no plan at all (`source="none"`, pinned by `tests/test_verify_no_plan.py`).
  The truth syscall is a primitive; "what a plan is" is a feature, and it lives
  upstairs.
- **`arbitrate()` carries no lane taxonomy.** The lane names are
  `SubstrateConfig` data, so the same pure arbiter admits a benchmark repo's
  lanes, a calendar's, or a k8s namespace's, unchanged. The admission *mechanism*
  is the primitive; *which lanes exist* is policy.

The poetic version, which is just the Unix observation: **a framework calls your
code; a substrate gets built on.** Unix won by
giving a chaotic world a few small, composable, trustworthy primitives — files,
processes, pipes — and *refusing to be clever above them*. DOS's bet is the same
for the age of autonomous agents: `verify()` is the minimal unit of "did it really
happen," `refuse()` the minimal unit of "no, and here's the kind of no,"
`arbitrate()` the minimal unit of "who may touch this," `spawn`/`reap` the minimal
unit of "who did it." None of them tries to be your workflow. That restraint is
exactly what makes them a substrate rather than a framework — and it is the same
restraint, viewed from below, as "the kernel is the part that doesn't believe the
agents." The kernel does not *act* on the disbelief either. It hands you a
trustworthy, minimal way to *represent* it, and gets out of the way.

---

## See also

- [`CLAUDE.md`](../CLAUDE.md) — the architecture contract; the layering table and
  the litmus tests this note argues the *spirit* of.
- [`76_flexible-goals-and-verification.md`](76_flexible-goals-and-verification.md)
  — where flexibility may live (the rung above this one).
- [`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md)
  — the sibling to this note: where this one argues each syscall is *small*, that
  one argues each is a *kind of no*, and that a credible "no" is the scarce
  primitive. (`refuse()` is the worked example here; there it is one of four.)
- [`HACKING.md`](HACKING.md) — the how-to for building in the layer above (the
  four extension axes, `dos.toml`, entry_points, drivers, the skill pack).

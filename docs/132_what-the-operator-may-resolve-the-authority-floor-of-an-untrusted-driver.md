# 132 — What the operator may resolve: the authority floor of an untrusted driver

> **DOS classifies every pending decision by *who can clear it* — `ResolverKind`
> is `ORACLE | JUDGE | HUMAN` (`decisions.py:91`). But that taxonomy answers
> "which *rung* owns this," not "what may the *operator* do without a human." And
> the operator here is an LLM — the exact self-narrating worker the kernel is built
> not to believe (`CLAUDE.md`: "the kernel is the part that doesn't believe the
> agents"). So the operator's authority is NOT "everything not tagged `HUMAN`." It
> is narrower, and the narrowing rule is the kernel's own posture turned inward: an
> LLM-operator may resolve a decision unilaterally **iff a deterministic rung — not
> its own narration — supplies the ground truth, AND the act is cheap and
> reversible.** Everywhere else the operator is the JUDGE rung wearing an operator
> hat: advisory-only, fail-to-abstain — it gathers evidence, runs the oracle,
> *proposes* the irreversible command, and lets the human enact what rests on
> judgment or leaves the machine. This note pins that map. It builds nothing new;
> it makes an authority boundary that is currently *implicit* (scattered across
> `decisions._resolver_for`, the `CLAUDE.md` commit-freely rule, and the
> `llm_judge` advisory disciplines) into one stated contract.**

Status: theory + operating contract. No kernel code changes. The map is a *reading*
of three already-shipped surfaces — the `decisions.ResolverKind` taxonomy
(`decisions.py:91`, `_resolver_for` at `:163`), the `CLAUDE.md` "Committing — close
the loop without asking" rule, and the JUDGE-rung four disciplines
(`docs/86_*`, `drivers/llm_judge.py`) — composed into the answer to one question an
operator (human *or* LLM) keeps asking and currently has to re-derive each time:
*which of these may I just do?* §1 states the inversion that makes the question
non-trivial. §2 is the three-tier map. §3 is the one-line rule and its proof-shape.
§4 is the honest residue + the one buildable hook (a `resolver_kind`-gated
emit-and-exit, already 90% present in the TUI).

The reference userland app is the downstream consumer (CLAUDE.md); this note cites
the kernel's own modules only — it is a contract *about* operating DOS, not a new
mechanism *in* DOS.

---

## 1. The inversion: the operator is also an untrusted worker

Every other distrust note in this series points the kernel's skepticism *outward* —
at the worker whose claim `verify()` checks, at the run whose progress
`liveness()` adjudicates, at the lane-asker `arbitrate()` refuses. This note points
it at the **operator** — and the operator, in a fleet driven by Claude Code, is an
LLM.

That is the whole twist. DOS's thesis is "do not believe what a generation says it
did." An LLM operating the kernel is a generation. So the naïve reading of the
decision queue — *the rows tagged `HUMAN` need a person; everything else I, the
operator, may clear* — is **wrong in the unsafe direction.** It would let the
untrusted worker self-authorize exactly the acts the kernel exists to gate. The
`JUDGE` tag does not mean "the LLM-operator may resolve this alone"; it means "an
LLM adjudicator is the cheapest *next reader before a human*" (`decisions.py:100`,
`:189`) — advisory, not dispositive. The `ORACLE` tag does not mean "I decided it";
it means "a *deterministic* oracle can cross-check it" (`decisions.py:99`) — the
authority is the oracle's, and I am merely the hand that runs it.

So the operator's authority floor is set by the same question the kernel asks of any
worker: **what backs this — a rung, or a narration?** Where a deterministic rung
backs the act, the operator may proceed (it is not trusting *itself*, it is reading
a verdict). Where only the operator's judgment backs it, the operator must escalate
— because DOS deliberately never distrusts *judgment* (`[[project-dos-distrust-primitive-map]]`:
"never distrust judgment/correctness"), which means it also never *delegates*
judgment to an untrusted operator. The thing the kernel won't adjudicate is exactly
the thing the operator may not self-authorize.

This is not a new discipline. It is the **`llm_judge` four disciplines**
(deterministic-first, advisory-only, fail-to-abstain, abstention-first — `docs/86_*`)
re-aimed from "a judge ruling on a worker's residue" to "an operator acting on the
queue." A judge that raises or returns garbage degrades to `ABSTAIN`, never `AGREE`
(`run_judge`); an operator unsure whether a rung backs an act degrades to *escalate*,
never *proceed*. Same safe direction, same floor.

---

## 2. The three-tier map

The rows below are sorted by the kernel surface that emits them
(`DecisionKind`, `decisions.py:77`) and the resolver the kernel assigns
(`_resolver_for`, `:163`). The **tier** is the operator's authority over each — the
thing this note adds.

### Tier 1 — Resolve alone (a deterministic rung backs the act; cheap; reversible)

The operator is not trusting itself here; it is *reading a syscall's verdict* and
acting on a cheap, reversible result.

| Act | Backed by (the rung) | Why no human |
|---|---|---|
| Run `verify` and report SHIPPED/NOT_SHIPPED as fact | `oracle.is_shipped` over git ancestry + ship-stamp grammar | The verdict is *read*, not decided — git is the witness, not the operator's narration. |
| Run `liveness` / report ADVANCING-SPINNING-STALLED | `liveness.classify` over git/journal delta | Pure verdict from a delta; the operator observes, doesn't judge. |
| Take / follow an arbiter **acquire** (incl. an auto-pick redirect) | `arbitrate` — structurally cannot double-book | The redirect *is* the kernel working; trusting `acquire` trusts the lock-manager, not the asker. |
| Clear an **ORACLE**-resolvable queue row | `picker_oracle` cross-check (`_ORACLE_CATEGORIES` = `STALE_CLAIM`/`TRUE_DRAIN`, `decisions.py:113`) | A deterministic oracle confirms (e.g.) the claim is fresh; no attention needed. |
| Commit a finished, suite-green unit of work on `master` | `CLAUDE.md` standing authorization ("do not stop to ask") + the suite as the rung | A local commit is the cheap, reversible ship-stamp the oracle reads; deferring it leaves the phase `NOT_SHIPPED`. |
| Run any read-only projection (`decisions`, `top`, `plan`, `doctor`, `man`) | takes no lease, mutates nothing, emit-and-exit | Never a decision; pure observation. |

The commit row carries the one scope caveat that matters in *this* repo: stage only
the lane worked (`git add docs/… src/dos/…`), never `git add -A`. The working tree
here routinely carries another loop's unstaged edits — the `SELF_MODIFY` / disjoint-lane
discipline applied to *staging* (`CLAUDE.md`, "commit only the lane you actually
worked"). Authority to commit is not authority to sweep.

### Tier 2 — Prepare and propose; a human (or durable authorization) enacts

This is the **advisory-only** discipline made concrete. The operator may compute
the verdict and *stage* the action; it may not *enact* the irreversible step.

| Act | Resolver tag | What the operator may do / may not do |
|---|---|---|
| A `LIVENESS` halt proposal (`OP_HALT`) | `ORACLE`-adjudicated, but enaction is human | **May:** surface the proposed stop command + the "let it ride" no-op. **May not:** signal the process. The queue "NEVER signals a process itself" (`decisions.py:545`); the verdict is the oracle's, the *kill* is a human/driver act. |
| A `JUDGE`-resolvable `WEDGE` | `JUDGE` (`_resolver_for` → `:191`) | **May:** run the adjudicator (`dos judge` / `llm_judge`) to rule *before* a human looks. **May not:** treat that ruling as a `--force` mandate — the override is the human's. |
| A seam-affecting fix (e.g. the docs/127 audit items) | n/a (a code change) | **May:** prepare the patch (re-stamp metadata, raise `_ONELINE_WINDOW`, reconcile the lane-health adapter). **May not:** land a change to a surface two consumers pin against (Job, Bench) without confirming direction — `bc83d94`-class contract breaks are *outward-facing* (§ Tier 3). |

The through-line: an `ORACLE` tag on a LIVENESS row means the *verdict* was
deterministic, **not** that the *consequence* is. The operator inherits the
verdict's authority, never the actuator's. This is `docs/99`'s advisory-floor
("record + propose, never actuate") read as an operator rule rather than a kernel
rule.

### Tier 3 — Always escalate (judgment-backed, or hard-to-reverse, or outward-facing)

Never self-authorized, because the backing is the operator's judgment (which DOS
won't adjudicate) or the act leaves the machine / can't be cheaply undone.

- **Anything that leaves this machine or is hard to reverse:** push, tag, `/release`,
  `/stable-release`, force-push, history rewrites. `CLAUDE.md` names these as the
  *explicit exceptions* to commit-freely. The harness's own rule agrees: confirm
  outward-facing / hard-to-reverse acts first.
- **`SOAK_GATE` rows** — `HUMAN` by definition (`decisions.py:179`): a time-window the
  operator must judge closed. The kernel hard-codes this resolver; the operator does
  not soften it.
- **Bare `ARBITER_REFUSE` / `PREFLIGHT_REFUSE` with no token** → `HUMAN`
  (`decisions.py:182`): pick-a-lane / `--force` / fix-the-packet are genuine operator
  calls, not auto-clears.
- **The `SELF_MODIFY` / `global`-lane hazard** — editing `src/dos/`'s own running path.
  The kernel refuses this *precisely because the operator is the untrusted worker*
  (`[[project-dos-self-modification-hazard]]`). The operator does not `--force` past
  its own refusal on its own say-so; that is the one refusal aimed *at* the operator.
- **Anything resting on judgment of *correctness* or *completeness*.** "Is this code
  right / is this PR good / is this design sound" is a human call. The operator can
  verify a phase *shipped*; it cannot certify it is *correct* — the kernel draws that
  line (`verify` answers shipped-ness, never quality) and the operator inherits it.

---

## 3. The one-line rule (and how to check yourself against it)

> **An LLM-operator may resolve a decision itself iff a deterministic rung supplies
> the ground truth AND the act is cheap and reversible. Otherwise it is the JUDGE
> rung: gather evidence, run the oracle, propose the command — and let the human
> enact what is irreversible, outward-facing, or judgment-backed.**

The self-check is a two-question gate, applied in order (most-specific first, the
`_resolver_for` idiom):

1. **What backs this act — a rung or my narration?** If the answer is "my read of a
   syscall verdict (`verify`/`liveness`/`arbitrate`/`picker_oracle`)," the backing is
   a rung → continue. If the answer is "my judgment that this is right/done/safe," the
   backing is narration → **escalate** (Tier 3).
2. **Is the act cheap and reversible, and does it stay on this machine?** A local
   commit on `master`, a lane acquire, a projection: yes → **proceed** (Tier 1). A
   process kill, a `--force` override, a push/tag/release, a seam contract break: no →
   **propose, don't enact** (Tier 2/3).

Default on uncertainty is **escalate**, not proceed — the abstention-first
discipline (`docs/86_*`). An operator that cannot tell which rung backs an act is in
exactly the position of a judge that cannot rule: it abstains. The cost of a wrong
escalation is one wasted question to a human; the cost of a wrong self-authorization
is the untrusted worker enacting an ungated effect — the asymmetry the whole kernel
is built around.

---

## 4. Residue + the one buildable hook

**What this note does *not* settle.** The map is for an operator acting *through the
CLI* — the surfaces that already exist. It does not cover an operator acting through
a *driver it wrote* (a custom `dos.judges` / `dos.predicates` plugin): there the
authority question collapses into the plugin's own conjunctive-only / fail-to-abstain
floor, which the kernel already enforces structurally (`docs/86_*`,
`overlap_policy.admissible_under_floor`). A plugin cannot grant its author more
authority than the floor allows; that case is *already* safe by construction and
needs no operator-discipline layer.

**The one place the map could become mechanism instead of prose.** The `decisions`
queue already carries `resolver_kind` on every row and already renders an
emit-and-exit action bar (`next_steps`, `decisions.py:521`) under the locked
read-only-router model (the TUI prints a command and exits, never mutates). The map's
Tier-1/Tier-2 split is *exactly* a function of `resolver_kind` + `DecisionKind` —
which means a future `dos decisions --auto-clear ORACLE` could enact the Tier-1 rows
the kernel already certifies an oracle owns (run the `picker_oracle` cross-check,
clear the fresh-claim rows) while leaving JUDGE/HUMAN rows untouched. That is the
honest scope of "automate the operator": **only the rows a deterministic rung already
backs** — never the JUDGE rows (those stay advisory), never the HUMAN rows (those
stay escalated). The floor is the same one this whole note rests on, so the feature
would be safe in the same way the auto-pick redirect is safe: it can only do what a
deterministic rung already authorized, and degrades to "show, don't clear" on any
abstain. It is not built; it is the natural Tier-1 extension if the operator-loop ever
wants hands-off clearing of the rows that genuinely need no judgment.

---

*Cross-refs: `decisions.py` (the `ResolverKind` taxonomy + `_resolver_for` this note
reads); `docs/86_*` + `drivers/llm_judge.py` (the four JUDGE disciplines re-aimed at
the operator); `docs/99` (the advisory-floor "record + propose, never actuate" that
Tier 2 inherits); `CLAUDE.md` "Committing — close the loop without asking" (the Tier-1
commit authorization) + the `SELF_MODIFY` / disjoint-lane staging discipline.
Memory: `[[project-dos-operator-decisions-queue]]`, `[[project-dos-judge-seam]]`,
`[[project-dos-distrust-primitive-map]]`, `[[project-dos-self-modification-hazard]]`.*

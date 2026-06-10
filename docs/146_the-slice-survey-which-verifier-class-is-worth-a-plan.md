# 146 — The slice survey: which remaining verifier class is worth a DOS plan?

> **Status:** survey + recommendation. Not itself a build plan — it grades three candidate
> verifier slices and names the one worth a full design plan, so the next plan is chosen from
> evidence rather than intuition. Produced by a 3-analyst adversarial survey + cross-rank
> (2026-06-04), each slice pressure-tested against the §5a mirror-verifier trap and the 660:30
> false-block ratio.
>
> **One line.** docs/143/144 banked the **Integrity** slice (`arg_provenance`, vanishes on a
> strong model); docs/145 took the **loop-economics / Task-Completion** slice (the
> `tool_stream` stall reader, value independent of minting). That leaves three candidate
> targets the audit named but never built: **Policy/Permission Compliance** (the benchmark's
> *weakest* class), the **Refusal subset** (30 infeasible tasks, zero-side-effect scoring),
> and **cross-call contradiction** (self-consistency). This survey grades all three on
> headroom × cleanliness × buildability and finds **two of them are the same mechanism**
> pointed at two corpora — so the winner is **one plan that serves both**, and the third is an
> honest near-zero to be declined.

---

## 0. The frame — why a survey before a plan

The operator asked, after docs/145, "if there are other slices that would make sense to look
at we can do that too," and chose to **map the candidates first**. Good discipline: each of
these slices *looks* promising in isolation, but the doctrine constraints (no planner, the
§5a trap, the 660:30 ratio) kill the obvious version of most of them, and only the residue
survives. The survey's job is to find which residue is worth a build — measured on three axes:

- **Headroom** — realistic pp on a cheap runnable model, given the slice's measured weakness.
- **Cleanliness** — distance from the §5a mirror-verifier trap (does the byte-author question
  smuggle in a self-authored satisfaction predicate?).
- **Buildability** — pure kernel leaf / driver / config; how much new mechanism it needs.

(A fourth axis, **false-block-safety** vs the 660:30 ratio, is scored too — all three floor to
WARN structurally, so none can honestly reach a BLOCK on its core signal.)

---

## 1. Slice A — Policy/Permission Compliance (the precursor-PRESENCE half only)

**The target.** Policy/Permission is the **weakest verifier class everywhere** (ITSM 30 %,
CSM 45.5 %, HR 50.4 %) — the biggest nominal headroom. The policy doc (Appendix C) is a
*parseable precondition grammar* ("first call a permission check"), not open prose, so it
splits cleanly:

- **Half-A (byte-clean):** *"Does the result of a mandated permission-check tool appear in
  env-authored bytes before this mutating call?"* — `arg_provenance`'s shape re-aimed from
  *is-this-id-minted?* to *is-a-precursor-result-present?*. Decidable from corpus bytes alone
  (a prior `TOOL_RESULT` whose tool-name is on the declared mandated-precursor set), no answer
  key. Self-contained byte question, no event-to-event binding — survives §5a for the same
  reason `arg_provenance` does.
- **Half-B (the trap):** *"Does the policy FORBID this action?"* — NL prohibition-inference,
  forgeable, the brutal 660:30 downside. **Off-limits.**

**Where the obvious version slides into half-B.** The instant you bind the precursor *to this
action* — "is *this* DENIED result FOR *this* mutation, on *this* resource?" — you are asking
**provenance-of-a-RELATION**: a join the agent narrates (which precursor, on which row,
satisfies which clause), agent-authored from agent-visible prose, forgeable. **What must be
cut:** any resource-identity match, any clause-satisfaction predicate, any ordering claim
stronger than corpus-index. Only the *type-level* presence question survives.

**The REFUTED stance — ruthlessly, not a free strengthening.** `evidence.believe_under_floor`
ships an unused `REFUTED` value (a positively-witnessed "the check returned DENIED," stronger
than mere absence). But REFUTED *for this action* re-imports the binding just cut: a
`TOOL_RESULT` read through the agent's own MCP tool is `OS_RECORDED` on its **bytes** but the
**predicate** ("this deny pertains to M") is agent-authored — so the floor cannot honestly
mint strong REFUTED. REFUTED-presence buys a *recordable WARN annotation*, **never** a BLOCK
trigger. The moment REFUTED-presence drives an actuating rung, it has crossed into the
mirror-verifier.

**Headroom.** Half-A catches only the *absent-precursor* sub-mode (the named "Missing
Prerequisite Lookup"), not *wrong-resource* or *forbidden-action* (those are half-B). Realistic
**+1 to +3 pp on the Policy slice** for a cheap model; caps: the precursor list must be parsed
from Appendix C (not inferred), WARN-only keeps the gain small-but-real, and most policy
failures are half-B NL-prohibition (off-limits).

**Scores — Headroom 3 · Cleanliness 3 · Buildability 4 · False-block-safety 4. Verdict:
maybe** — worth a plan *only* scoped to type-level precursor-presence at WARN, REFUTED demoted
to annotation, action-binding explicitly forbidden.

---

## 2. Slice B — the Refusal subset (a zero-side-effect gate over the call stream)

**The target.** 30 infeasible tasks; correct refusal = **decline AND leave zero side effects**
(~10 checks each); best model only 50 %. Structurally new for DOS.

**The byte-clean question — and the line it must not cross.** *Not* "is this task infeasible?"
(that needs the policy grammar + DB state, an agent-authored read). The honest, narrower
version: **"did the agent emit a mutating call before the env returned the result the policy
names as that call's mandated precursor?"** Env-authored bytes: the ordered call stream
(`dos_react` already accumulates `prior_tool_results`, each tagged `is_mutating`, gym-authored)
+ the *presence* of a literal precursor token in prior `TOOL_RESULT` bytes. The gate is
byte-clean **only at the weakest binding: precursor-tool-was-never-called — never
precursor-result-was-favorable.** It checks *firing*, not *adjudication*.

**The inverted 660:30 calculus — and why it does not bite.** Here a false "infeasible, refuse"
would land on a *feasible* task (aimed at the 660 — the kill-signal). The bound that saves it:
**this gate never asserts infeasibility.** It fires only on *mutating-call AND its named-literal
precursor absent* — which is *also a real bug on a feasible task* (acting before the mandated
lookup = the "Missing Prerequisite Lookup" / "Cascading State Propagation" failure modes). So a
fire on a feasible task is a **correct nudge, not a false-block**, provided the intervention is
WARN (re-surface "you have not yet called the mandated check," preserve the turn). Residual
false-block risk collapses to a literal-token *miss* (an alias/synonym tool name), bounded by
the same casefold/alias allow-list `arg_provenance` already carries.

**Moves the slice WITHOUT a planner — the key asymmetry.** The gate cannot decide *decline*;
it can decide *zero-side-effects-so-far* — flag the first mutating call whose mandated precursor
never fired. On a genuinely infeasible task there *is* no satisfying precursor, so every mutating
attempt trips the gate → the agent is steered toward emitting no mutation → the "zero side
effects" half is achieved **mechanically, with no feasibility verdict.** The "state the policy
reason" half still needs the model; the gate only suppresses the side-effect — the half the
verifier scores hardest.

**Headroom.** N=30 is small (~2.6 % of 1,150) but headroom-per-task is large (50 % floor,
side-effects the dominant miss): plausibly flips 3–6 of the 30 → **+0.3 to +0.5 pp aggregate,
but +10–20 pp on the refusal verifier-slice itself** — and it **generalizes**: the same gate
catches Cascading-State-Propagation skips on *feasible* Policy tasks, so its reach exceeds the 30.

**Scores — Headroom 3 · Cleanliness 3 · Buildability 5 · False-block-safety 4. Verdict: build
it** — a config-declared *precursor-firing* gate (literal tool-presence only, WARN-default,
REFUTED-on-absence as annotation); it dies the instant it judges whether a precursor *result*
authorized the act.

---

## 3. Slice C — cross-call contradiction (self-consistency)

**The target.** The agent passed `status="closed"` to one tool and `status="open"` to another
for the same record in one task — a contradiction detectable from its own call stream. Or:
referenced an id as a parent FK that it deleted in a prior call.

**Is it even byte-clean?** Yes, surprisingly — but for a subtle reason. The agent authored both
calls, so naively this is the blackboard disease (adjudicating self-reports against self-reports,
[[project-dos-memory-is-an-unverified-agent]]). But the §5a test is not "who authored the bytes"
— it is "what predicate, from whose prose." Here the predicate is **structural identity and
inequality of two byte-strings the agent already emitted** (`call_i.args["status"] == "closed"`
AND `call_j.args["status"] == "open"`, same record, same key, i≠j). That binds two emitted
strings with `==`/`≠` — self-contained, makes **no claim about which value is correct** — so the
*relation-between-them* is an OS-recorded structural fact, not an agent-authored rubric. The line:
the moment you ask "is `closed` the *right* terminal status for this task," you're dead.

**Detectable vs out-of-scope.** Structurally detectable: conflicting scalar (same `(record_id,
arg_key)`, two unequal values), use-after-delete, double-create. Out (needs a semantic model):
field synonymy (`state=3` vs `status="closed"`), unit normalization, "are these two records the
same entity" (= entity resolution, an agent-authored relation).

**Headroom — honest: near-zero, and shrinking.** Self-contradiction within one task is the *one*
failure mode a single-context ReAct loop is structurally good at avoiding — each call is
conditioned on the same growing context window, so the model rarely flips a scalar it just wrote.
The four named EnterpriseOps modes are all "the agent is *consistently* wrong," not
"*inconsistent*." Use-after-delete is the only sub-class with plausible incidence, and it
**overlaps `arg_provenance`'s territory and the Integrity verifier** — so even its small catch is
largely double-counted.

**The false-fire killer.** A legitimate `open → closed` transition *is* the task; a
delete-then-recreate is a valid workflow. Without a planner you cannot know the intended
trajectory. The only honest discriminant is structural-not-semantic: fire only on
*simultaneously-live* incompatible assertions (same id passed `open` and `closed` in two parallel
args of one step), never a monotone sequence. That narrows the catchable set to almost nothing —
which is the honest answer, not a bug.

**Scores — Headroom 1 · Cleanliness 4 · Buildability 4 · False-block-safety 4. Verdict: decline**
— the cleanest predicate but the least valuable; build only as a thin REFUTED-emitting footnote
on the precursor-gate plan, never its own plan.

---

## 4. The cross-slice finding — A and B are the SAME fold

The composite ranking (Refusal 3.75 · Policy 3.5 · Contradiction 3.25) hides the load-bearing
structural fact:

> **Slice A and Slice B are one mechanism pointed at two corpora.** Both reduce to *"does a tool
> whose name is on a config-declared mandated-precursor set produce a result before this mutating
> call?"* — `arg_provenance._component_found` over `_build_env`, re-aimed from
> *is-this-value-minted* to *is-a-precursor-present*. They differ only in **where the fire is
> scored**: Slice A scores precursor-presence on the *feasible* corpus (the 660 — catching
> Missing-Prerequisite-Lookup → the Policy slice); Slice B scores the same absence on the
> *infeasible* corpus (the 30 — where every mutating attempt necessarily trips it → side-effect
> suppression → the Refusal slice). **One pure leaf, two slices harvested.**

This is why the recommendation is not "pick A or B" but "build the one fold that serves both" —
and why the buildability product is taken over a single 5/4 build, not two.

| Slice | Headroom | Cleanliness | Buildability | False-block-safety | Composite | The catch |
|---|---|---|---|---|---|---|
| **A — Policy precursor-presence** | 3 | 3 | 4 | 4 | 3.5 | Reaches only the absent-precursor sub-mode; REFUTED + action-binding slide into §5a. |
| **B — Refusal zero-side-effect gate** | 3 | 3 | 5 | 4 | 3.75 | Byte-clean only at precursor-*firing*; one step toward "did it *authorize*" = mirror-verifier. |
| **C — Cross-call contradiction** | 1 | 4 | 4 | 4 | 3.25 | Cleanest predicate, but targets the mode a single-context ReAct loop avoids → near-zero lift. |

---

## 5. The recommendation

**Build the precursor-presence gate as ONE plan (a future docs/147) serving both the Refusal
subset and the Policy/Permission slice.** It wins on the headroom × cleanliness × buildability
product because:

- **Headroom (summed across two slices over one build).** On the 30: suppress side-effects
  (the half the refusal verifier scores hardest) → +10–20 pp on that verifier-slice, +0.3–0.5 pp
  aggregate. On the 660: catch Missing-Prerequisite-Lookup / Cascading-State-Propagation on
  feasible Policy tasks (the weakest class) → +1–3 pp on the Policy slice. Neither half clears
  the bar alone; **summed over one shared fold, they do.**
- **Cleanliness.** Survives §5a exactly as `arg_provenance` does — *as long as it checks
  firing, not adjudication.* The dead-line is explicit: never "did the precursor result
  *authorize* this action on this resource" (provenance-of-a-relation, agent-authored).
- **Buildability.** Reuses the precursor-presence fold + the already-tagged `is_mutating` call
  stream + the **shipped** WARN-default intervention ladder. One thin pure leaf + one config
  table + consumer wiring. No kernel I/O, no planner.

**The honest anti-recommendation: decline cross-call contradiction.** It is the cleanest of the
three (a `==`/`≠` over two emitted strings is genuinely self-contained), which is exactly what
makes it seductive to a kernel author optimizing for §5a-distance — *resist it.* Its headroom is
near-zero (the mode a single-context ReAct loop avoids), and its one live sub-class
(use-after-delete) overlaps `arg_provenance` + Integrity, so its small catch is double-counted.
Spending a design plan on it spends one on single-digit tasks mostly already counted elsewhere.

**The caveat on the winner:** REFUTED ships as a recorded WARN-only annotation, never a BLOCK
trigger — "a deny-token exists" is byte-clean as an unconditional fact, but "this deny is FOR
this mutation" re-imports the binding the floor will not honestly mint (`evidence.py`). The
moment docs/147 lets REFUTED-presence drive an actuating rung, it is the mirror-verifier.

---

## 6. Sketch of the follow-on plan (docs/147, if greenlit)

**Title: the precursor-presence gate — a config-declared firing check serving the refusal +
policy slices.**

- **Byte-author question:** *"Does a tool whose name is on the config-declared mandated-precursor
  set produce ANY result in env-authored `TOOL_RESULT` bytes before this mutating call's corpus
  index?"* — provenance-of-a-precursor-*presence*, self-contained, survives §5a as
  provenance-of-a-string does. **Explicitly forbidden (the non-goal, stated up front):** any
  resource-identity match, any clause-satisfaction predicate, any "did the precursor *result*
  authorize this action" — provenance-of-a-RELATION, agent-authored, dead.
- **Layer:** a **pure kernel leaf** `precursor_gate.classify(CallStream, PrecursorGrammar, policy)
  -> {ATTESTED, REFUTED, NO_SIGNAL}` (the `liveness.classify` / `believe_under_floor` shape),
  reusing `arg_provenance._component_found` / `_build_env` for the presence fold. The grammar is
  **config-as-data** in `dos.toml [precursor]` (`mutating_tool -> required_precursor_tool`,
  Appendix-C-derived, **never inferred** — inferring it *is* parsing policy = planner-adjacent).
  Consumer (`dos_react`) folds the already-accumulated `prior_tool_results`. Mechanism kernel,
  precursor map the seam, enforcement consumer opt-in (PDP-not-PEP).
- **Intervention rung:** **WARN-default, BLOCK structurally unreachable** for this signal —
  "mandated precursor absent" is inherently LOW confidence (you cannot prove a check was
  *required* without the relation you cut), so it floors to a re-surfacing nudge that preserves
  the turn and is a *correct* nudge even on a feasible task. REFUTED-on-absence is a recorded
  annotation only (the docs/143 §13 / docs/144 −9 pp over-enforcement lesson, made structural).
- **Experiment-ladder rung:** a paired EnterpriseOps-Gym run (cheap model, the docs/143 harness)
  gated on **two required conditions:** (a) refusal-verifier pass-rate up on the 30 infeasible
  tasks **AND** Policy/Permission slice up on the 660 feasible tasks; (b) **the kill-signal:
  feasible-task aggregate pass-rate must NOT be down** — any feasible regression vetoes the ship
  regardless of the refusal gain (the 660:30 false-block guard, the intervention-cost rule
  encoded as a gate). Report both verifier deltas *and* the feasible-rate delta as a floor, never
  a single headline.

---

## 7. Where this sits in the slice map

| Slice | DOS status | Doc |
|---|---|---|
| Integrity (FK validity) | **banked** (vanishes on a strong model) | docs/143 + docs/144 |
| Task Completion / horizon (loop economics) | **planned** (the durable, minting-independent edge) | docs/145 |
| **Policy/Permission + Refusal (precursor presence)** | **recommended next** (one fold, two slices) | this survey → docs/147 |
| Cross-call contradiction | **declined** (clean but near-zero) | — |

The throughline across all four: **DOS only ever asks env-authored byte questions** — is this id
minted (143), did this result repeat (145), did this mandated precursor fire (147) — and it never
asks the agent-authored relation question (did the precursor *authorize* the act / is the agent
*succeeding*) that the §5a mirror-verifier trap is made of. Each slice is the same discipline
re-aimed; the survey's value is knowing which re-aim pays.

**Cross-refs:** the byte-author / §5a discipline = docs/141 + docs/143 §5a; the fold this reuses
= `src/dos/arg_provenance.py` (`_component_found` / `_build_env`); the evidence floor + the unused
REFUTED stance = `src/dos/evidence.py`; the shipped intervention ladder the caps depend on =
`src/dos/intervention.py` + docs/144; the loop-economics sibling slice = docs/145.

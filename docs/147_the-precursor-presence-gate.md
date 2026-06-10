# 147 — The precursor-presence gate: one firing-check serving the refusal + policy slices

> **Status:** the **kernel is BUILT + GREEN** (2026-06-04). `src/dos/precursor_gate.py` (the
> pure leaf `classify_call` + the `precursor_intervention` REFUTED→WARN map),
> `src/dos/precursor_gate_eval.py` + `dos precursor-gate-eval`, the `dos.toml [precursor]` config
> seam (`SubstrateConfig.precursors`), and 26 tests all shipped; the full suite is green (2128
> passed). **What remains:** the consumer wiring in `dos_react.py` + a **hand-authored grammar**
> from the gym's per-task prose + the paired A/B run (§6, re-scoped to the real corpus after the
> §0 gym-reality probe). Greenlit by docs/146, which graded three candidate verifier slices and
> found **two of them are the same fold**: the slice survey's winner, scoped here to the one
> byte-clean question that survives the §5a mirror-verifier trap.
>
> **One line.** docs/143's `arg_provenance` asks *"did the model MINT this id, or RESOLVE
> it?"* — a check on **provenance-of-a-string** that vanishes on a strong model (a model that
> reads-before-it-writes mints nothing). docs/146 found one more byte-clean question of the
> same shape, on two corpora at once: *"did a tool whose name is on a config-declared
> mandated-precursor set produce **any** result in env-authored bytes before this mutating
> call?"* — **provenance-of-a-precursor-presence**. On the **660 feasible** tasks it catches
> *Missing-Prerequisite-Lookup* / *Cascading-State-Propagation* on the benchmark's **weakest
> verifier class** (Policy/Permission); on the **30 infeasible** tasks every mutating attempt
> necessarily trips it, so the agent is steered toward **emitting no side effect** — the half
> the refusal verifier scores hardest — **with no feasibility verdict.** One pure leaf, two
> slices harvested.
>
> **Lineage.** docs/146 §6 is the sketch this plan fills out. The *pattern* it lifts is
> `arg_provenance`'s — casefold + alias normalization + a pure scan over an env-authored
> corpus the consumer already accumulates — re-aimed from *is-this-id-value-minted* to
> *did-this-precursor-name-fire* (a structural membership scan over the call stream's
> `tool_name` fields, NOT a substring/token trace over result bytes — see §2/§9.1, the one
> place this plan diverges from a literal `_build_env`/`_component_found` reuse). The
> byte-author / §5a discipline it must survive is docs/141 + docs/143 §5a. The actuation it
> rides is the **already-shipped** intervention ladder + `Intervention.WARN` rung
> (`src/dos/intervention.py` + docs/144) — mapped DIRECTLY (the `tool_stream` precedent), not
> via `choose_intervention` (which is typed to a `ProvenanceVerdict` this gate does not
> produce — see §4/§5). The `EvidenceStance` vocabulary it reuses (`ATTESTED/REFUTED/NO_SIGNAL`)
> lives in `evidence.believe_under_floor` (`src/dos/evidence.py`); this gate gives `REFUTED`
> *presence-absence* semantics, distinct from the OS-witnessed disconfirmation the
> `os_acceptance` driver already mints it for. The sibling it mirrors structurally is
> `liveness.classify` (a PURE verdict, evidence gathered at the boundary).

---

## 0. The one fact that makes this a single build, not two (verified in-tree, 2026-06-04)

docs/146's load-bearing structural finding, re-verified against the source before this plan:

> **Slice A (Policy precursor-presence) and Slice B (the refusal zero-side-effect gate) are
> ONE mechanism pointed at two corpora.** Both reduce to *"does a tool whose name is on a
> config-declared mandated-precursor set produce a result before this mutating call?"* They
> differ only in **where the fire is scored**: on the *feasible* 660 a fire catches the
> Missing-Prerequisite-Lookup pathology (→ the Policy slice); on the *infeasible* 30 every
> mutating attempt *to a grammar-covered tool* trips the same fire (no satisfying precursor can
> exist on an infeasible task), which steers the agent away from emitting a side effect (→ the
> Refusal slice). The fold is the same; the corpus it is scored over is what changes. (A
> mutating tool absent from the grammar is `NO_SIGNAL`'d and not suppressed — so the edge is
> bounded by grammar coverage of the mutating surface, which is exactly what the eval's
> `missed_precursor_recall` measures, §5.)

> **⚠ Gym-reality correction (probed against the real EnterpriseOps-Gym clone, 2026-06-04 —
> AFTER the first draft, BEFORE building).** docs/146 assumed a *parseable Appendix C* and a
> *marked set of 30 infeasible/refusal tasks*. **Neither exists in the real gym** (probed
> directly): (a) the precondition rules are **prose embedded in each task's `system_prompt`**
> (e.g. "Cases cannot be closed directly; they must first be moved to resolved, then to
> closed"), **not** a machine-readable grammar — so the `requires` map must be **hand-authored
> per task from that prose**, exactly the "written, never inferred" discipline §2/§8 already
> demand (inferring it from the prose *is* parsing policy = off-limits); (b) there is **no
> `feasible`/`infeasible` flag** and only ~13 tasks in the clone, so the "30-task refusal
> slice" framing is **dropped** — the gate's value is re-grounded on the *feasible* corpus
> (catching Missing-Prerequisite-Lookup), with side-effect-suppression a bonus on any task where
> a mandated precursor is genuinely skipped; (c) the **verifier scores final DB state +
> *unordered* tool-call presence only — it never audits ordering**, so the gate's *firing*
> signal is not what the verifier scores. The value is therefore **indirect, exactly as
> `arg_provenance`'s was**: a WARN re-surfacing "you skipped the mandated lookup" can make the
> agent *call it*, flipping a `tool_execution` presence-miss to a hit or producing the correct
> final state a `database_state` verifier checks. This correction does not change the
> *mechanism* (the leaf is built as specified) — it corrects where the grammar comes from and
> what the honest experiment is (§6, re-scoped).

Two further facts checked against the code, because they decide what "build" means:

1. **The firing fold is a trivial membership scan over a stream the consumer already builds.**
   `dos_react` already accumulates `prior_tool_results` (the env-authored blobs `arg_provenance`
   consults). The precursor question — *"does a prior call whose `tool_name` is on the mandated
   set exist earlier in the stream?"* — is a pure structural scan over the call list's
   `tool_name` field (`any(_casefold(c.tool_name) in precursor_set for c in stream[:idx])`),
   **cheaper** than `arg_provenance`'s id-component matcher. NB it does **not** reuse
   `_build_env`/`_component_found`: those fold over a prior result's *text tokens*, and a
   precursor tool's name is generally **absent** from its own result payload, so a token-trace
   would systematically MISS a fired precursor (a false REFUTED). The gate lifts the *pattern*
   (casefold + alias normalization + a pure scan over an already-accumulated env corpus), the
   same way `tool_stream` lifts `churn`'s run-length pattern without importing `churn` — §9.1.

2. **The actuation is shipped and consumer-wired.** `src/dos/intervention.py` ships the closed
   `OBSERVE < WARN < BLOCK < DEFER` ladder, `choose_intervention`, the refuse-LESS-only
   `InterventionPolicy` (validated twice), and `dos_react.py` already consumes all four rungs.
   This gate needs **no new rung** — it floors to WARN and reuses the existing ladder, exactly
   as docs/145's stall reader does.

So the deliverable is **one new pure leaf + its eval + one `dos.toml` table + consumer wiring**
— the same envelope as docs/145, and the kernel's no-planner / PDP-not-PEP / byte-author-only
doctrine stays intact by construction.

---

## 1. Why this is worth a build (the headroom, and its honest caps)

Policy/Permission is the **weakest verifier class everywhere** in the benchmark (ITSM 30 %,
CSM 45.5 %, HR 50.4 % — docs/146 §1) — the biggest nominal headroom DOS has not yet touched.
And the policy doc (the gym's Appendix C) is a **parseable precondition grammar** ("first call
a permission check"), not open prose, so it splits cleanly into a half DOS can own and a half
it must refuse:

- **Half-A (byte-clean, this plan):** *"Does the result of a mandated permission/lookup tool
  appear in env-authored bytes before this mutating call?"* Decidable from corpus bytes alone
  — a prior `TOOL_RESULT` whose tool-name is on the declared mandated-precursor set. No answer
  key, no held-out state, no self-authored satisfaction predicate.
- **Half-B (the trap, off-limits):** *"Does the policy FORBID this action?"* — NL
  prohibition-inference, forgeable, the brutal 660:30 false-block downside. **Never built.**

**The realistic envelope (docs/146 §5, ESTIMATE — not a promise):**

- On the **30 infeasible** tasks: suppress side-effects (the half the refusal verifier scores
  hardest; the best model only reaches 50 %) → **+10 to +20 pp on the refusal verifier-slice
  itself, +0.3 to +0.5 pp aggregate** (N=30 is ~2.6 % of 1,150). *Bounded by grammar coverage*
  — the suppression fires only on mutating tools the host declared a precursor for, so the gain
  scales with how much of the mutating surface the agent reaches for on the 30 is grammar-covered.
- On the **660 feasible** tasks: catch Missing-Prerequisite-Lookup / Cascading-State-Propagation
  on the weakest class → **+1 to +3 pp on the Policy slice.**
- **Neither half clears the bar alone; summed over one shared fold, they do.** That is the
  whole reason docs/146 recommended *this* fold over the cleaner-but-near-zero
  cross-call-contradiction slice (declined, §6).

**The caps, stated up front so the experiment ladder can falsify them:**

- Half-A catches only the **absent-precursor** sub-mode, never *wrong-resource* or
  *forbidden-action* (those are Half-B). Most policy failures are Half-B NL-prohibition —
  off-limits — so the gain is small-but-real, not a category win.
- The precursor list must be **parsed from Appendix C as data**, never inferred — inferring it
  *is* parsing policy, which is planner-adjacent and off-limits (§2, §8).
- WARN-only keeps the gain small but keeps it **safe** (§4). The moment the gate reaches for a
  BLOCK on this signal it has crossed into the mirror-verifier (§3).

---

## 2. The mechanism — `dos.precursor_gate`, a firing-check over the call stream

A new **pure kernel leaf**, the `arg_provenance.classify_call` / `liveness.classify` sibling
re-aimed from *id-mintage* onto *precursor-firing*:

```
classify_call(MutatingCall, CallStream, PrecursorGrammar, policy) -> PrecursorVerdict
```

- **`MutatingCall`** — the call under scrutiny: `tool_name` (normalized) + `is_mutating`
  (set by the consumer's fail-open write-verb classifier, the same `is_mutating_tool` the
  `arg_provenance` consult already uses). A read / non-mutating call short-circuits to
  `NO_SIGNAL` — reads are how a precursor result *enters* the stream, never gated, exactly as
  `arg_provenance` never gates a read.
- **`CallStream`** — a frozen tuple of `PriorCall(tool_name, result_blob)` in call order — the
  env-authored bytes the agent has already seen, **the same `prior_tool_results` the
  `arg_provenance` consult already accumulates** in `dos_react`. The kernel parses no JSON and
  reads no clock; the consumer flattens each result to a string at the boundary (the
  `build_prior_results` idiom). `result_blob` is reused only for the legibility note; the
  *firing* decision keys on `tool_name` alone (see §3 — the byte-author of the *name* in the
  stream is the env, recorded when it returned that result).
- **`PrecursorGrammar`** — `{mutating_tool_name -> required_precursor_tool_name(s)}`, the
  **config-as-data** map declared in `dos.toml [precursor]` (`§5`). Appendix-C-derived,
  **never inferred** — a host writes the map by reading the policy doc once, the same way it
  writes its lane taxonomy. A mutating tool with no entry has no mandated precursor → the gate
  `NO_SIGNAL`s it (the absent-key safe direction, like an empty corpus in `arg_provenance`).
- **`PrecursorVerdict`** — `ATTESTED / REFUTED / NO_SIGNAL`, reusing the **`EvidenceStance`
  vocabulary** (`src/dos/evidence.py`) — it is, after all, a presence-of-evidence question.
  (The *vocabulary* is reused; the **`REFUTED` semantics differ**: here it means "a mandated
  precursor produced no result in the stream" — presence-absence — not the OS-witnessed
  disconfirmation the `os_acceptance` driver mints it for. §3 makes that demotion structural.)
  - **ATTESTED** — a tool whose name is on the mandated-precursor set for this mutating call
    produced a result *earlier in the call stream*. The mandated lookup fired. No intervention.
  - **REFUTED** — the call is mutating, has a declared mandated precursor, and **no** such
    precursor result appears anywhere earlier in the stream. The actionable rung: the agent is
    about to mutate before the mandated check fired (the named "Missing Prerequisite Lookup" /
    "Cascading State Propagation" failure modes). **WARN-only** (§4).
  - **NO_SIGNAL** — the fail-safe zero: a read/non-mutating call, OR a mutating call with no
    declared precursor for its tool, OR an empty call stream (the first call — nothing could
    have fired yet, so we never accuse). Honest no-answer; never an intervention.
- **`PrecursorPolicy`** — mechanism is kernel, knobs are config (the `LivenessPolicy` /
  `ProvenancePolicy` seam): `case_sensitive` (casefold tool names by default, the
  `arg_provenance` bias), `alias_map` (a host's tool-name synonyms — `permission_check` ≡
  `check_access`, the literal-miss safety valve §3), and the *deliberate non-knob* noted below.

**The deliberate non-knob — no resource binding, no ordering knob beyond stream-index.** There
is no field for "which row the precursor was about," no "did the precursor result match this
mutation's resource," no clause-satisfaction threshold. Those are Half-B (§3). The only
ordering the gate knows is *corpus index* (the precursor result appears at a lower stream
index than the mutating call) — a structural fact about the env-authored stream, not an
agent-narrated join.

The firing fold is **new, trivial code** — a structural membership scan over the prior calls'
`tool_name` fields: `any(_casefold(c.tool_name) in precursor_name_set for c in stream[:idx])`,
where `precursor_name_set` is the declared mandated set expanded by the `alias_map` and compared
under casefold. It deliberately does **not** reuse `arg_provenance._build_env` /
`_component_found` (which fold over a prior result's *text tokens* — a precursor tool's name is
generally absent from its own result payload, so a token-trace would systematically MISS a fired
precursor, a false REFUTED). It lifts only the *pattern* — casefold + alias normalization + a
pure scan over an already-accumulated env corpus — the same way docs/145's `tool_stream` lifts
`churn`'s run-length pattern *without importing* `churn`: same shape of pure leaf, different
(and here simpler) fold.

---

## 3. Why it is byte-clean — the §5a survival argument, and the exact dead-line

This is the crux, and it is the same test every survivor slice must pass: walk the provenance
of each field, because that is the only honest check.

| Field of a `PriorCall` | Byte-author | Forgeable by the judged agent? |
|---|---|---|
| `tool_name` (the call the agent *issued*) | the **agent** | yes — but we do not adjudicate on the agent's *chosen* call |
| **the PRESENCE of a result** for a precursor-named tool in the stream | the **gym MCP server** (it produced the result, recording that the tool *fired*) | **no** — env-authored: the result exists iff the env executed the tool |

The gate's only question is: **"did the env author a result for a tool whose name is on the
config-declared mandated-precursor set, before this call's stream index?"** That is
**provenance-of-a-precursor-*presence*** — a pure byte question about *env-authored* bytes
(the result the gym returned), keyed by the config-declared name. The agent did not author the
*existence* of a tool result; the gym did, by executing the tool. So the signal cannot be
forged in the agent's favor — it survives §5a for the **same reason `arg_provenance` does**:
the corpus is built only of env-authored blobs, and the predicate is a presence-of-bytes test,
not a satisfaction predicate.

**The dead-line — stated up front as the non-goal (the §5a discipline made structural):**

The instant the gate binds the precursor *to this action* — "is *this* DENIED result FOR
*this* mutation, on *this* resource, satisfying *this* clause?" — it is asking
**provenance-of-a-RELATION**: a join the agent narrates (which precursor, on which row,
satisfies which clause), authored from agent-visible prose, **forgeable in the agent's favor.**
What is forbidden, explicitly, and absent from the type by construction:

- **No resource-identity match.** The gate never asks "was the precursor about the same record
  the mutation touches." (That binding is what `arg_provenance` *deliberately cut* — see its
  module doc: `believe=True` means only "no id minted from nowhere," never "the args are
  correct".)
- **No clause-satisfaction predicate.** The gate never asks "did the precursor result return a
  value that *authorizes* the action." A `TOOL_RESULT` read through the agent's own MCP tool is
  `OS_RECORDED` on its **bytes** but the predicate "this deny pertains to M / this allow
  authorizes M" is **agent-authored** — so the floor cannot honestly mint it.
- **No ordering claim stronger than corpus-index.** "The precursor came before the mutation in
  the stream" is structural; "the precursor *logically precedes* this action in the policy's
  required sequence" is a narrated plan-relation — off-limits.

**The REFUTED stance — borrowed, but with weaker semantics, ruthlessly.** `evidence.py`'s
`REFUTED` value already carries a *positively-witnessed disconfirmation* meaning — the
`os_acceptance` driver mints it on a non-zero exit code (`drivers/os_acceptance.py`), and
`believe_under_floor` consumes it as `BeliefVerdict.refuted` (so it is shipped, consumed, and
test-pinned — **not** an unused slot). The precursor gate deliberately does **not** adopt that
strong semantics. It is tempting to mint the strong version here: "the precursor returned
DENIED, so this action is forbidden." **Resist it.** REFUTED *for this action* re-imports the
binding §3 just cut — "this deny pertains to M" is the agent-authored relation. So this gate's
REFUTED means **only** *"a mandated precursor for this tool produced no result in the stream"*
(presence-absence, a byte fact), and it buys a **recorded WARN annotation, never a BLOCK
trigger.** The moment REFUTED-presence drives an actuating rung it has crossed into the
mirror-verifier — and §4 makes that structural, not a discipline a future editor can erode.

**The residual false-fire risk, and why it does not bite (docs/146 §2):** a false REFUTED would
fire on a *feasible* task where the precursor *did* fire under an **alias** the grammar did not
list (a synonym tool name). But a fire on a feasible task is a **correct nudge, not a
false-block** — "you have not yet called the mandated check" is a *real* bug on a feasible
Policy task too (the Missing-Prerequisite-Lookup mode), provided the intervention is WARN
(re-surface the reminder, preserve the turn). So the residual risk collapses to a literal-token
*miss*, bounded by the same casefold + `alias_map` allow-list `arg_provenance` already carries
— and even when it misses, the cost is a redundant reminder, not a withheld call.

---

## 4. The intervention — WARN-default, BLOCK structurally unreachable for this signal

The precursor gate rides docs/144's **already-shipped** ladder and its `Intervention.WARN`
rung — but **not** via `choose_intervention`. That function is typed to a `ProvenanceVerdict`
(it reads `.believe` / `.unsupported` / each `ArgProvenance.components_checked`), and a
`PrecursorVerdict` carries none of those fields, so there is **no confidence to assess** for
this verdict type — `assess_confidence` cannot run on it, and "pinned LOW confidence" would
name a mechanism that does not exist. Instead the consumer maps the precursor *stance* DIRECTLY
to a ladder rung (the docs/145 `tool_stream` precedent — that kernel leaf returns only a
`StreamVerdict`, and its consumer maps it to a WARN without calling `choose_intervention`):

```
REFUTED            -> Intervention.WARN   (the only fired rung — re-surface the requirement)
ATTESTED / NO_SIGNAL -> no intervention   (dispatch unchanged)
```

A tiny `precursor_intervention(PrecursorVerdict) -> InterventionDecision` (kernel leaf, beside
`classify_call`, reusing the shipped `Intervention` / `InterventionDecision` vocabulary)
owns this two-line map. The mapping, and why the strong rung is **out of reach by
construction**:

- **REFUTED → WARN.** Attach an advisory result that re-surfaces the policy's own requirement:
  *"This mutating call (`create_change`) has not been preceded by a result from its mandated
  precursor (`check_change_authorization`). The policy requires that lookup first — issue it,
  then retry."* The call **still dispatches** (the agent is informed without losing the turn —
  the docs/144 WARN doctrine that recovered the −9 pp). It fabricates nothing: the reminder
  names a config-declared *requirement*, not a synthesized DB row.
- **BLOCK / DEFER are unreachable because the map never emits them.** Unlike `arg_provenance`
  (where a HIGH-confidence whole-value-absent mint earns the turn-preserving BLOCK), the
  precursor map's *only fired output is WARN* — there is no rung above it to escalate to, no
  ceiling knob a host can raise, and no `ProvenanceVerdict`/`InterventionPolicy` clamp in the
  path. "Mandated precursor absent" *cannot honestly carry a BLOCK's confidence* (you cannot
  prove a check was *required for this specific action* without the resource/clause relation §3
  cut), and the wiring reflects that directly: the gate emits a fixed WARN, full stop. This is
  **stronger** than a `ceiling=WARN` policy clamp (which a host could in principle re-tune):
  there is no policy object to re-tune — the rung is a literal in the gate's own two-line map.
- **Never DEFER, never a cut.** DEFER spends the turn (the −9 pp posture); a cut *fails* the
  feasible task it fired on. The gate's job is to *re-surface the requirement*, not to stop.

This is the **docs/143 §13 / docs/144 −9 pp over-enforcement lesson made structural**, and it
is *stronger* than docs/145's stall reader: there, BLOCK was opt-in-but-available behind a
ceiling; here, BLOCK is **absent from the gate's output type** — the leaf only ever recommends
WARN, so no host configuration can make it act harder.

---

## 5. Where it lives (the layering — kernel stays pure, actuation stays consumer-side)

- **Kernel (mechanism) — NEW:** `src/dos/precursor_gate.py`. The pure
  `classify_call(MutatingCall, CallStream, PrecursorGrammar, policy) -> PrecursorVerdict` (a
  structural `tool_name`-membership scan over the stream, §2/§9.1 — **not** a `_build_env` /
  `_component_found` token-trace) + the tiny `precursor_intervention(PrecursorVerdict) ->
  InterventionDecision` direct-map (§4). Frozen dataclasses in/out, no I/O, names no host. The
  `arg_provenance.classify_call` / `liveness.classify` sibling. It reuses
  `evidence.EvidenceStance` (`ATTESTED/REFUTED/NO_SIGNAL`) for its verdict vocabulary and the
  shipped `Intervention` / `InterventionDecision` for its WARN map — both sibling kernel imports
  (allowed: the enforced line is "no host, no I/O policy," not "no sibling import" — the
  `loop_decide`→`gate_classify` / `journal_delta`→`lane_journal` pattern). It imports
  `arg_provenance` only for the shared `_casefold`/normalization helper (or re-implements the
  one-liner) — *not* its id-matcher.
- **Kernel (eval) — NEW:** `src/dos/precursor_gate_eval.py` + `dos precursor-gate-eval`. The
  per-axis eval harness (the `intervention_eval` / `overlap_eval` / `judge_eval` discipline): a
  confusion grid over replayed call streams (REFUTED/ATTESTED vs a labelled
  *was-the-precursor-actually-required-and-skipped*) + **the two rates a deployer cares about**
  — `missed_precursor_recall` (of real prerequisite-skips, the fraction the gate fired on) and
  **`false_refute_rate`** (REFUTED fired on a feasible task whose precursor fired under an
  unlisted alias — the §3 residual, the alias-coverage instrument). Like `intervention_eval`,
  the labels are the **researcher's ground truth from executed replay**, never the gate's own
  output. This is what makes the grammar + `alias_map` **calibratable from data**, per
  deployment.
- **Config — `dos.toml [precursor]`:** the grammar as closed-config-as-data (the
  `[liveness]` / `[intervention]` / `[arg_provenance]` pattern), loaded at the boundary via a
  `load_from_toml`-style reader that mirrors `intervention.load_from_toml` (BOM-stripping
  `utf-8-sig`, additive, a missing/empty table degrades to an empty grammar = the gate
  `NO_SIGNAL`s everything — never an error):

  ```toml
  # Appendix-C-derived mandated precursors: a mutating tool -> the lookup/permission
  # tool whose result must appear in the stream first. NEVER inferred — written by
  # reading the policy doc once, the way lanes are written by reading the dir tree.
  [precursor]
  case_sensitive = false
  [precursor.requires]
  create_change      = ["check_change_authorization"]
  assign_incident    = ["get_assignment_group", "check_assignment_permission"]
  [precursor.aliases]
  check_access = ["check_change_authorization", "check_assignment_permission"]
  ```

- **Consumer (benchmark-side) — `dos_react.py`:** accumulate the `(tool_name, result_blob)`
  stream alongside the existing `prior_tool_results` corpus (it already does — this reuses
  it); before each mutating call, fold `precursor_gate.classify_call`; on REFUTED, map it to
  the WARN rung via `precursor_gate.precursor_intervention` (the direct stance→rung map, §4) and
  attach the re-surfacing ToolMessage through the existing WARN actuation branch in the loop —
  **not** via `choose_intervention` (which is `ProvenanceVerdict`-typed and reads fields the
  precursor verdict does not carry). One consult, the `arg_provenance` consult's sibling.
  **Imports `dos`, lives benchmark-side, never in the kernel** (the one-way arrow). The two
  consults compose: a call can be both a mint (arg_provenance WARN) and a prerequisite-skip
  (precursor WARN); the consumer takes the more-informative-but-no-more-disruptive of the two
  recommendations (both floor to WARN, so the union is two reminders, never an escalation).

The litmus held: the kernel **recommends** (a verdict + a re-surfacing reminder naming the
config-declared requirement) and **scores** (the eval); it **never actuates**, **never
fabricates** a result, and **never asks whether the precursor *authorized* the act.** PDP, no
PEP. The whole edge comes from a pure presence-of-env-bytes byte question — never a
self-authored relation.

---

## 6. The experiment ladder (re-scoped to the REAL gym corpus after the §0 probe)

The §0 gym-reality correction **rewrites this section**: there is no parseable Appendix C and no
marked 30-task refusal split, so the ladder cannot score a "refusal slice" vs a "feasible slice."
The honest re-scope grounds every rung on the **~13 real tasks** in the clone, with the grammar
**hand-authored from each task's `system_prompt` prose** (the "written, never inferred"
discipline). One change per rung, paired-seed, same model/tools/scorer, each gated on the
kill-signal. Pre-registered, falsifiable. The harness is the docs/143 cheap-model
EnterpriseOps-Gym run (`benchmark/enterpriseops/`, `gemini-3-flash`), reusing the paired A/B
plumbing the `arg_provenance` and `intervention` arms used.

| Rung | The ONE change vs below | What it measures | Promote iff | **Pre-registered prediction (ESTIMATE)** |
|---|---|---|---|---|
| **R-grammar** | hand-author `[precursor.requires]` from the prose of the ~13 tasks, run `dos precursor-gate-eval` on a labelled replay (NO live model) | grammar quality (offline) | `missed_precursor_recall` > 0 **and** `false_refute_rate` < 5 % | the grammar covers a real prerequisite the prose names; the eval is the gate, BEFORE any token is spent. Cheap, deterministic, zero-model. |
| **R0** | `react` baseline, no precursor consult | — | (control) | reference pass-rate on the ~13 tasks. |
| **R1** | `precursor_gate` **REFUTED → WARN** consult (wired in `dos_react`) | task pass-rate vs R0 | aggregate pass-rate ≥ R0 (the kill-signal) | **0 to +1 task** flipped (a prereq-skip re-surfaced → the agent calls the lookup → a `tool_execution` presence-miss or a `database_state` final-state flips to pass). Small-N: report the *count*, not a pp. **Falsified if pass-rate < R0** (the WARN derailed a run). |
| **R2** | **`aliases` calibrated from the R1 trajectory** (close any alias gap the run surfaced) | pass-rate + `false_refute_rate` | `false_refute_rate` down **and** pass-rate ≥ R1 | **0 to +1 marginal task; `false_refute_rate` → 0** on the replay. The calibration rung — the eval's payoff, now from the live trajectory not a 660-task split. |

**The kill-signal (the intervention-cost rule, encoded as a gate):** at **every** rung the
**aggregate task pass-rate must NOT be down.** Any regression **vetoes the ship** — the docs/143
§8 / docs/144 −9 pp lesson made a promotion gate. Because the gate is WARN-only (§4) a fire is a
correct-but-cheap reminder (the call still dispatches), so this is expected to stay green — but
it is the veto, not an afterthought.

**The honest small-N caveat (load-bearing).** ~13 tasks is far too few for a pp claim — a single
flipped task is ~8 pp of noise. So **R-grammar is the real deliverable**: a deterministic,
zero-model offline eval proving the grammar catches a prose-named prerequisite without
false-REFUTING, which is decidable on a labelled replay with **zero benchmark access** (the
keystone). The live R0/R1/R2 run is a *directional smoke test* — it can show the wiring works and
nothing regresses, but it cannot, at N=13, establish a headline number. A real pp claim needs the
full task set (not in the clone), which is the explicit boundary of what this build can prove.

**Why this order.** R-grammar first because it is cheap, deterministic, and the actual gate on
whether the grammar is worth a token — the eval *is* the experiment for the offline question. R0
→ R1 → R2 then verify the wiring end-to-end and that nothing regresses, with R2 closing any alias
gap the R1 trajectory surfaces (the `false_refute_rate` calibration, now from the live run).

---

## 7. The honest ceiling — and where it sits vs docs/143/144/145

State it plainly, because the survey already did (docs/146 §5):

- **The gain is single-digit and summed across two slices.** Neither half clears the bar alone;
  the build is justified by the **product** of a small-but-real Policy gain (+1–3 pp on the
  weakest class) and a large-per-task-but-small-aggregate refusal gain (+10–20 pp on a 30-task
  slice = +0.3–0.5 pp aggregate). **Do not promise a category win.** The +14–35 pp
  strategic-planning lever is forfeited by doctrine (it needs the oracle plan); this is a few
  points of Pareto movement on the **weakest existing class**, not a new ceiling.
- **It catches only the absent-precursor sub-mode.** *Wrong-resource* and *forbidden-action*
  are Half-B (NL-prohibition, off-limits). Most policy failures are Half-B — so the reachable
  slice is bounded, and the eval's `missed_precursor_recall` is the instrument that tells a
  host how much of *its* policy corpus is the catchable sub-mode.
- **Where it sits in the four-slice map (docs/146 §7):**

  | Slice | DOS status | Doc | The edge's durability |
  |---|---|---|---|
  | Integrity (FK validity) | **banked** | docs/143 + docs/144 | vanishes on a strong model (minting → 0) |
  | Task Completion / horizon (loop economics) | **planned** | docs/145 | **durable** — looping survives a stronger model |
  | **Policy/Permission + Refusal (precursor presence)** | **this plan** | docs/147 | **partly durable** — a strong model skips fewer precursors, but the *refusal side-effect-suppression* fires on any model that attempts a mutation *via a grammar-covered tool* on an infeasible task |
  | Cross-call contradiction | **declined** | — | clean but near-zero (the mode a single-context ReAct loop avoids) |

The single most defensible sentence: **docs/143/144 harden the substrate against an agent that
MINTS, docs/145 against an agent that LOOPS; this plan hardens it against an agent that ACTS
BEFORE THE MANDATED LOOKUP — and on the infeasible corpus that fire is structural (no precursor
can exist), so its side-effect-suppression edge does not depend on the model being weak.**

---

## 8. The honest non-goals (the dead-lines, restated so a future editor cannot erode them)

- **Not a policy interpreter.** The gate never *reads* the policy doc to decide whether an
  action is permitted — it reads a **config-declared map** a human wrote by reading the doc
  once. Inferring the precursor map from the policy text *is* parsing policy = planner-adjacent
  = off-limits. The map is DATA in `dos.toml`, never code, never inferred (§2, §5).
- **Not an authorization check.** The gate never asks "did the precursor result *authorize*
  this action / pertain to this resource / satisfy this clause." That is
  provenance-of-a-RELATION, agent-authored, forgeable — the mirror-verifier (§3). It asks only
  "did a mandated-precursor-named tool produce *any* result earlier in the stream."
- **Not a BLOCK.** The gate's stance→rung map (§4) emits **only WARN** — there is no rung above
  it in the precursor path, no ceiling knob, no `InterventionPolicy` clamp to re-tune. "Mandated
  precursor absent" cannot honestly carry a BLOCK's confidence (you cannot prove a check was
  *required for this specific action* without the relation §3 cut), and the wiring reflects that
  by construction: REFUTED-on-absence is a recorded WARN annotation, never an actuating rung,
  because the leaf's output type has no harder rung to reach.
- **Not a feasibility verdict.** The gate never asserts "this task is infeasible." On the 30 it
  achieves zero-side-effects **mechanically** — every mutating attempt *via a grammar-covered
  tool* on an infeasible task trips the absent-precursor fire, steering the agent toward emitting
  no mutation — *without* ever deciding feasibility (which would need the policy grammar + DB
  state, an agent-authored read). The suppression is bounded by grammar coverage of the mutating
  surface (the eval's `missed_precursor_recall`); the "state the policy reason" half still needs
  the model; the gate only suppresses the side-effect — the half the verifier scores hardest
  (docs/146 §2).
- **Not mandatory.** The floor stays advisory (WARN); the gate `NO_SIGNAL`s any tool with no
  declared precursor, so a host with an empty `[precursor]` table gets exactly today's
  behavior. The eval (`missed_precursor_recall` / `false_refute_rate`) is what tells a host
  whether declaring a grammar pays.

---

## 9. The DOS kernel changes implied (one new leaf + its eval + one config seam)

1. **NEW pure leaf `src/dos/precursor_gate.py`** — `classify_call(MutatingCall, CallStream,
   PrecursorGrammar, policy) -> PrecursorVerdict` (`ATTESTED/REFUTED/NO_SIGNAL`) + the tiny
   `precursor_intervention(PrecursorVerdict) -> InterventionDecision` direct stance→rung map
   (REFUTED → WARN, else no intervention). The `arg_provenance.classify_call` sibling re-aimed
   from id-mintage onto precursor-firing; the firing fold is a **new, trivial `tool_name`-
   membership scan** over the stream (NOT `_build_env`/`_component_found`, which token-trace
   result *bytes* — §2/§9.1). Reuses `evidence.EvidenceStance` for the verdict vocabulary and
   the shipped `Intervention`/`InterventionDecision` for the WARN map. *The one genuinely new
   mechanism.* Pure, no I/O, names no host.
2. **NEW eval `src/dos/precursor_gate_eval.py` + `dos precursor-gate-eval`** — confusion grid +
   `missed_precursor_recall` + `false_refute_rate`, labels from executed replay, never from the
   gate. The per-axis eval-friendliness discipline (`intervention_eval` / `overlap_eval` /
   `judge_eval` sibling), CI-gateable (exit non-zero on a `false_refute_rate` over a declared
   bound, the `overlap-eval`/`intervention-eval` exit-code analogue).
3. **`dos.toml [precursor]` seam** — `requires` (the grammar) + `aliases` + `case_sensitive` as
   closed-config-as-data, with a `load_from_toml`-style boundary reader mirroring
   `intervention.load_from_toml` (additive, BOM-safe, missing → empty grammar). Carried on
   `SubstrateConfig` like the other declared tables.
4. **No new intervention rung.** The gate maps REFUTED → the **shipped** `Intervention.WARN`
   rung directly (the `tool_stream` precedent), reusing the ladder's vocabulary +
   `InterventionDecision` shape. It does **not** reuse `choose_intervention` / `assess_confidence`
   / `InterventionPolicy` — those are `ProvenanceVerdict`-bound and read fields a
   `PrecursorVerdict` does not carry (§4). The consumer wiring in `dos_react.py` is one consult
   beside the existing `arg_provenance` consult, feeding the existing WARN actuation branch.

**Net:** exactly **one new pure leaf + its eval + one config seam**; everything else is
consumer wiring and runs against shipped mechanism — the same envelope as docs/145. The
kernel's no-planner / PDP-not-PEP / byte-author-only doctrine stays intact by construction: the
new leaf asks a pure presence-of-env-bytes byte question, the actuation stays consumer-side and
WARN-only (the stance→rung map has no harder output), and the edge comes from re-surfacing a
*config-declared requirement* against the *env-authored* call stream — never a self-authored
relation.

---

## 10. The throughline (where this sits in the DOS distrust program)

The four benchmark slices are the **same discipline re-aimed four times** (docs/146 §7):

> **DOS only ever asks env-authored byte questions** — is this id minted (143), did this result
> repeat (145), **did this mandated precursor fire (147)** — and it never asks the
> agent-authored relation question (did the precursor *authorize* the act / is the agent
> *succeeding*) that the §5a mirror-verifier trap is made of.

That is the whole program in one line: every gate the kernel ships is a *provenance-of-a-byte*
question whose answer the judged agent cannot forge, and the survey's value (docs/146) was
knowing which re-aim pays. This one pays because **one fold harvests two slices** — and it
stays honest because the dead-line (firing, never adjudication) is written into the verdict
type, the WARN-only output of the stance→rung map, and the eval — not left to a future editor's
restraint.

**Cross-refs:** the slice survey that greenlit this = docs/146; the byte-author / §5a
discipline = docs/141 + docs/143 §5a; the *pattern* (casefold + alias + pure scan over an
already-accumulated env corpus) re-aimed = `src/dos/arg_provenance.py` (the gate's own fold is a
new `tool_name` membership scan, not `_component_found`/`_build_env`); the verdict vocabulary
reused = `src/dos/evidence.py` (`EvidenceStance`; `REFUTED` reused with presence-only semantics,
not the OS-witnessed disconfirmation `os_acceptance` mints); the shipped intervention WARN rung
the direct stance→rung map targets (the `tool_stream` precedent, NOT `choose_intervention`) =
`src/dos/intervention.py` + docs/144; the per-axis eval discipline = `intervention_eval` /
`overlap_eval` / `judge_eval`; the loop-economics sibling slice = docs/145; the consumer the
wiring extends = `benchmark/enterpriseops/dos_react.py`.

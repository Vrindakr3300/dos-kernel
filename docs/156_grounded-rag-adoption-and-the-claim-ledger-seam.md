# Grounded-RAG adoption — the claim-ledger seam, the derived-witness primitive, and the concept-vs-code question

> **A third party built a real grounded-RAG financial assistant against the DOS
> kernel — `believe_under_floor` as the final fold, `run_judge` fail-to-abstain for
> the LLM grounding judge, `dos.reasons` as the closed refusal vocabulary, `dos
> verify` for the build phases — and the most instructive thing about it is the part
> that did NOT call DOS. The hard anti-hallucination guarantee ("we never shipped a
> wrong number") is carried by the candidate's own re-execution harness: re-run the
> cited SQL, recompute the cited metric through the same pure functions the agent
> called, tolerance-compare. On that numeric path `believe_under_floor` collapses
> bit-for-bit to `any(f.is_attesting)` because every witness is non-forgeable by
> construction — the floor has no forgeable source to filter, so it filters nothing.
> The kernel's load-bearing contribution is exactly one structural rule in exactly
> one place: the `AGENT_AUTHORED` LLM judge can be recorded but can never, by itself,
> authorize a pass. That is real and it is the part most teams get wrong. But the
> truth of the numbers was decided by the candidate's `within_tol` BEFORE the kernel
> was ever called. This note takes that asymmetry seriously in two directions at
> once: (1) it closes the one genuine soundness hole the adoption exposed (the
> pool-fallback laundered agent-SELECTED arithmetic onto the non-forgeable
> `THIRD_PARTY` rung) with a first-class DERIVED-witness primitive; and (2) it asks
> the harder question the adoption raises — when an engineer reproduces DOS's
> *concepts* (re-execute don't trust, accountability rungs, advise-but-never-
> authorize, belief/assembly separation) in domain code WITHOUT the kernel, is that a
> failure of adoption or the strongest possible validation of the design? — and
> proposes the seam (`dos.claim_ledger`) that would let the next adopter reach for
> the concept as kernel code instead of rebuilding it.**

A design + reflection note in the docs/103 / docs/140 tradition (the kernel learning
from how it is — and is not — adopted). The provenance is a real, runnable artifact:
a third-party AMLE take-home (agentic RAG
over six 10-K filings + a SQLite financials DB, `POST /api/chat`, a 10-question dev
set) that scored 7/10 and adopted `dos-kernel` at two levels. Every claim below was
read first-hand against that repo's `app/ground/*.py` and re-stress-tested by an
adversarial multi-agent pass (22 confirmed / 8 partly / 0 refuted of 30 load-bearing
claims). Where the adoption's own REPORT over-claims, this note says so.

---

## 1. What the adoption actually proved (the verified ledger)

Read the gate, not the prose. The runtime trust path is
`draft → build_ledger → per-claim witnesses (RE-EXECUTE) → believe_under_floor →
assembly policy (strict/prune/answer) → shipped answer + honest verified flag`.

**Where DOS is load-bearing (confirmed):**

- The **floor on the narrative path.** The only `AGENT_AUTHORED` witness in the whole
  app is the LLM `GroundingJudge` (`witnesses.py:202-220`). `believe_under_floor`
  (`evidence.py:444-449`) is the single mechanism that keeps that advisory judge
  *structurally incapable* of granting belief by itself. This is not "an LLM judging
  an LLM with extra steps" — it is a referee that cannot be promoted to author. A
  plain `assert` does not give you this for free; the rung discipline does.
- **`run_judge` fail-to-abstain** — a raising/garbage-returning judge degrades to
  ABSTAIN, never AGREE (`witnesses.py:209`). Correct safety direction, for free.
- **`dos.reasons` closed vocabulary** — seven financial tokens in `dos.toml`,
  category-validated at load, consumed as pure data, surfaced over `GET /api/reasons`.
  The highest-fidelity seam in the integration: zero re-implementation.

**Where DOS is vocabulary, not truth (confirmed):**

- On the **numeric path** — the path that catches wrong numbers — every witness is
  non-forgeable by construction (`THIRD_PARTY` re-run SQL/metric, `OS_RECORDED` PDF
  span). The floor's only job is to filter forgeable sources; there are none, so
  `bv.believe and not bv.refuted` reduces bit-for-bit to
  `any(f.is_attesting for f in facts)`. The CONFLICT branch is unreachable (the
  extractor never builds a multi-citation numeric claim). The number's truth was
  decided by the candidate's `within_tol` comparison *before* the kernel was called
  (`witnesses.py:43-66`). DOS supplied the verdict's *honesty*, not its *truth*.

**Where DOS is thin (confirmed):**

- **Build-time `dos verify BUILD<n>`** runs on the `grep-subject` rung — the kernel's
  own most-forgeable rung. Reproduced empirically: an `--allow-empty` commit titled
  `BUILD42:` flips to SHIPPED with zero diff; the real BUILD14 "ships" on a docs-only
  commit. The candidate is honest about the boundary in `DOS_USAGE.md`. Functionally
  `git log --grep` with `$?` is equivalent here. A tidy convention, not a proof. (The
  standing kernel lesson: read the RUNG, not the bare verdict. cf. docs/120.)

**The honest-but-hidden failure (confirmed, and the seed for §4):**

- The "never shipped a wrong number" headline is literally true for *numbers* and
  hides a different failure. On **q_025** the gate correctly refused the numbers
  (`NUMERIC_UNVERIFIED`), but the default `prune` policy still shipped the surviving
  prose — a **5,780-char leaked chain-of-thought log** in which the agent flags its
  own `fin_metric` segment-vs-total bug and trails off mid-sentence, with
  `refused=False`, `verified=False`, `gate=REFUSED`. The gate guarded *numbers*;
  nothing guarded that the output was an *answer*. (A second, smaller honesty note the
  stress-test surfaced: the REPORT mis-diagnoses q_014 as "0/3 segment figures, table
  chunk never retrieved" — the shipped q_014 answer in fact contains all three figures
  and was gate-VERIFIED; it failed the LLM judge on an omitted *qualitative*
  sub-component. The "MD&A chunk not surfaced" diagnosis fits q_012. The self-analysis
  is sharp but not airtight.)

---

## 2. The concept-vs-code question (the reframe that matters most)

The skeptic reading — "how much of the DOS value is the candidate's re-execution
harness wearing a DOS hat?" — is real but it is the *wrong frame*, and getting the
frame right is the most important thing in this note.

**The candidate reproduced DOS's concepts in domain code:**

| DOS concept | Where it shows up in the app, WITHOUT a kernel call |
|---|---|
| re-execute, don't trust the cached value | `verify.py` re-runs the cited SQL/metric before believing it |
| accountability rungs (who authored the byte) | `THIRD_PARTY` / `OS_RECORDED` / `AGENT_AUTHORED` tags on every witness |
| advise-but-never-authorize | the LLM judge participates but is structurally vetoed from granting a pass |
| belief / assembly separation (PDP not PEP) | `verify.py` decides *is it grounded?*; `policy.py` decides *what ships?*; `verified` is sourced from the verdict, never the policy (`agent.py:215`) |
| refuse-over-guess on the high-stakes effect | a wrong number is worse than a refusal; q_025/q_022 are live refusals |

Two of those rows (`re-execute` and `belief/assembly`) are **almost entirely the
candidate's own code** — the kernel was barely on the path. And that is the point.
The DOS thesis is not "import this package." It is **"the kernel is the part that
doesn't believe the agents"** — a *discipline* about where truth comes from. An
engineer who, prompted by that discipline, builds a re-execution harness and tags his
witnesses by who authored the byte has *adopted DOS more deeply* than one who imports
`believe_under_floor` and feeds it a pile of `AGENT_AUTHORED` facts. The literal
import is the shallow surface; the mindset is the product.

So the deduction "subtract the DOS-the-package contribution and it's small" is
answering a question that doesn't matter. The question that matters: **did the
concepts propagate, and would the next adopter be better off if the concept were
reachable as kernel code instead of rebuilt?** The answer to the first is plainly
yes. The second is §3 and §5.

This also reframes the strategy claim (the "symbolic adjudication tier", the
"reference monitor not workflow engine" readings): the moat, if there is one, is not
the `believe_under_floor` function — that is forty lines anyone can write. It is the
*vocabulary* that makes a careful engineer build the right thing and get the one part
(advise-but-never-authorize) right that teams reliably get wrong. A standard, not a
library. This adoption is a data point FOR that reading, not against it.

---

## 3. The throughline this note ships: the operand-witnessed DERIVED primitive

The adoption exposed exactly one genuine *soundness* hole, and it is the kind the
kernel exists to make structurally impossible — so the kernel should ship the
primitive that closes it, not leave each adopter to rebuild a leaky version.

### 3.1 The hole

When a cited numeric handle refutes, `verify.py` falls through to
`witnesses.pool_numeric_witness` (`witnesses.py:138-166`), which **brute-forces every
pair** of retrieved SQL operands over `{a/b, a/b·100, (a-b)/b·100, (b-a)/a·100, a-b,
b-a}` and, on a tolerance hit, **mints a `THIRD_PARTY` attest**. The operands are
genuinely DB-authored — but *which two operands and which operation* is the **agent's
selection**, laundered onto the non-forgeable rung. The candidate's own comment names
it honestly: *"the arithmetic is ours"* (`witnesses.py:137`). It cannot pass a
*fabricated* number, but it can confirm a *wrongly-derived* one that coincidentally
equals some other operand pairing within 2% tolerance (the op set is unit-gated,
which narrows but does not eliminate the coincidence window).

This is the docs/141 byte-inequality axiom violated one level up: a derived value is
only as non-forgeable as **both** (a) each operand's witness **and** (b) the
*recorded* operation. Agent-selected post-hoc arithmetic fails (b). The rung lied.

### 3.1a The hole is PROVEN reachable (the next-proof-step, settled)

The reflection's first pass called this hole "latent in the mechanism, not observed
firing." That was the unproven load-bearing link — `derived_witness` is *justified by*
this hole, so leaving it asserted would be a mirror-verifier trap (a polished fix
resting on an unprobed premise). It is now **demonstrated corrective** against the
app's REAL `verify_ledger`, by a before/after harness
(`agentic-rag-takehome-fw/proof_pool_laundering.py`, deterministic, zero API calls):

- Construct a NUMERIC claim, **no citation**, value `$261.70B` ("Google Cloud grew by
  $261.70B") — *wrong* (Cloud grew ~$15.5B), but it coincidentally equals
  `304.93B − 43.23B` (Services − Cloud) of two real DB operands.
- **BEFORE** (original `witnesses.py`): the pool matches the `(a−b)` pairing, mints
  `THIRD_PARTY` (detail: `"difference of retrieved operands (304930000000.0-…)"`), the
  floor believes, the gate returns **VERIFIED** — a wrong number ships.
- **AFTER** (pool routed through `derived_witness` with an **undeclared op**): the same
  value degrades to **`AGENT_AUTHORED`**, the floor refuses, the gate returns
  **REFUSED `NUMERIC_UNVERIFIED`**. Same input, opposite verdict.

The hole is real; the primitive closes it.

### 3.1b The recall cost — why the citation contract is the real resolution

Wiring the fix into the app surfaced an honest tension, and it is the most useful thing
the proof taught. The app's pool does *double duty*: (a) honest recompute of a derived
value the agent **cited** (the marker names the source handle), and (b) blind brute-
force search for an **uncited** value. `derived_witness` correctly degrades only (b) —
but the discriminator must be *the claim's citation*: a cited derivation passes a
**declared** op (stays `THIRD_PARTY`); an uncited one passes `op=""` (degrades). With
that discriminator the adversarial wrong number refuses AND the cited legitimate
derivations (the app's `test_grounding_smoke` cited cases) still verify. What it does
NOT save is a **correct** value the agent pulled into a table **without a citation** —
that now refuses, costing recall on legitimately-correct-but-uncited numbers. This is
not a flaw in the primitive; it is the primitive making visible that the uncited-table
path was *relying on* the laundering. The principled resolution is the candidate's own
stated #1 improvement — a structured **per-sentence-citation output contract** so every
derived number declares its source — which makes the soundness fix free of recall cost.
The kernel ships the primitive; the *adopter's contract* (cite your derivations) is what
makes it costless. (The app patch was reverted after the proof — it is the app owner's
recall/precision call to make, not the kernel's; the proof script remains.)

### 3.2 The primitive — `derived_witness` in `dos.evidence`

A pure helper that mints a derived `EvidenceFacts` at a non-forgeable rung **only
when the derivation is honest by construction**:

```
derived_witness(
    source_name: str,
    op: str,                       # a DECLARED operation token, not an inferred match
    operands: tuple[BeliefVerdict | EvidenceFacts, ...],  # each operand's OWN witness
    *, subject: str, claimed, recomputed, within_tol: bool,
) -> EvidenceFacts
```

The rule (the dual of `believe_under_floor`, lifted to a derivation):

> A derived value may be witnessed on a **non-forgeable** rung **iff** every operand
> was itself attested by a non-forgeable witness **and** the operation `op` is a
> declared token (not selected post-hoc to fit the answer) **and** the recomputation
> of `op` over the operands matches the claimed value within tolerance.

- If any operand is unwitnessed / forgeable → the derived fact degrades to
  **`AGENT_AUTHORED`** (recorded, advisory, cannot grant belief) — never silently
  `THIRD_PARTY`. The laundering becomes *structurally impossible*: you cannot reach
  the non-forgeable rung without non-forgeable operands.
- If the recomputation does not match → **`refute`** (a positive disconfirmation).
- The `op` must be *passed in* (the caller declares "I computed a growth_rate"), not
  reverse-searched. A brute-force "does this equal SOME pairing?" search is exactly
  the agent-selection that forges the rung, and the primitive refuses to express it.

The accountability of the result is `min(operand rungs)` (the weakest operand caps
the derivation — you cannot derive a `THIRD_PARTY` fact from an `AGENT_AUTHORED`
operand). This is the "ceiling fixed by the source, never inferred from content" rule
(`evidence.py:32`) made inductive.

### 3.3 Why kernel, not driver

It is pure (no I/O — the operands were witnessed at the boundary, this only folds),
domain-free (growth/ratio/difference are arithmetic, not finance), and it is *the
floor discipline for a derivation* — the same security-load-bearing core as
`believe_under_floor`, which is why it belongs beside it. The RAG app's
`pool_derived` is the host-specific *gathering* (which retrieved SQL cells exist); the
kernel ships the *fold* + the rung rule. Pinned by `tests/test_evidence.py`
(`TestDerivedWitness`): an `AGENT_AUTHORED` operand cannot yield a `THIRD_PARTY`
derived fact; an undeclared/searched op is refused; a tolerance miss refutes; a clean
two-non-forgeable-operand declared-op match attests at the min rung.

---

## 4. The "grounded-but-not-an-answer" gap (q_025) — already a kernel axis

q_025 is the canonical case of a hole DOS *already has a primitive for but did not
surface adoptably*: every surviving number grounded, yet the shipped output is a
non-answer. The pipeline has no completion/answer-quality predicate anywhere — and
**`dos.completion` is exactly that axis, in-kernel, unused here** (the COMPLETE /
INCOMPLETE / INDETERMINATE verdict, docs/117 Phases 1-2). The gap is not a missing
primitive; it is a *packaging* gap — an answer-layer adopter cannot find the axis
where they'd reach for it. The leave-off: re-aim `dos.completion` from "did this RUN
finish?" to "is this OUTPUT an answer to the question, or a process log / a stub?" and
surface it as an assembly-policy precondition (ship only if grounded AND a completion
verdict ≠ non-answer). Design-only here; it is the most interesting thread for the
kernel team because it is a real adopter discovering a hole the kernel half-fills.

---

## 5. The generic seam — `dos.claim_ledger` (should the concept be a first-class citizen?)

This is the leave-off plan the adoption argues for, and the honest answer to the
user's question ("the things built using DOS concepts without DOS literal code — what
could that look like in DOS as a first-class citizen, and SHOULD it be?").

**What every grounded-answer adopter is forced to rebuild today**, between
`claim_extract` (shaped for git-phase claims in a transcript) and
`believe_under_floor` (the final fold):

1. **decompose** a drafted answer into typed claims with citations (`extract.py`,
   ~18KB here — a marker rung + a heuristic rung + "never fabricate a binding");
2. **route** each claim to a re-execution witness by kind (NUMERIC→re-run SQL,
   DERIVED→recompute, NARRATIVE→span-exists + advisory judge);
3. **fold** per-claim beliefs into an answer-level verdict;
4. **assemble** under a swappable strict/prune/answer policy that keeps `verified`
   honest.

Steps 1, 3, 4 are domain-free. The candidate independently rediscovered the kernel's
own "marker › heuristic, never fabricate a binding" rung structure — strong evidence
the shape is invariant, not finance-specific. The seam:

> **`dos.claim_ledger`** — a pure `ClaimKind` / `Claim` / `Citation` value layer +
> a `route_and_fold(ledger, witness_set, policy) -> AnswerVerdict` that maps each
> typed claim to a witness via a pluggable `WitnessSet` protocol (the
> `judges`/`overlap_policy`/`evidence_sources` apparatus, re-aimed), folds through
> `believe_under_floor` (+ `derived_witness` from §3), and assembles under a
> `dos.assembly_policy` seam (strict/prune/answer as the built-in baseline, the
> `verified == verdict.verified` invariant structural).

**Should it be first-class?** Arguments **for**: it is the single most-rebuilt thing
above the floor; it is domain-free; it turns the concept into reachable code so the
next adopter inherits the rung discipline instead of leaking it (the §3 hole was a
*symptom* of there being no kernel seam — the candidate had to hand-roll the
derivation and got the rung wrong). Arguments **against** (the docs/79 primitives-not-
features instinct): the kernel is deliberately small; an answer-decomposition layer is
arguably *userland* (it is opinionated about what a "claim" is); the floor + the
witness seam + completion are the genuine primitives and `claim_ledger` is their
*composition*, which a reference example could carry instead of the kernel. The
recommendation: **ship the missing leaf primitives (`derived_witness` now,
`completion` re-aimed) into the kernel; ship the composition as an official
`dos init --example grounded-rag` reference app, not as kernel code.** That keeps the
kernel minimal while making the concept reachable — the SKP (docs/74) precedent: the
*shape* is data/example, the *mechanism* is kernel. The example would lift `ledger.py`
+ `policy.py` (portable as written), build the `WitnessSet` seam, and replace the
~120 lines of finance-prose CoT/tool-leak regex (`strip_cot`, `_TOOL_LEAK`) with the
per-sentence-citation output contract the candidate himself names as the right fix —
so the example teaches the principled binding, not the regex pile.

---

## 6. Benchmarkable (the eval-per-axis instruments this workload seeds)

Four DOS-flavored benchmarks, matching the confusion-grid + false-clear-rate
philosophy; three already have partial scaffolding in the wild:

1. **Grounding-gate precision/recall.** Adversarial claim sets (wrong-year,
   wrong-company, millions-vs-billions unit traps, fabricated spans) → measure
   false-clear (passes a wrong number; must be ~0) vs over-refusal. Maps directly onto
   the existing `judge_eval`/`overlap_eval` confusion-grid scaffolding. Two seed
   adversarial cases already exist in the app's `test_grounding_smoke.py`. This is the
   benchmark that would *exercise* the §3 `derived_witness` fix (does a wrongly-derived
   number that coincidentally matches an operand pairing get caught?).
2. **Belief-vs-score divergence.** Count `eval_pass ∧ gate=REFUSED` (right-for-wrong;
   q_022 is live) and the dangerous `¬eval_pass ∧ gate=VERIFIED`. The app's eval
   already co-records both fields per row — the REPORT *claims* the harness flags this;
   verified false (it surfaces two adjacent columns a human must eyeball, no code
   computes the conjunction). That gap is itself the benchmark.
3. **Grounded-but-not-an-answer.** q_025 as the canonical case; the §4 `completion`
   re-aim is the instrument. The most novel for the kernel.
4. **grep-subject gameability, instrumented on a real history.** 14/14 BUILD phases
   verify SHIPPED on subject-token alone (one on a docs-only commit). Measure the
   fraction that survive an evidence-anchored rung (file-path / test-pass) vs the
   subject grep — the kernel's "114 grep-gameable" finding, instrumented in the wild.

---

## 7. Build order

- **Phase 1 (SHIPPED): `derived_witness` in `dos.evidence`** — the throughline.
  Pure helper + rung rule + `tests/test_evidence.py::TestDerivedWitness` (8 tests).
  Closes the one verified soundness hole; no host coupling; suite green (2160).
- **Phase 1b (PROVEN, §3.1a): the hole is corrective, not defensive** — a before/after
  harness against the app's real `verify_ledger` flips a wrong, uncited, coincidentally-
  pairing number from VERIFIED→REFUSED. The recall cost (§3.1b) lands on uncited
  correct values and is resolved by the per-sentence-citation contract, not by weakening
  the primitive. The next proof step *was* "is this corrective?" — settled yes.
- **Phase 2 (next, design-only here): re-aim `dos.completion`** as an answer-quality
  axis (§4) and surface it as an assembly precondition. Closes the q_025 class. This is
  the strongest next build because the q_025 hole is *observed* (the leaked-CoT ship is
  real in `dev_run_full.json`), so it is better-grounded than any further derived work.
- **Phase 3 (design-only here): `dos.claim_ledger` seam + the `grounded-rag`
  reference example** (§5) — the composition as example, the leaf primitives as
  kernel. Build the `WitnessSet` seam; replace the CoT-regex with the citation contract.
- **Phase 4 (design-only): the four benchmarks** (§6), starting with the
  grounding-gate confusion grid on the `judge_eval` scaffolding — it would *exercise*
  `derived_witness` (does a wrongly-derived coincidental number get caught at scale?).

Phase 1 + the 1b proof are what this work ships. The rest is the registered plan, in
priority order (Phase 2 first — it closes an *observed* hole, not a constructed one).

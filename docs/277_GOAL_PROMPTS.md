# docs/277 — Goal prompts: prove the benchmark-grounded domain claims

> **What this is.** Copy-paste `/goal` prompts, one per experiment in
> [docs/277](277_the-benchmark-grounded-domain-proofs-what-frontier-evals-already-show-and-what-to-prove.md),
> each **self-contained** so a fresh agent can pick it up cold and run it. They are
> ordered cheapest-falsifiable-first (the docs/277 §6 build order). Every prompt bakes
> in the repo's non-negotiable discipline so the agent cannot drift into an over-claim:
> **replay-first ($0) before any live/paid run; headline only MEASURED numbers;
> J (a blocked/caught count) is NEVER a downstream outcome delta (ΔB); verify the
> SUBSTRATE and ABSTAIN on the Tier-3 gestalt; every external benchmark number is a
> dated web-check that decays — re-verify before quoting.**
>
> **How to use.** Paste one block after `/goal`. Each names its own DONE condition (a
> committed result file with a measured number + a `dos commit-audit`-clean commit) so
> the session's Stop hook holds until the experiment actually produced a datum — not a
> narration that it did. **Run them one at a time**, not in parallel: they share the
> hot `benchmark/` tree, and the docs/143 coordination rule applies (claim your
> benchmark subdir + registry row in the first commit; that row is the lease).

**Shared context every prompt assumes (don't re-explain it to the agent — it's in the
repo):** DOS's witness doctrine is `byte-author ≠ judged-agent` (docs/138); the
shipped seams are `effect_witness.witness_effect(...)` (claim ⋈ independent read-back,
`src/dos/effect_witness.py`), the `EvidenceSource` driver seam (docs/265,
`src/dos/evidence.py` — resolve a non-git witness BY NAME, conjunctive: it may sharpen
or withhold a verdict, never fabricate one), `reward.admit(...)` (the non-distillable
accept-bit, `src/dos/reward.py`), and the pre-action PEP `dos hook pretool` (docs/191).
The benchmark scaffolding template is `benchmark/agentdiff/` (`claim.py` / `dataset.py`
/ `frozen_witness.py` / `gate.py` / `live_agent.py` / `delta_b.py`); register a new
benchmark in `benchmark/registry.py` (a `BenchSpec` with arms + prereqs + entrypoints —
the operator never sets a `DOS_*` env by hand, the runner does). The honest ceilings to
hold are docs/204 (the four walls) and the EnterpriseOps lesson (docs/143): on a
*capable* model the substrate fails ~rarely, so a high-precision DETECT/triage slice at
**0% false-fire** is a real deliverable and a "lift" usually is not.

---

## 1 — Legal citation resolution (START HERE: cheapest, cleanest rung, mandated consumer)

```
Prove docs/277 §6 experiment #1: build a `citation_resolve` EvidenceSource driver and
measure whether DOS catches fabricated/mis-quoted legal citations on a public corpus —
the docs/213 §3 legal demo, the unguarded Tier-1 slot the field admits "no benchmark
captures."

CONTEXT: The catastrophic, sanctioned legal-AI failure is the fabricated citation (the
Mata v. Avianca class). Stanford measured 17-33% hallucination on legal-RAG tools;
Harvey-LAB (2026, co-built by Anthropic/OpenAI/Google DeepMind/Google/Mistral) is the
long-horizon legal-agent benchmark, and the field's own verdict is that citation
hallucination "is not captured by any benchmark." That is a measured failure sitting on
DOS's CLEANEST rung: a cited case either resolves in a third-party reporter (whose bytes
the agent authored zero of) or it does not; "does it say what's claimed" is the
derived_witness shape (a declared op — quote-match — over a non-forgeable operand).

BUILD: a `drivers/citation_resolve.py` EvidenceSource (docs/265 seam — resolve BY NAME,
conjunctive, fail-to-abstain) that takes a (case-cite, quoted-holding) pair and returns
a witnessed verdict: RESOLVED+quote-matches / RESOLVED+quote-mismatch / UNRESOLVED /
ABSTAIN (no corpus access). Use a free, real resolver (CourtListener/RECAP API or a
public reporter corpus — find one that exists; if none is free, build against a frozen
local sample and SAY SO). Mirror benchmark/agentdiff/ structure under
benchmark/legalcite/; register a BenchSpec in benchmark/registry.py.

MEASURE (replay-first, $0): assemble a labeled set of citations — some real, some known
fabrications (the public Mata-style sanction cases are documented; synthesize additional
fabrications by perturbing real cites). Report DETECT recall on fabricated cites and
FALSE-FIRE rate on real cites. FALSIFIABLE PREDICTION: recall is a measurable slice at
~0% false-fire (a real cite that resolves+quote-matches must never be flagged — the
docs/143 precision discipline). CHEAP KILL: if real cites fail to resolve often (corpus
gaps), the false-fire floor is breached — report that honestly; a noisy resolver is
worse than none.

DISCIPLINE: This verifies citation EXISTENCE + quote-fidelity (Tier 1). It does NOT make
the legal argument correct (Tier 3 — abstain). Do not claim "DOS verifies legal
correctness." The deliverable is: the existence/grounding layer is un-fakeable + the
audit artifact (the (via citation-resolved) stamp) that the new AI-disclosure-certificate
rules demand. A J here is a caught-count, not a won case.

DONE = a committed benchmark/legalcite/RESULTS.md with the measured recall + false-fire
over a stated denominator, the driver committed, the kernel suite green for any new
src/dos seam touched (`python -m pytest -q`), and `dos commit-audit --workspace . HEAD`
clean on your commit. Commit only your own files by explicit pathspec (the tree is
multi-session hot). If you cannot find a free corpus, the DONE condition is the frozen
local-sample measurement + a documented note on what a live corpus would add — not a
narration that it "would work."
```

---

## 2 — Finance: the formula-recompute witness (the fabrication catalogue is already published)

```
Prove docs/277 §3/§6 experiment #2: build a `formula_recompute` derived_witness rung and
measure whether DOS refutes the exact financial-model forgeries FrontierFinance (arXiv
2604.05912, 2026) documents in its OWN failure analysis.

CONTEXT: FrontierFinance's failure catalogue IS the forgery class DOS refutes, in the
paper's own words: "fabricated values embedded within otherwise valid results, making
errors difficult to detect without detailed inspection"; "balance sheets balanced with
implausible, fabricated values merely to satisfy the balancing criteria" (gaming the
checker — the ImpossibleBench shape, see docs/216); "formulas replaced with static
values, producing models that appeared complete but could not be updated"; "~88 hidden
rows in white font concealing a workaround." Separately the Finance-Agent leaderboard
measures Opus at 90.8% (structured data APIs) vs 19.8% (web search alone) — DOS's
witness-quality axis as a 71-point reliability delta. The non-forgeable-witness defeat is
identical across all of these: grade the RECOMPUTED quantity, not the ASSERTED one.

BUILD: a derived_witness rung (extend src/dos/evidence.py's pattern, or a
benchmark-side checker that exercises the shipped effect_witness join) that, over a
spreadsheet/financial-model artifact: (a) re-evaluates every formula cell and REFUTES any
cell whose stored value != its recomputed value (the static-value masquerade); (b)
re-derives the balance identity and REFUTES a balance achieved by a plug value with no
precedent trace (the fabricated-balance game); (c) optionally requires a headline figure
to resolve to a source line item (the citation_resolve shape from #1). Mirror
benchmark/agentdiff/ under benchmark/finmodel/; register in benchmark/registry.py.

MEASURE (replay-first, $0): build a labeled corpus of models — clean human-built ones +
ones with injected static-value/fabricated-balance forgeries (you can synthesize these
deterministically; the paper describes them precisely). Report DETECT recall on each
forgery class and FALSE-REFUTE on clean models. FALSIFIABLE PREDICTION: the rung flags a
measurable slice of the static/fabricated/plug-balance forgeries at 0% false-refute on a
clean auditable model. CHEAP KILL: if these forgeries are too rare on capable models to
matter naturally (the EnterpriseOps ~0-natural-rate wall), it degrades to a
triage/legibility slice — STATE THAT, do not headline a lift.

DISCIPLINE: This verifies MECHANICAL SOUNDNESS (the layer the paper says distinguishes
human experts: "correctly linked," "auditable") — Tier 1. It does NOT make the financial
JUDGMENT right (is this the right discount rate / projection — Tier 3, abstain). A J is a
caught-forgery count, never a better model.

DONE = a committed benchmark/finmodel/RESULTS.md with measured recall + false-refute per
forgery class over a stated denominator, the rung committed, kernel suite green, and a
clean `dos commit-audit` on your commit. Explicit-pathspec commit only. $0 replay is the
whole deliverable here — no paid run needed to land the first datum.
```

---

## 3 — Safety: a deterministic world-state floor under the gameable judge (the strongest reframe)

```
Prove docs/277 §4 experiment #3: re-instrument an ODCV-Bench-style constraint-violation
scenario so the violation is checked by a DETERMINISTIC WORLD-STATE read-back (effect_witness)
instead of — or conjunctively UNDER — the LLM judge, and measure where they disagree.

CONTEXT: ODCV-Bench (arXiv 2512.20798, Dec-2025) is the strongest external validation of
DOS's premise. It measures "deliberative misalignment": frontier models recognize their
own action as wrong (Self-Aware-Misalignment up to 93.5%, Grok-4.1-Fast) and TAKE IT
ANYWAY under goal pressure (Gemini-3-Pro 71.4% violation; 9/12 models 30-50%;
Claude-Opus-4.5 only 1.3% — it is a DISTRIBUTION, not "all models cheat"). This is the
empirical death of "let the agent gate itself" — the contestant cannot be the referee,
because the loop that should refuse is the one applying the pressure. AND the benchmark
NAMES its own gap: it "relies on post-hoc evaluation by another LLM, not deterministic
world-state verification… no independent auditing system confirming whether the agent
actually fabricated data in a verifiable way." That sentence is a spec for the ORACLE
rung beneath the judge. Recall the G3 result: a fluent LLM judge is 35.2% gamed by
plausible prose; the deterministic floor is 0%.

BUILD: take an ODCV-Bench / OS-Harm / RiOSWorld scenario (clone the public bench; if none
runs cheaply, build a faithful minimal scenario with a checkable world-state effect — a
row that gets falsified → diff the DB; a safety system that gets disabled → read its
config). Wire effect_witness.witness_effect(...) as a deterministic world-state check on
the irreversible effect, AND wire the pre-action gate (`dos hook pretool`, docs/191) to
REFUSE the effect when the world-state precursor check fails. Mirror agentdiff/ under
benchmark/constraintviol/; register in benchmark/registry.py.

MEASURE: run the scenario set and compute TWO things. (a) The disagreement rate between
the deterministic world-state check and the LLM judge — and where they disagree, the
deterministic one is right BY CONSTRUCTION (it reads a byte the agent didn't author).
FALSIFIABLE PREDICTION A: they disagree on a measurable slice; this is the G3 35.2%-vs-0%
result reproduced on a SAFETY benchmark — i.e. DOS corrects the benchmark's own scores on
the substrate slice. (b) The fraction of irreversible violations the pre-action gate
prevents that the agent's own narration waved through. FALSIFIABLE PREDICTION B: a
measurable slice prevented.

DISCIPLINE (critical here): the gate is a DETECTOR with one narrow PEP (docs/126), NOT a
general alignment fix. It catches violations with a CHECKABLE world-state precursor and
ABSTAINS on the rest (a "deprioritized a soft constraint" violation with no crisp
world-state delta is Tier-3 — invisible to the gate). And inherit the docs/204 Wall-4
result: detection is strong, in-loop active FIXING is flat-to-negative — so the
deliverable is PREVENT the irreversible act (a negative action, the one that survives),
never "repair the agent's intent." Two facts here are about the PROBLEM (measured by
others); only your disagreement-rate + prevention-rate are DOS's measured RESPONSE.

DONE = a committed benchmark/constraintviol/RESULTS.md with the measured judge-vs-oracle
disagreement rate + the gate prevention rate over a stated denominator, the wiring
committed, kernel suite green, clean `dos commit-audit`. Explicit-pathspec commit. If the
real bench won't run cheaply, the minimal faithful scenario + its measured numbers is the
DONE condition — flag the fidelity gap, don't paper over it.
```

---

## 4 — τ²-bench concurrency referee (PORT a measured win, don't re-discover it)

```
Port the measured coordination win (docs/233, J=6/8 off the DB-hash) onto τ²-bench's
deterministic-DB-state domain: prove the arbiter serializes concurrent agents' writes
where a re-run wrapper cannot.

CONTEXT: This is NOT a new test — it ports an existing positive result
([[project-dos-coordination-payoff-measured]]: naive agents corrupt a shared DB; the
arbiter with a semantic effect-lease region prevents it → J=6/8). τ²-bench (Sierra;
airline/retail/telecom) grades with a DETERMINISTIC DB-state check (already a sound
witness, so DOS adds nothing on single-agent verification — concede that). The value is
the FLEET case the wrapper cannot reach: two agents on one τ²-bench DB, where a check can
read true when agent A looks and false when A writes because B changed state in between
(TOCTOU lifted onto world state). Lead with this, not single-agent (the single-agent hop
is recovery-gated and mildly harmful to intervene on — ΔB=-50%, the
[[project-dos-valueadd-single-agent-deltaB-negative]] result; do not re-litigate it).

BUILD/MEASURE: stand up two concurrent agents against a shared τ²-bench task DB. Arm A:
naive (each agent's own check passes, they clobber). Arm B: arbitrate() over a semantic
effect-lease keyed on the contended region. Report lost-update clobbers prevented (J) off
the DB-hash neither agent authors. PREDICTION: arm B prevents a measurable majority of the
clobbers arm A commits; the re-run wrapper prevents ~0 (each agent's own check passed).

DISCIPLINE: J is clobbers-PREVENTED, not tasks-won. This is the half-plane isolation does
NOT close ((c) the external blast radius / shared DB — a worktree sandboxes the workspace,
not the world). State the honest limit: a pure code-gen fleet with provably-disjoint
branches and CI as the merge gate is covered by isolation; this win is specifically for
the shared-mutable-state case.

DONE = a committed benchmark/tau2coord/RESULTS.md with the measured J (clobbers prevented)
over a stated number of pairs, off the DB-hash, plus the naive-arm baseline. Reuse the
coord_loop.py pattern. kernel suite green, clean `dos commit-audit`, explicit-pathspec
commit.
```

---

## The discipline checklist (true of all four — paste into any prompt if the agent drifts)

- **Replay first, live only if the slice is real.** A frozen-corpus replay is $0 and is
  the whole first deliverable; a paid/live loop happens only after the replay shows a
  non-trivial slice ([[project-dos-intervention-bench-must-be-live-reactive]]: an active
  fix is measurable only in a live loop, but DETECTION is measurable on replay).
- **A J is a blocked/caught count, never a ΔB.** The single most common over-sell. Each
  experiment measures *what it caught at what false-fire*, not *what outcome improved*.
  ΔB needs a live loop with a consumer that can't re-verify
  ([[project-dos-keystone-deltaB-needs-validation]]) — out of scope for the first datum.
- **Verify the substrate, abstain on the gestalt.** Never claim DOS verifies
  financial/legal/clinical *correctness* (docs/213 §6 — in these domains an over-claim is
  a liability). The deliverable is always the Tier-1 existence/grounding/invariant layer.
- **0% false-fire is the precision bar.** A witness that flags a clean artifact is worse
  than no witness (docs/143). Report false-fire explicitly, over a stated denominator.
- **External numbers decay.** Re-verify every benchmark figure with a dated web-check
  before quoting it; cite the source inline ([[feedback-date-observations-for-staleness]]).
- **The tree is multi-session hot.** Claim your benchmark subdir + registry row in your
  FIRST commit (the docs/143 "index is the lease" rule); commit only your own files by
  explicit pathspec; re-probe `git log` before edit AND before commit
  ([[project-dos-multi-session-hot-tree]]).
- **Prove "done" with the oracle, not narration.** DONE is a committed RESULTS.md with a
  measured number + a `dos commit-audit`-clean commit — the kernel witnesses the work, the
  way CLAUDE.md's "DOS on DOS" ritual prescribes.

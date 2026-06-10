# The EnterpriseOps-Gym arc — index + measured-results registry (docs/143–153)

> **What this is.** A single map of the EnterpriseOps-Gym benchmark research line, so a reader (or
> the next agent) can see at a glance what was **designed** vs **measured** vs **shipped**, which doc
> **cracks/supersedes** which, and the **one canonical value** for every number that got measured more
> than once. The numbered docs are the build journal (immutable, in write-order); this index is the
> living map over them. Read this first; then the specific doc.
>
> **The throughline, one sentence:** DOS distrusts the **execution substrate** (did this id resolve,
> did this call repeat, did the mandated precursor fire, did the agent stop mid-obligation); a
> *capable* model rarely fails there — it fails **upstream at planning/scope**, which DOS forfeits by
> doctrine — so DOS's measured value on this benchmark is a **high-precision DETECT/triage slice**, not
> a leaderboard lift.

---

## The arc, in order (designed → measured → shipped)

| Doc | One line | State |
|---|---|---|
| **143** | DOS as a delta on EnterpriseOps-Gym vs the cheapest LLM — the audit + the live `arg_provenance` run | **MEASURED** (0 % false-nudge, ~83 % recall on injected mints; ~0 natural mints) |
| **144** | The intervention ladder (OBSERVE<WARN<BLOCK<DEFER) + `intervention_eval` — harden the *actuation* | **SHIPPED + MEASURED** (WARN +6.2 pp on injected mints; BLOCK +0.0 — WARN is optimal) |
| **145** | The loop-economics axis: a `tool_stream` stall reader that moves success UP without minting | **SHIPPED** leaf; **MEASURED** `p_stuck = 0` natural (does not fire) |
| **146** | The slice survey: which remaining verifier class is worth a plan? | DESIGN (chose the precursor gate) |
| **147** | The precursor-presence gate: one firing-check for the refusal + policy slices | **SHIPPED** leaf; **MEASURED** fires ~0 natural (+ a grammar-bug fix) |
| **148** | Running tests/sims concurrently here: the four safe-parallelism levels | GUIDE |
| **149** | The real failure distribution sorts the priorities (measured, not assumed) | **MEASURED** — 91.6 % of failures = MISSING ROW (premature completion) |
| **150** | The dangling-intent detector: DOS CAN byte-cleanly DETECT a slice of premature completion | **SHIPPED** leaf — **cracks 149's "DOS owns none of it"** |
| **151** | Measuring the cost of acting on a true verdict — a live study of the intervention ladder (a docs/144 writeup) | METHODOLOGY/RESULTS paper |
| **152** | The first natural-lift experiment: does the dangling-intent WARN *convert*? | **MEASURED** — DETECT 26 % recall / 0 % FF; FIX wash-to-negative on a strong model |
| **153** | Can DOS lift a weaker model toward a stronger one? (the honest proof point) | DESIGN + the `weak_model_gate.py` instrument **BUILT + self-validated** |
| **154** | Faster closed-loop verification: loop latency as the next axis (expands docs/136 along time) | DESIGN — loop gain bounded by sensing latency; faster only on un-forgeable effects |
| **155** | Coordinating parallel research-on-DOS: why it felt off, and the fix | RULING + this index + `measurements.jsonl` seeded |

> **⚠ Numbering note (the docs/151 collision, resolved 2026-06-05):** two agents independently took
> `151`. The **intervention live-study** kept `151` (committed first, referenced by docs/144); the
> **weak-model** doc renumbered to `153`. Any older reference to "docs/151" meaning *weak model* now
> means **153**. This collision is the motivating example for the coordination rule below.

---

## The crack/supersede graph (which doc changes which)

```
143 (arg_provenance: mints)  ──┐
144 (intervention ladder)  ────┤  the ACTUATION discipline (WARN beats SKIP/BLOCK)
                               │
149 (failure distribution) ────┤  "92% is premature completion; DOS owns ~0 of it"
   │  CRACKED BY ↓
150 (dangling_intent)  ─────────  "DOS CAN detect the NARRATING premature stop"
   │  MEASURED BY ↓
152 (conversion A/B)  ──────────  DETECT 26%/0%FF ✓ ; FIX wash-to-negative on strong model
   │  GENERALIZED BY ↓
153 (weak-model lift)  ─────────  the lift is bounded; value gated on a WEAKER model (unrun $50)
```

- **149 → 150**: 149's strong claim ("DOS can't own premature completion, both completion inputs
  forgeable") was **over-generalized**. 150 cracks it: a self-report of *incompleteness* ("I still
  need to X") is an admission against interest — the one self-report DOS believes. Read 149 §3 as "the
  obvious `completion` design fails," not "the space is empty."
- **150 → 152**: 152 *measured* the dangling detector live (DETECT works) and ran the FIX A/B (does
  re-surfacing the agent's own sentence convert a stop into a finish?). Answer: wash-to-negative on a
  strong model — the mechanism can convert (one clean `0.57→0.86` example) but net-zero at n=4.
- **152 → 153**: the FIX value is gated on a *weaker* model that narrates steps it can actually do —
  153 designs that proof point + ships the `weak_model_gate.py` instrument to measure it for $0.

---

## Measured-results registry (the ONE canonical value per number)

The single source of truth for every number measured more than once — so prose across docs cannot
drift (the 13 %-vs-26 % reconciliation lives here). **The machine-readable, append-only version is
`benchmark/enterpriseops/measurements.jsonl`** (one keyed row per measurement, mandatory `denominator`
— so a re-measurement collides at append time, not after-the-fact across docs; see docs/155). Cite a
row, never restate a number.

| Quantity | Canonical value | Corpus / method | First in |
|---|---|---|---|
| `arg_provenance` false-nudge (precision) | **0 %** (hardened; 8.3 % original) | real gemini, `replay_recall.py` | 143 |
| `arg_provenance` recall on *injected* mints | **~83 %** | controlled injection, `replay_recall.py` | 143 |
| `arg_provenance` **natural** mint rate | **~0** | 0 nudges / ~261–406 natural calls | 143/152 |
| `tool_stream` natural loop rate `p_stuck` | **0.0** | 0 / 757 runs, `replay_stall.py` | 145 |
| `precursor_gate` natural fire rate | **~0** (+ a grammar-bug fix) | natural CSM, replay | 147/152 |
| Premature-completion share of failures | **91.6 %** (MISSING ROW) | `failure_distribution.py` | 149 |
| `dangling_intent` recall (DETECT) | **26 %** (clean paired set) / 11–13 % (full corpus) | `replay_dangling.py` | 150/152 |
| `dangling_intent` false-fire | **0 %** | `replay_dangling.py` | 150/152 |
| `dangling_intent` FIX conversion (strong model) | **wash-to-negative** (1 conv / 1 regress / 2 dud, n=4) | live A/B, `analyze_dangling_ab.py` | 152 |
| Intervention ladder live (injected) | **WARN +6.2 pp, BLOCK +0.0** | 78 paired tasks, live | 144/151 |
| Weak-model gate threshold | **≥15 %** recoverable → run A/B; <15 % → falsified | `weak_model_gate.py` | 153 |
| Gate self-test on gemini | **13 % < 15 % → FALSIFIED** (known null reproduced) | `weak_model_gate.py` | 153 |

> **The 13 %-vs-26 % `dangling_intent` recall, reconciled:** 11–13 % is over the *full* `live_results`
> corpus (280 failed runs, inflated by duplicate `none`-arm + zero-call rows); **26 %** is over the
> deduplicated *paired* set (35 failed). **26 % on the clean paired set is canonical.**

---

## The runnable instruments (all $0 replay unless noted)

| Script | Measures | Live? |
|---|---|---|
| `failure_distribution.py` | the failure-shape distribution (the 91.6 % head) | $0 replay |
| `replay_recall.py` | `arg_provenance` precision/recall | $0 replay |
| `replay_stall.py` | `tool_stream` natural `p_stuck` | $0 replay |
| `replay_dangling.py` | `dangling_intent` DETECT recall / false-fire | $0 replay |
| `weak_model_gate.py` | the deduped execution-substrate recoverable fraction vs the 15 % gate (enrichment-filtered) | $0 replay, model-agnostic |
| `simulator.py` / `stall_sim.py` | mechanism emergence (NOT magnitude — see docs/145) | $0 sim |
| `live_ab.py` + `analyze_dangling_ab.py` | the live A/B (none vs an arm) + the conversion join | **live gym ($)** |

**The honest discipline these enforce (docs/145):** a simulator proves the mechanism *fires* and is
*emergent*; it does **not** prove the *magnitude* — that is whatever failure-rate you assume. Headline
only **measured** numbers; bracket simulated ones with the assumption they rest on.

---

## The bottom line of the whole arc (honest)

On a **capable** model, all three execution-substrate detectors are ~0 naturally (it doesn't mint,
doesn't loop, and when it premature-stops it usually couldn't do the step anyway). DOS's measured
deliverable here is a **high-precision DETECT/triage slice** (26 % recall, 0 % false-fire on premature
completion) — *legibility*, not lift. The ~90 % planning + silent-stop head is the off-limits
strategic-reasoning lever. The one unrun move that could show a *lift* is the **weak-model corpus**
($50 DeepSeek/Qwen + the $0 `weak_model_gate.py`): a weaker model should fail *more* at the substrate
DOS guards — but the gate's enrichment filter means it only "passes" if those failures are real, not
noise, and the FIX (conversion) only lands if the weaker model can do the step when nudged. The
pre-registered prediction and the cheap-kill condition are in **docs/153 §3**.

---

## The coordination rule (read this BEFORE starting parallel research on this repo)

> **Before you write `docs/NNN`, claim the number: `ls docs/ | tail` to find the highest, take the
> next, and IMMEDIATELY add your one-line row to this index file in your first commit — the index is
> the lease. Before you edit a hot shared file (`live_ab.py`, `RESULTS.md`, a `dos_react` arm), grep
> the recent `git log -5 <file>` for an in-flight agent and prefer ADDING a new arm/script over editing
> the shared path. Headline only MEASURED numbers, and write each measured number to the registry
> table above so it cannot drift. One finding, one row — not one finding, one new numbered doc that
> later contradicts another.**

(This rule exists because two agents took `docs/151` simultaneously and `live_ab.py` accreted ~5
near-duplicate fixes across agents — the friction the operator named. The deeper structural option —
make the arc ONE living lab-notebook + this registry instead of 11 numbered docs — is under
evaluation; this index is the minimum that makes the collisions *visible* either way.)

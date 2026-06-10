# Glossary — the terms used across the Toolathlon replay, docs/157–159, and the additivity ledger

A single reference for every term the benchmark docs use without expanding it. The `EXPLAINER.md`
"Basic terms" table is the *read-this-first* short version (replay mechanics); this is the *full*
reference, and it adds the **evidence-ladder vocabulary** (`byte-clean`, `byte-author`, `forgeable`,
`net-new`, `additivity`, the `frontier` cut, `SSOT`) that `docs/158` and `_results/additivity_claims.md`
lean on heavily.

Every definition here is grounded in the code it names — the detector grammar in
`benchmark/toolathlon/trajectory.py`, the verdict vocabularies in `src/dos/tool_stream.py` /
`src/dos/dangling_intent.py`, and the numbers in `additivity.py`. When a term has a canonical kernel
definition, this entry is the *benchmark-local* gloss and points at the kernel module; the
authoritative kernel-internal glossary lives in the repo-root `CLAUDE.md` ("Glossary — acronyms used in
this contract").

---

## 1. The benchmark & data

| Term | What it means |
|---|---|
| **Toolathlon** | An external benchmark (ICLR 2026): 108 long-horizon tasks where an agent must use 600+ real tools across 32 apps (Gmail, Notion, k8s, WooCommerce…). Hard — the best model passes <40%. DOS did not build it; we **replay** its published trajectories. |
| **Toolathlon-Trajectories** | The published dataset of recorded runs: **7,116 records** = 22 models × 3 runs × ~108 tasks. The frozen input to the whole study. |
| **trajectory** | The full recorded transcript of *one* agent attempt at *one* task: every message, every tool call, every tool result. Parsed by `trajectory.py:parse_record`. |
| **replay** | Running DOS's detectors over the *frozen* trajectories offline ($0, no live env, no LLM). Because the runs are recordings, nothing can intervene — this measures **DETECT**, never **FIX**. |
| **the third-party oracle** | Toolathlon's OWN pass/fail judge (`evaluation/main.py`). It reads the *real app state* after the run (did the email actually send?) and returns true/false. **Authored by Toolathlon, not by us** — a verdict DOS cannot fake. An agent saying "I'm done" cannot make it pass. This is the **label** every detector is scored against. |
| **`replay_all_rows.csv`** | The durable per-run join: one row per trajectory, carrying the model, the oracle label, and each detector's fire bit. The single frozen artifact `additivity.py` recomputes every published number from. Has a content **fingerprint** (`sha256:…`) so a stale ledger vs a regenerated CSV is detectable. |

## 2. The three detectors

All three are **byte-clean** (see below) and **advisory** — they REPORT, they never block, kill, or
refuse. Each reads only **environment-authored** bytes (the tool-result `content` the MCP gateway
produced), never the agent's narration about itself.

| Detector | Kernel module | Fires when… | In one phrase |
|---|---|---|---|
| **`dangling_intent`** | `src/dos/dangling_intent.py` | the agent's **last message admits unfinished work** ("I still need to update the rest…") **AND nothing acted after it** (no real tool ran). | *said it wasn't done, then stopped.* |
| **`tool_stream`** | `src/dos/tool_stream.py` | the **same `(tool, args, result_digest)` triple recurs** `repeat_n` times in a row — the agent re-asks a question the env keeps answering identically. | *spinning in place, learning nothing.* |
| **`terminal_error`** | `trajectory.py` (`terminal_error_fired`, `is_struct_error`, `TerminalErrorEvidence`) — the docs/158 detector | the agent **stopped while the env's last word was a structured error** (a crash, an `MCP error -3xxxx`, `isError:true`, a `Traceback`, a non-zero exit, a permission-denied) **and no later result from the same tool recovered**. | *walked away from a wall the env clearly reported.* |

## 3. The evidence-ladder vocabulary (the load-bearing terms)

These are the DOS-specific concepts that make a detector's verdict *worth acting on*. They are why
`terminal_error` shipped and two tempting alternatives (hedge-scoring, claim-vs-narration) were
**rejected**.

| Term | What it means |
|---|---|
| **byte-author** | *Who actually produced the bytes a verdict reads.* The single invariant of the whole trust model: a verdict is trustworthy only when its **byte-author ≠ the judged agent**. The env's tool results are authored by the MCP gateway; the agent's narration is authored by the agent. |
| **byte-clean** | A detector is byte-clean iff it reads **only bytes the judged agent did not author** (env tool-results), never the agent's own claims about itself. The agent can't forge "the same result came back 3×" or "the env returned an error" — the env wrote those bytes. This is what makes a fire trustworthy. The canonical byte-clean field is `tool_stream`'s `result_digest`; `terminal_error`'s error-envelope has identical provenance. |
| **forgeable** | The opposite of byte-clean: a signal that reads **agent-authored** bytes (its narration tone, its self-described confidence). It shows fake recall on a frozen dataset and **collapses to zero on deployment**, because a model just learns to stop emitting the give-away phrase. The reason hedge-scoring and completion-without-verification were rejected (docs/158 §5). |
| **mirror-verifier (trap)** | A "verifier" that checks one agent-authored thing against another agent-authored thing — e.g. the agent's claim vs the agent's last narration. It *looks* like effect-checking but has no env-authored operand, so it is consistency, not grounding. (`docs/143 §5a`, `[[project-dos-byte-inequality-and-derivatives]]`.) |
| **consistency ≠ grounding** | Re-deriving an author's OWN bytes proves *consistency*; checking against a DIFFERENT byte-author proves *grounding*. Only grounding crosses the trust floor. |
| **structured error envelope** | The TIGHT grammar `terminal_error` matches — *shapes*, not loose substrings: `MCP error -3\d{4}`, `"isError":true`, a leading `Error:` node, a `Traceback`, a non-zero `exited with code N`, a `permission denied`. Anchored deliberately: a LOOSE match on the words `error`/`failed`/`not found` fires on legitimate env PAYLOAD (an arXiv abstract about "error rates", a "404" in fetched HTML) — measured at **69.4% false-alarm** vs the tight grammar's **0.2%** (a ~350× gap). The same tight-anchor discipline as the `result_digest` normalizer (docs/157 §4). |
| **`result_digest`** | `tool_stream`'s canonical byte-clean field: a digest of the **env-authored** tool-result `content`, normalized to strip volatile fields (timestamps, request-ids) so that *semantically identical* results compare equal. `result_digest=None` means errored/no-result and can never match another step (fail-safe). |
| **ABSTAIN** | The safe non-answer. When evidence is insufficient or a transform is non-deterministic, a DOS adjudicator returns ABSTAIN rather than guessing — it can *refute* but never *falsely affirm*. (`run_judge` converts any raise/bad-return to ABSTAIN, never AGREE.) |
| **`derived_witness` / `believe_under_floor`** | The kernel seam (`src/dos/evidence.py`) for crossing the trust floor: a claim is believable only if its operands are themselves non-forgeable AND the deriving operation is declared AND the result matches. The $-tier **live post-hoc re-read** (docs/158 §6) is this with a THIRD_PARTY operand fetched on demand. |

## 4. The metrics

| Term | Definition | Ours |
|---|---|---|
| **fire / fire-rate** | A detector "fires" when it flags a run. Fire-rate = fraction of all runs it flags. | `terminal_error` 1.2%; the detectors are quiet by design. |
| **precision** | When it fires, how often is it right? = (fires that were real failures) ÷ (all fires). | `terminal_error` 95.0%; trio union 92.6%. |
| **recall** | Of all failures that happened, how many did it catch? = (failures flagged) ÷ (all failures). **The low number.** | pair 4.74% → trio 6.18%. |
| **base-fail-rate** | How often runs fail anyway (the benchmark is hard). A detector that flagged *everything* would be "right" this often by luck — so precision must beat it to mean anything. | 76.2%. |
| **lift** | precision − base-fail-rate. "How much better than guessing." | `terminal_error` +18.8pp. |
| **false-alarm rate** | Of all *passing* runs, how many did it wrongly flag? = FP ÷ all passes. The precision cost of widening a detector. | `terminal_error` 0.24%; loose grammar 69.4% (rejected). |
| **TP / FP / FN** | True-positive (fired on a real failure) / false-positive (fired on a pass) / false-negative (a failure it missed). The confusion grid; here the **FN cell dominates** (most failures are silent). | — |
| **DETECT vs FIX** | DETECT = does the detector spot failures? (measured, offline). FIX = if we warned the agent, would it then pass? (NOT measured — needs a live run, Phase 4). The whole study is DETECT. | — |

## 5. The additivity story (docs/158)

The terms specific to "is `terminal_error` a *distinct* slice or a re-catch?" — recomputed by
`additivity.py` and pinned by `--check`.

| Term | What it means |
|---|---|
| **net-new** | A catch made by `terminal_error` that **neither** `dangling_intent` **nor** `tool_stream` made. The additivity headline: **75 of `terminal_error`'s 76 catches are net-new** (only 1 overlap) — a different failure mode, not redundancy. |
| **additive** | Adding the detector *raises union recall* because its catches are mostly net-new. Trio union recall 4.74% → 6.18% (+30% relative). Contrast a detector whose catches all overlap the existing pair (zero additivity). |
| **union recall / union precision** | The metric for a *set* of detectors: a run is "caught" if **any** member fires. Union recall = caught-failures ÷ all-failures across the set; union precision = real-failure-fires ÷ all-fires across the set. |
| **pair → trio** | Shorthand for the before/after: the **pair** = `dangling_intent` + `tool_stream` (the docs/157 baseline); the **trio** = pair + `terminal_error` (the docs/158 result). |
| **frontier** | A capability **THRESHOLD**, not a fixed model list: the models above a chosen Toolathlon pass-rate cut. Strong models fail *quietly* (no dangling cue, no visible loop), so the pair goes nearly silent there. The net-new count is **threshold-sensitive**, so docs/158 reports **three honest cuts** (top-4 / ≥0.30 / top-10 → +7 / +9 / +12). |
| **the ≥0.30 cut (SSOT default)** | The default frontier cut used by `fig6` and the ledger: the **8** models with pass-rate ≥ 0.30. On it, the pair catches 6 and `terminal_error` adds **9** net-new. |
| **"additive, not first"** | The honesty correction baked into every frontier claim: `tool_stream` **already** catches some frontier failures (4 on the strongest models), so `terminal_error` is the first signal for the strong-model failures the **pair misses**, **NOT** the first DOS signal to reach the frontier at all. A stale draft over-claimed "22 net-new / pair 35" from a hand-picked 10-model set that no principled cut reproduces. |
| **SSOT (single source of truth)** | `additivity.py:compute()` — the one function the figures, the ledger, and the 5 tests all consume, so no published number can drift. `--check` asserts 6 structural invariants and exits non-zero on drift; `--emit` writes the ledger with a CSV fingerprint. |

## 6. The figures

| Figure | Shows |
|---|---|
| `figA_additivity_headline` | the two load-bearing claims: 75/76 catches net-new (left); union recall +1.43pp with precision flat + false-alarm cost on the twin axis (right). |
| `figB_per_model_catches` | all 22 models, capability-ascending; grey = caught by the pair, purple = `terminal_error` net-new; the shaded band = the ≥0.30 frontier. |
| `figC_frontier_sensitivity` | the honesty figure: net-new vs the capability cut (9 at ≥0.30 vs 22 at top-10, where o3 alone supplies 12), and per-model net-new ranked. |
| `fig6_trio_additivity` | the headline trio additivity at the ≥0.30 SSOT cut. |
| `fig1`–`fig5` | the docs/157 replay figures (purchase-vs-capability, per-model grid, Simpson, confusion, lift-vs-recall). |

## 7. Kernel acronyms referenced in passing

These appear in the docs but belong to the kernel; full definitions in `CLAUDE.md`.

| Acronym | Expansion (benchmark-relevant sense) |
|---|---|
| **DOS** | Dispatch Operating System — the trust kernel whose detectors this benchmark replays. |
| **MCP** | Model Context Protocol — the gateway that authored the tool-result bytes. "MCP error -3xxxx" is its JSON-RPC error code, the canonical structured error envelope. |
| **§5a line** | The rule from `tool_stream` §5a: a byte-clean detector reads provenance-of-output, never a "is the agent succeeding?" satisfaction predicate. The line `terminal_error` had to stay inside. |
| **EOG** | End-Of-Generation — the silent-failure ceiling: a run that ends with no error and no contradiction because the agent never re-read the state it claims it changed. The residual `terminal_error` can't reach (docs/158 §6). |
| **ORACLE → JUDGE → HUMAN** | the trust ladder: deterministic verdict first, advisory non-deterministic adjudicator only on the residue, human only at the irreducible seed. The third-party oracle is the ORACLE rung; the rejected hedge-scorer would have been a forgeable JUDGE. |

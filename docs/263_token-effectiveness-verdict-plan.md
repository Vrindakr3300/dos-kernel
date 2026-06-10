# 263 — EFF: the token-effectiveness verdict

> **Status:** shipped (2026-06-09). The forcing question (operator `/goal`): *make
> DOS 3× better at supporting token-effectiveness understanding.* This doc records
> the gap that was found, the one primitive built to fill it, why it is byte-clean,
> and why the default is deliberately conservative. The module
> (`dos.efficiency`), the CLI verb (`dos efficiency`), and the test pin
> (`tests/test_efficiency.py`, 24 cases) are landed; `EFFICIENT 0 / COSTLY 3 /
> WASTEFUL 4` is in the `dos exit-codes` contract and `dos doctor --json`.

---

## 1. The gap

The kernel had two loop-economics verdicts and a clean hole between them:

| Verdict | Module | The question | The shape |
|---|---|---|---|
| `liveness()` | `dos.liveness` | did state move *at all* since start? | a binary, lifetime count |
| `productivity()` | `dos.productivity` | is the work-per-step *rate* fading? | a trend over per-step deltas |
| **`efficiency()`** | **`dos.efficiency`** | **did the tokens *buy* work?** | **a ratio: work / tokens** |

`liveness` reads a single since-start count; `productivity` reads a *trend* of
per-step work deltas; **neither relates the work to its price.** A run can be
ADVANCING (it committed) AND PRODUCTIVE (each step lands work) and still be
spending ten times the tokens that work was worth. The operator who asks about
"token effectiveness" is not asking "is the run moving" — they are asking "is the
run **spending well**." That is a *ratio* — work per token — and nothing in the
kernel computed it.

The nearest adjacent things, and why none of them was the answer:

- `liveness.ProgressEvidence.tokens_spent_since` already carries a token count, but
  only as an *optional waste signal* feeding the binary did-it-move verdict — it
  never becomes a ratio or a verdict of its own.
- `productivity` reads work deltas but is *deliberately blind to tokens* — it
  compares magnitudes step-to-step, never work-to-price.
- The `loop_authoring` benchmark (docs/260) prices loop-control *divergences* in
  dollars, but that is about whether a prose loop reproduces `loop_decide`, not
  about a live run's token economics.
- The `trajectory-audit` skill detects token waste *post-hoc across sessions* — a
  retrospective skill, not a kernel verdict a live loop or `dos top` can read.

So the highest-leverage move — and the one that fits the kernel doctrine
(mechanism is a small pure cog; policy is data) — was to give the kernel a
first-class **token-effectiveness verdict**, the lateral sibling of
`productivity`, re-aimed from a trend onto a ratio.

## 2. The primitive

`efficiency.classify(EfficiencyEvidence, EfficiencyPolicy) -> EfficiencyVerdict`,
PURE, no I/O, timeless (it reads two numbers, not ages — the `productivity`
discipline). Three mutually-exclusive verdicts:

- **EFFICIENT** — the ratio `work / tokens` is at/above the floor (or there is too
  little spend to judge, or the floor is disabled and work is nonzero). The tokens
  bought their work.
- **COSTLY** — meaningful spend AND nonzero work AND the ratio is *under* the
  floor: the run is doing work but paying a lot per unit (fading efficiency, not
  pure waste). The efficiency analogue of `productivity.DIMINISHING`.
- **WASTEFUL** — meaningful spend AND **zero** work: the tokens bought nothing
  (pure overhead). The degenerate floor — the analogue of `productivity.STALLED`,
  and the operator's clearest "the spend was wasted" signal (the 252-marker /
  $7.80 keep-alive bleed `loop_decide.py` records is exactly this shape).

The ladder is read top-to-bottom: too-little-spend → WASTEFUL (zero work) → COSTLY
(low ratio) → EFFICIENT. The verdict IS the exit code (`EFFICIENT 0 / COSTLY 3 /
WASTEFUL 4`, contract-error 2), the verdict-is-exit-code idiom every verdict-bearing
verb shares, so a babysitter loop branches without re-parsing.

## 3. Why it is byte-clean (the docs/138 invariant)

The whole point of DOS is that the kernel does not believe what an agent says it
did. EFF holds that line: **both inputs are counts the runtime/environment authors,
never the agent's narration.**

- `tokens` is the provider usage record — what the API *billed* this run. The
  agent does not author its own token count.
- `work` is a count of ground-truth work the environment *witnessed*: commits the
  git machinery wrote, bytes a diff measured, tests the runner passed — the same
  work-unit `productivity` counts and the same kind of fact `verify` confirms off
  git.

So WASTEFUL is "the environment recorded N tokens spent and ~0 work landed," never
"the agent says it was inefficient." And — this is the load-bearing property —
**the verdict is non-forgeable in the direction that matters**: an agent cannot
move the verdict *toward* EFFICIENT by narrating productivity, because the
numerator is work the environment witnessed, not a claim the agent emitted. This
is the same reason `reward.admit` trusts the read-back and not the answer text:
the bytes that move the verdict are bytes the claimant did not write.

EFF reports a **price, never a quality** (the `productivity` line, held): it says
the cost-per-unit-of-work is high; it never says the work was *wrong*. A run can be
correct and WASTEFUL (it burned tokens deliberating / re-reading / marker-spinning)
or EFFICIENT and wrong (cheap garbage). Quality is an advisory judge's call
(`llm_judge`), never this deterministic verb.

## 4. Why the default floor is disabled (0.0)

The one real design decision. `productivity` could lift a genuine constant from
Claude Code's own loop (`tokenBudget.ts`'s 500-token diminishing threshold). EFF
**cannot**, because there is no universal "good" work-per-token ratio — it depends
entirely on what the host counts as a work unit. A ratio sensible for "changed
bytes per token" is meaningless for "commits per token." Shipping a guessed floor
would manufacture COSTLY verdicts out of a *unit mismatch* — precisely the
docs/235 slice-must-have-power failure (a threshold that fires for the wrong
reason is worse than no threshold).

So the split is:

- **WASTEFUL is always-free and unit-independent.** Zero work is zero work whatever
  the unit, so the "tokens bought literally nothing" verdict fires with no floor
  needed. This is the half of the verdict every consumer gets for free.
- **COSTLY is opt-in.** A host arms it by declaring a `floor` (CLI `--floor`, or
  the forward-looking `dos.toml [efficiency]` table, the same seam `productivity`
  documents) that means something for *its* work unit. Until then, every
  nonzero-work run is EFFICIENT.

`min_tokens` (default 1000) is the withhold-the-accusation guard — the
`productivity.min_steps` / `liveness.grace_ms` analogue, measured in spend: below
it the run has barely started and a low ratio is not yet real signal, so the
verdict reports EFFICIENT-benign.

## 5. What this is NOT (and the honest scope)

- It is **not** a cost model. EFF compares a ratio to a floor; it does not price
  tokens in dollars or model the dollar waste of a divergence (that is the
  `loop_authoring` scorer's job, docs/260). The dollar framing belongs to a
  consumer, not the verdict.
- It is **not** a quality or correctness signal (§3).
- It does **not** read telemetry itself. Like every verdict in the family the I/O
  is gathered at the caller's boundary (a loop reading the provider usage record +
  its own git delta) and frozen into `EfficiencyEvidence`; `classify` is pure.
- The honest single-run win is **understanding**, not enforcement: EFF gives an
  operator (or `dos top`, or a `loop_decide` rung) a typed, non-forgeable read on
  *whether a run is spending well* — the thing that was previously only knowable by
  hand-reading a trajectory after the fact. The fleet win is the same one the rest
  of the kernel has: the verdict is a pure function K loops can each call
  identically, so a fleet's token-effectiveness becomes legible at fan-out without
  trusting K self-reports.

## 6. Follow-ups (not built here)

- **`dos.toml [efficiency]` loader.** Today the floor + min_tokens come from CLI
  flags and the generic dataclass defaults (the same state `productivity`'s config
  table is in — documented, flag-driven, not yet parsed from `dos.toml`). Wiring
  the `[efficiency]` table is the natural next seam.
- **`dos top` surface.** EFF is a clean column for the live fleet-watchdog (a
  WASTEFUL run is exactly what an operator wants flagged) — a read-only projection
  consuming the verdict, no new mechanism.
- **A `loop_decide` rung.** A `DIMINISHING_RETURNS`-style stop that converts a
  sustained WASTEFUL/COSTLY verdict into a stop-when-unproductive transition (the
  consumer `productivity`'s docstring already anticipates, generalized to the
  ratio).

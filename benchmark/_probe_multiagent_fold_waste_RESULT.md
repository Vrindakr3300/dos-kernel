# Multi-agent fold-waste probe — RESULT (2026-06-07)

The k>1 mirror of the k=1 horizon-keeper probe. Where the k=1 probe measured *temporal*
waste (one run fading), this measures the one *multi-agent* waste species cheaply available
on this machine: **the fold** (docs/197) — a parent spawns N children, some die, the parent
folds the dead child's "result" as if real. Probe: `_probe_multiagent_fold_waste.py`.
Read-only over the 6,306 real workflow-child transcripts (`agent-*.jsonl`).

## The multi-agent waste taxonomy (only C is measurable here)

| species | what it is | DOS instrument | measurable here? |
|---|---|---|---|
| **A. Collision** | two agents touch the same region → retry/overwrite tokens | lane-journal REFUSE events; `arbitrate` | **No** — no real lane journal (`~/.dos` missing; benchmark-synthetic only) |
| **B. Redundancy** | N agents solving the SAME subtask; N−1 wasted | `lane_overlap` footprint dedup | No — needs semantic trajectory dedup, not cheap |
| **C. The fold** | a parent believes a DEAD child's self-report | `verify-result` / `effect_witness` | **YES — this probe** |
| **D. Coordination** | tokens spent polling/talking, not working (the status tax) | the durable-commons read | No — not separable from work in a raw transcript |

## The result (after splitting a v1 magnitude artifact)

| verdict | count | % of judged | tokens (median) |
|---|---|---|---|
| **ANY DEATH** | 2,060 | **32.7%** | — |
| ↳ DIED_ON_SPAWN (clean fold-waste) | 1,260 | **20.0%** | **0** (die cheap) |
| ↳ DIED_LATE (worked then errored) | 800 | 12.7% | 623,936 |
| COMPLETED | 4,241 | 67.3% | — |

(6,306 children judged; 5 EMPTY. v1 lumped both deaths into "DEAD" and counted DIED_LATE's
pre-death work as waste → a bogus 1.05B-token / 11.7% figure. The split is the honest fix.)

## The headline — a RATE problem, not a TOKEN problem

**1 in 3 workflow children dies (32.7%)** — and the rate **independently corroborates
docs/197's 32% parent-side fold measurement** on a 5× larger corpus (6,306 vs ~2,305). Of
those, **20% died on spawn having done ZERO work** — a parent got a result string back for
nothing (the clean fold-waste). The other 12.7% worked (median 624k tokens) then errored
late — partial work, *not* counted as waste.

**The token waste is negligible — and that is the point.** Dead-on-spawn children die
**cheap** (median 0 tokens, p90 0 — they error on the spawn turn), so the clean spawn-waste
token pool is **0.02%** of all child tokens. You **cannot see multi-agent fold-waste by
watching token spend.** The damage is not the spawn tokens — it is that the parent folds a
zero-work "result" as if it were real and **builds downstream on garbage** (docs/197: the
doc-writing workflow reported `completed` having silently lost 4 of 6 children). So
multi-agent fold-waste is a **correctness/trust** failure, not a cost failure — which is
exactly the regime DOS's `verify-result`/`effect_witness` exist for, and exactly the regime
a token-budget watchdog (the k=1 lever) is **blind** to.

## The two halves of the plane, two waste signatures

- **k=1 (horizon):** waste is *temporal* and *visible in tokens* — ~4% of long-session spend
  in a fading tail. A token/productivity watchdog catches it.
- **k>1 (fold):** waste is *trust* and *invisible in tokens* — 0.02% of spend, but a third of
  children folded as garbage. Only an artifact-checking witness (`verify-result`) catches it;
  a token watchdog sees nothing.

This is why the two regimes need different DOS syscalls: `productivity`/`liveness` for the
solo long horizon, `verify-result`/`effect_witness` for the fleet fold. The single number
"% of spend wasted" is the WRONG lens for the fleet — it hides the failure that matters.

## Honest ceiling (the same as the k=1 probe)

- This is the **CHILD-SIDE dead rate** = an UPPER BOUND on fold-waste. The full claim is
  "the parent FOLDED the dead result as real," which needs the parent↔child join (does the
  parent transcript reference the child id and continue as if it succeeded?). docs/197
  measured the parent side at 32% on a smaller corpus; this corroborates the child side at
  32.7%. The believed-vs-discarded split is the named follow-up.
- **Collision-waste (species A) is unmeasured here** — no real lane journal. Measuring it
  needs a real dispatch-loop fleet writing `OP_ATTEMPT`/`REFUSE` to a non-synthetic journal,
  then folding the refusal + re-attempt cost (the trajectory-audit skill's contention join).

## Reproduce

```bash
python benchmark/_probe_multiagent_fold_waste.py   # ~20s over ~/.claude/projects; table + JSON
```

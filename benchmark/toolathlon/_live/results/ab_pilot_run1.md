# F0 tool_stream WARN A/B — pilot run 1 (gemini-2.5-pro, N=1)

> **The honest result: NO MEASURED CONVERSION — because the WARN never fired.** The apparent +1
> task is run-to-run variance, not the intervention. Recorded in full because a null from a starved
> arm is as important as a positive, and the trajectory-level analysis is the finding.

**Date:** 2026-06-05. **Model:** gemini-2.5-pro (public OpenAI-compat endpoint). **Subset:** the 6
loop-enriched pure-local tasks (where this model fired tool_stream in the FROZEN replay). **Arms:**
OBSERVE (stock harness) vs WARN (`DOS_WARN=1`, tool_stream re-surface installed). **1 rep each.**

## Raw scoreboard (third-party oracle)

| task | OBSERVE pass | OBSERVE ts | WARN pass | WARN ts | WARN re-surface fired? |
|---|---|---|---|---|---|
| academic-pdf-report | False | ADVANCING | False | ADVANCING | no |
| arrange-workspace | **None** (max_turns, 283 msgs) | **STALLED** | **True** | ADVANCING | **no** |
| dietary-health | False | ADVANCING | False | ADVANCING | no |
| logical-datasets-collection | False | ADVANCING | False | ADVANCING | no |
| sales-accounting | False | ADVANCING | False | ADVANCING | no |
| shopping-helper | None | ADVANCING | False | ADVANCING | no |

OBSERVE: 0 pass / 4 scorable / 2 errored. WARN: 1 pass / 6 scorable / 0 errored.

## Why the +1 is NOT a WARN conversion (the trajectory-level check)

The tempting read is "WARN flipped arrange-workspace fail→pass (+1 task)." The trajectories refute it:

1. **The WARN re-surface fired ZERO times across all 6 WARN-arm runs** (grep of the run logs +
   conversation histories for the injected "[DOS tool-stream WARN]" text = 0). The patch was *installed
   and active* (the `[DOS sitecustomize] WARN arm active=True` breadcrumb is in every run.log), but
   tool_stream never reached REPEATING/STALLED in any WARN-arm run, so nothing was ever injected.
2. On `arrange-workspace` specifically: OBSERVE **STALLED** into `max_turns_reached` (283 messages — a
   genuine loop, the failure WARN targets). The WARN-arm run of the same task went **ADVANCING** from
   the start and passed — i.e. the agent simply *did not stall this run*, so the patch had nothing to
   act on. The flip is the model not reproducing the loop, **not** the WARN unsticking it.

So the WARN's effect on this run is **unmeasured** (it never actuated), and the pass-rate delta
(+1 task) is run-to-run variance of a stochastic model, not the intervention.

## What this confirms (the honest finding)

The **starved-arm problem, reproduced LIVE.** The replay showed these tasks fired tool_stream for
gemini-2.5-pro *historically*, but a fresh live run did not reproduce those exact loops (stochasticity).
A WARN acts ONLY on fires; with zero live fires, the A/B measures nothing about the WARN — exactly the
[[project-dos-toolathlon-live-ab-prereqs]] prediction. It is consistent with the EOG record: the
DETECT signal is rare and the FIX has nothing to grab when the loop doesn't recur.

## Next step to actually measure a conversion (the fix for the starve)

The fire-rate must be raised so the WARN actuates. Options, cheapest first:
1. **More reps** (3–5×) — a stochastic model will stall on SOME reps; accumulate the runs where
   tool_stream DID fire and measure the conversion only on those (the paired fire-subset). The batch
   runner is resumable; re-run `run_ab.sh 5`.
2. **A weaker / more loop-prone model** — gemini-2.5-flash fired tool_stream MORE in the replay
   (11 vs 9 convertible loops) though at a lower base pass-rate; it stalls more, so the WARN actuates
   more (trade: a noisier *lift* number, a cleaner *conversion-rate* number).
3. **Lower the policy threshold** — `StreamPolicy(repeat_n=2)` fires earlier (more actuations, more
   false re-surfaces — the precision/recall knob). Keep the default for the headline; sweep as a
   sensitivity.

The mechanism is PROVEN (the patch installs + runs + is byte-clean); what is unproven is the
conversion rate, because this rep never triggered it. Report the conversion number only from runs
where the WARN actually fired.

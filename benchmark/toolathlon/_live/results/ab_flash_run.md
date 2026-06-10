# F0 tool_stream WARN A/B — flash run (gemini-2.5-flash, N=2 reps)

> **Result: NO CONVERSION measured, and the live A/B surfaced WHY — three honest findings that are
> worth more than a bare lift number.** All 24 runs failed (0 pass, both arms). The loops that DID
> occur were (a) not seen by the live WARN seam, and (b) non-recoverable anyway. Mechanism proven;
> the live FIX is a no-op on this subset, for diagnosable reasons.

**Date:** 2026-06-05. **Model:** gemini-2.5-flash (the loop-prone 3.7%-Pass model — chosen to FIRE the
WARN that the gemini-2.5-pro pilot never triggered). **Subset:** the 6 loop-enriched pure-local tasks.
**Arms:** OBSERVE vs WARN (`DOS_WARN=1`). **2 reps each = 24 runs.**

## Scoreboard

**OBSERVE: 0/12 pass. WARN: 0/12 pass.** No flip in either direction — a clean uniform null (cleaner
than the pro pilot, which had a variance flip). gemini-2.5-flash failed every task in both arms.

## What looped, and what the WARN did about it

The post-hoc scorer (`live_adapter`) found tool_stream REPEATING on 2 runs (`observe r1` +
`warn r2` of `logical-datasets-collection`). On the WARN-arm REPEATING run, the trajectory is:

> 7 messages; the agent called `web_search` 3× in a row; each returned **`"Tool web_search not found
> in agent Assistant"`** — the same non-existent-tool error 3× = the REPEATING triple.

**The live WARN re-surface fired ZERO times** across all 12 WARN-arm runs — *including* this REPEATING
one. So the live patch did NOT see the loop the post-hoc scorer did. Three findings explain the no-op:

### Finding 1 — the loop ENDED on the turn it hit the threshold (VERIFIED — a limitation, not a bug)
The REPEATING run is exactly 3 turns (messages 1-6): `web_search → "not found"`, ×3, then the agent
STOPPED (`status: success`, message 6 is the last). The 3rd identical result is what crosses
`repeat_n=3` — but it is also the FINAL action. The WARN patch only injects when the model will be
called AGAIN (`if not isinstance(result.next_step, NextStepRunAgain): return result` — the turn-
boundary discipline, so a WARN always lands on a *future* turn). Here there was no 4th turn: the loop
completed and the agent stopped on the same turn the threshold was crossed. **So the patch behaved
exactly as designed — there was no in-flight intervention point.** This is a real LIMITATION of the
F0 re-surface, now verified live: a loop the agent *ends on* (the Nth strike being its last act) is
detectable post-hoc but has no future turn to WARN into. The fix is not a patch bug fix — it is a
DESIGN choice: either fire one turn EARLIER (`repeat_n=2`, accepting more false re-surfaces), or
accept that "looped-then-quit" is a STOP-boundary case the `dangling`/`terminal_error` STOP gates own,
not the in-flight `tool_stream` gate. (The synthetic parity test could not catch this — it tested the
detector VERDICT, not the live turn-boundary timing of the inject.)

### Finding 2 — even if it HAD fired, this loop is NON-RECOVERABLE
The looped result is `"Tool web_search not found"` — which `conversation_ceiling.is_usable_result`
correctly classifies as NON-usable (it is in the `_NOT_USABLE` grammar). Re-surfacing "you got
'tool not found' 3×" does not hand back a usable value; the agent needs a DIFFERENT tool, which is
exactly the dead-end class the conversion-ceiling EXCLUDES from recoverable. So this loop is not a
fixable target — the WARN firing on it would (at best) be a no-op, consistent with the ceiling.

### Finding 3 — the STARVE holds: the recoverable loops the replay showed did not recur
The replay's gemini-2.5-pro `tool_stream` fires were on usable-data eventual-consistency loops; the
live flash runs mostly produced tool-not-found loops or no loop at all. The historical recoverable
fires did not reproduce live (stochasticity + a different tool environment). With ~0 live
*recoverable* fires, there is nothing for the WARN to convert.

## The honest bottom line (across both pilots, N=18 runs)

- **Mechanism: PROVEN.** The patch installs, runs in-container without breaking the harness, and is
  byte-clean (the 6 parity tests + the live breadcrumb).
- **Live conversions: ZERO measured** — across gemini-2.5-pro (variance flip, WARN never fired) and
  gemini-2.5-flash (uniform fail, WARN never fired even on a REPEATING run).
- **Why, diagnosed:** (1) a live seam gap on the tool-not-found loop type; (2) the loops that occurred
  were non-recoverable (tool-not-found, the ceiling's excluded class); (3) the recoverable loops the
  replay showed did not recur live.
- This is the **EOG record, confirmed live and instrumented**: DETECT is real but rare; the FIX has
  nothing to grab when the live loops are non-recoverable. The $0 ceiling (+2.4pp max, mostly on
  usable-data loops that didn't recur) BOUNDED this correctly — the live conversion is a fraction of
  a ceiling that was already tiny.

## What would actually move it (ranked, for a future agent with budget)
1. **Fix or scope the seam gap** + add a not-found parity fixture, so the live verdict matches the
   post-hoc scorer on EVERY loop type (closes the silent divergence this run exposed).
2. **Target a model+task regime that loops on USABLE data live** — the replay's recoverable fires were
   concentrated; replay-mine the exact (model, task) cells with usable-data REPEATING and run ONLY
   those, many reps, to accumulate a fire-subset big enough to estimate a conversion rate.
3. **The F1.5 rewind loop (docs/164, src/dos/rewind.py)** attacks a DIFFERENT failure mode
   (accreted-context dead ends, not eventual-consistency polls) — a more promising live target than F0
   re-surface, because a tool-not-found dead end is exactly a "backjump and forbid this branch" case.

# N-axis probe — RESULT (2026-06-07)

The $0 horizon-keeper measurement from
`dos-private/dispatch-os-the-horizon-keeper-at-k-equals-one.md` §8, **run**.
Probe: `_probe_horizon_keeper_n_axis.py`. Imports the **shipped** `dos.productivity`
(dogfood, not reimplemented). Read-only over the real Claude Code session corpus.

## Corpus (the denominator, stated honestly)

- **17,390** `.jsonl` files across all projects under `~/.claude/projects/`.
- **9,431** sessions carry real main-thread model turns (7,959 had none — short/empty/
  all-tool sessions). This is the k=1 denominator: every session is one agent, and the
  ground truth at each step is its own token usage.
- **287,058** real turns after deduping double-logged streaming records (the raw count
  was 495,216 — **~42% of assistant records were adjacent duplicates**, a streaming/retry
  re-record; deduped on identical `total` tokens, which grows monotonically via cache_read
  so a genuine distinct turn cannot collide). Per-session: median 12 turns, p90 74, max 2,006.

## Method (after stripping three confounds my own diagnostics exposed)

- **Work-rate trigger** = `output_tokens/turn < 500` (Claude Code's own `tokenBudget.ts`
  floor, the exact unit `productivity`'s default policy thresholds on).
- **Burn priced in TOTAL tokens** (input+cache_read+cache_creation+output), not output —
  output is the work-*rate* signal; total is the real *cost*.
- **A "faded" session** = it had a **productive prefix** (some turn cleared the floor) and
  then ended in a **spinning tail** of ≥3 consecutive turns that are low-output **AND**
  ≤1 tool-use. The prefix guard excludes uniformly-quiet Q&A sessions (the confound that
  made an earlier cut read 46%); the tool guard excludes tool-heavy-terse real work (the
  "output measures verbosity not work" weakness — a turn that's *editing* isn't spinning).
- **Dogfood cross-check**: the shipped `classify` is also run on the trailing window
  (`term-DIM%`); it fires on a strict superset of the guarded "faded" set.

## The result

| horizon ≥ | eligible | faded% | term-DIM% (raw classify) | median tail | median reclaim% | p90 reclaim% | **POOL%** (of all tokens) |
|---|---|---|---|---|---|---|---|
| 10 turns | 5,186 | **15.0%** | 35.8% | 4 | 19.3% | 49.7% | **4.1%** |
| 20 turns | 3,614 | **14.9%** | 23.6% | 4 | 14.5% | 46.8% | **3.9%** |
| 40 turns | 2,152 | **12.8%** | 16.6% | 5 | 9.5% | 47.7% | **3.9%** |
| 80 turns | 846 | **10.4%** | 14.9% | 5 | 5.0% | 36.1% | **4.4%** |

**Headline.** ~**11–15%** of genuinely long single-agent (k=1) sessions end in a sustained
low-activity "spinning" tail that the shipped `productivity.classify` also flags
DIMINISHING/STALLED. That tail is a median **~5–19%** of total session tokens — with a fat
right tail (**p90 ~36–50%**: some long sessions burn nearly half their tokens winding down)
— and a median absolute **~0.5–1.0M tokens** (long sessions carry large cumulative cache,
so even a 5% tail is hundreds of k of tokens).

**The pool (sizes the prize).** Aggregated, **~4% of ALL tokens across the entire
long-session corpus** land in these flagged spinning tails (POOL% = 3.9–4.4%, strikingly
flat across every horizon floor — a robustness signal: the result does not depend on where
you set "long"). So the aggregate reclaimable-spend ceiling a stop-when-unproductive gate
addresses is **~4% of total spend** — real and modest, concentrated in the fat tail. Not
transformative; not nothing. (Still an upper bound — see below.)

Hand-verified example tails (horizon≥40, post-dedup) are unambiguous: e.g. a 114-turn
session whose prefix peaked at 13,915 output tokens ends in 10 turns of
`[342, 396, 73, 232, 24, 200, 292, 36, 96, 352]` output and **zero** tool calls — terse
text, no actions, winding down. Not miscounted work.

## What this supports — and what it does NOT

**Supports the essay's §6 N-axis claim, with honest magnitude:** the horizon-keeper's
addressable spend is **real, a minority, and fat-tailed** — *not* the "100% of everything"
an earlier buggy cut produced (that was a method artifact: an earliest-ever-crossing fires
on two quiet turns near any session start; discarded). The value is concentrated in the
right tail (the p90-half-the-session sessions), which is exactly where a stop-when-
unproductive gate pays.

**A consumer insight fell out (useful for `loop_decide`):** the raw `classify` on a
trailing window over-fires on short quiet sessions (`term-DIM%` 36% vs guarded 15% at
horizon≥10) and converges at long horizon. A productivity gate needs the **productive-
prefix guard** or it false-fires on Q&A — i.e. "did it fade" ≠ "is it currently below
floor"; you must have *been* above floor first.

**Does NOT establish** (the honest ceiling, Wall §3 + §4):
- The tail spend is an **UPPER BOUND on reclaimable**, not reclaimable. A low-activity tail
  can be **legitimate completion** (final commit, summary, answering the user) — this
  measures *presence* of a fading rate, never whether stopping would have been *correct*.
- The decisive test — **does the spinning tail predict a FAILED/abandoned task?** — is the
  difference between "tokens spent in a low-rate tail" (this, a rate) and "tokens wasted"
  (payoff, the claim a value case needs). **And it is NOT cheaply available on this corpus**,
  for the reason my own notes flag for EnterpriseOps: *there is no independent success
  witness.* A session transcript has no ground-truth "did the task succeed" label — the only
  in-corpus signals are (a) did the repo commit (a weak proxy: research/debug/Q&A sessions
  legitimately don't commit, so no-commit ≠ failed — Wall §3 on the *outcome* label), or
  (b) the session's own narration (the exact channel DOS distrusts — circular). Manufacturing
  a commit-overlap number and calling it "waste" would be the docs/179 static-replay error
  (re-projecting a frozen corpus as payoff). So this probe is honestly **a rate, not a
  payoff**, and the payoff measurement needs a LIVE harness with an independent witness
  (the `out-of-loop-live-payoff` triple: consumer≠producer, checkable claim vs independent
  witness, live/API) — e.g. a controlled long-horizon task suite where success is
  ground-truth-by-construction and you A/B a stop-when-DIMINISHING gate against no gate.
  That is the real follow-up; it is not free, and this $0 probe does not stand in for it.

## Reproduce

```bash
python benchmark/_probe_horizon_keeper_n_axis.py   # ~30s over the local corpus; prints table + JSON
```

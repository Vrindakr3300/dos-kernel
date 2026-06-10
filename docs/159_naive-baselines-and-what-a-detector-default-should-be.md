# Naive baselines, the recall mirage, and what a detector's defaults should be

> **A reviewer's question on docs/158 — "this looks too good to be true; is it a real improvement,
> and what about a naive version?" — turned out to be the most useful thing asked of the whole
> detector line. Building the naive baselines and measuring them head-to-head against the shipped
> `terminal_error` produced (a) a clean refutation of the "naive did better" reading, (b) the precise
> reason recall is the WRONG scoreboard on this benchmark, and (c) one genuinely useful knob DOS can
> learn from a naive variant. This doc records the comparison, the lesson, and the DEFAULTS the lesson
> implies — so the next detector starts from the right baseline instead of re-discovering it.**

**Status:** analysis doc (no new kernel code). Every `terminal_error` / union / frontier figure is
the canonical one from the single-source-of-truth `benchmark/toolathlon/additivity.py` (`compute()`,
verifiable with `python -m benchmark.toolathlon.additivity --check`). The naive-variant figures were
measured by re-running the detector logic over the raw corpus (`benchmark/toolathlon/_data/`, 66
cached files) with the grammar/window swapped — **same records, same oracle labels, same labeled
denominator the SSOT uses, only the rule changed.**

> **A methodology note worth its own line (a trap I walked into writing this doc).** The corpus is
> 7,116 records but only **6,862 are LABELED** (have a pass/fail oracle verdict); 254 have no label.
> The SSOT — and `replay.py` — count over the **labeled** set only and **never guess** an absent
> label. My first pass hand-rolled a CSV counter that treated an empty `passed` cell as a failure
> (`not passed` is `True` for `""`), which inflated every count (76→84 catches, 4.74%→4.72% union,
> 9→10 frontier net-new). **Run the SSOT, don't re-derive** — `additivity.py` exists precisely so the
> numbers can't drift. All figures below are the SSOT's.

**Lineage.** Companion to `docs/158` (the `terminal_error` detector this stress-tests; its additivity
SSOT is `additivity.py`) and `docs/157` (the replay that set the precision/recall frame). The
"precision-above-base, not recall" scoreboard is the same one `dos.judge_eval` /
`dos.intervention_eval` / `dos.overlap_eval` already use (false-clear rate, lift-over-base) — this doc
is that discipline applied to the *grammar-design* choice. Inherits the byte-clean doctrine from
`docs/141` / `docs/143 §5a`.

---

## 1. The question

The `terminal_error` headline (docs/158) — 95.0% precision, additive on the frontier — drew the right
skeptical reflex: *is this a real gain, or is something missing, and would a dumb version do as well?*
Three naive baselines answer it:

- **`baseline-always-fail`** — predict every run failed. The degenerate detector; the floor any real
  signal must beat.
- **`naive-loose`** — the same closing-window structure as `terminal_error`, but the error grammar is
  a LOOSE substring match (`error` / `failed` / `not found` / bare `4xx` / `5xx` / `denied`) instead of
  a structured envelope. This is the exact rule docs/158 §4 *says* it rejected; here it is measured.
- **`naive-any-error`** — fire if a structured env error appears ANYWHERE in the run (drop the
  closing-window + recovery requirement). Tests whether the window logic earns its keep.

And one near-shipped variant, to find the honest knob:

- **`tight-no-recovery`** — the shipped tight grammar and closing window, but WITHOUT the
  "did a later same-tool call recover?" test.

## 2. The comparison (labeled corpus: 6,862 runs, 76.2% base fail rate)

"catches" = true-positive failures / false-positive passes. `lift` = precision − base-fail-rate (the
skill above guessing). `false-alarm` = fraction of PASSING runs that fire.

| Approach | fire | precision | **lift** | recall | **false-alarm** | catches (fail/pass) |
|---|---|---|---|---|---|---|
| `baseline-always-fail` | 100% | 76.2% | **+0.0pp** | 100% | 100% | 5228 / 1634 |
| `naive-loose` | 32.3% | 81.1% | **+4.9pp** | **34.4%** | **25.6%** | 1800 / 419 |
| `naive-any-error` | 19.5% | 81.4% | +5.2pp | 20.9% | 15.2% | 1090 / 249 |
| `tight-no-recovery` | 2.3% | 93.0% | +16.9pp | 2.8% | 0.7% | 147 / 11 |
| **SHIPPED `terminal_error`** | 1.2% | **95.0%** | **+18.8pp** | 1.5% | **0.2%** | 76 / 4 |

For reference, the other two shipped detectors and the union (SSOT figures):

| | dangling_intent | tool_stream | terminal_error | union (trio) |
|---|---|---|---|---|
| precision | 98.0% | 89.0% | 95.0% | 92.6% |
| recall | 1.8% | 2.9% | 1.5% | **6.18%** |
| false-alarm | ~0.1% | ~1.2% | 0.2% | 1.59% |

(Union recall pair → trio: **4.74% → 6.18%**, +1.43pp, **+30% relative**, at union precision 92.6%.
`terminal_error` contributes **75 net-new catches of its 76** — 1 overlap with the pair. Source:
`additivity.py`.)

## 3. The recall mirage — why "naive did better" is the wrong reading

Read by recall alone, `naive-loose` (34.4%) crushes `terminal_error` (1.5%) — a ~24× difference. That
reading is wrong, and the table shows exactly why.

**`baseline-always-fail` is the control that breaks the recall scoreboard.** It scores **100% recall**
by printing "fail" on every run. It is the most useless detector imaginable, and on a 76.2%-fail
benchmark it posts a *higher recall than anything we will ever build.* So recall, in isolation, ranks
the worthless detector first. Any honest comparison must score against the floor that 76.2% base rate
sets — which is what **lift** (precision − base) does:

- `baseline-always-fail`: **+0.0pp lift.** Zero skill, by construction — its precision *is* the base
  rate.
- `naive-loose`: **+4.9pp lift.** Its 81.1% precision is barely above guessing. It is most of the way
  to the worthless control: it mostly just fires a lot. The 34.4% recall is bought almost entirely by
  firing on **1 in 4 passing runs** (25.6% false-alarm).
- `terminal_error`: **+18.8pp lift** at **0.2% false-alarm.** Few fires, but each one is real and it
  almost never cries wolf.

So the shipped detector did not lose to the naive one. It made the **opposite trade on purpose**:
high precision / low false-alarm over raw recall, because a DOS verdict is meant to be *acted on*, and
a signal is only worth acting on if it is reliable. A detector that fires on a quarter of healthy runs
gets switched off the first day it pages someone for nothing.

**The one-line statement:** on a high-base-rate benchmark, *recall measures how often you speak;
precision-above-base measures whether you should be believed when you do.* DOS optimizes the second
because it actuates on the verdict (`docs/144` intervention ladder).

## 4. What DOS CAN learn from the naive variants

Two distinct lessons — one negative (load-bearing), one a real knob.

**4a. The tight grammar is load-bearing, not over-caution (the negative lesson).** docs/158 §4
*asserts* the grammar must be tight; this doc *measures* the cost of loosening it. Going from the
structured-envelope grammar to a loose substring match moves false-alarm **0.2% → 25.6%** — a ~130×
degradation — for a precision that lands ~5pp above the base rate. There is no recall-for-precision
trade worth that. Loosening the *reading of bytes already in the trace* cannot raise DOS's real skill;
it only buys false alarms. (The only honest way up is MORE INDEPENDENT EVIDENCE — a fresh third-party
byte — which is exactly why docs/158 §6 points at the live post-hoc re-read, not at a looser grammar.)

**4b. The recovery-check is a real recall knob (the positive lesson).** Compare the shipped detector
to `tight-no-recovery` — same tight grammar, same window, only the "did a later same-tool call
recover?" test removed:

| | recall | precision | false-alarm |
|---|---|---|---|
| shipped (recovery-aware) | 1.5% | 95.0% | 0.2% |
| tight-no-recovery | **2.8%** | 93.0% | 0.7% |

Dropping the recovery check **nearly doubles recall** for a still-tiny false-alarm cost (0.2% → 0.7%,
well under the deployable ceiling). That is a legitimate tunable, and it surfaces a real phenomenon
worth investigating: a class of failures end with a structured error that a later same-tool call
*nominally recovered* (so the recovery-aware detector stays quiet) **yet the run still failed the
final-state check.** The recovery was a false reassurance. Worth exposing as a confidence knob and
worth a follow-up read of those cases.

## 5. The defaults this implies (the reusable part)

The point of building the baselines is not the one detector — it is the **defaults the next detector
should inherit** so this is not re-litigated each time:

1. **Score detectors by lift (precision − base) and false-alarm, never recall alone.** On any
   high-base-rate slice, recall ranks `baseline-always-fail` first. The eval harnesses
   (`judge_eval`, `intervention_eval`, `overlap_eval`) already do this; a *detector* must too. A
   recall number without its precision-above-base and false-alarm beside it is not a result.

2. **Always run `baseline-always-fail` (and `baseline-never-fire`) as controls.** They bracket the
   scoreboard: any real detector must beat `always-fail` on precision (i.e. lift > 0) and beat
   `never-fire` on recall. A detector that does not clear the `always-fail` lift floor has no skill,
   whatever its recall.

3. **Default to the CONSERVATIVE rule; expose the aggressive one as a confidence knob.** Ship
   recovery-aware (0.2% false-alarm) as the default an operator acts on; offer `tight-no-recovery`
   (0.7%) as a higher-recall mode. This is the same shape as the intervention ladder's
   OBSERVE‹WARN‹BLOCK‹DEFER (`docs/144`): the safe default actuates, the aggressive setting is opt-in.

4. **A "deployable false-alarm ceiling" is a first-class design constraint.** The naive variants are
   not rejected for low precision in the abstract — they are rejected because **25.6% / 15.2%
   false-alarm makes them un-actionable.** Carry an explicit ceiling (DOS's shipped detectors sit at
   0.1–1.2%); a candidate above it is dead regardless of recall.

5. **You cannot buy recall by loosening the reading of bytes you already have — only by adding an
   independent witness.** Loosening grammar trades precision for false alarms (4a). Real recall gains
   come from a NEW byte-author: the env's terminal error (`terminal_error`, offline, shipped) or a
   fresh third-party world-read (`derived_witness` / live re-read, docs/158 §6). This is the
   byte-inequality axiom (`docs/141`) restated as a recall strategy.

6. **Compute headline numbers from one source of truth, over the LABELED set, and never guess an
   absent label.** `additivity.py` is that source for this benchmark; `--check` asserts the structural
   invariants. The labeled/unlabeled split (6,862 of 7,116 here) silently inflates a hand-rolled
   counter that treats an empty label as a fail — the methodology trap recorded at the top of this
   doc. A claim that cannot be regenerated by a committed `compute()` is not yet a claim.

## 6. Bottom line

The naive baselines did not beat DOS — they exposed that **recall is the wrong scoreboard on a
76.2%-fail benchmark**, where the worthless `always-fail` control posts 100% recall. Measured by lift
and false-alarm (the scoreboard a detector you *act on* must use), the shipped tight-grammar
recovery-aware `terminal_error` is the clear winner (+18.8pp lift, 0.2% false-alarm), and the naive
loose grammar is most of the way to the worthless control (+4.9pp lift, 25.6% false-alarm). The
experiment paid for itself three times: it refuted the "too good / naive is better" reading with
numbers, it proved the tight grammar is load-bearing (not caution), and it found one honest recall
knob (drop the recovery check) plus the false-reassurance phenomenon behind it. The lasting output is
the six defaults in §5 — the baseline every future DOS detector should start from.

# The recovery-knob and the false-reassurance failure — same-tool is not same-operation

> **docs/159 §4b found a recall knob in passing: dropping `terminal_error`'s "did a later same-tool
> call recover?" check nearly doubles recall at a still-tiny false-alarm cost, and named a
> phenomenon behind it — runs that hit an env error a later same-tool call *nominally* recovered,
> yet still failed final-state. This doc BUILDS that knob, MEASURES the phenomenon, and explains its
> mechanism. The finding is sharper than docs/159 predicted: the +70 net-new failures the knob
> recovers are ALL on GENERAL-PURPOSE EXECUTORS (`local-python-execute` ×68, `terminal-run_command`
> ×2) where the agent ran a script that errored, then ran a DIFFERENT script with the same tool that
> succeeded — so the recovery-aware detector went quiet, but the "recovery" was a different operation,
> not a fix. For a general-purpose executor the tool NAME does not identify the OPERATION, so "a later
> same-tool success" is not evidence the failed operation recovered. The knob this motivates is not
> the blunt binary docs/159 named — it is a SURGICAL one (`specific-only`) that ignores recovery for
> generic executors while keeping it for specific tools: +70 net-new catches at 92% precision, ~96%
> of the recall gain of dropping recovery entirely, at FEWER false alarms.**

**Status:** SHIPPED this session (2026-06-05). New code: the `recovery` confidence knob on
`benchmark/toolathlon/trajectory.py:terminal_error_fired` (and `to_terminal_error_evidence`),
threaded through `replay.py` (`run_row`/`replay`) and the CLI (`run_replay.py --te-recovery`). The
shipped default (`aware`) is **byte-identical** to the prior behavior — every existing test stays
green, and the durable `replay_all_rows.csv` / `additivity.py` SSOT are untouched (the new modes are
opt-in). 8 new tests on frozen fixtures (zero network/LLM), 48 in the replay suite.

**Lineage.** Direct build of [`docs/159`](159_naive-baselines-and-what-a-detector-default-should-be.md)
§4b (which *named* the knob + phenomenon) and [`docs/160`](160_sota-positioning-the-trained-classifier-and-the-arbiter-neighbors.md)
§4 item #2 (which *ranked* it). Tunes the `terminal_error` detector from
[`docs/158`](158_recall-expansion-silent-and-frontier-failures.md). The knob follows the
[`docs/144`](144_the-intervention-ladder.md) confidence-ladder shape (conservative default actuates,
aggressive opt-in) and the byte-clean / §5a doctrine from `docs/143` / `docs/141`. Every number here
is reproducible offline from the cached corpus with zero network — the `dos` replay-testable keystone.

---

## 1. The knob

`terminal_error` (docs/158) fires when the closing window of a run holds a structured env error that
**no later same-tool success recovered** — the recovery-check suppresses a transient error the agent
fixed. The `recovery` knob exposes that check as three settings (the docs/144 ladder shape):

| mode | rule | role |
|---|---|---|
| `aware` (**default**) | any later **same-tool** success counts as recovery | conservative; today's shipped behavior, the operator default an actuation rides on |
| `specific-only` | a later same-tool success counts as recovery ONLY for a **specific** tool; for a **generic executor** recovery never suppresses | **surgical** — the docs/162 finding |
| `none` | recovery is ignored entirely; any closing-window structured error fires | aggressive; the docs/159 §4b `tight-no-recovery` floor |

The fold is uniform across modes — `any(is_err and not recovered)` over the closing window. The knob
lives entirely in how the `recovered` flag is computed, so the three modes are nested by construction
(see §4, the safe direction).

## 2. The measurement (labeled corpus: 6,862 runs, 76.2% base fail rate)

Folding each mode over the full frozen corpus (`--te-recovery <mode>`, zero network):

| mode | TP | FP | precision | recall | false-alarm | **lift** |
|---|---:|---:|---:|---:|---:|---:|
| `aware` (default) | 76 | 4 | **95.0%** | 1.45% | **0.24%** | **+18.8pp** |
| `specific-only` | **146** | 10 | 93.6% | **2.79%** | 0.61% | +17.4pp |
| `none` | 147 | 11 | 93.0% | 2.81% | 0.67% | +16.9pp |

Read on the scoreboard a detector you *act on* must use (lift + false-alarm, never recall alone —
docs/159 §3):

- **`specific-only` nearly DOUBLES recall** (1.45% → 2.79%) at a still-tiny **0.61% false-alarm** —
  well under the deployable ceiling DOS's shipped detectors sit at (docs/159 §5.4). It confirms
  docs/159 §4b's "~doubles recall at a small false-alarm cost" prediction, measured.
- **`specific-only` captures ~96% of the recall gain of `none` (146 of 147 TP) at FEWER false alarms
  (10 vs 11) and higher precision (93.6% vs 93.0%).** Dropping recovery entirely buys one extra catch
  for one extra false alarm — a wash. The surgical knob is strictly the better trade: it targets the
  exact mechanism (§3) without giving up the genuine recoveries on specific tools.
- The aware→specific-only delta is **+70 TP / +6 FP — a 92% delta-precision.** The runs the default
  silences are real failures ~12 times out of 13. That is a genuinely actionable slice, not noise.

**At the TRIO (union) level — the headline that compounds.** Folding `specific-only` into the
dangling + tool_stream + terminal_error union lifts whole-corpus **trio recall 6.18% → 7.42%**
(+1.24pp, a +20% relative gain) at essentially unchanged precision (92.6% → 92.4%) and a still-low
1.96% false-alarm — and **140 of the 146 surgical catches are net-new** (missed by both other
detectors). This is a first-class, `--check`-reproducible SSOT claim: the durable rows
(`replay_all_rows.csv`) now carry BOTH a `terminal_error_fired` (aware) and a
`terminal_error_specific_fired` (specific-only) column, and `additivity.py compute(te_specific=True)`
folds the surgical trio — so the number is regenerable, never prose-only (the docs/159 §5.6 rule).
The conservative default rows + numbers are byte-identical (the aware column is unchanged), so every
prior figure stands.

## 3. The mechanism — why `specific-only`, not the blunt binary

The cases the surgical knob recovers are not random. The **+70 net-new catches** (runs that fire
under `specific-only` but not `aware`, on a FAILED run) break down by the tool that
errored-then-nominally-recovered in the closing window:

| generic-executor tool | net-new TP | (delta FP on passes) |
|---|---:|---:|
| `local-python-execute` | 68 | 5 |
| `terminal-run_command` | 2 | 1 |

**Every net-new catch is a general-purpose executor** (+70 TP / +6 FP, 92.1% delta-precision). The
pattern is identical across them: the agent writes a script, it throws a `Traceback` in STDERR, the
agent then runs a **different** script with the **same** `local-python-execute` tool that returns
clean STDOUT — so the recovery-aware detector sees "a later same-tool success" and goes quiet. But
the second script was a *different operation*; it did not fix the failed one, and the third-party
oracle scored the run failed on final state.

The root cause is precise: **for a general-purpose executor the tool NAME does not identify the
OPERATION.** Two `local-python-execute` calls are two different programs. "A later same-tool success"
is therefore not evidence the failed operation recovered — it is only evidence the agent ran
*something else* that did not error. Contrast a **specific** tool like `db-write` or `email-send`: a
later `db-write` success genuinely is evidence the failed write recovered, because the tool name
*is* the operation. So the recovery-check is sound for specific tools and unsound for generic
executors — which is exactly what `specific-only` encodes. Dropping recovery entirely (`none`) would
also throw away the sound specific-tool recoveries (the `test_recovery_specific_only_PRESERVES_*`
pin), buying nothing the surgical knob does not already get.

The generic-executor set is a small declared list (`local-python-execute`, `terminal-run_command`,
`bash`, `shell`, …) plus a shape rule (a name whose FINAL token is an exec/shell verb), anchored
tightly so a specific tool like `db-execute_query` (final token `query`) is not swept in. It is a
**floor**: a generic executor the set misses is treated as specific and only loses recall, never
breaks the safe direction (§4) — so the §2 recall numbers read as a lower bound. Of the 526 distinct
tool names in the corpus only 6 classify generic, and specific tools that merely *mention* an exec/run
verb (`k8s-exec_in_pod`, `notion-API-post-database-query`, `snowflake-write_query`) are correctly left
alone — the set is principled, not corpus-fit (10 of its 13 literal entries do not even appear here;
they generalize to other benchmarks' executor names).

## 4. Why this stays byte-clean, and the safe direction

**Byte-clean (the §5a line preserved).** The load-bearing argument here is DIRECTION, not
input-control — and it is worth being precise about which, because the knob *does* read an
agent-authored byte (the tool name). Three points, in order of weight:

1. **The error SIGNAL is always env-authored.** Under all three modes the fire is gated by
   `is_struct_error(tool.content)` — the MCP gateway wrote the `Traceback`, not the agent. The knob
   never starts *believing* an agent-authored byte; it only changes whether a *different* env-authored
   success is allowed to *suppress* that env-authored error.
2. **The knob reads the agent-chosen tool NAME — but only to add scrutiny.** `is_generic_executor`
   reads the tool name, which the agent authored (it chose which tool to call). So the agent *can*
   influence the classifier's input — but classifying a tool generic can only **remove a suppression**
   (fire more), never add one. The single suppression path (a later same-name success) is
   byte-identical to the already-shipped `aware` recovery-check, so `specific-only`/`none` add **zero
   new leverage in the dangerous (suppress) direction**. There is no forgeable "make my failure look
   recovered" move — naming a tool generic only invites *more* scrutiny.
3. **The classification SET is fixed harness config** — a benchmark fact the agent cannot change.

So the analogy to `tool_stream`'s volatile-field normalizer (docs/157 §4) is one of **kind** (fixed
harness config + a monotone-safe direction), **not exact**: the normalizer touches only env-authored
result bytes, whereas this reads an agent-chosen name — which is safe for the *directional* reason in
(2), not because the input is env-authored. The verdict is never a forgeable "is the agent
succeeding?" satisfaction predicate (the rejected hedge/confidence reader, docs/158 §5).

**The safe direction (monotone by construction).** `aware` ⊆ `specific-only` ⊆ `none`: each looser
mode suppresses *less*, so it can only fire *more* than the stricter one — it never silences a catch
the default makes. The only risk is added false alarms, which §2 measures (0.24% → 0.61% → 0.67%)
and caps under the deployable ceiling. This is the same asymmetry as the normalizer's: the dangerous
direction (manufacturing a fire the env did not justify) is structurally unreachable, because the
knob only ever *declines to suppress* an error the env actually emitted. Pinned by
`test_recovery_modes_are_monotone_aware_subset_specific_subset_none`.

## 5. What ships, and what it is for

- **Default unchanged.** `aware` is byte-identical to the shipped detector; the SSOT
  (`replay_all_rows.csv`, `additivity.py`) and every prior number stand. The new modes are opt-in,
  so docs/157/158/159/160's headline figures are untouched.
- **The operator surface** is `dos`-idiomatic: `run_replay.py --te-recovery {aware,specific-only,none}`,
  and the same knob on the `replay()` / `run_row()` / `terminal_error_fired()` API. An operator who
  wants higher recall on a corpus dominated by code-execution tasks flips one flag; the conservative
  default protects an operator who actuates on the verdict.
- **It sizes the Tier-B prize before spending** (docs/160 §4 item #1). The +70 net-new
  false-reassurance failures are precisely where a fresh THIRD_PARTY world-read (the live post-hoc
  re-read) would confirm fail-despite-nominal-recovery. This offline counterfactual bounds how much
  that (≈$170–1.8K) spend could add on this failure mode — the cheap measurement that gates the
  expensive one.

## 6. Bottom line

The recovery-check docs/159 flagged as a recall knob is, measured, a **false-reassurance** filter
that the dominant failure mode defeats: a general-purpose executor's "later same-tool success" is a
different operation, not a fix. The surgical `specific-only` knob — ignore recovery for generic
executors, keep it for specific tools — nearly doubles `terminal_error` recall (1.45% → 2.79%) at
0.61% false-alarm, captures ~96% of the gain of dropping recovery entirely at fewer false alarms,
and stays byte-clean and monotone-safe. The default does not move; the recall is one opt-in flag
away; and the +70 net-new failures are a ready-made, pre-sized target list for the live re-read.

# Doing good with a `terminal_error` catch — the byte-clean WARN gate (DETECT → FIX)

> **The detector line so far MEASURES: docs/158 ships `terminal_error`, docs/159 fixes the scoreboard,
> docs/162 tunes the recovery knob. All of it is DETECT on frozen trajectories — a catch produces a
> CSV bit and nothing happens. This doc asks the next question: can a catch DO GOOD — change an
> outcome — and can we prove it without the $1.8K live environment? The answer is yes, in two moves.
> (1) An OFFLINE counterfactual sizes the prize: 71 of 76 catches (93%) hit a wall that was
> demonstrably CLEARABLE — the agent walked away from an error a retry could have fixed. (2) The
> ACTUATION: a byte-clean, opt-in `terminal_error → WARN` gate that, at the agent's STOP event,
> re-surfaces the env's OWN error envelope + the failing tool and lets the loop run one more turn.
> Built + unit-tested this session with ZERO model spend. The live A/B that would produce the real
> task-delta number is the honest, bounded next step — and the 93% counterfactual is what makes it
> worth proposing.**

**Status:** the WARN gate is SHIPPED this session (2026-06-05) — `benchmark/enterpriseops/dos_react.py`
gains a pure `terminal_error_gate(tool_results)` decision + an opt-in `DOS_TERMINAL_ERROR` STOP-event
consult that mirrors the `DOS_DANGLING` gate exactly. 9 new pure unit tests
(`tests/test_dos_react_terminal_error.py`, no model / no gym / no Docker), the existing enterpriseops
+ dos_react suites stay green. The default is OFF — behavior is byte-identical when the flag is unset.
The live A/B is **not** run here (it spends + needs the live harness; see §4).

**Lineage.** Builds [`docs/158`](158_recall-expansion-silent-and-frontier-failures.md) (the detector),
[`docs/159`](159_naive-baselines-and-what-a-detector-default-should-be.md) (the lift scoreboard +
the §4b no-recovery knob this extends), and [`docs/162`](162_the-recovery-knob-and-the-false-reassurance-failure.md)
(the same-tool≠same-operation mechanism behind the counterfactual). The actuation rides the
[`docs/144`](144_the-intervention-ladder.md) WARN rung — the live-proven net-positive intervention
(WARN +4.2pp; BLOCK/DEFER can be net-harmful even on a true catch). Inherits the byte-clean / §5a line
from `docs/143` / `docs/141`. Pairs with [`docs/161`](161_toolathlon-live-gemini-run.md) (the live
harness this would A/B on).

---

## 1. The question — a catch that does nothing

`terminal_error` fires on 76 of 6,862 labeled runs at 95% precision (docs/158). On the frozen
trajectories that fire is a row in `replay_all_rows.csv` — a *label*, not an *action*. The detector
line's whole frame so far is DETECT-not-FIX (the trajectories are recordings; nothing can intervene).
The honest next question, asked by a reviewer: **can the catch do good — and can we prove it without
standing up the live environment ($170–1.8K, docs/157 HANDOFF)?**

Two moves answer it: an offline counterfactual that proves the catch points at a *fixable* wall (§2),
and a byte-clean actuation that turns the catch into a corrective nudge (§3). The live number is §4.

## 2. The counterfactual — 93% of catches hit a CLEARABLE wall

A `terminal_error` catch means the agent stopped while the env's last word was an unresolved
structured error. Is that error the kind a retry could have cleared, or a dead end? Measured offline
($0) over the raw trajectories (the per-message tool/error content the scalar CSV does not carry):

For each catch, its **failing tool** = the tool of the last unresolved structured error. A tool's
errors are **empirically recoverable** if, somewhere in the corpus, a structured error from that tool
was later followed by a success from the *same* tool in the same run. Result:

| failing tool | catches | that tool's errors recovered elsewhere |
|---|---:|---:|
| `local-python-execute` | 47 | 92% |
| `terminal-run_command` | 7 | 86% |
| `k8s-port_forward` | 4 | 75% |
| (browser / forms / k8s-delete / …) | 18 | mostly 0% |
| **total** | **76** | **71 of 76 (93%) on a recoverable tool** |

**71 of 76 catches (93%) hit a wall that was demonstrably clearable.** The dominant case is the
cleanest possible story: `local-python-execute` (47 of 76) — the agent ran code, got a **Traceback**,
declared success, and stopped, while 92% of the time runs that hit that tool's errors cleared them
with a retry. The agent had a fixable wall in front of it and walked away.

So a catch is not "this run failed" — it is **"this run failed at a clearable wall; here is the tool
and the error."** That is repair-grade information, and it is exactly what an intervention can act on.

**The honest caveat (it leads, it is not a footnote):** *recoverable-somewhere is an UPPER BOUND on
per-catch fixability.* It proves the wall is the **kind** that can be cleared by retry, not that *this*
agent would have. (docs/162 sharpens the mechanism: for a general-purpose executor the tool name does
not identify the operation, so "a later same-tool success" is a different operation, not proof the
failed one recovered. The 93% is "clearable class," not "93 fixes waiting.") The counterfactual sizes
the prize; only the live A/B (§4) measures the actual conversion.

## 3. The actuation — a byte-clean `terminal_error → WARN` gate

The gate lives at the agent's **STOP event** (the turn with no tool calls), beside the existing
`DOS_DANGLING` gate, and mirrors it exactly:

- **Opt-in:** `DOS_TERMINAL_ERROR` (default OFF — unset behavior is byte-identical to before).
- **One-shot:** a `_terminal_errored` guard — it re-surfaces at most once per run (never a livelock).
- **The decision is a pure function**, `terminal_error_gate(tool_results)`, unit-testable without the
  gym: it reads the last K=3 entries of the wrapper's `tool_results` list, fires iff a structured
  error sits there with no later same-tool recovery, and returns `(tool, excerpt, nudge)` — or `None`.
- **On fire:** append a `HumanMessage` re-surfacing the env's error + the failing tool, then run one
  more turn so the agent can fix/retry or confirm completion. DETECT-not-FIX, WARN-only.

**Why it stays byte-clean (the load-bearing property).** The nudge interpolates **only** the failing
tool name and the env error excerpt — both pulled from `tool_results` (the gym-authored result
payload). It **never reads `response.content`** (the agent's own narration). This is the §5a
byte-inequality line: the judged agent did not author the *identity* of the env's error envelope, so
the gate is provenance-of-an-env-authored-error, never a forgeable "am I succeeding?" predicate. A
pinned test proves it: a run whose last result is a `Traceback` from `local-python-execute` while the
agent says "All done!" fires the gate, and the nudge contains the Traceback bytes + the tool name and
does **not** contain "All done." The model cannot suppress the cue by claiming success — the
environment, not the agent, emitted it.

The error grammar is the byte-faithful copy of `trajectory.py`'s `is_struct_error` (the tight
structured-envelope match, docs/158), lifted inline with a canonical-source comment rather than a
cross-benchmark import (`dos_react.py` imports only `dos.*` + stdlib).

**Why WARN, not BLOCK/DEFER.** The live gym A/B already ruled (docs/144): WARN is the net-positive
rung (+4.2pp); the turn-spending skips (DEFER/BLOCK) can be net-harmful even on a *true* catch,
because the disruption breaks a different downstream step. A `terminal_error` catch is high-precision
(95%), but the safe actuation is still the least-disruptive-that-informs.

## 4. The live A/B — the real number, and its honest boundary

The gate makes a catch *actionable*; only a live A/B *measures* whether acting helps. The design
mirrors the dangling A/B (`benchmark/enterpriseops/analyze_dangling_ab.py`): two arms (control =
OBSERVE, treat = WARN-on-`terminal_error`), the same task set, the same model, measuring net
task-delta (treat pass-rate − control), with the docs/143 small-N accounting discipline (per-verifier-
pass over all-or-nothing, conversion-on-the-fired-subset, backfire guard). The live harness exists —
`live_adapter.py` bridges a live Toolathlon run into the same `Trajectory` the detectors score
(docs/161), and the `pure_local` task subset keeps the spend near $0 by avoiding paid cloud apps.

Two boundaries stated up front, not papered over:

1. **It spends + is outward-facing** — model API calls against the live env. This is a confirm-first
   step, not something to launch unilaterally.
2. **`terminal_error` fires on ~1.5% of runs.** On a small `pure_local` set it may catch ~0 tasks —
   an A/B with no catches proves nothing. This is precisely why the §2 counterfactual matters: it is
   the cheap pre-check that says the catch *is* worth wiring (93% of catches target a clearable wall),
   so the spend has a real target. Size the prize offline; spend only when it is sized.

The DOS-specific value the live number would add over Toolathlon's own pass/fail oracle is
**attribution**: the oracle says a run failed; the gate says *which wall, which tool* — and now offers
the agent a byte-clean chance to clear it.

## 5. Bottom line

A `terminal_error` catch can do good, and the good is provable in stages. Offline and free: 93% of
catches hit a clearable wall, so the catch carries repair-grade attribution, not just a failure bit.
Built and tested this session: a byte-clean, opt-in, one-shot WARN gate that re-surfaces the env's own
error and gives the agent one more turn — the actuation that turns DETECT into a FIX attempt without
ever reading the agent's own words. The remaining number — does the WARN actually convert a failure
into a pass — is a live A/B on the existing harness, bounded by a real (small) spend and the
detector's low fire-rate, and worth running precisely because the offline counterfactual already sized
its prize. That staging — *size the prize offline, spend only to measure conversion* — is the honest
DETECT→FIX discipline for a high-precision, low-recall advisory signal.

# 193 — Clean restart, seeded with DOS knowledge

> *"Even if it seems naive, think about this option — 'clean restart' but adding in
> the knowledge of DOS for the next fresh attempt. Test and benchmark it, and how
> it's different (or not) from other naive approaches."* — the operator, 2026-06-06

This is the plan + audit record for the **restart** arm: on a thrash, RE-ORCHESTRATE
a fresh context window instead of appending (block) or subtracting (rewind). It is the
one comparand the entire rewind line (docs/172/175/176) was built to need and never ran.

Method: a 4-agent adversarial workflow (`wf_63b15a54`) audited the idea from four angles
(conceptual / benchmark-design / vs-naive-prior-art / kernel-reuse), each finding's
high-confidence claims adversarially verified. The verifiers REFUTED two claims and
CONFIRMED the critical blocker — recorded below, defects and all.

## 1. The framing — what it is

On a THRASH (the same tool blocked a 2nd time = `convergence.THRASHING`), the move set
differs only in **what prefix the LLM re-reasons from**:

| move | keeps as prefix | authored bytes |
|---|---|---|
| none | everything | — |
| block / append | everything + a synthetic corrective | a kernel-authored result (REFUTED, −4/task) |
| rewind / subtract | `[System, Human, …good prefix…, note]` | byte-clean note only |
| **restart** | `[System, Human]` | — |
| **restart_seeded** | `[System, Human, note]` | byte-clean note only |

Restart is the only move that **drops the prefix entirely**.

## 2. Why it escapes the rewind livelock (mechanically sound — verified)

Rewind was REFUTED live (`none 49.2 / block 48.3 / rewind 44.9`, n=48) by a **livelock**:
the dominant natural thrash (`create_filter`, 9/12) is an **upstream omission** — the
agent invents an id because it never *looked it up*, and that missing read lives *before*
the rewind anchor, inside the good prefix rewind preserves. So rewind hands back the
poisoned prefix and the agent re-invents the same id.

**Restart is the only move in the set that drops that prefix**, so it is the only one
structurally capable of clearing an upstream omission (the logged prediction,
`restart_arm.py:25-29`). Three verifiers independently confirmed the mechanism is sound.
**Sound ≠ measured:** conversion is live-only (a restart's next move is a fresh LLM call
on the reset window; no recorded transcript contains those turns).

## 3. How it differs from naive approaches (the operator's Q3)

~95% commodity, with one real structural novelty:

| naive approach | same as seeded-restart? |
|---|---|
| plain LLM retry-from-scratch | **identical** to restart-unseeded (the wrapper calls it "the naive recovery") |
| ReAct re-prompting | different — that's the *append* (block) arm |
| max-iters-then-restart | same move, different *trigger* (timeout vs typed verdict) |
| **reflexion** (fail→self-critique→retry) | **same control flow, different lesson byte-author** |
| human "just start over" | restart-unseeded, human-triggered |

**Where the substrate earns its keep — two seams a naive harness lacks:**
1. **Seed provenance.** Reflexion lets the *same unreliable agent* author its own lesson
   (consistency, not grounding — [[project-dos-consistency-not-grounding]]). DOS's seed
   rides a closed kernel `VerdictToken` + env bytes.
2. **Trigger grounding.** Naive restart fires on a hand-tuned timeout; DOS fires on a
   typed ground-truth verdict (`THRASHING` / `STALLED`) — the same byte-identical signal
   the live PostToolUse hook computes.

The restart *move itself* is commodity. The kernel's contribution is the seam, not the verb.

## 4. The defect the audit caught — half-clean seed (now FIXED)

Two verifiers **refuted** the "byte-clean seed" claim:
- The **VerdictToken half** (`verify = NOT_SHIPPED @ <id>=never-appeared`) is un-forgeable. ✅
- The **EnvExcerpt half** — `"…Look the id up with a read/query tool, then retry."` — was
  **prose the wrapper authored in its own f-string**, then **self-tagged THIRD_PARTY**.
  The kernel docstring names this exact move forbidden (`rewind.py:243-247`): *a generated
  critique tagged THIRD_PARTY is a LIE about its byte-author the boundary reader must not
  mint.* And `"Look the id up…"` is *advice* (the corrective action) — F3 territory, not
  the F1.5 constraint the contract allows.

This defect is **inherited from the shipped rewind mint-path** (`dos_react.py` `_maybe_rewind`),
not unique to restart. **Fixed for restart** (`3f95b02`): `_restart_env_excerpt` reads the
gym's REAL recorded block-error bytes; absent one, a STRUCTURAL fact that names the WALL
(id never appeared) but never the corrective action. Pinned by
`test_seeded_note_carries_no_fabricated_directive`. **The rewind mint-path still carries
the directive — a flagged follow-up.**

## 5. The wiring blocker — dead code (now FIXED)

CONFIRMED by two agents: `_maybe_restart` lived on a bespoke `RestartOrchestrator` subclass
that never overrode `execute()`, so the inherited BLOCK branch called only `_maybe_rewind`
— **running `--arms restart` would have silently behaved as plain `block`** (the
green-unittest/red-live class the rewind anchor bug already burned this project on).

**Fixed** (`3f95b02`): folded restart into the base `DosReactOrchestrator` as an env-gated
arm (`DOS_RESTART` / `DOS_RESTART_SEED`), exactly like `DOS_REWIND`. The bespoke subclass
was the wrong shape — every other arm is the *same* class differentiated by an env flag.
Now structurally impossible to be dead code. `live_ab.py` got the two `_ARM_ENV` entries +
the pop-list guard.

## 6. The $0 gate — PROCEED (sized the slice before any spend)

`restart_counterfactual.py` (`145d6e5`) reuses the REAL live-arm logic over recorded
BLOCK-arm transcripts: recovers per-tool block counts from the kernel's own `dos_block`
events, applies the real restart trigger, classifies each fire SAME/VARYING.

**A real finding the gate caught:** the BLOCK-arm thrash is an arg-provenance INVENTED-ID
block (recorded as a `dos_block` event with `unsupported`), NOT a gym env error — so the
natural-regime env-error classifier saw nothing and reported a FALSE 0% slice → STOP. The
regime-aware fix classifies off the **blocked-id signature**: SAME = the agent re-invents
the *same* missing id every block (upstream omission, livelock-prone); VARYING = different
ids (exploratory). Byte-clean — reads only the kernel-authored `unsupported` field.

| dir | runs | fire rate | SAME slice | median prefix tokens re-paid |
|---|---|---|---|---|
| live_results/block | 78 | 7.7% | **71%** | ~187 |
| live_results_rewind_paired/block | 20 | 25.0% | **60%** | ~189 |
| live_results_rewind_ab/block | 22 | 27.3% | **67%** | ~121 |

**VERDICT = PROCEED:** the upstream-omission population is large (60–71% ≫ 15% floor) →
the restart>rewind prediction is testable. The cost half (median ~23–29 turns / ~120–190
prefix tokens re-paid per fire) now has numbers for the KC#5 cost veto.

## 7. The benchmark plan

**Arms (5, paired, same mint-seed):** `none / block / rewind / restart / restart_seeded`.
- `restart_seeded` vs `restart` → is the byte-clean seed load-bearing at all?
- `restart_seeded` vs `rewind` → **the logged prediction** (re-orchestrate beats subtract
  on upstream causes).
- `restart` vs `none` → does a cold re-orchestrate alone recover?

**Scoreboard** (recall is the *wrong* metric on a 76%-fail bench): primary = **per-task
flip net on fired runs**, split by the SAME/VARYING slice; secondary = **lift vs none**;
plus **false-alarm** + a **lift-per-1k-tokens** cost table (live `usage_metadata`).

**Pre-registered KILL CRITERIA (so it's refutable):**
- **KC#1** restart_seeded doesn't beat rewind by ≥+2pp on the SAME slice → prediction refuted.
- **KC#2** fired-run flip net ≤ 0 → net-harmful where it fires.
- **KC#3** restart_seeded doesn't beat restart by ≥+2pp → the seed carries zero marginal value.
- **KC#5 (cost veto)** restart wins raw but worse lift-per-token than rewind → "prune beats
  re-orchestrate" survives on cost; restart not recommended.

## 8. The honest risk

**Weak-model-only by the frontier-lift law** ([[project-dos-frontier-lift-axis]]): the
trigger fires ~never on a strong model (natural mint rate ~0/406). Two likely outcomes are
KC#5 (cost veto — re-paying the whole prefix loses on lift-per-token) and KC#1 (prediction
refuted if `create_filter` is a missing-prerequisite-knowledge gap a one-line note can't
teach). And: the note's information content is low ("this id never appeared, look it up") —
clean provenance, but a capable model already knows it.

## 9. Verdict + state

**Not naive — it's the missing comparand and the structurally-unique escape from the
documented rewind livelock.** But it is unmeasured, weak-model-scoped, and its durable
value (if any) is loop-hygiene + cost + the anti-reflexion seed provenance — not a frontier
capability lift. Present as a *structurally-distinct-but-unmeasured arm*, not a result.

**Shipped:** the $0 gate (`145d6e5`) + the live wiring + provenance fix (`3f95b02`),
39 benchmark tests green. **Running:** the live Gemini smoke (does restart fire end-to-end
+ produce a valid re-orchestrated window). **Future:** the powered 5-arm A/B in both the
mint and `mint-rate 0` natural regimes, scored against the 5 KCs.

Links: [[project-dos-live-trajectory-verification]] (docs/176 parent),
[[project-dos-rewindable-fix-loop-experiment]] (the rewind refutation restart escapes),
[[project-dos-fix-loop-and-rewind-verdict]] (the F0–F3 ladder, the ONE RULE),
[[project-dos-rewind-natural-thrash-pivot]] (the upstream-omission cause),
[[project-dos-frontier-lift-axis]] (the weak-model-only bound).

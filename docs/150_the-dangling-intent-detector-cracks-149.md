# 150 — The dangling-intent detector: DOS CAN detect a slice of premature completion

> **Status:** SHIPPED (the pure leaf + tests + the real-data replay) + measured, 2026-06-04.
> The deliberate steelman of docs/149 — *argue the opposite* — and it landed a real, buildable,
> measured result, not just a rhetorical win.
>
> **One line.** docs/149 concluded "DOS structurally cannot own premature completion (the measured
> ~92 % failure head) because the `completion` verdict's inputs are both forgeable here." That is
> **cracked, not overturned.** The crack: docs/149 over-generalized "the agent's narration is
> forgeable" from the *"I'm done"* direction (forgeable-in-favor, correctly distrusted) to *both*
> directions. But *"Now I need to allocate the personnel…"* right before stopping is an **admission
> against interest** — the one self-report class DOS *already believes* (`resume` keeps a
> `STEP_CLAIMED`-but-unverified step IN the residual). A verdict over it, corroborated by the
> **env-authored absence of any subsequent tool result**, is byte-clean, planner-free, WARN-only,
> and non-backfiring. **Measured on the recorded `gemini-3-flash` corpus: 13 % recall over the
> failures, 0 % false-fire on passed runs.** A smaller-but-real DOS-shaped target where docs/149
> declared none.

---

## 0. How this was reached (the method, because it matters)

This is the product of **arguing the opposite of a committed conclusion** — a 9-agent steelman
workflow (4 independent angles → adversarial refutation of each → a ruling synthesis), every angle
trying to find a byte-clean way DOS *could* help with the 92 % premature-completion head, grounded
in the real recorded data. The discipline that made it honest: a crude first probe
(`obligation_probe.py`, the env-imperative→tool-verb table) showed 71 % recall and **looked** like
a win — but the adversarial pass **killed it as a planner**, with the exact grounding example as
the proof of death (see §2). What survived four rounds was the *one* mechanism that needs no
verb→tool table at all. The simulator-overclaim lesson (docs/145 → the +17.3 pp that collapsed to a
measured ~0) is held here: the headline number is **measured on real recorded data**, not assumed.

---

## 1. The crack in docs/149, stated precisely

docs/149 §3: *"`completion.classify` needs `declared − verified`; on this benchmark there is no git
ancestry and no env-authored per-step checkpoint, so `verified` collapses to the agent's narration
→ agent-authored → forgeable → a §5a mirror-verifier."*

True — **but only in the direction of completeness.** A self-report of *"I'm done"* is forgeable in
the agent's favor, and the kernel correctly refuses it (`STEP_CLAIMED ≠ STEP_VERIFIED`). A
self-report of *incompleteness* — *"I still need to X"* — is an **admission against interest**: no
premature-completing agent benefits from falsely confessing unfinished work right before it stops.
DOS already encodes exactly this asymmetry: `resume.py` keeps a `STEP_CLAIMED`-but-unverified step
**in** the residual — it believes the agent's self-report *only* when the agent admits *more* work,
never when it claims *less*. So the against-interest axis is **not** forgeable-in-favor, and a
verdict over it is **not** the mirror-verifier docs/149 assumed was unavoidable. The counterexample
was sitting in the grounded trajectory all along.

---

## 2. Why the obvious version (a verb→tool table) is a planner — and dies

The tempting mechanism: the env prompt says *"allocate the appropriate internal personnel"*; map
the imperative verb *allocate* → the write-tool `add_group_member`; flag if no such call fired. My
`obligation_probe.py` did exactly this and measured **71 % recall**. The adversarial pass killed it,
and **the grounding example is the proof of death**: to flag "allocate personnel" you must encode
that, *in this task*, "allocate" discharges to the *membership* verb (`add_group_member`) and **not**
the co-plausible group-creation verb (`add_new_user_group`) — which **did** fire. Resolving that
ambiguity requires reading *this task's* prose, which is the `precursor_gate` dead-line ("inferring
the map from policy text IS parsing policy = planner-adjacent"). The example that proves the signal
exists is the same example that proves the table is task-derived. **The 71 % was a planner's recall,
not a byte-clean detector's** — and its 38 % false-fire (it also fired on a third of *passed* runs,
detecting task *complexity* not *prematurity*) confirmed it. Killed, not hedged.

---

## 3. The survivor — `dangling_intent.classify_stop` (the build, shipped)

A new **pure kernel leaf** `src/dos/dangling_intent.py`, the `claim_extract` / `liveness.classify`
shape:

```
classify_stop(StopEvidence, policy) -> DanglingVerdict   # DANGLING_INTENT | ABSTAIN
```

**The byte-clean question** (over two surfaces, one with an env-authored corroborator):

> Does the agent's **last authored turn** contain a fixed, task-INDEPENDENT committed-future-intent
> discourse marker ("I need to", "I still have to", "next I will", "I was unable to", "cannot … yet")
> — AND did **no env-authored tool result** land after it?

- **Not a planner.** The cue set is an English-discourse-marker grammar writable having read *zero
  task prompts* — the verdict is **invariant under task-swap** (pinned by a test: a VPC-deploy turn
  with the same envelope fires identically). It never reads a domain noun, never enumerates a
  step-list, never decides what to do next. It does not even need to know what the unfinished step
  *is* — only that a standing-obligation envelope was emitted at the moment of stopping. The
  knife-edge, enforced: **key on the first-person-future envelope, never on content** — the instant
  it keys on "members"/"allocate" it is a planner and dead.
- **Not a mirror-verifier.** It reads no DB, asks no "is the work enough" rubric. The one
  agent-authored surface (the narration) is read on the **against-interest axis** (§1) and
  corroborated by an **env-authored absence**: the gym writes a tool `result` only when a tool
  actually executed, so "no result after the terminal turn" is a non-forgeable byte (the
  `precursor_gate` existence-of-a-result rung). That corroborator is checked **first** (a marker
  followed by a real call → ABSTAIN), killing the named-it-then-did-it false positive by
  construction.
- **Non-backfiring (WARN-only by type).** The verdict maps to `Intervention.WARN` and the type has
  no harder rung. On a fire the consumer re-surfaces **the agent's own abandoned sentence** — it
  authors **no directive and no step**, so the −9 pp derailment channel (a verifier-authored
  directive on a correct path, docs/143) is **unreachable**. Worst case is replaying a sentence the
  agent already wrote — a one-turn iteration tax, not a derailment. On a correctly-finished task no
  marker fires; on a correctly-refused infeasible task the narration is "I cannot…" not "I need
  to…[stop]" — different grammar, no fire.

**The honest forgeable hole, named** (the `arg_provenance` discipline): this reads one
agent-authored surface, so it is **forgeable by SUPPRESSION** — an agent trained against the gate
stops narrating "I need to…" and the signal goes quiet. Acceptable ONLY because suppression
degrades to **false-DONE → baseline** (the safe direction) and because the value is on *today's*
uncoached models that narrate their abandoned plans. It catches the **honest-but-premature**
stopper; it is blind to the **silent** stopper (the majority of the 92 %) and the **adversarial**
one. Stated plainly, not buried.

**Where it sits vs `completion.py` (docs/117): it REPLACES the forgeable axis, does not patch it.**
`completion` rests on `declared − verified` where `verified` is the non-forgeable *ancestry* rung
(`STEP_VERIFIED`, git SHAs) — absent on this benchmark, which is *why* `completion` is genuinely a
mirror-verifier here (docs/149 is right about that). `dangling_intent` never computes `declared` or
`verified` at all; it is `liveness` re-aimed — a forward temporal verdict over (terminal-narration
⋈ post-turn-execution-delta) rather than (git/journal delta). `completion`'s sibling, not its patch.

---

## 4. Measured on real recorded data (the proof, not a sim)

`benchmark/enterpriseops/replay_dangling.py` folds the **shipped** `classify_stop` over the recorded
`gemini-3-flash` trajectories and joins to the gym's own `verification_results` — pure replay, zero
model calls (the `failure_distribution.py` / `replay_stall.py` sibling):

| Metric | Measured |
|---|---|
| **against-interest recall** (of FAILED runs, fraction flagged) | **13 %** (9 / 68) |
| **false-fire on passed runs** (must be ~0) | **0 %** (0 / 8) |

The flagged cues are the agent's **own words** ("I need to", "I was unable to") — provably not a
planner. The 13 % is the **narrating-stopper** subset (the synthesis predicted 15–30 %; the shipped
detector is slightly more conservative than the crude probe because the resolved-guard + the
env-corroborator trade a little recall for honesty — the right trade). The **0 % false-fire** is the
decisive number: the against-interest asymmetry holds on real data — a passed run does not end on
"I still need to…".

---

## 5. The honest ceiling — DETECT, not FIX

**DOS CAN byte-cleanly DETECT a slice of premature completion. DOS still CANNOT FIX it.** Those are
different claims and the win is exactly the first.

The advisory nudge re-surfaces the agent's own abandoned sentence ("your final message says you
still needed to X, and no tool ran after — continue or confirm"). It supplies **no plan** — it
cannot tell the model *what* call to make, with *which* entities (the +14–35 pp planner lever,
forfeit by doctrine). So the realistic value is bounded: it converts a *self-admitted* premature
stop into *one more turn* by re-surfacing the model's own contradiction. Whether that turn produces
the missing write depends on whether the model, re-prompted with its own words, can finish the step
it had already articulated — plausible for the narrating stopper (it knew the next step; it just
stopped), out of reach for one that didn't. This is the same indirect value `arg_provenance` /
`precursor_gate` ship: a presence-miss flips *if the model heeds the reminder*, never by DOS doing
the work.

**The ruling:** docs/149's strong claim — *"DOS structurally cannot own premature completion here"*
— is **refuted as stated** (it over-generalized from "forgeable toward done" to "forgeable in both
directions"). docs/149's **empirical core survives**: the measured 92 % is dominated by the
**silent** stopper (stops at ~5 calls, no narration, no self-report to distrust), and there DOS
still has nothing byte-clean to read, because the env records what an agent *did*, never what it
was *required* to do. So DOS owns a **~13 % high-precision advisory slice**, not the head — a crack,
not an overturn. The smaller-but-real target is the honest outcome of arguing the opposite.

---

## 6. The residual + what would extend it

- **The silent stopper (the majority)** stays out of reach without an env-authored required-step
  signal the benchmark does not expose to a fair agent. The `arity_underfill` idea (a write call
  fired with an env-schema-`required` arg left empty) is doctrinally the cleanest extension — it
  reads only the env-authored tool schema, zero prose — but it is structurally blind to the
  *never-called-tool* shape the missing-row head is made of (there is no call to inspect). Low
  single-digit additional coverage; correct insurance, not a head-shot. Noted, not built.
- **Consumer wiring** (`dos_react` consulting `classify_stop` at the agent's stop event, attaching
  the re-surface WARN) + an `intervention-eval`-style net-delta measurement of whether the nudge
  actually makes the narrating stopper finish — the live experiment, deferred (it is the L4
  contended step; the detection is already proven by replay).

**Cross-refs:** the claim this cracks = docs/149; the measured failure head = `failure_distribution.py`;
the against-interest residual rule = `src/dos/resume.py` (`STEP_CLAIMED` stays in residual); the
terminal-narration boundary reader + abstain-never-invent floor = `src/dos/claim_extract.py`; the
byte-clean presence + the existence-of-a-result rung = `src/dos/precursor_gate.py` (docs/147); the
WARN-only ladder = `src/dos/intervention.py` (docs/144); the sibling it re-aims = `src/dos/liveness.py`;
the killed planner version = `benchmark/enterpriseops/obligation_probe.py`; the real-data proof =
`benchmark/enterpriseops/replay_dangling.py`; the simulator-overclaim lesson held = docs/145.

# docs/252 — The context reset as an out-of-loop handoff, and the loop-vs-trajectory split

> **One sentence.** A context-window reset — compaction, `/clear`, a summary-then-continue,
> a fresh session picking up the same task — is structurally a **peer-B handoff
> (docs/229/235) where peer B is the *same model in a fresh window***: the post-reset
> reader inherits the pre-reset agent's *claims* but authored *none of the bytes* that
> produced them, so it is the cheapest, most common, and most overlooked occupant of the
> out-of-loop half-plane (docs/209) — and saying this precisely forces a second
> correction, that **"in-loop" is a property of the live control structure (the loop),
> not of the recorded byte-stream (the trajectory)**, which the repo already uses as two
> different words without having said so.

**Status:** theory note. **Date:** 2026-06-08. Carries no new litmus and ships no
mechanism — it re-files an existing structure (context reset) into the existing taxonomy
(in/out-of-loop, docs/209) and sharpens two words the corpus already uses divergently.
In the family of [[docs/209]] (the in/out-of-loop split + the only positive half-plane),
[[docs/229]]/[[docs/235]] (the peer-B handoff, executed; ΔB measured), [docs/231](https://github.com/anthony-chaudhary/dos-strategy/blob/master/231_maintaining-not-improving-the-decay-prevention-charter.md)
(decay-prevention is the charter — a reset is a horizon event; now in `dos-strategy`), [[docs/176]] (the
"re-orchestrate a fresh context window" comparand + `restart_arm.py`), [[docs/236]]
(recovery is a confound — the lurking variable that returns here), and [[docs/243]]
(the fleet-trajectory benchmark — where "trajectory" means the recorded artifact).

---

## 1. The question, and why it is not idle

The operator asked to *explore resetting the context window as an out-of-loop concept*.
It is the right instinct and it lands on a real gap: the in/out-of-loop map in docs/209
enumerates the out-of-loop consumers as *"a dependent task, a reviewer, a merge gate, a
training label, a peer, the shared store"* — and **a context reset is none of those by
name, yet it is the same structure as all of them.** It is worth a doc because it is the
out-of-loop consumer a fleet hits **most often** (every long task crosses at least one
compaction) and **names least** (nobody calls `/clear` "a handoff").

---

## 2. The reduction: a reset *is* the peer-B handoff, with B = the same model, fresh window

docs/229/235 built and measured the peer-B handoff. Recall its exact shape:

```
  Agent A runs, emits a CLAIM ("I cancelled the reservation / the write landed").
                 │
                 ▼
  A's context ends.  Peer B starts from one of two inherited states:
     believe arm     → B's prior context = A's RAW CLAIM        (trust the narration)
     adjudicate arm  → B's prior context = the VERIFIED state   (trust the witness)
                 │
                 ▼
  B does the dependent work.   ΔB = B's task-success(adjudicate) − B's task-success(believe).
```

The load-bearing property is one line of docs/235: **B authored none of the bytes A
produced.** That is what makes B's inheritance an *out-of-loop* consumption — the verdict
changes an outcome for *someone other than the agent that emitted the claim* (docs/209
Module 2, gate (a): CONSUMER ≠ PRODUCER).

Now hold that picture and substitute a context reset for the handoff:

| Peer-B handoff (docs/229/235) | Context-window reset |
|---|---|
| Agent A | the pre-reset turns |
| A's claim | whatever survives into the **summary / compaction / carried-over notes** |
| Peer B | **the same model, reading a fresh window** |
| B's prior context | the summary (believe) **or** a re-verified state (adjudicate) |
| "B authored none of A's bytes" | **the post-reset reader authored none of the pre-reset bytes** — they are gone; only the summary remains |
| ΔB | does the post-reset agent finish the task correctly more often when the carried-over state is *witnessed* vs *narrated*? |

The substitution is exact. **A context reset manufactures a CONSUMER ≠ PRODUCER boundary
inside a single agent's own run** — the pre-reset self is the producer, the post-reset
self is a structurally-distinct consumer, because the bytes that would let it check the
claim no longer exist in its context. The reset is not a *kind* of out-of-loop consumer
sitting beside "peer / reviewer / merge gate"; it is the **mechanism that turns one agent
into two**, the cheapest way the producer≠consumer split arises in the wild.

### 2.1 Why this is the *most forgeable* handoff, not the least

A reset looks benign — "it's the same model, it knows what it did." That intuition is the
trap. The summary is **maximally forgeable** in the docs/138 sense (byte-author = judged
agent): the pre-reset agent (or its summarizer) *authored the very bytes the post-reset
agent will trust*. There is no witness in the loop. A peer-B handoff at least crosses a
process boundary where a gate *could* interpose the verified state; a naive context reset
crosses no boundary at all — the claim flows from self to self with nothing reading
ground truth in between. **It is the peer-B believe-arm with no adjudicate-arm even
available** unless something is deliberately wired to re-verify across the seam.

This is precisely the docs/229 peer-B *believe* arm — and docs/235's headline result is
the warning: at a single capable self-verifying hop, **the consumer re-verifies the
phantom and self-recovers (ΔB ≈ 0)**. So the naive expectation "the model will just
re-check after the reset" is the **recovery confound of docs/236** returning one level
down: *sometimes* the post-reset agent re-establishes ground truth on its own, which
makes the reset look harmless — but that is a property of the *recovery rate r*, a lurking
variable, not a property of the reset being safe. Where docs/236 localized the real payoff
(a structurally-weaker / non-LLM / **multi-hop** consumer, P(never-recover) high), the
reset analogue is: **the reset is dangerous exactly when the carried claim is one the
post-reset agent will NOT independently re-derive** — a fact it would have to redo
expensive work to recheck, so it takes the summary on faith. That is the feasible-tail
(docs/236 H1) of context resets.

---

## 3. Where the reset sits in the existing map (docs/209 Module 0, extended)

```
                          THE VERDICT / THE STATE crossing a seam
                                          │
        ┌─────────────────────────────────┴─────────────────────────────────┐
        ▼                                                                    ▼
   IN-LOOP consumer                                              OUT-OF-LOOP consumer
   (SAME agent, SAME window, next turn)                  (a reader that did NOT author the bytes)
   WASH-TO-NEGATIVE by structure (docs/188)                ┌──────────┬──────────┬──────────┐
                                                           ▼          ▼          ▼          ▼
                                                      dependent    reviewer /   training   ░░CONTEXT░░
                                                       task /       merge gate   label      ░░RESET ░░
                                                       peer B                               (self→self
                                                      (docs/229)                            across a
                                                                                            window seam)
```

The reset is drawn as a *first-class out-of-loop consumer* because it satisfies the
docs/209 Module-2 gates:

- **(a) CONSUMER ≠ PRODUCER** — ✅ the post-reset reader is not the pre-reset author of
  the carried bytes (§2). This is the whole point.
- **(b) CHECKABLE CLAIM** — ✅ *if and only if* the carried-over state names something a
  witness can read back (a file that shipped, a DB-hash, a lane that was held). A summary
  that carries only *prose intent* ("I was working on the auth refactor") carries no
  checkable claim — that is the docs/243 / `dos plan --once` empty case (a sound witness
  aimed at a distribution with no parseable claim → J = 0), one level up.
- **(c) LIVE / API** — to *show value* (a payoff, not a rate) you would run a live loop
  that resets mid-task and measures task success with vs without a re-verification at the
  seam. A frozen replay of summaries is a rate (docs/179/209 Module 1), never a payoff.

**The mechanism DOS already has for this seam is `resume` (docs/107).** A context reset
is the *intra-run* special case of the ARIES-third-phase question `resume` answers across
a *dead* run: *"a run paused mid-flight; how far did the FOSSILS say it got, and what is
the residual?"* — answered off the non-forgeable rung (git ancestry + the intent ledger),
never the agent's self-report. The right out-of-loop treatment of a context reset is
**not** "trust the summary"; it is **`resume`'s discipline applied at the compaction
boundary**: re-derive how far the work actually got from the witness the pre-reset agent
did not author, and hand the post-reset agent the *verified* residual (adjudicate) rather
than the *narrated* one (believe). The summary becomes a hint to be checked, not a claim
to be believed — which is the entire DOS thesis, aimed inward at the agent's own memory
seam (cf. docs/103: "memory is an unverified agent").

---

## 4. The wording: "in-loop" is NOT "in-trajectory" (loop ≠ trajectory)

The operator's second prompt — *keep thinking about wording like is in-loop same as
in-trajectory* — is not a side question. It is the **precision the §2 reduction depends
on**, because a context reset is exactly the case that *splits* the two words: a reset
**breaks the trajectory** (the byte-stream restarts) while **the loop may continue** (the
task goes on). If the two words were synonyms, a reset could not be "still in the loop but
in a new trajectory" — which is precisely what it is.

The corpus already uses them as two different things; it just never said so. Pinned to the
tree (2026-06-08):

| Word | What it denotes in this repo | Evidence on disk |
|---|---|---|
| **trajectory** | the **recorded artifact** — the `.jsonl` byte-stream, one record per turn/event; a *noun*, a *log*, a thing you parse after the fact | `benchmark/fleet_trajectory/corpus.py:1` — *"parse the CC **trajectory** `.jsonl` files into structured Session"*; docs/243 §1 — *"one record per turn/event"*; the `trajectory-audit` skill sweeps these post-hoc |
| **loop** | the **live control structure** — the running dispatch/agent cycle that is *currently deciding and acting*; a *verb-ish* thing, a process, something you are *inside of* now | docs/209 Module 0 — *"hand it back to the SAME agent's **next turn**"* (a live act); docs/194 title — *"uncurable **in-loop**"* (about the running cycle, not the log); docs/188 — the harm is *"the extra turn's EXISTENCE **in a loop** that was already passing"* |

So the precise definitions, which I propose the repo adopt explicitly:

- **In-loop** ≡ the verdict/state is consumed by the **same live control cycle that
  produced it**, by the **same agent, in the same context window, on a subsequent turn**.
  The defining test is docs/209's: does consuming it inject *an extra turn into a loop
  that was already running*? If yes, it is in-loop, and it is wash-to-negative by
  structure (docs/188), because the cost is the turn's existence.

- **In-trajectory** ≡ the verdict/state appears in **the same recorded byte-stream** (the
  same `.jsonl`). This is a statement about *where the bytes are logged*, **not** about
  *who consumes them or when*. Two turns are in the same trajectory iff they are the same
  session log — full stop.

These come apart in both directions, which is the proof they are not synonyms:

| | same trajectory | different trajectory |
|---|---|---|
| **in-loop** | the normal case: turn N+1 reads turn N, same session, same live cycle | **rare/degenerate** — a loop spanning two log files (e.g. a crash-and-relaunch that the host stitches into one logical run); the bytes are in two trajectories but it is arguably one loop |
| **out-of-loop** | **the context reset (§2)** — pre- and post-reset are in *one* `.jsonl` (one trajectory) but the post-reset reader is a structurally-distinct consumer (out of the producing loop). ALSO: a sub-agent / sidechain whose work is logged inline (`isSidechain`, docs/243) | the canonical case: peer B's own session, a reviewer, a merge gate, a training run — a *different* log entirely |

The load-bearing cell is **out-of-loop ∩ same-trajectory = the context reset**. That cell
is *empty* if you treat the two words as synonyms — which is exactly why the synonym
confusion hides the reset as an out-of-loop consumer. **Naming the split is what makes the
§2 reduction visible.**

### 4.1 The one-line rule for prose going forward

> Say **in-loop** when the claim is about *who consumes the verdict and whether it costs a
> live turn* (the docs/188/209 economic axis — the thing that is wash-to-negative). Say
> **in-trajectory** / **same trajectory** only when the claim is literally about *which
> recorded `.jsonl` the bytes live in* (the docs/243 corpus axis — the thing you parse).
> They are orthogonal; the context reset is the cell that proves it (out-of-loop yet
> in-trajectory). Never write "in-trajectory" to mean "in-loop" — the reset is the
> counterexample that makes that substitution false.

This also retro-justifies the existing titles: docs/176 *"live **trajectory** verification
— walk, re-walk, prune"* is correctly about the *artifact path* being re-walked, and it
already contrasts that with *"**re-orchestrating** a fresh context window"* (line 8) — i.e.
docs/176 was already drawing the loop-vs-trajectory line (re-walk the trajectory vs
restart the loop in a fresh window), and even built the comparand (`restart_arm.py`). This
doc just names the distinction docs/176 used implicitly.

---

## 5. What (if anything) to build — and the honest "not yet"

Consistent with the docs/209 discipline, the reset-as-out-of-loop frame is a **half-plane
placement, not yet a payoff**. The honest status of each move:

1. **The frame is sound and free** — a context reset IS an out-of-loop consumer; this
   costs nothing to assert and it correctly re-files the concept. ✅ (this doc.)

2. **The mechanism already exists** — `resume` (docs/107) is the verified-residual-across-a-seam
   syscall; applying its discipline at the compaction boundary is a *wiring* question, not
   a new kernel primitive. The seam to occupy is the host's summarizer/compaction step
   (the docs/191 "occupy the host's seams" lens): at compaction, emit a `resume`-style
   verified residual alongside the prose summary, so the post-reset agent inherits
   `adjudicate`, not `believe`. **Not built.**

3. **The payoff is UNMEASURED, by the same wall as everything in docs/209** — to show
   value (not a rate) you must run a **live** loop that resets mid-task and measure task
   success with vs without seam re-verification, on a benchmark whose witness the agent did
   not author. The cheapest live testbed is the one we already have: the docs/235
   `peer_b_run.py` *is* a reset-handoff harness if you let B's inherited state be "A's
   summary" (believe) vs "the env-verified residual" (adjudicate) — which it already does.
   So **the reset payoff is a relabeling of the peer-B experiment, not a new build** — and
   docs/235 already measured ΔB ≈ 0 *at the single capable self-verifying hop*. The reset
   payoff therefore inherits docs/236's localization verbatim: **expect ≈ 0 when the
   post-reset agent self-recovers; expect positive ΔB only where the carried claim is one
   the post-reset agent will NOT cheaply re-derive** (the feasible-tail / multi-hop /
   weaker-consumer regime). Measuring *that* — a reset where re-verification is expensive
   enough that the agent takes the summary on faith — is the open experiment. **Not run.**

The contribution of this doc is the *placement and the vocabulary*, not a number:
the most common out-of-loop consumer in a real fleet is the one nobody was counting,
and the word that hid it was "trajectory" standing in for "loop."

---

## 6. Summary

- A **context-window reset is an out-of-loop handoff**: pre-reset = producer,
  post-reset = consumer, and the post-reset reader authored none of the bytes it
  inherits (§2). It is the peer-B handoff (docs/229/235) with B = the same model in a
  fresh window — the **believe arm with no adjudicate arm** unless one is wired in.
- It is the **most forgeable** seam (self authors the summary the self will trust) and
  its apparent safety is the **recovery confound** (docs/236) returning one level down:
  harmless only to the degree the post-reset agent independently re-derives ground truth.
- The right treatment is **`resume`'s discipline at the compaction boundary** (docs/107):
  hand the post-reset agent the *witnessed residual*, not the *narrated summary* — DOS's
  thesis aimed inward at the agent's own memory seam (docs/103).
- **"In-loop" ≠ "in-trajectory."** *Loop* = the live control cycle (who consumes,
  costs a turn — the docs/188/209 axis). *Trajectory* = the recorded `.jsonl` artifact
  (which log the bytes are in — the docs/243 axis). They are orthogonal, and the
  **context reset is the cell that proves it**: out-of-loop yet in-trajectory (§4). Use
  the words by §4.1's rule; never let "in-trajectory" stand in for "in-loop."
- Status: **frame sound, mechanism exists (`resume`), payoff unmeasured** — and the live
  testbed is a *relabel* of docs/235's `peer_b_run.py`, expected ≈ 0 at the easy hop and
  positive only in the no-cheap-recovery tail (§5).

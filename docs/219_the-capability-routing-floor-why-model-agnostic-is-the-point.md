# 219 — The capability-routing floor: why "model-agnostic" is the point, not a footnote

> **Status:** DESIGN / positioning (2026-06-07). No kernel change — this doc names
> a property the kernel *already has* (zero model surface; verdicts read git, the
> file tree, and the clock, never the worker's tier) and argues it is the load-bearing
> enabler of a thing the field is racing toward: **capability routing** — deliberately
> sending each task to the *cheapest model that can do it*. The thesis: DOS does not
> make a weak model strong (that is [153](153_can-dos-lift-a-weak-model.md), and the
> answer there is mostly *no*). DOS makes the **bet that a cheaper model is "capable
> enough" safe to take**, because it removes the single failure mode — a confident
> wrong "done" you cannot see — that otherwise forces you to keep the expensive model
> everywhere. Grounded in a live, unexploited instance in the reference app: the
> dispatch loop runs the most expensive model on an orchestrator whose every hard
> decision is already a $0 kernel verdict.

---

## 0. The question, stated precisely

The operator's framing: *"it's becoming common for 'capable enough' models to be used
for certain tasks — think about that relative to DOS."*

This is **not** the [153](153_can-dos-lift-a-weak-model.md) question. 153 asks "can DOS
lift a weak model *toward* a strong one?" — can the kernel's nudges make a 24%-on-the-bench
model *complete more tasks*. The honest answer there is bounded and mostly negative: DOS
forfeits ~90% of a weak model's failures (planning + *silent* stops) by doctrine and
recovers only the execution-substrate slice, WARN-only, "with a credible floor of zero"
([153 §1](153_can-dos-lift-a-weak-model.md)). 153 is DOS-as-**corrective-feedback** to one
struggling agent, and it concludes the lift is small.

The capability-routing question is the *opposite valence*. It does not ask the kernel to
improve the model. It asks: **in a world where you already route tasks to the cheapest
sufficient model, what does DOS contribute to making that routing decision safe?** The
answer is large and positive, and it is the natural reading of the one sentence
[128](128_the-ultracode-economics-and-how-the-kernel-saves-spend.md) ends on — that the
same kernel can referee *"a Claude fleet, a Gemini fleet, or a mixed one, without ever
being a contestant in the race it adjudicates"* — promoted from an economics footnote to a
design claim with its own proof.

The distinction matters because the two questions have opposite answers, and conflating
them buries the positive result under 153's honest negative one.

---

## 1. Why capability routing is risky *without* a verdict floor

"Capable enough" is a bet. You bet a $1/MTok model can fill this form, classify this row,
render this packet — that the task does not need the $25/MTok model's reasoning. Most of
the time you win. The bet's expected value is dominated not by the average case but by the
**cost of being wrong in the way you cannot see**.

A weaker model fails *more*, and — this is the load-bearing fact — its most common failure
is the cheapest, most invisible one: the **cheap lie**. From
[108](108_the-cheap-lie-and-the-narration-taxonomy.md): `"all work completed"` — *"a
one-line, high-confidence claim of done, emitted by a worker that committed little or
nothing… It is **common** (the default shape of a worker that overran its context, lost the
thread, or simply guessed it was finished). It is **cheap**… And it is **eye-undetectable**
— there is nothing to look at."* [153 §4](153_can-dos-lift-a-weak-model.md) measures this
directly on a real weak-model corpus: the dominant failure is the *silent stopper* — "median
5 calls vs ~9 needed, no narration, no loop, no mint — structurally invisible."

So the structure of the risk is: **a cheaper model fails more often in exactly the mode a
narration-reading supervisor cannot detect.** If your supervisor is *also* a model reading
the worker's self-report — a stronger model summarizing, a dashboard showing a status string,
a human skimming "✓ done" — then downgrading the worker degrades your detection at the same
time it degrades the work. That coupling is what makes naïve capability routing dangerous,
and it is why, absent something better, the safe-but-expensive default is *use the strong
model everywhere and trust its narration more.*

The whole point of DOS is that it breaks the coupling. The detector is not a model reading a
report. It is git.

---

## 2. The kernel is model-blind by construction — and that is the enabling property

DOS's verdicts consume **zero model tokens** and never observe which model produced the work
they judge. This is not an aspiration; it is checkable in the source — and was checked
mechanically (2026-06-07), two ways:

> **Proof A (introspection).** Enumerate the parameters of all six headline verdict functions
> (`oracle.is_shipped`, `oracle.batch_is_shipped`, `loop_decide.decide`, `liveness.classify`,
> `pickable.classify`, `reconcile.reconcile`). Every parameter is a plan id, a phase id, a
> structural state dict, an evidence dataclass, or a git-reading callback. **None names a
> model / tier / capability / provider / temperature.** A model-aware kernel would inevitably
> take the model as input; it does not. (`is_shipped` params: `plan, phase, cfg, state,
> grep_fallback, expected_doc, commit_touches_doc, grep_touched_files, soaks`. `decide` params:
> `state, outcome`. Capability lives on *no* kernel input axis.)
>
> **Proof B (differential execution).** Run the real `is_shipped` + `liveness.classify` on
> identical inputs, paired once with a synthetic worker context `model="claude-opus-4-7"` and
> once with `model="claude-haiku-4-5"`. The serialized verdicts are **byte-identical** — the
> model marker has no parameter to flow into, so the swap changes nothing. The liveness
> evidence dump even carries `tokens_spent_since: null`: the kernel keeps the cost slot but
> never reads it as a signal ([128 §9](128_the-ultracode-economics-and-how-the-kernel-saves-spend.md)).
>
> The kernel's own committed suite confirms the same from the other side: `test_verdict_contract`,
> `test_oracle_and_loop`, `test_liveness`, `test_pickable`, `test_reconcile` — **145 tests
> green** — exercise every verdict purely from git/state/clock inputs, with no model fixture
> anywhere. The verdict floor is invariant under model swap *because* capability reaches no
> kernel input; routing a task to a cheaper model cannot move it.

The underlying facts, with line references:

- `dos.oracle.is_shipped(plan, phase, …)` is a **pure function** over a registry the agent
  did not author, with a git-ancestry fallback (`src/dos/oracle.py:30`). Its only external
  call is `subprocess.run` to invoke git (`oracle.py:370, 1114, 1239`) — it reads commit
  ancestry, never an LLM. A grep of the entire `src/dos/` tree for any provider import or
  inference call (`anthropic`, `openai`, `google.generativeai`, `messages.create`,
  `generate_content`, `httpx`, …) returns **nothing**.
- `dos.liveness.classify(now_ms)` reads a since-start commit delta + journal events
  (`src/dos/liveness.py`); `tokens_spent_since` is *explicitly not an input*
  (`liveness.py:163-167`, per [128 §9](128_the-ultracode-economics-and-how-the-kernel-saves-spend.md)).
  The kernel never reasons about cost — or about who paid it.
- `dos.loop_decide.decide(state, outcome)` is pure (no subprocess / file / git / model I/O);
  it consumes *verdicts* (`liveness`, `pickability`, `completion`) handed in as frozen input
  fields.
- `dos.pickable.classify(...)` and `dos.reconcile(...)` are likewise pure verdicts over
  state the worker cannot retroactively edit.

The trust law these instantiate is stated abstractly in
[102](102_when-to-trust-an-agent.md), and its key sentence is the bridge this whole doc
turns on:

> **trust a blackbox iff its output is checked against a prior, binding commitment the
> blackbox could not edit after the fact.** Where that holds, the agent's *internal process
> is irrelevant* — let it be as much a blackbox as you like, because you are not trusting the
> process, you are trusting the conformance of its artifact to a commitment.
> — [102 §3](102_when-to-trust-an-agent.md)

Read that last clause through a 2026 lens. **"The agent's internal process" includes which
model it is.** Opus-grade chain-of-thought and a $0.50/MTok model's shallower pass are both
*internal process*. The trust law says the kernel does not look at either — it looks only at
whether the artifact conforms to a commitment (a ship-stamp grammar declared in `dos.toml`
*before* the run; a git ancestry the agent cannot forge). The kernel is model-agnostic not
by oversight but because **model capability lives on precisely the axis the trust law throws
away.**

That is the inversion this doc names: *model-agnostic* is usually written as a portability
nicety ("works with any provider"). It is actually the **functional enabler of capability
routing**. A supervisor that judged by reading the worker's reasoning would have to trust a
weaker model's reasoning less, and could not safely downgrade. A supervisor that judges by
git ancestry is indifferent to the downgrade — the ship either happened or it didn't, and
the verdict is byte-identical whether the committer was Opus or Haiku.

---

## 3. The asymmetry the thesis predicts is sitting un-exploited in the reference app

If the argument in §2 is right, you would expect to find systems that already tier their
*work* to "capable enough" models — because the work's correctness is independently
checkable — while still over-paying on the *orchestration*, because nobody yet connected
"the kernel does the judgment" to "so the orchestrator's model can be cheap." The reference
job-dispatch app is exactly that system, and the seam is measurable.

**The work is already capability-routed.** The apply pipeline tiers down deliberately:
`_phase_model` sends Scout / Submit / Auth-Probe to Haiku — *"Scout, Submit, and Auth-Probe
use Haiku (cheaper); Fill and Complete use the configured apply model (Sonnet)"*
(`agents/_phase_shared.py:709`); `_micro_phase_model` sends text + demographics fills to
Haiku and keeps Sonnet only for combobox/screening/uploads (`_phase_shared.py:721`); the
Gemini backend leads every read-only chain with mid-tier Flash and keeps Flash-Lite as the
tail (`agents/config_pkg/gemini.py:38`). This is "capable enough" applied with a scalpel,
and it is safe precisely because each apply produces a confirmation artifact the kernel and
the proof-gallery check against ground truth.

**The orchestration is not.** All three headless dispatch children run the most expensive
model, uniformly: `CHILD_LAUNCH_MATRIX` pins `loop-iter`, `child1`, and `child2` to
`claude-opus-4-7` (`scripts/dispatch_child_config.py:67-106`), and the live `--model
claude-opus-4-7` flags are hardcoded in the SKILL launch blocks
(`.claude/skills/dispatch/SKILL.md:253, 684`; `.claude/skills/dispatch-loop/SKILL.md:406`).
There is no per-task differentiation and no documented break-even that says the orchestrator
*needs* Opus. What there is, is an explicit unresolved tension in the matrix's own notes —
child2 is annotated:

> *"playbook-driven; **deep reasoning wasted and paid N times over**."*
> — `scripts/dispatch_child_config.py:102`

— wasted reasoning, acknowledged, multiplied across N grandchildren, and still billed at
Opus rates.

**And the orchestrator's judgment is already entirely in the kernel.** This is the part that
makes the over-payment not just expensive but *structurally* unnecessary. Tracing the
dispatch-loop iteration, the upper LLM's per-iteration contribution is ~6 mechanical tool
calls (launch a child, confirm it started, heartbeat the lease, parse one result envelope) —
the reference app's own fan-out audit clocked it at ~6 tool calls per iteration, none of
which authored a ship. Every genuinely hard decision is
a $0 kernel verdict the LLM is **forbidden to re-derive**:

| Per-iteration decision | Decided by (zero model tokens) | LLM's role |
|---|---|---|
| Did this pick ship, or is the driver lying? | `oracle` / `packet_verdict` (git ancestry ⋈ registry) | reads a token |
| Continue, retry, or stop the loop? | `loop_decide.decide()` | obeys the verdict |
| dispatch vs replan next? | `gate_policy()` | obeys the verdict |
| Is the run spinning? | `liveness.classify()` (git delta) | reads a token |
| Is the lane held by a re-dispatch-invariant reason? | `pickable.classify()` | reads a flag |
| Backlog genuinely drained twice? | `gate_classify` drained-twice rule | reads a token |

The host's dispatch-loop skill states the contract in one line: act on the kernel's
`decision.action` — the kernel already called `decide()`; do NOT re-derive the stop
conditions. The continue/stop choice is a *mechanical
obey*, not a reasoning task — there is no branch where the LLM reads git and overrules the
kernel. The judgment was lifted out of the model and into deterministic code on purpose.

> **Proven on a real Haiku run — the full live A/B (2026-06-07).** The §5 experiment was run
> end-to-end: **140 real `claude -p` decisions** (K=14 cells × R=5 reps × 2 arms,
> `--model claude-haiku-4-5` vs `--model claude-opus-4-7` as the positive control), each against a
> *fresh throwaway git repo* whose commit graph was harness-authored, with ship-truth recomputed
> from `git merge-base --is-ancestor` — never the child's prose. The battery centred on the
> **lying-driver trap in both polarities**: lying-BLOCKED (token says blocked, git proves 1/2/3 real
> ancestor commits) and the asymmetric-hard lying-SHIPPED (token says `SHIPPED count=2/1/3`, git
> proves *zero* commits reachable from HEAD), plus honest-agree controls to defeat an
> always-distrust reflex. **Result: the ship-truth floor is perfectly model-invariant — Haiku and
> Opus each scored 65/65 over all decision cells and 30/30 over every trap rep in both polarities;
> followed-lie count = 0 for both arms.** Neither model ever shipped a phantom on a lying-SHIPPED
> token nor missed a real ship under a lying-BLOCKED one. The *only* systematic Haiku-vs-Opus delta
> was **cost: Opus cost 5.7× Haiku for the identical floor** — the dividend made
> concrete. (The run also surfaced a clean refinement, caught by the Opus positive control: the
> orchestrator's residual in-model work has two axes — *ship-truth* (model-invariant, above) and the
> *loop-control action* continue/stop/retry, which depends on loop-state the model isn't given and
> which the kernel's `loop_decide.decide()` owns deterministically in production, not the model. Only
> the ship-truth axis is the model's job, and it is the invariant one.) The full protocol,
> pre-registration, 140-row result log, and analysis are archived in the reference app's
> audit bundle (private repo).
> So the downgrade changes the cost and the narration, not the floor — the "capable enough" bet for
> the orchestrator is no longer a candidate, it is *measured*, including the hardest
> distrust-your-own-tooling case.

Put the two facts together and the asymmetry is stark: the layer whose decisions are
*entirely deterministic verdicts* runs the strong model; the layer whose decisions are
*genuinely capability-bound* (does this combobox need reasoning? can this form be filled?)
is the one that was carefully tiered down. The thesis predicts this is backwards, and the
code's own comments ("deep reasoning wasted") agree.

---

## 4. The honest counter, and why it does not rescue uniform-Opus orchestration

The strongest objection is 153's result turned into a warning: *"DOS recovers almost none of
the planning/judgment slice. If you downgrade the orchestrator you lose orchestration
*quality*, and the kernel will not catch it — silent stops are invisible to all three
detectors."* This is a real argument and deserves a real answer, not a dismissal.

The answer is that **the objection applies to a worker whose judgment is in the model, and
the dispatch orchestrator is not that worker.** 153's forfeited 90% is *planning* — choosing
which steps a task needs, in what order, recovering when the plan goes wrong. That is
exactly the work the dispatch loop **does not do in the LLM**: the planning was lifted into
`next-up`'s pick logic, the stop logic into `loop_decide`, the ship-truth into `oracle`. The
orchestrator LLM that remains does ~6 tool calls and obeys verdicts. There is almost no
planning slice *left in the model* for a downgrade to degrade — which is the entire reason
the over-payment is safe to question. 153 says "don't expect the kernel to cover a weak
model's planning"; the dispatch orchestrator answers "there is no planning here to cover —
it was already moved to the kernel."

This sharpens, rather than weakens, the claim, and it yields a clean **decision rule** for
when capability routing is safe — a rule the kernel makes checkable:

> **Route a task to the cheapest model whose residual in-model judgment is dominated by
> conformance to a prior commitment the kernel can check.** Where the hard decisions are
> already $0 verdicts the worker only *obeys* (dispatch orchestration), downgrade freely —
> the kernel is the floor and it does not move. Where the hard decisions live *in the
> model's reasoning* and produce no checkable artifact (open-ended planning, the silent-stop
> slice), the kernel is **not** a floor (153) — keep the capable model, or add a witness
> before you downgrade.

The same kernel property reads both ways, and that is the discipline: model-agnosticism is a
*license to downgrade exactly where a commitment is checked*, and an *explicit non-license
everywhere else*. The honest counter is not "so uniform-Opus is fine"; it is "so the test is
whether a checkable commitment brackets the task" — and for the dispatch orchestrator, it
provably does.

There is one residual in-model step per iteration that is not a pure obey: the orphan-collision
reroute (`.claude/skills/dispatch-loop/SKILL.md:511-524`), where the LLM re-acquires a
disjoint lane and re-runs the collision sweep. But even that is gated by a **mandatory
deterministic re-sweep** (`detect_orphan_child sweep`) whose `COLLISION` / `NONE` /
`SAFE-CONCURRENT` verdict the LLM only branches on — the judgment is in the sweep (git
ancestry), not the model. It is a few tokens of boolean control flow, not strong-model
reasoning. So the residual does not rescue the objection either.

---

## 5. What this is *not* — keeping the boundary honest (the [128 §9] discipline)

This doc would be marketing without the limits, so:

1. **DOS does not *do* the routing.** Exactly as [128 §4](128_the-ultracode-economics-and-how-the-kernel-saves-spend.md)
   says of model tiering — *"DOS decides whether a model is needed at all; it does not itself
   select Sonnet-over-Opus."* The kernel ships the verdict floor that *makes a downgrade
   safe*; the host realizes the saving by actually pointing the cheap child at a cheap model.
   Nothing here changes that the saving is host-realized and conditional.

2. **The floor only covers what a commitment checks.** Per §4 and 153: the kernel is a floor
   under *ship-truth, liveness, pickability, lane-disjointness* — the things a prior binding
   commitment can be checked against. It is **not** a floor under open-ended reasoning
   quality. Downgrading a model on a task with no checkable artifact is unguarded by DOS, and
   this doc claims nothing there.

3. **The Haiku evidence is decision-level (n=140), not a full end-to-end shipping marathon.** The
   §3 battery proves the *hard part transfers at scale*: across 140 real decisions — the
   lying-driver trap in both polarities + honest controls — Haiku matched Opus's ship-truth floor
   perfectly (65/65, 30/30 on traps, 0 followed-lies), so the obedience-and-distrust the thesis
   rests on is *measured with power*, not assumed from a single trial. What it does **not** show is
   an end-to-end run of a Haiku orchestrator driving N real `/dispatch` iterations to clean ships at
   the same rate across a live backlog (the residual mechanical plumbing — heartbeat timing, Monitor
   re-arms, orphan adoption — is exercised only at the decision layer here, not under live
   wall-clock; and a live backlog run was deliberately *not* hijacked because the fleet was mid-drain
   with three sibling leases held). That marathon is now *safe and legible to run* because the kernel
   verdicts make its outcome measurable from git — but it is future work the thesis de-risks rather
   than completes. The decision floor is no longer the open question; the wall-clock plumbing is.

4. **No new code, no new enum.** The kernel already has this property. The contribution is
   naming it correctly — *model-agnostic is the capability-routing floor, not a portability
   footnote* — and locating the live asymmetry that proves it has teeth.

---

## 6. The one-line synthesis

A stronger model is one whose *narration* you can afford to trust more. DOS's whole thesis is
that you should trust narration *not at all* and structure *only* — git ancestry, a prior
ship-stamp, a lane region-lock — none of which a weaker model can forge any more easily than
a strong one. So the kernel is model-blind by construction, and that blindness is exactly
what lets a fleet route each task to the cheapest model that can do it: **the verdict floor
does not sag when the model gets cheaper, because the floor was never standing on the model.**
The proof that this has teeth is sitting in the reference app, where the layer that runs the
most expensive model is the one whose every hard decision is already a $0 verdict it is
forbidden to re-derive — the capability-routing dividend, fully earned and not yet spent.

---

## References

**Kernel theory (the law this doc extends — `../`):**
- [102_when-to-trust-an-agent.md](102_when-to-trust-an-agent.md) — the trust law; §3's
  *"the agent's internal process is irrelevant"* is the bridge to model-agnosticism.
- [108_the-cheap-lie-and-the-narration-taxonomy.md](108_the-cheap-lie-and-the-narration-taxonomy.md)
  — why the dominant weak-model failure is the *invisible* one, hence why a narration-reading
  supervisor cannot safely downgrade.
- [153_can-dos-lift-a-weak-model.md](153_can-dos-lift-a-weak-model.md) — the *other*
  question (lift, not route); its honest negative result is the counter §4 answers, and its
  forfeited-planning-slice is the boundary §5 keeps.
- [128_the-ultracode-economics-and-how-the-kernel-saves-spend.md](128_the-ultracode-economics-and-how-the-kernel-saves-spend.md)
  — §4 (deterministic-first model ladder) + §10 (*"a Claude fleet, a Gemini fleet, or a mixed
  one"*) — the economics seed this doc promotes to a positioning claim; §9 is the honesty
  template §5 follows.
- [218_the-productivity-verdict-diminishing-returns-as-a-syscall.md](218_the-productivity-verdict-diminishing-returns-as-a-syscall.md)
  — sibling "the kernel reads a trend git already knows, not the model's self-report"; same
  externalize-the-judgment move.

**Source evidence (the property + the asymmetry):**
- `src/dos/oracle.py:30, 370` — `is_shipped` pure fn; only external call is git via
  subprocess; zero LLM surface across `src/dos/`.
- `src/dos/liveness.py:163-167` — `tokens_spent_since` explicitly not a verdict input; the
  kernel never reasons about cost or model.
- The reference userland app (private repo) supplies the asymmetry's other half: its
  *worker* phases are already capability-routed (cheaper tiers for read-only/simple
  phases) while its *orchestration* runs uniformly on the strong model — the
  "deep reasoning wasted and paid N times over" tension this doc lifts to a kernel
  concern — and its dispatch-loop skill instructs the model to obey the kernel's
  `decide()` rather than re-derive it, with its fan-out audit showing the
  orchestrator's residual in-model work is mechanical (~6 tool calls/iteration).

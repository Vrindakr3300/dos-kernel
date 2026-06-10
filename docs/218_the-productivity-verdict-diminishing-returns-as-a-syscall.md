# 218 — The productivity verdict: diminishing returns as a syscall

> **Status:** ✅ **Shipped** (2026-06-07). `src/dos/productivity.py` (the pure
> verdict), `dos productivity` (the CLI verb), `tests/test_productivity.py` (24
> tests), the `dos doctor --json` exit-contract row. This is the build of idea
> **H1** from the Claude Code source audit (docs/189): *the diminishing-returns
> gate, lifted as a kernel primitive.*

## What this is, in one sentence

`liveness` asks "did the run move *at all*?"; `productivity` asks "is the run
still moving *as fast*, or is each step doing less and less?" — a verdict over a
**trend**, not a single count.

## The gap it closes

DOS already distrusts an agent's claims about motion. `verify` distrusts a
*finished* claim ("I shipped P"). `liveness` distrusts an *in-flight* claim ("I'm
making progress") by reading ground truth: did git or the lane journal advance at
all since the run started? That answer is a yes/no over the run's whole lifetime.

But there is a failure mode that answer cannot see. A run can keep committing —
so `liveness` says ADVANCING, correctly — while each successive step lands less
and less real work, until the run is spending a large budget to refine the same
small thing. The state *is* moving, so it is not SPINNING; it is just moving
slower and slower. Call it **productive-but-fading**. Nothing in the kernel had a
verdict for it:

- `liveness` reads a single since-start count. A count cannot show a *trend* —
  "10 commits" looks the same whether the run is accelerating or grinding to a
  halt.
- `loop_decide` (the reference app's dispatch-loop decider) stops on hard count
  caps (`max_iterations=10`) and discrete verdicts (DRAIN, BLOCKED, SPINNING). It
  has six hand-coded circuit-breakers, and every one of them counts *events* or
  reads a *discrete verdict* — none of them measures a *rate*. So the loop's only
  answer to a fading run is "stop after N iterations," which is the wrong knob: it
  stops a fast run too early and a grinding run too late.

The missing verdict is **stop-when-unproductive**, not stop-after-N.

## Where the shape comes from: Claude Code's own loop

The docs/189 audit of the Claude Code v2.1.88 source found exactly this verdict
already running inside CC's session loop, and flagged it as "the cleanest
loop-economics lift." The function is `checkTokenBudget` in
`src/query/tokenBudget.ts`. Its core is one boolean:

```ts
const isDiminishing =
  tracker.continuationCount >= 3 &&
  deltaSinceLastCheck < DIMINISHING_THRESHOLD &&
  tracker.lastDeltaTokens < DIMINISHING_THRESHOLD
```

Read it in plain words: a run is *diminishing* when it has taken at least three
steps **and** this step did little **and** the previous step also did little.
That is the whole idea. Three signals, ANDed.

The AND is the load-bearing part, and it is worth saying why. A single quiet step
is not a fading run — a run legitimately pauses to read a large file, to plan, to
wait on something eventually-consistent. If one small step tripped the verdict,
it would fire constantly on healthy runs (the docs/188 lesson: a noisy detector
that fires on normal behavior is worse than no detector). Requiring the **last
two** steps to both be small means the verdict fires on a *sustained* low rate —
a trend — not a blip. It is the productivity analogue of `liveness`'s `grace_ms`
guard, which withholds the SPINNING accusation until a run is old enough to
deserve it: withhold the accusation until there is enough evidence to make it.

## Why it belongs in the kernel — the mechanism/policy test

The reason a small thing can be a universal cog is the same reason `malloc` is in
every C program: it is **mechanism with the policy pushed out**. `malloc` does
not know what you are allocating; it knows how to hand out bytes. A
harness-specific "stop the dispatch loop after 10 iterations" rule can never be
universal, because the 10 and the "dispatch loop" are someone's policy baked into
the mechanism. A *domain-free* "the work-per-step rate is fading" verdict can be,
because the policy is data the caller supplies.

`productivity.classify` passes that test cleanly:

- **The mechanism is the kernel's:** the pure fold over the trend — "enough
  steps AND the last two deltas both under the floor." That logic is the same
  whether the run is writing code, filling forms, or moving money.
- **The policy is the host's, as data:** *what a "work unit" is* (tokens?
  commits? changed bytes? passed tests?), *how many steps* count as a trend
  (`min_steps`), and *what counts as "did little"* (`floor`). The kernel never
  knows the unit — it only compares magnitudes. The host names the unit and the
  thresholds in `dos.toml [productivity]`, the same closed-config-as-data pattern
  as `[lanes]` / `[stamp]` / `[liveness]`.

This is why the evidence type is called `WorkHistory` and its field is a bare
list of `deltas`, not `tokens` or `commits`. Naming it `tokens` would weld one
host's unit into the kernel. Naming it `deltas` keeps the kernel unit-agnostic —
the cog stays universal.

## Byte-clean by construction

The docs/138 invariant: a signal is evidence only when its bytes were authored by
something *other than the judged agent*. A productivity delta passes, for the same
reason `liveness`'s git read and `tool_stream`'s result-digest do: a per-step
work delta is a count the **runtime or environment** produces — tokens the
provider metered this turn, commits git recorded this step, bytes the diff
measured. The agent does not get to type "I did a lot this step." So DIMINISHING
means *the work rate the environment recorded is fading*, never *the agent says
it's almost done*. It is a quantity, not a self-report.

And, like `liveness.SPINNING`, the verdict reports a **quantity of motion, not a
judgment of quality**. DIMINISHING says the rate fell; it never says the work was
*wrong*. Whether slow work is bad work is an advisory judge's call (`llm_judge`),
never this deterministic kernel verb — the distrust-state / distrust-judgment line
the whole kernel holds.

## The verdict ladder

Three states, mutually exclusive, read top to bottom (the whole point is that a
reader holds the ladder in their head):

1. **PRODUCTIVE (too little history)** — fewer than `min_steps` steps. There is
   not enough of a trend to accuse a run of fading. Withhold the accusation. A
   run with no steps at all also lands here: nothing to judge, no problem yet.
   (The benign verdict — the `liveness` young-and-alive guard, restated for the
   work axis. It explicitly does *not* claim the run is thriving; it claims there
   is no productivity *problem* to flag.)
2. **STALLED** — the most recent step landed **zero** work. The run flat-lined.
   This is the degenerate floor of diminishing — a fading rate that reached
   nothing — but it is named distinctly because a zero is the operator's clearest
   "it stopped doing anything" signal, the give-up rung. Named precisely so it is
   not blurred into a merely-slow rate.
3. **DIMINISHING** — `step_count >= min_steps` **and** the last two deltas are
   **both** under `floor`. CC's `isDiminishing`, exactly. Fading, but still
   moving a little.
4. **PRODUCTIVE** — none of the above: a recent step cleared the floor, or the
   low rate is not sustained across the last two steps. Still doing real work.

## How it differs from its siblings — keeping the verdicts apart

The kernel is deliberate about not having two verdicts that answer the same
question (the docs/79 primitives discipline). Here is the carve:

| Verdict | The question | The evidence | Shape of answer |
|---|---|---|---|
| `verify` | Did the *finished* claim ship? | git ancestry + ship-stamp | yes / no |
| `liveness` | Did *ground-truth state* move at all since start? | one since-start count (commits / journal events) + heartbeat age | moved / alive-not-moving / dead |
| `tool_stream` | Did the *env's tool results* advance, or recur? | the env-authored `(tool, args, result_digest)` stream | advancing / repeating / stalled |
| **`productivity`** | Is the *work-per-step rate* fading? | a **trend** of per-step work deltas | productive / diminishing / stalled |

The one-line distinction: every other verdict reads a **count or a stream**;
`productivity` reads a **trend**. A run that is ADVANCING (liveness) can be
DIMINISHING (productivity) at the same time, with no contradiction — they are
answering different questions, and that is the point of having both. `liveness`
catches the run that *stopped*; `productivity` catches the run that is *grinding*.

`tool_stream` is the nearest neighbor — both watch an in-process sequence — but
they look for different things. `tool_stream` looks for *repetition* (the same
result recurring); `productivity` looks for *decline* (the amount of work
shrinking). A run can produce all-different results that get steadily smaller —
that is invisible to `tool_stream` (no repeat) and visible to `productivity` (a
falling trend), and vice versa.

## Timeless: the one place it is even purer than `liveness`

`liveness.classify` reads ages (`now_ms - run_started_ms`) — it needs a clock,
gathered at the boundary and frozen onto the evidence. `productivity.classify`
does not read a clock at all. It reads a *sequence*. Productivity is **timeless**:
the verdict over `[800, 600, 300, 40, 12]` is the same whether those steps took
one minute or one day. So the no-I/O discipline here is total — the test bans
`time.time` *and* `open` and the verdict still returns. This also makes it the
strongest no-plan floor of any verdict: it needs no git, no journal, no registry,
no clock — only the deltas the caller already has.

## The CLI

The verdict IS the exit code, the same idiom as `liveness`/`gate`, so a
babysitter loop branches on it without parsing stdout:

```bash
dos productivity --deltas 800,600,300,40,12 --floor 100
#   DIMINISHING  the last two of 5 steps landed 40 then 12 work units,
#                both under the 100-unit floor — a sustained fading rate
#   exit 3

dos productivity --deltas 40,30,500 --floor 100
#   PRODUCTIVE  last step landed 500 work units over 3 steps — still productive
#   exit 0

dos productivity --deltas 800,50,0
#   STALLED  the most recent of 3 steps landed 0 work units — flat-lined
#   exit 4
```

Exit codes: PRODUCTIVE 0, DIMINISHING 3, STALLED 4, contract-error 2 (a bad
`--deltas`). A non-numeric delta is a contract error, never silently dropped — a
corrupted trend would give a wrong verdict, and the kernel refuses to guess
(docs/117 refuse-don't-guess). The deltas are oldest-first; the `--floor` and
`--min-steps` flags override the generic defaults (500 / 3, the CC constants)
when a host has not yet declared a `[productivity]` table.

## What it deliberately leaves out

CC's `checkTokenBudget` actually does two things in one function: the
diminishing-returns *trend* (lifted here) **and** an absolute ceiling
(`turnTokens < budget * COMPLETION_THRESHOLD` — "stop when you've spent most of a
fixed budget"). PRD lifts only the trend, on purpose. An absolute ceiling is a
*different* mechanism: it is a host's answer to "what is my budget?", a number
that means nothing to the kernel and everything to one operator's wallet —
exactly the policy that belongs in `loop_decide.max_iterations` / a host cap, not
in a domain-free verdict. Folding it in would weld a budget into the primitive
and break the mechanism/policy split that is the whole reason this can be a shared
cog. The trend is universal ("is the rate falling?"); the ceiling is local ("is
the bill too high?"). PRD is the universal half.

## What it makes buildable (the primitive's open right column)

`productivity` is shipped as a primitive, not wired into a consumer yet — the
docs/79 restraint. The space it opens, none of which touches this module:

1. **A `loop_decide` `DIMINISHING_RETURNS` rung.** The natural first consumer: a
   loop gathers per-iteration work deltas (commits-per-iter, or tokens-per-iter)
   and stops when `productivity.classify → DIMINISHING`, converting the
   stop-after-N cap into stop-when-unproductive. This is the H1 payoff the audit
   named; it is a *driver/host* change (the reference app's loop), not a kernel
   change — the kernel just supplies the verdict.
2. **A WARN-before-BLOCK nudge on the enforce ladder.** DIMINISHING is a softer
   signal than STALLED — the ladder (docs/144, OBSERVE‹WARN‹BLOCK) can attach a
   WARN ("you're at a fading rate; consider wrapping up") in flight, the soft
   precursor to a hard stop. The audit's H4 "continuation nudge," grounded in a
   real verdict.
3. **A `dos top` swimlane chip.** The live fleet TUI already shows liveness; a
   fading run is a different color of trouble than a stalled one, and an operator
   wants to see it before it hits the cap.
4. **A `dos status` rung.** `status` folds liveness/resume/completion; a fourth
   "is it still productive?" rung is a one-line add at the same evidence boundary.

## The next lifts from the same audit (H-theme)

This is the first of the loop-economics cluster docs/189 surfaced. The siblings,
all domain-free mechanisms, all unbuilt:

- **H2 — a generic circuit-breaker facility.** `loop_decide` hand-codes six
  near-identical breakers (CONSECUTIVE_UNCLEAR / DIRTY_ZERO / OVERLOADED /
  STALE_STAMP …). Extracting `circuit_breaker(streak, threshold) -> Triggered` +
  a fail-N-then-escalate variant (CC's `denialTracking`: classifier → human after
  N) is the *malloc* of the loop's stop logic — the policy (which failure class,
  what threshold, what escalation rung) becomes data.
- **H3 — verdict-repeat → escalate-the-mechanism.** If the same `refuse` reason
  (or `liveness → STALLED`) recurs N times for a lane, don't re-emit the same
  verdict — escalate the *rung* (ORACLE → JUDGE → HUMAN). "Don't keep refusing
  identically."

`productivity` is the cleanest of the cluster (no refactor, a brand-new
primitive, no existing equivalent), which is why it shipped first.

---

*Provenance: idea H1 from docs/189 (the Claude Code v2.1.88 source audit). Source
shape: `tokenBudget.ts:checkTokenBudget` (`isDiminishing`, the 3-signal AND).
Built 2026-06-07 as `src/dos/productivity.py` + `dos productivity` + 24 tests.*

# LVN — Liveness-oracle plan (the 4th distrust syscall: *is the agent actually moving?*)

> **Status:** 🚧 **Phases 1–2 shipped** (2026-06-01); Phase 3 still design. This is the highest-value
> entry in the distrust-primitive map (`project-dos-distrust-primitive-map`):
> the temporal completion of `verify()`. `verify` distrusts a *finished* claim
> ("I shipped P"); LVN distrusts an *in-flight* claim ("I'm making progress").
> A spinning agent never produces a finished claim to check — so today the
> operator falls back to watching output, the exact cost DOS set out to remove
> ("not having to read output and guess", `project-dos-real-use-value`). LVN is
> the syscall that ends the watching: a pure verdict over ground-truth deltas the
> agent cannot forge.

## The gap this closes

DOS ships three distrust syscalls — `verify()` (did it ship?), `refuse()` (why
blocked?), `arbitrate()` (is the lane free?). Each answers a question about
*state* from evidence the agent can't author. There is a fourth question every
operator of a long-running agent asks and that nothing in the kernel answers:

> **Has ground-truth state actually advanced since this run started, or is the
> agent spinning?**

An agent in a loop is a *systematically optimistic narrator of its own motion*:
it reports "refining the approach", "almost there", "making good progress" while
re-editing the same file, re-running the same failing test, and burning tokens
with zero state change. It cannot see its own loop. The operator can — but only
by reading output and judging, by hand, the thing DOS exists to adjudicate
mechanically. The self-report is exactly where it's least trustworthy, and
exactly where the kernel currently has no verdict.

The closest existing module, `loop_decide.decide()`, *does* catch some spinning
— `consecutive_unclear`, `consecutive_dirty_zero`, `DRAINED_TWICE` are
anti-spin breakers. But it reads the **caller's self-reported `IterationOutcome`
tokens** (`SHIPPED` / `GATE` / `UNCLEAR`), not ground truth. A loop that reports
`SHIPPED` every iteration while landing zero commits is caught *only* if the
caller also classified the packet honestly (the `SHIPPED-DIRTY` + `ship_count==0`
pair). LVN closes the loop under that: it asks the **git history and the lane
journal**, not the agent, whether anything moved. It is to `loop_decide` what
`verify()` is to the SHIPPED-stamp: the registry-first, distrust-the-narrative
version of a signal the self-report also carries.

## What it is — a pure verdict, evidence gathered outside (the arbiter discipline)

LVN is **not** a monitor, a watchdog thread, or anything that polls. It is the
same shape as every other DOS syscall verdict (`arbiter.arbitrate`,
`loop_decide.decide`, `gate_classify.classify_packet`): a **pure function** that
takes already-gathered evidence in and returns one typed verdict out. All I/O —
reading git, reading the journal, reading the clock — happens *before* the call,
in the CLI/caller boundary, exactly as `pick_oracle`'s I/O happens outside
`arbitrate()` (`arbiter.py:131`) and `verify`'s git reads happen outside the
classifier.

```python
# dos/liveness.py  (the new pure kernel module — loop_decide's sibling)

class Liveness(str, enum.Enum):
    ADVANCING = "ADVANCING"   # ground-truth state moved since the run started
    SPINNING  = "SPINNING"    # the run is active (heartbeat fresh) but state is NOT moving
    STALLED   = "STALLED"     # no heartbeat, no commits — the run is dead or hung, not spinning

@dataclass(frozen=True)
class ProgressEvidence:
    """Everything classify() needs, gathered by the caller BEFORE the call.
    No git, no journal, no clock inside the verdict — the arbiter rule."""
    run_started_ms: int            # run_id.ts_ms_of(run_id) — the clock is in the token, free
    now_ms: int                    # injected (the env BANS Date.now in pure paths)
    commits_since_start: int       # len(timeline._git_log(start_sha)) — the authoritative delta
    journal_events_since: int      # lane-journal entries with seq/ts after the run start
    last_heartbeat_age_ms: int | None   # now - newest HEARTBEAT/ACQUIRE ts; None = never beat
    tokens_spent_since: int | None      # optional: cost burned with no commit (the waste signal)

def classify(ev: ProgressEvidence, policy: LivenessPolicy = DEFAULT) -> LivenessVerdict:
    ...
```

The verdict logic is small and total — the whole point is that a reader holds it
in their head (the `loop_decide` design value):

- **No fresh heartbeat AND no commits** since start, past the grace window →
  `STALLED` (the run is dead/hung; this is the orphan-detector's input, not a
  spin).
- **Fresh heartbeat** (the run is alive and working) **but zero commits AND zero
  state-mutating journal events** past the spin window → `SPINNING` (alive,
  narrating, not moving — the signal that has no existing home).
- **Any forward delta** (≥1 commit, or a state-mutating journal event, or — at a
  workspace's option — a `verify()` that flipped to SHIPPED) → `ADVANCING`.

The windows (`grace_ms`, `spin_ms`) are policy, carried on `LivenessPolicy`, with
a generic default — the same "mechanism is kernel, thresholds are config" split
as `loop_decide`'s `max_unclear` / `max_iterations`.

## The clock and the deltas already exist — LVN is mostly assembly

Every input above is something the kernel already computes; LVN does not add a
new evidence source, it *adjudicates* the ones the spine already has:

- **Run start time** — `run_id.ts_ms_of(run_id)` decodes epoch-ms straight from
  the sortable token. No I/O, no stored timestamp. The correlation spine (CID)
  was built so "since run R started" is a pure decode.
- **Commit delta** — `timeline._git_log(start_sha)` is *already* "commits since
  the run's start SHA", already factored, already used by the dispatch timeline.
  LVN's git rung is that call, lifted to a shared helper.
- **Heartbeat / journal delta** — `lane_journal.read_all()` + the `HEARTBEAT` /
  `ACQUIRE` ops already carry `heartbeat_at` and monotonic `seq`. "Newest
  heartbeat age" and "events since start" are folds over `read_all()`, the same
  read `replay()` already does.
- **Token spend** — the optional waste signal; a workspace that tracks per-run
  cost (job's telemetry sidecars) can pass it, a workspace that doesn't passes
  `None` and the verdict degrades to the commit/heartbeat rungs. Never required
  (the no-plan-needed discipline: LVN must answer in a plain git repo with no
  telemetry at all).

This is why LVN is the right *next* one: the mechanism is sitting in the spine,
the verdict is `loop_decide`-shaped, and the contribution is a syscall, not a
subsystem (`project-dos-primitives-not-features` — a small primitive that opens
buildable space above it, e.g. a loop that self-refuses on `SPINNING`, a fleet
dashboard that flags spinning agents, a `decisions`-queue row).

## Design laws this plan must honor

- **The verdict stays PURE.** No git, no journal, no clock, no subprocess inside
  `classify()`. Evidence is gathered by the caller and passed in — the
  `arbitrate()` / `pick_oracle` rule (`arbiter.py:107`, `131`). This is what lets
  the verdict be replay-tested on frozen fixtures, away from anything that needs a
  live multi-minute agent run to reproduce.
- **The clock is injected** (`run_id.py` hard rule; this environment *bans*
  `Date.now()` in reproducible paths). `now_ms` is a field on `ProgressEvidence`,
  never read inside the verdict.
- **Evidence-over-narrative** (`project-dos-kernel-design-laws` law #1, restated
  for the temporal axis). The verdict consults git + journal FIRST; a self-report
  ("I'm making progress") is never an input. This is the same inversion as
  registry-first ship: the durable artifact is truth, the narration is decorative.
- **Distrust state, never judgment** (`project-dos-flexibility-geometry` /
  `docs/76`, and the anti-pattern rail in the distrust-primitive map). LVN
  answers a mechanical question about *whether bytes moved*. It does **not** judge
  whether the movement was *good*, whether the approach is *sound*, or whether the
  agent is *confused* — those are taste/correctness, an advisory judge's job
  (`llm_judge.py`), never a deterministic kernel verb. `ADVANCING` says state
  changed, not that it changed *well*.
- **No-plan-needed** (`tests/test_verify_no_plan.py` discipline). LVN must return
  a verdict against a plain git repo with a run-id and a start SHA and *nothing
  else* — no plan, no registry, no telemetry. Commits-since-start alone is a
  sufficient `ADVANCING` / `SPINNING` signal; every richer input is optional.
- **`SPINNING` is advisory, never an admission force.** LVN reports; it does not
  kill. A loop *may* consult LVN and choose to stop (the natural first consumer),
  and the operator-decisions queue *may* surface a spinning run — but LVN never
  reaches into the arbiter to refuse a lease. (Distrust-state separation: the
  liveness verdict and the admission decision are different syscalls. A future
  `LivenessPredicate` that refuses a *new* lease for a process already spinning is
  possible under ADM's conjunctive seam — but that is opt-in driver policy, not
  LVN itself.)

## North-star acceptance (the whole plan is done when)

```bash
# A run that has been alive for 8 minutes (heartbeat fresh) but landed 0 commits:
dos liveness --workspace . --run-id RID-XXXX --start-sha abc123
# → SPINNING  (alive 8m, 0 commits, 0 lane events since start — the agent is
#              narrating motion it isn't making)

# The same run after a commit lands:
dos liveness --workspace . --run-id RID-XXXX --start-sha abc123
# → ADVANCING (1 commit since start)

# A run whose heartbeat is 40 minutes stale, 0 commits:
dos liveness --workspace . --run-id RID-YYYY --start-sha abc123
# → STALLED   (no heartbeat past grace, 0 commits — dead/hung, feed the orphan sweep)
```

…and `dos liveness --output json` emits the verdict + the evidence that drove it
(the renderer seam, RND/Axis-4: `--output` already on verify/arbitrate/man/
decisions; LVN joins them), and the verdict function passes the **no-plan** test
— it classifies a plain git repo from commits-since-start alone, with journal and
telemetry absent.

---

## Phase 1 — `Liveness` verdict + the pure classifier (throughline) — ✅ SHIPPED 2026-06-01

The smallest end-to-end slice: the typed verdict, the evidence dataclass, the
pure `classify()`, and the `dos liveness` CLI verb that gathers evidence and calls
it. Git-rung only — the signal that already exists in `timeline`.

**Built:** `src/dos/liveness.py` (the pure `Liveness` enum / `ProgressEvidence` /
`LivenessVerdict` / `LivenessPolicy` / `classify`), `src/dos/git_delta.py` (the
shared "commits since start SHA" reader, with `timeline._git_log` now delegating
to it so the rung can't drift), and `cmd_liveness` in `cli.py` (`dos liveness
--run-id … --start-sha … [--now-ms] [--last-heartbeat-age-ms] [--json|--output]`;
verdict-as-exit-code ADVANCING=0/SPINNING=3/STALLED=4, bad run-id=2). All five
Phase-1 litmus tests + four CLI/no-plan tests green in `tests/test_liveness.py`;
full suite 329 green.

**The two-window resolution** (the spec was loose on how `grace_ms`/`spin_ms`
interact): `spin_ms` is the **heartbeat-freshness (alive/dead) bound**, `grace_ms`
is the **minimum run-age before an alive-but-idle run is accused of SPINNING** (a
false-positive guard so a run that simply hasn't committed in its first minute
isn't called spinning — it reports ADVANCING-benign, "no liveness problem yet").
So: forward delta → ADVANCING; else heartbeat fresh (≤ spin_ms) AND run-age ≥
grace_ms → SPINNING; else heartbeat fresh but run too young → ADVANCING; else
(heartbeat stale or absent) → STALLED.

- **1a.** Add `dos/liveness.py`: the `Liveness` `str`-enum
  (`ADVANCING|SPINNING|STALLED`), a frozen `ProgressEvidence`, a frozen
  `LivenessVerdict` (`verdict: Liveness`, `reason: str`, plus the evidence echoed
  back for the `--output json` consumer), a frozen `LivenessPolicy`
  (`grace_ms`, `spin_ms`, with a generic default), and the pure
  `classify(ev, policy) -> LivenessVerdict`. No I/O; `now_ms` is a field. Mirror
  `loop_decide`'s module docstring discipline — the verdict ladder, top to
  bottom, in one place.
- **1b.** Factor `timeline._git_log(start_sha)` into a shared kernel helper (it is
  the commit-delta evidence both the timeline and LVN need; LVN must not re-implement
  it). The CLI's evidence-gather step calls it, counts commits, decodes
  `run_id.ts_ms_of(run_id)` for the start, and reads the clock at the boundary.
- **1c.** Add `cmd_liveness` to `cli.py` (a `dos liveness` subparser beside
  `verify`/`arbitrate`): args `--run-id`, `--start-sha`, optional `--now-ms`
  (injectable for tests/scripts; defaults to wall clock at the boundary only),
  `--output text|json`. It gathers evidence and calls `classify`. Journal/telemetry
  rungs are stubbed to absent in Phase 1 (commit-rung only).

**Litmus (Phase 1):**
- `tests/test_liveness.py::test_commits_since_start_is_advancing` — ≥1 commit →
  `ADVANCING`, on frozen evidence (no live git).
- `test_no_commits_fresh_heartbeat_is_spinning` — 0 commits, a fresh heartbeat age
  passed in → `SPINNING`.
- `test_no_commits_no_heartbeat_past_grace_is_stalled` — 0 commits, heartbeat age
  past `grace_ms` (or None) → `STALLED`.
- `test_classify_is_pure` — `classify()` makes no subprocess/file/clock call
  (same assertion style as the arbiter purity test).
- `test_liveness_no_plan` — the **no-plan rail**: `dos liveness` returns a verdict
  in a plain git repo with no `docs/*-plan.md`, no registry, no journal
  (commits-since-start alone suffices), the temporal sibling of
  `test_verify_no_plan.py`.

---

## Phase 2 — the journal + heartbeat rungs (distinguish SPINNING from STALLED honestly) — ✅ SHIPPED 2026-06-01

Phase 1's heartbeat age was caller-supplied (`--last-heartbeat-age-ms`); Phase 2
grounds it (and the lease-event signal) in the lane journal so the alive-vs-dead
distinction comes from kernel evidence, not a passed number.

**Built:** `src/dos/journal_delta.py` — `git_delta`'s sibling (the same
boundary/pure-fold split LVN-1b established): a PURE
`fold_since(entries, *, run_started_ms, now_ms, lease_key) -> JournalDelta`
(`events_since_start`, `newest_heartbeat_age_ms`, `saw_corrupt`), replay-testable
on frozen entry lists like `lane_journal.replay()`. The CLI's evidence-gather
(`cli._journal_delta`) does the `lane_journal.read_all(path=cfg.paths.lane_journal)`
at the boundary (explicit served path, never the process-global; every-failure→
empty, the `git_delta` stance) and hands the list to the fold; `cmd_liveness`
then feeds the two numbers into `ProgressEvidence`. `classify()` is BYTE-UNCHANGED
— Phase 2 only changed WHERE its two journal inputs come from. New `--lane` /
`--loop-ts` args carry this run's lease identity. `tests/test_journal_delta.py`
(15 pure-fold tests) + 3 new CLI tests in `tests/test_liveness.py`; full suite
371 green.

- **2a.** ✅ The pure fold lives in `journal_delta.py` (not on `lane_journal`,
  whose job is lease correctness + replay — the liveness clock/attribution
  semantics are sibling-kernel, the `timeline`→`git_delta` arrow). It imports
  only the lane-journal `OP_*` constants + `_lease_identity`; it never imports
  back into `lane_journal`, reads no config, calls no clock.
- **2b.** ✅ The CLI wires it in. The ladder now separates `SPINNING` (fresh
  journal heartbeat, 0 commits, 0 lease-work events) from `STALLED` (stale/absent
  beat) on real evidence. `--last-heartbeat-age-ms` became an **override** (it
  wins over the journal-derived age when given — a non-journal source like the
  live registry); absent, the journal-derived age is used.
- **2c.** ✅ Fail-closed degrade: a `_CORRUPT` sentinel, an unparseable `ts`, an
  empty/missing journal — none can invent an event or a beat, none raises;
  corruption only ever *reduces* observed progress (sets `saw_corrupt`, kept for
  a Phase-3 renderer's data-quality note, never flips the verdict). The journal
  read never creates the journal or `.dos/` (the no-plan / read-only rail, pinned
  by the extended `test_liveness_no_plan`).

**Two design refinements the build pinned (the spec was loose):**

- **Identity is REQUIRED for the journal rungs** (operator call, 2026-06-01:
  *require identity always*). A journal entry carries no run-id — only a
  `(loop_ts, lane)` lease key — so time-alone attribution would let a busy
  *neighbor* lane manufacture a false `ADVANCING` (or keep a dead run "alive" off
  a neighbor's beat). The fold scopes every rung to `lease_key`; with no identity
  (`--lane`/`--loop-ts` absent) the journal rungs go **silent** (events 0, no
  journal heartbeat) — there is no host-wide "is *some* lane alive" guess. The
  bare `dos liveness --run-id … --start-sha …` North-star still answers from the
  commit rung (proven: bare form → `STALLED`/`ADVANCING` by commits alone).
- **A `HEARTBEAT` is a *beat*, not an *event*.** docs/82's own ladder (the
  "fresh heartbeat … but zero *state-mutating* events → SPINNING" line)
  distinguishes the *freshness* signal from *progress*. So the event rung counts
  only lease-*work* ops (`ACQUIRE`/`RELEASE`/`SCAVENGE`/`RECONCILE`) STRICTLY
  after the start-second floor — excluding both the boundary `ACQUIRE` and a
  keepalive `HEARTBEAT`. This is what makes `SPINNING` *reachable* from the
  journal: a fresh `HEARTBEAT` proves life without counting as motion. Time
  attribution uses the entry's own append `ts` (never the copy-prone
  `heartbeat_at`), and a future-dated beat beyond a 1 s slack is dropped (not
  clamped) — both fail toward `STALLED`. **The EVENT rung carries the same future
  upper bound** (`(floored start, now + slack]`): events ≥1 is the top-of-ladder
  `ADVANCING` verdict — the most consequential — so it must be the *best*-guarded,
  not the worst; a future-skewed lease op (NTP step-back / forgery / cross-host
  merge) must fail toward `SPINNING`/`STALLED`, never invent `ADVANCING` (docs/82
  2c "over-counting is FORBIDDEN"). *(Hardening, 2026-06-01: an adversarial review
  caught the event rung shipping with only a lower bound — a future-dated op
  fabricated `ADVANCING` on a stuck run; fixed + pinned by
  `test_future_dated_event_is_not_advancing`.)*

**Write-path closure (the HEARTBEAT writer SHIPPED, kernel-side):** the Phase-2
journal fold was originally fed only by synthetic test entries — no writer in the
package emitted a `HEARTBEAT` op, so in production the newest journal beat for a
long run was its boundary `ACQUIRE`, which aged out → `STALLED`, and **SPINNING
was unreachable from real evidence.** That gap is now closed *in the kernel*, not
host-side: the generic Layer-3 write-back `lane_lease.heartbeat` (the verb behind
`dos lease-lane heartbeat`) appends an `OP_HEARTBEAT` for a currently-held lease,
so a held worker beating on a cadence refreshes the journal beat and the fold
reaches SPINNING (alive-but-not-progressing) on a real timeline. The
held-lease-only guard is load-bearing: `fold_since` credits a beat by identity+ts
with no held-lease check, so beating only a *live* lease is the writer-side
defense that stops a stray post-`RELEASE` beat from reading a dead run alive
(pinned by `test_post_release_stray_beat_cannot_revive`). The end-to-end flip
STALLED→SPINNING from the real writer is pinned by
`test_heartbeat_makes_spinning_reachable_end_to_end`. `--last-heartbeat-age-ms`
remains an override for a non-journal heartbeat source. (A *host* with its own
separate registry may still write heartbeats there too; that is additive, not a
prerequisite — the kernel path stands alone now.)

**Litmus (Phase 2):** — all green
- `test_journal_event_without_commit_is_advancing` — a lease-work op (here
  `RECONCILE`) after start, 0 commits → `ADVANCING` (lease-layer progress).
- `test_stale_heartbeat_is_stalled` vs `test_fresh_heartbeat_no_progress_is_spinning`
  — separated purely by the journal-derived heartbeat age, on frozen entries.
- `test_corrupt_journal_degrades_safe` — a `_CORRUPT` sentinel never yields an
  event or a beat and never raises; an all-corrupt journal → `STALLED`.
- `test_lone_boundary_acquire_is_not_advancing` / `test_same_second_pre_start_op_excluded`
  — the strict `>`-floor rounding (a held-but-idle lane / a same-second pre-start
  op is never `ADVANCING`-by-journal).
- `test_neighbor_lane_events_do_not_advance_this_run` /
  `test_neighbor_heartbeat_does_not_keep_dead_run_alive` — the identity-scope
  cross-run defenses.
- `test_future_dated_beat_is_dropped_not_clamped` — a future beat fails toward
  `STALLED`, not age-0.
- CLI: `test_liveness_cli_journal_event_advancing` /
  `test_liveness_cli_journal_spinning` /
  `test_liveness_cli_heartbeat_override_wins_over_journal` — the boundary read +
  fold + classify path, and the override precedence, end-to-end.

---

## Phase 3 — the consumer seam + the policy/output rails

Make the verdict *useful*: a loop that self-refuses on `SPINNING`, the decisions
queue surfacing it, the policy declarable, the verdict rendered through the shared
`--output` seam.

- **3a.** *(the first real consumer)* Extend `loop_decide` so a caller can pass an
  optional `Liveness` verdict into the loop state, adding a `SPINNING` stop reason
  (`StopReason.SPINNING`) — the loop stops itself when the kernel says it's
  burning tokens without moving, instead of waiting for the iteration cap. This is
  the payoff: the anti-spin breaker that reads *ground truth*, complementing the
  existing self-report breakers (`consecutive_dirty_zero` et al.). Opt-in — a
  caller that passes no liveness verdict gets today's behavior unchanged
  (the conservative-default precedent).
- **3b.** *(observability)* Surface a `SPINNING`/`STALLED` run as an
  operator-decision row (`project-dos-operator-decisions-queue` — the queue is
  already a projection over multiple sources; liveness is a new source). The
  resolver-kind is `ORACLE` (LVN is deterministic), with an emit-and-exit action
  (e.g. "kill run RID-XXXX" / "let it ride").
  **SHIPPED (live-ops form), 2026-06-01:** `dos top` (`src/dos/dispatch_top.py`)
  realizes the *cross-session live* half of this — each held lane's status chip
  IS `liveness.classify` (🟢 ADVANCING / 🟡 SPINNING / 🔴 STALLED), so a spinning
  lane is visible at a glance on the watchdog screen. (The *queue-row* form — a
  SPINNING run as a `dos decisions` entry with a kill/let-it-ride action — is
  still the remaining 3b work; `dos top` is the dashboard, the queue row is the
  actionable nudge.)
- **3c.** *(policy + rails)* Make `grace_ms`/`spin_ms` declarable per-workspace
  (a `dos.toml [liveness]` block, read back through `SubstrateConfig` like
  `[lanes]`/`[stamp]`/`[reasons]` — the closed-config-as-data pattern). Render the
  verdict + evidence through the shared `--output json` renderer (Axis-4). Add a
  HACKING.md axis row for the liveness policy if a new axis is warranted, or fold
  it under the existing config-as-data narrative. `dos doctor` reports the active
  liveness windows (the "see what governs your kernel" completeness rail, like the
  active reasons/predicates).

**Litmus (Phase 3):**
- `test_loop_stops_on_spinning` — a `LoopState` carrying a `SPINNING` liveness
  verdict yields `action="stop", stop_reason=SPINNING`; without it, behavior is
  byte-identical to today (the behavior-preservation proof).
- `test_liveness_policy_from_toml` — `[liveness] spin_ms = …` in `dos.toml` is
  read back and changes the verdict boundary.
- `test_liveness_output_json` — `dos liveness --output json` emits verdict +
  driving evidence through the shared renderer.
- `dos doctor` names the active liveness windows.

---

## Out of scope (explicitly)

- **A monitor / watchdog / polling thread.** LVN is a *verdict you ask for*, the
  same as `verify`/`arbitrate` — pull, not push. A daemon that periodically calls
  it is a *consumer* a host can build (job's dispatch-loop, an MCP host); it is not
  the kernel. The kernel ships the question-answerer, not the scheduler that asks.
- **Judging the *quality* of progress.** LVN says bytes moved, not that they moved
  *well*. "Is this good work / the right approach / a confused agent" is an
  advisory judge (`llm_judge.py`), forever driver-layer. Re-litigating this would
  collapse the distrust-state / distrust-judgment line that keeps the kernel
  domain-free.
- **Killing a run.** LVN never terminates a process or refuses a lease. It reports;
  a consumer decides. (A `LivenessPredicate` over ADM's conjunctive seam — refuse a
  *new* lease to an already-spinning process — is a possible *separate* opt-in
  driver predicate, not LVN, and not in this plan.)
- **Per-keystroke / sub-second liveness.** LVN's resolution is commits + journal
  events + heartbeats — the granularity the spine already records (minutes). A
  finer signal would need a new evidence source, which the no-new-subsystem
  discipline rules out for now.
- **Cross-host fleet liveness.** Single-host, like the lane journal (the DLO
  non-goal). A cross-host roll-up is a projection a future driver builds over many
  hosts' verdicts, not a kernel concern.

## Why this is the right next syscall

It is the **temporal completion of the referee**. The three shipped syscalls
adjudicate *finished or instantaneous* state: did it ship, why is it blocked, is
the lane free. None covers the *interval* — the minutes an agent is supposedly
working — which is exactly the interval where the operator is forced back into
reading output and guessing, the cost `project-dos-real-use-value` names as the #1
thing DOS removed. LVN closes that: the same evidence-over-narrative discipline,
pointed at "is it moving?", built almost entirely from spine machinery that
already exists (`run_id` clock, `timeline` git-delta, `lane_journal` heartbeat).
Small primitive, large buildable space above it (self-stopping loops, fleet spin
dashboards, decision-queue rows) — the `primitives-not-features` thesis, and the
first new entry in the distrust-primitive map to graduate from design to a syscall.

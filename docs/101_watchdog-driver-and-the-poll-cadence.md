# The watchdog driver — putting `liveness()` on a cadence (the §2.1 budget-late answer)

> **DOS now mints the in-flight verdict (`liveness()`) and the self-stop seam
> (`StopReason.SPINNING`) and the stop-recorder (`halt`). What it still lacks is the
> thing that *asks the question on a timer*: an independent poller that wakes every
> N seconds, classifies each tracked run, and — when a run is SPINNING or hung past
> its budget — records the stop decision and proposes the command. That is the
> literal "ongoing agent supervisor", and per [`99 §6`](99_runtime-validation-and-the-actuation-boundary.md)
> it is a **driver**, not a kernel change. This note specifies it. It is the build
> that directly answers the single most expensive incident in the historical record
> ([`99 §2.1`](99_runtime-validation-and-the-actuation-boundary.md): eight jobs hung
> ~4.4 h each because the budget fired 2.2 h late — the supervisor meant to stop the
> stuck thing was itself asleep inside the same stuck loop).**

A spec note in the family of [`99`](99_runtime-validation-and-the-actuation-boundary.md)
(which it completes) and the supervisor-loop plan
([`184_the-supervisor-loop-plan.md`](184_the-supervisor-loop-plan.md)). It builds
**one driver module** (`src/dos/drivers/watchdog.py`) and **one read-only seam
extension** (a `LIVENESS` source in `dos.decisions`). It touches **no kernel
module's logic** — the watchdog is assembly over `liveness.classify`, the
`cli` liveness-evidence boundary, and `lane_lease.halt`, all already on master.

---

## 1. Why this is a separate driver from `supervise()` — two axes, not one

DOS already ships a long-lived watchdog: `drivers/supervisor.py`, the enactor of
`supervise()`. It is tempting to think the work here is "make the supervisor also
fire halts." It is not, and conflating them would muddy the cleanest line in the
runtime story. The two operate on **different axes**:

| | `drivers/supervisor.py` (shipped) | `drivers/watchdog.py` (this note) |
|---|---|---|
| **Axis** | *Population* — is the roster full? | *Per-run health* — is **this** run moving? |
| **Verdict** | `supervise()` → SPAWN / REAP / FLAG / HOLD | `liveness.classify()` → ADVANCING / SPINNING / STALLED |
| **Subject** | a *lane roster* and its target count | a *set of tracked runs*, each `(run_id, start_sha, …)` |
| **Acts on** | a STALLED *lane* → SCAVENGE its lease + refill | a SPINNING/hung *run* → record `OP_HALT` + propose a stop command |
| **The dead case** | reaps a STALLED lease so the lane refills | the run is hung but *still holds its lease and its pid* — the lease isn't the problem, the **process** is |

The supervisor's REAP is about freeing a *lane* so a replacement worker can take
it; it scavenges the journal lease and moves on. It deliberately does **nothing**
about a SPINNING worker beyond `FLAG` — "the supervisor flags a spinner, it never
auto-reaps it" (`supervise.py`), because a spinner still holds a live lease and
the supervisor has no standing to halt a peer's control flow
([`99 §3.1`](99_runtime-validation-and-the-actuation-boundary.md): FLAG-a-neighbor
vs stop-yourself). The watchdog is the missing actor for exactly that residue: it
is the operator's delegated agent, watching a *named set of runs it was told to
watch*, with standing (because the operator gave it standing) to **record a stop
decision and propose the kill** for a run that is spinning or hung past its budget.

The §2.1 incident is precisely a per-run-health failure, not a population one: the
roster was *full* (eight workers alive), the supervisor (had one been running)
would have happily reported AT_TARGET — every lane held a live lease. The failure
was that each of those eight runs was **hung**, and the timer meant to notice was
asleep *in the same process as the thing it was timing*. An independent poller in
its own process, asking `liveness` on a cadence, is structurally immune to that:
its clock keeps ticking no matter what the watched runs do, because it is not
inside their loop. **That structural independence is the whole point** — it is why
the watchdog must be a separate long-lived process, not a callback the dispatch
loop invokes on itself (the thing that already failed).

## 2. What the watchdog watches — the tracked-run set

`liveness.classify` needs, per run: `run_started_ms` (decoded from the run-id),
`commits_since_start` (needs a **start SHA**), and the journal fold (needs the
`(loop_ts, lane)` lease identity). So a run is watchable only if the watchdog
knows that tuple. The watchdog therefore watches a **declared set of tracked
runs**, each a small record:

```python
@dataclass(frozen=True)
class TrackedRun:
    run_id: str                 # the CID token — decodes run_started_ms (the clock is free)
    start_sha: str              # the git SHA the run started at — the commit-delta floor
    lane: str = ""              # the lease's lane (for the journal rung + halt correlation)
    loop_ts: str = ""           # the lease's (loop_ts, lane) identity key
    handle: str = ""            # the OPAQUE stop handle (a pid / container id / task token)
    budget_ms: int | None = None  # wall-clock budget; STALLED past it → halt. None = no budget.
    stop_command: str = ""      # the host-supplied stop command echoed in the OP_HALT proposal
```

Two ways the set gets populated, both host-supplied (the watchdog mints nothing):

- **Explicit** — the operator passes `--track run_id:start_sha:lane:loop_ts:handle`
  (repeatable), or a JSON file of `TrackedRun`s. The simplest, and enough for the
  §2.1 case (you know which eight jobs you launched).
- **Discovered** — the watchdog folds the lane journal's live leases
  (`lane_lease.live_leases`) into tracked runs, deriving `lane`/`loop_ts`/`handle`
  (`pid`) from each live lease. The gap: a journal lease records **no start SHA**
  (the honest commit-rung floor `_supervise_evidence` already lives with — it
  passes `commits_since_start=0`). So a discovered run is judged on the **journal
  rung alone** (heartbeat age + lease-work events), never the commit rung. That is
  strictly weaker but never *wrong*: it can reach SPINNING/STALLED from a stale
  beat, it just can't use commits as an ADVANCING signal. A host that wants the
  commit rung passes the start SHA explicitly. (This mirrors the supervisor's own
  "a live lease records no start SHA, so the commit rung is 0" stance — one honest
  floor, two consumers.)

The discovered mode is what makes the watchdog *also* a drop-in answer to "watch
whatever is running right now" without the operator enumerating runs — the same
ergonomic `dos top` gives the dashboard, here wired to an actuator.

## 3. The verdict-to-action map (the auto-halt-record default)

Each tick, for each tracked run, the watchdog gathers evidence at the boundary
(reusing `cli`'s liveness helpers — §5) and calls `liveness.classify`. The
disposition:

| Liveness verdict | Watchdog action |
|---|---|
| **ADVANCING** | nothing — the run is moving. (Drop it from any prior "halt proposed" memory: it recovered.) |
| **SPINNING** | **record `OP_HALT`** (via `lane_lease.halt`, which appends the intent and echoes the `stop_command`) — alive but landing zero forward delta is the textbook hung-but-narrating shape; the operator delegated the watchdog to catch exactly this. |
| **STALLED**, run age < `budget_ms` | nothing yet — a young run that simply hasn't committed/beaten is not yet a problem (the `grace_ms` false-positive guard, lifted to the budget axis). |
| **STALLED**, run age ≥ `budget_ms` (or `budget_ms` is `None`) | **record `OP_HALT`** — this is the §2.1 case: no heartbeat, no commits, past the wall-clock budget. The run is dead or hung and the budget says stop. |

This is the **auto-halt-record + emit-command** disposition (the operator's chosen
default). "Auto" means the watchdog itself calls `lane_lease.halt` to *record the
`OP_HALT` and emit the host-supplied stop command* — so the proposed stop is one
paste away, sitting in the journal and in the decisions queue. It does **not** mean
the watchdog kills anything: `lane_lease.halt` is the kernel boundary verb that
records intent and proposes a command and **never signals**
([`99 §5`](99_runtime-validation-and-the-actuation-boundary.md)). The actuation
boundary holds exactly where docs/99 draws it — the watchdog (a driver) *records +
proposes*; delivering the signal is a separate, even-more-host-specific act left to
the operator (paste the command) or a further driver that consumes `OP_HALT` and
signals. The watchdog deliberately stops at the same line the supervisor stops at
(journal the decision, let a human/driver enact), one axis over.

**Idempotence — never a halt storm.** A SPINNING run stays SPINNING across many
ticks; a naive watchdog would append an `OP_HALT` every tick forever. So the
watchdog keeps a `proposed: {run_id: proposed_at_ms}` memory (the supervisor's
`launched`-set analogue) and records **at most one `OP_HALT` per run per
`repropose_ms` window** (default: long — a halt proposal is not something you want
to spam). A run that flips back to ADVANCING is dropped from `proposed`, so if it
later spins again it earns a fresh proposal. This bounds the journal to one halt
record per genuine spin episode, not one per tick — the same "bound the effect to
the genuine event, not the poll rate" discipline as the supervisor's race belt.

## 4. The decisions-queue seam — surfacing the proposal to the operator

[`82` Phase-3b](82_liveness-oracle-plan.md) left the *queue-row* form of liveness
observability open: "a SPINNING run as a `dos decisions` entry with a kill /
let-it-ride action is still the remaining 3b work; `dos top` is the dashboard, the
queue row is the actionable nudge." The watchdog's `OP_HALT` records are exactly
the durable feed that row reads. So this note also closes 3b's queue half, with a
**read-only** extension to `dos.decisions` (no new store — the
[`decisions.py`](../src/dos/decisions.py) projection discipline):

- A new `DecisionKind.LIVENESS` (the fifth source), read from the lane journal's
  `OP_HALT` entries (`_from_lane_journal` already reads the journal; it gains a
  HALT branch beside its REFUSE branch). Each `OP_HALT` → one `Decision` carrying
  the run handle, lane, the proposed `command`, and the halt `reason`.
- `resolver_kind = ORACLE` — liveness is a *deterministic* verdict (`liveness`,
  like `picker_oracle`, is the ORACLE rung), so a halt proposal is oracle-sourced,
  not a human's open question. (It still *needs* a human or driver to enact, but
  the *adjudication* was mechanical — the resolver-kind axis records who *judged*,
  and an ORACLE judged this one. The operator acts via the emit-and-exit action.)
  **Consequence (accepted):** `dos decisions` default-filters to `HUMAN` ("what
  needs me"), so a halt proposal is **not** shown by the bare verb — it surfaces
  under `dos decisions --all` (`resolver=None`) and on the `dos top` dashboard.
  This keeps the resolver-kind axis honest (who *adjudicated*, not who must *act*);
  the cost is that the bare queue hides the proposal. (Were "who must act" the axis,
  this would be HUMAN like `SOAK_GATE`; we keep it ORACLE — the operator's call,
  recorded here.)
- `next_steps` for a `LIVENESS` decision offers the proposed `command` as the
  primary emit-and-exit action (paste-to-stop), plus a "let it ride" no-op and the
  `dos man` for the verdict. The TUI prints the command and exits — the locked
  read-only-router model; the queue never signals a process itself, identical to
  how it never forces a lane itself.

This keeps the kill decision where docs/99 puts it: the queue *proposes*, the
operator *enacts*. The watchdog automates the *detect → record → propose* arc that
a human previously did by watching output; the human keeps the *enact* call.

## 5. Shape and home (the boundary-reuse discipline)

The watchdog is a driver (layer 4) and obeys the one-way arrow: it `import dos`;
no kernel module imports it (the `import dos.drivers` litmus,
[`tests/test_drivers_supervisor.py`](../tests/test_drivers_supervisor.py)
restated). Its structure mirrors `drivers/supervisor.py` exactly — a near-pure
plan step, an effectful tick, a cadence loop — so the same hermetic test idiom
applies:

- `assess_run(cfg, tracked, *, now_ms) -> liveness.LivenessVerdict` — **near-pure**
  (the testable seam): it gathers this run's evidence by calling the SAME boundary
  helpers `cmd_liveness` uses (`cli._git_delta_count` for the commit rung,
  `cli._journal_delta` for the journal rung, `run_id.ts_ms_of` for the start), then
  returns `liveness.classify(...)`. No effects. *Reuse, do not re-implement* — the
  LVN-1b discipline ("LVN must not re-implement the timeline's git rung") applied
  to the driver: the watchdog reads the commit/journal deltas through the exact
  same code `dos liveness` does, so the watchdog's verdict can never drift from the
  CLI's. (A `consumer→consumer` import of `cli`, blessed exactly as
  `drivers/supervisor.plan_tick` imports `cli._supervise_evidence`.)
- `tick(cfg, tracked_runs, *, now_ms, proposed, repropose_ms, halt=lane_lease.halt)
  -> (verdicts, WatchActions)` — calls `assess_run` per run, applies the §3 map,
  and for each run that warrants it calls `halt(cfg, handle=…, lane=…, loop_ts=…,
  reason=…, command=tracked.stop_command)` (the kernel boundary verb — records
  `OP_HALT`, proposes the command, signals nothing). Mutates `proposed` in place
  (records each proposal's ms; drops a run that recovered to ADVANCING). `halt` is
  injectable so a test asserts the proposal **without** writing a journal, and so a
  test can monkeypatch `os.kill`/`subprocess` to **raise** and prove the watchdog
  never calls them (the "proposes, does not signal" proof, lifted from
  `test_halt_proposes_does_not_signal`). Returns a `WatchActions` audit record
  (`proposed_halts`, `advancing`, `spinning`, `stalled_within_budget`).
- `run(config=None, *, tracked_runs, interval, max_ticks=None, repropose_ms,
  clock_ms=None, sleep=time.sleep, halt=lane_lease.halt) -> int` — the cadence
  loop: each tick gathers + assesses + records, then sleeps `interval` (long — a
  watchdog, not a busy-poll, default 300 s like the supervisor). `clock_ms`/`sleep`
  injectable for deterministic tests; `KeyboardInterrupt` → clean 0.

A `dos watch` CLI verb (a thin `cmd_watch` beside `cmd_loop`) drives the driver:
`--track …` (repeatable) for the explicit set, `--discover` to fold live leases,
`--interval`, `--budget-ms`, `--repropose-ms`, `--now-ms` (injectable boundary
clock), `--output text|json`. Exit 0 always (like `cmd_loop`: the output is an
effect record carried in stdout / the journal, not a verdict the shell branches on).

**The bulkhead — `dos watch` resolves the driver BY NAME, never a static import.**
`dos watch` is the one CLI verb that *drives an out-of-kernel actor*, the way
`dos judge` drives the LLM judge. The kernel's one-way arrow forbids a kernel
module (`cli.py` is layer-3) from *importing* a driver — pinned by
[`tests/test_vendor_agnostic_kernel.py::test_no_kernel_module_imports_a_driver`](../tests/test_vendor_agnostic_kernel.py),
which AST-walks every `src/dos/*.py` (outside `drivers/`) and forbids a static
`import dos.drivers...`. So `cmd_watch` resolves `dos.drivers.watchdog` by name via
`importlib.import_module` at the call boundary (`_load_watchdog()` — the same
mechanism `_resolve_driver_config` uses for host policy packs and the `dos.judges`
seam uses for adjudicators), **not** `from dos.drivers import watchdog`. The
distinction is real, not a lint-dodge: a static import makes the driver a
compile/package-time dependency of the kernel; name-resolution at the boundary
keeps it runtime-optional (the kernel imports and packages without the driver; the
verb fails gracefully if it is absent). This is why the verb can live in `cli.py`
at all without inverting the arrow.

## 6. The disciplines this must honor (the litmus, restated for the watchdog)

- **No kernel change, no kernel import of the driver.** The watchdog lives in
  `drivers/`; `grep` for `import dos.drivers.watchdog` under `src/dos/*.py`
  (non-driver) returns nothing. Pinned by a layering test, the
  `test_driver_imports_kernel_not_the_other_way` shape.
- **The kernel still kills nothing.** The watchdog records `OP_HALT` and emits a
  command. It never calls `os.kill`/`subprocess`/`TaskStop`. The actuation boundary
  ([`99 §3`](99_runtime-validation-and-the-actuation-boundary.md)) is unchanged:
  the watchdog goes exactly as far as the kernel boundary verb lets it (record +
  propose) and no further, because *delivering* the signal needs to know what the
  handle **is** — a driver's knowledge the kernel forbids itself, and that this
  driver still declines to exercise (it stays at the propose line, leaving the
  enact to the operator or a kill-driver). Pinned by a monkeypatch-`os.kill`-raises
  test.
- **Evidence-over-narrative.** The watchdog never reads a run's self-report. Its
  only inputs are the ground-truth deltas `liveness.classify` consumes (git +
  journal + the clock). A run that *says* it is fine but landed zero commits and
  stopped beating is SPINNING/STALLED regardless of what it says — the entire LVN
  thesis, now on a timer.
- **Distrust state, never judgment.** The watchdog halts a run for *not moving*,
  never for moving *badly*. "Is this good work" is an advisory judge's call
  (`drivers/llm_judge`), forever a different driver. The watchdog's halt reason is
  always a mechanical liveness fact (SPINNING / STALLED-past-budget), never a
  quality verdict.
- **No-budget-needed degrade.** A `TrackedRun` with `budget_ms=None` still gets a
  verdict every tick; STALLED with no budget is treated as past-budget (a hung run
  with no declared budget is still hung). A run with no `start_sha` (discovered)
  degrades to the journal rung. A run with no `stop_command` still records the
  `OP_HALT` (the proposal carries an empty command — the operator supplies the kill
  by hand). Every input is optional except the run-id; the watchdog never crashes
  on a thin tracked run (the no-plan discipline, applied per-run).
- **Single-host.** Like the lane journal and the supervisor, the watchdog is
  single-host (the DLO non-goal). Cross-host roll-up is a future projection over
  many hosts' watchdogs, not this.

## 7. Litmus (the acceptance set)

Driver (`tests/test_drivers_watchdog.py`, the supervisor-driver test idiom —
monkeypatch the boundary, inject a recorder for `halt`):

- `test_spinning_run_records_a_halt_proposal` — a tracked run whose evidence
  classifies SPINNING → exactly one `OP_HALT` recorded (or `halt` called once),
  carrying the run's handle + the host `stop_command`.
- `test_advancing_run_records_nothing` — an ADVANCING run → no `halt` call, empty
  `WatchActions.proposed_halts`.
- `test_stalled_within_budget_records_nothing` vs
  `test_stalled_past_budget_records_a_halt` — the budget split, separated only by
  the run's age vs `budget_ms` on frozen evidence.
- `test_halt_proposal_is_idempotent_within_window` — a run SPINNING across three
  ticks within `repropose_ms` → exactly **one** `OP_HALT`, not three (the
  `proposed` memory).
- `test_recovered_run_can_be_reproposed` — SPINNING → (proposal) → ADVANCING
  (dropped from `proposed`) → SPINNING again → a second proposal is allowed.
- `test_watchdog_proposes_does_not_signal` — monkeypatch `os.kill` **and**
  `subprocess.Popen` to raise; a full tick over a SPINNING run still succeeds and
  records the `OP_HALT` (proving the watchdog never calls them — the actuation-
  boundary proof, lifted from `test_halt_proposes_does_not_signal`).
- `test_run_is_bounded_by_max_ticks` — `run(..., max_ticks=3, clock_ms=…,
  sleep=recorder)` ticks exactly 3 times, sleeps 2 (no real sleep, no real clock).
- `test_assess_run_reuses_cli_boundary` — `assess_run` calls
  `cli._git_delta_count` / `cli._journal_delta` (monkeypatch them to sentinels and
  assert they were consulted) — the no-drift / reuse proof.
- `test_watchdog_resolves_via_config_not_file` — the `OP_HALT` lands at the
  configured journal path; nothing is written under the package tree (the layering
  path discipline, `_journal_path(config)` everywhere).
- `test_kernel_does_not_import_watchdog` — `ast`-parse the non-driver kernel
  modules; none imports `dos.drivers.watchdog` (the one-way-arrow litmus).

Decisions seam (extend `tests/test_decisions.py`):

- `test_op_halt_surfaces_as_liveness_decision` — an `OP_HALT` on the journal →
  one `Decision(kind=LIVENESS, resolver_kind=ORACLE)` carrying the handle + the
  proposed command; its `next_steps` offers the command as an emit-and-exit action.
- `test_decisions_queue_still_green_without_halts` — the behavior-preservation
  proof: a journal with no `OP_HALT` yields exactly today's decision set (the new
  source is purely additive).

## 8. Non-goals (what this note explicitly does NOT do)

- **It does not deliver a kill.** Still record + propose. (§6.)
- **It does not move the actuation boundary.** The watchdog is the *scheduler that
  asks* + *the recorder of the proposal*; the *enactment* stays a human's paste or
  a separate kill-driver, exactly the [`99 §3`](99_runtime-validation-and-the-actuation-boundary.md)
  layering.
- **It does not solve the sub-commit blind spot**
  ([`99 §2.3`/`§6`](99_runtime-validation-and-the-actuation-boundary.md)). The
  watchdog's resolution is commits + journal events + heartbeats — minutes, the
  granularity the spine records. The mid-step self-deception failure (the agent
  that logs `still_broken=[]` while the DOM shows the field empty) lives below a
  commit and is the genuinely-open frontier docs/99 §6 leaves for real design. The
  watchdog is the last piece of the *interval* verdict's loop; the *sub-interval*
  is the next question, and it is not this.
- **It is not a kernel module.** If a future host wants the watchdog's cadence/
  budget/discovery rules tuned, that is an edit to `drivers/watchdog.py` (or a new
  driver), never to a `src/dos/*.py` kernel module. The kernel ships the
  question-answerer (`liveness`), the stop-recorder (`halt`), and the queue
  projection; the timer that asks is — and stays — a driver's.

---

## References

- [`99_runtime-validation-and-the-actuation-boundary.md`](99_runtime-validation-and-the-actuation-boundary.md)
  — the actuation boundary this honors; §2.1 (the budget-late incident this
  answers), §6 (the watchdog named as a deferred driver; the sub-commit frontier
  left open).
- [`82_liveness-oracle-plan.md`](82_liveness-oracle-plan.md) — `liveness.classify`,
  the verdict the watchdog puts on a timer; Phase 3b (the decisions-queue row this
  closes).
- [`src/dos/drivers/supervisor.py`](../src/dos/drivers/supervisor.py) — the
  structural template (plan/tick/run, injectable clock/sleep, the journal-write
  driver precedent, the layering litmus).
- [`src/dos/lane_lease.py`](../src/dos/lane_lease.py) — `halt()`, the record +
  propose boundary verb the watchdog fires; the "never signals" guarantee.
- [`src/dos/decisions.py`](../src/dos/decisions.py) — the read-only operator-queue
  projection the `LIVENESS` source extends.
- [`src/dos/cli.py`](../src/dos/cli.py) — `_git_delta_count` / `_journal_delta`,
  the liveness-evidence boundary helpers the watchdog reuses (the no-drift rule).

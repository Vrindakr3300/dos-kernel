# 210 — The `[supervise]` config seam: the always-on loop becomes declarable

> **Status:** SHIPPED (2026-06-07). The supervisor's standing population policy
> (`SupervisePolicy`) is now read back from `dos.toml [supervise]` and threaded
> through `SubstrateConfig.supervise` into BOTH the `dos loop` emitter and the
> long-lived watchdog driver. Before this, the population *target* was reachable
> only as the `dos loop --target` flag and the two policy booleans
> (`count_spinning_as_alive`, `reap_stalled`) were not reachable from the operator
> surface at all — the CLI hardcoded `SupervisePolicy(target=target)`. This is the
> config-seam piece of the supervisor's Phase 3 (`docs/99`'s sibling).
>
> **Update (2026-06-07, same day):** the next stage shipped too — **acting-on-spin**
> (`FLAG → PROPOSE_HALT`, advisory; `spin_halt_after_ms` policy knob) — and the
> third direction, **value-aware spawn ranking, was investigated and DECLINED** as a
> measured no-op, replaced by a config-time roster-order lint. See "The next stage"
> below.

## Why this is the foundational piece of "always-on as a separate program"

The supervisor (`dos.supervise` verdict + `dos.drivers.supervisor` watchdog) is
DOS's init / PID-1: a separate program that keeps a target number of dispatch-loop
workers alive across the lane roster (SPAWN the free lanes, REAP the dead, FLAG the
spinning). For it to be a *standing* program — one an operator starts once and
leaves running — its policy has to live where standing configuration lives: the
workspace's `dos.toml`, next to the lane roster the population is filled against.

A flag (`--target 3`) is the wrong home for a standing policy. It has to be
re-typed on every invocation, the long-lived driver has no flag to read, and two
of the three knobs (whether a spinning worker counts as "up", whether a dead one
is reaped) had no flag at all — they were dead parameters, settable only from
Python. So the supervisor could *detect* the right things but an operator could
not *tune* them. This seam closes that: the three knobs become one declaration
that the emitter and the watchdog both read.

## What a knob means (define each once)

`[supervise]` carries the three fields of `SupervisePolicy`:

| Key | Default | What it decides |
|---|---|---|
| `target` | `1` | The desired number of live workers across the roster. The supervisor fills up to it (bounded by the disjointness ceiling) and flags above it. |
| `count_spinning_as_alive` | `true` | Whether a SPINNING worker (alive, fresh heartbeat, but landing no forward git/journal delta) counts toward the live population. `true` because a spinner still *holds its lease* — re-spawning its lane would just duplicate a worker. (It is still FLAGged either way; this only changes the arithmetic.) |
| `reap_stalled` | `true` | Whether a STALLED worker (no fresh heartbeat, no commits — dead or hung) yields a REAP plan that releases its lease. Set `false` to make the supervisor report-only — it names the dead lane but proposes no scavenge. |

Example:

```toml
[supervise]
target = 3            # keep three dispatch-loops alive
reap_stalled = true   # scavenge the dead so their lanes refill
# count_spinning_as_alive omitted → inherits the default (true)
```

## The shape — the same mechanism/policy split every other seam draws

This is the `[cooldown]` / `[stamp]` pattern, restated for the population axis
(`HACKING.md`'s closed-enum-as-data law):

- **Mechanism stays in the kernel.** `supervise.supervise(evidence, policy)` is
  unchanged — a pure verdict, frozen evidence in, typed plan out. It already *took*
  a `SupervisePolicy`; it never cared where the policy came from.
- **Policy becomes data.** `supervise.policy_from_table` / `supervise.load_from_toml`
  build the policy from the `[supervise]` table (an unknown key raises — a typo'd
  knob is a loud error, not a silent no-op; a TOML bool for `target` is rejected so
  `target = true` cannot silently mean 1). `SubstrateConfig.supervise` carries it.
- **The boundary layers it.** `config.load_workspace_config` folds `[supervise]` in
  with the same `_layer` helper as every other table: a present-but-malformed table
  **warns and keeps the base** (the supervisor is advisory/effect — even the
  driver's reap is idempotent — so a broken policy degrades to the safe default
  rather than wedging the roster), and an absent table inherits the generic default.

## Two consumers, one declaration

The point of the seam is that the *hand-run emitter* and the *standing watchdog*
can never diverge on policy:

- **`dos loop`** (the emitter) reads `cfg.supervise` as its policy base. `--target`
  now defaults to `None`; when omitted the config target stands, when given it
  overrides **only** the target for that one run (the two booleans keep their
  declared values). So `dos loop` with no flag emits the standing plan, and
  `dos loop --target 1` is a one-off smaller population.
- **`dos.drivers.supervisor.run`** (the watchdog) defaults its target to
  `cfg.supervise.target` when none is passed, and `plan_tick` builds the policy from
  `cfg.supervise` (target overridden by the effective target) — so the booleans
  always come from the one declaration. A watchdog launched with no explicit
  population keeps the workspace's declared one.

`dos doctor` reports the active policy on both surfaces — a `supervisor target`
text row (`count_spinning_as_alive` / `reap_stalled` shown) and a `supervise` key
in `--json` — so an operator or skill reads the standing population without
re-parsing `dos.toml`.

## The next stage: acting on a spin (SHIPPED) — and why ranking was declined

After this seam, the two documented remaining Phase-3 directions were value-aware
spawn ranking and acting-on-spin. A 12-agent investigation (run before writing any
code, the "probe before building" discipline) **declined spawn ranking and built
acting-on-spin.** The investigation is the load-bearing part — five of six
load-bearing premises for ranking were refuted:

**Value-aware spawn ranking — DECLINED (a measured no-op, replaced by a config lint).**
The spawn walk is a *greedy disjointness walk*, not interval-scheduling: its order
changes which lanes fill only under a triple-rare condition — overlapping CONCURRENT
lanes AND target>admissible AND fewer spawn slots than candidates — which is <1% of
spawn decisions and is itself a roster config *smell*. In the designed
disjoint-concurrent norm (`docs/89`), every free lane spawns regardless of order, so
ranking is a no-op. Worse, the signal a ranker would need does not exist cleanly:
`enumerate` residual-per-lane is a *category error* (`enumerate_units` consumes one
plan-doc's bytes; a lane is a glob-region; no lane→plan map exists), and a journal
"starvation age" is *destroyed by compaction* (`lane_journal.compact()` discards
RELEASE/SCAVENGE history and the checkpoint carries no timestamp). And DOS already
ships exactly one value-ordering seam — the arbiter's `rank_key` (`docs/91`) — so a
second, independently-invented supervisor ranker would be debt, not a feature. The
honest fix for the rare order-sensitive case is therefore a **config-time lint**, not
a runtime ranker: `dos doctor --check` now flags overlapping CONCURRENT lane pairs
(`supervise.overlapping_concurrent_lanes`), so an operator fixes the order-sensitivity
at its source (declare disjoint lanes, or mark one exclusive) instead of papering over
it at runtime.

**Acting on a spin — SHIPPED (`FLAG → PROPOSE_HALT`).** The supervisor's SPINNING
FLAG already existed and was already collected by the driver, then went *nowhere* —
a documented unclosed loop (`docs/90 §5`). The build escalates that existing typed
signal, it does not add a new detector:

- a new `Disposition.PROPOSE_HALT` and a SEPARATE `SuperviseVerdict.proposed_halt`
  tuple (never folded into `reap`, so `reap_stalled` semantics and the spawn-refill
  coupling stay byte-identical, and a driver's reap code can never act on a mere
  proposal);
- `LaneLiveness.spinning_age_ms`, populated at the `_supervise_evidence` boundary
  from the *same* heartbeat age `liveness.classify` already consumed to call the lane
  SPINNING — **zero new I/O**, the arbiter purity rule;
- `SupervisePolicy.spin_halt_after_ms` (`dos.toml [supervise]`, or the ergonomic
  `spin_halt_after_minutes`), default **None = off** — the advisory-only default that
  reproduces today's pure-FLAG behaviour byte-for-byte (the `reap_stalled=False`
  posture). When set, a spinner whose `spinning_age_ms ≥ spin_halt_after_ms` ALSO
  yields a PROPOSE_HALT.

The **soundness floor** is preserved trivially: PROPOSE_HALT never touches the spawn
walk, never appends to `spawn_candidates`, never releases a held region (unlike REAP),
never changes the population/admissible math — so the disjoint-by-construction spawn
plan is *byte-identical* whether a spinner is proposed-halted or not (pinned by a test).
And it stays on the `docs/99` actuation floor (PDP, not PEP): the supervisor *proposes*
stopping a still-alive worker; the kernel and the driver never enact it (the driver
writes no `OP_RELEASE`/`OP_SCAVENGE` and kills no process — pinned by a test); the
operator enacts with an explicit `dos halt`. The line between REAP and PROPOSE_HALT is
*dead vs alive*: a reap frees a confirmed-dead lease (safe to enact — a second SIGTERM
to a dead pid is a no-op); a proposed halt only proposes stopping a *live* worker, so
the kernel must not act on it (stopping a live foreign process is the domain knowledge
the kernel deliberately lacks, `docs/99 §3`).

## Files

- `src/dos/supervise.py` — `[supervise]` seam (`to_dict`/`policy_from_table`/
  `load_from_toml`); the acting-on-spin tier (`Disposition.PROPOSE_HALT`,
  `SuperviseVerdict.proposed_halt`, `LaneLiveness.spinning_age_ms`,
  `SupervisePolicy.spin_halt_after_ms`, the SPINNING-branch escalation); the
  roster-order lint (`overlapping_concurrent_lanes`).
- `src/dos/config.py` — `SubstrateConfig.supervise` field + the `[supervise]`
  `_layer` block in `load_workspace_config`.
- `src/dos/cli.py` — `cmd_loop` reads `cfg.supervise` (with `--target` as a
  one-off override) and emits the `propose-halt` rows; `_supervise_evidence`
  populates `spinning_age_ms` from the boundary heartbeat age; `dos doctor` reports
  the policy (incl. `spin_halt_after`) and runs the roster-order lint under `--check`.
- `src/dos/drivers/supervisor.py` — `plan_tick` builds the policy from
  `cfg.supervise`; `run` defaults its target to the config target; `tick` surfaces
  `proposed_halt` into `TickActions.proposed_halts` (advisory — no kill, no release).
- `tests/test_supervise.py` / `tests/test_cli_loop.py` / `tests/test_drivers_supervisor.py`
  — the seam tests; the acting-on-spin tests (escalation, fail-quiet on absent
  evidence, the soundness-floor invariance, the boundary wiring, the driver
  no-release pin); the roster-order lint tests.

# SUP — The supervisor loop (the init/PID-1 of a DOS fleet)

> **Status:** 🚧 **Phases 1–2 shipped** (kernel verdict + emit-only `dos loop` +
> watchdog driver + skill; landed on `master` 2026-06-02, after a rebase + the
> doc renumber from `88`). Phase 3 (value-aware spawn ranking, acting-on-spin, a
> `[supervise]` policy seam) is still design.
>
> **DOS has a verdict for one in-flight run — `liveness()` says ADVANCING /
> SPINNING / STALLED ([`82`](82_liveness-oracle-plan.md)). It has no verdict for
> the *population*: "are N workers actually alive across the lane roster, and what
> should change to get there?" This note specs `supervise()` — `liveness`'s
> population-axis sibling — and the thin emit-only `dos loop` verb + watchdog
> driver that put it on a cadence. The supervisor is the fleet's **init / PID-1**:
> it reconciles the observed worker population toward a target the way `init`
> keeps services up, by counting the *leases* (the lane region-locks), never by
> trusting a worker's report that it is "still working."**

A phased plan in the form of [`82`](82_liveness-oracle-plan.md) /
[`86`](86_the-typed-verdict-surface.md): small, separately-testable slices, each
green before the next.

## The shape, in one minute

```text
                 ┌─────────────────── dos loop (boundary, EMIT-ONLY) ──────────────────┐
  lane journal ──┤  replay → live leases   ┐                                            │
  (the WAL)      │  liveness.classify each ├─► supervise(ev, policy)  ──►  prints the    │
  git deltas  ───┤  _tree disjointness     ┘     (PURE verdict)            spawn/reap/   │
  cfg.lanes   ───┘                                                         flag plan     │
                 └──────────────────────────────────────────────────────────────────────┘
                                                   │  (no Popen, no journal write)
                                                   ▼
                 ┌──────────── drivers/supervisor.py (the watchdog, ACTS) ─────────────┐
                 │  tick(): gather → supervise() → Popen each SPAWN, scavenge each REAP │
                 │  surface each FLAG; launched-set→pending belt bounds double-spawn    │
                 └──────────────────────────────────────────────────────────────────────┘
```

`dos loop --target 3` on the generic `main`/`global` roster prints
`SUPERVISE TARGET_UNREACHABLE: alive 0/3, admissible 1` and names the fix (declare
disjoint concurrent lanes); with a 3-disjoint-lane `dos.toml` it prints `FILLING`
and three `spawn` command lines. **The verb emits; it never launches a worker or
writes the journal** — that is the driver's job.

The one-line thesis: **keeping N dispatch-loops alive is a pure per-tick
reconcile verdict over the lane journal + per-lane liveness — so the kernel ships
a pure `supervise()` and an emit-only `dos loop`, and the long-lived watchdog
(the only thing that `Popen`s and writes the journal) is a driver, exactly the
kernel/driver split [`82`](82_liveness-oracle-plan.md) drew for the verdict vs.
its monitor.**

---

## 0. What exists today (verified against the live code)

Every input the supervisor needs already ships; `supervise()` *adjudicates* them,
it adds no new evidence source — the same "mostly assembly" property that made
[`82`](82_liveness-oracle-plan.md) the right next syscall:

- **The lane journal + replay → the live-lease set.** `lane_journal.read_all()` +
  `lane_journal.replay()` fold the WAL into the currently-held leases (each a dict
  carrying `lane`, `loop_ts`, `acquired_at`, `heartbeat_at`, `pid`). That is the
  ground-truth population count — *which lanes are held right now* — read from the
  durable record, never from a worker's self-report.
- **Per-lane liveness.** `liveness.classify(ProgressEvidence, policy)` already
  decides ADVANCING / SPINNING / STALLED for *one* run from git + journal deltas
  ([`82`](82_liveness-oracle-plan.md), Phases 1–2 shipped). The supervisor runs it
  once per held lease at the boundary and freezes the verdict onto its evidence.
  Crucially the heartbeat age comes from the journal entry's own append-ts
  (`journal_delta.newest_heartbeat_age_ms`), not the copy-prone self-reported
  `heartbeat_at` — the LVN Phase-2 integrity property, carried into the population.
- **The region-lock algebra.** `_tree.lane_trees_disjoint(tree_a, tree_b)`
  (`_tree.py:35`) is the pairwise-disjointness test — conservative by design (an
  empty *or* universal/leading-glob tree is treated as **not** disjoint). This is
  what tells the supervisor how many concurrent workers a roster can *physically*
  hold.
- **The lane taxonomy.** `cfg.lanes` (a `LaneTaxonomy`) gives the roster:
  `cfg.lanes.tree_for(lane)`, `cfg.lanes.is_exclusive(lane)`,
  `cfg.lanes.is_concurrent(lane)`. The generic default is `concurrent=("main",)`,
  `exclusive=("global",)`, both with the universal tree `("**/*",)`.
- **Eviction.** `lane_journal.scavenge_entry(lease, *, reason=…, prev_holder=…)`
  builds the SCAVENGE entry that frees a dead worker's lane (replay folds
  OP_SCAVENGE identically to OP_RELEASE — eviction by `(loop_ts, lane)`), carrying
  the forensic `pid`/`prev_holder` pair.

**What is missing:** there is exactly *one* dispatch loop per invocation
(`dos-dispatch-loop`, the SKP reference loop) and **no population layer above it.**
Running a fleet today is "spin up N sessions by hand and hope." Nothing counts the
leases, nothing refills a dead lane, nothing tells you the roster *cannot* hold the
N you asked for. That is the gap `supervise()` closes — turning open-loop "run N
agents" into a steerable, self-refilling population (the closed-loop-control move).

---

## 1. The soundness floor (the invariants the whole plan rides on)

The supervisor emits an *effect* plan (spawn / reap), so its floor is sharper than
a pure-belief verdict's. Four invariants, each load-bearing:

> **1. The spawn plan is disjoint by construction.** `supervise()` never proposes
> two workers on overlapping lanes, and never proposes a worker onto a region a
> live worker already holds. The spawn walk is a **region-aware greedy seeded with
> the regions of every already-alive worker** (ADVANCING / counted-SPINNING /
> pending): a FREE lane is emitted only when its tree is
> `_tree.lane_trees_disjoint` from every held region *and* every spawn already
> chosen this tick. When candidates collide with held regions it emits **fewer**
> than the headroom count — correct, the headroom was illusory.

> **2. The supervisor never reaps a healthy worker.** REAP is reserved for
> `STALLED` runs (dead/hung — no fresh heartbeat, no commits). An `OVER_TARGET`
> population is *flagged*, never reaped: choosing which healthy worker to retire is
> an operator/driver call, not a mechanical kernel one (the distrust-state /
> distrust-judgment line). A mechanical "kill one to hit the number" would kill
> *forward progress* to satisfy a count — exactly the category error the kernel
> refuses.

> **3. The worker's own `arbitrate` at Step 0 is the authoritative gate.** The
> supervisor's pick is an **advisory hint**, an honest one (disjoint by
> construction) but not the lock. The spawned worker still calls `arbitrate(...)`
> for its lane at its own Step 0 and respects a REFUSE. So even if the supervisor
> and a manual launch race onto the same region, the *arbiter* resolves it — the
> supervisor cannot grant a lease it has no authority to grant. The
> disjoint-by-construction plan is belt; the worker's arbitrate is the buckle.

> **4. SPINNING is advisory — flagged, never auto-killed.** A SPINNING worker is
> *alive* (fresh heartbeat) but landing no forward delta. The supervisor emits a
> FLAG and, by default, still counts it as alive (it holds its lease; re-spawning
> its lane would just duplicate the worker). **Acting on a spin** — auto-stop,
> escalate, demote its rank, recycle the lane — is open research (the acting-on-spin
> question, a sibling to [`82`](82_liveness-oracle-plan.md) §3a); the kernel ships
> the signal, a driver/operator decides the act. This is `liveness`'s own rule
> (SPINNING is the verdict with no enforcement home), restated for the population.

A fifth, structural floor: the **double-spawn race guard.** Between the tick that
emits a SPAWN and the tick where that worker's ACQUIRE lands in the journal, the
lane has no live lease but a spawn is in flight. The caller marks such a lane
`pending=True`; a pending lane counts toward alive ("alive-or-coming") and occupies
its region for the disjointness walk, but is **not** a held lease and is **not** a
spawn candidate. The race is thus *bounded* to at most one extra worker per lane
per in-flight window — the supervisor analogue of an idempotent reconcile, never an
unbounded stampede.

And the **no-plan floor** ([`82`](82_liveness-oracle-plan.md)'s `test_verify_no_plan`
sibling): `supervise(SuperviseEvidence(lanes=(), target=N))` returns
`TARGET_UNREACHABLE` with `admissible=0` — it never crashes on an empty roster.

---

## 2. Phases

### Phase 1 — the pure `supervise()` verdict + `scavenge_entry` + the emit-only `dos loop` (kernel) — ✅ SHIPPED 2026-06-01

The verdict, as built (`src/dos/supervise.py`):

- **`supervise(ev, policy=DEFAULT_POLICY) -> SuperviseVerdict`** — PURE, no I/O, no
  clock, no subprocess. Imports are stdlib + `dos.liveness` (the `Liveness` enum) +
  the kernel sibling `dos._tree` (the layering litmus is "no host, no I/O", not "no
  sibling import" — `scope.py` imports `_tree` too).
- **The disposition ladder** (`class Disposition`: `SPAWN` / `REAP` / `HOLD` /
  `FLAG`), per lane: ADVANCING → HOLD (counts alive, holds its region); SPINNING →
  FLAG always + (by policy) counts alive (advisory, never reaped); STALLED → REAP +
  re-enter the spawn pool *this same tick* (kill-and-refill); FREE (`liveness is
  None`) → spawn candidate; `pending` → counts alive, holds region, emits nothing.
- **The population outcome** (`class SuperviseOutcome`: `AT_TARGET` / `FILLING` /
  `TARGET_UNREACHABLE` / `OVER_TARGET`). `TARGET_UNREACHABLE` deliberately
  dominates `OVER_TARGET` — a roster whose disjointness ceiling is below target is
  the operator's *first* lever (raise the ceiling), so it is the more actionable
  verdict, and it still carries a fill-to-admissible spawn plan.
- **`admissible` is computed PURE from the per-lane trees** (`_admissible`): the
  largest set of *concurrent* lanes that are pairwise `_tree.lane_trees_disjoint`,
  walked greedily in roster order; an exclusive-only roster admits 1; an empty
  roster admits 0. For the generic default (`main` + `global`, both `**/*`) this
  computes to **1** — `main`'s universal tree is disjoint from nothing, so no
  second concurrent worker can join. Correct: only one worker can safely own the
  whole tree.
- **`scavenge_entry`** (`lane_journal.py`) is the eviction sibling of
  `release_entry`, written by the driver when `supervise()` returns a REAP.

> **`SuperviseVerdict` is a [`verdict.py`](86_the-typed-verdict-surface.md) COUSIN,
> not a member.** It shares the `classify` *shape* — closed-enum verdict +
> one-line `reason` + echoed evidence + `to_dict()` — but its output is an
> **EFFECT decision** (spawn / reap / hold / flag), not an epistemic belief about
> ground-truth state. Like `arbitrate()` and `spawn`/`reap`, it is therefore
> deliberately **not** registered as a `TypedVerdict`: forcing an effect-emitter
> under the epistemic Protocol would make that type a god-type that means nothing
> (`verdict.py:41-47`). We match the value shape so the JSON / MCP / renderer seam
> is uniform; we do not claim it answers "is this claim true?"

The **`dos loop` verb** (`cmd_loop` in `cli.py`) is the **boundary**, and it is
**emit-only**: it runs `_apply_workspace` → `cfg = _config.active()`, gathers
evidence (a shared `_supervise_evidence(cfg, …)` helper: build the ordered roster,
`lane_journal.replay` the live leases, `liveness.classify` each held lease scoped
to its `(loop_ts, lane)` lease key via `journal_delta` — trusting the journal
append-ts for the heartbeat, the lease's self-report only as fallback), calls
`supervise()`, and **prints the plan** — a tally header (`SUPERVISE {verdict}:
alive {alive}/{target}, admissible {admissible}`) then the spawn/reap/flag command
lines, or `--output json` of `to_dict()`. It is the emit-and-exit discipline of the
decisions-queue TUI: **no `Popen`, no journal write.** `--watch` re-emits on an
interval; the clock is injectable (`--now-ms`) for deterministic tests, exactly
like `cmd_liveness`. It is a bespoke verb (not a verdict-registry verb) because it
emits *command lines*, not a verdict-as-exit-code.

**Tests (Phase 1):** the verdict on frozen `SuperviseEvidence` fixtures
(`tests/test_supervise.py`) — the ladder rows; the no-plan floor (empty roster →
`TARGET_UNREACHABLE`, `admissible=0`, no crash); the generic-default
`admissible==1`; the disjoint-spawn-walk soundness pins (a FREE lane whose region
collides with a held worker is **not** spawned even under target; two overlapping
FREE lanes never both spawn; fewer-than-headroom on collision); the pending race
guard; `OVER_TARGET` flags but never reaps a healthy worker; the purity poison-test;
the `verdict.conforms` value-shape + not-registered check. `scavenge_entry` +
replay-eviction in `tests/test_lane_journal.py`. The `dos loop` CLI emit
(`tests/test_cli_loop.py`): JSON parses, text renders with the header, `--now-ms`
deterministic, the benchmark 3-disjoint-lane case fills to three SPAWNs, the
emitted command names no host.

### Phase 2 — the watchdog driver + the `dos-supervise-loop` skill (driver + data) — ✅ SHIPPED 2026-06-01

The **driver** (`drivers/supervisor.py`) is layer 4 — it MAY import anything. It
turns the pure verdict into effects, on a cadence:

- A testable **`tick(cfg, *, target, now_ms, launched, …)`** that reuses
  `cli._supervise_evidence`, calls `supervise()`, then for each REAP appends
  `lane_journal.scavenge_entry(<the live lease>)` **under `archive_lock`** (the
  first in-tree journal *writer* — `lane_journal.append` is lock-free by contract,
  so the caller serializes), and for each SPAWN `subprocess.Popen`s a worker with a
  lineage env from `run_id` (`launched[lane] = now_ms`). It returns the verdict +
  the actions taken so tests drive it with no real subprocess and no real git.
- The **launched-set → pending** race belt: a lane launched within `cooldown_ms` is
  marked `pending=True` in the next tick's evidence, so a worker whose ACQUIRE has
  not yet landed is never double-spawned (soundness-floor §5, realized at the
  driver boundary).
- **`run(config=None, *, target=1, interval=…, max_ticks=None)`** mints a root
  `run_id`, loops `tick` + sleep, stops on `max_ticks` / KeyboardInterrupt. The
  interval is *long* (the watchdog is not a busy-poll — it is `init`'s reaper
  cadence).

The **skill** (`dos-supervise-loop/SKILL.md`) is the generic operator screenplay,
mirroring `dos-dispatch-loop`'s shape — package **DATA**, not code (nothing under
`src/dos/*.py` imports it; it shells only `dos` verbs and the `/dos-dispatch-loop`
slash-skill). The cadence: Step 0 read the taxonomy (`dos doctor --workspace .
--json`) and the plan (`dos loop --workspace . --target N --json`); Step 1 launch a
`/dos-dispatch-loop --lane <LANE>` worker per SPAWN (the worker journals its ACQUIRE
early to shrink the double-spawn window); Step 2 free the lane per REAP, surface
(don't kill) each FLAG; Step 3 sleep the interval and re-tick. It **deliberately
does not** auto-kill a SPINNING worker, reap a healthy/ADVANCING one to hit a
number, or hardcode a lane / trunk.

**Tests (Phase 2):** `tick()` over crafted evidence with `subprocess.Popen` and
`lane_journal.append` monkeypatched — a STALLED lane → a scavenge append; a FREE
under-target lane → a `Popen` with the right worker command; a pending lane → **no**
double `Popen`; all hermetic. Plus the skill-pack litmus sweep
(`test_skill_pack_litmus.py`): no forbidden host substrings, no whole-word
`apply`/`tailor`/`discovery`, shells only `dos` verbs, and the `EXPECTED_SKILLS` set
extended to include `dos-supervise-loop`.

### Phase 3 — value-aware spawn ranking, acting-on-spin, the `[supervise]` seam (future)

The directional slice. Three independent extensions, each landing *outside*
`supervise()`'s disjointness floor:

- **Value-aware spawn ranking.** Today the spawn walk takes the first disjoint
  candidates in roster order. Rank them instead by a `rank_key`-style seam (the
  same shape the value-aware picker introduces) — pre-order the candidates by
  descending yield before the unchanged disjointness gate, so the supervisor
  front-loads the high-yield, low-conflict lanes when it cannot fill the whole
  roster. Sound by construction: ranking only reorders *already-disjoint*
  candidates; it can never admit a colliding one. The yield signal stays
  driver/config policy, never a kernel concept.
- **Acting on a spin.** Today a SPINNING worker is FLAGged and left alone. A
  *driver* may consume the FLAG and act — auto-stop, escalate to the decisions
  queue, demote the lane's rank, recycle it after a budget. Open research; the
  kernel ships the signal, the act is opt-in driver policy.
- **A `[supervise]` `dos.toml` policy seam.** Make `SupervisePolicy`
  (`target` / `count_spinning_as_alive` / `reap_stalled`) declarable per-workspace,
  read back through `SubstrateConfig` exactly like `[lanes]` / `[liveness]` /
  `[stamp]` / `[reasons]` — the closed-config-as-data pattern. `dos doctor` then
  reports the active supervise policy.

---

## 3. Deliverables, by layer (the litmus this plan keeps)

| Layer | Deliverable | Litmus |
|---|---|---|
| **Kernel** (`supervise.py`, `lane_journal.py`, `cli.py`) | the pure `supervise()` verdict; `scavenge_entry`; the emit-only `dos loop` verb | PURE (no I/O / clock / subprocess inside the verdict); imports stdlib + `dos.liveness` + `dos._tree` only — **no host name, no `dos.drivers`**; the spawn plan is disjoint by construction; never reaps a healthy worker; `dos loop` emits, never `Popen`s or writes the journal; a `verdict.py` cousin, **not** registered |
| **Driver** (`drivers/supervisor.py`) | the long-lived watchdog: tick → gather → `supervise()` → `Popen` spawns + `scavenge_entry` reaps under a lock | the **only** place subprocess + journal-write + policy live; the launched-set race belt bounds the double-spawn; reuses `cli._supervise_evidence`; nothing under `src/dos/*.py` imports it |
| **Skill (data)** (`skills/dos-supervise-loop/SKILL.md`) | the generic supervisor screenplay | names **no** host (every fact from `dos doctor --json` / `dos.toml`); shells only `dos` verbs + the `/dos-dispatch-loop` slash-skill; package-DATA, not code (no `src/dos/*.py` import); passes the skill-pack litmus + the extended `EXPECTED_SKILLS` |

**The boundary that makes this safe:** the only kernel change is a *pure verdict*
whose worst case is a sub-optimal-but-disjoint spawn plan (it cannot admit a
collision, cannot reap a healthy worker). Everything that has an *effect* —
launching a process, writing the journal, sleeping on an interval — lives in the
driver and the skill, outside `src/dos/`. The dependency arrow points one way, the
same as the release tooling and the MCP server: the watchdog `import dos`, the
kernel is unaware it exists.

---

## 3a. How much is tied to user / host concepts?

Almost nothing — by the same rule as the rest of the kernel ("mechanism is the
kernel; policy is data a workspace declares; workflow is the host's"). The
coupling, layer by layer:

- **The pure verdict (`supervise.py`) names no host concept at all.** Its only
  imports are stdlib + `dos._tree` + `dos.liveness` — grep it for `job` / `apply` /
  `tailor` / `discovery` / `docs/_plans` and you get nothing (the one "job" hit is
  the English word in a comment). It does not know what a "plan", a "phase", a
  "dispatch", or a userland app is. It reasons purely about **leases** (region-locks
  it gets as `(lane, tree, liveness)` tuples) and a **target integer**.
- **The "user concepts" it consumes are all config-data, never hardcoded.** The
  roster is `cfg.lanes` — the `[lanes]` table a workspace declares in `dos.toml`;
  each lane's region is `cfg.lanes.tree_for(lane)`; the desired population is the
  `--target N` the operator passes. Swap the `dos.toml` and the same verdict serves
  a different fleet with zero code change. The generic default (`main`/`global`,
  both `**/*`) is what ships, and it is what produces `admissible 1` out of the box.
- **The lane *is* the only domain concept — and it is already generic.** A lane is
  a leased glob-region ([`89`](89_the-lane-is-a-region-lock.md)), not a host
  workflow stage. "How many workers can I run?" reduces to "how many region-locks
  are pairwise compatible?", computed from `_tree.lane_trees_disjoint` over
  whatever trees the config declares — so the supervisor inherits genericity from
  the lane, it does not re-introduce coupling.
- **The skill (`dos-supervise-loop/SKILL.md`) is held to the litmus and passes it.**
  It names no host directory, no host lane, no host commit prefix; every specific it
  needs comes from `dos doctor --json` / `dos.toml`, and it shells only `dos` verbs
  + the generic `/dos-dispatch-loop` slash-skill. `tests/test_skill_pack_litmus.py`
  pins this (the skill analogue of "kernel imports no host").
- **The one host-shaped assumption is deliberately *not* in the kernel.** "A worker
  is a `/dos-dispatch-loop` process launched with `claude -p`" lives in the
  **driver** (`drivers/supervisor.py`) and the **skill** — the spawn *command string*
  is policy. A different host that runs workers differently swaps the driver, not the
  verdict. The kernel only ever emits "SPAWN lane X"; what a spawn *is* is host policy.

Net: the supervisor is as domain-free as `liveness()` or `arbitrate()`. The only
thing a host must supply is its `dos.toml [lanes]` and a way to launch a worker —
both already the config/driver seam, neither a kernel edit.

---

## 4. Why this composition

- **The supervisor is `init`.** A DOS fleet is a set of dispatch-loops, each a
  process holding one lane lease. Nothing keeps the *set* at a target size, refills
  a lane whose worker died, or tells you the roster physically can't reach the
  number you asked. That is precisely what `init` / PID-1 does for a system's
  services: reconcile the observed population toward the declared one,
  declaratively, by watching what is actually *up*. `supervise()` is that reconcile
  loop for workers — and like `init` it never trusts a process's word that it is
  healthy; it reads the lease (the journal) and the liveness (git/journal deltas).
- **It consumes the lane as a region-lock.** "How many workers can I run at once?"
  is *exactly* "how many region-locks are pairwise compatible?" — so `admissible`
  is the size of the largest set of pairwise-disjoint concurrent trees, computed
  straight from the lock-compatibility test (`_tree.lane_trees_disjoint`). The
  generic `**/*`-everywhere default admitting **1** is the universal-lock-blocks-
  everything fact, not a special case. Reasoning about the population as *region-
  lock occupancy* is what makes the spawn plan disjoint by construction.
- **It is `liveness`'s population-axis sibling, and the verdict/monitor split is
  the same.** `liveness.classify` answers one run; `supervise()` answers the
  roster — both are pure `classify(Evidence, Policy) -> Verdict` functions with all
  I/O at the boundary, both replay-testable on frozen fixtures.
  [`82`](82_liveness-oracle-plan.md) drew the line "a daemon that periodically
  calls the verdict is a *consumer* a host builds; it is not the kernel" — the
  watchdog driver is that consumer for the population verdict, exactly as a
  dispatch loop is for `liveness`.
- **It closes the loop on a fleet.** The distrust syscalls are sensors (`verify` /
  `liveness`) and actuators (`refuse` / `arbitrate`); the supervisor is the
  *controller* that turns open-loop "spin up N ultracode sessions, no control" into
  a steerable, self-refilling population — the strongest answer to "why not just
  run N agents?"

---

## See also

- [`82_liveness-oracle-plan.md`](82_liveness-oracle-plan.md) — the per-run verdict
  `supervise()` consumes; the sibling whose verdict/monitor split (pure verdict in
  the kernel, the polling consumer in a driver) this plan mirrors for the
  population, and whose "SPINNING is advisory, never a kill" rule it inherits.
- [`86_the-typed-verdict-surface.md`](86_the-typed-verdict-surface.md) — the
  `verdict.py` contract `SuperviseVerdict` matches in *shape* (closed-enum verdict +
  reason + `to_dict`) but is a **cousin not a member** of (it emits an effect
  decision, not an epistemic belief — `verdict.py:41-47`).
- `src/dos/supervise.py` (the pure verdict), `src/dos/lane_journal.py`
  (`scavenge_entry`, `replay`), `src/dos/liveness.py` (`classify`),
  `src/dos/_tree.py` (`lane_trees_disjoint`), `src/dos/drivers/supervisor.py` (the
  watchdog), `src/dos/skills/dos-supervise-loop/SKILL.md` (the screenplay) — the
  surfaces this plan ships.

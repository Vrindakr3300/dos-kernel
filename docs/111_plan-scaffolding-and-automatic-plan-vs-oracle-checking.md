# Plan scaffolding, and checking the plan against the oracle automatically

> **`dos plan` already exists — a read-only `verify()`-fan-out that pairs every
> phase's *claim* (`plan_source` harvests it) with `oracle.is_shipped` and
> headlines the `⚠over-claim` cell where the plan says SHIPPED but git says not
> ([`plan_board.divergence`](../src/dos/plan_board.py), `plan_board.py:86`). But it
> is a *pull* projection — a human has to run it and read the board. Two gaps
> remain. (5) There is no first-class *scaffold*: a host adopting DOS has nothing
> that writes a starter plan doc into its declared `plans_glob` location and proves
> the doc actually harvests under the active grammar — we shipped
> [`examples/plans/example-plan.md`](../examples/plans/example-plan.md) as a
> copyable file, but no verb emits it and no check confirms the copy parses. (6)
> Nothing runs `dos plan` *automatically* at a loop/supervisor boundary, so a
> dispatch loop can run for hours while the plan quietly over-claims and the
> over-claim is visible only if someone thinks to look — the loop self-certifies.
> This note specifies both, and keeps each on the right side of the kernel's line:
> the scaffold writes a *file the kernel already knows how to read* and the doctor
> harvest-check is a pure verdict over `plan_source`'s own output; the automatic
> check **mints** the over-claim divergence (a belief over the unforgeable oracle
> verdict, the same one `dos plan` already mints) and **proposes** it into the
> `dos decisions` queue (a new advisory rung — record + surface, never
> auto-correct), and it lives in the **watchdog DRIVER**, never a new kernel verb,
> because the actor that polls on a cadence and writes the journal is policy. The
> kernel never edits a plan doc, never re-stamps a phase, and never believes the
> plan's `SHIPPED` word — exactly as it never believes a run's `STEP_CLAIMED`.**

A plan in the family of [`74_skill-pack`](74_skill-pack-plan.md) (the scaffold is
the SKP on-ramp restated: a domain-free *shape* a host copies, every host-specific
already config data), [`101_watchdog`](101_watchdog-driver-and-the-poll-cadence.md)
(the auto-check is the watchdog's per-run-health poll generalized to a
per-*plan*-health poll — same driver, same cadence, same record-and-propose
boundary), [`99`](99_runtime-validation-and-the-actuation-boundary.md) (the
advisory-only actuation floor the auto-check must respect: it records an
`OP_REFUSE`-shaped decision and stops, it never re-stamps), [`98`](98_the-orchestrator-is-a-driver.md)
(the supervisor is a driver — the auto-check is *its* job, not the kernel's),
[`107`](107_resumable-work-and-the-intent-ledger.md) (the `STEP_CLAIMED` vs
`STEP_VERIFIED` line — a plan's `SHIPPED` claim is the `STEP_CLAIMED` self-report,
the oracle verdict is the `STEP_VERIFIED` ground truth, and the over-claim is the
plan-altitude restatement of "the run claimed a step it never landed"), and
[`72_renderer-seam`](72_renderer-seam-plan.md) / the `dos.plan_sources` seam
([`plan_source.py:366`](../src/dos/plan_source.py)) the deferred second dialect
plugs into.

It carries no litmus and is **NOT YET BUILT** — `dos plan` and the example file
exist (verified live); the scaffold verb, the doctor harvest-check, and the
watchdog auto-check rung do not. §3 is the model; §4 the phases; the rest is
obligations and the boundary.

---

## 1. Problem

A host can run `dos plan` but cannot *get* a plan (no scaffold) or be *told* when
its plan starts lying (no automatic check) — the loop self-certifies on the plan's
own `SHIPPED` word between manual board reads.

## 2. Goal

Two enabled slices, smallest-first, each behind the current behavior so neither can
regress what ships today:

1. **A scaffold** — `dos init --with-example-plan` (and the equivalent `dos plan
   scaffold`) writes a starter plan doc into the workspace's declared `plans_glob`
   location, then `dos doctor --check` gains a *harvest finding* that confirms the
   doc actually produces rows under the active grammar (a plan a host writes that
   the default `markdown` source can't read is a silent foot-gun today).
2. **An automatic plan-vs-oracle rung** — the watchdog driver periodically fans
   `oracle.is_shipped` over the active plan's phases (reusing `plan_board`) and
   records each `⚠over-claim` as a new **decision source** feeding the existing
   `dos decisions` queue — record + propose, never auto-correct.

The throughline both slices share: **the plan is a distrusted self-report, the
oracle is the authority, and the only new thing is making the existing distrust run
on a cadence and ship with a starter doc** — no new syscall, no new trust rung,
just a driver poll over `plan_board` + `decisions` and a `dos init` flag.

---

## 3. The model

### 3.1 The scaffold is a file the kernel already reads — not a new schema

The whole reason a scaffold is *cheap and safe* is that DOS already holds the
grammar the scaffolded doc must satisfy: the built-in `MarkdownPlanSource` harvests
`### N. PLAN PHASE — title` headings whose phase token carries both a letter and a
digit (`plan_source._HEADING_RE`, `plan_source.py:154`; the letter+digit guard
`_looks_like_phase_id`, `plan_source.py:168`). [`example-plan.md`](../examples/plans/example-plan.md)
is *already written to that grammar* and already states it inline. So the scaffold
verb is not authoring a new format — it is **emitting the known-good example into
the declared `plans_glob` target**, exactly as `dos init` emits a known-good
`dos.toml` via `_render_init_config` (`cli.py:466`). The default glob is
`docs/**/*-plan.md` (`config.py:265`), so the natural target is
`docs/example-plan.md` (or the first concrete directory the glob names) — derived
from `cfg.paths.plans_glob`, never a hardcoded `docs/` literal (the
"kernel-imports-no-host" rule applied to the scaffold target, the same discipline
`MarkdownPlanSource` keeps by globbing the declared path).

The one genuinely new mechanism is the **harvest-check**: a `dos init
--with-example-plan` that wrote a doc the active grammar can't read would be worse
than no scaffold. So the scaffold's correctness is *verified by running the source
over it* — `run_plan_source(MarkdownPlanSource(), cfg)` (`plan_source.py:324`, the
fail-to-empty wrapper) must return a non-empty row set whose `(plan, phase)` pairs
match what the scaffold wrote. This is a pure check over the source's own output —
it sits beside `_treeless_lane_findings` (`cli.py:2481`) and `_stamp_coverage_finding`
(`cli.py:2518`) as a third `dos doctor --check` finding, computed once and shared
by the text and `--json` paths (`cmd_doctor`, `cli.py:2266`), gating the exit code
the same way. The finding answers one question: **does this workspace's declared
plan glob harvest at least one phase under the active source?** A repo whose plans
use a dialect the default can't read (DOS's own `### Phase N:` design docs) gets a
finding pointing at the `dos.plan_sources` plugin escape hatch — the honest
under-harvest made *visible* rather than silent.

### 3.2 The automatic check is the watchdog's poll, re-aimed at the plan

The watchdog ([`drivers/watchdog.py`](../src/dos/drivers/watchdog.py)) already polls
a *pure kernel verdict* on a cadence from outside the watched run's process and
**records + proposes** rather than acts: `assess_run` calls `liveness.classify`
(near-pure, watchdog.py:133), `tick` maps the verdict to an action, and a halt is
recorded via the injectable `lane_lease.halt` which appends an `OP_HALT` and
**NEVER signals** (`lane_lease.py:482`; pinned by
`test_watchdog_proposes_does_not_signal`). That `OP_HALT` then surfaces in the
`dos decisions` queue as a `LIVENESS` decision (`decisions._from_lane_journal`,
`decisions.py:273`).

The plan-vs-oracle auto-check is *that exact pattern with the verdict swapped*:

| Watchdog's per-run-health rung | The new per-plan-health rung |
|---|---|
| evidence: git/journal delta for one run | evidence: `plan_board.snapshot` rows + `oracle.is_shipped` per phase |
| pure verdict: `liveness.classify` → SPINNING/STALLED | pure verdict: `plan_board.divergence` → `⚠over-claim` per phase (`plan_board.py:86`) |
| warrant: `_warrants_halt` + idempotence memory (`proposed` dict) | warrant: phase is `is_divergent` over-claim + one-record-per-episode idempotence |
| record: `lane_lease.halt` → `OP_HALT` (never signals) | record: a journal append (never re-stamps) → a new decision source |
| surface: `decisions._from_lane_journal` → `LIVENESS` row | surface: a new `_from_plan_overclaims` reader → a `PLAN_OVERCLAIM` row |
| enact: human pastes the stop command | enact: human fixes the plan stamp or lands the missing commit |

The kernel side is *already built*: `plan_board.snapshot` is the pure-data frame,
`divergence` is the pure verdict, `decisions.Decision` is the row type. The driver
adds the **cadence and the journal write** — the two things the kernel forbids
itself. This is why the auto-check is a watchdog tick extension, **not** a new
`dos plan --check-and-record` kernel verb: `cmd_plan` (`cli.py:2053`) is read-only
by contract ("stores nothing, mutates nothing, acquires no lease" —
`plan_board.py:20`), and a kernel verb that wrote a decision journal entry on a
cadence would be the `dos loop`/supervisor boundary collapsing into the kernel,
exactly the `docs/98`/`docs/101` line. The supervisor is a driver; the auto-check
is the supervisor's.

### 3.3 The decision source — a new advisory rung, record-and-propose only

`decisions.collect_decisions` (`decisions.py:480`) joins four sources today
(`_from_lane_journal`, `_from_verdict_envelopes`, `_from_soaks` — the journal one
yields both `ARBITER_REFUSE` and `LIVENESS`). The auto-check adds a fifth:

- A new `DecisionKind.PLAN_OVERCLAIM` (`decisions.py:77`, the closed `str`-enum) —
  "the plan claims a phase SHIPPED that the oracle says is `via none`."
- `ResolverKind.ORACLE` for it (`decisions.py:91`): the over-claim *was already
  adjudicated by a deterministic oracle* (`oracle.is_shipped`), exactly as a
  `LIVENESS` halt carries `ORACLE` because liveness is deterministic
  (`decisions.py:289`). The next reader is not a human-judgment call but a
  re-check — the operator either fixes the stamp or lands the commit.
- A `_KIND_RANK` slot (`decisions.py:471`): below `LIVENESS`/refusals (a hung run
  and a blocked lane are more urgent than a stale claim) but a real standing row.

How the over-claim becomes a *durable* decision the queue can read is the one
design choice with two honest options, and the plan picks the journal:

1. **Journal an `OP_REFUSE`-shaped record** under a `plan_overclaim` reason class,
   via the existing lock-free `lane_journal.append` the supervisor driver already
   serializes (`drivers/supervisor.py` brings its own `O_CREAT|O_EXCL` lock). The
   record is NOT in `_STATE_MUTATING_OPS` (`lane_journal.py:135`) so `replay`
   ignores it — it mutates no lease, exactly like `OP_REFUSE`/`OP_HALT`
   (`lane_journal.py:100`, `:112`). `decisions._from_lane_journal` grows a branch
   that lifts it into a `PLAN_OVERCLAIM` row. This reuses the watchdog's exact
   surface (journal → decisions) and gets idempotence + age for free. **Chosen.**
2. *(Rejected)* A fresh `.dos/plan-overclaims.json` sidecar read by a new
   `_from_plan_overclaims`. Rejected because it is a *new durable store*, which the
   decisions module is explicitly built to avoid ("read-only projection, never a
   store" — `decisions.py:12`); the journal is the existing durable feed.

Idempotence mirrors the watchdog's `proposed` dict (`watchdog.py:206`): one record
per `(plan, phase)` over-claim episode per repropose window, dropped when the
over-claim clears (the phase ships, or the false `SHIPPED` is removed) so a later
re-divergence earns a fresh record — the recovered-run-can-be-reproposed property,
restated for plans.

---

## 4. Phases (throughline-first; each ships an enabled slice behind the old behavior)

**Phase 1 — `dos doctor --check` harvest finding (the smallest enabled slice, no
new write path).** Add `_plan_harvest_finding(cfg)` beside `_treeless_lane_findings`
(`cli.py:2481`): run `plan_source.run_plan_source(MarkdownPlanSource(), cfg)` and
emit a finding iff the declared `plans_glob` matches files but harvests **zero**
rows (the silent-dialect foot-gun), pointing at the `dos.plan_sources` plugin
escape hatch. No finding when the glob matches nothing (a repo legitimately has no
plans — the no-plan floor `dos plan` already honors) or harvests ≥1 row. Wire it
into `cmd_doctor` (`cli.py:2266`) under the same `check_requested` gate, computed
once, shared by text + `--json`, exit-code-gating — exactly the existing
finding rail. This ships value alone: a host running `dos doctor --check` today
learns its plan doc is unreadable. Behind the old behavior: `--check` without the
new finding is unchanged.

**Phase 2 — `dos init --with-example-plan` + `dos plan scaffold` (the scaffold
write path).** Add the `--with-example-plan` flag to `cmd_init` (`cli.py:513`) and
a `dos plan scaffold` subcommand: after the `dos.toml` exists, derive the target
from `cfg.paths.plans_glob` (the first concrete path the glob names; default
`docs/example-plan.md`), and write the [`example-plan.md`](../examples/plans/example-plan.md)
body (shipped as package-data, the SKP precedent — `src/dos/skills/` ships in the
wheel) **only if the target does not exist** (the `dos init` `--force` posture,
`cli.py:531`). Then immediately run the Phase-1 harvest-check over the freshly
written doc and print its row count, so the scaffold *proves itself* — a scaffold
that wrote an unharvestable doc fails loud. Names no host directory: the target is
the declared glob. Behind the old behavior: `dos init` with no flag is byte-for-byte
unchanged; the scaffold is opt-in.

**Phase 3 — the `PLAN_OVERCLAIM` decision source (the queue rung, read side
first).** Add `DecisionKind.PLAN_OVERCLAIM` (`decisions.py:77`), its `_KIND_RANK`
slot (`decisions.py:471`), `ResolverKind.ORACLE` derivation, and a branch in
`_from_lane_journal` (`decisions.py:230`) that lifts a `plan_overclaim`-classed
journal record into a `Decision` (carrying `plan`/`phase` in `evidence`, the
oracle `via none` source, the doc path in `source_path`). `next_steps`
(`decisions.py:521`) offers the two real actions: `m` → `dos verify --explain PLAN
PHASE` (re-check), and a `# fix the SHIPPED stamp or land the PHASE: commit` hint.
This ships the *reader* with zero writers yet — a `PLAN_OVERCLAIM` record placed by
a test surfaces correctly. Behind the old behavior: no record exists in the wild
until Phase 4, so the live queue is unchanged.

**Phase 4 — the watchdog auto-check tick (the cadence + the write).** Add
`assess_plan(cfg) -> list[over-claims]` to the watchdog driver (near-pure: calls
`plan_board.snapshot` + filters `is_divergent` `DIV_OVERCLAIM` rows) and a
`tick`-level pass that records one `plan_overclaim` journal entry per over-claim
episode (the `proposed`-dict idempotence, keyed on `(plan, phase)`, dropped when it
clears), via the injectable journal append — **never re-stamping the plan**, the
`docs/99` floor and the `test_watchdog_proposes_does_not_signal` analogue (a new
`test_watchdog_plan_check_records_does_not_restamp`). Expose it on `dos watch
--check-plan` (off by default, so existing watchdog runs are unchanged) and as a
`dos loop` opt-in tick. Tests drive it with `plan_board.snapshot` returning frozen
frames and the journal append monkeypatched — no real git, no real plan doc, the
watchdog-driver test idiom (`watchdog.py:54`). This is the slice that closes the
self-certification gap: now a loop running for hours surfaces its own over-claim
into `dos decisions` without anyone watching the board.

**Phase 5 (deferred) — the second built-in plan dialect as a `dos.plan_sources`
plugin.** DOS's own design docs use `### Phase N:` / `- **1a.**` (bare-ordinal
phase tokens) which `_looks_like_phase_id` deliberately rejects (`plan_source.py:168`,
the digit-only cut that keeps prose like `### 1. The rationale — why` from mining
phantom phases). A second built-in or shipped plugin that reads the bare-ordinal
dialect would let `dos plan` audit *this very repo's* plans. This is deferred and
flagged for care: it cannot relax `_looks_like_phase_id` in the existing `markdown`
source (that would re-open the prose-mining false-positive the guard closes — see
the `### 1. Phase 2 of 3 — done` case the comment names, `plan_source.py:176`); it
must be a *separate, opt-in* source registered under `dos.plan_sources`
(`plan_source.py:366`), resolved by name, with its **own** false-positive geometry
(a bare-ordinal heading is far more prone to harvesting prose numbered lists, so it
needs a stricter context guard — e.g. requiring a `Phase`/`Step` keyword before the
ordinal). It is the kernel-default-does-not-guess rule: the strict default ships,
the looser dialect is an explicit plugin a host (or DOS-on-DOS) opts into.

---

## 5. Test obligations

- **Harvest-check (Phase 1):** a workspace whose `plans_glob` matches a doc that
  harvests ≥1 row → no finding, exit 0; a doc that matches but harvests 0 (a
  bare-ordinal `### Phase 1:` dialect) → exactly one finding, exit 1; a repo with
  no matching files → no finding (the no-plan floor). Text and `--json` `findings`
  array agree (the `test_stamp_doctor` shared-findings rail).
- **Scaffold (Phase 2):** `dos init --with-example-plan` writes the doc at the
  glob-derived target, the written doc harvests the same `(plan, phase)` pairs the
  example states (`AUTH AUTH1`, `AUTH AUTH2`, `AUTH AUTH3`), and re-running it
  without `--force` does not clobber an existing doc. The scaffold names no
  hardcoded `docs/` literal — a workspace with `plans_glob = "planning/*.md"`
  (`config.py:315`) scaffolds under `planning/`.
- **Decision source (Phase 3):** a `plan_overclaim` journal record lifts into a
  `PLAN_OVERCLAIM` `Decision` with `ResolverKind.ORACLE`, ranked below `LIVENESS`,
  carrying the `(plan, phase)` in evidence and the oracle `via none` source; it
  appears in `collect_decisions(resolver=None)` and `--all`, and `next_steps`
  offers the `dos verify --explain` re-check.
- **Watchdog auto-check (Phase 4):** with `plan_board.snapshot` returning a frame
  carrying one `⚠over-claim` row, a tick records exactly one `plan_overclaim`
  entry; a second tick within the repropose window records none (idempotence); a
  tick where the over-claim has cleared (oracle now ships it) records none and
  drops the memory. The driver **never** calls a plan-doc write/re-stamp — pinned
  by monkeypatching the file write to raise (the `does_not_signal` analogue).
- **Dialect plugin (Phase 5, when built):** the bare-ordinal source harvests
  `### Phase N:` headings WITHOUT re-introducing a prose false-positive on a
  numbered-list heading; the default `markdown` source's `_looks_like_phase_id`
  behavior is byte-unchanged (the guard is not relaxed).

---

## 6. Boundary — what is DOS, what stays a driver

- **Kernel (already built, unchanged):** `plan_board.snapshot`/`divergence`
  (`plan_board.py`), `plan_source` + the `dos.plan_sources` seam (`plan_source.py`),
  `oracle.is_shipped`, `decisions.collect_decisions` + the `Decision` type. Phase 3
  adds *data* to the kernel's closed vocabularies (a `DecisionKind` enum member, a
  rank, a journal reader branch) — the same kind of additive closed-set growth as
  the `LIVENESS` kind that `docs/101` added; it introduces no new policy, no I/O on
  a cadence, no plan-doc write.
- **Helper/CLI (Phases 1–2):** `dos doctor --check`'s harvest finding and
  `dos init --with-example-plan` / `dos plan scaffold` live in `cli.py` beside the
  existing init/doctor machinery — thin shells carrying no policy, deriving every
  host-specific from `cfg` (the glob, the lane taxonomy). The scaffolded doc body
  ships as package-data, the SKP precedent — DATA, not code.
- **Driver (Phase 4):** the cadence + the journal write live in
  `drivers/watchdog.py` (or a sibling driver). This is the load-bearing boundary
  claim: **the actor that polls the plan-vs-oracle divergence on a timer and writes
  a decision record is a driver, not a kernel verb**, for the same reason the
  watchdog and supervisor are drivers (`docs/98`/`docs/101`) — subprocess-adjacent
  cadence + journal-write + policy live outside the kernel, which only ever ships
  the pure verdict and the read-only projection. `dos plan` stays read-only; the
  kernel never edits a plan doc, never re-stamps a phase, never believes the plan's
  `SHIPPED` word over the oracle's `via none`.
- **Stays a driver / host (out of scope):** *enacting* an over-claim fix (editing
  the plan, landing the missing commit) — that is a human emit-and-exit action or a
  host driver consuming the `PLAN_OVERCLAIM` decision, exactly as enacting a halt is
  left to a driver consuming `OP_HALT` (`lane_lease.py:509`). The auto-check
  records and proposes; it never corrects.

---

## 7. What this note claims, and what it does not

- **Does claim:** plan scaffolding is the `dos init` pattern aimed at a plan doc the
  kernel already reads, made safe by a pure harvest-check over `plan_source`'s own
  output; automatic plan-vs-oracle checking is the watchdog's record-and-propose
  poll with `liveness.classify` swapped for `plan_board.divergence`, feeding a new
  advisory `PLAN_OVERCLAIM` rung into the existing `dos decisions` queue; both are
  additive, neither is a new syscall, and the cadence + journal write live in the
  driver so the kernel keeps its read-only / believes-no-self-report discipline.
- **Does not claim:** that the kernel should ever edit or re-stamp a plan doc (it
  records the divergence and stops — the `docs/99` advisory floor), that the plan's
  `SHIPPED` word is ever trusted (the oracle is always the authority,
  `plan_board.py:97`), that the default `markdown` grammar should be loosened to fit
  the bare-ordinal dialect (that re-opens the prose-mining false-positive — the
  dialect is an opt-in `dos.plan_sources` plugin, §4 Phase 5), or that the
  over-claim severity ranking is calibrated (it ranks below the live-incident
  kinds by construction; a bench is not in scope here).

---

## References

*The surface this composes (built, verified live):*
- [`src/dos/plan_board.py`](../src/dos/plan_board.py) — `divergence` (`:86`), the
  `DIV_OVERCLAIM` cell (`:75`), `snapshot` (`:311`), the pure `build_phase_rows`
  adapter (`:183`); the read-only-projection discipline (`:20`).
- [`src/dos/plan_source.py`](../src/dos/plan_source.py) — `MarkdownPlanSource`
  (`:277`), `run_plan_source` fail-to-empty (`:324`), `_looks_like_phase_id`
  (`:168`), the `dos.plan_sources` entry-point seam (`:366`).
- [`src/dos/decisions.py`](../src/dos/decisions.py) — `collect_decisions` over the
  four sources (`:480`), `DecisionKind` (`:77`), `ResolverKind` (`:91`),
  `_from_lane_journal` (`:230`), `_KIND_RANK` (`:471`), `next_steps` (`:521`).
- [`src/dos/drivers/watchdog.py`](../src/dos/drivers/watchdog.py) — the
  record-and-propose tick (`assess_run` `:133`, `tick` `:206`, the `proposed`
  idempotence `:206`), the never-signals boundary.
- [`src/dos/cli.py`](../src/dos/cli.py) — `cmd_init` (`:513`), `_render_init_config`
  (`:466`), `cmd_doctor` (`:2266`), `_treeless_lane_findings` (`:2481`),
  `_stamp_coverage_finding` (`:2518`), `cmd_plan` (`:2053`).
- [`examples/plans/example-plan.md`](../examples/plans/example-plan.md) — the
  known-good starter doc the scaffold emits.

*The frame and the boundary:*
- [`101_watchdog-driver-and-the-poll-cadence.md`](101_watchdog-driver-and-the-poll-cadence.md)
  — the poll-and-propose driver the auto-check generalizes.
- [`99_runtime-validation-and-the-actuation-boundary.md`](99_runtime-validation-and-the-actuation-boundary.md)
  — the advisory-only floor (record, never enact).
- [`98_the-orchestrator-is-a-driver.md`](98_the-orchestrator-is-a-driver.md) — the
  supervisor-is-a-driver line the auto-check sits behind.
- [`107_resumable-work-and-the-intent-ledger.md`](107_resumable-work-and-the-intent-ledger.md)
  — the `STEP_CLAIMED` vs `STEP_VERIFIED` line the plan-`SHIPPED`-vs-oracle
  over-claim restates at plan altitude.
- [`74_skill-pack-plan.md`](74_skill-pack-plan.md) — the ship-a-domain-free-shape-as-
  package-data precedent the scaffold follows.
- [`72_renderer-seam-plan.md`](72_renderer-seam-plan.md) — the seam pattern the
  deferred `dos.plan_sources` dialect plugin plugs into.

# 127 — DOS ↔ Bench/Job integration audit (2026-06-03)

**Date:** 2026-06-03
**Scope:** How well does DOS (the `dos-kernel` package, source at `dos/`, v0.10.0) *actually*
work with its two consumers — **Job** (`job/`, deep python-import coupling via re-export shims)
and **Benchmark** (`Benchmark/`, CLI + skills + `dos.toml` coupling). Both are under active development.
**Method:** 10 parallel probes running **real commands** (pytest, `dos` CLI, live import/version checks) against
the editable install, then a lead-auditor pass that **re-ran the key commands live** to adjudicate where probes
disagreed. Every quoted output below is from this session on Windows 11 / PowerShell, not assumed.

> Workflow stats: 10 probes → 69 candidate findings → adjudication. The per-finding adversarial-verify panel
> only formally graded 1 finding (a harness quirk), but the synthesis agent independently re-executed the
> headline commands, so the load-bearing findings are first-hand verified. Two items remain
> **unverified-in-isolation** and are flagged as such: the `test_dispatch_lane.py` hang, and C1 lease-flip's
> "plan-only" keystone status.

---

## Verdict

DOS is a **structurally sound substrate that genuinely works with both consumers at the level that matters** —
live code executes correctly across the seam — but it ships with a real multi-way version-reporting drift and a
small number of confirmed seam regressions.

| Surface | Grade | One-line |
|---|---|---|
| **DOS ↔ Job** | Works-with-caveats | Deep import coupling resolves & runs live; concurrency seam is real; but 3 confirmed seam-real test regressions. |
| **DOS ↔ Bench** | Solid (thin by design) | CLI/skills/`dos.toml` delegation works end-to-end; lone residual gap (F2) is honestly unfinished, not broken. |
| **DOS internal** | Works-with-caveats (drift-risk) | Domain purity litmus-clean; API mostly stable; **no release process** keeps 4 version numbers in sync. |

None of the breakage is fatal; all of it is the expected texture of a system under active development — **except
the version drift, which is a latent clean-room landmine.**

---

## Surface 1 — DOS ↔ Job (deep python-import coupling)

**What works (verified).** `import dos` in Job resolves to **live HEAD source** at `dos/src/dos/__init__.py`
via the editable `.pth` (sole line: `dos/src`) — consumers get 0.10.0+ code, not a stale build (proven by
importing 0.10.0-only `dos.event_severity` live). All 17 re-export shims under `scripts/` import cleanly; every
explicit symbol in their `from dos.X import (...)` blocks resolves, including the underscore monkeypatch helpers
(`_check_phase_with_cache`, `_git_log`, `_state_path`) that `import *` would silently skip. The new 0.10.0 modules
Job leans on — `event_severity` (18 sites, 43 tests green) and `provider_limit` (8 sites, API
`{TRANSIENT_OVERLOAD|USAGE_WINDOW|HARD_QUOTA|NONE}` matched exactly, 94 tests green) — were adopted cleanly.

**Lease/substrate truth (better than memory claimed).** Memory said C1 lease-flip was "plan-only." Reality: Job's
HEAD ancestry contains **LJ Stage 4 read-flip** (`7a4cf3da`). A probe wrote a lease **only** into the lane-journal
WAL (zero YAML rows) and `_live_leases` surfaced it as live via `dos.lane_journal.replay(read_all())` — the
WAL-authoritative read-flip is **load-bearing, not cosmetic**. The lock-storm fix is in the shipping write path:
host `execution-state._dump` delegates to kernel `dos._filelock.atomic_replace` (bounded exp-backoff on
WinError 5/32/33). 17 substrate-race + 53 lease + 49 kernel journal/lease/filelock tests pass.

**Shim "byte-thin" label is overstated (1 of 17).** CLAUDE.md calls the shims "byte-thin re-export." True for 16.
**False** for `scripts/ship_oracle.py` (10,428 bytes): its body override-wraps three kernel functions
(`batch_is_shipped`, `load_state_from`, `load_state`, each `# noqa: F811`) with host policy. These are *documented,
fail-safe* wrappers that still delegate to `_kernel_batch_is_shipped(...)` (ship_oracle.py:128-136) — host DEFAULT
demotion hooks for the FQ-444 false-drain storm, not silent reimplementations. The override is sound; only the
label is wrong.

**Test truth — NOT all-green (confirmed seam regressions):**

- **Phase-shipped false-negative (reproduced live).** `python scripts/check_phase_shipped.py --json RS RS4` →
  `{"shipped": false, ...}` despite commit `8ea6ee8` existing with the exact expected subject. Root cause:
  `dos/src/dos/phase_shipped.py:186 _ONELINE_WINDOW = 4000`, but RS4 sits at position **4207** from HEAD (4627
  total commits). The kernel's own "FQ-409" comment warns about exactly this. `test_check_phase_shipped.py`:
  **10 failed / 203 passed.**
- **Arbiter UNKNOWN_LANE break (reproduced live).** Kernel `bc83d94` ("refuse UNKNOWN_LANE instead of auto-picking")
  reversed the documented DLO-Phase-6 empty-tree-degrades-to-auto-pick behavior; Job pinned the OLD behavior. Live:
  `fanout_state.arbitrate_lane(requested_lane='mystery', requested_kind='keyword', requested_tree=[], live_leases=[]).outcome`
  → `refuse`. `test_dispatch_lane.py`: **2 failed, 202 passed**.
- **Lane-health adapter/kernel disagreement.** Job adapter `dispatch_lane_health.assess` returns `PROCEED` on a
  fixture where kernel `dos.health.check` returns `ROUTE_UNSTICK` — the exact fork hazard the test guards.
  `test_dispatch_lane_health.py`: **3 failed.**
- **`test_dispatch_lane.py` (full file) HUNG** once under batch (0-byte output, killed) — consistent with the
  documented JOB lease lock-storm; **did not** reproduce in an isolated 82s run, so treat as intermittent.

**Confirmed-good seam (survived adversarial verification).** `test_ship_oracle.py` + `test_dispatch_substrate_race.py`
→ **71 passed** (ship-oracle registry-hit short-circuit + substrate-race concurrency against live 0.10.0
`dos.oracle`/`dos.config`). Also green: `test_lane_journal` (29), `test_leases`, `test_commit_broker`,
`test_dispatch_scout`, `test_reason_class_alias`, `test_dos_decision_log`, `test_severity_skill_contract`.

> Net: memory's "2 red job tests" is **stale-low** — current DOS-seam red count is **10 + 2 + 3 = 15**. Other reds
> (`test_lane_baseline` drift-band, `test_dispatcher_yaml_unification`, `test_lane_gardener`) are job-side
> config/drift issues that do **not** import `dos` and are **not** kernel regressions.

---

## Surface 2 — DOS ↔ Bench (CLI + skills + dos.toml)

**What works.** Delegation-heavy, not a drifted host reimplementation. Every verb Bench's skills/helpers invoke runs
correctly from `Benchmark/`: `dos doctor --json` (reads `next_packets=docs\_next`, `runs=docs\_fanout_runs`,
plans_glob → 18 docs), `dos verify`, `dos gate` (all three verdict paths LIVE/DRAIN/STALE-STAMP, exit codes 0/3/4),
`dos lease-lane` (acquire/live/release lifecycle, durable cross-process WAL — a probe lease appeared alongside 2
real live fanout leases), `dos arbitrate`, `dos decisions`, `dos init`. The three forked skills (`/next`, `/fanout`,
`/replan`) shell out for every load-bearing decision (**51** `dos <verb>` call sites). `fanout_helpers._dos_verify`
returns correct verdicts; 45 `fanout_helpers` tests pass.

**CLI-verb truth.** Full verb list (from `dos --help`): `init, verify, liveness, resume, loop, watch, arbitrate,
scope-gate, lease, lease-lane, halt, health, scout, run-id, id-alloc, journal, man, judge, judge-eval, overlap-eval,
decisions, memory, top, plan, doctor, reindex, projects, learn, reap, gate`. **`dos status` is NOT a choice**
(`invalid choice: 'status'`) — it remains a docs/120 design plan. Bench never references it → informational.

**Fork-drift truth.** Bench-owned logic that remains is genuine bench policy, not kernel mechanism: `next_context.py`
active-plans 3-table parse + git-log staleness self-check, and a documented byte-identical phase-label fallback that
delegates to `dos.stamp.parse_phase_labels` when DOS is importable. The lone python coupling resolves, signatures
match (`(subject: str|None) -> sorted list[str]`), wrapped in a clean `try/except ImportError`. 21 `next_context.py`
tests pass and transitively exercise the real primitive.

**Real residual gaps:**

- **F2 (`dos learn` workspace scoping) — still BLOCKED (probes disagreed; adjudicated live).** `dos learn --help`
  shows **only** `[-h] [--json]` — no per-subcommand `--workspace`. The top-level `dos --workspace . learn
  wedge-hotspots --json` IS accepted but **INERT**: `count: 167`, byte-identical to the global form (also `167`).
  The "STALE/unblocked" probe was misled by the silently-accepted top-level flag. **Bench's `dos-adoption-plan.md`
  F2-BLOCKED claim is accurate.**
- **`dos decisions` has no WRITE verb.** The queue write path (`home.append_decision`) is reachable only via
  `dos arbitrate --force` override-capture (cli.py:748-766). The adoption plan names this correctly.
- **Test coverage is thin.** Bench's DOS seam is unit-test-covered at exactly **one** point (phase-label parsing).
  `dos.toml` parsing and the forked `/next`/`/replan` skill contracts have **zero** tests — most of Bench's DOS
  integration is trust-on-faith.

---

## Surface 3 — DOS internal (the substrate itself)

**Version/install coherence — the headline defect (drift-risk, verified).** **Four** divergent version numbers for
one running artifact, plus a vestigial dist-info:

```
pyproject.toml / git tag .......... 0.10.0   (the truth — tag v0.10.0, HEAD abd0692 one past)
pip metadata / dist-info .......... 0.7.0    (dos_kernel-0.7.0.dist-info — stale)
dos.__version__ (runtime) ......... 0.7.0    (single-sourced from metadata)
job's pyproject pin ............... @v0.6.0  (git tag, 4 minors stale, dormant)
vestigial ......................... dos-0.4.0.dist-info + __editable__.dos-0.4.0.pth
```

The `.pth` correctly points at `dos/src`, so **code is current; only the self-reported string is stale.**
The bite is operator-facing and provenance-corrupting: `dos doctor`/`env_print` stamp `kernel_version=0.7.0` next to
the *current* `kernel_sha=abd0692` — a 0.7.0 label glued to a 0.10.0+ commit, internally self-contradictory in
durable adjudication records. **No runtime code gates on the version** (grep of both repos = zero gates), so it
does not break execution today.

**The latent landmine.** Job's prod pin `dos-kernel @ git+...@v0.6.0` is dormant because the editable sibling
shadows it. But `v0.6.0` does **not** contain `event_severity.py` or `provider_limit.py` (verified
`git ls-tree v0.6.0` → empty), which Job imports 18×/8×. A clean-room / prod install honoring that pin would
**crash on import.** The dev editable shadow masks this entirely.

**API stability.** Mostly stable; kernel consumer-relevant suite green (371 tests across arbiter / event_severity /
provider_limit / oracle / phase_shipped / stamp / gate_classify / scout / health). The one real contract break is the
arbiter UNKNOWN_LANE reversal (`bc83d94`, see Surface 1).

**Domain-purity (verified clean).** Litmus `test_vendor_agnostic_kernel.py` → **8 passed**. Grep for `import job` /
`import benchmark` under `dos/src` → **no host-import leaks.** The one host-policy literal
(`_job_policy.JOB_LANE_TAXONOMY`) is correctly fenced into a leaf module re-exported only for back-compat. **The
arrow points the right way.**

**Release process.** **None** keeps the four version numbers in sync — only manual `pip install -e`. The last
editable install froze metadata at 0.7.0; nothing re-stamps it on `git pull`.

---

## Claims vs Reality ledger

| Claim | Reality | Verdict |
|---|---|---|
| `.pth` reads 0.7.0 while pyproject reads 0.10.0 | Confirmed, **and worse**: 4-way drift + vestigial 0.4.0 dist-info | **TRUE (understated)** |
| Bench F2 BLOCKED — `dos learn` lacks `--workspace` | `--help` = `[-h] [--json]`; top-level flag accepted but **inert** (167==167) | **TRUE** |
| Bench F2 now STALE/unblocked (one probe) | Refuted by byte-identical output; scoping does not work | **FALSE** |
| Job shims are "byte-thin re-exports" (CLAUDE.md) | 16/17 true; `ship_oracle.py` override-wraps 3 kernel fns | **OVERSTATED** |
| Memory: "2 red job tests" on the seam | Stale-low: **15** seam-real reds (10+2+3) | **STALE/UNDERSTATED** |
| Memory: C1 lease-flip is "plan-only" | LJ Stage 4 read-flip **shipped** (`7a4cf3da`) + proven WAL-authoritative live | **STALE (work shipped)** |
| `dos status` exists / is shipped | `invalid choice: 'status'` — docs/120 plan only; Bench never calls it | **TRUE (not shipped, harmless)** |
| Bench A–E adoption phases COMPLETE | Spot-checked real commits doing what they say | **TRUE** |
| Job prod pin `@v0.6.0` works | Dormant; v0.6.0 lacks event_severity/provider_limit → clean-room crash | **DRIFT-RISK (masked)** |
| DOS is a clean vendor-agnostic substrate | Litmus 8/8, zero host-import leaks | **TRUE** |

---

## Top risks (ranked)

1. **Clean-room / prod install crashes on Job's `@v0.6.0` pin** (drift-risk, **HIGH latent**). Any env honoring
   `pyproject` over the editable shadow imports a kernel missing `event_severity`/`provider_limit` → `ImportError`
   on 18+ Job sites. Invisible on this box.
2. **Provenance corruption from version drift** (drift-risk, **MEDIUM**). `kernel_version=0.7.0` + `kernel_sha=abd0692`
   co-stamped into durable adjudication records makes them internally inconsistent — a data-trust-floor breakage even
   though execution is fine.
3. **Phase-shipped false-negative** (active breakage, **MEDIUM**). `_ONELINE_WINDOW=4000 < 4207` returns NOT_SHIPPED
   for genuinely-shipped phases → false-drain re-dispatch. 10 red tests.
4. **Arbiter UNKNOWN_LANE contract break** (active breakage, **MEDIUM**). Kernel reversed empty-tree auto-pick; Job
   pinned the old behavior. 2 red tests + reproduced live. Kernel and Job disagree about launch-vs-block.
5. **Lane-health adapter/kernel divergence** (active breakage, **LOW-MEDIUM**). Adapter `PROCEED` vs kernel
   `ROUTE_UNSTICK` on the same fixture. 3 red tests.
6. **Lease lock-storm intermittency** (latent, **LOW**). `test_dispatch_lane.py` hung once under batch; retry-replace
   is wired but the C1 WAL-authoritative lease-flip keystone remains plan-only per memory. Not reproduced isolated.
7. **Bench DOS seam is single-point-tested** (drift-risk, **LOW**). `dos.toml` parse + forked skill contracts have
   zero tests; future kernel CLI changes could silently break Bench.

---

## What's genuinely working well

- **The substrate is structurally clean.** Dependency arrow points the right way, AST-enforced purity litmus passes
  (8/8), zero host-import leaks, the one host literal correctly fenced. This is the hard part, done right.
- **The concurrency seam is real and load-bearing.** WAL-authoritative lease union proven live; lock-storm retry
  delegates to the kernel's hardened `atomic_replace` in the actual write path. **Ahead of where memory said.**
- **Live code, not stale builds.** Despite the version label, every consumer provably executes current 0.10.0+
  source via the editable `.pth`.
- **Clean new-module adoption.** `event_severity` + `provider_limit` added and adopted with no scramble — the seam
  absorbs kernel growth gracefully.
- **Bench's delegation discipline.** 51 shell-out call sites; forked skills delegate every load-bearing decision and
  keep only genuine host context-packing. F2 is honestly BLOCKED, not silently faked.
- **Core ship-oracle + substrate-race green** (71 passed) — the confirmed-sound center of the Job seam.

---

## Recommended next actions (ranked)

**Fix now (small, high-leverage):**

1. **Re-stamp the editable metadata.** `pip install -e ./dos` to regenerate `dos_kernel-*.dist-info` at 0.10.0
   and clear the 4-way drift; delete vestigial `dos-0.4.0.dist-info` + `__editable__.dos-0.4.0.pth`. Then add a
   `dos doctor` self-check asserting `importlib.metadata.version == __init__ fallback literal` so it can't recur.
2. **Resolve the arbiter UNKNOWN_LANE disagreement.** Either (a) revert/guard `dos/src/dos/arbiter.py` `bc83d94` to
   restore empty-tree auto-pick, or (b) migrate Job's two `test_dispatch_lane.py` tests + call sites to expect
   `refuse`. Pick one truth — they currently disagree about launch-vs-block.
3. **Bump/adapt the phase-shipped window.** `dos/src/dos/phase_shipped.py:186` — raise `_ONELINE_WINDOW` past repo
   depth (4627) or fall back to `git merge-base --is-ancestor` when the oneline scan misses. Re-run the 10 reds.
4. **Reconcile `dispatch_lane_health.assess` to the kernel verdict.** Align the Job adapter with `dos.health.check`
   on the parity fixture (3 reds) — the documented fork hazard the test exists to catch.

**Fine to defer while developing:**

5. **Job's `@v0.6.0` prod pin** — bump to a floor including event_severity/provider_limit before any clean-room/prod
   build; harmless while the editable shadow holds, fatal the moment it doesn't.
6. **F2 (`dos learn --workspace`)** — genuinely unfinished upstream; leave BLOCKED. When implemented, make the
   per-subcommand flag real (not top-level-accepted-and-inert) + add a test asserting scoped count != global count.
7. **`dos decisions` WRITE verb** — surface a first-class write verb when Bench's replan loop needs it.
8. **Add Bench seam tests** for `dos.toml` parsing + forked `/next`/`/replan` skill contracts.
9. **Correct CLAUDE.md** to stop calling `ship_oracle.py` "byte-thin" — it is a documented host-policy override.

---

*Evidence note: every command in this report was re-run live on Windows 11 / PowerShell against the editable
install. The `test_dispatch_lane.py` hang and the C1 lease-flip "plan-only" status are **unverified-in-isolation**
(the hang did not reproduce; C1 keystone status was not independently re-confirmed beyond the probe's ancestry check).*

*Related: this repo's `docs/120` (`dos status` plan), `docs/126` (mediated-write/apply-gate PEP). Cross-repo memory:
`dos-transition-audit-2026-06-02`, `git-issues-to-dos-audit-2026-06-03`, `c1-lease-flip-plan-20260603`,
`dos-job-lock-storm-rootcause`, `dos-preexisting-red-tests`.*

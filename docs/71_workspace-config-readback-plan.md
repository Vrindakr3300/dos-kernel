# WCR — Workspace-Config read-back plan (lanes & paths as `dos.toml` data)

> **Status:** ✅ **SHIPPED** (2026-06-01). Second in the genericization series
> ([SCV](70_stamp-convention-plan.md) → WCR →
> [RND](72_renderer-seam-plan.md) → [ADM](73_admission-predicate-plan.md) →
> [SKP](74_skill-pack-plan.md) → [DOS-HOME](75_state-home-plan.md)).
> `_apply_workspace` now reads back all four `dos.toml` data tables
> (`[reasons]`/`[stamp]`/`[lanes]`/`[paths]`) via `load_lanes_from_toml` +
> `PathLayout.with_overrides`/`load_paths_from_toml` (`config.py`), so a host
> stands up a real concurrent, correctly-pathed workspace with no driver. `--job`
> < TOML precedence is pinned and `dos doctor --check` flags treeless lanes.
> Pinned by `tests/test_workspace_config.py` (15 tests). Throughline-first, one
> separately-tested slice per phase.

## The gap this closes

`dos init` scaffolds a `dos.toml` with three policy tables — `[reasons]`,
`[lanes]` (+`[lanes.trees]`), and `[stamp]` (`cli.py:73-92`). **Only `[reasons]`
is read back.** `_apply_workspace` (`cli.py:46-67`) always builds the config from
`default_config(ws)` or `job_config(ws)` and then layers *only* the reasons
table on top:

```python
# cli.py — the lanes/stamp tables the init template just wrote are ignored
if getattr(args, "job", False):
    cfg = _config.job_config(ws)        # hardcoded JOB_LANE_TAXONOMY
else:
    cfg = _config.default_config(ws)    # hardcoded main/global
registry = _reasons.load_from_toml(toml_path, base=cfg.reasons)   # ONLY reasons
```

So an external repo that edits `[lanes]` to declare `apply`/`tailor`/`ui` lanes
gets a silent no-op: `dos arbitrate` still sees `main`/`global`. The scaffold
*promises* lane customization-via-data and doesn't deliver it. This is the same
class of bug SCV fixes for `[stamp]`: **a scaffolded table nothing reads back.**

The fix completes the "data in `dos.toml`, behavior in `entry_points`" promise
(`HACKING.md`) for the two remaining *data* axes — lanes and paths — so a host
can stand up a real, concurrent, correctly-pathed workspace **without writing a
driver**. (Writing a `drivers/<host>.py` module stays the option for policy that
needs *code*; this is the no-code path for policy that is *only data*.)

## Design laws this plan must honor

- **Kernel imports no host** (`CLAUDE.md`). Reading `[lanes]` from TOML produces a
  `LaneTaxonomy` value; it must never resurrect a hardcoded job lane in the
  kernel. The job taxonomy stays in `drivers.job`; TOML-declared lanes are pure
  workspace data.
- **A driver is the only place *code* policy lives.** WCR does **not** replace
  drivers — a driver can still do things data can't (computed trees, a factory
  that consults the environment). WCR is the floor: declare-only hosts need no
  Python. The precedence (Phase 3) makes the relationship explicit.
- **Additive degradation.** Mirror `reasons.load_from_toml` exactly: absent/empty
  table → built-in default unchanged; present-but-malformed → raise (surfaced).
  A workspace that declares nothing is byte-identical to today.

## North-star acceptance (the whole plan is done when)

```bash
dos init /tmp/svc && cd /tmp/svc
cat > dos.toml <<'TOML'
[lanes]
concurrent = ["api", "worker", "web"]
exclusive  = ["infra"]
autopick   = ["api", "worker"]
[lanes.trees]
api    = ["src/api/**"]
worker = ["src/worker/**"]
web    = ["web/**"]
infra  = ["deploy/**", "terraform/**"]
[paths]
plans_glob = "planning/*.md"
TOML
dos doctor --workspace .          # reports api/worker/web/infra — NOT main/global
dos arbitrate --workspace . --lane api --kind cluster --leases \
  '[{"lane":"worker","tree":["src/worker/**"]}]'   # ADMIT (disjoint trees)
dos arbitrate --workspace . --lane api --kind cluster --leases \
  '[{"lane":"web","tree":["src/api/handlers.py"]}]' # the overlap algebra runs on declared trees
```

…with no driver written and the existing suite green.

---

## Phase 1 — `[lanes]` read-back (the throughline)

The smallest end-to-end slice: a declared lane taxonomy reaches `arbitrate`.

- **1a.** Add `LaneTaxonomy.from_table(table: dict) -> LaneTaxonomy` to
  `config.py` (pure; mirrors `reasons.specs_from_table`): maps
  `concurrent`/`exclusive`/`autopick` arrays + the `[lanes.trees]` /
  `[lanes.aliases]` sub-tables onto the dataclass. Tolerant of missing keys
  (each defaults to `()` / `{}`); rejects a non-table or a tree value that isn't
  a list-of-strings with a `ValueError` naming the offending lane.
- **1b.** Add `config.load_lanes_from_toml(path, *, base)` (mirrors
  `reasons.load_from_toml`): a present `[lanes]` table *replaces* the base
  taxonomy (lanes aren't additive the way reasons are — a host declaring lanes
  means "these are my lanes," not "these plus job's"); absent → `base`
  unchanged; malformed → raise.
- **1c.** In `cli.py:_apply_workspace`, after the reasons load, layer the lanes
  load with the same warn-and-fall-back-on-malformed guard, and
  `dataclasses.replace(cfg, lanes=…)`.

**Litmus (Phase 1):**
- `tests/test_workspace_config.py::test_lanes_from_toml_reaches_arbiter` — a tmp
  workspace declaring `api`/`worker` trees produces an ADMIT for disjoint trees
  and a COLLISION for overlapping ones, *through the CLI path* (not just the
  pure function), proving `_apply_workspace` actually installed them.
- `test_no_lanes_table_is_unchanged` — a `dos.toml` with only `[reasons]` yields
  the identical taxonomy as today (additive-degradation proof).
- Litmus: kernel imports no host — `from_table` builds a value, names no job lane.

---

## Phase 2 — `[paths]` read-back (override the layout without a driver)

`PathLayout.for_root` bakes the job-shaped layout (`docs/_plans/…`,
`docs/**/*-plan.md`). A foreign repo whose plans live in `planning/*.md` can't
say so in data today.

- **2a.** Add `PathLayout.with_overrides(table: dict)` (pure): start from
  `for_root(root)`, then `dataclasses.replace` only the fields the table names
  (`plans_glob`, `execution_state`, `soaks_index`, …). Unknown keys raise (a
  typo'd path field is a host mistake worth surfacing). Relative paths resolve
  against `root`.
- **2b.** Fold `[paths]` (and the `plans_glob` that `[stamp]` in the init
  template currently also carries — reconcile to one home: `plans_glob` belongs
  to `[paths]`, the *grammar* belongs to `[stamp]`) into the
  `_apply_workspace` load chain.
- **2c.** `dos doctor` reports the resolved plans-glob and execution-state path so
  an operator can confirm the override took.

**Litmus (Phase 2):**
- `test_paths_override_changes_plan_discovery` — a workspace declaring
  `plans_glob="planning/*.md"` makes `verify` find a plan under `planning/` that
  the default glob would miss.
- `test_unknown_path_key_raises` — `[paths] plnas_glob=…` (typo) fails loud.

---

## Phase 3 — make the precedence explicit + the completeness rail

Three sources can now set lanes (the `--job` flag, a `dos.toml [lanes]`, the
`default_config` fallback). Nail the order down so it's not accidental, and guard
the open vocabulary.

- **3a.** Define and document the resolution order (highest first): an explicit
  `SubstrateConfig` passed in code (a direct library caller's `cfg=` argument to a
  syscall) › `dos.toml` tables › `--job` reference taxonomy › `default_config`
  generic. Encode the `dos.toml` › `--job` › default rungs once in
  `_apply_workspace` and state it in `HACKING.md`'s `dos.toml` section (today it
  only documents reasons). **NB the in-code rung lives at the API boundary, not on
  top of the CLI's rebuild:** a `dos` subcommand always rebuilds from the pointed-at
  workspace, so a `set_active(...)` done before a subcommand is deliberately NOT
  preserved (the workspace flag/cwd is authoritative for the CLI). The "explicit
  config in code" rung is reached by `oracle.is_shipped(cfg=…)` /
  `arbiter.arbitrate(config=…)`, not by `set_active` + a `dos` command.
- **3b.** *(completeness rail)* extend the `dos doctor --check` candidate from
  SCV: **a lane named in `[lanes].concurrent`/`autopick` but absent from
  `[lanes.trees]`** → a finding (a lane that feeds the disjointness algebra with
  no tree can't be arbitrated — nothing to prove disjoint or refuse for overlap).
  **Scope it to `concurrent`/`autopick` only, NOT `exclusive`:** an exclusive lane
  runs alone and is arbitrated on liveness — the arbiter never consults its tree —
  so a treeless exclusive lane is perfectly arbitrable (and the reference job
  taxonomy's `global` + the `dos init` scaffold's `global` are both legitimately
  treeless; scoping `exclusive` here false-flags them). This is the lane analogue of
  HACKING.md's "a reason emitted but not in the registry → fail." Land as a
  warning first.
- **3c.** Update the `dos init` template so every scaffolded table is one that is
  *actually read back* after this plan + SCV — no dead scaffold remains. Add a
  one-line header comment: "every table below is read by `dos` at workspace
  load; see HACKING.md."

**Litmus (Phase 3):**
- `test_precedence_toml_over_job_flag` — `--job` plus a `dos.toml [lanes]`
  resolves to the TOML lanes (TOML wins), and `dos doctor` says so.
- `test_doctor_check_flags_treeless_lane` — a lane in `concurrent` but not in
  `trees` is reported.

---

## Out of scope (explicitly)

- **Behavioral hooks in TOML.** Renderers and admission predicates are *code* and
  load via `entry_points` ([RND](72_renderer-seam-plan.md),
  [ADM](73_admission-predicate-plan.md)) — never declarable in `dos.toml`. WCR is
  strictly the *data* axes.
- **Computed taxonomies.** A host whose lanes depend on runtime state still
  writes a `drivers/<host>.py` factory; WCR doesn't try to make data do code's
  job. The driver path stays first-class.
- **Migrating `job` off its driver.** `job` keeps `drivers.job` /
  `job_config` — it has computed/reference policy. WCR adds the no-code path for
  *new* hosts; it does not force existing ones onto it.

## Why this is second

SCV makes `verify` reach a stranger's repo (strict-by-default, loose-on-opt-in);
WCR makes `arbitrate` and the plan-discovery layer configurable from data too —
together they let a host stand up a real workspace (correct lanes, correct paths,
correct ship grammar) entirely in `dos.toml`, no driver. WCR shares SCV's
`load_from_toml` shape and the `_apply_workspace` load chain it extends, and rides
the green/single-versioned base the concurrent commit `68b189b` established; the
two could ship in either order, but SCV's gap is the louder broken promise (and
the contested design call), so it leads.

Note the **deliberate asymmetry** with SCV: lanes/paths default to a *generic*
shape (`default_config`'s `main`/`global`) and a host *replaces* them with its
real taxonomy — declaring more is the safe direction. The stamp grammar defaults
to the *strict* job shape and a host *loosens* it only knowingly — because there
the permissive direction is the dangerous one (false-positive ships). Same
"declare-your-policy-as-data" mechanism, opposite safe defaults, for principled
reasons.

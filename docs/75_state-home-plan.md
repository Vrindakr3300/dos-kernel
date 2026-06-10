# DOS-HOME — the `.dos/` state-home plan (per-project emissions + machine-local projection)

> **Status:** ✅ **SHIPPED** (v1 + v2, 2026-06-01). Sixth plan of the
> genericization series, after [SCV](70_stamp-convention-plan.md) →
> [WCR](71_workspace-config-readback-plan.md) → [RND](72_renderer-seam-plan.md) →
> [ADM](73_admission-predicate-plan.md) → [SKP](74_skill-pack-plan.md). Where the
> earlier plans make a *single workspace* domain-free, this one makes DOS clean
> *across many* — its own state-home per project and a machine-local projection
> over every workspace it has served. `src/dos/home.py` ships
> `for_dos_dir`/`resolve_dos_home`/`HomeLayout`/`ensure_project_home`; the CLI
> creates `.dos/` lazily on the first persisting syscall (`cli.py`) and adds the
> `dos reindex`/`projects`/`learn` read-only home verbs. The four critique
> blockers (no `[paths]` override — since landed by WCR; UTC-named run dirs keep
> the picker regex; a cross-process `.home.lock` around the central JSONL on
> win32; `with_root` branches on `style`) are resolved as designed below. v1 =
> Phases 1–2 (layout swap + auto-create); v2 = Phases 3–4 (central indices +
> cross-project learning). Pinned by `tests/test_state_home.py`,
> `tests/test_ensure_home.py`, `tests/test_home_layering.py`,
> `tests/test_central_index.py`, `tests/test_reindex.py`. Throughline-first,
> observe-first, one separately-tested slice per phase.

---

## 1. The gap this closes

DOS was lifted out of the reference userland app, and it inherited that app's
body-plan along with its spine. The config seam (`PathLayout.for_root`) was
deliberately built to *reproduce the reference app's layout* so it would be "a
zero-surprise consumer"
(`config.py:107`): DOS's own emissions scatter across the served repo's `docs/`
tree — `docs/_fanout_runs/`, `docs/_dispatch_loops/`, `docs/_chained_runs/`,
`docs/_plans/lane-journal.jsonl`, `docs/_soaks/index.yaml`, `docs/_picker_audits/`,
`output/next-up/`. That was the right call for the first userland app, the way
`/bin` lived inside the one Unix tree before anyone separated the OS from the
disk it served. But it bakes a host's directory dialect into what is supposed to
be the **generic default**: a stranger who `dos init`s a fresh folder and runs a
persisting syscall today gets DOS scratch sprayed into a `docs/_fanout_runs/`
that means nothing in their repo, mingled with their source, untracked-by-accident
rather than untracked-by-design.

This plan gives the generic default its own body: a per-project **`.dos/`**
directory (sibling of `dos.toml`, gitignored-by-default, auto-created on the
*first write*) that collects every DOS emission under one re-derivable, deletable
tree — and a machine-local **DOS_HOME** (`~/.dos`, XDG-aware) holding a
*rebuildable projection* (`projects/index.jsonl`, `decisions.jsonl`) so an
operator running many DOS-backed repos can ask "what does this machine know"
without DOS ever becoming a database. The split is the whole design: **read-side
host truth (the plan registry the host curates) stays repo-relative; write-side
DOS emissions move under `.dos/`; the central store is a cache of digests that
`dos reindex` rebuilds from the `.dos/` dirs and never the source of truth.**

Crucially, this is — as the seam was built to allow — **almost entirely a
`PathLayout` change plus one new layer-1 module**. Every kernel consumer already
reads its state path through `config.active().paths.*` (verified module-by-module
in §6); no consumer derives a path from `__file__`. So the relocation is a new
`PathLayout` factory the generic `default_config()` adopts, while `job_config()`
keeps `PathLayout.for_root` byte-for-byte. The reference userland app does not
move, by construction.
The honest scope: a handful of consumers that *join onto* the relocated fields
(the picker_oracle run-dir filter, the run-dir naming convention) must be
reconciled with the collapse, and the central JSONL append needs a real
cross-process lock on Windows — both are blockers the critique caught and both
are resolved below, not waved past.

---

## 2. Design laws this must honor

These are the five hard constraints, each with the exact mechanism that satisfies
it. They are load-bearing, not advisory.

**Law 1 — THE REFERENCE USERLAND APP MUST NOT MOVE.** `job_config()` keeps
`PathLayout.for_root` (the `docs/_plans` layout) untouched (`config.py:247`). Only
`default_config()` (`config.py:258`) flips its factory call to the new
`PathLayout.for_dos_dir`. Every `from dos.X import *` shim in the reference app
resolves the identical `docs/_plans/…`
paths it does today. The new `PathLayout` fields are added **keyword-only with
defaults at the end of the dataclass** so `for_root`'s construction is unchanged
and no positional consumer breaks. `archive_lock` keeps its literal
`docs/_fanout_runs/.archive.lock` value in `for_root` (NOT re-derived from any new
field). Pinned by `test_state_home.py::test_job_config_layout_is_unchanged`.

**Law 2 — kernel imports/names no host.** `home.py`, `for_dos_dir`, `HomeLayout`,
`resolve_dos_home`, the `.dos/` vocabulary — all use only the generic
`main`/`global`/`.dos` tokens. No module under `src/dos/` except `drivers/` names
`job`/`apply`/`tailor`. The `.dos/` layout is *the generic default's business*,
installed by `default_config`, never by editing the kernel for a host. Pinned by
the existing `test_judge.py::TestBulkhead` AST-walk, extended to assert `home.py`
names no host and imports only `dos.config` + stdlib.

**Law 3 — layering / `decisions.py` stays a pure read-only projection.** `home.py`
is layer-1 kernel (stdlib + `dos.config` only, optionally a *downward* import of
`dos.archive_lock` for the lock helper). `config.py` imports neither `home` nor
any persist module (verified: it imports only `dos.reasons` + `dos.stamp`, both
stdlib leaves), so the dependency graph stays a DAG:
`config (leaf) ← home ← cli`, and `config ← {lane_journal, archive_lock, run_id,
oracle, …}`. `decisions.py` gains **no write path**: the resolved-decision digest
writer lives in `home.py` and is called by the CLI *action* layer, never by
`collect_decisions`. Pinned by `test_home_layering.py` (AST-walk) and
`test_decisions.py::test_decisions_module_has_no_write_primitives`.

**Law 4 — the seam is real (every path resolves against `SubstrateConfig`, never
`__file__`).** Verified §6: all 12 consumers read `cfg.paths.*` /
`config.active().paths.*`. Two documented env-override layers
(`DISPATCH_*_PATH`/`JOB_*_PATH`) sit *in front of* the seam in
`oracle`/`picker_oracle`/`lane_journal`/`archive_lock` — these are host escape
hatches, not bypasses, but they create a wrong-answer hazard under the `.dos/`
default (§6.4) that this plan addresses with a `dos doctor` warning, not a silent
inheritance.

**Law 5 — determinism + concurrent-safe writes.** No wall-clock or randomness in
any reproducible path: `project_id` is a pure function of the resolved root; run
dirs keep `run_id.mint` (clock/entropy injectable). The two genuinely
clock-sourced fields (`project.json.created_at`, `decisions.jsonl.ts_ms`) are
*event* stamps (allowed, same category as `lane_journal`'s `ts`) and take an
injectable `clock=` defaulting to `run_id._default_clock_ms`. Central-index
writes follow `lane_journal`'s fsync/torn-tail discipline — **and, because they
are cross-process with no shared `_StateFileLock` (unlike `lane_journal`), they
take a real `O_CREAT|O_EXCL` cross-process lock around the append/rewrite** (the
critique's blocker: `O_APPEND` alone is not atomic on win32, the stated primary
platform). The lock primitive is the one already in `archive_lock`.

---

## 3. North-star acceptance (the whole plan is done when)

```bash
# ── READ-ONLY in a foreign repo writes NOTHING (the safety property) ──────────
cd /tmp/foreign-repo && git init -q
dos verify --workspace . SOMEPLAN 1      # answers via=none from git alone
dos man wedge --workspace .              # projects the reason registry
dos doctor --workspace .                 # reports config + DOS_HOME location
dos decisions --workspace .              # pure projection over live sources
test ! -e .dos                           # ← no .dos/ created
test ! -e ~/.dos/projects/index.jsonl    # ← no central row written
                                         #   (read-only syscalls never persist)

# ── First PERSISTING syscall lazily creates .dos/ + one courtesy line ─────────
dos lease acquire --workspace . main
# stderr (exactly once): dos: created .dos/ for this workspace
#                        (/tmp/foreign-repo/.dos) — gitignored DOS state;
#                        `dos reindex` rebuilds central indices
test -d .dos/leases                      # the lock lives under .dos/leases/
test -f .dos/.gitignore                  # self-ignoring dir, host repo untouched
test -f .dos/project.json                # the identity card
grep -q '"project_id"' .dos/project.json

# ── A second project, then the central projection sees both ───────────────────
cd /tmp/other-repo && git init -q
dos lease acquire --workspace . main             # ensures .dos/ here too
dos projects                             # (v2) two rows, one per project_id

# ── reindex rebuilds the central store from the .dos/ dirs (projection) ───────
rm -rf ~/.dos/projects/index.jsonl
dos reindex                              # walks each known .dos/project.json
dos projects                             # ← identical two rows reconstructed

# ── the reference app is unmoved ──────────────────────────────────────────────
cd /work/userland-app && dos doctor --workspace . --job   # lane_journal still docs/_plans
```

The suite stays green throughout; new test files (§7) pin every new surface.

---

## 4. The full field mapping (`for_root` → `for_dos_dir`)

Let `r = Path(root).resolve()` and `d = r / ".dos"`. The principle, stated once:
**DOS's own emissions move under `.dos/`; the host's plan registry (the truth DOS
*reads*) stays repo-relative.**

| Field | `for_root` (reference app — UNCHANGED) | `for_dos_dir` (new generic default) | Class |
|---|---|---|---|
| `root` | `r` | `r` | — |
| `execution_state` | `r/docs/_plans/execution-state.yaml` | **`r/dos.state.yaml`** (§4.1) | host registry |
| `plans_glob` | `"docs/**/*-plan.md"` | `"docs/**/*-plan.md"` (STAYS — discovery glob, §4.1) | host registry |
| `findings_queue` | `r/docs/_plans/findings-followup-queue.md` | **`r/dos.findings.md`** (§4.1) | host workflow |
| `fanout_runs` | `r/docs/_fanout_runs` | `d/runs` | DOS emission |
| `dispatch_loops` | `r/docs/_dispatch_loops` | `d/runs` | DOS emission |
| `chained_runs` | `r/docs/_chained_runs` | `d/runs` | DOS emission |
| `next_packets` | `r/output/next-up` | `d/verdicts` | DOS emission |
| `replan_dir` | `r/docs/_replan` | `d/replan` | DOS emission |
| `soaks_index` | `r/docs/_soaks/index.yaml` | `d/soaks/index.yaml` | DOS emission |
| `picker_audits` | `r/docs/_picker_audits` | `d/picker_audits` | DOS emission |
| `archive_lock` | `r/docs/_fanout_runs/.archive.lock` | `d/leases/.archive.lock` (derived from `leases_dir`) | DOS lease |
| `lane_journal` | `r/docs/_plans/lane-journal.jsonl` | `d/lane-journal.jsonl` | DOS WAL |
| `leases_dir` *(NEW)* | `plans` (= `docs/_plans`) | `d/leases` | NEW field |
| `project_card` *(NEW)* | `None` | `d/project.json` | NEW field |
| `style` *(NEW)* | `"repo"` | `"dos"` | discriminator |

The three run-dir fields (`fanout_runs`, `dispatch_loops`, `chained_runs`)
**collapse to one value `d/runs`** under `for_dos_dir` (they remain three *fields*
for back-compat with `for_root`; under the generic default they are aliases).
`next_packets` **is** the verdicts dir — no separate `verdicts_dir` field is added
(one directory, one name; an optional read-only `@property verdicts_dir`
returning `self.next_packets` may be added for vocabulary, but it is not a schema
field). This resolves the cross-probe `verdicts_dir` contradiction in favor of
**`{leases_dir, project_card, style}` and the classmethod name `for_dos_dir`.**

### 4.1 RESOLVED — the generic registry location (execution_state / plans_glob / findings_queue)

The critique caught a real fork the probes left open: one probe copied the
reference app's `docs/_plans/execution-state.yaml` verbatim into the generic
default (secretly host-shaped), while another floated `dos.state.yaml` but left it
undecided. **Decision: do NOT copy the host's path. Use a generic, neutral
location, AND keep them
repo-relative (not under `.dos/`).** Specifically:

- `execution_state = r / "dos.state.yaml"` — repo-relative, generic name, NOT
  `docs/_plans/`. It is the host's plan registry, *host truth DOS reads, not
  scratch DOS writes*: CLAUDE.md is explicit that "phased-plan concepts are NOT in
  this package" and the kernel treats the registry as "an optional `source`."
  Moving it under `.dos/` would make `verify` answer `NOT_SHIPPED` against a repo
  that plainly has a registry; keeping it repo-relative preserves the
  read-inputs-in-repo / write-outputs-in-`.dos/` split that is *why* read-only
  `verify` never needs to create `.dos/`.
- `plans_glob = "docs/**/*-plan.md"` — stays. It is a *discovery glob*: in a repo
  with no such files it matches nothing and `verify` answers `via=none` (which
  `test_verify_no_plan.py` proves). Harmless as a default and the conventional
  place plan docs live.
- `findings_queue = r / "dos.findings.md"` — repo-relative, generic name. Same
  logic; no kernel consumer reads it (grep: zero reads), so its value only needs
  to be a non-host-shaped, non-colliding generic path.

**Why this is safe and not a regression:** `test_verify_no_plan.py:47` only
asserts the registry does *not exist* in a bare repo — any non-existent path
passes, so this choice is invisible to that test. Because the test can't catch a
wrong choice, the decision is pinned deliberately by
`test_state_home.py::test_generic_registry_is_not_job_shaped` (asserts
`"_plans" not in str(layout.execution_state)`). **The dependency on a `[paths]`
override is dropped entirely** (see §8): a foreign repo that keeps its registry
elsewhere cannot relocate it via `dos.toml` today because
`PathLayout.with_overrides` / `[paths]` read-back **do not exist** (verified:
`with_overrides` has zero code hits; `_apply_workspace` reads back only
`[reasons]` and `[stamp]`, never `[paths]`/`[lanes]`). That is a future
WCR-Phase-2 capability and this plan does not lean on it. The generic default's
repo-relative registry locations are therefore *fixed* until WCR lands — and
chosen to be generic, not host-shaped, so the default is honest about being
domain-free.

### 4.2 RESOLVED — run dirs stay UTC-named under `.dos/runs/` (the picker_oracle blocker)

The critique's blocker is real and verified: `picker_oracle._list_recent_runs`
(`picker_oracle.py`) hard-filters child dir names with
`re.match(r"^\d{8}T\d{6}Z", name)`, and the chained-run join sites
(`picker_oracle` envelope loaders, `cli.cmd_judge`'s `run_ts` positional,
`test_judge.py` seeding `chained_runs/20260531T010000Z/`) all key on a **UTC
timestamp string**. A `RID-…`-named dir would not match the regex and would not be
found by `dos judge`/sweep — every run silently invisible.

**Decision: run dirs under `.dos/runs/` keep their existing UTC-timestamp
directory names; `run_id` is carried *inside* the dir's `run.json`
(`process_id`/`parent_id`/`root_id`), NOT in the dir name.** This honors the
decided-design goal ("keyed by run_id, sortable+collision-safe+lineage") at the
*content* layer (`run.json`) while leaving the *directory grammar* — which the
kernel's only run-dir consumers (`picker_oracle`, `timeline`) parse — untouched.
The collapse of three dirs into one `.dos/runs/` is then a pure value change for
those readers: `_list_recent_runs`'s regex still matches, the `<run_ts>` join key
still resolves, `cli.cmd_judge`'s positional still works, and `test_judge.py`'s
seeding is unchanged. **Zero consumer code changes** — the "code is unchanged"
claim becomes *true* instead of internally inconsistent.

Note for honesty: the kernel does not itself *write* run dirs under these fields —
`write_run_json(run_dir, run)` takes a caller-supplied dir and the only kernel
caller is `run_id._cmd_mint --write-dir`; the run-dir-creation/partition logic
lives host-side (the reference app's `fanout_state`). So the collapse is transparent to the
kernel because the kernel only *reads* `chained_runs/<run_ts>/…`. We do not claim
`process_id` "replaces the three directories" at the kernel layer; we claim only
that the three fields aliasing to one dir is invisible to the kernel readers. The
lineage/process partition is a queryable field in `run.json` for whoever (host)
writes those dirs.

---

## 5. DOS_HOME resolution + central-store schemas

### 5.1 `resolve_dos_home()` — lives in `config.py`, beside `resolve_workspace_root`

It belongs in `config.py` (the layer-1 leaf that owns `resolve_workspace_root` and
`ENV_WORKSPACE`), keeping both precedence idioms side by side. `home.py` imports
it. Add `import sys` to `config.py` (it currently imports only `os`).

```python
ENV_DOS_HOME = "DISPATCH_HOME"

def resolve_dos_home(home: Path | str | None = None) -> Path:
    """Machine-local DOS_HOME root, per precedence (highest first):
      1. explicit `home` arg, 2. DISPATCH_HOME env, 3. XDG_DATA_HOME/dos,
      4. (win32) %APPDATA%\\dos, 5. ~/.dos.
    Path(...).resolve()'d on every branch (project_id keying must be stable).
    NEVER creates the dir — a read-only syscall must be able to ASK for the
    home path without a write happening (ensure_dos_home is the only creator)."""
    if home is not None:
        return Path(home).resolve()
    env = os.environ.get(ENV_DOS_HOME)
    if env:
        return Path(env).resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return (Path(xdg) / "dos").resolve()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return (Path(appdata) / "dos").resolve()
    return (Path.home() / ".dos").resolve()
```

### 5.2 `HomeLayout` — a separate frozen object; resolution is LAZY, not per-construction

The critique caught a real smell: hanging `home` on `SubstrateConfig` via
`field(default_factory=HomeLayout.for_home)` would re-resolve DOS_HOME on *every*
config construction (every read-only syscall, every test fixture), reading env
each time. **Decision: resolve lazily and cache, re-pointable like `_ACTIVE`.**
DOS_HOME is per-machine and root-invariant; it must NOT live on `PathLayout`
(which `with_root` rebuilds per workspace).

```python
@dataclass(frozen=True)
class HomeLayout:
    """Machine-local DOS_HOME paths — per-MACHINE, root-invariant. Distinct
    from PathLayout (per-workspace)."""
    home: Path
    config_toml: Path        # home / "config.toml"
    projects_index: Path     # home / "projects" / "index.jsonl"
    decisions_log: Path      # home / "decisions.jsonl"
    home_lock: Path          # home / ".home.lock"  (the cross-process mutex, §5.5)

    @classmethod
    def for_home(cls, home: Path | str | None = None) -> "HomeLayout":
        h = resolve_dos_home(home)
        return cls(home=h, config_toml=h / "config.toml",
                   projects_index=h / "projects" / "index.jsonl",
                   decisions_log=h / "decisions.jsonl",
                   home_lock=h / ".home.lock")
```

Process-cached module global in `config.py`, mirroring `active()`/`set_active()`:
`_ACTIVE_HOME`, `active_home()`, `set_active_home(h)`. Tests redirect either by
`monkeypatch.setenv("DISPATCH_HOME", …)` *before first `active_home()`*, or — the
robust idiom — by passing the optional `home=` arg that **every `home.py`
reader/writer accepts** (so a test never needs to rebuild or reset the cached
global). This is the established `DISPATCH_LANE_JOURNAL_PATH`-re-read-per-call
idiom applied to the home tier. `resolve_dos_home` and `HomeLayout` are
re-exported from `__init__.py` (symmetry with the existing seam re-exports).

### 5.3 `~/.dos` tree

```
$DOS_HOME/                  (resolve_dos_home())
├── config.toml             machine-global prefs (optional; absent = defaults)
├── .home.lock              cross-process mutex for the JSONL writes (§5.5)
├── projects/
│   └── index.jsonl         one logical row per known project (.dos/ seen)
└── decisions.jsonl         resolved-decision digests (append-only event log)
```

### 5.4 Exact schemas

**`.dos/project.json` (identity card — local truth, atomic tmp+`os.replace`):**

| field | type | source |
|---|---|---|
| `schema` | int | constant `1` |
| `project_id` | str | §5.6 id — **minted once at create-time, read back thereafter** |
| `root` | str | `str(cfg.paths.root)` (resolved) |
| `created_at` | str (ISO) | first-create stamp, **preserved across re-ensures** |
| `last_seen` | str (ISO) | refreshed each ensure call |
| `dos_version` | str | `dos.__version__` |

**`~/.dos/projects/index.jsonl` row (rebuildable projection; folded
last-write-wins by `project_id`):**

| field | type | source |
|---|---|---|
| `schema` | int | `1` |
| `project_id` | str | the card's id (the logical primary key) |
| `root` | str | last-known project realpath (mutable hint) |
| `dos_dir` | str | `str(cfg.paths.root / ".dos")` |
| `label` | str | `cfg.paths.root.name` (basename, for the human view) |
| `status` | str | `active` / `stale` / `moved` (set by reindex) |
| `first_seen` | str (ISO) | set once; preserved across re-projections |
| `last_indexed` | str (ISO) | refreshed each write/reindex |
| `run_count` | int | count of `.dos/runs/<utc>` dirs at projection time |
| `wedge_count` | int | count of WEDGE-shaped verdict envelopes under `.dos/verdicts/` |
| `refusal_count` | int | count of `OP_REFUSE` rows in `.dos/lane-journal.jsonl` |

All counts are derived by **counting on-disk artifacts**, never a clock read.
`first_seen`/`last_indexed` are event stamps (injectable `clock=`).

**`~/.dos/decisions.jsonl` row (resolved-decision digest; append-only event log):**

| field | type | source |
|---|---|---|
| `schema` | int | `1` |
| `project_id` | str | which project |
| `label` | str | project basename |
| `kind` | str | `Decision.kind.value` (`WEDGE`/`ARBITER_REFUSE`/…) |
| `resolver_kind` | str | `Decision.resolver_kind.value` (`HUMAN`/`ORACLE`/`JUDGE`) |
| `lane` | str | `Decision.lane` |
| `reason_token` | str | the WedgeReason/registry token, or `""` |
| `reason_category` | str | `cfg.reasons.category_for(token)` (denormalized so `dos learn` groups without re-reading each registry) |
| `run_ts` | str | the chained-run dir name, if known |
| `resolution` | obj | `{"action": "force_acquire"|"soak_closed", …}` (§5.7) |
| `ts_ms` | int | event time (injectable `clock=`; allowed — a journal stamp, not a path) |

### 5.5 Append discipline — `lane_journal`'s fsync/torn-tail pattern PLUS a real cross-process lock

The critique's blocker is correct and decisive: the probes leaned on "`O_APPEND`
of one line is atomic w.r.t. other appenders" as the *sole* serialization — but
that POSIX guarantee does not hold on win32 (the stated primary platform, the very
reason `archive_lock` exists), and `lane_journal.append` itself is only safe
because *its caller holds `_StateFileLock`* (`lane_journal.py`: "the surrounding
`_StateFileLock` already serializes our own callers; `O_APPEND` is the belt to
that suspenders"). The central store has no such caller lock. **Decision:**

- `home.py` provides `_append_jsonl(path, row, *, home=None, clock=…)` that reuses
  `lane_journal`'s exact discipline —
  `json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)+"\n"`,
  `parent.mkdir(parents=True, exist_ok=True)`,
  `os.open(O_WRONLY|O_APPEND|O_CREAT)` → `os.write` → `os.fsync` — **drop the
  `seq` field and `next_seq()`** (computing a monotonic seq requires reading the
  whole file under a lock to find max+1, which would reintroduce the
  read-modify-write race; the central store has no replay-ordering invariant that
  needs it).
- **All central-store writes — both `_append_jsonl` and reindex's whole-file
  `os.replace` rewrite — are wrapped in a cross-process `O_CREAT|O_EXCL` lock on
  `$DOS_HOME/.home.lock`** (the same primitive `archive_lock._write_lock` already
  uses, with retry/TTL). This serializes the hot `ensure_project_home` append
  against reindex's atomic rewrite, so an append can never land between reindex's
  read and its `os.replace` (the critique's "dropped row" race). `home.py` may
  import `dos.archive_lock` *downward* for the lock helper (`archive_lock` imports
  only `dos.config`, so a `home → archive_lock → config` edge is still acyclic);
  prefer the import to duplication.
- Readers reuse `lane_journal.read_all`'s torn-tail rule **verbatim**: skip an
  unparseable *trailing* line (crash mid-append), surface a `_CORRUPT` sentinel
  for a mid-file bad line. Since `~/.dos` is rebuildable, a `_CORRUPT` in
  `index.jsonl` simply means "reindex"; reusing the proven reader is cheaper than
  arguing a weaker one.

Whole-file `index.jsonl` rewrites (reindex compaction) use the atomic
tmp+`os.replace` discipline from `run_id.write_run_json`. **Litmus: a Windows
concurrent-append test** (`test_central_index.py::test_concurrent_appends_survive`)
spawns two processes each appending N rows and asserts all 2N rows survive
uncorrupted and no row is lost to a reindex rewrite running concurrently.

### 5.6 `project_id` — deterministic, path-derived, with a card-authoritative tiebreaker

```python
def project_id_for(workspace_root: Path | str) -> str:
    """16 hex chars (64 bits) of SHA-256 over the resolved POSIX path.
    Deterministic: same realpath -> same id, no clock, no random."""
    real = Path(workspace_root).resolve().as_posix()
    return hashlib.sha256(real.encode("utf-8")).hexdigest()[:16]
```

The critique is right that this is *not* stable across the win32/WSL path-view
split (`C:\repo` vs `/mnt/c/repo` hash differently). **Decision: the id is
minted ONCE at `.dos/project.json` create-time and read back thereafter; the card
is authoritative.** `project_id_for(root)` is only used to *mint* on first ensure
(when no card exists) and to detect `moved` (a card whose stored id matches but
whose `dos_dir` differs from the registry hint). The recompute-must-agree
assertion is therefore scoped to the *same path view* — pinned by
`test_state_home.py::test_project_id_matches_card_same_view`. Cross-view stability
is explicitly **out of scope** (§8); a project accessed via two OS path views gets
two cards/ids, and reindex *surfaces* (does not silently merge) a 64-bit
truncation collision via `test_central_index.py::test_reindex_surfaces_id_collision`
(two distinct roots mapping to one id → a flagged finding, not a merge).

### 5.7 The resolved-decision capture points — and the `dos judge` read-only contradiction, RESOLVED

The critique caught a direct contradiction: one probe proves `dos judge` is
READ-ONLY (writes nothing, preserves the safety property), while another has
`cmd_judge` call `home.append_decision` (a `~/.dos` write). They cannot both ship.
**Decision: the safety property wins — `dos judge` stays READ-ONLY and writes
nothing.** Resolved-decision capture is wired only to genuinely-persisting
operator acts, and made idempotent:

| Resolving action | Resolver kind | Trigger | `resolution` |
|---|---|---|---|
| `dos arbitrate --force` producing an `acquire` a non-forced call would have refused | HUMAN | `args.force and decision.outcome == "acquire" and not would_acquire_unforced` | `{"action":"force_acquire","lane":L,"forced":true}` |
| soak window closing | HUMAN→auto | reindex-time diff (no live actor) | `{"action":"soak_closed","phase":P}` |

`dos judge`'s ruling is **not** captured as a resolution (it is read-only and
idempotent — running it N times would otherwise multiply rows). The JUDGE-tier
calibration signal (`oracle_disagrees`) is still recoverable in v2 by re-deriving
from the verdict envelopes in `.dos/` during reindex, not by a live write on the
read path. `dos arbitrate --force` is *the* architecturally-blessed attributable
operator override (the SCV plan calls it the model for explicit overrides), so it
is the right HUMAN capture point; it is reached only on a persisting path. The
append is deduped by `(project_id, lane, run_ts, action)` so a repeated force is
one logical resolution. This keeps the headline safety property intact (§6.5) and
keeps `decisions.py` pure (the writer is `home.append_decision`, called by
`cli.cmd_arbitrate`, never by `collect_decisions`).

---

## 6. `ensure_project_home` semantics + acyclic imports + read-only-writes-nothing proof

### 6.1 `ensure_project_home(cfg, *, home=None, clock=…, _stderr=sys.stderr) -> Path`

New layer-1 module `src/dos/home.py` (stdlib + `dos.config`, optionally a downward
import of `dos.archive_lock` for the lock helper — see §5.5). Idempotent; safe to
call on every persist. Behavior, in order:

1. `dot_dos = cfg.paths.root / ".dos"` (a derived property `cfg.paths.dot_dos`
   returning `self.root / ".dos"` is added to `PathLayout` for vocabulary — a
   property, **not** a stored field, so it does not duplicate `root`).
2. **First-time detection via atomic create** (the TOCTOU fix): attempt
   `os.mkdir(dot_dos)` (NOT `exist_ok`); `first_time = True` iff it succeeds,
   `False` on `FileExistsError`. Exactly-once across concurrent processes (only
   one `mkdir` wins) — no check-then-act race. Then `os.makedirs(dot_dos,
   exist_ok=True)` is a no-op safety net for parents.
3. Write `.dos/.gitignore` if absent (never overwrite — §9 content).
4. Write/update `.dos/project.json` (atomic tmp+`os.replace`): if the card exists,
   read it, preserve `created_at` + `project_id`, refresh `last_seen` +
   `dos_version`; if absent, mint `project_id = project_id_for(cfg.paths.root)`
   and stamp `created_at`.
5. Under the `$DOS_HOME/.home.lock` (§5.5), append/update the central
   `projects/index.jsonl` row. A failure to write the *central* index is
   **best-effort** (wrap, log to stderr, never raise) — the project home is truth,
   the central index is rebuildable. A failure to create `.dos/` itself **does**
   propagate (the persist that follows would fail anyway).
6. If `first_time`: emit exactly one stderr courtesy line naming `dot_dos`.
7. Return `dot_dos`.

Idempotency holds: step 2 is atomic-create-once, step 3/4 are
write-if-absent/preserve, step 5 is locked-append-last-wins, step 6 is gated on
the atomic `first_time`. 1000× = one `.dos/`, one `.gitignore`, one courtesy line,
N folded index rows.

### 6.2 Where the hook fires — the CLI layer, declaratively

Fire in the CLI, after `_apply_workspace`, before dispatching a *persisting*
subcommand — the kernel persist fns stay ignorant of `home`. Add
`_ensure_home_if_persisting(args)` called by persisting handlers; classify
subcommands declaratively (a `persists=True` per-subparser default or a
`_PERSISTING` set in `main()`). The umbrella CLI's only persist points today:
`dos lease {acquire,release}` and `dos arbitrate --force` (the latter only when it
captures a resolution). `cmd_init` is the special case: it writes `dos.toml` (the
config sibling), NOT `.dos/`, and must **not** ensure — `.dos/` is created lazily
by the first real *emission*. The kernel `mkdir`s (`lane_journal`, `archive_lock`,
`run_id`, `picker_oracle.cmd_sweep`) stay — they are also reached as *library*
calls by in-process hosts (the reference app's `fanout_state` appends to the WAL directly);
`ensure_project_home` guarantees the *identity scaffolding*, the per-write `mkdir`
guarantees the *durability floor*. They compose, idempotently.

### 6.3 The acyclic import arrangement

The critique verified there is **no cycle** as designed, and the design keeps it
that way: `config.py` imports only `dos.reasons` + `dos.stamp` (stdlib leaves);
`home.py` imports `dos.config` (and optionally `dos.archive_lock`, which itself
imports only `dos.config` — a downward edge, still a DAG);
`lane_journal`/`archive_lock`/`run_id` do **not** import `home`; only the CLI
(layer 3) imports `home` and the persist modules together. Resulting DAG:
`config (leaf) ← home ← cli`, `config ← {archive_lock ← home}`,
`config ← {lane_journal, run_id, oracle, …}`. **Pinned as a litmus**
(`test_home_layering.py`, AST-walk like `test_judge.py::TestBulkhead`): `home.py`
imports only `dos.config` + `dos.archive_lock` + stdlib; no `src/dos/*.py` except
`cli.py`/`drivers/` imports `dos.home`.

### 6.4 The env-override hazard — a `dos doctor` warning, not silent inheritance

The critique found a real wrong-answer path: `oracle._state_path()` /
`picker_oracle._state_path()` read `JOB_FANOUT_STATE_PATH`/`DISPATCH_STATE_PATH`
*unconditionally before* the active cfg, so an operator with `DISPATCH_STATE_PATH`
exported in their shell (common for reference-app devs) running `dos verify`/`dos judge`
against a new `.dos/` workspace silently reads the *reference app's* state file, not the
`.dos/` one. **Decision: do not change the env precedence (the reference app + tests rely on
it), but make the hazard loud:** `dos doctor` emits a warning line when an env
path override is set *and* the active layout's `style == "dos"` (`warning:
DISPATCH_STATE_PATH overrides the .dos/ default — verify/judge will read <env
path>, not <.dos/ path>`). `dos reindex` and `home.py` read `cfg.paths.*` only,
never the env vars. Pinned by
`test_state_home.py::test_doctor_warns_on_env_override_under_dos_layout`.

### 6.5 Read-only-writes-nothing — proof by three independent guarantees

**Claim:** `dos verify`/`man`/`doctor`/`decisions`/`judge`/`journal
{tail,replay,seq}` in a foreign repo create no `.dos/`, no `~/.dos` row, no
`.gitignore`.

1. **The hook is never reached.** `ensure_project_home` is invoked only from
   `_ensure_home_if_persisting`, called only by persisting handlers (`lease
   {acquire,release}`, `arbitrate --force`-on-capture). No read-only handler calls
   it. `home.py`'s top level only defines functions (no import side effect).
   Importing `dos`/`dos.cli` runs no ensure.
2. **The underlying syscalls are themselves writeless.** `verify` →
   `oracle.is_shipped` (registry read + `git log`, pinned writeless by
   `test_verify_no_plan.py`); `man`/`doctor` → registry/lane projection +
   `.git`-existence check; `decisions` → `collect_decisions` (declared pure,
   readers `return []` on missing source); `judge` → `_classify_one` (the CLI
   never calls `cmd_sweep`, the only picker_oracle writer); `journal
   {tail,replay,seq}` → `read_all`/`replay`/`next_seq` (no CLI `append`). With
   `dos judge` now firmly READ-ONLY (§5.7), this guarantee is unbroken.
3. **A read of a path never creates it.** Every seam read guards on `.exists()`
   (`oracle`, `decisions._from_*`, `archive_lock._read_lock`,
   `run_id.read_run_json`); `resolve_dos_home`/`HomeLayout.for_home` are pure path
   math, never `mkdir`; the kernel `mkdir`s live exclusively inside write fns no
   read-only verb reaches.

Therefore: zero workspace mutation and zero `~/.dos` mutation on the read-only
path. The first *persisting* verb is the first `.dos/` create, with exactly one
courtesy line. ∎ Pinned by
`test_ensure_home.py::TestReadOnlySyscallsWriteNothing` (one case per read-only
verb).

---

## 7. Phase breakdown

**v1 = Phase 1 (layout + resolver) + Phase 2 (ensure + auto-create). v2 = Phase 3
(central indices populated) + Phase 4 (reindex + cross-project queries +
doctor/HACKING).** Each slice is separately tested, matching `tests/` style
(`tmp_path`, `default_config(tmp_path)`, `monkeypatch.setenv/delenv`, `capsys`,
classes grouping behavior, active-config save/restore fixture).

### Phase 1 — `for_dos_dir` + `resolve_dos_home` (pure, no writes)

- **1a.** Add to `PathLayout` (keyword-only, defaulted, at END of dataclass):
  `leases_dir: Path = None`, `project_card: Path | None = None`, `style: str =
  "repo"`. Add `@property dot_dos` (`self.root / ".dos"`) and `@property
  verdicts_dir` (`self.next_packets`). Set `leases_dir`/`style` in `for_root`
  (`leases_dir=plans`, `style="repo"`, `project_card=None`); `archive_lock` stays
  the literal `_fanout_runs/.archive.lock`.
- **1b.** Add `PathLayout.for_dos_dir(root)` classmethod per §4 (`style="dos"`,
  three run-fields → `d/runs`, `next_packets→d/verdicts`, `archive_lock` derived
  from `leases_dir=d/leases`, registry trio at generic repo-relative locations
  §4.1).
- **1c.** Fix `with_root` to branch on `self.paths.style` (REQUIRED — not the
  path-equality sniff): `factory = PathLayout.for_dos_dir if self.paths.style ==
  "dos" else PathLayout.for_root`. (`with_root` has zero live callers today, so
  this is fixing a latent trap, but it is the re-point path for Law 1 and must be
  correct before `default_config` flips.)
- **1d.** `config.py`: add `import sys`, `ENV_DOS_HOME`, `resolve_dos_home`,
  `HomeLayout`, `active_home`/`set_active_home`. Re-export
  `resolve_dos_home`/`HomeLayout` from `__init__.py`.
- **1e.** Flip `default_config` to `PathLayout.for_dos_dir(root)`; leave
  `job_config` on `for_root`.

**Litmus (Phase 1) — `tests/test_state_home.py`:**
- `test_dos_emissions_live_under_dot_dos` — every DOS-emission field under
  `tmp_path/".dos"`.
- `test_run_dir_trees_collapse_to_one` — `fanout_runs == dispatch_loops ==
  chained_runs == d/runs`.
- `test_archive_lock_is_under_leases` — `archive_lock == d/leases/.archive.lock`.
- `test_generic_registry_is_not_job_shaped` — `"_plans" not in
  str(execution_state)`; `execution_state == r/"dos.state.yaml"` (§4.1 pin).
- `test_job_config_layout_is_unchanged` — `job_config(tmp).paths.lane_journal`
  under `docs/_plans/`; `archive_lock` literal `docs/_fanout_runs/.archive.lock`;
  `style == "repo"` (Law 1 proof).
- `test_default_uses_for_dos_dir` — `default_config(tmp).paths.style == "dos"`;
  `lane_journal` under `.dos/`.
- `test_with_root_preserves_style` — `default_config(a).with_root(b).paths.style
  == "dos"` and points under `b/.dos`; `job_config(a).with_root(b)` stays
  `for_root`.
- `test_pathlayout_field_order_locked` — constructs `for_root` and `for_dos_dir`,
  asserts full field set + the `archive_lock` asymmetry (literal vs
  leases-derived); pins field order so a future mid-struct insert can't break
  positional construction.
- `TestResolveDosHome` — `test_dispatch_home_env_wins`,
  `test_xdg_data_home_second`, `test_win32_appdata_third`
  (`monkeypatch.setattr(sys,"platform","win32")`), `test_home_fallback_last`,
  `test_win32_falls_to_home_when_no_appdata`.
- `TestProjectId` — `test_project_id_is_deterministic`,
  `test_project_id_differs_by_root`, `test_project_id_normalizes_root`.

### Phase 2 — `home.py` ensure + auto-create-on-first-write

- **2a.** New `src/dos/home.py`: `project_id_for`, `_home_lock` ctx (§5.5),
  `_append_jsonl`, `ensure_dos_home(home=None)` (lazy mkdir + one-time courtesy on
  home create), `ensure_project_home(cfg, *, home=None, clock=…, _stderr=…)` per
  §6.1.
- **2b.** `cli.py`: add `_ensure_home_if_persisting(args)` called after
  `_apply_workspace` in `cmd_lease`; declare `persists` per subparser; `cmd_init`
  deliberately does not ensure.
- **2c.** Repo `.gitignore`: add `.dos/` (§9). Write the shipped `.dos/.gitignore`
  template in `ensure_project_home` (§9).

**Litmus (Phase 2) — `tests/test_ensure_home.py`** (all set
`monkeypatch.setenv("DISPATCH_HOME", str(tmp_path/"home"))`):
- `TestLazyCreate`: `test_first_write_creates_dot_dos`,
  `test_project_json_is_identity_card` (carries `project_id ==
  project_id_for(root)`, `created_at`, `dos_version`), `test_idempotent` (twice;
  `created_at` + content stable), `test_gitignore_written_with_star`.
- `TestReadOnlySyscallsWriteNothing`: `test_verify_creates_no_dot_dos`,
  `test_doctor_creates_no_dot_dos`, `test_decisions_collect_creates_no_dot_dos`,
  `test_man_creates_no_dot_dos`, `test_judge_creates_no_dot_dos` (the §5.7
  resolution — judge is read-only).
- `TestCourtesyLine` (`capsys`): `test_first_persist_prints_one_courtesy_line`,
  `test_courtesy_line_not_repeated`, `test_concurrent_first_create_prints_once`
  (the §6.1 step-2 atomic-create exactly-once).
- `tests/test_home_layering.py`: `test_home_imports_only_config_and_stdlib`,
  `test_no_kernel_module_imports_home` (AST-walk).

### Phase 3 — central indices populated (v2)

- **3a.** `ensure_project_home` appends the `projects/index.jsonl` row under
  `.home.lock` (§5.5, §6.1 step 5) — already wired in 2a; this phase pins it and
  adds the count fields.
- **3b.** `home.append_decision(cfg, row, *, home=None, clock=…)` (the
  resolved-decision digest writer). Wire the **`dos arbitrate --force`** capture
  point in `cli.cmd_arbitrate` (§5.7), deduped by `(project_id, lane, run_ts,
  action)`. `decisions.py` is NOT touched (Law 3). Also mirror the resolution to
  the project's own `.dos/decisions/resolved.jsonl` (local truth — see the
  rebuildability note at the end of §7).
- **3c.** `dos doctor` reports `~/.dos` location + project count (one line);
  emits the env-override warning (§6.4).

**Litmus (Phase 3) — `tests/test_central_index.py`:**
- `TestProjectsIndex`: `test_ensure_home_appends_a_projects_row`,
  `test_second_project_appends_second_row`, `test_reensure_folds_to_one_row`
  (last-write-wins by `project_id`).
- `TestDecisionsIndex`: `test_force_acquire_appends_digest` (HUMAN, via
  `cmd_arbitrate --force`), `test_judge_appends_nothing` (READ-ONLY — the §5.7
  contradiction pinned), `test_force_dedup` (repeated force = one logical row).
- `TestConcurrency`: `test_concurrent_appends_survive` (Windows; two processes × N
  rows, all 2N survive uncorrupted), `test_append_under_home_lock` (spy
  `archive_lock` lock acquire); `TestTornTail`: `test_partial_final_line_skipped`,
  `test_corrupt_middle_line_surfaced`.
- `test_doctor_reports_dos_home_and_count`,
  `test_doctor_warns_on_env_override_under_dos_layout`.

### Phase 4 — reindex + cross-project queries + HACKING (v2)

- **4a.** `home.reindex(home=None, *, prune=False)` per the algorithm: read
  `projects/index.jsonl` (torn-tail tolerant) → fold last-per-`project_id` → for
  each, follow the card, re-stat counts via `PathLayout.for_dos_dir(meta["root"])`
  (NO env vars), mark `active`/`stale`/`moved` (never crash; `--prune` drops
  stale), diff soak-closes (§5.7, the one reindex-time capture), atomic-rewrite
  `index.jsonl` under `.home.lock`, append soak-close decision rows. Sorted by
  `project_id` for byte-stable output.
- **4b.** `dos projects` (registry view: `LABEL ROOT STATUS LAST_INDEXED #runs`;
  `--stale`/`--json`) and `dos learn {wedge-hotspots,lane-refusals,oracle-calibration}`
  — pure group-bys over `decisions.jsonl`, read-only, degrade-to-empty with a "run
  `dos reindex`" hint on a stale index. These are the new read-only syscalls of
  the home tier (write nothing).
- **4c.** `dos reindex` CLI verb; `dos doctor --check` index-staleness warning.
- **4d.** HACKING.md: document the `.dos/` + DOS_HOME contract beside the
  reasons/stamp axes; `dos learn` is the fifth surface a single reason declaration
  lights up (`reason_category` in the digest comes from the active
  `ReasonRegistry`).

**Litmus (Phase 4) — `tests/test_reindex.py`:**
- `test_reindex_rebuilds_projects_from_cards` (delete `index.jsonl`, reindex two
  cards, both rows reconstructed — projection-not-sync proof).
- `test_reindex_marks_stale_not_crash` (a card whose root is gone →
  `status:"stale"`, no exception).
- `test_reindex_prune_drops_stale`, `test_reindex_is_idempotent` (twice →
  byte-identical index), `test_reindex_surfaces_id_collision` (§5.6).
- `test_reindex_diffs_soak_close` (a window open last-index, now closed → one
  `soak_closed` row; re-running does not re-emit).
- `tests/test_learn.py`: `test_wedge_hotspots_groups_by_project`,
  `test_lane_refusals_groups_by_lane`, `test_oracle_calibration_groups_by_category`,
  `test_learn_degrades_on_stale_index`.

**The `decisions.jsonl` rebuildability tension, RESOLVED:** adopt
**mirror-locally-then-project** to keep the projection-not-sync contract exact.
The `force_acquire` capture point also appends the resolution to the project's own
`.dos/decisions/resolved.jsonl` (local truth); `~/.dos/decisions.jsonl` becomes a
pure projection of those local logs that `reindex` fully rebuilds. Cost is one
extra local append per resolution — trivial, and it means every byte of `~/.dos`
is rebuildable by walking `.dos/`, honoring "`~/.dos` is never the source of
truth" without an asterisk. (soak-closes are reindex-derived from `.dos/soaks/`
and need no local mirror.)

---

## 8. Out of scope (explicitly)

- **`PathLayout.with_overrides` / `[paths]` & `[lanes]` read-back.** These DO NOT
  EXIST (`with_overrides`: zero code hits, only a `stamp.py` comment;
  `_apply_workspace` reads back only `[reasons]` and `[stamp]`). This plan **does
  not build them and does not depend on them** — the generic registry locations
  (§4.1) are fixed repo-relative defaults until a future WCR-Phase-2 lands. No
  part of this design's correctness rests on overriding a path via `dos.toml`.
- **`run_id`-named run directories.** Run dirs stay UTC-named under `.dos/runs/`
  (§4.2); `run_id` lives in `run.json` content, not the dir name. Renaming dirs to
  `RID-*` (and updating `picker_oracle._list_recent_runs`'s regex + every
  `<run_ts>` join site + `cli.cmd_judge`'s positional + `test_judge` seeding) is a
  separate, later plan if a consumer needs it.
- **Cross-OS-path-view `project_id` stability** (win32 vs WSL). The card is
  authoritative per path-view (§5.6); a project reached via two views gets two
  ids. Drive-mapping normalization is out of scope.
- **`dos judge` as a write/capture point.** It stays read-only (§5.7). JUDGE-tier
  calibration is re-derived from verdict envelopes at reindex time in a later
  hardening, never on the read path.
- **Migration of any pre-existing generic-default state.** Verified: no on-disk
  `for_root`-shaped state exists for a non-host generic workspace today. The switch
  is forward-only; a hypothetical orphan under `docs/_fanout_runs` is harmless and
  re-derivable. No automatic migration is provided (back-flow is
  projection-not-sync, not migration).
- **`dos learn` aggregates beyond the three** (wedge-hotspots / lane-refusals /
  oracle-calibration). They map one-to-one to the three closed axes
  (`DecisionKind`, `lane`, `resolver_kind`×`oracle_disagrees`); cost/latency
  metrics need fields not captured and wait for a consumer.
- **`config.toml` machine-global policy.** The file exists (so `$DOS_HOME` isn't
  opaque) with `schema` + `[index] auto_reindex`, read via the `tomllib`/`tomli`
  -degrade ladder; richer machine-global prefs are deferred.

---

## 9. The `.gitignore` deltas

### A. The `dos` repo's own `.gitignore` — YES, add `.dos/`

After `default_config` adopts `for_dos_dir`, any persisting run from the repo root
(`dos lease acquire`, future writers) creates a `.dos\` directory in this
repository. The repo
`.gitignore` ignores `.dos-workspace/` but **not** `.dos/`. Add it to the existing
"DOS state / scratch" block, right after `.dos-workspace/`:

```
# DOS state / scratch (re-derivable; never tracked in the OS repo itself —
# the OS is stateless about which workspace it serves)
_scratch/
*.err
.dos-workspace/
.dos/
```

### B. The shipped `.dos/.gitignore` template (written by `ensure_project_home`, write-if-absent)

A self-ignoring directory, so a host repo needs zero `.gitignore` edits of its own:

```gitignore
# DOS per-project state — re-derivable emissions (runs, leases, verdicts,
# lane journal, soak index). DOS auto-created this directory and ignores its own
# contents so they never enter your repo's history. Safe to delete; DOS rebuilds
# with `dos reindex`. See dos/CLAUDE.md.
*
!.gitignore
```

`*` + `!.gitignore` makes the whole `.dos/` tree untracked from the host repo's
view without touching the host's root `.gitignore`. `project.json` is therefore
also untracked — consistent with the central index being a rebuildable,
machine-local projection (state does not survive a clone; `reindex` walks *live*
`.dos/` dirs on this machine, which is intended). `ensure_project_home` writes this
only if absent (never overwrites a host's customization), pinned by
`test_ensure_home.py::test_gitignore_written_with_star`.

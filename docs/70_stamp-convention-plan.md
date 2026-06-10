# SCV — Stamp-Convention plan (make the truth syscall domain-free)

> **Status:** ✅ **SHIPPED** (all three phases, 2026-06-01). Lead plan of the
> genericization series (SCV → [WCR](71_workspace-config-readback-plan.md) →
> [RND](72_renderer-seam-plan.md) → [ADM](73_admission-predicate-plan.md) →
> [SKP](74_skill-pack-plan.md) → [DOS-HOME](75_state-home-plan.md)).
> `phase_shipped.py` resolves the active `StampConvention` through one
> `_subject_matchers(cfg)` helper on **every** entrypoint (P1); `cli.py` reads
> back `[stamp]` and honors the warned `style="loose"` opt-in (P2); `dos doctor`
> names the active grammar and `--check` flags a declared `[stamp]` that covers
> none of the repo's own ship-shaped commits (P3). Strict job grammar stays the
> default. Pinned by `tests/test_stamp_convention.py` + `tests/test_stamp_doctor.py`
> (17 tests) and the unchanged-strict `tests/test_verify_no_plan.py`.
> Throughline-first, observe-first, one separately-tested slice per phase.

## The gap this closes — and the design tension at its heart

DOS's North Star says *"`verify()` works against a plain git repo with no phased
plan, answering from git history alone."* It does — but the no-plan git rung
recognizes only *job-repo* commit-subject conventions:

```python
# src/dos/phase_shipped.py:206
_DIRECT_PREFIX = r"(?:docs|go|agents|job_search|scripts)"   # job's top-level dirs
```

A direct ship matches `<dir>/<SERIES>: <PHASE>` (those dirs) and a summary bundle
matches `vX.Y.Z:` / `docs/HYG:`. A foreign repo committing
`AUTH2: ship token refresh` or `feat(auth): …` resolves to `NOT_SHIPPED`.

**Two readings of "generic" collided here — and the operator resolved them
(strict-default, loose-opt-in).** A concurrent commit (`68b189b`,
"verify(cfg=): wire the no-plan git rung") took one side deliberately: it wired
the *plumbing* (`is_shipped(plan, phase, cfg=…)` fills `state` + a default
git-log `grep_fallback` from the config) but **kept the subject grammar
hardcoded and strict**, and fixed the red `test_verify_no_plan.py` cases by
*conforming the fixtures to job's grammar* — explicitly *"rather than loosening
the deliberately-strict detector."* That strictness is load-bearing
(`project-dos-kernel-design-laws` §1): a too-loose grep rung resurrects
false-positive ship detection — the false-`DRAIN`-archive storms that spawned
job's entire QWB plan series. Trusting a vague subject as a ship is the exact
failure the oracle exists to prevent.

The other reading — a stranger should point DOS at their *existing* repo and have
`verify` work on the commits they already write — is also real, and is what
`dos init` implies by scaffolding `[stamp] style="grep"` into `dos.toml`
(`cli.py:89`) that nothing reads back.

**The resolution this plan implements: strict by default, loose by explicit
opt-in.** The stamp grammar becomes declared data on `SubstrateConfig` (a
`StampConvention`, the way lanes and reasons became data), but:

- the **default is the strict job convention** — `job` and every repo that adopts
  `<dir>/<SERIES>: <PHASE>` is byte-for-byte unchanged, and the concurrent
  commit's decision stands as the default;
- a `[stamp] style="loose"` (or a declared `subject_dirs`/template) is an
  **opt-in a host takes knowingly**, and `dos` emits a one-line warning that the
  loosened detector trades strictness for reach — the operator owns that
  trade-off, the kernel doesn't make it silently.

So the kernel keeps the mechanism (grep `git log`, ancestry-check,
registry-first) and the *safe default*; a host that genuinely needs its own
grammar declares it and accepts the documented risk. This is the same posture as
the `--force` arbiter override: the conservative behavior is the default, and
loosening it is always an explicit, attributable operator act.

## Design laws this plan must honor

From `project-dos-kernel-design-laws` — these are load-bearing, not advisory:

0. **Strict is the default; loosening is an explicit, warned opt-in.** The
   concurrent commit `68b189b` chose the strict detector deliberately, and §1
   below is why. This plan must preserve strict-by-default: a repo that declares
   no `[stamp]` (or `style="grep"`/`"strict"`) gets the job grammar verbatim. The
   loose path exists, but only behind a declared `style="loose"`/`subject_dirs`
   that triggers a warning. **A plan that flipped the default to loose would
   re-introduce exactly the false-positive class §1 spent a whole plan series
   killing — don't.**
1. **Evidence over narrative.** The registry stays the primary signal; the grep
   rung stays the *fallback* (it covers manual commits that bypassed
   `mark done`). This plan touches only the grep rung's *grammar* and only behind
   the opt-in, never its precedence. A loose grammar's danger is precisely a
   false `shipped=True` from a subject that merely *mentions* a series token —
   the loose path must still run the ancestry check + bookkeeping-subject
   exclusions, so "loose" widens *which subjects are candidates*, not *what
   counts as proof*. **Never delete the grep fallback; never let loose skip the
   exclusions.**
2. **Multi-entrypoint oracle consistency.** `check_phase_shipped` has ≥3 calling
   paths (`--check-packet`, `--batch`, library fn). The convention must be read
   through one shared helper used by *every* path — a fix wired into one path
   recurred 9× historically on a different hot path.
5. **Kernel imports no host** (`CLAUDE.md` litmus). The default convention is the
   *job* convention, but it lives as a named default the kernel can fall back to
   without importing `dos.drivers.job` — same pattern as `main`/`global` lanes.

## North-star acceptance (the whole plan is done when)

```bash
# DEFAULT: strict. A repo that hasn't opted in gets the job grammar, unchanged.
dos verify --workspace <any-repo> AUTH 2      # strict <dir>/<SERIES>: <PHASE> rung

# OPT-IN: a host that knowingly accepts the loosened detector declares it…
dos init /tmp/foreign && cd /tmp/foreign
cat >> dos.toml <<'TOML'
[stamp]
style = "loose"                               # opt-in; dos warns this loosens the detector
subject_dirs = ["src", "lib", "app"]          # this repo's top-level dirs
series_phase = "{series}: {phase}"            # or a custom subject template
TOML
git commit --allow-empty -m "AUTH2: ship token refresh"
dos verify --workspace . AUTH 2
# warning: [stamp] style="loose" — verify will trust subjects the strict rung rejects
# SHIPPED (via grep) — was NOT_SHIPPED
```

…with `tests/test_verify_no_plan.py` green on the **strict default** (the
concurrent commit already conformed its fixtures to it), and a new
`tests/test_stamp_convention.py` pinning *both* that the job convention is the
unchanged default AND that the loose opt-in works + warns.

---

## Phase 0 — DONE by the concurrent agent (recorded as the starting base)

The phase-0 housekeeping this series rides on **already landed** in commits
`68b189b` + `c7afcbc` while this plan was being drafted (the scheduled-agent
concurrency noted in `project-dos-concurrent-automation`). Recorded here so SCV
starts from the real base, not a stale one:

- **0a. Version single-sourced — ✅ done.** `src/dos/__init__.py` now does
  `__version__ = _pkg_version("dos")` with a `0.2.0` literal fallback for an
  un-installed tree; `dos doctor` reports `DOS v0.2.0`, matching
  `pyproject.toml`. No further work.
- **0b. The red `test_decisions` case — ✅ done.** The suite is green
  (`76 passed`); the JUDGE-row `[j]` action routing was fixed alongside the
  decisions-queue commit. No further work.
- **0c. `verify(cfg=…)` plumbing — ✅ done (and SCV builds on it).**
  `oracle.is_shipped(plan, phase, cfg=…)` + `SubstrateConfig.state_path()` fill
  `state` and a default git-log `grep_fallback` from the config and fall through
  to the grep rung on a registry miss. **This is the wiring SCV's old Phase 1b/1c
  assumed — it exists.**
- **0d. `StampConvention` object + TOML loader + config field — ✅ done (in flight,
  uncommitted).** While this plan was drafted the concurrent agent also wrote
  `src/dos/stamp.py` (frozen `StampConvention` with `subject_dirs` /
  `summary_bundle_prefixes` / `bookkeeping_prefixes` / `style`; the three
  `*_re()` fragment accessors; `JOB_STAMP_CONVENTION`, `GENERIC_STAMP_CONVENTION`,
  `convention_from_table`, `load_from_toml`), added `stamp: StampConvention =
  JOB_STAMP_CONVENTION` to `SubstrateConfig` (`config.py:168` — **strict job is
  the default, exactly the operator's choice**), and re-exported the constants
  from `dos/__init__.py`. SCV Phase 1a/1b are therefore **already built**.
- **0e. Untracked HTML — note, don't fix.** `_arbiterk.html` /
  `arbiterk_tmp.html` (prior-art research residue) sit untracked in the repo
  root. `.gitignore` was touched by `68b189b`; confirm these are ignored or
  delete them in a separate housekeeping commit — not a kernel slice.

**Net — the two gaps that actually remain.** The data and the default are done;
two load-bearing pieces are NOT, and they are the whole of SCV's remaining work:

1. **`phase_shipped` does not consume the convention yet.** A grep of
   `phase_shipped.py` for `StampConvention` / `direct_prefix_re` / `cfg.stamp`
   returns nothing — the matcher still compiles its hardcoded `_DIRECT_PREFIX` /
   `_SUMMARY_SUBJECT_RE` / `_BOOKKEEPING_SUBJECT_RE`. So `stamp.py` is a
   beautifully-built object **nothing reads** — the very "scaffold nothing reads
   back" anti-pattern this series exists to kill, one layer up. **Wiring it in is
   Phase 1 (below).**
2. **There is no warned `style="loose"` opt-in.** The agent's model is binary —
   strict job dirs vs. install `GENERIC_STAMP_CONVENTION` (optional-prefix) — and
   the looser reach is selected *silently* by which convention object you install.
   The operator's chosen design is **strict default + a `style="loose"` opt-in
   that emits a one-line warning** (reach is a knowing, attributable trade-off,
   not a silent one). Reconciling the binary into the warned-opt-in is **Phase 2
   (below).**

---

## Phase 1 — WIRE the convention into `phase_shipped` (the actual throughline)

`stamp.py` (the data + `*_re()` fragments) and `SubstrateConfig.stamp` (strict
default) are **already built** (Phase 0d). The throughline that remains is making
the matcher *read* them — without this, `stamp.py` is an object nothing consumes.
This is the single most load-bearing slice in SCV.

- **1a.** In `phase_shipped.py`, replace the three hardcoded constants
  (`_DIRECT_PREFIX`, the `_SUMMARY_SUBJECT_RE` construction, `_BOOKKEEPING_SUBJECT_RE`)
  with reads of the active config's `stamp` via its `direct_prefix_re()` /
  `summary_subject_re()` / `bookkeeping_subject_re()` accessors. The accessors
  already return exactly the fragments the old constants held (the agent built
  them to be drop-in — `JOB_STAMP_CONVENTION.direct_prefix_re()` reproduces
  `(?:docs|go|agents|job_search|scripts)/`), so the substitution is mechanical.
- **1b.** Route **every** entrypoint through one shared `_subject_matchers(cfg)`
  helper: `--check-packet`, `--batch`, the library fn, AND
  `default_grep_fallback_single` (the path the new `is_shipped(cfg=…)` uses).
  Design-law §5 (multi-entrypoint consistency) is the explicit hazard here — a
  fix wired into one path recurred 9× historically on a different hot path. The
  regex must not stay hardcoded in *any* path.
- **1c.** Resolve which config the matcher reads: it must honor the `cfg=` passed
  to `is_shipped` (so `dos verify --workspace X` uses X's stamp), falling back to
  `config.active()`. Mirror the active-config save/restore `is_shipped(cfg=)`
  already does (`oracle.py:704`) so there's no global side effect.

**Litmus (Phase 1):**
- The full existing suite stays green with `stamp` defaulting to strict-job
  (proves the wiring is byte-faithful) — including the green `test_verify_no_plan.py`
  whose fixtures `68b189b` conformed to the strict grammar.
- New `tests/test_stamp_convention.py::test_generic_convention_recognizes_bare_subject`
  — installing `GENERIC_STAMP_CONVENTION`, a repo whose only evidence is a commit
  `AUTH2: ship token refresh` resolves **SHIPPED (via grep)** (today: NOT_SHIPPED).
  This is the proof the wiring made the syscall actually reach a foreign subject.
- `test_strict_job_convention_unchanged` — the job-subject corpus
  (`docs/X: P`, `go/X:`, `vX.Y.Z:`, `docs/HYG:`) resolves identically through the
  config-driven path; a bare `AUTH2:` under the **strict default** still does NOT
  ship (strict-by-default holds).

---

## Phase 2 — wire `[stamp]` to the CLI + add the warned `style="loose"` opt-in

`dos.stamp.load_from_toml` / `convention_from_table` are **already built**
(Phase 0d) and `dos init` already writes `[stamp]` (`cli.py:89`). Two gaps remain
between that and the operator's chosen design: the loader is **not called by the
CLI**, and there is **no `style="loose"` warning**.

- **2a. Wire the loader into the CLI.** `cli.py:_apply_workspace` (`cli.py:56-66`)
  loads `[reasons]` but **not** `[stamp]` — the exact "scaffold nothing reads
  back" gap WCR fixes for `[lanes]`. Add the `stamp.load_from_toml(toml_path,
  base=cfg.stamp)` load beside it and `dataclasses.replace(cfg, stamp=…)`, same
  warn-and-fall-back-on-malformed posture. (This is the line that makes a
  declared `[stamp]` actually reach `verify`.)
- **2b. Add `style="loose"` as a recognized, warned trigger.** Today `style` is
  declarative-only (`stamp.py:104-108` — "a non-`grep` value is accepted as data
  but the kernel still runs the grep rung"). Give it meaning: treat
  `style="loose"` as the operator's explicit "widen the detector" — and have the
  matcher emit a **one-line stderr warning** whenever the active convention is
  loosened (either `style="loose"` *or* a config whose `subject_dirs` is empty
  while the workspace declared a `[stamp]`): `warning: [stamp] loosened — verify
  will trust subjects the strict rung rejects; this relaxes the false-positive
  guard`. The warning is the operator's chosen mechanism for making reach a
  *knowing, attributable* trade-off rather than a silent one. The loosened
  matcher **still** composes the bookkeeping exclusions + ancestry check
  (design-law §1: loose widens *candidate* subjects, never *what counts as
  proof* — `GENERIC_STAMP_CONVENTION` already keeps the universal `snapshot:`
  guard, `stamp.py:206`; preserve that).
- **2c.** Update the `dos init` template so `[stamp]` documents the live fields
  AND the trade-off: `style="grep"` (= strict job dirs) is the safe default;
  declaring `subject_dirs`/`style="loose"` opts into the wider, riskier detector
  and prints the warning. No dead scaffold remains (this + WCR's `[lanes]` close
  every scaffolded-but-unread table).

**Litmus (Phase 2):**
- `test_strict_is_default_no_warning` — a workspace with no `[stamp]` resolves
  `JOB_STAMP_CONVENTION` and emits **no** warning (strict-by-default, silent).
- `test_loose_opt_in_widens_and_warns` — `[stamp] subject_dirs=["src"]` (or
  `style="loose"`) makes `src/AUTH: 2` and a bare `AUTH: 2` SHIP, emits the
  loosen-warning to stderr, and **still** rejects a bookkeeping/`snapshot:`
  subject that merely names the series (proves loose didn't drop the exclusions).
- `test_stamp_toml_reaches_verify_via_cli` — the override actually takes through
  the `dos verify` CLI path (not just the pure loader), proving 2a wired it.
- The North-star opt-in snippet runs green end-to-end.

---

## Phase 3 — `dos doctor` visibility + the completeness rail

Make the active grammar visible and guard the open vocabulary. (The old "make
`test_verify_no_plan` generic" task is **moot** — `68b189b` already conformed
those fixtures to the strict default, which is the correct resolution under
strict-by-default; this phase no longer touches them.)

- **3a.** Add to `dos doctor` a one-line report of the *active* stamp convention
  and its style: `stamp: strict (docs|go|agents|…)` vs `stamp: LOOSE
  (src|lib|…) — false-positive guard relaxed`. So an operator sees, before
  trusting a verdict, exactly which grammar `verify` will apply to their repo.
  Doctor *reports*, never writes (design-law §3).
- **3b.** *(completeness rail, per HACKING.md's `--check` invariant)* a
  `dos doctor --check` candidate: if a workspace declares `[stamp]` but `verify`
  would still resolve `via none` for that repo's own most-recent ship-shaped
  commit, surface it as a finding (the stamp analogue of "a reason emitted but
  not in the registry"). For a **loose** workspace, additionally flag if the
  loosened grammar would match a known bookkeeping subject (a sign the opt-in is
  too wide). Land as a finding/warning first; CI hardening is a follow-up.
- **3c.** Flip HACKING.md's mention of stamp-as-scaffold to *shipped*: document
  the strict-default / loose-opt-in contract beside the reasons axis, since
  `[stamp]` is now a real, read-back data axis like `[reasons]`.

**Litmus (Phase 3):**
- `dos doctor --workspace <strict-repo>` names the strict convention with no
  relaxation note; `dos doctor --workspace <loose-repo>` names LOOSE and the
  relaxed-guard note.
- `test_doctor_check_flags_loose_matching_bookkeeping` — a loose grammar that
  would match a bookkeeping subject is reported.

---

## Out of scope (explicitly)

- The **registry-first** path, the **ancestry check**, and the **bookkeeping
  exclusions** — unchanged; they run in both styles. This plan is *only* which
  subjects the grep rung treats as *candidates*.
- **Flipping the default to loose.** Explicitly forbidden (design-law §0/§1).
  Strict stays the default; loose is opt-in. A future plan may not quietly invert
  this.
- Stamp styles beyond `strict`/`loose` (e.g. a tag-based or trailer-based
  `style="tag"`). The `style` field is the extension point, but only those two
  ship here; another style is a later plan if a consumer needs it.
- The Go port (DSP) differential corpus — when SCV lands, DSP's executable-spec
  corpus must cover *both* styles, but that coupling is tracked host-side in the
  reference userland app, not here.

## Why this is the lead plan

It is the **deepest "make it generic" fix** *and* the one where "generic" was
genuinely contested — `verify` is the truth syscall the North Star most loudly
claims is domain-free, yet its strictness is load-bearing safety. SCV is the plan
that reconciles the two: it makes the syscall reach a stranger's repo *on the
host's explicit, warned opt-in* while keeping the safe strict grammar as the
default the concurrent commit `68b189b` already established. Because that commit
also landed the version single-sourcing, the green suite, and the `verify(cfg=)`
plumbing, SCV's remaining surface is small — the grammar object + the loose
read-back — and the rest of the series (WCR/RND/ADM) starts from that green,
single-versioned base.

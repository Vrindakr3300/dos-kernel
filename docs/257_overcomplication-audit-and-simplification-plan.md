# docs/257 — Overcomplication audit: where DOS is harder than its problem, and how to cut it

> **Status:** audit complete (2026-06-08). Findings below are verified against the
> code, not the docstrings — every "dead" claim was checked by grepping for a live
> consumer. Fixes are proposed, not yet applied.

## The frame

DOS earns a large *conceptual* surface: many distrust verbs, a careful four-layer
split, a pure-verdict discipline. That is **essential** complexity — the price of
being a trust kernel. This audit ignores that and hunts only the **accidental**
kind: code that is harder than the problem it solves, two mechanisms where one
would do, and abstractions built for consumers that never arrived.

The honest test for "bad" complexity here is not "does this module have a distinct
docstring" — every module does; the docstrings are excellent. The test is **"does
a live caller depend on it, or is it a maintained-but-unplugged leaf?"** Several
findings below survived that test (they are essential and only *look* redundant);
the ones that failed it are the real targets.

## The numbers (verified 2026-06-08)

| Measure | Value |
|---|---|
| Python modules under `src/dos/` | 136 |
| Total kernel LOC | 65,223 |
| `cli.py` alone | 8,974 (13.8% of the kernel in one file) |
| Modules named in CLAUDE.md | ~48 |
| Modules that exist | 136 → **~88 "ghost" modules** the contract never names |
| `docs/NN_*.md` design plans | ~191 (numbered up to 256) |
| Test files | ~162 |
| Entry-point groups **declared in pyproject** | **6** |
| Entry-point seams **with discovery machinery in code** | ~14 |

The gap rows are the story: a contract that names a third of the modules, a
plugin system whose code builds twice as many seams as the package declares, and
one file holding an eighth of the kernel.

---

## Finding 1 — `cli.py` is a 9k-line file carrying TWO CLI mechanisms, one dead

**Severity: high. This is the loudest single signal.**

`cli.py` is 8,974 lines — 5× the next-largest module. Most of it is defensible
(81 real verbs each need a thin wrapper), but three things make it *bad*-big:

1. **`build_parser()` is a single 1,540-line function** (`cli.py:7426–8966`) that
   hand-wires all 81 subparsers in one straight-line sequence — no table, no loop.
   Adding a verb means editing this monolith.

2. **A complete, generic replacement for that monolith already exists and is
   unused.** `verdict_cli.py` + the registry half of `verdicts.py` are a
   registry→argparse dispatcher: "adding a verb = one `register(...)`, and
   `cli.py` is edited ONCE." Its own docstring (`verdict_cli.py:12–14`) says it is
   *"deliberately deferred until the (currently hot) `cli.py` settles, so this
   module is built and tested STANDALONE first."* Verified: `verdict_cli.attach`
   and `verdicts.all_specs` are **never called from `cli.py`** (the only mention
   is one comment naming a helper). The registry registers exactly two verbs
   (`liveness`, `scope`). Both modules even ship their own test files
   (`test_verdict_cli.py`, `test_verdicts.py`), which is why they *look* alive.
   → The kernel pays for two CLI mechanisms and uses the worse one.

3. **~600 lines of inline help-text constants** (`_HELP_VERIFY`, `_HELP_INIT`, …,
   38 of them at `cli.py:7069–7425`) and **~42 repetitions** each of the
   `_apply_workspace(args); cfg = _config.active()` opener, the
   `if getattr(args, "json", False): print(json.dumps(...))` tail, and the
   per-verb `_<VERB>_EXITS = ExitMap({...})` constant.

**Fix (in priority order):**
- **Do not finish migrating to `verdict_cli`, and do not keep it parked.** Pick
  ONE. Given that `cli.py` works and ships, the cheaper honest move is to
  **delete `verdict_cli.py` and the registry/dispatch half of `verdicts.py`**
  (keep `verdict.py`, the type contract, which IS used) and drop their tests. That
  removes a whole dead mechanism and the false signal that a migration is pending.
  *If* the team would rather keep the registry, then commit to it: mount it in
  `cli.py` and delete the hand-wired duplicates for those verbs. The one thing not
  to do is leave both — that is the actual overcomplication.
- Extract the 38 help strings to a sibling data module (`cli_help.py`) or load
  from the verb's docstring. ~600 lines leave the file.
- Replace the three copy-paste patterns with one small helper each (a
  `@workspace_cmd` decorator for the opener; an `emit(args, verdict, token)` that
  every handler already *almost* uses; keep `ExitMap` but declare the maps in one
  table). Removes ~250 lines and the inconsistency where 18 handlers each emit
  verdicts a slightly different way.

Net: `cli.py` drops to roughly 6,500 lines **and** the kernel loses a dead
parallel CLI. The dead-mechanism removal matters more than the line count.

---

## Finding 2 — ~8 plugin seams are discovery machinery guarding an empty room

**Severity: high. This is the clearest speculative-generality cluster.**

pyproject declares **6** entry-point groups, all with real occupants:
`dos.judges` (3), `dos.stop_policies` (1), `dos.hook_dialects` (3),
`dos.notifiers` (1), `dos.hook_installs` (3). Those are fine — real
kernel/driver splits with shipping drivers.

But the **code** builds a full Protocol + by-name resolver + `importlib.metadata`
discovery loop for ~8 *more* groups that pyproject never declares and that ship
**zero** implementations (only the unshadowable built-in):

| Seam | Discovery loop | Declared in pyproject? | Non-built-in impls |
|---|---|---|---|
| `dos.predicates` | `admission.py:~300` | no | 0 |
| `dos.evidence_sources` | `evidence.py:~623` | no | 0 |
| `dos.log_sources` | `log_source.py:~344` | no | 0 |
| `dos.plan_sources` | `plan_source.py:~394` | no | 0 |
| `dos.renderers` | `render.py:~330` | no | 0 (built-in text/json only) |
| `dos.scope_sources` | `scope_source.py:~310` | no | 0 |
| `dos.enforce_handlers` | `enforce.py:~363` | no | 0 |
| `dos.overlap_policies` | `overlap_policy.py:~276` | no | 0 (built-in `prefix` only) |

Each is the same ~45–65-line discovery block (try `importlib.metadata`, handle the
<3.10 selectable API, loop, instantiate, catch, warn) — **copy-pasted ~8×**,
guarding a registry that only ever contains the one built-in.

**Important nuance (this is why the fix is surgical, not "delete 8 files"):** the
*modules themselves are mostly alive* — their **data types and built-ins** have
real consumers. `evidence.py` (`Accountability`, `EvidenceFacts`) is imported by
`attest`, `effect_witness`, `reward`, `precursor_gate`, `os_acceptance`,
`state_diff`, `cli`. `overlap_policy`'s `admissible_under_floor` is used by
`admission` and `overlap_eval`. `scope_source` is used by `completion`. So the
dead part is **only the second half of each file** — the entry-point discovery
apparatus — not the verdict/type it sits next to.

**Fix:**
- Delete the `_discover_entry_point_*` function and the resolver's plugin branch
  from each of the 8 seams. Keep the Protocol *only if* a built-in implements it
  for real use; keep the data types and built-ins untouched. The resolver
  collapses to "return the built-in." ~350 lines gone, zero behavior change
  (nothing resolves a non-built-in today).
- **Or**, if the intent is to keep these as a public extension story: factor the
  one discovery routine into a single `dos._plugins.discover(group, protocol)`
  helper and call it from all seams. That removes the 8× copy-paste even if the
  seams stay. (~290 lines gone, machinery preserved.)
- Either way, **make the code and pyproject agree**: a seam whose group isn't in
  `[project.entry-points]` and has no driver is not a feature, it's a maintenance
  cost and a false advertisement of extensibility.

The two *real* extension stories (`judges`, `hook_dialects`/`notifiers`) prove the
pattern works — which is the argument for not diluting it with six look-alikes
that have never been plugged into.

---

## Finding 3 — `stamp.py` (912 lines) is a DSL for what is mostly a regex + a flag

**Severity: medium. Real essential core, over-built shell.**

`stamp.py` lifts the reference app's commit-subject grammar into declarable data —
architecturally correct. But the *interpreter* dwarfs the *data*:

- `StampConvention` has 9 fields and ~13 methods.
- `repo_path_re()` (`stamp.py:~417–466`) carries **two incompatible regex
  strategies** in one method (tight allowlist when `code_dirs` is declared;
  permissive single-segment otherwise). In practice the reference app takes the
  tight branch and *every* foreign repo takes the generic branch (none declare
  `code_dirs`), and the comment concedes the tight branch is only a "recognition
  narrowing" whose real false-positive guards live downstream. So the branch is a
  micro-optimization nobody outside the one host uses.
- `recognizes_direct_ship()` (~57 lines) is a heuristic used **only** by a config
  *warning* rail (does a declared `[stamp]` table look like the repo's real
  subjects?) — never on the hot `verify()` path, which always knows the concrete
  series/phase.
- 40 lines of `to_dict`/`from_dict` exist to marshal ONE object across the
  `python -m dos.phase_shipped` subprocess boundary — a bespoke serializer for a
  single value resolved once at startup.
- Ships exactly **two** conventions: the reference app's (`JOB_STAMP_CONVENTION`)
  and the permissive fallback. No third party declares `[stamp]`.

**Fix:** keep the data-as-config idea (it's sound and the `verify()` litmus needs
it), but shrink the interpreter. Collapse the dual-branch `repo_path_re` to the
generic form plus an optional allowlist passed as data; move
`recognizes_direct_ship` + the warning rail into a separate `stamp_lint.py` that
`dos lint`/`doctor` calls (off the hot path); replace the bespoke
`to_dict`/`from_dict` with a plain dataclass-asdict if the subprocess boundary
still needs it. Estimated ~912 → ~350 lines with no loss to `verify()`.

---

## Finding 4 — `config.py` (1,288 lines) carries ~8 config tables nobody declares

**Severity: medium. Defensible scope, speculative tail.**

`SubstrateConfig` carries **18 policy fields** and `load_workspace_config()` reads
**16 `dos.toml` tables**, each with its own loader and identical try/warn/keep-base
boilerplate (16×). Of the 16, ~8 have a real in-repo consumer or default that's
exercised (`reasons`, `stamp`, `lanes`, `paths`, `overlap`, `retention`,
`data_class`, `reasons.morphology`). The other ~8 (`enumerate`, `cooldown`,
`supervise`, `lifecycle`, `intervention`, `tool_stream`, `precursor`,
`concurrency_class`) are declared-and-loaded with **no in-repo example** and a
generic default that always works — forward extension points, not current
features.

This is *tentative*, not *fake* (unlike `verdict_cli`): the knobs are wired to
real kernel behavior, they just have no declared user yet. The cost is the 16×
loader boilerplate and a 110-line `SubstrateConfig` docstring where every field
gets a paragraph.

**Fix (low-risk):** factor the per-table load into one
`_load_table(toml, name, loader, base)` helper to kill the 16× boilerplate
(~120 → ~30 lines). Condense the field docstrings to a one-line reference each and
let the per-module docs carry the detail. Don't remove the speculative tables
*yet* — but track which ones gain a real consumer, and delete any still unused at
the next major version. (`home.py`, by contrast, audited as *justifiably* complex —
dual state-tree management with locking; leave it.)

---

## Finding 5 — the contract names a third of the system

**Severity: medium (comprehensibility, not correctness).**

CLAUDE.md is the "read before editing" contract and names ~48 modules. There are
136. The ~88 it doesn't name aren't junk — they're the witness ecosystem
(`effect_witness`, `evidence`, `arg_provenance`, `attest`, `reward`,
`result_state`), the detector line (`dangling_intent`, `precursor_gate`,
`firing_label`, `commit_audit`), the observability apparatus (`health`,
`event_severity`, `churn`, `coverage`, `fleet_roll`), and the seams above. A new
maintainer reading the contract will understand the *intent* and then be blindsided
by 2/3 of the surface.

(Verified non-redundant under the live-caller test: `rewind*` vs `resume*` are
mirror axes that *both* have live callers — `completion` reads `rewind`'s
checkpoint fields, `loop_decide`/`coverage`/`reconcile` consume `completion`;
`health`/`status`/`liveness` answer three different questions; `churn`/`cooldown`
gate different things. These only *look* redundant; they survive the audit. The
problem is documentation drift, not duplication.)

**Fix:** this isn't a code cut, it's a map. Add a generated "module census" to
`docs/ARCHITECTURE.md` (the cold-tier doc the contract already points at) — one
line per module grouped by the cohesion clusters the contract already names
(temporal-verdict / recovery / picker / seam-protocol / witness / observability).
A tiny script that lists `src/dos/*.py` and pulls each one-line docstring keeps it
honest and current. The contract stays short; the census carries the breadth.

---

## What is NOT overcomplicated (so the audit is honest)

- The four-layer split and the pure-verdict / I/O-at-the-boundary discipline —
  essential, and consistently applied.
- The `_filelock` consolidation (one home for steal logic; killed three
  hand-rolled copies) — this is the *good* direction.
- `home.py` — load-bearing dual-state management, not speculative.
- The `*_evidence` / pure-`classify` pairing across the verdict family — the right
  shape, not duplication.
- The 162 test files / ~0.6 test:source ratio — proportionate.

## Suggested order of work (cheapest, highest-signal first)

1. **Delete the dead CLI mechanism** (`verdict_cli.py` + registry half of
   `verdicts.py` + their tests) — removes a whole parallel system and a false
   "migration pending" signal. (Finding 1.2)
2. **Strip or unify the 8 plugin-discovery loops** with zero occupants. (Finding 2)
3. **De-boilerplate `cli.py`** (help-text extraction + 3 helpers). (Finding 1.3)
4. **Shrink `stamp.py`'s interpreter**, move the warning rail off the hot path.
   (Finding 3)
5. **One config-table loader helper**; condense the docstring. (Finding 4)
6. **Generate the module census** into `docs/ARCHITECTURE.md`. (Finding 5)

Items 1–3 are pure deletions / mechanical refactors with strong test coverage
already in place — low risk, and they remove the two clearest "two mechanisms for
one job" instances. 4–6 are scoped refactors. None touch the verdict semantics or
the litmus tests.

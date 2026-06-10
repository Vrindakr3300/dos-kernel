# 284 — ship-oracle file-path backstop: hoist the per-pair `git log` into one windowed scan

> Status: LANDED (2026-06-10). Routed from job; measure-then-change baseline below
> is live-measured on the reference userland app's workspace (read-only analysis — the host
> side does NOT self-edit the adjudicating kernel). The dos-side fix is now
> implemented and pinned — see the **Verification checklist** at the bottom for the
> per-item landing record and the byte-identity (never-under-count) proof.

## TL;DR

`dos.oracle.batch_is_shipped`'s grep-fallback rung is **~19s on a 262-pair
snapshot** because the AAR-FQ230 file-path backstop
(`phase_shipped._apply_filepath_backstop` → `_check_phase_by_filepath` →
`_git_log`) runs **one `git log` subprocess per unresolved pair** — 364 git
subprocesses for 262 pairs, ~50ms each. The batch entry already holds the whole
pair-set, so these per-pair `git log` calls can be hoisted into **one windowed
`git log --name-only` scan** shared across every pair, turning ~19s into ~1s. This
is the single biggest per-iteration deterministic tax in the job repo's
`/dispatch-loop` (it is paid by the acquire-time pick-oracle, the pre-launch
pickability gate, and the orphan-sweep — up to 3× per loop iteration).

## Measured baseline (live, job workspace, 2026-06-10)

A real snapshot: **71 plans, 265 `(plan,phase)` remaining pairs, 50 shipped.**

| Rung | Wall-clock | Pairs it resolves |
|---|---|---|
| `load_state_from` (registry YAML parse) | **0.06s** | — |
| `batch_is_shipped` registry-only (no grep, no hooks) | **0.16s** | 3 / 50 |
| `batch_is_shipped` FULL (grep + 4 demotion hooks) | **19.58s** | 50 / 50 |
| `default_grep_fallback_batch` over the 262 registry-misses | **19.09s** | 47 |

So **~19.4s of the ~19.6s is the grep file-path backstop**, not the registry. The
registry is already instant; the cost is entirely in the git rung.

### cProfile of `default_grep_fallback_batch` (262 misses)

```
   ncalls  cumtime  percall  filename:lineno(function)
        1   19.932   19.932  dos/oracle.py:1385(default_grep_fallback_batch)
        1   19.349   19.349  dos/oracle.py:1263(_grep_batch_in_process)
      364   18.421    0.051  subprocess.py:506(run)                       <-- git
      265   18.028    0.068  dos/phase_shipped.py:1435(_apply_filepath_backstop)
      262   18.027    0.069  dos/phase_shipped.py:1279(_check_phase_by_filepath)
      320   17.889    0.056  dos/phase_shipped.py:154(_git_log)           <-- per-pair
```

**364 `git log` subprocesses** (320 from `_git_log` + the rest from the matcher
warm-up), one (sometimes two) per pair, dominate. A single `git log` on this tree
is ~16–50ms; the cost is `N × subprocess-spawn`, not any one slow call.

## Root cause

`_apply_filepath_backstop` (the AAR-FQ230 file-path false-NEGATIVE backstop, added
2026-05-18 so `--batch`/`check_phase_shipped()` get the same artefact rung
`--check-packet` had) calls `_check_phase_by_filepath(series, phase, plan_doc, …)`
**once per pair**. Each `_check_phase_by_filepath` shells `git log` to learn "what
file paths did recent commits touch?" and overlaps that against the file paths the
plan doc's phase row names. The **commit→file-path data is identical across all
pairs** — every pair asks the same git history "which commits touched which files"
and only the per-pair *overlap test* differs. The git scan is being redone 262×
for one answer.

## Proposed fix (batch the git, keep the per-pair overlap pure)

`default_grep_fallback_batch` (or `_grep_batch_in_process`) already has the full
`pairs` list and the `plan_doc_map`. Before the per-pair loop:

1. **One windowed `git log --name-only --format=…`** over a bounded recent window
   (the same window the per-pair calls already scan — they are not scanning all of
   history, so the union window is the max of the per-pair windows). Parse it once
   into `{sha: (subject, [touched_paths])}` in memory.
2. The per-pair `_check_phase_by_filepath` becomes a **pure in-memory overlap**
   against that one parsed structure — no subprocess. Same verdict, same
   false-positive overlap guard, same `#399` release-bump demotion (which already
   has its own `commit_touches_doc` git work — see note below).

Expected: **~19s → ~1s** (one git scan + 262 in-memory overlaps), and because the
job side calls this from acquire + pre-launch gate + orphan-sweep, the win
compounds ~3× per `/dispatch-loop` iteration.

### Note on the `#399` release-bump demotion

`default_grep_fallback_batch` also runs `_grep_verdict_is_release_bump_falsepos`
on each `shipped=True` verdict, which calls `commit_touches_doc` (a per-commit
`git diff` footprint check). On this snapshot only 50 pairs reach that path and it
was a small fraction of the 19s, but the SAME windowed `--name-only` scan from step
1 already carries each commit's touched-path set, so the demotion's footprint check
can read it from memory too (a second, free win). Confirm with a profile after step
1 lands — if the demotion is still hot, fold it into the same parsed structure.

## Trust invariant (must hold — ⚓ never-under-count)

The batched scan must produce **byte-identical verdicts** to the per-pair path. The
job side relies on the never-under-count contract: a shipped-set is only ever
SUBTRACTED from `remaining` (a "drop this already-shipped phase" gate), so a
verdict that flips `shipped=False→True` incorrectly would remove a genuinely-live
pick (lost work). Pin parity with a test that runs both paths over a fixed fixture
and asserts equal `{(plan,phase): ShipVerdict}` maps. The windowing must use the
**union** of the per-pair windows (never a narrower one) so no pair loses a commit
it would have seen.

## Why routed, not landed by the job side

`dos.oracle` / `dos.phase_shipped` are the adjudicating kernel (this repository); the
reference userland app's CLAUDE.md forbids it from self-editing the kernel it is judged by.
The job side is landing the **complementary** fix in parallel: a cross-process
disk cache of the shipped-set keyed on `git HEAD` + pair-set
(`agents/lease_state/loaders.py`), so a fresh `claude -p` iteration child at an
unchanged HEAD reads ~0s instead of re-paying this 19s. That cache hides the cost
from the second-and-later iterations; **this kernel fix removes the cost at the
source** (every first-at-a-new-HEAD call, every consumer, every workspace). They
compose: cache for warm reads, batched scan for cold ones.

## Verification checklist for the dos-side author

- [x] One windowed `git log --name-only` replaces the per-pair `_git_log` calls in
      the file-path backstop's batch path. — `_build_filepath_log_cache` runs ONE
      `git log --name-only --no-merges --format=%x00%h%x00%s -<cap> -- <union>` scan;
      `build_batch_filepath_cache` harvests the union of every pick's files and
      drives it; `_grep_batch_in_process` (+ `--batch`/`--check-packet` in
      `phase_shipped.main()`) build the cache once before the per-pick loop.
- [x] Per-pair `_check_phase_by_filepath` overlap is a pure in-memory function in
      the batch path (no subprocess). — it takes an optional `fp_cache`; when
      supplied each named file's `(sha, subject)` list is a dict lookup, and the
      overlap/attribution logic below it is byte-unchanged.
- [x] Parity test: batched vs per-pair verdict maps are byte-identical over a fixed
      fixture (the never-under-count pin). — `tests/test_filepath_backstop_batch.py`
      pins (1) the verdict map equal across the rung's distinct shapes, (2)
      abbreviated-sha parity (the `%h` not `%H` bug), (3) the git-call reduction,
      (4) saturation → `None` → per-file fallback, (5) `fp_cache=None` ≡ no-cache,
      (6) merges excluded from both paths. Verified 129/129 `src/dos` files
      byte-identical on this repo.
- [x] Window is the UNION of the per-pair windows (no pair loses a commit). — the
      union pathspec is scanned with a `_FILEPATH_WINDOW * _BATCH_SCAN_CAP_FACTOR`
      (=12) commit cap, each file then truncated to its own `_FILEPATH_WINDOW`; a
      SATURATED cap returns `None` so the caller re-runs the exact per-file path
      (the never-under-count safety degrade — never a narrower window).
- [x] Re-profile: `default_grep_fallback_batch` over ~262 pairs drops ~19s → ~1s. —
      measured 20.9× on this repo at 30 files (617ms → 29ms, 1 git call vs 30); the
      win scales with the union-file count, so the job's 364-call/262-pair snapshot
      lands in the ~1s range projected above.
- [x] `#399` release-bump demotion reads touched-paths from the same parsed scan if
      still hot. — LANDED (2026-06-10, docs/284 follow-up): rather than thread the
      batch `--name-only` scan into the per-sha demotion (the scan is keyed by
      *file*, the demotion by *sha*), the cleaner mechanism was the EXISTING
      per-process SHA-footprint memo. `default_commit_touches_doc` (the registry-side
      Signal A/B/C collision check) was shelling its OWN inline
      `git show --name-only --format= <sha>`, bypassing `_git_touched_files`'s
      `(root, sha)` cache — so the same release-bump sha's footprint was fetched once
      there AND again by the grep-side `_grep_verdict_is_release_bump_falsepos`, and a
      fan-out re-paid the spawn per repeated sha. Routed it through `_git_touched_files`
      (byte-identical: same git command, same path normalization, same permissive
      None on unknown/empty); verified 30/30 recent shas' footprints identical, and a
      50× fan-out over one sha drops 50 git-show spawns → 1 (52× on that path). The
      cross-rung double-fetch the cache comment flagged is now collapsed for the
      registry side too. Pinned by `tests/test_oracle_grep_in_process.py`
      (`test_default_commit_touches_doc_verdicts` — first DIRECT coverage of the
      predicate's three verdicts; `test_default_commit_touches_doc_uses_the_touched_files_memo`
      — the cache-routing/no-double-fetch invariant).

> **Merge-commit note (landed):** byte-identity forced one design choice the spec
> didn't anticipate — a union `git log --name-only` over many pathspecs cannot
> reproduce git's per-PATH history simplification through MERGE commits (default
> `--oneline -- <file>` follows a TREESAME parent; the union scan has no single
> parent to follow). `--no-merges` on BOTH the batched and per-file paths removes
> the ambiguity at the source: a merge commit is never a phase's ship of record
> (the underlying feature commit is retained either way), and the two paths become
> byte-identical by construction. This is the one behavioural change vs pre-284
> (the per-file path now also drops merges); the full kernel suite stays green.

> **Status: LANDED (2026-06-10).** Kernel side implemented in
> `src/dos/phase_shipped.py` + `src/dos/oracle.py`, pinned by
> `tests/test_filepath_backstop_batch.py`. The job-side disk cache (warm reads) is
> the complementary fix; this removes the cost at the source for every cold read.

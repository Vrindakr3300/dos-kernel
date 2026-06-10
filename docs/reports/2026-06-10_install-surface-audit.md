# Install-surface audit — the docs/286 wheel pipeline + the install workstream

**Date:** 2026-06-10
**Auditor:** Claude (Fable 5), `/goal deep audit latest install things and progress`
**Window audited:** the install workstream landed 2026-06-10 — `1101611` (PATH
wiring) → `5836f10` (docs/286 P1+P2) → `f36f446` (install options + drift gate) →
`9de9bb0` (docs/286 P3, CI matrix) → `129ce9a` (PUBLISHING.md) — plus the three
concurrent-session commits that landed mid-audit (`2832c6b` CI guard wiring,
`5e06928` WSL portability fixes, `f0cfc91` report addendum), against the
docs/286 plan and the 2026-06-10 WSL prove-out report.

## TL;DR

The install surface is **real, tested, and honest** — every claim I checked is
backed by a witness that ran, not narration. Per-platform wheels build correctly
(byte-format guard passes when run), all five real-install levels pass on this
box (uvx, `uv tool`, pip-venv, the PowerShell wrapper, a genuine WSL install),
the drift gate leashes the docs to `pyproject.toml`, and `dos commit-audit`
sweeps the whole window at **0% drift**. Two real defects were found and both are
now closed (one by a concurrent session, one by this audit). The workstream's one
open endpoint is **distribution itself: nothing is on PyPI yet** — the pipeline
is built and gated; the first owner-approved upload has not run.

## What was verified, and how (each row is a thing that actually ran)

| Claim | Witness | Result |
|---|---|---|
| Per-platform wheels carry exactly one right-format binary | `DOS_TEST_BUILD_WHEELS=1 pytest test_build_wheels_binary_format.py` (2 cross-arch Go builds + zip byte inspection, this box) | **PASS** |
| The 6-arch plan maps to correct PyPI tags | `python scripts/build_wheels.py --check` (Go 1.26.3 present) | **PASS** — manylinux2014/macosx/win tags as designed |
| Real installs work at every level | `pytest test_install_levels.py -v` | **5 passed, 1 skipped** (uvx ✅ uv-tool ✅ pip-venv ✅ install.ps1 ✅ REAL-WSL ✅; install.sh correctly win32-skipped) |
| Locator + fallback contract | `test_hook_binary_locator.py` (+ Go source check: pretool/posttool never DELEGATE after consuming stdin, so the Python fallback never reads a drained event) | **PASS** |
| Install docs can't rot against pyproject | `test_install_drift.py` + `test_prop_install_wrappers.py` | **PASS** |
| Commit subjects in the window match their diffs | `dos commit-audit --sweep "1101611^..HEAD"` (11 commits) | **0.0% drift** — 7/7 checkable claims diff-witnessed, 4 abstained |
| PUBLISHING.md Stage 1 matches the build reality | grep: Stage 1a + quick-ref point at `build_wheels.py` | **PASS** (129ce9a's claim holds) |
| Published state | `pip index versions dos-kernel` | **No matching distribution — NOT on PyPI** (expected; INSTALL.md marks every PyPI row pre-release) |
| Full suite after this audit's kernel fix | `python -m pytest -q` on this box | **3962 passed, 4 skipped, 3 failed — all 3 triaged**: the documented environmental hermes failure (below), plus `test_arbitrate_default_loads_live_wal_no_double_book` + `test_self_tree_verifies_clean_against_head`, both known hot-tree contamination modes (a live peer lease in the WAL; HEAD advancing mid-suite) that **pass in isolation** (re-run witnessed, 2 passed) |

`dos verify --workspace . docs/286 "Phase N"` answers `NOT_SHIPPED (via none)`:
the subjects stamp `docs/286 Phase 3`, and a two-word phase token does not parse
under the stamp grammar, so the oracle conservatively abstains. Not a defect —
this repo's honesty witness is `commit-audit` (clean, above); noted so the next
session doesn't read the abstention as a missing phase.

## Defects found (both now closed)

1. **Vendor-litmus violation in the kernel — found by the WSL session, closed by
   this audit.** docs/286 Phase 1 (`5836f10`) introduced
   `if dialect and dialect != "claude-code":` in `src/dos/hook_binary.py:128` — a
   vendor literal as a Compare operand in a kernel module, which
   `test_vendor_agnostic_kernel::test_vendor_names_only_appear_in_prose_not_branches`
   correctly rejects (the suite was red on master from `5836f10` until this fix).
   Fixed by importing `dos.hook_dialect.DEFAULT_DIALECT` — the one sanctioned home
   of that literal — instead of spelling it. Litmus suite green again (8/8).
   *Lesson: the litmus caught exactly the drift class it was built for, in the
   first commit that introduced one; the gap was only that nobody ran that test
   between `5836f10` and the WSL prove-out.*

2. **The wheel byte-format guard was dormant — found independently here and by
   the concurrent session; closed by `2832c6b`.** The guard that pins the
   build/-staging-leak fix (the macOS-binary-inside-the-Windows-wheel bug) is
   opt-in (`DOS_TEST_BUILD_WHEELS=1`) because it builds in the shared repo root,
   and **no CI leg set the flag** — so the regression guard ran nowhere. `2832c6b`
   added a dedicated clean-checkout step to ci.yml's build job that sets it.
   Verified: the step is in ci.yml, and the guard passes for real on this box.

## Doc fixes landed by this audit

- `docs/INSTALL.md`: `git clone …/dos-kernel && cd dos` → `cd dos-kernel` (2
  sites — the clone dir is the repo name; `cd dos` fails).
- `docs/286_…md` status header: said "Phases 3 + 4 remain" while its own §4
  recorded Phase 3 as SHIPPED; header now matches the body and records the
  not-on-PyPI state.
- WSL report: third residual environmental failure appended (System32-bash, below).

## Residual environmental failure (documented, deliberately not "fixed")

On a Windows box whose `bash` is `C:\WINDOWS\system32\bash.exe` (WSL bash), the
hermes safety demo's hazards can never fire: the sentinel path is forward-slashed
to a `C:/`-rooted profile path WSL bash cannot address, so `naive = 0` and
`test_safety_demo_blocks_every_arbitrary_exec_command` fails. **A/B-proven
pre-existing** (a `git archive HEAD` export of the pre-fix tree fails
identically; every kwarg variant of the `5e06928` fix behaves the same) and
**environmental** (CI's windows runner passes — git-bash wins PATH there).
Candidate fix is a demo-side `wslpath` conversion; spun off as a follow-up task
rather than bundled into this audit.

## Progress: where the install workstream stands

| Piece | State |
|---|---|
| docs/286 P1 — in-package locator + consult-and-fall-back CLI preamble | ✅ shipped + tested |
| docs/286 P2 — per-platform wheel build (`build_wheels.py`) | ✅ shipped; staging-leak fixed + guarded |
| docs/286 P3 — CI builds the 6-wheel matrix (publish.yml + ci.yml) | ✅ shipped; byte guard wired on clean CI (`2832c6b`) |
| docs/286 P4 — measure the pip native win; decide the console-script shim; `Root-Is-Purelib` polish | ⏳ open (the only remaining plan phase) |
| Install options (uv/uvx, wrappers, WSL) + drift gate | ✅ shipped; 5/6 levels proven live on this box |
| WSL portability (the 4 prove-out gaps) | ✅ all landed (`5e06928`); suite runs to completion on WSL (3914 passed per `f0cfc91`) |
| **First PyPI publish** (owner-only: pending-publisher setup + approved upload, PUBLISHING.md Stage 1) | ⏳ **open — the workstream's endpoint.** Until it runs, every PyPI install path is documentation of the future; the clone paths are the live ones. |
| Push state | the whole window (16 commits at audit close) is local to `master`, unpushed as of the last fetch — pushing is the owner's call |

## Post-audit note (same day)

Minutes after this audit's fixes landed, a concurrent session released the
workstream as **v0.21.0** (`58209d4` — "wheel-bundled native hook fast path,
first-class installers, verified plugin installs", with the bundled binaries
rebuilt in `3e4eb65`). The release therefore carries this audit's
vendor-litmus fix (`f701a9f`). The PyPI-publish endpoint above is unchanged —
a version tag exists to publish when the owner runs Stage 1.

## Smaller observations (no action taken)

- publish.yml's own build job does not run the byte-format guard step (ci.yml's
  does, and the same commit normally crosses ci.yml on master before a tag) —
  acceptable; worth copying the step over if tag-time paranoia is wanted.
- GitHub-hosted ubuntu runners don't ship `uv`, so the two uv install levels
  likely skip in CI (they skip cleanly by design). Adding `astral-sh/setup-uv`
  to the test job would make CI exercise them; spun off as a follow-up.
- The re-tagged wheels still say `Root-Is-Purelib: true` — cosmetic, already
  recorded in docs/286 §2 as Phase 4 polish.

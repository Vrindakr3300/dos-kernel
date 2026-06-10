# 286 — Shipping the native `dos-hook` binary through PyPI (per-platform wheels)

> **Status:** Phase 1 (package-side locator + Python fallback) **+ Phase 2**
> (per-platform wheel build) **SHIPPED 2026-06-10.** A clean-room
> `pip install dos_kernel-…-win_amd64.whl` into a fresh venv now resolves
> `dos.hook_binary.native_hook_binary()` to the bundled `site-packages/dos/_bin/
> dos-hook.exe` and `dos hook pretool` reports *"served by native dos-hook"* — the
> pip surface gets the fast path. **Phase 3 (CI matrix) SHIPPED 2026-06-10** —
> `publish.yml` + `ci.yml` build the 6-wheel matrix via `scripts/build_wheels.py`,
> with the byte-format guard run on the clean CI checkout (§4). Only Phase 4
> (measure the pip native win, decide the console-script shim) remains. Note:
> nothing is on PyPI yet — the pipeline is built and gated; the first
> owner-approved upload (PUBLISHING.md Stage 1) has not run.
>
> The PyPI publish *infrastructure* was already built and correct
> (`PUBLISHING.md`, `.github/workflows/publish.yml`, `scripts/build_dist.py`,
> Trusted-Publishing OIDC, version-tag gating). What this plan adds is the one thing
> that infrastructure did **not** carry: the native Go fast-path binary. Before this,
> `pip install dos-kernel` produced a **pure-Python** `py3-none-any` wheel, so a pip
> user who wires the hooks (`dos init --with-hooks`) ran `dos hook pretool` —
> ~600 ms of Python cold-start on **every tool call** — and never saw the 16–43×
> native win (docs/270). That win shipped *only* through the Claude Code plugin's git
> tree (`claude-plugin/bin/`, docs/125 GHF4). This plan closes the gap for the **pip**
> distribution surface.
>
> **What landed:** `src/dos/hook_binary.py` (the in-package locator + `try_native_hook`
> + `hook_argv_from_args`), the `dos._bin/` package-data dir (gitignored binary; glob
> in `pyproject`), the `cmd_hook_pretool`/`cmd_hook_posttool` "consult-and-fall-back"
> pre-amble in `cli.py`, `scripts/build_wheels.py` (go-build → `python -m build` →
> `wheel tags` re-tag, per arch; pure-source sdist), `wheel>=0.43` in `[dev]`, and
> `tests/test_hook_binary_locator.py`.

This is a **distribution-tooling** plan, OUTSIDE the four kernel layers (CLAUDE.md
"Four things live OUTSIDE the four layers"). Nothing under `src/dos/` *imports* the
build tooling; the binary is package **data**, the same one-way arrow as the skill
pack. The kernel stays vendor-blind and near-stdlib — bundling a static binary adds
**zero** runtime dependency.

---

## 0. The gap, stated precisely

Two distribution surfaces, only one of which carries the binary today:

| Surface | How it ships | Native `dos-hook`? |
|---|---|---|
| **Claude Code plugin** | the git tree itself (`marketplace.json` `source: ./claude-plugin`) | **Yes** — 6 arches committed in `claude-plugin/bin/`, launcher dispatches (docs/125 GHF4). |
| **PyPI wheel** (`pip install dos-kernel`) | a `py3-none-any` wheel built by `python -m build` | **No** — pure Python; the hook verbs run the slow Python path. |

The plugin path is *solved* and must stay untouched. This plan is purely about the
wheel. A pip user is not *blocked* without the binary (the Python verb is always
the fallback), but they pay the full per-call cold-start the binary was built to
erase — so the highest-felt win in the product is invisible to anyone who adopts
via `pip` rather than the marketplace.

## 1. The decision: per-platform wheels (not download-on-demand, not one fat wheel)

Three honest ways to get a compiled binary to a `pip install` user:

1. **Per-platform wheels** (CHOSEN). Build one wheel per OS/arch, each embedding
   **only** its matching binary at `dos/_bin/dos-hook[.exe]`. `pip` reads the wheel's
   platform tag and downloads only the one wheel that matches the installing machine.
2. **Download-on-demand.** Ship one tiny pure-Python wheel; fetch the right binary
   from the GitHub release assets at first use into a user cache, checksum-verified.
3. **One universal wheel, all binaries.** Put the full ~24 MB 6-arch matrix into a
   single `py3-none-any` wheel; a runtime launcher picks the right one.

**Why per-platform wheels (best practice).** This is the standard way the Python
ecosystem ships binaries (it is what `ruff`, `maturin`-built packages, and
`cibuildwheel` projects do):

- **No runtime network.** The binary arrives *with* the wheel, inside pip's existing
  integrity envelope (per-file hashes in `RECORD`, the index's hash-pinning, and —
  once Trusted Publishing is live — PyPI's attestations). Option 2 bolts a *second*,
  post-install, executable-fetching supply-chain surface onto the install — exactly
  the kind of thing SECURITY.md "Supply chain" is wary of, and a thing many locked-
  down environments (no egress, air-gapped CI) forbid outright. A binary that arrives
  through the same channel pip already audits is strictly safer to reason about.
- **Right-sized.** Each user downloads ~4 MB (one binary), not ~24 MB (option 3's six).
- **No first-use latency cliff.** Option 2's first hook call blocks on a network
  fetch (or silently degrades to Python until the cache warms); per-platform wheels
  are fast from call one.
- **ABI-independent ⇒ Python-version-agnostic.** The binary is a *static Go
  executable*, not a CPython C-extension. So the wheel is platform-specific but **ABI
  tag `none`**: one `py3-none-<platform>` wheel per OS/arch covers 3.11/3.12/3.13 at
  once. This is materially simpler than full `cibuildwheel` (no per-interpreter
  build, no `manylinux` C-toolchain image needed for *our* code — Go statically links
  libc via `CGO_ENABLED=0`).

The cost accepted: the publish job grows a build matrix (6 `go build`s + 6 wheel
re-tags) and the release ships 6 wheels + 1 sdist instead of 1 wheel + 1 sdist. That
is the normal shape of a binary-shipping PyPI project and it is worth it for the
felt win.

## 2. The sdist stays honest (the fallback floor)

The **source distribution** (`dos_kernel-<v>.tar.gz`) carries the `go/` source but
**no** prebuilt binary. `pip install` from an sdist (a platform with no matching
wheel, or `--no-binary`) therefore gets a pure-Python install — which **runs
correctly**, falling through to the Python hook verb. We deliberately do **not** add
a `build` step that shells `go build` during `pip install`: most install
environments have no Go toolchain, a build-time shell-out is fragile and slow, and
the whole point of the fallback discipline (docs/100) is that *no machine is ever
blocked* by a missing accelerator. An sdist install is un-accelerated, never broken.

(A user on an off-matrix arch who *wants* the native path can `cd go && go build` and
drop the binary at `dos/_bin/` — the §3 locator finds it. That is the same escape
hatch the plugin launcher gives.)

> **Decided 2026-06-10: the sdist carries NEITHER a compiled binary NOR the `go/`
> source.** Verified: `python -m build --sdist` produces a tarball of `src/` + `tests/`
> + metadata only. The `go/` tree is *deliberately* not added to the sdist — it would
> bloat the artifact with the parity corpora + `.dos` stream fossils for a source most
> install environments (no Go toolchain) cannot use, and the design explicitly does
> **not** `go build` during `pip install`. An sdist install is the pure-Python
> fallback: correct, un-accelerated. If a future need arises to make the sdist
> self-building, add `go/` via `MANIFEST.in` with a corpus/`.dos` exclude — but that
> is a non-goal today (§5).
>
> **Cosmetic note:** the re-tagged wheel's `WHEEL` metadata still says
> `Root-Is-Purelib: true`. It is harmless — the `py3-none-<platform>` *tag* is what
> pip's platform-compatibility check reads, and that is correct — but a stricter build
> could set it false. `wheel tags` does not flip it; left as-is (Phase 4 polish).

## 3. How the installed package finds its binary (`dos._bin` + the locator)

A new package-data dir `src/dos/_bin/` (with no `__init__.py` content beyond the
marker — it is *data*, like `skills/`). The per-platform wheel build drops exactly
one file there: `dos-hook` (POSIX) or `dos-hook.exe` (Windows). A new tiny pure-
stdlib module — `dos/hook_binary.py` — resolves it:

```python
def native_hook_binary() -> Path | None:
    """The bundled native dos-hook for THIS interpreter's platform, or None.

    Returns the path iff a matching, executable binary is present in the installed
    package (dos/_bin/dos-hook[.exe]); None otherwise (a pure-python/sdist install,
    or an off-matrix arch). The caller falls back to the in-process Python verb.
    """
```

This is the wheel analogue of the plugin's POSIX `bin/dos-hook` launcher, but it
lives *inside* the package and is consulted by the CLI, so the same `dos hook
pretool` invocation a pip user wires transparently routes through the native binary
when one is bundled. The fallback is unchanged: no binary → the existing Python
decider runs, byte-for-byte.

**Where the CLI consults it (Phase 1 scope):** `cmd_hook_pretool` /
`cmd_hook_posttool` (the per-tool-call hot path — the ones that pay the cold-start)
gain a thin pre-amble: if `native_hook_binary()` is present and `DOS_HOOK_NATIVE`
is not disabled, `exec`/subprocess the binary with the same argv and forward its
exit code + stdout; else fall through to today's Python body. `stop` fires once per
turn (negligible cold-start) and stays Python. The binary already owns its own
delegate/fail-safe discipline (exit 3 = DELEGATE → run the Python body; a panic →
exit 0 emit-nothing), so the CLI pre-amble is: *run native; on DELEGATE/abnormal,
run Python.* This reuses the exact contract the plugin path already proved.

> **Note on the felt win through pip vs plugin.** The plugin wins big because its
> hooks.json `exec`s a *shell* launcher → the static binary, paying ZERO Python.
> The pip path still pays the Python *interpreter start* to reach
> `cmd_hook_pretool` before it can `exec` the binary — so the pip native path saves
> the heavy `import dos` + predicate work, not the bare interpreter boot. Measure it
> (Phase 4); if a Python-launcher pre-amble only recovers ~2× (the docs/125 §8.3
> measured-constraint note), the larger pip win is to ALSO ship a console-script
> shim (`dos-hook`) that `pip` puts on PATH, which a pip user can wire into
> settings.json directly the way the plugin wires its launcher. Decide in Phase 4
> from the measurement; Phase 1 ships the in-CLI route (correct + fallback-safe)
> regardless.

## 4. Phases

- **Phase 1 (this commit) — the package-side locator + fallback, behind a test.**
  `dos/_bin/` data dir + `.gitignore` (the built binary is a release artifact, not
  committed to the kernel repo — unlike the plugin's, which *must* be committed
  because the plugin ships as its git tree; the wheel is built, so its binary is
  built-then-bundled, never committed). `dos/hook_binary.py` locator (pure stdlib,
  platform map shared in spirit with `build_hook_binary.py`). `pyproject` package-
  data glob so the dir ships. Tests: locator returns None on a clean tree (no binary
  committed), returns the path when one is dropped in, and the platform map matches
  the build matrix. **No CLI behavior change yet beyond "consult and fall back" —
  the Python path stays the default until a binary is present, so the suite stays
  green on a binary-free checkout.**

- **Phase 2 — the build wiring (per-platform wheels).** A `scripts/build_wheels.py`
  (sibling of `build_dist.py`) that, per arch: `go build` the binary into
  `src/dos/_bin/`, `python -m build --wheel`, then re-tag the resulting wheel from
  `py3-none-any` to `py3-none-<platform>` (via `wheel tags` or a `--config-setting`).
  Keep `build_dist.py` for the pure sdist + the local universal smoke. Document the
  matrix → wheel-tag mapping (the `manylinux`/`macosx`/`win` platform tags).

- **Phase 3 (SHIPPED 2026-06-10) — CI builds the matrix.** `publish.yml` + `ci.yml`'s
  `build` jobs now `setup-go@v5` and run `scripts/build_wheels.py` → the 6 platform
  wheels + 1 sdist as the `dist` artifact the existing OIDC publish jobs upload
  unchanged; `twine check` over every one. **Decided: ONE ubuntu runner
  cross-compiles all six** (not native-runner legs). This is honest because the binary
  is `CGO_ENABLED=0` static Go — there is NO glibc/libc link, so the `manylinux2014`
  tag's "runs on any 2014+ glibc" promise holds regardless of which OS built it (a
  native-runner matrix would only matter if we ever needed cgo; we don't). Simpler +
  cheaper + the artifacts are byte-identical to a native build (`-trimpath`).

  > **⚠ Bug found + fixed building Phase 3 (the `build/` staging leak).** The first
  > matrix build shipped a **macOS Mach-O binary inside the Windows wheel**. Cause:
  > `python -m build` stages the source into `build/lib/dos/_bin/`, and setuptools does
  > NOT prune files there that no longer exist in the source — so each arch's binary
  > accumulated and the next wheel swept in every prior arch's. Clearing only the
  > source `_bin/` was insufficient. Fix: `build_wheels.py` wipes BOTH `_bin/` AND the
  > `build/` staging dir before each `python -m build` (`_clean_for_build`). Pinned by
  > a per-wheel byte-format assertion (each wheel holds exactly ONE binary whose magic
  > bytes — `MZ`/`\x7fELF`/Mach-O — match its platform tag). The lesson: a build
  > script's "OK" message is not proof; inspect the produced bytes.

- **Phase 4 — measure the pip native win + decide the console-script shim.** Bench
  the in-CLI native route vs the Python verb on a pip install (the §3 note); if the
  interpreter-boot tax dominates, add the `dos-hook` console script + document
  wiring it into settings.json for pip adopters. Update `PUBLISHING.md` Stage 1 with
  the per-platform-wheel reality.

## 5. What this does NOT change (guardrails)

- **The plugin path is untouched.** `claude-plugin/bin/` stays committed; docs/125
  GHF4 stands. This adds a *second* delivery of the same binary for a *different*
  surface.
- **The kernel stays vendor-blind + near-stdlib.** The binary is data; the locator
  is pure stdlib; no new runtime dependency; no `src/dos/` import of build tooling.
- **No build-time `go build` during `pip install`.** The sdist is pure-source +
  pure-Python-fallback; binaries are pre-built into wheels by CI, never compiled on
  the install host.
- **The fallback discipline is absolute.** Missing/mismatched/crashing binary → the
  Python verb. No machine is blocked; the binary is only ever an accelerator.
- **The upload stays owner-only.** This plan ships the *automatable* half (build the
  right artifacts); the actual PyPI upload is the protected-environment, owner-
  approved step `PUBLISHING.md` Stage 1 already gates.

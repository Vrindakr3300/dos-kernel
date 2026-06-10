# WSL audit — proving out DOS + its test suite on Linux

**Date:** 2026-06-10
**Auditor:** Claude (Opus 4.8), `/goal audit and prove out DOS and tests etc on WSL`
**Audited commit:** `a2a78fe` (master HEAD at export time; live HEAD advanced under
concurrent Windows sessions during the run — the multi-session-hot tree).
**Environment:** WSL2 **Ubuntu 24.04.4 LTS** (kernel 6.6.114.1-microsoft-standard-WSL2),
**Python 3.12.3**, git 2.43.0, pytest 9.0.3, hypothesis 6.155.2.

## TL;DR

DOS **proves out on WSL/Linux**. The kernel installs editably, all **151** package
modules import with zero failures, the full syscall ritual (`doctor`/`arbitrate`/
`verify`/`lint`/`man`/`plan`/`commit-audit`) behaves correctly, and the MCP server
loads and passes its contract suite. The full pytest suite is **3856 passed, 4
failed, 14 skipped** — and **all 4 failures are test/example portability gaps
(Windows-isms exercised on Linux), not kernel logic defects.** Net real kernel
defects found on Linux: **0**.

One of the four — an unattended `sudo` in a shipped example — does more than fail:
it **hangs the entire suite indefinitely** on a stock Linux/WSL box. That is the
headline finding and the one worth fixing upstream.

## Method

To get a faithful read (the live `/mnt/c` tree is multi-session-hot and shows 129
dirty files — verified to be **pure CRLF↔LF churn**: the 8 `src/`+`tests/` diffs
vanish under `git diff --ignore-cr-at-eol`), I exported the committed tree only:

```bash
git archive <HEAD> | tar -x -C ~/dos-wsl-audit     # ext4, no /mnt/c, no .git noise
python3 -m venv .venv && pip install -e ".[dev]"   # PEP-668 needs a venv on 24.04
```

A second venv (`~/dos-mcp-venv`) got `pip install -e ".[mcp]"` to exercise the MCP
server in isolation.

## What passed (the substrate is sound on Linux)

- **Editable install** — clean; `dos` resolves to v0.20.1; console script on PATH.
- **Module imports** — **151/151** kernel modules import, zero failures.
- **`dos doctor`** — reports `linux-x86_64`, py 3.12.3, full lane taxonomy, evidence
  sources, judges, overlap policy; workspace facts resolve off the seam.
- **`dos arbitrate`** — the admission kernel is correct. Requesting `src`/`global`
  with `--kind cluster` correctly **REFUSES with `SELF_MODIFY`** (the repo is its own
  kernel, `is_kernel_repo: true`); a disjoint lane (`paper`) **ACQUIREs** directly.
  It never double-books. *(Nit below.)*
- **`dos verify`** — runs against a plain git repo with no plan, answers
  `NOT_SHIPPED … (via none)` from git ancestry alone. The headline litmus holds.
- **`dos lint`** — config clean, text + JSON.
- **`dos man` / `dos plan` / `dos commit-audit`** — all functional; commit-audit
  witnesses the audit commit as a doc-scope claim.
- **MCP server** — `[mcp]` extra installs cleanly (mcp 1.27.2 + FastMCP stack);
  `dos_mcp` imports; `dos-mcp` console script present; **54 MCP-related tests pass**
  in the `[mcp]` venv (`test_mcp_server.py`, `test_interpret_parity.py`, and the
  plugin-manifest build check). With the extra absent, the server emits a clean
  install-hint, not a traceback (correct graceful degradation; PyYAML-only core).

## The 4 failures — all triaged to test/example portability, 0 kernel defects

| # | Test | Root cause | Kernel bug? |
|---|------|-----------|-------------|
| 1 | `test_filelock::test_atomic_replace_retries_then_succeeds` | Simulates `WinError-5`; `_filelock.atomic_replace` retries only on the `winerror` attr, which **is Windows-only**. The production code's docstring *documents* that on POSIX it degrades to one attempt — so the code is correct; the test asserts the Windows path. | **No** — needs `@skipif(sys.platform != 'win32')` (its sibling `test_filelock.py:201` already has one). |
| 2 | `test_filelock::test_atomic_replace_raises_when_budget_exhausted` | Asserts `ei.value.winerror == 5`; `winerror` doesn't exist on a Linux `PermissionError`. | **No** — same missing skip-guard. |
| 3 | `test_plugin_manifest::test_mcp_server_actually_builds` | Imports `dos_mcp.server` which needs the `[mcp]` extra; the suite venv has `[dev]` only, so it hits the graceful `SystemExit` install-hint. The test **assumes** the extra is installed but has no skip guard (unlike `test_mcp_server.py:24`, which skips correctly). | **No** — proven to **pass** in the `[mcp]` venv; needs a skip guard. |
| 4 | `test_posttool_sensor::test_end_to_end_output_poll_fires_in_flight` | The event hard-codes `cwd: "/work/dos"` while the fixture sets `DISPATCH_WORKSPACE=tmp_path`. `cmd_hook_posttool` resolves workspace as **event-cwd › env**; on Linux `/work/dos` is a valid absolute path so it **wins** over the tmp workspace, the per-test accumulator never gets the writes, and REPEATING never fires. On Windows `/work/dos` is not a valid root, so the env wins and it accidentally passes. **Proven**: when the event `cwd` matches the workspace, REPEATING fires correctly on read #3. | **No** — the in-flight `tool_stream` sensor logic is correct on Linux; the test fixture has a conflicting `cwd`. |

## ★ Headline finding — the suite HANGS on Linux/WSL (unattended `sudo`)

Before any of the above is even reachable, the full suite **deadlocks forever** at
~37% on a stock Linux box. Cause:

- `test_hermes_integration_example::test_safety_demo_blocks_every_arbitrary_exec_command`
  runs the shipped example `examples/hermes_integration/run_safety_demo.py`, whose
  naive arm **executes** a stand-in hazard `sudo bash -c "echo PRIVILEGED >> …"`.
- `examples/hermes_integration/swarm_agent.py:run_tool_command` did
  `subprocess.run(cmd, shell=True, capture_output=True, text=True)` with **no
  timeout, no stdin redirect, and no session detach**.
- `sudo` opens the **controlling terminal** (`/dev/tty`) to prompt for a password.
  Under pytest in a background process group, the tty read raises **SIGTTIN → the
  whole group goes to state `T` (stopped)**: pytest `sigsuspend`, the `sudo` child
  `do_signal_stop`. It is a job-control deadlock, and `timeout=` never fires because
  the parent that would measure it is itself stopped.

Why Windows never sees it: Windows has no blocking `sudo`, so the command fails
fast. The test author anticipated only two cases ("sudo no-ops on Windows" → naive
count 2; "sudo runs where it works" → 3) and missed the **default Linux case**:
passwordless sudo not configured → `sudo -n true` exits 1 → it blocks.

**The fix (validated in the export, not yet landed on the live tree):** give
`run_tool_command` `stdin=subprocess.DEVNULL, timeout=10, start_new_session=True`
and catch `TimeoutExpired`. `stdin=DEVNULL` **alone is insufficient** — `sudo` reads
`/dev/tty`, not stdin; **`start_new_session=True`** is what removes the controlling
tty so `sudo` fails rc=1 fast instead of stopping the group. Proven: the exact call
with all three returns rc=1 in <1s; with the fix applied the suite runs to
completion (the 3856/4/14 result above). A stand-in that only echoes needs no tty,
so the `bash -c`/`sh -c` hazards still fire and the test's `naive_count >= 2`
invariant is preserved.

## Recommended upstream fixes (none touch the kernel)

1. **`examples/hermes_integration/swarm_agent.py`** — add
   `stdin=subprocess.DEVNULL, timeout=10, start_new_session=True` (+ `TimeoutExpired`
   guard) to `run_tool_command`. *Unblocks the whole suite on Linux/CI.* High value.
2. **`tests/test_filelock.py`** — mark the two `winerror`-simulating tests
   `@pytest.mark.skipif(sys.platform != "win32", …)` (match the existing sibling).
3. **`tests/test_plugin_manifest.py::test_mcp_server_actually_builds`** — add the
   same `importorskip("mcp")` / skip guard that `test_mcp_server.py` already uses.
4. **`tests/test_posttool_sensor.py::test_end_to_end_output_poll_fires_in_flight`** —
   make the event's `cwd` equal the tmp workspace (or drop the conflicting `cwd`) so
   workspace resolution doesn't diverge by platform.

## Minor observation (not a bug)

`dos arbitrate` in the **bare auto-pick** path (no `--kind`) returns the reason
*"requested '<lane>' was busy"* even when the true cause is `SELF_MODIFY`, not
contention (the `--kind cluster` path reports the precise SELF_MODIFY reason). The
*decision* is always safe — it never double-books and correctly steers off the
kernel's own path — only the auto-pick *wording* is imprecise. Matches the known
"arbiter false 'was busy'" message-quality nit.

## Cross-cutting note (method, for the next Linux/WSL run)

- Build the faithful tree with `git archive HEAD | tar -x` into `$HOME` (ext4), not
  `/mnt/c` (CRLF + concurrent-Windows-session noise).
- A process backgrounded *inside* a one-shot `wsl -d … bash script &` does **not**
  outlive the one-shot (WSL tears the tree down on return); `setsid …&` doesn't save
  it either. Run the suite in the **foreground of a `run_in_background` PowerShell
  tool call** (that keeps the WSL instance alive), and avoid concurrent foreground
  `wsl` probes on the side (they can job-control-stop the suite's process group).
- A `git archive` export has **no `.git`** — ~11 binary-bundle / verify-clean tests
  (`test_hook_binaries_bundled`, `test_verify_plugin_install`, `test_build_wheels_*`)
  shell `git … HEAD` and fail with exit 128 until you `git init && add && commit` the
  export. Those failures are env, not code; init the export to clear them.

## Fixes landed — `5e06928` (2026-06-10)

All four recommended fixes are committed (`fix(portability): unblock the suite on
Linux/WSL`, witnessed clean by `dos commit-audit` — `[diff-witnessed]`). They touch
only `examples/` + `tests/`, never `src/dos/`. For #2 I chose to **preserve cross-OS
coverage** (a portable `_winerror_oserror()` that sets `.winerror` on every OS) over
a `skipif(win32)`, honouring the file's stated "CI on any OS exercises the retry
loop" intent — the two formerly-failing retry tests now **run and pass** on Linux,
they don't skip.

**Re-verified on WSL2 Ubuntu 24.04 (py3.12), `.git`-initialized export:** the suite
no longer hangs; **3914 passed**, and the original 4 failures are gone.

### Two residual full-suite failures — NEITHER from these fixes

1. `test_vendor_agnostic_kernel::test_vendor_names_only_appear_in_prose_not_branches`
   — flags `hook_binary.py:128` (`if dialect and dialect != "claude-code":`), a
   vendor literal as a `Compare` operand in a **kernel module this work never
   touched**. It is **pre-existing on current master** (HEAD advanced ~10 commits
   between the two audit exports; a concurrent session introduced it) and a genuine
   no-vendor-litmus drift — but fixing it edits `src/dos/`, a separate/more-sensitive
   lane, so it is left for a dedicated change, not bundled here. **Flag for follow-up.**
2. `test_install_levels::test_real_wsl_pip_install_and_dogfood` — calls `wsl.exe …
   wslpath` and is built to run **from Windows into WSL**; run from inside WSL it
   nests `wsl.exe` and `wslpath` errors. A test-harness env artifact, not a defect.
3. *(added 2026-06-10, install-surface audit)*
   `test_hermes_integration_example::test_safety_demo_blocks_every_arbitrary_exec_command`
   — fails (`naive = 0`) on a **Windows box whose `bash` resolves to
   `C:\WINDOWS\system32\bash.exe` (WSL bash)**: the demo forward-slashes the
   sentinel to a `C:/`-rooted home-directory path, which WSL bash cannot address
   (`No such file or directory`), so no hazard ever fires. Probed: the bare pre-fix call fails
   identically, and a `git archive HEAD` export of the committed tree reproduces it
   — **pre-existing + environmental, NOT caused by the `5e06928` fix** (CI's
   windows runner passes because git-bash, which understands `C:/` paths, wins
   PATH there). Candidate fix: `wslpath`-convert the sentinel (or detect the
   System32 bash) in the demo. See
   [2026-06-10_install-surface-audit.md](2026-06-10_install-surface-audit.md).

   **CLOSED 2026-06-10 by `b64ce1d`** (upgrades the interim skip `a0784c7`):
   `run_tool_command` now substitutes the BARE sentinel filename and anchors the
   child with `cwd=sentinel.parent` — the one path shape every bash dialect
   resolves (the WSL child inherits the Windows cwd as `/mnt/c/…`);
   `hazards_can_fire` probes by EXECUTION (`bash -c "echo ok"`, then `sh`),
   never PATH inspection; and the pinning test asserts the honest invariant
   `naive >= 1` (where only the WSL-launcher bash resolves, `sh` resolves to
   nothing, so exactly one hazard can fire). Proven both ways on the box that
   redded the v0.21.0 release verify: the test green in foreground isolation
   AND inside a backgrounded full-suite run under the System32-bash PATH
   (4008 passed, this test among them), plus 6/6 green on WSL Ubuntu 24.04
   (2.6s — the `5e06928` sudo fail-fast preserved, no hang).

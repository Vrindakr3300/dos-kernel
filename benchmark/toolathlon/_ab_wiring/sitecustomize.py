"""Container-side WARN-arm wiring for the Toolathlon lift A/B (docs/164 F0 / docs/163).

`run_single_containerized.sh` copies the Toolathlon project into the container's `/workspace` and runs
`uv run main.py` there (main.py:11 loads the monkey-patches). This file, dropped at `/workspace`
(Python auto-imports `sitecustomize` at interpreter start, before main.py), installs the DOS WARN
patch — but ONLY when `DOS_WARN` is truthy, so the SAME container image runs BOTH arms and the env
flag is the only delta (the docs/144 OBSERVE-vs-WARN discipline).

It is a NO-OP unless DOS_WARN is set, so it is safe to bake into both arms' workspace; the OBSERVE arm
simply never sets the flag. Wiring requirements (handled by the patched runner, see AB_RUN_RECIPE.md):
  1. the dos repo is mounted/copied so `dos` (under src/) + `benchmark.toolathlon` (repo root) import;
  2. `DOS_WARN` is passed into the container env for the WARN arm.

PYTHONPATH (verified 2026-06-05): `dos` lives under `src/`, `benchmark.toolathlon` at the repo root,
so BOTH must be on the path. The dos repo is mounted at `/dos` (`-v <hostdos>:/dos`).
"""

import os
import sys

_DOS_MOUNT = os.environ.get("DOS_REPO_MOUNT", "/dos")

if os.environ.get("DOS_WARN") not in (None, "", "0"):
    # both paths: /dos/src (for `import dos`) + /dos (for `benchmark.toolathlon.warn_patch`)
    for p in (f"{_DOS_MOUNT}/src", _DOS_MOUNT):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        from benchmark.toolathlon.warn_patch import apply_warn_patch

        active = apply_warn_patch()
        # one-line breadcrumb to the run log so the operator can confirm the arm wired (the
        # AB_RUN_RECIPE spend-gate: this must print active=True in-container or the WARN arm is a
        # silent no-op == OBSERVE). Goes to stderr to avoid polluting any stdout the harness parses.
        print(f"[DOS sitecustomize] WARN arm active={active}", file=sys.stderr, flush=True)
    except Exception as e:  # never break the harness if the wiring is wrong — fail toward OBSERVE
        print(f"[DOS sitecustomize] WARN wiring FAILED ({type(e).__name__}: {e}) — "
              f"running as OBSERVE (un-patched). FIX BEFORE TRUSTING THIS ARM.",
              file=sys.stderr, flush=True)

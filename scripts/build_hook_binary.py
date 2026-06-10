#!/usr/bin/env python
"""build_hook_binary.py — cross-compile the native `dos-hook` into the plugin bundle (docs/125 GHF4).

> **Tooling that operates ON the package, never inside it** (CLAUDE.md "Four things
> live OUTSIDE the four layers"). Like `build_plugin.py` and the release scripts,
> this consumes the repo and is unaware to the kernel — nothing under `src/dos/`
> imports it, and it is not shipped in the wheel. It exists to put the compiled
> `dos-hook` fast-path binary where the plugin's `hooks.json` can call it
> (`claude-plugin/bin/dos-hook-<os>-<arch>`), so a Claude Code operator pays ZERO
> Python cold-start on the per-tool-call hooks (the GHF throughline).

What it does
============

Cross-compiles `go/cmd/dos-hook` for the common desktop arches with a STATIC,
no-cgo build (`CGO_ENABLED=0`) so each binary is self-contained and the cross-
compile needs no target toolchain. Outputs one binary per arch into
`claude-plugin/bin/`:

    dos-hook-linux-amd64      dos-hook-linux-arm64
    dos-hook-darwin-amd64     dos-hook-darwin-arm64
    dos-hook-windows-amd64.exe dos-hook-windows-arm64.exe

The per-arch launchers (`bin/dos-hook`, a POSIX `sh` script, and `bin/dos-hook.ps1`,
a PowerShell script) are COMMITTED source (they pick the right binary at runtime and
fall back to Python) — this script does NOT write them; it only produces the
binaries they dispatch to.

Why the binaries ARE committed (the bundled-binary discipline)
==============================================================

The binaries are now COMMITTED into `claude-plugin/bin/` so the plugin is a DIRECT
install: a Claude Code user runs `/plugin marketplace add …` (which clones this git
repo) and the native fast-path binary for their arch is ALREADY THERE — no build
step, no separate release-asset download, no silent fall-back to Python. A plugin is
distributed as the git tree itself (`marketplace.json` `source: ./claude-plugin`),
so a gitignored binary is a binary the user never gets; committing them is the only
way the bundle actually ships.

The cost is ~24 MB of compiled artifacts in git and a re-commit whenever the Go
source changes — accepted deliberately so the fast-path is real for everyone, not
just whoever rebuilds locally. `tests/test_hook_binaries_bundled.py` pins that every
default-matrix binary is present + tracked (and `--check` here reports the matrix). A
host on an arch outside the matrix still falls through the launcher to the Python
verb (the docs/100 fallback), so no one is blocked.

Usage
=====

    python scripts/build_hook_binary.py                 # build all default arches
    python scripts/build_hook_binary.py --host           # build only the host arch (dev)
    python scripts/build_hook_binary.py --arches linux/amd64 darwin/arm64
    python scripts/build_hook_binary.py --check          # report what WOULD build, write nothing
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# The default cross-compile matrix — the common desktop/CI arches. A host whose arch
# is not here falls back to the Python verb via the launcher (never blocked).
# Covers the full amd/intel (amd64) + arm64 grid across linux/macOS/windows, so every
# mainstream desktop gets the native fast-path (windows/arm64 included — a Surface/
# WoA box otherwise silently fell back to Python via dos-hook.ps1).
DEFAULT_ARCHES = (
    "linux/amd64",
    "linux/arm64",
    "darwin/amd64",
    "darwin/arm64",
    "windows/amd64",
    "windows/arm64",
)


def _repo_root() -> Path:
    """The repo top-level — git's answer, NOT __file__ math (the build_plugin.py idiom)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return Path(__file__).resolve().parents[1]


def _binary_name(goos: str, goarch: str) -> str:
    """The per-arch output name the launcher dispatches to: dos-hook-<os>-<arch>[.exe]."""
    suffix = ".exe" if goos == "windows" else ""
    return f"dos-hook-{goos}-{goarch}{suffix}"


def _host_arch() -> str:
    """The host GOOS/GOARCH as `os/arch` (best-effort map from platform)."""
    goos = {"windows": "windows", "darwin": "darwin", "linux": "linux"}.get(
        platform.system().lower(), platform.system().lower()
    )
    m = platform.machine().lower()
    goarch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(m, m)
    return f"{goos}/{goarch}"


def build_one(root: Path, goos: str, goarch: str, *, check: bool) -> tuple[bool, str]:
    """Build (or, with check, plan) one arch. Returns (ok, message)."""
    go_dir = root / "go"
    out_dir = root / "claude-plugin" / "bin"
    out = out_dir / _binary_name(goos, goarch)
    if check:
        return True, f"would build {goos}/{goarch} -> {out.relative_to(root).as_posix()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(GOOS=goos, GOARCH=goarch, CGO_ENABLED="0")
    # `-trimpath` makes the build reproducible (no local path leakage); a static
    # no-cgo build cross-compiles without a target toolchain.
    proc = subprocess.run(
        ["go", "build", "-trimpath", "-o", str(out), "./cmd/dos-hook"],
        cwd=str(go_dir), env=env, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return False, f"FAILED {goos}/{goarch}: {proc.stderr.strip()}"
    size_kb = out.stat().st_size // 1024
    return True, f"built {goos}/{goarch} -> {out.relative_to(root).as_posix()} ({size_kb} KB)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", action="store_true",
                        help="build only the host arch (a fast dev build)")
    parser.add_argument("--arches", nargs="+", metavar="OS/ARCH",
                        help="explicit arches to build (default: the common matrix)")
    parser.add_argument("--check", action="store_true",
                        help="report what would build; write nothing")
    args = parser.parse_args(argv)

    if shutil.which("go") is None:
        print("error: the Go toolchain is not on PATH — cannot build the native hook "
              "binary (install Go 1.25+ or skip; the plugin falls back to the Python "
              "verb where no binary is present).", file=sys.stderr)
        return 2

    root = _repo_root()
    if args.host:
        arches = [_host_arch()]
    elif args.arches:
        arches = args.arches
    else:
        arches = list(DEFAULT_ARCHES)

    ok_all = True
    for spec in arches:
        try:
            goos, goarch = spec.split("/", 1)
        except ValueError:
            print(f"error: malformed arch {spec!r} — expected OS/ARCH (e.g. linux/amd64)",
                  file=sys.stderr)
            ok_all = False
            continue
        ok, msg = build_one(root, goos, goarch, check=args.check)
        print(("  " if ok else "  ! ") + msg)
        ok_all = ok_all and ok

    if not args.check:
        print(f"\n{'OK' if ok_all else 'INCOMPLETE'}: native dos-hook binaries -> "
              f"claude-plugin/bin/ (commit these alongside the launchers; the plugin "
              f"ships them in git so the install is direct — see test_hook_binaries_bundled).")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())

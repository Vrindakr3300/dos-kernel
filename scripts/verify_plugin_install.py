#!/usr/bin/env python
"""verify_plugin_install.py — is an installed DOS plugin bundle what git shipped?

> **Tooling that operates ON the package, never inside it** (CLAUDE.md "Four things
> live OUTSIDE the four layers"). Like `build_plugin.py` and the release scripts, this
> consumes the repo and is unaware to the kernel: nothing under `src/dos/` imports it.

The integrity witness for the plugin's DISTRIBUTION
===================================================

A Claude Code plugin is distributed as its git tree: `/plugin marketplace add` clones
the repo and `marketplace.json` points `source: ./claude-plugin`. The plugin is then
COPIED into `~/.claude/plugins/cache/<market>/<plugin>/<version>/`. Two ways that copy
can silently diverge from what the repo committed:

  * **STRAY files** — a directory-source install copies the WORKING TREE, not a clean
    `git archive`, so anything gitignored-but-present (e.g. the runtime `bin/.dos/`
    stream debris the plugin's own hook writes when it runs with cwd inside `bin/`)
    rides along into the install. It won't ship via a marketplace CLONE, but a local
    directory install carries it.
  * **MODIFIED files** — a binary or manifest in the install whose bytes no longer
    match the committed blob (a half-finished rebuild, a hand-edit, corruption).

This script answers "is what I installed what git shipped?" — the same
*did-it-actually-X* question the kernel asks agents (docs/138), turned on the plugin's
own files. The reference is **git's own blob SHA**: `git hash-object <file>` reproduces
exactly the SHA `git ls-tree HEAD claude-plugin` records, so the comparison uses git's
hashing, not a private scheme — the honest, forge-resistant reference (the bytes git
committed, which the installer did not author).

It is read-only: it hashes files and prints a verdict; it changes nothing, installs
nothing, deletes nothing. The exit code IS the verdict (0 clean / 1 a divergence
found), so it drops into CI or a pre-release gate.

Usage
=====

    python scripts/verify_plugin_install.py <install-dir>     # check an install
    python scripts/verify_plugin_install.py --json <dir>      # machine form
    python scripts/verify_plugin_install.py --self            # check claude-plugin/ in-repo

`--self` checks the repo's own `claude-plugin/` working tree against HEAD — the
dogfood form (it will report the same STRAY debris a directory install carries).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# The plugin subtree, relative to the repo root, as git records it.
PLUGIN_PREFIX = "claude-plugin"

# Stray paths that are EXPECTED and benign: runtime debris the plugin's own hook
# writes under bin/.dos/ (a tool-stream journal) when it fires with cwd inside the
# bundle. It is gitignored (never ships via a marketplace clone) and harmless; we
# down-grade it to an informational note rather than a failing STRAY so the check
# does not cry wolf on every dogfooded install. Everything ELSE stray fails.
_BENIGN_STRAY_PREFIXES = ("bin/.dos/",)


def _repo_root() -> Path:
    """The repo top-level — git's answer, not __file__ math (matches build_plugin.py)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return Path(__file__).resolve().parents[1]


def committed_blob_shas(root: Path) -> dict[str, str]:
    """{path-relative-to-claude-plugin/ -> git blob SHA} for every tracked plugin file.

    From `git ls-tree -r HEAD claude-plugin`. The blob SHA is the reference the
    install's files must reproduce."""
    out = subprocess.run(
        ["git", "ls-tree", "-r", "HEAD", PLUGIN_PREFIX],
        cwd=str(root), capture_output=True, text=True, check=True,
    )
    shas: dict[str, str] = {}
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # format: "<mode> <type> <sha>\t<path>"
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) != 3 or parts[1] != "blob":
            continue
        sha = parts[2]
        rel = path[len(PLUGIN_PREFIX) + 1:] if path.startswith(PLUGIN_PREFIX + "/") else path
        shas[rel] = sha
    return shas


def _hash_object(root: Path, file: Path) -> str | None:
    """git's blob SHA for an arbitrary file (need not be in any repo): the same
    sha1('blob <len>\\0' + bytes) git ls-tree records. None if git can't hash it."""
    try:
        out = subprocess.run(
            ["git", "hash-object", str(file)],
            cwd=str(root), capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _installed_files(install_dir: Path) -> dict[str, Path]:
    """{path-relative-to-install-root -> absolute path} for every file in the install."""
    if not install_dir.is_dir():
        return {}
    out: dict[str, Path] = {}
    for p in install_dir.rglob("*"):
        if p.is_file():
            out[p.relative_to(install_dir).as_posix()] = p
    return out


def _is_benign_stray(rel: str) -> bool:
    return any(rel.startswith(pfx) for pfx in _BENIGN_STRAY_PREFIXES)


def verify(install_dir: Path, root: Path | None = None) -> dict:
    """Compare an installed bundle against HEAD:claude-plugin. Returns a report dict:

        {ok, missing:[...], modified:[...], stray:[...], benign_stray:[...],
         matched:int, total_committed:int}

    ok is False iff there is a missing, modified, or (non-benign) stray file.
    """
    root = root or _repo_root()
    committed = committed_blob_shas(root)
    installed = _installed_files(install_dir)

    missing: list[str] = []
    modified: list[str] = []
    matched = 0
    for rel, want_sha in sorted(committed.items()):
        f = installed.get(rel)
        if f is None:
            missing.append(rel)
            continue
        got = _hash_object(root, f)
        if got == want_sha:
            matched += 1
        else:
            modified.append(rel)

    stray: list[str] = []
    benign_stray: list[str] = []
    for rel in sorted(installed):
        if rel in committed:
            continue
        (benign_stray if _is_benign_stray(rel) else stray).append(rel)

    ok = not (missing or modified or stray)
    return {
        "ok": ok,
        "install_dir": str(install_dir),
        "missing": missing,
        "modified": modified,
        "stray": stray,
        "benign_stray": benign_stray,
        "matched": matched,
        "total_committed": len(committed),
    }


def _render(report: dict) -> str:
    lines = [f"plugin install integrity -- {report['install_dir']}"]
    lines.append(f"  matched        {report['matched']}/{report['total_committed']} "
                 f"committed files reproduce their git blob SHA")
    for kind, label in (("missing", "MISSING (in HEAD, not installed)"),
                        ("modified", "MODIFIED (bytes differ from the committed blob)"),
                        ("stray", "STRAY (installed, not in HEAD)")):
        items = report[kind]
        if items:
            lines.append(f"  {label}:")
            for rel in items:
                lines.append(f"    - {rel}")
    if report["benign_stray"]:
        lines.append("  benign stray (gitignored runtime debris, won't ship via clone):")
        for rel in report["benign_stray"]:
            lines.append(f"    - {rel}")
    lines.append("  OK" if report["ok"] else "  DIVERGENCE FOUND")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("install_dir", nargs="?",
                        help="the installed bundle dir to check (omit with --self)")
    parser.add_argument("--self", action="store_true",
                        help="check the repo's own claude-plugin/ working tree vs HEAD")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)
    root = _repo_root()

    if args.self:
        install_dir = root / PLUGIN_PREFIX
    elif args.install_dir:
        install_dir = Path(args.install_dir).resolve()
    else:
        parser.error("give an install dir or use --self")

    report = verify(install_dir, root)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_render(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

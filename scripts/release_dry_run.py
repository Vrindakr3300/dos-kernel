#!/usr/bin/env python3
"""The tag-last release dry-run gate — adjudicate the commit, not the tree.

docs/295 P2. Run between the release COMMIT and the release TAG:

  python scripts/release_dry_run.py            # full suite against HEAD
  python scripts/release_dry_run.py --fast     # the release-perturbation set (~seconds)
  python scripts/release_dry_run.py v0.23.3    # any ref
  python scripts/release_dry_run.py --json     # machine verdict on stdout

Exit 0 = tag it. Exit 1 = fix forward (another commit), re-run, THEN tag —
no version number is minted, nothing is pushed, nothing is burned.

Why this exists (the 2026-06-10 v0.23.x night, three burned version numbers):
the tag is a CLAIM ("these bytes are releasable") and the publish pipeline's
ci-green gate is its WITNESS — but the witness ran only after the claim was
world-visible, so every red cost a permanent version number. This script is
the same witness shifted left of the tag mint. The out-of-loop gate in
publish.yml is unchanged — defense in depth, this is the cheap inner rung.

Two design rules, both bought with that night's evidence:

1. **The subject is the committed bytes, never the working tree.** This repo's
   tree is multi-session-hot; a working-tree suite run produced four false
   signals alongside the true ones. The suite here runs in a detached
   `git worktree` of the ref — the same isolation `dos-self-improve` applies
   to its candidates (docs/280): the tree being adjudicated is not the tree
   being edited.
2. **Workflow files are parsed at the ref, from `git show` bytes** — the
   v0.23.0 class (a workflow that fails CI in 0 seconds) is a release-blocking
   fact of the candidate bytes, not of the working tree.

Isolation is two-layer, and BOTH layers earned their place the same day this
script was born. The worktree isolates against the dirty working tree; a
scratch venv (`--system-site-packages` + `pip install -e <worktree>
--no-deps`) isolates against the machine's editable install — without it the
worktree suite imports `dos` through the global editable `.pth` finder
(which PYTHONPATH cannot shadow), so `dos.__version__` reads the MAIN tree's
version markers. The first live run of this script proved that bites: a
sibling session bumped the main tree mid-flight and every version-drift test
in a v0.23.3 worktree read 0.23.4. The venv's own editable finder registers
ahead of the system one (venv site-packages is processed first), so `dos`
resolves to the worktree; pytest/PyYAML still come from the system site.
Costs ~15s; `--no-venv` opts out when the main tree provably sits at the ref.

This is dev/release tooling, not kernel — it operates ON the package and is
never imported BY it (the "no `scripts/` in the kernel" litmus).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The release-perturbation family: the doc-coherence tests the release flow
# itself perturbs (version literals, generated artifacts, packaging pins).
# These caught — or would have caught — the v0.23.1 and v0.23.2 classes.
# Existence-checked at the ref: a missing file is skipped with a note, never
# an error (test files move; the fast set degrades, the full suite does not).
FAST_SET = (
    "tests/test_docs_version_drift.py",
    "tests/test_readme_assembly.py",
    "tests/test_plugin_manifest.py",
    "tests/test_canonical_example_lockstep.py",
    "tests/test_install_drift.py",
)

_FULL_TIMEOUT_S = 900
_FAST_TIMEOUT_S = 240

_SUMMARY_RE = re.compile(
    r"(?:(?P<failed>\d+) failed)?(?:, )?(?P<passed>\d+) passed"
    r"(?:, (?P<skipped>\d+) skipped)?(?:, .*?)?(?:, (?P<errors>\d+) errors?)?"
)


def run(cmd: list[str], cwd: Path | None = None, timeout: int | None = None) -> tuple[int, str]:
    """Run a command; return (exit_code, combined output). Never raises."""
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        return proc.returncode, proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.output or "") + f"\n(timed out after {timeout}s)"
    except FileNotFoundError as exc:
        return 127, str(exc)


def repo_root() -> Path:
    code, out = run(["git", "rev-parse", "--show-toplevel"])
    return Path(out.strip()) if code == 0 and out.strip() else Path.cwd()


def parse_workflows_at_ref(ref: str) -> dict:
    """YAML-parse every .github/workflows file AT THE REF (git show bytes)."""
    out: dict = {"ok": True, "files": {}, "note": None}
    code, listing = run(["git", "ls-tree", "-r", "--name-only", ref, "--", ".github/workflows"])
    if code != 0:
        out.update(ok=False, note=f"git ls-tree failed for ref {ref!r}")
        return out
    paths = [p for p in listing.splitlines() if p.endswith((".yml", ".yaml"))]
    if not paths:
        out["note"] = "no workflow files at ref"
        return out
    try:
        import yaml as _yaml
    except Exception:
        out["note"] = "PyYAML unavailable - parse check skipped"
        return out
    for p in paths:
        code, text = run(["git", "show", f"{ref}:{p}"])
        if code != 0:
            out["files"][p] = "unreadable at ref"
            out["ok"] = False
            continue
        try:
            _yaml.safe_load(text)
            out["files"][p] = None
        except Exception as exc:
            out["files"][p] = " ".join(str(exc).split())[:300] or exc.__class__.__name__
            out["ok"] = False
    return out


def parse_pytest_summary(output: str) -> dict:
    """Fold the pytest tail into counts; tolerant of format drift."""
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for line in reversed(output.splitlines()[-15:]):
        if " passed" in line or " failed" in line or " error" in line:
            for key, pat in (
                ("passed", r"(\d+) passed"), ("failed", r"(\d+) failed"),
                ("skipped", r"(\d+) skipped"), ("errors", r"(\d+) errors?"),
            ):
                m = re.search(pat, line)
                if m:
                    counts[key] = int(m.group(1))
            break
    failed_names = [
        ln.strip() for ln in output.splitlines()
        if ln.startswith(("FAILED ", "ERROR "))
    ][:20]
    counts["failed_names"] = failed_names
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tag-last release dry run: adjudicate a ref's committed "
                    "bytes in a detached worktree (docs/295 P2)."
    )
    parser.add_argument("ref", nargs="?", default="HEAD",
                        help="Ref to adjudicate (default HEAD)")
    parser.add_argument("--fast", action="store_true",
                        help="Run only the release-perturbation test set")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Emit the machine verdict as JSON on stdout")
    parser.add_argument("--keep-worktree", action="store_true",
                        help="Leave the worktree behind for inspection")
    parser.add_argument("--no-venv", action="store_true",
                        help="Skip the scratch-venv isolation (only safe when "
                             "the main tree's version markers sit at the ref)")
    args = parser.parse_args()

    root = repo_root()
    # ^{commit}: an annotated tag ref resolves to the TAG object otherwise.
    code, sha = run(["git", "rev-parse", "--short", f"{args.ref}^{{commit}}"], cwd=root)
    if code != 0:
        print(f"release-dry-run: unresolvable ref {args.ref!r}", file=sys.stderr)
        return 1
    sha = sha.strip()

    verdict: dict = {"ref": args.ref, "sha": sha, "mode": "fast" if args.fast else "full"}

    # Rung 1: workflow parseability at the ref (the v0.23.0 class).
    wf = parse_workflows_at_ref(args.ref)
    verdict["workflows"] = wf

    # Rung 2: the suite against the committed bytes, in isolation.
    tmp_parent = Path(tempfile.mkdtemp(prefix="dos-dryrun-"))
    wt = tmp_parent / "wt"
    suite: dict = {"ran": False, "venv": not args.no_venv}
    try:
        code, out = run(["git", "worktree", "add", "--detach", str(wt), args.ref], cwd=root)
        if code != 0:
            suite["error"] = f"worktree add failed: {out.strip()[:300]}"
        else:
            python = sys.executable
            if not args.no_venv:
                # Scratch venv with system site visible: pytest/PyYAML resolve
                # from the system site, while the venv's OWN editable install of
                # the worktree registers its `dos` finder ahead of the system
                # one — the worktree's bytes win the import.
                venv_dir = tmp_parent / "venv"
                vcode, vout = run([sys.executable, "-m", "venv",
                                   "--system-site-packages", str(venv_dir)])
                vpy = venv_dir / ("Scripts/python.exe" if sys.platform == "win32"
                                  else "bin/python")
                if vcode != 0 or not vpy.is_file():
                    suite["venv"] = False
                    suite["venv_note"] = f"venv creation failed - falling back to system env: {vout.strip()[:200]}"
                else:
                    icode, iout = run([str(vpy), "-m", "pip", "install", "-e",
                                       str(wt), "--no-deps", "-q"], timeout=180)
                    if icode != 0:
                        suite["venv"] = False
                        suite["venv_note"] = f"editable install failed - falling back to system env: {iout.strip()[-200:]}"
                    else:
                        python = str(vpy)
            if args.fast:
                targets = [t for t in FAST_SET if (wt / t).is_file()]
                missing = [t for t in FAST_SET if not (wt / t).is_file()]
                if missing:
                    suite["missing_fast_targets"] = missing
                if not targets:
                    suite["error"] = "no fast-set test files exist at ref"
                cmd = [python, "-m", "pytest", "-q", *targets]
                timeout = _FAST_TIMEOUT_S
            else:
                cmd = [python, "-m", "pytest", "-q"]
                timeout = _FULL_TIMEOUT_S
            if "error" not in suite:
                pcode, pout = run(cmd, cwd=wt, timeout=timeout)
                suite["ran"] = True
                suite["exit_code"] = pcode
                suite.update(parse_pytest_summary(pout))
                suite["tail"] = "\n".join(pout.splitlines()[-8:])
    finally:
        if not args.keep_worktree:
            run(["git", "worktree", "remove", "--force", str(wt)], cwd=root)
            run(["git", "worktree", "prune"], cwd=root)
            shutil.rmtree(tmp_parent, ignore_errors=True)
        else:
            print(f"release-dry-run: worktree kept at {wt}", file=sys.stderr)
    verdict["suite"] = suite

    ok = bool(wf.get("ok")) and suite.get("ran") and suite.get("exit_code") == 0
    verdict["ok"] = bool(ok)
    # The P3 trailer line — paste into the tag annotation if desired:
    #   git tag -a vX.Y.Z -m "vX.Y.Z" -m "<trailer>"
    verdict["trailer"] = (
        f"release-dry-run: {'pass' if ok else 'FAIL'} {sha} "
        f"mode={verdict['mode']} passed={suite.get('passed', 0)} "
        f"failed={suite.get('failed', 0) + suite.get('errors', 0)}"
    )

    if args.as_json:
        json.dump(verdict, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(verdict["trailer"])
        if not wf.get("ok"):
            for f, err in wf.get("files", {}).items():
                if err:
                    print(f"  workflow UNPARSEABLE: {f}: {err}")
        for name in suite.get("failed_names", []):
            print(f"  {name}")
        if not suite.get("ran") and suite.get("error"):
            print(f"  suite did not run: {suite['error']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

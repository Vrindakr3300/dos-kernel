#!/usr/bin/env python3
"""Standalone installer for the DOS kernel: venv + editable install + a
system-wide ``dos`` command.

DOS is the domain-free trust substrate (see CLAUDE.md). It is normally consumed
as a *library* — a host repo pins ``dos-kernel>=0.1.0`` and does an editable
install of this repository into its own venv (that path is wired into the host's
installer). This script is the OTHER surface: it puts the ``dos`` and
``dos-mcp`` console commands on your PATH so you can run ``dos verify`` /
``dos doctor`` / ``dos arbitrate`` from any directory, against any workspace via
``--workspace`` — the kernel never assumes it lives in the repo it serves.

It mirrors the sibling installers in adjacent repositories: a project-local
``.venv``, an editable install,
then the venv's entry-point scripts exposed on PATH (POSIX symlink into a bin
dir; Windows user-PATH registry edit). Paired ``--uninstall`` / ``--dry-run`` /
``--fresh`` / ``--fix-shadowing`` / ``--system`` / ``--user`` flags, same shape.

DOS-specific concern baked in: because DOS is often checked out in several
worktrees (``dos`` / ``dos-scv`` / ``dos-cerebras``), a stale entry-point shim
or editable ``.pth`` can silently point ``dos`` at the WRONG tree. So the
install/doctor/fix-shadowing paths all report the *resolved* dos source path +
version, not merely that the command exists — the resolved path is the honest
signal (see the extraction-contract notes).
"""

import argparse
import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
VENV_DIR = PROJECT_DIR / ".venv"
# The console_scripts declared in pyproject.toml [project.scripts]. dos-mcp only
# works once the [mcp] extra is installed, but the shim is always generated, so
# we expose both and let dos-mcp fail loudly with its install hint if [mcp] is
# absent.
ENTRY_POINTS = ("dos", "dos-mcp")
_PROFILE_MARKER = "# Added by dos installer"

_is_root = hasattr(os, "getuid") and os.getuid() == 0
_is_windows = sys.platform == "win32"

# Windows console (cp1252) chokes on the em-dashes / arrows this installer
# prints. Force utf-8 with replacement so a print never aborts the install.
if _is_windows:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


# ---------------------------------------------------------------------------
# venv path helpers
# ---------------------------------------------------------------------------

def _venv_python():
    """Path to the Python binary inside the venv."""
    if _is_windows:
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _venv_scripts_dir():
    """The venv directory that holds the generated console-script shims."""
    return VENV_DIR / ("Scripts" if _is_windows else "bin")


def _venv_entry(name):
    """Path to an entry-point script inside the venv (``.exe`` on Windows)."""
    if _is_windows:
        return _venv_scripts_dir() / f"{name}.exe"
    return _venv_scripts_dir() / name


def _is_wsl():
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except (OSError, FileNotFoundError):
        return False


def _on_windows_fs(path):
    return str(path).startswith("/mnt/")


_WSL_VENV_DIR = Path.home() / ".local" / "share" / "dos" / "venv"


def _run(cmd, *, cwd=None, check=True, capture=False):
    """Run a subprocess, streaming output unless capture=True."""
    if capture:
        return subprocess.run(cmd, cwd=cwd, check=check,
                              capture_output=True, text=True)
    return subprocess.run(cmd, cwd=cwd, check=check)


def _is_child_of(child: Path, parent: Path) -> bool:
    """True if *child* is equal to or nested under *parent* (resolved)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _resolved_dos(venv_python: Path):
    """Return (ok, detail) where detail is '<resolved-src-dir>  v<version>'.

    The resolved real path is the load-bearing signal: an editable ``.pth`` is a
    static path pointer and can aim at a different dos worktree than this one.
    """
    if not venv_python.exists():
        return False, "venv python missing"
    r = subprocess.run(
        [str(venv_python), "-c",
         "import dos, os; print(os.path.realpath(os.path.dirname("
         "dos.__file__)) + '  v' + getattr(dos, '__version__', '?'))"],
        capture_output=True, text=True,
    )
    return r.returncode == 0, (r.stdout.strip() or r.stderr.strip()
                               or "ModuleNotFoundError: dos")


# ---------------------------------------------------------------------------
# venv creation (stdlib venv → --without-pip+ensurepip → virtualenv)
# ---------------------------------------------------------------------------

def _bootstrap_pip(venv_python):
    """Install pip into a venv created with --without-pip."""
    r = subprocess.run([str(venv_python), "-m", "ensurepip", "--default-pip"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print("  Bootstrapped pip via ensurepip")
        return
    get_pip = VENV_DIR / "get-pip.py"
    print("  ensurepip not available, downloading get-pip.py...")
    try:
        import urllib.request
        urllib.request.urlretrieve(
            "https://bootstrap.pypa.io/get-pip.py", str(get_pip))
    except Exception as exc:  # noqa: BLE001 — actionable, then bail
        print(f"Error: could not download get-pip.py: {exc}", file=sys.stderr)
        sys.exit(1)
    _run([str(venv_python), str(get_pip)])
    get_pip.unlink(missing_ok=True)
    print("  Bootstrapped pip via get-pip.py")


def _try_venv():
    r = subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        stderr = r.stderr.strip()
        print(f"  python -m venv failed: "
              f"{stderr.splitlines()[-1] if stderr else 'unknown error'}")
        return False
    venv_python = _venv_python()
    pip_check = subprocess.run([str(venv_python), "-m", "pip", "--version"],
                               capture_output=True, text=True)
    if pip_check.returncode != 0:
        print("  venv created but pip missing, bootstrapping...")
        _bootstrap_pip(venv_python)
    return True


def _try_venv_without_pip():
    r = subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(VENV_DIR)],
        capture_output=True, text=True)
    if r.returncode != 0:
        return False
    print("  Created venv (--without-pip), bootstrapping pip...")
    _bootstrap_pip(_venv_python())
    return True


def _try_virtualenv():
    for cmd in ([sys.executable, "-m", "virtualenv", str(VENV_DIR)],
                ["virtualenv", str(VENV_DIR)]):
        try:
            if subprocess.run(cmd, capture_output=True,
                              text=True).returncode == 0:
                return True
        except FileNotFoundError:
            continue
    print("  virtualenv not available")
    return False


def _create_venv():
    print("Creating venv...")
    for label, fn in (("python -m venv", _try_venv),
                      ("python -m venv --without-pip", _try_venv_without_pip),
                      ("virtualenv", _try_virtualenv)):
        print(f"Trying {label}...")
        if fn():
            return
        if VENV_DIR.exists():
            shutil.rmtree(VENV_DIR, ignore_errors=True)
    print("\nError: could not create a virtual environment.", file=sys.stderr)
    if _is_windows:
        print("  Ensure a full CPython is installed (python.org), not the "
              "Microsoft Store stub.", file=sys.stderr)
    else:
        print("  Fix: sudo apt install python3-venv   (then retry)",
              file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# PATH wiring — POSIX symlink / Windows registry
# ---------------------------------------------------------------------------

def _create_symlinks(bin_dir: Path):
    """Symlink the venv's entry-point scripts into *bin_dir* (POSIX)."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for name in ENTRY_POINTS:
        source = _venv_entry(name)
        target = bin_dir / name
        if not source.exists():
            print(f"Warning: entry point {source} not found, "
                  f"skipping symlink for '{name}'")
            continue
        if target.is_symlink():
            if target.resolve() == source.resolve():
                print(f"Symlink already correct: {target} -> {source}")
                made.append(name)
                continue
            print(f"Updating symlink: {target} (was -> {target.resolve()})")
            target.unlink()
        elif target.exists():
            print(f"Warning: {target} exists and is not a symlink — "
                  f"skipping (remove it manually to fix)")
            continue
        os.symlink(source.resolve(), target)
        print(f"Created symlink: {target} -> {source}")
        made.append(name)
    return made


def _add_to_win_path(scripts_dir: Path):
    """Prepend the venv Scripts dir to the Windows user PATH via registry."""
    try:
        import winreg
    except ImportError:
        print("Warning: cannot modify Windows PATH (winreg unavailable)")
        return
    scripts_str = str(scripts_dir)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                user_path, reg_type = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                user_path, reg_type = "", winreg.REG_EXPAND_SZ
            if scripts_str.lower() in user_path.lower():
                print(f"  PATH already contains {scripts_str}")
                return
            new_path = f"{scripts_str};{user_path}" if user_path else scripts_str
            winreg.SetValueEx(key, "Path", 0, reg_type, new_path)
            print(f"Added {scripts_str} to user PATH")
            print("  Changes take effect in NEW terminal windows.")
    except OSError as exc:
        print(f"Warning: could not update PATH: {exc}", file=sys.stderr)
        print(f"  Manual fix: add {scripts_str} to your PATH", file=sys.stderr)


def _on_path(bin_dir: Path) -> bool:
    """True if *bin_dir* is already a member of the current PATH."""
    target = bin_dir.resolve()
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if d and Path(d).resolve() == target:
            return True
    return False


def _ensure_path_in_profile(bin_dir: Path):
    """Append a PATH export to the user's shell profiles (POSIX) so a *fresh*
    login shell finds `dos`.

    Symlinking into ``~/.local/bin`` is only half the job: on many distros that
    dir is not on PATH in a login shell, so a new terminal can't find `dos`
    even though the symlink is correct. We append one marked block
    (``_PROFILE_MARKER`` + an ``export PATH=…``) to every profile file that
    exists, so the dir is reachable however the user opens a shell; uninstall
    removes exactly that block (`_remove_profile_block`). No-op if the dir is
    already on PATH (e.g. a distro that puts ``~/.local/bin`` on PATH for you).
    """
    if _on_path(bin_dir):
        print(f"  {bin_dir} already on PATH — no profile edit needed.")
        return
    bin_resolved = str(bin_dir.resolve())
    export_line = f'export PATH="{bin_resolved}:$PATH"'
    block = f"\n{_PROFILE_MARKER}\n{export_line}\n"
    home = Path.home()
    # .profile is the POSIX login-shell default; .bash_profile overrides it on
    # bash login shells when present; .bashrc covers interactive non-login
    # shells. Write to every one that exists so PATH is set however the shell
    # is opened; if none exist, create ~/.profile.
    candidates = [home / ".profile", home / ".bash_profile", home / ".bashrc"]
    updated = []
    for rc in candidates:
        if not rc.exists():
            continue
        try:
            contents = rc.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"  Warning: cannot read {rc} ({exc})")
            continue
        if _PROFILE_MARKER in contents or bin_resolved in contents:
            print(f"  PATH already configured in {rc}")
            continue
        with open(rc, "a", encoding="utf-8") as f:
            f.write(block)
        updated.append(rc)
    if not updated and not any(rc.exists() for rc in candidates):
        rc = home / ".profile"
        with open(rc, "a", encoding="utf-8") as f:
            f.write(block)
        updated.append(rc)
    if updated:
        names = ", ".join(str(p) for p in updated)
        print(f"Added {bin_resolved} to PATH in {names}")
        print("  Changes take effect on next login / in a new shell "
              "(or: source the profile).")


def _wire_path(bin_dir: Path):
    """Expose `dos`/`dos-mcp` on PATH using the platform's idiom."""
    if _is_windows:
        _add_to_win_path(_venv_scripts_dir())
    else:
        _create_symlinks(bin_dir)
        # Symlinking the shims is not enough if bin_dir isn't on PATH — wire it
        # into the shell profiles so a fresh login shell finds `dos`.
        _ensure_path_in_profile(bin_dir)


# ---------------------------------------------------------------------------
# --fix-shadowing — remove stale dos shims from OTHER PATH dirs
# ---------------------------------------------------------------------------

def _remove_shadowing_entries(bin_dir: Path, *, dry_run=False, force=False):
    """Find/remove stale `dos`/`dos-mcp` shims elsewhere on PATH.

    The multi-worktree hazard: a `dos.exe`/`dos` from a previous install in
    ``dos-scv`` or ``dos-cerebras`` earlier on PATH will run that tree's code
    instead of this one. We only touch shims we can prove are ours (a symlink
    into this project/venv, or a script whose shebang points at this venv);
    unrelated same-named files are left with a warning.
    """
    # The dirs that legitimately hold OUR shim — never flag these.
    own_dirs = {_venv_scripts_dir().resolve(), bin_dir.resolve()}
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    found, removed = [], []

    for d in path_dirs:
        if not d:
            continue
        dp = Path(d).resolve()
        if dp in own_dirs:
            continue
        for name in ENTRY_POINTS:
            for cand in ({dp / name, dp / f"{name}.exe"}
                         if _is_windows else {dp / name}):
                if not cand.exists() and not cand.is_symlink():
                    continue

                # Case 1: symlink into this project/venv (POSIX).
                if cand.is_symlink():
                    tgt = cand.resolve()
                    if _is_child_of(tgt, PROJECT_DIR) or _is_child_of(tgt, VENV_DIR):
                        desc = f"symlink: {cand} -> {tgt}"
                        found.append((cand, desc))
                        if force and not dry_run and cand.is_symlink():
                            cand.unlink()
                            removed.append(str(cand))
                            print(f"Removed stale {desc}")
                    continue

                # Case 2: a generated shim referencing our venv. On POSIX the
                # shebang names the interpreter; Windows .exe shims embed the
                # venv path, so we sniff the bytes for our venv dir.
                try:
                    st = cand.lstat()
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                ours = False
                try:
                    if _is_windows:
                        blob = cand.read_bytes()
                        ours = str(VENV_DIR).encode("utf-8").lower() in blob.lower()
                    else:
                        with open(cand, "rb") as f:
                            first = f.readline(512)
                        if first.startswith(b"#!"):
                            interp = first[2:].decode("utf-8", "replace").strip()
                            interp = interp.split()[0] if interp else ""
                            ours = bool(interp) and (
                                _is_child_of(Path(interp), VENV_DIR)
                                or _is_child_of(Path(interp), PROJECT_DIR))
                except (OSError, PermissionError) as exc:
                    print(f"  Warning: cannot read {cand} ({exc})")
                    continue
                if ours:
                    desc = f"script: {cand}"
                    found.append((cand, desc))
                    if force and not dry_run:
                        cand.unlink()
                        removed.append(str(cand))
                        print(f"Removed stale {desc}")
                    continue

                # Not provably generated by our project venv. A console-script
                # shim lives next to the venv that created it, so its on-disk
                # location is the tell: if it sits inside a SIBLING dos*
                # worktree, it's a cross-tree shadow (the real hazard — it would
                # run dos-scv/dos-cerebras code instead of this tree). Otherwise
                # it's an unrelated `dos` we leave alone with a soft note.
                shadow_tree = next(
                    (sib for sib in PROJECT_DIR.parent.glob("dos*")
                     if sib != PROJECT_DIR and _is_child_of(cand, sib)), None)
                if shadow_tree is not None:
                    print(f"Warning: '{name}' at {cand} belongs to another DOS "
                          f"worktree ({shadow_tree.name}) and is earlier on "
                          f"PATH — it will shadow this install. Remove it or "
                          f"reinstall from the worktree you want.")
                else:
                    print(f"Note: an unrelated '{name}' is on PATH at {cand} "
                          f"(not from a DOS worktree — left alone).")

    if dry_run and found:
        print(f"Would remove {len(found)} stale dos shim(s):")
        for _p, desc in found:
            print(f"  {desc}")
        print("Run --fix-shadowing (without --dry-run) to remove them.")
    elif removed:
        print(f"Cleaned {len(removed)} stale dos shim(s) from PATH.")
        if not _is_windows:
            print("  Tip: run 'hash -r' in open shells to clear cached lookups.")
    elif found and not force:
        print(f"Found {len(found)} stale dos shim(s) on PATH that may shadow "
              f"this install:")
        for _p, desc in found:
            print(f"  {desc}")
        print("Run 'python install.py --fix-shadowing' to remove them.")
    elif not found:
        print("No stale dos shims found on PATH.")


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

def _remove_profile_block(rc: Path, *, dry_run: bool) -> bool:
    """Remove the installer's marked PATH block from a shell profile.

    Strips the ``_PROFILE_MARKER`` line, the ``export PATH=…`` line that
    follows it, and the single preceding blank line `_ensure_path_in_profile`
    wrote — leaving any hand-edited content untouched. Returns True if a block
    was found (and removed unless *dry_run*). The inverse of
    `_ensure_path_in_profile`; the marker is the surgical handle so uninstall
    never has to guess which lines were ours.
    """
    try:
        lines = rc.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except OSError:
        return False
    out, found, i = [], False, 0
    while i < len(lines):
        if lines[i].strip() == _PROFILE_MARKER:
            found = True
            # Drop a single preceding blank line we emitted (the leading "\n").
            if out and out[-1].strip() == "":
                out.pop()
            # Skip the marker line and the export line directly after it.
            i += 1
            if i < len(lines) and lines[i].lstrip().startswith("export PATH"):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    if not found:
        return False
    if dry_run:
        print(f"  Would remove the dos PATH block from {rc}")
        return True
    tmp = rc.with_suffix(rc.suffix + ".tmp")
    try:
        tmp.write_text("".join(out), encoding="utf-8")
        os.replace(tmp, rc)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"  Removed the dos PATH block from {rc}")
    return True


def _discover_profile_blocks() -> list[Path]:
    """Profile files that carry our `_PROFILE_MARKER` block (POSIX)."""
    home = Path.home()
    hit = []
    for rc in (home / ".profile", home / ".bash_profile", home / ".bashrc"):
        try:
            if rc.exists() and _PROFILE_MARKER in rc.read_text(
                    encoding="utf-8", errors="replace"):
                hit.append(rc)
        except OSError:
            continue
    return hit


def _discover_symlinks(args):
    bin_dirs = set()
    if args.bin_dir:
        bin_dirs.add(Path(args.bin_dir).resolve())
    bin_dirs.add((Path.home() / ".local" / "bin").resolve())
    bin_dirs.add(Path("/usr/local/bin").resolve())
    links = []
    for bd in bin_dirs:
        for name in ENTRY_POINTS:
            link = bd / name
            if link.is_symlink():
                try:
                    link.resolve().relative_to(PROJECT_DIR)
                    links.append(link)
                except ValueError:
                    pass
    return links


def _uninstall(args):
    dry_run = args.dry_run
    print(f"Project:  {PROJECT_DIR}")
    print(f"Venv:     {VENV_DIR}")
    if dry_run:
        print("Mode:     dry-run (no changes)")
    print()

    links = _discover_symlinks(args)
    profiles = [] if _is_windows else _discover_profile_blocks()
    venv_present = (VENV_DIR / "pyvenv.cfg").exists()
    win_note = _is_windows and venv_present

    if not links and not venv_present and not profiles:
        print("Nothing to uninstall.")
        return

    for link in links:
        print(f"  Symlink: {link} -> {link.resolve()}")
    for rc in profiles:
        print(f"  Profile: {rc} (has the dos PATH block)")
    if venv_present:
        print(f"  Venv:    {VENV_DIR}")
    if win_note:
        print(f"  Windows PATH: remove {_venv_scripts_dir()} from your user "
              f"PATH manually (registry edits are not auto-reverted).")
    print()

    if dry_run:
        for rc in profiles:
            _remove_profile_block(rc, dry_run=True)
        print("No changes made (--dry-run).")
        return

    for link in links:
        if link.is_symlink():
            link.unlink()
            print(f"Removed symlink: {link}")
    for rc in profiles:
        _remove_profile_block(rc, dry_run=False)
    if venv_present:
        try:
            shutil.rmtree(VENV_DIR)
            print(f"Removed venv: {VENV_DIR}")
        except PermissionError:
            print(f"Error: cannot remove {VENV_DIR} (permission denied).",
                  file=sys.stderr)
            if not _is_windows:
                print(f"  Fix: sudo rm -rf {shlex.quote(str(VENV_DIR))}",
                      file=sys.stderr)
    print(f"\nTo remove the source too: "
          f"{'rmdir /s /q' if _is_windows else 'rm -rf'} "
          f"{shlex.quote(str(PROJECT_DIR))}")


# ---------------------------------------------------------------------------
# doctor — read-only health check (resolved-path is the honest signal)
# ---------------------------------------------------------------------------

def _doctor(args):
    venv_python = _venv_python()
    print("install.py doctor — read-only health check")
    print(f"  project:  {PROJECT_DIR}")
    print(f"  venv:     {VENV_DIR} "
          f"({'present' if VENV_DIR.exists() else 'missing'})")
    print(f"  venv py:  {venv_python} "
          f"({'present' if venv_python.exists() else 'missing'})")

    ok, detail = _resolved_dos(venv_python)
    status = "OK " if ok else "FAIL"
    print(f"  [{status}] import dos (venv) -> {detail}")
    if ok:
        resolved = detail.split("  v")[0]
        if not _is_child_of(Path(resolved), PROJECT_DIR):
            print(f"  WARNING: the venv's `dos` resolves OUTSIDE this project "
                  f"({resolved}). An editable .pth is pointing at another "
                  f"worktree. Re-run: python install.py install --fresh",
                  file=sys.stderr)

    # The system-wide `dos` the shell actually finds (may differ from the venv).
    sys_dos = shutil.which("dos")
    if sys_dos:
        r = subprocess.run([sys_dos, "doctor", "--workspace", "."],
                           capture_output=True, text=True)
        first = (r.stdout.strip().splitlines() or [""])[0]
        print(f"  [{'OK ' if r.returncode == 0 else 'FAIL'}] `dos` on PATH "
              f"({sys_dos}) -> {first}")
    else:
        print("  [WARN] no `dos` command on PATH "
              "(run: python install.py install)")

    if venv_python.exists():
        _remove_shadowing_entries(
            args.bin_dir or (Path.home() / ".local" / "bin"),
            dry_run=True, force=False)

    return 0 if ok else 1


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

def _pip_install_editable(venv_python, extras):
    spec = "." if not extras else f".[{extras}]"
    print(f"Installing dos{('[' + extras + ']') if extras else ''} "
          f"(editable)...")
    # --force-reinstall --no-deps for the dos package itself guards the
    # stale-.pth trap: pip otherwise sees version 0.2.0 already installed and
    # no-ops the .pth rewrite, leaving `dos` pointed at an old worktree. We do a
    # normal install first (resolves deps), then force-rewrite the editable link.
    _run([str(venv_python), "-m", "pip", "install", "-e", spec],
         cwd=str(PROJECT_DIR))
    _run([str(venv_python), "-m", "pip", "install", "-e", ".",
          "--force-reinstall", "--no-deps"], cwd=str(PROJECT_DIR))


def _install(args):
    global VENV_DIR

    if args.venv_dir:
        VENV_DIR = Path(args.venv_dir).resolve()
    elif _is_wsl() and _on_windows_fs(VENV_DIR):
        VENV_DIR = _WSL_VENV_DIR
        print("WSL detected — relocating venv to native Linux filesystem")
        print(f"  Venv location: {VENV_DIR}\n")

    print(f"Python:   {sys.executable} "
          f"({'.'.join(map(str, sys.version_info[:3]))})")
    print(f"Platform: {sys.platform}")
    print(f"Project:  {PROJECT_DIR}")
    print(f"Venv:     {VENV_DIR}")
    print(f"Bin dir:  {args.bin_dir}")

    if sys.version_info < (3, 11):
        print(f"Error: Python >= 3.11 required, got {sys.version}",
              file=sys.stderr)
        return 1

    if args.fresh and VENV_DIR.exists():
        print(f"\nRemoving existing venv: {VENV_DIR}")
        try:
            shutil.rmtree(VENV_DIR)
        except PermissionError:
            print(f"Error: cannot remove {VENV_DIR} (permission denied).",
                  file=sys.stderr)
            return 1

    if VENV_DIR.exists():
        print(f"\nVenv already exists: {VENV_DIR}")
    else:
        print()
        _create_venv()

    venv_python = _venv_python()
    if not venv_python.exists():
        print(f"Error: venv python not found at {venv_python}",
              file=sys.stderr)
        return 1

    print("\nUpgrading pip / setuptools / wheel...")
    _run([str(venv_python), "-m", "pip", "install", "--upgrade",
          "pip", "setuptools>=75", "wheel"])

    print()
    _pip_install_editable(venv_python, args.extras)

    # Confirm the editable link resolves into THIS project (the honest check).
    ok, detail = _resolved_dos(venv_python)
    if not ok:
        print(f"Error: `import dos` failed after install: {detail}",
              file=sys.stderr)
        return 1
    resolved = detail.split("  v")[0]
    print(f"\nVerified: dos resolves to {detail}")
    if not _is_child_of(Path(resolved), PROJECT_DIR):
        print(f"WARNING: dos resolved OUTSIDE this project ({resolved}); an "
              f"editable .pth from another worktree won. Try --fresh.",
              file=sys.stderr)

    if args.no_symlink:
        print("\nSkipping PATH setup (--no-symlink).")
    else:
        print()
        _wire_path(args.bin_dir)
        # Warn (don't auto-remove) about stale shims from other worktrees.
        _remove_shadowing_entries(args.bin_dir, dry_run=False, force=False)

    print("\n--- Installation complete ---")
    print(f"  venv: {VENV_DIR}")
    if _is_windows and not args.no_symlink:
        print(f"  dos     -> {_venv_entry('dos')}")
        print(f"  dos-mcp -> {_venv_entry('dos-mcp')}")
        print("\n  Open a NEW terminal, then: dos doctor --workspace .")
    elif not args.no_symlink:
        for name in ENTRY_POINTS:
            print(f"  {name:8s} -> {args.bin_dir / name}")
        print("\n  Run: dos doctor --workspace .")
    else:
        print(f"\n  Activate the venv: "
              f"{VENV_DIR}\\Scripts\\activate" if _is_windows
              else f"\n  source {VENV_DIR}/bin/activate")
    print("\n  dos is a library too — host repos consume it via an editable "
          "install of this repository (see CLAUDE.md).")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_mode(args):
    """Pick install mode + default bin-dir (POSIX). Windows ignores mode and
    uses the user-PATH registry."""
    if args.system:
        system_wide = True
    elif args.user:
        system_wide = False
    else:
        system_wide = _is_root
    if args.bin_dir is None:
        args.bin_dir = (Path("/usr/local/bin") if system_wide
                        else Path.home() / ".local" / "bin")
    else:
        args.bin_dir = Path(args.bin_dir).resolve()
    return system_wide


def main():
    parser = argparse.ArgumentParser(
        description="Install the DOS kernel: venv + editable install + a "
                    "system-wide `dos` command.")
    sub = parser.add_subparsers(dest="cmd")

    def _add_common(p):
        p.add_argument("--venv-dir", default=None,
                       help="Custom venv location (default: .venv in repo)")
        p.add_argument("--bin-dir", default=None,
                       help="Directory for symlinks on POSIX "
                            "(default: auto by mode)")
        mode = p.add_mutually_exclusive_group()
        mode.add_argument("--system", action="store_true",
                          help="System-wide (/usr/local/bin; POSIX, needs root)")
        mode.add_argument("--user", action="store_true",
                          help="Per-user (~/.local/bin; POSIX)")

    p_install = sub.add_parser("install", help="Create venv + editable "
                               "install + put `dos` on PATH (default)")
    _add_common(p_install)
    p_install.add_argument("--fresh", action="store_true",
                           help="Remove existing .venv and recreate")
    p_install.add_argument("--no-symlink", action="store_true",
                           help="Skip PATH setup (confine to the venv)")
    p_install.add_argument("--extras", default="",
                           help="Extras for pip install, e.g. 'mcp' or "
                                "'dev,mcp' (default: none — core kernel only)")

    p_doctor = sub.add_parser("doctor", help="Read-only health check "
                              "(reports the RESOLVED dos path + version)")
    _add_common(p_doctor)

    p_uninstall = sub.add_parser("uninstall",
                                 help="Remove symlinks + venv")
    _add_common(p_uninstall)
    p_uninstall.add_argument("--dry-run", action="store_true",
                             help="Preview what uninstall would remove")

    p_fix = sub.add_parser("fix-shadowing",
                           help="Remove stale dos shims from other PATH dirs "
                                "(the multi-worktree trap)")
    _add_common(p_fix)
    p_fix.add_argument("--dry-run", action="store_true",
                       help="Preview what would be removed")

    args = parser.parse_args()
    if args.cmd is None:
        args.cmd = "install"
        # Re-parse defaults for the implicit install subcommand.
        args = p_install.parse_args(sys.argv[1:])
        args.cmd = "install"

    _resolve_mode(args)

    if args.cmd == "install":
        if not _is_windows and args.system and not _is_root:
            print("Error: --system needs root (run with sudo) or use --user.",
                  file=sys.stderr)
            return 1
        return _install(args)
    if args.cmd == "doctor":
        return _doctor(args)
    if args.cmd == "uninstall":
        _uninstall(args)
        return 0
    if args.cmd == "fix-shadowing":
        _remove_shadowing_entries(args.bin_dir, dry_run=args.dry_run,
                                  force=not args.dry_run)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

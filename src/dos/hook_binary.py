"""Locate the native `dos-hook` fast-path binary bundled in the installed package (docs/286).

The per-tool-call hook hot path (`dos hook pretool`/`posttool`) pays ~0.3-0.8 s of
Python interpreter cold-start on EVERY tool call; a static Go binary serves the same
decision in ~10 ms (docs/125/270, the 16-43x win). That binary ships two ways:

  * **The Claude Code plugin** carries it in its git tree (`claude-plugin/bin/`,
    docs/125 GHF4) and a shell launcher dispatches to it.
  * **A `pip install dos-kernel` per-platform wheel** (docs/286) bundles exactly the
    one binary for the installing machine's OS/arch into the package, at
    `dos/_bin/dos-hook[.exe]`. THIS module is the in-package locator for that copy —
    the wheel analogue of the plugin's POSIX `bin/dos-hook` launcher, consulted by the
    CLI hook verbs so a pip user's `dos hook pretool` transparently routes through the
    native binary when one is present.

This is PURE stdlib and adds NO runtime dependency (the binary is package DATA, the
same one-way arrow as the skill pack). It only RESOLVES a path + checks it is an
executable file — it launches nothing; the CLI is the call site that execs it.

**The fallback discipline (docs/100) is absolute.** On a pure-Python install (the
sdist, or any arch with no matching wheel, or a clean dev checkout where the binary is
gitignored), `native_hook_binary()` returns None and the caller runs the in-process
Python decider — un-accelerated, never broken. No machine is ever BLOCKED by a missing
accelerator; the binary is only ever a speed-up.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

# The native binary's DELEGATE sentinel (docs/125): it exits 3 for a verb/moment it
# does not own natively, signalling "let Python decide." A clean native decision is
# exit 0 (it already emitted any dialect to stdout). Anything else is abnormal and we
# fall through to Python too (fail-safe).
DELEGATE_EXIT = 3

# The package-data dir the per-platform wheel drops the binary into. Resolved against
# THIS module's location (the installed package), NOT a workspace root — the binary is
# part of the package, wherever pip put it.
_BIN_DIR = Path(__file__).resolve().parent / "_bin"

# The verbs the native binary serves on the per-tool-call hot path. `stop` fires once
# per TURN (negligible cold-start) and the oracle port it needs is heavier (docs/125
# §8.2), so it stays Python on the pip path; the binary itself DELEGATEs it anyway.
NATIVE_HOOK_VERBS = frozenset({"pretool", "posttool"})

# The env opt-out, matching the plugin path's flag. Unset/anything-but-"0" => native
# allowed; "0" => force the Python verb (the differential-oracle / debug escape hatch).
_DISABLE_ENV = "DOS_HOOK_NATIVE"


def _host_goos_goarch() -> tuple[str, str]:
    """This interpreter's (GOOS, GOARCH) tokens — the same mapping `build_hook_binary.py`
    and the POSIX launcher use, so the name we look up matches the name the build emits."""
    goos = {"windows": "windows", "darwin": "darwin", "linux": "linux"}.get(
        platform.system().lower(), platform.system().lower()
    )
    m = platform.machine().lower()
    goarch = {
        "x86_64": "amd64", "amd64": "amd64",
        "arm64": "arm64", "aarch64": "arm64",
    }.get(m, m)
    return goos, goarch


def bundled_binary_name() -> str:
    """The plain in-package binary name for this platform: `dos-hook` or `dos-hook.exe`.

    The per-platform wheel ships ONE binary per wheel, so it is the un-suffixed
    `dos-hook[.exe]` (NOT the `dos-hook-<os>-<arch>` matrix names the PLUGIN bundle
    uses — the plugin carries all arches in one dir and disambiguates by name; a wheel
    carries only its own arch, so no disambiguation is needed)."""
    goos, _ = _host_goos_goarch()
    return "dos-hook.exe" if goos == "windows" else "dos-hook"


def native_hook_enabled() -> bool:
    """True unless `DOS_HOOK_NATIVE=0` forces the Python verb (the opt-out)."""
    return os.environ.get(_DISABLE_ENV, "").strip() != "0"


def native_hook_binary() -> Path | None:
    """The bundled native dos-hook for THIS platform, or None if there isn't one.

    Returns the path iff a matching, executable regular file is present at
    `dos/_bin/dos-hook[.exe]` in the installed package; None otherwise (a pure-Python /
    sdist install, an off-matrix arch, a clean dev checkout, or the `DOS_HOOK_NATIVE=0`
    opt-out). The caller falls back to the in-process Python hook decider when None.

    Never raises: any probe error (an exotic platform, a permissions surprise) degrades
    to None, so a packaging oddity can only LOSE the accelerator, never break the hook.
    """
    if not native_hook_enabled():
        return None
    try:
        candidate = _BIN_DIR / bundled_binary_name()
        if not candidate.is_file():
            return None
        # On POSIX the file must be executable to exec it; on Windows the bit is
        # meaningless (an .exe is run by extension), so we don't gate on it there.
        if os.name != "nt" and not os.access(candidate, os.X_OK):
            return None
        return candidate
    except OSError:
        return None


def hook_argv_from_args(args: object) -> list[str]:
    """Rebuild the `dos hook <verb>` flag list from the parsed argparse namespace.

    The native binary's CLI mirrors the Python verb's, so we re-emit the same flags it
    understands: `--workspace`, `--dialect`, `--handler` (pretool), `--session-id`
    (posttool), `--debug`. A flag absent / left at its argparse default is omitted (the
    binary applies the same default). Unknown/None values are skipped, so a namespace
    missing a flag (e.g. posttool has no --handler) simply doesn't emit it.
    """
    # The default-dialect name is imported, never spelled here: the vendor-blindness
    # litmus allows the literal in hook_dialect.py ONLY (the one sanctioned default),
    # and a kernel module must not branch on a vendor literal of its own.
    from dos.hook_dialect import DEFAULT_DIALECT

    out: list[str] = []
    workspace = getattr(args, "workspace", None)
    if workspace:
        out += ["--workspace", str(workspace)]
    dialect = getattr(args, "dialect", None)
    # Only forward a NON-default dialect — the binary's default matches the kernel's,
    # so omitting it keeps the argv minimal and the native default authoritative.
    if dialect and dialect != DEFAULT_DIALECT:
        out += ["--dialect", str(dialect)]
    handler = getattr(args, "handler", None)
    if handler and handler != "observe":
        out += ["--handler", str(handler)]
    session_id = getattr(args, "session_id", None)
    if session_id:
        out += ["--session-id", str(session_id)]
    if getattr(args, "debug", False):
        out += ["--debug"]
    return out


def try_native_hook(verb: str, argv: list[str]) -> int | None:
    """Run the bundled native binary for `verb` if one is present; else return None.

    The "consult and fall back" pre-amble the CLI hook verbs call BEFORE reading stdin:

      * Returns an `int` exit code when the native binary OWNED the decision (it has
        already emitted any host dialect to this process's stdout and exited 0) — the
        CLI returns that code directly, the native fast path.
      * Returns `None` when there is no usable native path — no bundled binary for this
        platform, the `DOS_HOOK_NATIVE=0` opt-out, a verb the binary does not serve
        natively (`stop`/`marker`), a DELEGATE (exit 3) sentinel, or ANY launch error.
        The CLI then runs its in-process Python decider (the docs/100 fallback).

    `verb` is the hook verb (`pretool`/`posttool`); `argv` is the flags AFTER the verb
    (e.g. `["--workspace", "."]`) — the native binary's CLI mirrors `dos hook <verb>
    <flags>`. stdin is inherited so the binary reads the SAME event the Python body
    would; stdout is inherited so its dialect reaches the host unbuffered through us.

    Never raises: a missing binary, a launch failure, or a crash all degrade to None
    (run Python), so the accelerator can only be SKIPPED, never break the hook.
    """
    if verb not in NATIVE_HOOK_VERBS:
        return None
    binary = native_hook_binary()
    if binary is None:
        return None
    try:
        # Inherit stdin (the event) + stdout (the dialect) + stderr (--debug) so the
        # native binary's I/O is byte-identical to the Python body's, and we add no
        # buffering between it and the host runtime.
        proc = subprocess.run(
            [str(binary), verb, *argv],
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    except OSError:
        # The binary vanished between the is_file() probe and exec, or the OS refused
        # to launch it — fall through to Python.
        return None
    if proc.returncode == DELEGATE_EXIT:
        return None  # the binary punted this one to Python
    if proc.returncode != 0:
        # An abnormal exit (a panic the binary's own recover() did not catch, a signal):
        # do NOT trust a partial native decision — but stdin is now consumed, so the
        # Python body can't re-decide. The hook fail-safe is exit 0 / emit-nothing, and
        # the binary will have emitted nothing on a crash, so 0 is the safe report.
        return 0
    return 0  # the native binary owned it cleanly

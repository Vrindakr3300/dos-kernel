"""proc-delta — the OS process-liveness rung, one shared boundary reader.

docs/95 — the proc-liveness rung the liveness verdict was missing.

`dos.liveness` decides ADVANCING / SPINNING / STALLED from a forward-delta (git
commits, lane-journal events) and a heartbeat age. But the alive/dead half of
that verdict — SPINNING ("alive, narrating, not moving") vs STALLED ("dead/hung")
— rests ENTIRELY on a caller-supplied heartbeat. A heartbeat is forgeable: a
crashed agent whose last act wrote a fresh `heartbeat_at` (or whose `.lease-
liveness` mtime a wrapper keeps touching) reads SPINNING when the process is gone.
That is the exact gap docs/95 §3 names — the verdict trusts a self-reported beat
where it could instead ask the OS process table, which the dead process cannot
keep fresh.

This module is that OS rung: given a pid (and the host it was recorded on), it
asks the kernel "is this process actually alive right now?" — the one liveness
signal an agent cannot fabricate after it dies. Like `git_delta`/`journal_delta`
it is **boundary I/O, not a pure verdict**: the probe happens HERE, at the caller
boundary, and the already-resolved `alive: Optional[bool]` is handed to the pure
`liveness.classify` as one more piece of frozen evidence (the arbiter discipline —
no I/O inside the verdict).

The design rules (docs/95), each load-bearing:

  * **Never fabricate `True`.** Every failure mode — a foreign host, no pid, an
    unsupported platform, a PermissionError, ANY OSError — degrades to
    `alive=None` ("could not tell"), NEVER to `alive=True`. A None corroborates
    nothing and demotes nothing; only a *confident* `False` (the process is
    provably gone) is allowed to flip a verdict. This is the fail-safe direction:
    an unforgeable signal that can only ever make the verdict MORE skeptical, the
    same shape as the overlap floor and the judge's fail-to-abstain.
  * **Foreign-host blindness.** A pid is only meaningful on the host that minted
    it; pid 4242 on `boxA` says nothing about `boxB`. If the recorded `host_id`
    is not `this_host`, the probe returns `alive=None` — it refuses to read its
    own process table as if it were the other host's (the cross-host false-True
    docs/95 explicitly forbids).
  * **stdlib + ctypes only.** No psutil, no new dependency — the kernel's import
    set stays PyYAML-only (the CLAUDE.md litmus). POSIX uses `os.kill(pid, 0)`;
    win32 uses `OpenProcess` via `ctypes` and distinguishes alive from exited.
  * **Demote-only at the consumer.** This module just reports; `liveness.classify`
    is where a `False` flips SPINNING→STALLED and a True/None never promotes
    dead→alive. The kernel that doesn't believe the agents also doesn't believe a
    bare "process looks up" as proof of *progress* — only as proof of *life*.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProcLiveness:
    """The result of one OS process probe — `alive` plus a one-line `detail`.

    `alive` is THREE-valued on purpose:
      * True  — the process is confidently up (the OS confirms it exists/running).
      * False — the process is confidently gone (the OS confirms no such live pid
                on this host). The ONLY value allowed to demote a verdict.
      * None  — could not tell (foreign host, no pid, unsupported platform, a
                permission/OS error). Corroborates nothing, demotes nothing.

    `detail` is an operator-facing one-liner for `--output json` legibility — the
    same "legible distrust" the liveness verdict's reason carries.
    """

    alive: Optional[bool]
    detail: str


def _probe_posix(pid: int) -> ProcLiveness:
    """`os.kill(pid, 0)` — signal 0 tests existence + permission without delivering.

    Returns True if the process exists (or exists-but-not-ours, ESRCH vs EPERM),
    False on ESRCH (no such process), None on any other OSError (we couldn't tell).
    """
    try:
        os.kill(pid, 0)
        return ProcLiveness(True, f"pid {pid} is alive (posix kill 0 succeeded)")
    except ProcessLookupError:
        return ProcLiveness(False, f"pid {pid} is gone (posix ESRCH — no such process)")
    except PermissionError:
        # The process EXISTS but is owned by another user — existence is confirmed,
        # which is what liveness needs (it asks "alive?", not "ours?").
        return ProcLiveness(True, f"pid {pid} is alive (posix EPERM — exists, not ours)")
    except OSError as e:  # any other errno — we genuinely cannot tell
        return ProcLiveness(None, f"pid {pid} undetermined (posix OSError {e})")


# win32 OpenProcess access right + the "still running" sentinel.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259  # GetExitCodeProcess returns this while the process runs


def _probe_win32(pid: int) -> ProcLiveness:
    """`OpenProcess` + `GetExitCodeProcess` via ctypes — alive iff exit code is STILL_ACTIVE.

    A successful OpenProcess alone is NOT proof of life: Windows keeps a process
    object openable after exit while a handle lingers, so a freshly-exited pid can
    still open. We must read the exit code and confirm it is STILL_ACTIVE (259).
    Any failure to determine → None (never a fabricated True).
    """
    try:
        import ctypes
        from ctypes import wintypes
    except Exception as e:  # ctypes unavailable — cannot tell
        return ProcLiveness(None, f"pid {pid} undetermined (ctypes unavailable: {e})")
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            err = ctypes.get_last_error()
            # ERROR_INVALID_PARAMETER (87) on a non-existent pid == confidently gone.
            # ERROR_ACCESS_DENIED (5) == the process EXISTS but we can't open it →
            # existence confirmed (alive), same as POSIX EPERM.
            if err == 5:
                return ProcLiveness(True, f"pid {pid} is alive (win32 ACCESS_DENIED — exists)")
            if err == 87:
                return ProcLiveness(False, f"pid {pid} is gone (win32 INVALID_PARAMETER)")
            return ProcLiveness(None, f"pid {pid} undetermined (win32 OpenProcess err {err})")
        try:
            exit_code = wintypes.DWORD()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            if not ok:
                return ProcLiveness(None, f"pid {pid} undetermined (win32 GetExitCodeProcess failed)")
            if exit_code.value == _STILL_ACTIVE:
                return ProcLiveness(True, f"pid {pid} is alive (win32 STILL_ACTIVE)")
            return ProcLiveness(
                False, f"pid {pid} is gone (win32 exit code {exit_code.value})")
        finally:
            kernel32.CloseHandle(handle)
    except Exception as e:  # any ctypes/OS failure — we cannot tell
        return ProcLiveness(None, f"pid {pid} undetermined (win32 probe error: {e})")


def probe(
    pid: Optional[int],
    *,
    host_id: str = "",
    this_host: str = "",
) -> ProcLiveness:
    """Is `pid` (recorded on `host_id`) alive RIGHT NOW on `this_host`? Never raises.

    The single boundary reader `dos.liveness`'s evidence-gather calls to fill
    `ProgressEvidence.process_alive`. Resolves to:

      * None  — no pid (None / ≤0 sentinel), a foreign host (`host_id` set and ≠
                `this_host`), an unsupported platform, or any probe error. The
                "could not tell" value: it neither promotes nor demotes a verdict.
      * True  — the OS confirms a live process for `pid` on this host.
      * False — the OS confirms no such live process on this host (the one value
                that may demote SPINNING→STALLED downstream).

    `host_id` is the host the lease/run recorded the pid on; `this_host` is where
    we are probing. Both default to "" so a caller that does not track hosts (a
    single-box workspace) gets a pure pid probe — the foreign-host guard only
    fires when BOTH are set and differ, never blindly refusing a host-less pid.
    """
    if pid is None or pid <= 0:
        # ≤0 is the lease layer's "no real pid" sentinel (TTL-only liveness) — there
        # is nothing to probe, so we cannot tell (and must not pretend gone=False,
        # which would demote a TTL-only lease the heartbeat says is fine).
        return ProcLiveness(None, f"no probeable pid (pid={pid!r}) — TTL-only liveness")

    if host_id and this_host and host_id != this_host:
        return ProcLiveness(
            None,
            f"pid {pid} was recorded on host {host_id!r}, probing from "
            f"{this_host!r} — foreign host, cannot tell",
        )

    if sys.platform.startswith("win"):
        return _probe_win32(pid)
    if os.name == "posix":
        return _probe_posix(pid)
    return ProcLiveness(None, f"pid {pid} on unsupported platform {sys.platform!r} — cannot tell")

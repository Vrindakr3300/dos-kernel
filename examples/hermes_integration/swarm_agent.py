"""swarm_agent — a mock Hermes / OpenClaw autonomous worker.

It stands in for one agent in a swarm. It does two kinds of thing a real
autonomous runtime does, each of which is where DOS adds value:

  * runs a TOOL COMMAND (axis 2 / safety) — some commands are innocuous
    (`git status`), one is the prompt-injection hazard (`bash -c 'rm -rf …'`) the
    runtimes' weak defaults let through.
  * writes SHARED STATE (axis 1 / coordination) — books a slot in the shared
    reservations store, racing other agents for the same slot.

Two modes select whether DOS is in the loop:

  * ``naive``   — the runtime's status quo: run the command, write the state. No gate.
  * ``guarded`` — gate the command through ``hermes_adapter.guard_action`` and the
    write through ``hermes_adapter.claim_region`` first; obey DOS's verdict.

A real integrator does not edit this file — they edit their OWN tool-execution loop
to call the two adapter functions. This agent is just a harness to make the
difference measurable.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from hermes_adapter import claim_region, guard_action, lease_dict
from shared_resource import Reservations


@dataclass
class AgentResult:
    name: str
    ran_command: bool = False          # did the tool command actually execute?
    command_blocked: bool = False      # did DOS block it (guarded mode)?
    booked: bool = False               # did the agent's booking land?
    region_refused: bool = False       # did DOS refuse the region (guarded mode)?
    notes: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def hazards_can_fire() -> bool:
    """Can this host actually EXECUTE the stand-in hazards (the naive arm)?

    Answered by RUNNING a shell, never by inspecting PATH: the hazards are
    `bash -c` / `sh -c` one-liners, so the honest probe is whether
    `bash -c "echo ok"` (or, failing that, `sh -c "echo ok"`) executes and says
    ok. ANY working bash counts — including Windows' System32 WSL launcher,
    because `run_tool_command` addresses the sentinel by bare filename + cwd, a
    shape every bash dialect resolves. The pinning test consults this so a host
    with no working POSIX shell at all reads as an explicit skip, never a
    silent `naive = 0` failure.
    """
    for shell in ("bash", "sh"):
        try:
            proc = subprocess.run(
                f'{shell} -c "echo ok"', shell=True, capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=10, start_new_session=True,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        if proc.returncode == 0 and "ok" in proc.stdout:
            return True
    return False


def run_tool_command(command: str, sentinel: Path) -> bool:
    """Actually execute a tool command. To prove (non-forgeably) that the
    destructive command WOULD have run, the demo's 'unsafe' command appends a line
    to `sentinel` — so a post-run count of sentinel lines is the witness for 'how
    many unsafe commands executed', independent of what the agent claims.

    We run the command with the sentinel path substituted in for any '{SENTINEL}'
    token, so the demo never runs a truly destructive command — it runs a STAND-IN
    that has the same arbitrary-exec SHAPE (`bash -c '…'`) but only touches the
    sentinel. DOS classifies the shape, which is the point.
    """
    # Substitute the BARE filename and anchor the child in the sentinel's
    # directory: a relative name is the one path shape every shell dialect
    # resolves identically. An absolute C:/-shaped path is unaddressable inside
    # Windows' System32 WSL-launcher bash (it needs the /mnt/c automount form),
    # so the hazards would silently no-op there — but the WSL child inherits the
    # Windows cwd as /mnt/c/…, and Git bash / native sh resolve the bare name in
    # cwd just the same. Commands that never mention the sentinel keep the
    # caller's cwd (`git status` should still report the caller's repo).
    cwd = str(sentinel.parent) if "{SENTINEL}" in command else None
    cmd = command.replace("{SENTINEL}", sentinel.name)
    # An unattended hazard must never be able to BLOCK the demo. The `sudo` stand-in
    # opens the controlling terminal (/dev/tty) to prompt for a password on a host
    # without passwordless sudo (the default on a stock Linux box); from a background
    # process group that tty access raises SIGTTIN and STOPS the whole group — a
    # deadlock, not a wait. `start_new_session=True` detaches the child from the
    # controlling tty so it gets no terminal and FAILS fast instead (stdin=DEVNULL is
    # NOT enough — sudo reads /dev/tty, not stdin); the timeout is a backstop. A
    # stand-in that only echoes to the sentinel needs no tty, so this leaves the
    # witnessed count unchanged where the hazard can actually run unattended.
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, cwd=cwd,
            stdin=subprocess.DEVNULL, timeout=10, start_new_session=True,
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0


def act(
    *,
    name: str,
    mode: str,
    command: str | None,
    sentinel: Path,
    slot: str | None,
    store: Reservations | None,
    live_leases: list[dict],
    deny_on_arbitrary_exec: bool = True,
) -> AgentResult:
    """One agent's turn: optionally run a tool command, optionally book a slot.

    `live_leases` is the set of regions other agents already hold (for the guarded
    coordination arm). On a successful guarded booking the caller should append
    `lease_dict(region)` so the NEXT agent sees this region as taken.
    """
    res = AgentResult(name=name)

    # --- axis 2: the tool command -------------------------------------------
    if command is not None:
        if mode == "guarded":
            verdict = guard_action(command, deny_on_arbitrary_exec=deny_on_arbitrary_exec)
            if not verdict.allowed:
                res.command_blocked = True
                res.notes.append(f"DOS blocked `{command}` ({verdict.capability})")
            else:
                res.ran_command = run_tool_command(command, sentinel)
                res.notes.append(f"ran `{command}` ({verdict.capability}, allowed)")
        else:  # naive: run it, no questions asked
            res.ran_command = run_tool_command(command, sentinel)
            res.notes.append(f"ran `{command}` (naive, ungated)")

    # --- axis 1: the shared-state write -------------------------------------
    if slot is not None and store is not None:
        region = f"reservations/{slot}/**"
        if mode == "guarded":
            verdict = claim_region(region, live_leases, workspace=".")
            if not verdict.acquired:
                res.region_refused = True
                res.notes.append(f"DOS refused region {region}: {verdict.reason}")
            else:
                store.book(slot, name)
                res.booked = True
                res.notes.append(f"leased {verdict.lane} -> booked slot {slot}")
        else:  # naive: book directly, racing everyone else
            store.book(slot, name)
            res.booked = True
            res.notes.append(f"booked slot {slot} (naive, no lease)")

    return res


__all__ = ["AgentResult", "act", "run_tool_command"]

"""hermes_adapter — the ~2-function wire-in that gives a Hermes / OpenClaw runtime
DOS's safety gate and lease manager. *This is the file you copy.*

The whole integration is: before your autonomous agent **runs a tool command** or
**writes shared state**, ask DOS — by shelling the `dos` CLI exactly as any foreign
runtime must (there is NO `import dos` here; DOS is a separate process, the
zero-coupling adoption surface). DOS answers with a deterministic verdict the agent
cannot forge, and your runtime honors it.

Two seams, one per axis of value (see ``docs/278``):

  * ``guard_action(command)`` — AXIS 2, SAFETY (matters even for a single agent).
    Shells ``dos exec-capability`` to classify the *shape* of the command. An
    autonomous agent that a prompt-injection (or a buggy skill) steered into
    ``bash -c 'rm -rf ~'`` / ``npx <fetched-pkg>`` / ``ssh …`` / ``sudo …`` is
    asking to run *arbitrary code*; DOS flags that BEFORE it runs. It is SHAPE-not-
    word: ``cat python.txt`` is BOUNDED (the filename ``python`` is not an invocation
    of python), so the gate does not false-positive on innocent commands.

  * ``claim_region(region, live_leases)`` — AXIS 1, COORDINATION (the fleet case).
    Shells ``dos arbitrate`` to lease a *region* of shared state (a set of repo-
    relative globs, e.g. ``reservations/42/**``). Two concurrent agents that ask
    for the same region cannot both ACQUIRE — the loser is REFUSED (and, for a
    cluster request, auto-redirected to a free disjoint lane). The lease is recorded
    in DOS's write-ahead log, so it survives the agent process that took it.

Neither call mutates your agent's reasoning; each returns a verdict your
tool-execution loop reads and obeys. That is the entire contract: *adjudicate the
act against ground truth instead of trusting the agent's narration of it.*
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Locate the `dos` CLI. A real runtime would assume it is on PATH (the user
# `pip install dos-kernel`-ed it). We fall back to `python -m dos.cli` so the
# demo runs from a dev checkout with no console-script on PATH.
# ---------------------------------------------------------------------------
def _dos_argv() -> list[str]:
    exe = shutil.which("dos")
    if exe:
        return [exe]
    return ["python", "-m", "dos.cli"]


def _run_dos(args: list[str]) -> subprocess.CompletedProcess:
    """Invoke `dos <args>` and capture stdout/stderr/exit-code. Never raises on a
    non-zero exit — the exit code IS the verdict for DOS's truth/admission verbs."""
    return subprocess.run(
        _dos_argv() + args,
        capture_output=True,
        text=True,
        check=False,
    )


# ===========================================================================
# AXIS 2 — SAFETY: gate a tool command before the agent runs it.
# ===========================================================================
@dataclass(frozen=True)
class ActionVerdict:
    """DOS's verdict on whether a proposed tool command is safe to run."""

    allowed: bool          # may the runtime run this command?
    capability: str        # GRANTS_ARBITRARY_EXEC | BOUNDED | EMPTY
    program: str | None    # the invoked program DOS matched (e.g. "bash")
    reason: str            # one-line operator-facing why
    message: str           # what to surface to the agent on a deny


def guard_action(command: str, *, deny_on_arbitrary_exec: bool = True) -> ActionVerdict:
    """Classify a proposed tool COMMAND's execution capability via DOS, and decide
    allow/deny for an *autonomous* agent.

    `dos exec-capability --command "<cmd>"` exits 0 for BOUNDED/EMPTY and 3 for
    GRANTS_ARBITRARY_EXEC, printing "<CAPABILITY>  <reason>" on stdout. We parse
    that into a typed verdict.

    `deny_on_arbitrary_exec` is the POLICY knob, and it belongs to YOU (the host),
    not to DOS — DOS only *reports* the capability (advisory by default, the
    docs/143 "spurious disruption is the expensive mistake" discipline). An
    *unattended* agent reaching the public internet should set this True (hard
    block); an interactive, supervised one might set it False and merely warn.
    """
    proc = _run_dos(["exec-capability", "--command", command])
    # stdout is "<CAPABILITY>  <reason>"; the exit code (0 vs 3) is the same signal.
    out = (proc.stdout or "").strip()
    capability = out.split(None, 1)[0] if out else "EMPTY"
    reason = out.split(None, 1)[1] if " " in out else out
    grants = capability == "GRANTS_ARBITRARY_EXEC"

    allowed = not (grants and deny_on_arbitrary_exec)
    message = ""
    if not allowed:
        message = (
            f"DOS refused this command: it invokes an arbitrary-code-execution "
            f"entry point ({reason}). An autonomous agent will not run it. "
            f"Use a bounded, single-purpose command instead."
        )
    return ActionVerdict(
        allowed=allowed,
        capability=capability,
        program=_program_of(command),
        reason=reason,
        message=message,
    )


def _program_of(command: str) -> str | None:
    """Best-effort: the first non-assignment token, basename-lowered (for display
    only — DOS does the authoritative tokenization)."""
    for tok in command.split():
        if "=" in tok.split("/")[-1] and tok.split("=", 1)[0].replace("_", "").isalnum():
            continue
        return tok.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return None


# ===========================================================================
# AXIS 1 — COORDINATION: lease a region of shared state before writing it.
# ===========================================================================
@dataclass(frozen=True)
class RegionVerdict:
    """DOS's verdict on whether the agent may take (lease) a region of shared state."""

    acquired: bool         # did the agent get the region?
    lane: str              # the region actually leased (may differ if auto-picked)
    outcome: str           # "acquire" | "refuse"
    auto_picked: bool      # did DOS redirect to a free disjoint region?
    reason: str            # one-line why


def claim_region(
    region: str,
    live_leases: list[dict],
    *,
    workspace: str | Path = ".",
    kind: str = "keyword",
) -> RegionVerdict:
    """Ask DOS whether the agent may take `region` (a glob like
    "reservations/42/**"), given the regions currently held by other agents
    (`live_leases`).

    `dos arbitrate --lane <region> --kind keyword --tree <region> --leases <json>`
    is a PURE decision: state in, verdict out, no disk write. It exits 0 + an
    `{"outcome":"acquire",...}` JSON when the region is free and disjoint from every
    live lease, or 1 + `{"outcome":"refuse",...}` when another agent holds it.

    `live_leases` is a list of `{"lane","lane_kind","tree"}` dicts — the regions
    other agents have already claimed. In a real runtime you keep this set in your
    shared store (or read DOS's own WAL via `dos journal replay --json`); here the
    demo threads it explicitly so the coordination is visible.
    """
    args = [
        "--workspace", str(workspace),
        "arbitrate",
        "--lane", region,
        "--kind", kind,
        "--tree", region,
        "--leases", json.dumps(live_leases),
        "--output", "json",
    ]
    proc = _run_dos(args)
    try:
        verdict = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        verdict = {}
    outcome = verdict.get("outcome", "refuse")
    return RegionVerdict(
        acquired=outcome == "acquire",
        lane=verdict.get("lane", region),
        outcome=outcome,
        auto_picked=bool(verdict.get("auto_picked", False)),
        reason=verdict.get("reason", proc.stderr.strip() or "no verdict"),
    )


def lease_dict(region: str, kind: str = "keyword") -> dict:
    """Build the live-lease record for a region the agent now holds — the shape
    `claim_region` expects in `live_leases` for the NEXT agent's call."""
    return {"lane": region, "lane_kind": kind, "tree": [region]}


# ---------------------------------------------------------------------------
# The DURABLE lease path — the real cross-process coordination primitive.
# Unlike `claim_region` (a pure decision you feed live leases into), these go
# through DOS's write-ahead log: `acquire_lease` arbitrates AND journals the grant
# atomically (guarded by DOS's archive-lock, so two processes cannot both win), and
# the next caller's arbitration replays the WAL and sees the held region. This is
# what a real fleet uses — the lock survives the process that took it.
# ---------------------------------------------------------------------------
def acquire_lease(
    region: str,
    *,
    owner: str,
    loop_ts: str,
    workspace: str | Path = ".",
    kind: str = "keyword",
) -> RegionVerdict:
    """Durably acquire `region` against DOS's WAL via `dos lease-lane acquire`.

    Arbitrates against the live set reconstructed from the journal, and on ACQUIRE
    appends the grant to the WAL — atomically, under the archive-lock. A concurrent
    process asking for the same region replays the journal, sees it held, and is
    REFUSED. `loop_ts` is the (loop_ts, lane) identity that keys the lease; give
    each agent a distinct one.
    """
    args = [
        "--workspace", str(workspace),
        "lease-lane", "acquire",
        "--lane", region,
        "--kind", kind,
        "--tree", region,
        "--owner", owner,
        "--loop-ts", loop_ts,
    ]
    proc = _run_dos(args)
    verdict = _parse_last_json(proc.stdout)
    outcome = verdict.get("outcome", "refuse")
    return RegionVerdict(
        acquired=outcome == "acquire",
        lane=verdict.get("lane", region),
        outcome=outcome,
        auto_picked=bool(verdict.get("auto_picked", False)),
        reason=verdict.get("reason", proc.stderr.strip() or "no verdict"),
    )


def release_lease(
    region: str,
    *,
    owner: str,
    loop_ts: str,
    workspace: str | Path = ".",
) -> bool:
    """Release a durably-held region via `dos lease-lane release` (RELEASE to the
    WAL), freeing it for the next agent."""
    args = [
        "--workspace", str(workspace),
        "lease-lane", "release",
        "--lane", region,
        "--owner", owner,
        "--loop-ts", loop_ts,
    ]
    proc = _run_dos(args)
    return proc.returncode == 0


def _parse_last_json(stdout: str) -> dict:
    """Parse the last JSON object on stdout. `lease-lane acquire` may print a
    one-time `.dos/ created` notice before the verdict; the verdict is the last
    `{...}` line, so we scan from the end."""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


__all__ = [
    "ActionVerdict",
    "RegionVerdict",
    "guard_action",
    "claim_region",
    "acquire_lease",
    "release_lease",
    "lease_dict",
]

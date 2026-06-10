"""dos.guard — the headless-launch wrapper (the argv shim, docs/134 §4).

`dos guard [opts] -- <host-cmd> [host-args]` frames a non-interactive agent
launch (`claude -p …`, or any host taking the same flags) with the DOS wiring,
then execs the host command. It injects two things the host already honors:

  * ``--mcp-config '<json>'`` — mounts the DOS MCP server (``dos-mcp``) so the
    agent *can* call ``dos_verify`` / ``dos_arbitrate`` mid-run. (Works today —
    ``dos-mcp`` is a shipped console script.)
  * ``--settings '<json>'`` — carries a ``Stop`` hook (the verify-on-stop
    binding, docs/134 §2) and/or an ``--append-system-prompt`` instruction.
    This is the ONLY way to add a hook to a headless run — there is no
    ``--hooks`` flag (verified against ``claude --help``).

The split is the whole contract: everything after ``--`` is the host command,
passed through byte-for-byte. DOS computes the two injected flags and appends
them; an unrecognized host flag is the host's problem, not ours (degrade to
passthrough). This module is a **layer-3 helper** — it names no host internals
beyond the two public flags, takes no lease, and computes a plan a test can
assert without ever launching a subprocess.

Design discipline (mirrors the kernel's "pure core, I/O at the boundary"):
``build_guard_plan`` is PURE — options in, a ``GuardPlan`` (the injected JSON +
the final argv) out, no environment read, no process spawned. The CLI verb does
the one impure thing (``os.execvp`` / ``subprocess``) over the plan the pure
function returned, and ``--print-config`` dumps the plan without launching.

This is a CONSUMER surface, the MCP server's sibling: it *frames* a host launch,
it does not get inside the host. The advisory-only boundary (docs/99) is intact —
nothing here forces a process; the dev typed ``dos guard``, and the host is what
honors the flags.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field


# The console script that serves the DOS syscalls as MCP tools (pyproject
# [project.scripts]). The wrapper points the host's --mcp-config at it by name;
# resolution is the host's PATH lookup, same as any MCP stdio server.
DEFAULT_MCP_COMMAND = "dos-mcp"

# The default Stop-hook command — the docs/134 §2 verify-on-stop binding, now
# SHIPPED (`cmd_hook_stop`). The hook stays OPT-IN (`--verify-on-stop`), never
# injected by default, because it changes the launch's stop behavior — that is a
# decision the dev makes explicitly, not a silent default. (The MCP mount, which
# only ADDS a callable tool, is the safe default.)
DEFAULT_STOP_HOOK_COMMAND = "dos hook stop --workspace ."

# The one instruction that makes the docs/134 §2.1 explicit-marker rung reliable:
# the agent declares what to verify in a form the claim extractor lifts exactly.
DEFAULT_CLAIM_PROMPT = (
    "When you complete a unit of work, end your turn with a line of the form "
    "`DOS-CLAIM: <plan> <phase>` naming the plan and phase you claim shipped, so "
    "it can be verified against git."
)


@dataclass(frozen=True)
class GuardPlan:
    """The pure result of framing a launch: what to inject and the final argv.

    ``argv`` is the complete command to exec (host command + appended DOS flags).
    ``mcp_config`` / ``settings`` are the JSON objects injected (kept separately
    so ``--print-config`` can show them legibly and tests can assert on them).
    ``notes`` carries any honesty caveats surfaced to the user (e.g. the Stop
    hook targeting a not-yet-built verb).
    """

    argv: list[str]
    mcp_config: dict | None
    settings: dict | None
    host_command: list[str]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "argv": self.argv,
            "mcp_config": self.mcp_config,
            "settings": self.settings,
            "host_command": self.host_command,
            "notes": self.notes,
        }


def build_settings(
    *,
    verify_on_stop: bool,
    stop_hook_command: str = DEFAULT_STOP_HOOK_COMMAND,
    append_prompt: str | None = None,
) -> dict | None:
    """Build the ``--settings`` JSON object, or None if nothing to inject.

    Pure. The Stop hook is only present when ``verify_on_stop`` is True — see the
    DEFAULT_STOP_HOOK_COMMAND note on why it is opt-in.
    """
    settings: dict = {}
    if verify_on_stop:
        # The host's settings.json hook shape (verified): an event → a list of
        # matcher-groups, each carrying a list of {type, command} hooks.
        settings["hooks"] = {
            "Stop": [
                {"hooks": [{"type": "command", "command": stop_hook_command}]}
            ]
        }
    if append_prompt:
        # Carried in settings too — the host merges an appendSystemPrompt setting
        # the same way the CLI --append-system-prompt flag does. (We pass it via
        # settings rather than a second flag so the whole injection is two flags
        # max, and so --print-config shows one legible object.)
        settings["appendSystemPrompt"] = append_prompt
    return settings or None


def build_mcp_config(
    *, mount_mcp: bool, mcp_command: str = DEFAULT_MCP_COMMAND
) -> dict | None:
    """Build the ``--mcp-config`` JSON object, or None if not mounting.

    Pure. The DOS server is mounted under the key ``dos`` so the agent's tools
    are ``mcp__dos__verify`` etc.
    """
    if not mount_mcp:
        return None
    return {"mcpServers": {"dos": {"command": mcp_command}}}


def build_guard_plan(
    host_command: list[str],
    *,
    mount_mcp: bool = True,
    verify_on_stop: bool = False,
    add_claim_prompt: bool = False,
    strict_mcp: bool = False,
    stop_hook_command: str = DEFAULT_STOP_HOOK_COMMAND,
    mcp_command: str = DEFAULT_MCP_COMMAND,
) -> GuardPlan:
    """Frame a host launch with the DOS wiring. PURE — no I/O, no subprocess.

    Returns the complete ``argv`` to exec plus the injected objects. Raises
    ``ValueError`` only on an empty host command (the one contract error).
    """
    # argparse.REMAINDER keeps a literal leading `--` separator in the captured
    # list; strip one so callers may pass the host command with or without it.
    if host_command and host_command[0] == "--":
        host_command = host_command[1:]

    if not host_command:
        raise ValueError(
            "dos guard needs a host command after `--` "
            "(e.g. `dos guard -- claude -p \"...\"`)."
        )

    notes: list[str] = []

    append_prompt = DEFAULT_CLAIM_PROMPT if add_claim_prompt else None
    mcp_config = build_mcp_config(mount_mcp=mount_mcp, mcp_command=mcp_command)
    settings = build_settings(
        verify_on_stop=verify_on_stop,
        stop_hook_command=stop_hook_command,
        append_prompt=append_prompt,
    )

    # Build the final argv: host command, then the appended DOS flags. We append
    # (never prepend) so the host's own flags parse first and ours are additive —
    # and so a host that doesn't recognize a flag fails on OUR flag, legibly,
    # rather than mangling the user's command.
    argv = list(host_command)
    if mcp_config is not None:
        argv += ["--mcp-config", json.dumps(mcp_config, sort_keys=True)]
        if strict_mcp:
            # Only use the servers we injected — the CI-honest form (verified flag).
            argv += ["--strict-mcp-config"]
    if settings is not None:
        argv += ["--settings", json.dumps(settings, sort_keys=True)]

    return GuardPlan(
        argv=argv,
        mcp_config=mcp_config,
        settings=settings,
        host_command=list(host_command),
        notes=notes,
    )


def render_plan_human(plan: GuardPlan) -> str:
    """A legible multi-line dump of what `dos guard` would inject and run."""
    lines: list[str] = []
    lines.append("dos guard — launch plan")
    lines.append("")
    lines.append("host command (passed through verbatim):")
    lines.append("  " + " ".join(shlex.quote(a) for a in plan.host_command))
    lines.append("")
    if plan.mcp_config is not None:
        lines.append("injected --mcp-config:")
        lines.append("  " + json.dumps(plan.mcp_config, sort_keys=True))
    else:
        lines.append("injected --mcp-config: (none — MCP mount disabled)")
    if plan.settings is not None:
        lines.append("injected --settings:")
        lines.append("  " + json.dumps(plan.settings, sort_keys=True))
    else:
        lines.append("injected --settings: (none)")
    lines.append("")
    lines.append("final argv to exec:")
    lines.append("  " + " ".join(shlex.quote(a) for a in plan.argv))
    if plan.notes:
        lines.append("")
        lines.append("notes:")
        for n in plan.notes:
            lines.append("  ! " + n)
    return "\n".join(lines)

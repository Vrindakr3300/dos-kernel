"""XCAP — the arbitrary-code-execution capability classifier: *a SHAPE, not a word.*

docs/224 — idea **B1** from the Claude Code source audit (docs/189). The audit
found CC's `dangerousPatterns.ts`: a list that identifies which *allow-rule
prefixes* hand the model **arbitrary code execution** — `python`, `node`, `bash`,
`ssh`, `npx`, `eval`, … An allow-rule like `Bash(python:*)` is not "a python
command"; it is *a way to run anything at all*, because `python -c '<any code>'`
escapes every narrower gate. CC strips such rules at auto-mode entry. The insight
DOS lifts is the docs/158 law — **a capability is a SHAPE, not a word** — applied to
*command auditing* rather than output classification: you do not scan a command for
the substring "dangerous"; you ask "does the program it invokes grant arbitrary
execution?", matched against a closed, declared capability list.

This is a **pure classifier leaf**, the `terminal_error`/`arg_provenance` detector
shape (a pure verdict over already-gathered bytes), NOT an admission predicate. The
distinction is deliberate and load-bearing:

  * `self_modify` is an *admission* predicate — it answers "may this LANE (a
    file-tree request) be leased?" over a tree. It plugs into the arbiter's
    conjunction.
  * XCAP answers "does this COMMAND grant arbitrary exec?" over a command string.
    DOS has no permission-rule allow-list surface (CC's home for this), so XCAP is
    not an arbiter predicate — it is a classifier the **consumer** (`pretool_sensor`,
    the PRE-moment PEP, docs/191) consults to attach an advisory signal to a
    proposed Bash call. The verdict REPORTS the capability; the consumer decides
    what to do with it (today: a WARN on the intervention ladder; a host driver may
    escalate). Advisory by default — the docs/143 −9 pp lesson: spurious disruption
    is the expensive mistake, so a capability *observation* never auto-denies on its
    own (a deny is a host's explicit, --force-overridable choice).

**Byte-clean / SHAPE-not-word, made precise.** XCAP reads the *program token* — the
first word of the command (after stripping an `env VAR=…` / `sudo` prefix) — and
compares it to a closed set. It does NOT regex the whole command for scary
substrings (a path named `my_eval_helper.txt` is not an `eval`; a comment
mentioning `python` is not a python invocation). Matching the invoked-program SHAPE,
not a word anywhere in the string, is what keeps it from the forgeable-keyword trap
the docs/158 detector-design guide warns against. The command bytes are the agent's
*proposal* (agent-authored), so XCAP is a check on a PROPOSED capability, not a
distrust-of-result verdict — it belongs at PRE (before the call runs), exactly where
`pretool_sensor` already lives.

**Domain-free / mechanism-policy split.** The mechanism is "tokenize the command,
look up the program in the capability set." The policy — *which programs grant
arbitrary exec* — is data, defaulted to CC's `CROSS_PLATFORM_CODE_EXEC` list and
declarable per-workspace in `dos.toml [exec_capability]`. A host that ships an
internal interpreter adds one line of data; the kernel's matching logic never
changes. The classifier never branches on a host name.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Capability(str, enum.Enum):
    """What execution capability a command grants — the typed verdict.

    `str`-valued so it round-trips through a CLI stdout token / exit-code map
    (the `liveness.Liveness` / `breaker.BreakerState` idiom).
    """

    GRANTS_ARBITRARY_EXEC = "GRANTS_ARBITRARY_EXEC"  # invokes an interpreter/shell/remote-exec
    BOUNDED = "BOUNDED"  # the invoked program is not a known arbitrary-exec entry point
    EMPTY = "EMPTY"      # no program token to classify (blank command)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# ---------------------------------------------------------------------------
# The capability set — CC's CROSS_PLATFORM_CODE_EXEC, lifted verbatim. Each entry
# is a PROGRAM whose mere invocation grants arbitrary code execution (an
# interpreter that takes `-c`/`-e`, a shell, a package-runner that runs scripts, a
# remote-exec wrapper). This is the SHAPE the classifier matches the program token
# against — declared as data so a host extends it in `dos.toml [exec_capability]`,
# the closed-config-as-data pattern (`[lanes]`/`[reasons]`/`[liveness]`).
# ---------------------------------------------------------------------------
CROSS_PLATFORM_CODE_EXEC: frozenset[str] = frozenset({
    # Interpreters — each takes inline code (`python -c`, `node -e`, `ruby -e`, …).
    "python", "python3", "python2", "node", "deno", "tsx", "ruby", "perl", "php", "lua",
    # Package runners — run arbitrary project scripts / fetched packages.
    "npx", "bunx", "npm", "yarn", "pnpm", "bun",
    # Shells — the most direct arbitrary-exec entry point.
    "bash", "sh", "zsh", "fish",
    # Exec built-ins / wrappers that run an arbitrary argument as a program.
    "eval", "exec", "xargs",
    # Remote / privilege wrappers — arbitrary command on another host / as root.
    "ssh", "sudo",
})

# Prefix tokens that wrap a REAL program without being the capability themselves:
# `env FOO=bar python …` and `sudo python …` both invoke `python`. We strip these
# (and any `VAR=value` assignments) to find the program token actually invoked.
# NOTE `sudo` is ALSO in the capability set (it grants root) — so `sudo rm` is
# GRANTS_ARBITRARY_EXEC via the sudo entry, while `sudo python` is caught either
# way; stripping it lets us also see the wrapped `python`. The verdict fires on the
# FIRST capability hit, so wrapping never hides a capability.
_WRAPPER_TOKENS: frozenset[str] = frozenset({"env", "sudo", "command", "nice", "nohup", "time"})


@dataclass(frozen=True)
class ExecCapabilityPolicy:
    """The capability set to match against — policy, not mechanism.

    The mechanism (tokenize, strip wrappers, look up) is the kernel's; the SET of
    arbitrary-exec programs is data. Defaults to `CROSS_PLATFORM_CODE_EXEC` (CC's
    list); a workspace declares additions in `dos.toml [exec_capability]`
    (`extra = ["myinterp"]`), the same closed-config-as-data on-ramp as `[reasons]`.

      programs — the closed set of program tokens that grant arbitrary execution.
                 Matched case-insensitively against the invoked program token (a
                 program's basename, lower-cased — `/usr/bin/python3` → `python3`).
    """

    programs: frozenset[str] = field(default_factory=lambda: CROSS_PLATFORM_CODE_EXEC)

    def with_extra(self, extra) -> "ExecCapabilityPolicy":
        """A new policy with `extra` program tokens added (the host on-ramp)."""
        more = frozenset(str(p).strip().lower() for p in (extra or ()) if str(p).strip())
        return ExecCapabilityPolicy(programs=self.programs | more)


DEFAULT_POLICY = ExecCapabilityPolicy()


@dataclass(frozen=True)
class ExecCapabilityVerdict:
    """The classifier's verdict + the evidence (the matched program), echoed back.

    `capability` is the typed `Capability`. `program` is the invoked program token
    the classifier extracted (the basename, lower-cased) — None for an empty
    command. `reason` is the one-line operator-facing summary. The matched program
    is carried so a consumer can name *what* grants the capability (legible
    distrust — "GRANTS_ARBITRARY_EXEC via `python`", not a bare flag).
    """

    capability: Capability
    program: str | None
    reason: str

    @property
    def grants_arbitrary_exec(self) -> bool:
        return self.capability is Capability.GRANTS_ARBITRARY_EXEC

    def to_dict(self) -> dict:
        return {
            "capability": self.capability.value,
            "program": self.program,
            "reason": self.reason,
        }


def _program_token(command: str) -> str | None:
    """Extract the program token a command invokes. PURE — a tokenizer, not a shell.

    The SHAPE extraction: split off the first word, skipping leading `VAR=value`
    assignments and benign wrappers (`env`, `nice`, `time`, …) to find the program
    that is actually run. Returns the program's BASENAME, lower-cased
    (`/usr/bin/python3` → `python3`, `PYTHON` → `python`), or None for a blank
    command. Deliberately simple — it reads the invoked-program shape, never the
    whole command (matching a word anywhere would be the forgeable-keyword trap).
    """
    if not command or not command.strip():
        return None
    # Walk leading tokens, skipping VAR=value assignments and wrapper words, until
    # we hit the real program. A wrapper that is ALSO a capability (`sudo`) is
    # handled by the caller scanning all leading capability hits — here we just find
    # the first non-wrapper, non-assignment token to report as the program.
    for raw in command.strip().split():
        tok = raw.strip()
        if not tok:
            continue
        if "=" in tok and not tok.startswith("="):
            # A leading `VAR=value` assignment (only before the program) — skip.
            head = tok.split("=", 1)[0]
            if head and all(c.isalnum() or c == "_" for c in head):
                continue
        base = tok.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if base in _WRAPPER_TOKENS:
            continue  # a wrapper — keep walking to the wrapped program
        return base
    return None


def _leading_tokens(command: str) -> list[str]:
    """The leading program-ish tokens (basenames, lower-cased) up to the first
    non-wrapper program, INCLUDING any wrapper that is itself a capability. PURE.

    Used so a command whose WRAPPER is a capability (`sudo rm`) fires on the sudo
    entry even though the reported program is the wrapped `rm`. Returns the wrappers
    seen plus the final program token, in order.
    """
    out: list[str] = []
    for raw in command.strip().split():
        tok = raw.strip()
        if not tok:
            continue
        if "=" in tok and not tok.startswith("="):
            head = tok.split("=", 1)[0]
            if head and all(c.isalnum() or c == "_" for c in head):
                continue
        base = tok.replace("\\", "/").rsplit("/", 1)[-1].lower()
        out.append(base)
        if base not in _WRAPPER_TOKENS:
            break  # reached the real program — stop
    return out


def classify_command(
    command: str, policy: ExecCapabilityPolicy = DEFAULT_POLICY
) -> ExecCapabilityVerdict:
    """Classify the execution capability a command grants. PURE — no I/O.

    The ladder:
      1. EMPTY — no program token (a blank command). Nothing to classify.
      2. GRANTS_ARBITRARY_EXEC — the invoked program (or a capability wrapper like
         `sudo` in front of it) is in the capability set. `python -c …`, `bash -c …`,
         `npx …`, `ssh host …`, `sudo …` — each is a way to run arbitrary code.
      3. BOUNDED — the invoked program is not a known arbitrary-exec entry point
         (`ls`, `cat`, `git status`, `grep`, …). This is NOT a safety guarantee
         (`git` can run hooks; the audit notes `git`/`gh`/`curl` are ant-only
         additions) — only "not a member of the declared arbitrary-exec set." A host
         that wants those flagged adds them to `[exec_capability]`.

    Matches the SHAPE (the invoked program), never a substring of the command — so a
    file named `eval.txt` or a comment mentioning `python` does not trip it.
    """
    program = _program_token(command)
    if program is None:
        return ExecCapabilityVerdict(
            capability=Capability.EMPTY,
            program=None,
            reason="empty command — no program token to classify",
        )
    # Scan the leading tokens (wrappers + the program) for the FIRST capability hit,
    # so `sudo python` / `env X=1 bash` fire on whichever capability appears.
    for tok in _leading_tokens(command):
        if tok in policy.programs:
            return ExecCapabilityVerdict(
                capability=Capability.GRANTS_ARBITRARY_EXEC,
                program=program,
                reason=(
                    f"the command invokes {tok!r}, an arbitrary-code-execution entry "
                    f"point — it can run any code, escaping a narrower per-command gate "
                    f"(GRANTS_ARBITRARY_EXEC)"
                ),
            )
    return ExecCapabilityVerdict(
        capability=Capability.BOUNDED,
        program=program,
        reason=(
            f"the command invokes {program!r}, not a known arbitrary-exec entry point "
            f"— bounded (NOT a safety guarantee; only 'not in the declared exec set')"
        ),
    )

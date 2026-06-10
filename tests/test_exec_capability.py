"""XCAP — the arbitrary-exec capability classifier (docs/224, idea B1).

`exec_capability.classify_command` is a PURE classifier (the terminal_error/
arg_provenance detector shape) that answers "does this command grant arbitrary code
execution?" by matching the INVOKED PROGRAM SHAPE against a closed capability set —
the docs/158 "a SHAPE, not a word" law applied to command auditing.

The load-bearing correctness claim under test: it matches the invoked PROGRAM, never
a substring of the command — so a file named `eval.txt` or a comment mentioning
`python` does NOT trip it (the forgeable-keyword trap avoided).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dos import exec_capability
from dos.exec_capability import (
    Capability,
    ExecCapabilityPolicy,
    classify_command,
)


# ---------------------------------------------------------------------------
# The core: interpreters / shells / runners / remote-exec grant arbitrary exec.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cmd, prog", [
    ("python -c 'import os'", "python"),
    ("python3 script.py", "python3"),
    ("node -e 'process.exit(1)'", "node"),
    ("bash -c 'rm -rf /'", "bash"),
    ("sh ./install.sh", "sh"),
    ("npx create-react-app x", "npx"),
    ("npm run build", "npm"),
    ("ruby -e 'puts 1'", "ruby"),
    ("ssh host 'shutdown now'", "ssh"),
    ("deno run x.ts", "deno"),
])
def test_interpreters_and_runners_grant_arbitrary_exec(cmd, prog):
    v = classify_command(cmd)
    assert v.capability is Capability.GRANTS_ARBITRARY_EXEC
    assert v.program == prog
    assert v.grants_arbitrary_exec is True


@pytest.mark.parametrize("cmd, prog", [
    ("ls -la", "ls"),
    ("cat README.md", "cat"),
    ("git status", "git"),  # NOT in the default set (ant-only per the audit)
    ("grep -r foo src/", "grep"),
    ("echo hello", "echo"),
    ("mkdir build", "mkdir"),
])
def test_ordinary_commands_are_bounded(cmd, prog):
    v = classify_command(cmd)
    assert v.capability is Capability.BOUNDED
    assert v.program == prog
    assert v.grants_arbitrary_exec is False


# ---------------------------------------------------------------------------
# THE KEY PROPERTY: a SHAPE, not a word. A substring is not a capability.
# ---------------------------------------------------------------------------


def test_a_path_named_after_an_interpreter_does_not_trip():
    """`cat python_notes.txt` mentions 'python' but invokes `cat` → BOUNDED.

    The forgeable-keyword trap the docs/158 guide warns against: matching the word
    anywhere would mis-fire here. We match the invoked PROGRAM only.
    """
    v = classify_command("cat python_notes.txt")
    assert v.capability is Capability.BOUNDED
    assert v.program == "cat"


def test_an_argument_named_eval_does_not_trip():
    """`grep eval src/` searches for 'eval' but invokes `grep` → BOUNDED."""
    assert classify_command("grep eval src/").capability is Capability.BOUNDED


def test_a_filename_argument_to_a_bounded_tool_does_not_trip():
    """`./node_modules/.bin/something` as an ARG to `ls` is not a node invocation."""
    assert classify_command("ls node_modules/").capability is Capability.BOUNDED


# ---------------------------------------------------------------------------
# Wrapper stripping + basename normalization.
# ---------------------------------------------------------------------------


def test_env_wrapper_is_stripped_to_find_the_real_program():
    """`env FOO=bar python x.py` invokes python via the env wrapper → arbitrary exec."""
    v = classify_command("env FOO=bar python x.py")
    assert v.capability is Capability.GRANTS_ARBITRARY_EXEC
    assert v.program == "python"


def test_leading_var_assignment_is_skipped():
    """`PYTHONPATH=. python x.py` — a bare VAR=value prefix is skipped to the program."""
    v = classify_command("PYTHONPATH=. python x.py")
    assert v.capability is Capability.GRANTS_ARBITRARY_EXEC
    assert v.program == "python"


def test_sudo_wrapper_fires_on_sudo_itself():
    """`sudo rm -rf /x` invokes `rm` but `sudo` grants root → GRANTS_ARBITRARY_EXEC.

    The wrapper that is ALSO a capability fires on the wrapper entry; the reported
    program is the wrapped one.
    """
    v = classify_command("sudo rm -rf /x")
    assert v.capability is Capability.GRANTS_ARBITRARY_EXEC
    # The capability hit was `sudo`; the program walked-to is `rm`.
    assert v.program == "rm"
    assert "sudo" in v.reason


def test_sudo_python_is_caught():
    """`sudo python x.py` — caught either via sudo or the wrapped python."""
    assert classify_command("sudo python x.py").capability is Capability.GRANTS_ARBITRARY_EXEC


def test_absolute_path_program_is_basename_matched():
    """`/usr/bin/python3 x.py` → matched on the basename `python3`."""
    v = classify_command("/usr/bin/python3 x.py")
    assert v.capability is Capability.GRANTS_ARBITRARY_EXEC
    assert v.program == "python3"


def test_case_insensitive_program_match():
    """`PYTHON x.py` (upper) → matched (the set is lower-cased)."""
    assert classify_command("PYTHON x.py").capability is Capability.GRANTS_ARBITRARY_EXEC


# ---------------------------------------------------------------------------
# Empty + policy on-ramp.
# ---------------------------------------------------------------------------


def test_empty_command_is_empty():
    assert classify_command("").capability is Capability.EMPTY
    assert classify_command("   ").capability is Capability.EMPTY
    assert classify_command("").program is None


def test_host_can_extend_the_capability_set():
    """A host adds its own interpreter via the policy on-ramp."""
    p = DEFAULT = exec_capability.DEFAULT_POLICY.with_extra(["myinterp"])
    v = classify_command("myinterp run x", p)
    assert v.capability is Capability.GRANTS_ARBITRARY_EXEC
    assert v.program == "myinterp"
    # ...and the built-ins still fire under the extended policy.
    assert classify_command("python x", p).capability is Capability.GRANTS_ARBITRARY_EXEC


def test_with_extra_does_not_mutate_the_default():
    """The on-ramp returns a NEW policy (the closed-set immutability discipline)."""
    base = exec_capability.DEFAULT_POLICY
    base.with_extra(["zzz"])
    assert "zzz" not in base.programs  # default unchanged


def test_git_can_be_flagged_by_a_host_that_wants_it():
    """`git` is bounded by default but a host can add it (the audit's ant-only set)."""
    assert classify_command("git push").capability is Capability.BOUNDED
    p = exec_capability.DEFAULT_POLICY.with_extra(["git", "curl", "gh"])
    assert classify_command("git push", p).capability is Capability.GRANTS_ARBITRARY_EXEC


# ---------------------------------------------------------------------------
# Structural guarantees.
# ---------------------------------------------------------------------------


def test_classify_is_pure(monkeypatch):
    """classify_command makes NO I/O."""
    import builtins
    import time as _time

    def _boom(*a, **k):  # pragma: no cover - only on a violation
        raise AssertionError("classify_command must not perform I/O")

    monkeypatch.setattr(_time, "time", _boom)
    monkeypatch.setattr(builtins, "open", _boom)
    assert classify_command("python -c x").capability is Capability.GRANTS_ARBITRARY_EXEC


def test_verdict_to_dict_round_trips():
    v = classify_command("python -c 'x'")
    d = v.to_dict()
    assert d["capability"] == "GRANTS_ARBITRARY_EXEC"
    assert d["program"] == "python"
    assert json.loads(json.dumps(d, sort_keys=True)) == d


def test_default_set_matches_cc_cross_platform_list():
    """The default capability set is CC's CROSS_PLATFORM_CODE_EXEC (spot-check)."""
    s = exec_capability.CROSS_PLATFORM_CODE_EXEC
    for p in ("python", "node", "bash", "ssh", "npx", "deno"):
        assert p in s


# ---------------------------------------------------------------------------
# The CLI verb (`dos exec-capability`).
# ---------------------------------------------------------------------------


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_cli_grants_arbitrary_exec_exit_code(tmp_path: Path):
    """A command granting arbitrary exec → exit 3 (the verdict IS the code)."""
    r = _run_cli("exec-capability", "--command", "python -c 'import os'", cwd=tmp_path)
    assert r.returncode == 3, r.stderr
    assert "GRANTS_ARBITRARY_EXEC" in r.stdout


def test_cli_bounded_exit_zero(tmp_path: Path):
    """A bounded command → exit 0 (the success/no-finding case)."""
    r = _run_cli("exec-capability", "--command", "ls -la", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "BOUNDED" in r.stdout


def test_cli_shape_not_word(tmp_path: Path):
    """The SHAPE-not-word property holds through the CLI: `cat python.txt` → BOUNDED."""
    r = _run_cli("exec-capability", "--command", "cat python.txt", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "BOUNDED" in r.stdout


def test_cli_json(tmp_path: Path):
    r = _run_cli("exec-capability", "--command", "bash -c x", "--json", cwd=tmp_path)
    assert r.returncode == 3, r.stderr
    obj = json.loads(r.stdout)
    assert obj["capability"] == "GRANTS_ARBITRARY_EXEC"
    assert obj["program"] == "bash"


def test_cli_extra_flag_extends_the_set(tmp_path: Path):
    """`--extra git` flags a git command the default set leaves bounded."""
    bounded = _run_cli("exec-capability", "--command", "git push", cwd=tmp_path)
    assert bounded.returncode == 0
    flagged = _run_cli("exec-capability", "--command", "git push", "--extra", "git", cwd=tmp_path)
    assert flagged.returncode == 3
    assert "GRANTS_ARBITRARY_EXEC" in flagged.stdout


def test_cli_no_plan(tmp_path: Path):
    """The no-plan rail: a bare dir, no git/plan/journal — needs only the command."""
    r = _run_cli("exec-capability", "--command", "python x.py", cwd=tmp_path)
    assert r.returncode == 3, r.stderr
    assert not (tmp_path / ".dos").exists()


def test_cli_empty_command(tmp_path: Path):
    """An empty command → EMPTY, exit 0 (nothing to flag)."""
    r = _run_cli("exec-capability", "--command", "", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "EMPTY" in r.stdout

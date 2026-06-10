"""`dos guard` — the headless-launch wrapper (docs/134 §4).

`build_guard_plan` is the PURE core: options in, a `GuardPlan` (injected JSON +
final argv) out, no I/O, no subprocess — so the framing logic is asserted here
without ever launching a host. These pins the contract the live `--print-config`
runs demonstrate:

  * the host command after `--` is passed through VERBATIM (its own flags are
    not eaten), and a leading `--` separator is stripped;
  * the DOS MCP server is mounted by default (`--mcp-config` with the `dos` key)
    and can be turned off;
  * the Stop hook is OPT-IN (the target `dos hook stop` is not yet built), and
    when requested it carries an honesty note;
  * `--strict-mcp` / `--claim-prompt` add exactly their one flag / prompt;
  * the appended flags are ADDITIVE and come AFTER the host command, so a host
    that rejects an unknown flag fails on OUR flag, not on a mangled command;
  * an empty host command is the one contract error (ValueError → exit 2).
"""

from __future__ import annotations

import json

import pytest

from dos import guard


# ---------------------------------------------------------------------------
# The default plan — MCP mounted, no settings.
# ---------------------------------------------------------------------------
def test_default_mounts_mcp_and_passes_host_through():
    plan = guard.build_guard_plan(["claude", "-p", "do the thing"])
    # host command preserved exactly, including its own -p flag and the spaced arg
    assert plan.host_command == ["claude", "-p", "do the thing"]
    # MCP server injected under the `dos` key
    assert plan.mcp_config == {"mcpServers": {"dos": {"command": "dos-mcp"}}}
    # no settings by default (the Stop hook is opt-in)
    assert plan.settings is None
    assert plan.notes == []
    # the final argv = host command, THEN the appended --mcp-config (additive,
    # after — so the host parses its own flags first)
    assert plan.argv[:3] == ["claude", "-p", "do the thing"]
    assert "--mcp-config" in plan.argv
    assert plan.argv.index("--mcp-config") == 3
    # the value is the JSON of the mcp_config object
    val = plan.argv[plan.argv.index("--mcp-config") + 1]
    assert json.loads(val) == plan.mcp_config


def test_leading_separator_is_stripped():
    # argparse.REMAINDER keeps a literal leading `--`; the builder strips one.
    plan = guard.build_guard_plan(["--", "claude", "-p", "x"])
    assert plan.host_command == ["claude", "-p", "x"]
    assert plan.argv[0] == "claude"


def test_no_mcp_injects_nothing():
    plan = guard.build_guard_plan(["claude", "-p", "x"], mount_mcp=False)
    assert plan.mcp_config is None
    assert "--mcp-config" not in plan.argv
    assert plan.argv == ["claude", "-p", "x"]


# ---------------------------------------------------------------------------
# The opt-in Stop hook + its honesty note.
# ---------------------------------------------------------------------------
def test_verify_on_stop_injects_stop_hook_and_notes_unbuilt():
    plan = guard.build_guard_plan(["claude", "-p", "x"], verify_on_stop=True)
    assert plan.settings is not None
    hooks = plan.settings["hooks"]["Stop"]
    assert hooks == [{"hooks": [{"type": "command",
                                 "command": "dos hook stop --workspace ."}]}]
    # `dos hook stop` is now SHIPPED, so the default target carries no caveat note
    assert plan.notes == []
    # the settings ride inside --settings (there is no --hooks flag)
    assert "--settings" in plan.argv
    settings_val = plan.argv[plan.argv.index("--settings") + 1]
    assert json.loads(settings_val) == plan.settings


def test_custom_stop_hook_command_is_honored():
    plan = guard.build_guard_plan(
        ["claude", "-p", "x"],
        verify_on_stop=True,
        stop_hook_command="my-verifier.sh",
    )
    assert plan.settings["hooks"]["Stop"][0]["hooks"][0]["command"] == "my-verifier.sh"
    assert plan.notes == []


# ---------------------------------------------------------------------------
# The claim-prompt + strict-mcp toggles.
# ---------------------------------------------------------------------------
def test_claim_prompt_appends_marker_instruction():
    plan = guard.build_guard_plan(["claude", "-p", "x"], add_claim_prompt=True)
    assert plan.settings is not None
    assert "DOS-CLAIM:" in plan.settings["appendSystemPrompt"]


def test_strict_mcp_adds_exactly_that_flag():
    plan = guard.build_guard_plan(["claude", "-p", "x"], strict_mcp=True)
    assert "--strict-mcp-config" in plan.argv
    # it must come right after the --mcp-config value (it scopes that injection)
    i = plan.argv.index("--mcp-config")
    assert plan.argv[i + 2] == "--strict-mcp-config"


def test_strict_mcp_without_mount_is_noop():
    # strict only makes sense alongside a mount; with --no-mcp it must not appear
    plan = guard.build_guard_plan(
        ["claude", "-p", "x"], mount_mcp=False, strict_mcp=True)
    assert "--strict-mcp-config" not in plan.argv


# ---------------------------------------------------------------------------
# Passthrough integrity — the host's own dash-flags are never eaten.
# ---------------------------------------------------------------------------
def test_host_flags_that_look_like_dos_flags_pass_through():
    # a host arg `--verify-on-stop` after the command must be host's, untouched
    plan = guard.build_guard_plan(
        ["claude", "--verify-on-stop", "--output-format", "json"])
    assert plan.host_command == [
        "claude", "--verify-on-stop", "--output-format", "json"]
    # and it appears before our appended --mcp-config
    assert plan.argv.index("--verify-on-stop") < plan.argv.index("--mcp-config")


# ---------------------------------------------------------------------------
# The one contract error.
# ---------------------------------------------------------------------------
def test_empty_host_command_raises():
    with pytest.raises(ValueError):
        guard.build_guard_plan([])


def test_bare_separator_only_raises():
    # just `--` with nothing after is still empty
    with pytest.raises(ValueError):
        guard.build_guard_plan(["--"])


# ---------------------------------------------------------------------------
# Determinism — same options, byte-identical plan (sortable JSON).
# ---------------------------------------------------------------------------
def test_plan_is_deterministic():
    a = guard.build_guard_plan(["claude", "-p", "x"], verify_on_stop=True,
                               add_claim_prompt=True)
    b = guard.build_guard_plan(["claude", "-p", "x"], verify_on_stop=True,
                               add_claim_prompt=True)
    assert a.to_dict() == b.to_dict()
    # the injected JSON is sort_keys=True so the argv strings match byte-for-byte
    assert a.argv == b.argv


# ---------------------------------------------------------------------------
# CLI wiring — the verb parses and routes (a thin smoke over the parser).
# ---------------------------------------------------------------------------
def test_cli_print_config_routes(capsys):
    from dos import cli
    rc = cli.main(["guard", "--print-config", "--json", "--",
                   "claude", "-p", "hello"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["host_command"] == ["claude", "-p", "hello"]
    assert out["mcp_config"] == {"mcpServers": {"dos": {"command": "dos-mcp"}}}


def test_cli_empty_command_exits_2(capsys):
    from dos import cli
    rc = cli.main(["guard", "--print-config"])
    assert rc == 2
    assert "needs a host command" in capsys.readouterr().err

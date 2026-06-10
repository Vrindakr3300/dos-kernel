"""The agent-facing `interpretation` hint is ONE implementation, two surfaces.

`dos.interpret` holds the next-action gloss ("treat as NOT done; don't trust the
claim") that both agent surfaces attach to a verdict:

  * the MCP tools (`dos_mcp.server`) — always, as an `interpretation` field;
  * the `dos` CLI's opt-in `--explain` flag — `dos verify --explain --json`,
    `dos arbitrate --explain --output json`.

This module pins that they can NEVER DRIFT: for the same verdict, the string the
CLI emits under `--explain` is byte-identical to the string the MCP tool returns,
because both call the same `dos.interpret` function. If someone edits one surface's
wording without the other, this fails. It also pins the byte-faithfulness floor:
WITHOUT `--explain`, the CLI's `--json` output carries NO `interpretation` key, so
no existing pipe consumer is disturbed (the complement of tests/test_render.py).

The MCP-driven assertions skip if the optional `mcp` extra is absent; the pure
`dos.interpret` and CLI-subprocess assertions always run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dos import interpret


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _plain_repo(repo: Path) -> None:
    """A git repo with zero phased-plan surface (mirrors test_mcp_server)."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-m", "init: empty repo, no phased plan")


def _run_cli(repo: Path, verb: str, *args: str) -> subprocess.CompletedProcess:
    """Invoke the `dos` CLI against `repo` via a subprocess.

    Uses `dos.cli.main` through a `python -c` entrypoint so the test exercises the
    real argparse + emission path (not a re-imported function). PYTHONPATH carries
    the `src` tree so the editable package resolves even in a bare checkout.

    NOTE: `--workspace` is now accepted in BOTH positions — globally (before the
    verb) and per-subcommand (after it). This helper passes it AFTER the verb
    (`dos verify --workspace . X Y`), the spelling that has always worked; the
    global spelling (`dos --workspace . verify X Y`) is exercised separately by
    `tests/test_cli_ergonomics.py`.
    """
    env = {
        **_os_environ(),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        # Force the machine path: no TTY, so color never wraps the JSON/hint.
        "NO_COLOR": "1",
        # The CLI writes UTF-8 (its em-dash hint); decode it as UTF-8 here too, so
        # a Windows cp1252 default doesn't mangle `—` into `?` in the captured
        # stdout. (Belt-and-suspenders alongside `encoding="utf-8"` below.)
        "PYTHONIOENCODING": "utf-8",
    }
    return subprocess.run(
        [sys.executable, "-c", "from dos.cli import main; raise SystemExit(main())",
         verb, "--workspace", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", env=env)


def _os_environ() -> dict:
    import os
    return dict(os.environ)


# ---------------------------------------------------------------------------
# dos.interpret — the pure functions read the verdict's own to_dict() fields
# ---------------------------------------------------------------------------
def test_verify_interpretation_three_branches():
    real = interpret.verify({"shipped": True, "source": "grep", "sha": "abc123"})
    assert real.startswith("SHIPPED") and "abc123" in real and "rely on" in real

    honest_no = interpret.verify({"shipped": False, "source": "none"})
    assert honest_no.startswith("NOT shipped") and "Do NOT accept" in honest_no

    checked_no = interpret.verify({"shipped": False, "source": "grep"})
    assert checked_no.startswith("NOT shipped") and "until a" in checked_no


def test_arbitrate_interpretation_go_and_stop():
    go = interpret.arbitrate({"outcome": "acquire", "lane": "api",
                              "auto_picked": False})
    assert go.startswith("GO") and "'api'" in go
    # The GO must also say what arbitrate did NOT do — no lease was journaled —
    # and name the durable verb, so an agent reading the MCP `interpretation`
    # (or an operator reading `--explain`) doesn't believe the grant sticks.
    assert "no lease was journaled" in go
    assert "dos lease-lane acquire --lane api" in go

    go_auto = interpret.arbitrate({"outcome": "acquire", "lane": "docs",
                                   "auto_picked": True})
    assert "auto-picked for you" in go_auto

    stop = interpret.arbitrate({"outcome": "refuse", "free_clusters": ["a", "b"]})
    assert stop.startswith("STOP") and "a, b" in stop

    stop_none = interpret.arbitrate({"outcome": "refuse", "free_clusters": []})
    assert stop_none.startswith("STOP") and "No free lane" in stop_none


def test_check_reason_interpretation_known_and_unknown():
    known = interpret.check_reason({"known": True, "refusal": True})
    assert known.startswith("VALID reason") and "replan" in known

    advisory = interpret.check_reason({"known": True, "refusal": False})
    assert "advisory-only" in advisory

    unknown = interpret.check_reason({"known": False})
    assert unknown.startswith("UNKNOWN reason") and "Do NOT emit" in unknown


def test_gate_interpretation_five_verdicts_plus_unknown():
    """interpret.gate glosses each typed gate verdict into a loop-routing line —
    the prose mirror of `gate_classify.gate_policy`."""
    live = interpret.gate({"verdict": "LIVE"})
    assert live.startswith("LIVE") and "CONTINUE" in live

    drain = interpret.gate({"verdict": "DRAIN"})
    assert drain.startswith("DRAIN") and "STOP" in drain and "drained-twice" in drain

    stale = interpret.gate({"verdict": "STALE-STAMP"})
    assert stale.startswith("STALE-STAMP") and "reconcile" in stale

    blocked = interpret.gate({"verdict": "BLOCKED"})
    assert blocked.startswith("BLOCKED") and "surface" in blocked

    race = interpret.gate({"verdict": "RACE"})
    assert race.startswith("RACE") and "retry once" in race

    # A future verdict the gloss doesn't know reads conservatively, never "LIVE".
    unknown = interpret.gate({"verdict": "WHO-KNOWS"})
    assert "NOT a clean LIVE" in unknown


# ---------------------------------------------------------------------------
# the byte-faithfulness floor — WITHOUT --explain the CLI JSON has no hint
# ---------------------------------------------------------------------------
def test_cli_verify_json_without_explain_has_no_interpretation(tmp_path: Path):
    _plain_repo(tmp_path)
    cp = _run_cli(tmp_path, "verify", "SOMEPLAN", "PH1", "--json")
    assert cp.returncode == 1  # not shipped
    out = json.loads(cp.stdout)
    assert out == {"plan": "SOMEPLAN", "phase": "PH1",
                   "shipped": False, "source": "none"}
    assert "interpretation" not in out  # the floor: opt-in only


def test_cli_arbitrate_json_without_explain_has_no_interpretation(tmp_path: Path):
    _plain_repo(tmp_path)
    cp = _run_cli(tmp_path, "arbitrate", "--lane", "main", "--leases", "[]",
                  "--output", "json")
    assert cp.returncode in (0, 1)
    out = json.loads(cp.stdout)
    assert "interpretation" not in out  # the floor: opt-in only


# ---------------------------------------------------------------------------
# --explain ON: the CLI carries the field, inside the JSON object
# ---------------------------------------------------------------------------
def test_cli_verify_explain_json_adds_interpretation(tmp_path: Path):
    _plain_repo(tmp_path)
    cp = _run_cli(tmp_path, "verify", "SOMEPLAN", "PH1", "--json", "--explain")
    assert cp.returncode == 1
    out = json.loads(cp.stdout)
    # The verdict fields are still all present and unchanged...
    assert out["shipped"] is False and out["source"] == "none"
    # ...plus the interpretation, equal to the pure function on the SAME dict.
    bare = {k: v for k, v in out.items() if k != "interpretation"}
    assert out["interpretation"] == interpret.verify(bare)


def test_cli_verify_explain_text_appends_hint_line(tmp_path: Path):
    _plain_repo(tmp_path)
    cp = _run_cli(tmp_path, "verify", "SOMEPLAN", "PH1", "--explain")
    assert cp.returncode == 1
    lines = [ln for ln in cp.stdout.splitlines() if ln.strip()]
    # First line is the byte-faithful verdict line; last is the interpretation.
    assert lines[0] == "NOT_SHIPPED SOMEPLAN PH1 (via none)"
    assert lines[-1] == interpret.verify(
        {"plan": "SOMEPLAN", "phase": "PH1", "shipped": False, "source": "none"})


# ---------------------------------------------------------------------------
# THE PARITY GUARANTEE — CLI --explain == MCP tool, byte-for-byte
# ---------------------------------------------------------------------------
def test_cli_explain_matches_mcp_tool_interpretation(tmp_path: Path):
    """For the same verdict, `dos verify --explain --json` and the MCP `dos_verify`
    tool return the IDENTICAL interpretation string — the anti-drift guarantee."""
    pytest.importorskip("mcp", reason="dos-mcp needs the optional `mcp` extra")
    from dos_mcp.server import build_server

    _plain_repo(tmp_path)

    # MCP surface: the registered tool callable.
    verify_tool = {t.name: t.fn
                   for t in build_server()._tool_manager.list_tools()}["dos_verify"]
    mcp_out = verify_tool(plan="SOMEPLAN", phase="PH1", workspace=str(tmp_path))

    # CLI surface: --explain --json.
    cp = _run_cli(tmp_path, "verify", "SOMEPLAN", "PH1", "--json", "--explain")
    cli_out = json.loads(cp.stdout)

    # Same verdict fields AND same interpretation — one source of truth.
    assert cli_out["shipped"] == mcp_out["shipped"]
    assert cli_out["source"] == mcp_out["source"]
    assert cli_out["interpretation"] == mcp_out["interpretation"]


# ---------------------------------------------------------------------------
# `dos gate --explain` — the same opt-in hint, on the typed empty-packet gate
# ---------------------------------------------------------------------------
def test_cli_gate_json_without_explain_has_no_interpretation(tmp_path: Path):
    """The byte-faithfulness floor: a plain `dos gate --json` carries no hint."""
    _plain_repo(tmp_path)
    cp = _run_cli(tmp_path, "gate", "--picks-json", "[]", "--json")
    assert cp.returncode == 3  # DRAIN (empty packet)
    out = json.loads(cp.stdout)
    assert out["verdict"] == "DRAIN"
    assert "interpretation" not in out  # opt-in only


def test_cli_gate_explain_json_adds_interpretation(tmp_path: Path):
    """`dos gate --explain --json` carries the hint INSIDE the object, equal to the
    pure `interpret.gate` on the same verdict — and the exit code is unchanged."""
    _plain_repo(tmp_path)
    cp = _run_cli(tmp_path, "gate", "--picks-json", "[]", "--json", "--explain")
    assert cp.returncode == 3  # explain never changes a verb's exit semantics
    out = json.loads(cp.stdout)
    assert out["verdict"] == "DRAIN"
    assert out["interpretation"] == interpret.gate({"verdict": "DRAIN"})


def test_cli_gate_explain_text_appends_hint_line(tmp_path: Path):
    """`dos gate --explain` (text) prints the verdict line, then the gloss line."""
    _plain_repo(tmp_path)
    cp = _run_cli(tmp_path, "gate", "--picks-json", "[]", "--explain")
    assert cp.returncode == 3
    lines = [ln for ln in cp.stdout.splitlines() if ln.strip()]
    assert lines[0].startswith("DRAIN")  # the byte-faithful verdict line
    assert lines[-1] == interpret.gate({"verdict": "DRAIN"})


# ---------------------------------------------------------------------------
# `dos man wedge <ID> --explain` — the safe-to-emit gloss, via the SAME
# interpret.check_reason the MCP `dos_check_reason` tool uses
# ---------------------------------------------------------------------------
def test_cli_man_wedge_explain_appends_check_reason_gloss(tmp_path: Path):
    """`dos man wedge <known> --explain` appends the check_reason gloss; a man page
    is a KNOWN reason, so the gloss is the safe-to-emit (refusal vs advisory) one.

    Asserted against a base reason that ships in every workspace (LANE_DRAINED is
    a TRUE_DRAIN refusal), so this needs no declared dos.toml."""
    _plain_repo(tmp_path)
    cp = _run_cli(tmp_path, "man", "wedge", "LANE_DRAINED", "--explain")
    assert cp.returncode == 0
    expected = interpret.check_reason({"known": True, "refusal": True})
    lines = [ln for ln in cp.stdout.splitlines() if ln.strip()]
    assert lines[-1] == expected
    # The man page proper is still present and unchanged above the gloss.
    assert any(ln.startswith("NAME") and "LANE_DRAINED" in ln for ln in lines)


def test_cli_man_wedge_explain_json_carries_interpretation(tmp_path: Path):
    """`dos man wedge <known> --explain --output json` rides the gloss inside the
    structured fields (the `interpretation` convention), equal to the pure fn."""
    _plain_repo(tmp_path)
    cp = _run_cli(tmp_path, "man", "wedge", "LANE_DRAINED",
                  "--explain", "--output", "json")
    assert cp.returncode == 0
    out = json.loads(cp.stdout)
    assert out["key"] == "LANE_DRAINED"
    assert out["interpretation"] == interpret.check_reason(
        {"known": True, "refusal": out["refusal"]})


def test_cli_man_wedge_without_explain_has_no_interpretation(tmp_path: Path):
    """The floor: a plain `dos man wedge <known> --output json` carries no hint."""
    _plain_repo(tmp_path)
    cp = _run_cli(tmp_path, "man", "wedge", "LANE_DRAINED", "--output", "json")
    assert cp.returncode == 0
    out = json.loads(cp.stdout)
    assert "interpretation" not in out


def test_cli_man_wedge_explain_matches_mcp_check_reason(tmp_path: Path):
    """CROSS-SURFACE parity: for the same known reason, `dos man wedge <ID> --explain`
    and the MCP `dos_check_reason` tool emit the IDENTICAL interpretation string.

    This is the structural guard (the man/check_reason analogue of
    `test_cli_explain_matches_mcp_tool_interpretation`): cmd_man now hands
    `interpret.check_reason` the SAME full dict the MCP tool builds, so if the gloss
    ever branches on `category`/`summary`/etc. the two surfaces still agree. Skips
    without the `mcp` extra."""
    pytest.importorskip("mcp", reason="dos-mcp needs the optional `mcp` extra")
    from dos_mcp.server import build_server

    _plain_repo(tmp_path)
    check_tool = {t.name: t.fn
                  for t in build_server()._tool_manager.list_tools()}["dos_check_reason"]
    mcp_out = check_tool(reason_class="LANE_DRAINED", workspace=str(tmp_path))

    cp = _run_cli(tmp_path, "man", "wedge", "LANE_DRAINED",
                  "--explain", "--output", "json")
    cli_out = json.loads(cp.stdout)
    assert cli_out["interpretation"] == mcp_out["interpretation"]


def test_cli_man_explain_is_harmless_noop_on_list_and_lane(tmp_path: Path):
    """`--explain` is wired ONLY for `man wedge <ID>`. On the list/lane paths it is
    accepted and does nothing (there is no single verdict to gloss) — pinned here so
    a reader knows the no-op is intentional and a future edit can't silently start
    emitting a half-formed gloss there."""
    _plain_repo(tmp_path)
    # man wedge (no id) — the list path.
    lst = _run_cli(tmp_path, "man", "wedge", "--explain")
    assert lst.returncode == 0
    assert "interpretation" not in lst.stdout

    # man lane <id> --output json — never reads --explain; no interpretation key.
    lane = _run_cli(tmp_path, "man", "lane", "main", "--explain", "--output", "json")
    assert lane.returncode == 0
    assert "interpretation" not in json.loads(lane.stdout)

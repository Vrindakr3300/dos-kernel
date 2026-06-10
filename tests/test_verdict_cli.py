"""Modular registry → CLI wiring (docs/86 §2) — the generic dispatcher.

`verdict_cli.attach` builds a subcommand for every registered verb that carries a
CLI adapter, and `verdict_cli.run` is the ONE handler for all of them
(gather → classify → render → exit code). These tests prove the modular path
works END-TO-END against a plain argparse parser + a real temp git repo, with NO
dependency on `cli.py` — i.e. adding a verb needs zero per-verb CLI code, and the
`cli.py` integration is the single `attach(...)` call (deferred until cli.py
settles).
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
from contextlib import redirect_stdout
from pathlib import Path

import dataclasses

import pytest

from dos import verdict_cli, verdicts
from dos.config import default_config, LaneTaxonomy


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _repo_with_diff(repo: Path, touched: list[str]) -> None:
    """A git repo with a base commit, then a second commit touching `touched`."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    for rel in touched:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("change\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "the change under test")


def _cfg_with_lane(repo: Path):
    """A config whose lane-03 owns the effort-03/ subtree (the bench shape)."""
    base = default_config(workspace=repo)
    taxonomy = LaneTaxonomy(
        concurrent=("lane-03",), autopick=("lane-03",), exclusive=(),
        trees={"lane-03": ("effort-03/",)},
    )
    return dataclasses.replace(base, lanes=taxonomy)


def _parser_with_verdicts(cfg):
    """A standalone argparse parser with the verdict verbs attached — NO cli.py."""
    parser = argparse.ArgumentParser(prog="t")
    sub = parser.add_subparsers(dest="cmd", required=True)
    wired = verdict_cli.attach(sub, config_resolver=lambda args: cfg)
    return parser, wired


def test_attach_wires_scope_from_the_registry():
    """`attach` discovers `scope` from the registry — no per-verb code in the
    consumer. (liveness/verify are not yet surfaced via the dispatcher; scope is
    the proof.)"""
    cfg = _cfg_with_lane(Path("."))
    _parser, wired = _parser_with_verdicts(cfg)
    assert "scope" in wired


def test_scope_in_scope_exits_zero(tmp_path):
    """A diff wholly inside the lane's tree → IN_SCOPE, exit 0, through the
    generic dispatcher end-to-end (parse → gather git diff → classify → render)."""
    repo = tmp_path / "repo"
    _repo_with_diff(repo, ["effort-03/mod_1.txt", "effort-03/mod_2.txt"])
    cfg = _cfg_with_lane(repo)
    parser, _ = _parser_with_verdicts(cfg)

    args = parser.parse_args(["scope", "--lane", "lane-03",
                              "--workspace", str(repo), "--output", "json"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = verdict_cli.run(args)
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["verdict"] == "IN_SCOPE"


def test_scope_creep_exits_nonzero(tmp_path):
    """A diff that touches the lane AND spills outside it → SCOPE_CREEP, exit 5 —
    the cross-lane stomp caught through the CLI path, end-to-end."""
    repo = tmp_path / "repo"
    _repo_with_diff(repo, ["effort-03/mod_1.txt", "effort-07/intruder.txt"])
    cfg = _cfg_with_lane(repo)
    parser, _ = _parser_with_verdicts(cfg)

    args = parser.parse_args(["scope", "--lane", "lane-03", "--workspace", str(repo)])
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = verdict_cli.run(args)
    assert code == 5
    assert "SCOPE_CREEP" in buf.getvalue()


def test_scope_wrong_target_exits_six(tmp_path):
    """A diff touching nothing in the lane's tree → WRONG_TARGET, exit 6."""
    repo = tmp_path / "repo"
    _repo_with_diff(repo, ["effort-07/x.txt", "effort-09/y.txt"])
    cfg = _cfg_with_lane(repo)
    parser, _ = _parser_with_verdicts(cfg)

    args = parser.parse_args(["scope", "--lane", "lane-03", "--workspace", str(repo)])
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = verdict_cli.run(args)
    assert code == 6
    assert "WRONG_TARGET" in buf.getvalue()


def test_undeclared_lane_is_generic_in_scope(tmp_path):
    """A lane with no declared tree falls back to the generic `("**/*",)` → every
    diff IN_SCOPE (the no-plan floor reaches the CLI path too)."""
    repo = tmp_path / "repo"
    _repo_with_diff(repo, ["whatever/x.txt"])
    cfg = _cfg_with_lane(repo)
    parser, _ = _parser_with_verdicts(cfg)

    args = parser.parse_args(["scope", "--lane", "nonexistent-lane",
                              "--workspace", str(repo)])
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = verdict_cli.run(args)
    assert code == 0  # IN_SCOPE


def test_adding_a_verb_needs_no_dispatcher_change(tmp_path):
    """The modularity claim, made executable: register a NEW verb with a CLI
    adapter and it is wired by the SAME `attach` with zero dispatcher edits."""
    from dos.scope import classify as scope_classify, ScopeEvidence

    def _add(p):
        p.add_argument("--lane", default="lane-03")

    def _gather(args, cfg):
        return ScopeEvidence(touched_files=frozenset({"effort-03/a.txt"}),
                             lane_tree=("effort-03/",), lane=args.lane)

    verdicts.register(verdicts.VerdictSpec(
        name="probe-verb", classify=scope_classify, summary="probe",
        distrusts="x", add_arguments=_add, gather=_gather,
        exit_codes={"IN_SCOPE": 0}), replace=True)
    try:
        cfg = _cfg_with_lane(tmp_path)
        parser = argparse.ArgumentParser(prog="t")
        sub = parser.add_subparsers(dest="cmd", required=True)
        wired = verdict_cli.attach(sub, config_resolver=lambda a: cfg)
        assert "probe-verb" in wired  # discovered, no dispatcher change
        args = parser.parse_args(["probe-verb", "--workspace", str(tmp_path)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert verdict_cli.run(args) == 0
    finally:
        verdicts._REGISTRY.pop("probe-verb", None)

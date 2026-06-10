"""Tests for the E1 real-policy trajectory miner (docs/206 §5).

These pin the three load-bearing properties: (1) the extractor pairs `git commit`
tool calls with their results by tool_use_id; (2) the git adjudicator labels a real
HEAD sha as landed and a fabricated sha as not — the byte-author != judged-agent
join; (3) the corpus summary splits not-landed into pure-lie/no-op vs the
shape-identical flake. The distillation itself is `verifier.py`'s test; here we only
prove the real-source plumbing emits a sound `TrajectoryStep` corpus.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from .real_trajectory import (
    CommitClaim, GitAdjudicator, build_corpus, claim_to_step,
    corpus_summary, extract_commit_claims,
)


def _write_transcript(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def _bash_commit_call(tid: str, cmd: str = "git commit -m x") -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}}


def _tool_result(tid: str, text: str) -> dict:
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text}]}}


def test_extractor_pairs_commit_call_with_result(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    _write_transcript(f, [
        _bash_commit_call("t1", "cd r && git commit -m a"),
        _tool_result("t1", "[master 9f0008d] a\n 6 files changed, 118 insertions(+)"),
        # a non-commit bash call must be ignored
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t2", "name": "Bash",
             "input": {"command": "git status"}}]}},
        _tool_result("t2", "nothing"),
    ])
    claims = extract_commit_claims(f)
    assert len(claims) == 1
    c = claims[0]
    assert c.claimed_sha == "9f0008d"
    assert c.n_files == 6
    assert c.printed_commit_line is True
    assert c.looked_failed is False


def test_extractor_flags_failed_commit(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    _write_transcript(f, [
        _bash_commit_call("t1"),
        _tool_result("t1", "Exit code 1\nnothing to commit, working tree clean"),
    ])
    c = extract_commit_claims(f)[0]
    assert c.claimed_sha == ""           # no commit line printed
    assert c.printed_commit_line is False
    assert c.looked_failed is True


def test_dry_run_commit_is_not_a_claim(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    _write_transcript(f, [
        _bash_commit_call("t1", "git commit --dry-run"),
        _tool_result("t1", "would commit"),
    ])
    assert extract_commit_claims(f) == []


def _repo_root() -> Path:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("not in a git repo")
    return Path(r.stdout.strip())


def test_adjudicator_labels_real_head_as_landed():
    repo = _repo_root()
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    adj = GitAdjudicator(repo)
    assert adj.is_in_ancestry(head) is True           # HEAD is reachable from a ref
    assert adj.is_in_ancestry("deadbeefdead") is False  # fabricated sha
    assert adj.is_in_ancestry("") is False


def test_adjudicator_caches(monkeypatch):
    repo = _repo_root()
    adj = GitAdjudicator(repo)
    calls = {"n": 0}
    real_exists = adj._exists

    def counting_exists(sha):
        calls["n"] += 1
        return real_exists(sha)
    monkeypatch.setattr(adj, "_exists", counting_exists)
    adj.is_in_ancestry("deadbeefdead")
    adj.is_in_ancestry("deadbeefdead")
    assert calls["n"] == 1                             # second call hits the cache


def test_claim_to_step_label_is_git_not_word():
    repo = _repo_root()
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    adj = GitAdjudicator(repo)
    # a claim that prints a REAL sha -> landed
    landed = claim_to_step(
        CommitClaim("s", 0, "git commit", f"[master {head}] x\n 1 file changed",
                    head, 1, True, False),
        adj, seen_shas=set())
    assert landed.really_committed is True
    assert landed.label == 1
    # a claim that prints a FABRICATED sha + files -> flake (label 0, looks real)
    flake = claim_to_step(
        CommitClaim("s", 1, "git commit", "[master deadbeef] x\n 3 files changed",
                    "deadbeef", 3, True, False),
        adj, seen_shas=set())
    assert flake.really_committed is False            # git says no, despite the word
    assert flake.label == 0
    assert flake.sha_looks_real is True               # shape-identical to a landing
    assert flake.n_files_written == 3


def test_corpus_summary_splits_lie_and_flake(tmp_path: Path):
    repo = _repo_root()
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    f = tmp_path / "s.jsonl"
    _write_transcript(f, [
        _bash_commit_call("t1"),
        _tool_result("t1", f"[master {head}] real\n 2 files changed"),   # landed
        _bash_commit_call("t2"),
        _tool_result("t2", "Exit code 1\nnothing to commit"),            # pure lie/no-op
        _bash_commit_call("t3"),
        _tool_result("t3", "[master deadbeef] x\n 4 files changed"),     # flake
    ])
    # min_bytes 0 so the tiny transcript is not skipped
    steps = build_corpus(tmp_path, repo, min_bytes=0)
    s = corpus_summary(steps)
    assert s["steps"] == 3
    assert s["landed"] == 1
    assert s["pure_lie_or_noop"] == 1
    assert s["flakes_shape_identical"] == 1


def test_build_corpus_skips_tiny_transcripts(tmp_path: Path):
    repo = _repo_root()
    tiny = tmp_path / "tiny.jsonl"
    tiny.write_text('{"type":"user"}', encoding="utf-8")
    assert build_corpus(tmp_path, repo, min_bytes=2000) == []

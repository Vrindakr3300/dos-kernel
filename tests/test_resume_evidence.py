"""docs/107 Phase 3 — the writers + the STEP_VERIFIED mint on the non-forgeable rung (§5).

The load-bearing guarantee: a step the agent merely CLAIMED — or claimed with an
`--allow-empty` commit (the forgeable subject-grep rung §5 names) — can NEVER reach
`STEP_VERIFIED`, so it can never become a resume anchor that skips work that never
happened. Most cases use the injectable `touched_files`/`is_ancestor` hooks (the
`oracle` injection discipline, no git needed); one end-to-end test drives a real
tmp git repo to prove the git-backed defaults agree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dos import config as _config
from dos import intent_ledger as il
from dos import resume as rz
from dos import resume_evidence as re_
from dos.resume import AncestryFacts, Resume


# ==========================================================================
# step_stands_on_nonforgeable_rung — the §5-req-2 predicate (injected).
# ==========================================================================


def test_in_ancestry_and_touches_files_is_a_safe_anchor():
    ok = re_.step_stands_on_nonforgeable_rung(
        "c1", root=".",
        is_ancestor=lambda s: True,
        touched_files=lambda s: {"src/dos/foo.py"},
    )
    assert ok is True


def test_allow_empty_commit_is_never_a_safe_anchor():
    # The commit IS in ancestry (an --allow-empty commit lands fine) but touches
    # NO files — the forgeable case §5 forecloses.
    ok = re_.step_stands_on_nonforgeable_rung(
        "c1", root=".",
        is_ancestor=lambda s: True,
        touched_files=lambda s: set(),   # empty footprint = --allow-empty
    )
    assert ok is False


def test_not_in_ancestry_is_never_a_safe_anchor():
    ok = re_.step_stands_on_nonforgeable_rung(
        "c1", root=".",
        is_ancestor=lambda s: False,     # claimed but never landed
        touched_files=lambda s: {"src/dos/foo.py"},
    )
    assert ok is False


def test_unresolvable_sha_is_failclosed():
    ok = re_.step_stands_on_nonforgeable_rung(
        "c1", root=".",
        is_ancestor=lambda s: True,
        touched_files=lambda s: None,    # could not resolve → fail-closed
    )
    assert ok is False


def test_region_intersection_required_when_declared():
    # The COMPLETE §5 fix (the adversarial-review residual hole): a forged record
    # pointing at a real, in-ancestry commit that touched files OUTSIDE the step's
    # declared region is NOT a safe anchor — the commit isn't the step's work.
    in_region = re_.step_stands_on_nonforgeable_rung(
        "c1", root=".", region=["src/dos/foo.py"],
        is_ancestor=lambda s: True,
        touched_files=lambda s: {"src/dos/foo.py"},   # footprint ∩ region → OK
    )
    assert in_region is True
    out_of_region = re_.step_stands_on_nonforgeable_rung(
        "c1", root=".", region=["src/dos/foo.py"],
        is_ancestor=lambda s: True,
        touched_files=lambda s: {"docs/unrelated.md"},  # real commit, WRONG region
    )
    assert out_of_region is False
    # A glob region intersects a file under it.
    glob_ok = re_.step_stands_on_nonforgeable_rung(
        "c1", root=".", region=["src/dos/**"],
        is_ancestor=lambda s: True,
        touched_files=lambda s: {"src/dos/sub/bar.py"},
    )
    assert glob_ok is True


def test_adjudicate_uses_per_step_regions():
    # End-to-end through the fold: s1's region matches its commit, s2's does not.
    state = il.LedgerState(
        run_id="RID-1", goal="g", declared_steps=("s1", "s2"),
        step_regions={"s1": ("src/a/**",), "s2": ("src/b/**",)},
        claimed={"s1": "c1", "s2": "c2"},
    )
    verified = re_.adjudicate_verified_steps(
        state, root=".",
        is_ancestor=lambda s: True,
        touched_files=lambda s: {"src/a/x.py"} if s == "c1" else {"src/a/y.py"},
        # ^ BOTH commits touch src/a; only s1's region is src/a, so s2 (region src/b)
        #   is rejected — its commit touched files outside its declared region.
    )
    assert verified == frozenset({"s1"})


# ==========================================================================
# verify_step — the mint: appends a STEP_VERIFIED only when safe.
# ==========================================================================


def test_verify_step_mints_on_a_real_commit(tmp_path: Path):
    cfg = _config.default_config(tmp_path)
    p = tmp_path / "intent.jsonl"
    il.append("RID-1", il.intent_entry(goal="g", declared_steps=["s1"]), path=p)
    il.append("RID-1", il.step_claimed_entry("s1", "c1"), path=p)
    minted = re_.verify_step(
        "RID-1", "s1", "c1", cfg=cfg, path=p,
        is_ancestor=lambda s: True,
        touched_files=lambda s: {"src/dos/foo.py"},
    )
    assert minted is not None
    assert minted["op"] == "STEP_VERIFIED"
    assert minted["via"] == "file-path"
    # And it actually landed in the ledger → replay sees s1 as verified.
    state = il.replay(il.read_all(path=p))
    assert "s1" in state.verified


def test_verify_step_refuses_an_allow_empty_step(tmp_path: Path):
    cfg = _config.default_config(tmp_path)
    p = tmp_path / "intent.jsonl"
    il.append("RID-1", il.intent_entry(goal="g", declared_steps=["s1"]), path=p)
    il.append("RID-1", il.step_claimed_entry("s1", "empty-commit"), path=p)
    minted = re_.verify_step(
        "RID-1", "s1", "empty-commit", cfg=cfg, path=p,
        is_ancestor=lambda s: True,
        touched_files=lambda s: set(),   # --allow-empty
    )
    assert minted is None
    # NOTHING was appended — the ledger still has no STEP_VERIFIED, so s1 stays in
    # the residual (the forged step is never minted into a belief).
    state = il.replay(il.read_all(path=p))
    assert "s1" not in state.verified
    ops = [e["op"] for e in il.read_all(path=p)]
    assert "STEP_VERIFIED" not in ops


# ==========================================================================
# gather_ancestry — the boundary evidence-gather (injected).
# ==========================================================================


def test_gather_ancestry_collects_claimed_verified_and_start(tmp_path: Path):
    cfg = _config.default_config(tmp_path)
    state = il.LedgerState(
        run_id="RID-1", goal="g", start_sha="START",
        declared_steps=("s1", "s2"),
        claimed={"s1": "c1", "s2": "c2"},
        verified={"s1": il.VerifiedStep("s1", "c1", via="file-path")},
    )
    # Only c1 + START are in ancestry; c2 (claimed, never landed) is not.
    anc = re_.gather_ancestry(
        state, cfg=cfg,
        is_ancestor=lambda s: s in {"c1", "START"},
    )
    assert anc.contains("c1")
    assert anc.contains("START")
    assert not anc.contains("c2")


# ==========================================================================
# End-to-end against a REAL tmp git repo — the git-backed defaults agree.
# ==========================================================================


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def _rev(cwd) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(cwd),
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git not available",
)
def test_end_to_end_real_repo_mints_real_refuses_empty(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(["add", "a.txt"], repo)
    _git(["commit", "-q", "-m", "real: add a.txt"], repo)
    real_sha = _rev(repo)
    # An --allow-empty commit whose SUBJECT names the step (the forgeable attack).
    _git(["commit", "-q", "--allow-empty", "-m", "step s2 done"], repo)
    empty_sha = _rev(repo)

    cfg = _config.default_config(repo)
    # The REAL commit (touches a.txt, in ancestry) → a safe anchor.
    assert re_.step_stands_on_nonforgeable_rung(real_sha, root=repo) is True
    # The --allow-empty commit (in ancestry, touches NOTHING) → NOT a safe anchor.
    assert re_.step_stands_on_nonforgeable_rung(empty_sha, root=repo) is False
    # A bogus sha (not in ancestry) → NOT a safe anchor.
    assert re_.step_stands_on_nonforgeable_rung("0" * 40, root=repo) is False

    # And the full resume loop over the real repo: s1 (real) verifies, s2 (forged
    # --allow-empty) does NOT, so the resume keeps s2 in the residual.
    p = repo / "intent.jsonl"
    il.append("RID-E", il.intent_entry(goal="g", start_sha=real_sha,
                                       declared_steps=["s1", "s2"]), path=p)
    il.append("RID-E", il.step_claimed_entry("s1", real_sha), path=p)
    il.append("RID-E", il.step_claimed_entry("s2", empty_sha), path=p)
    assert re_.verify_step("RID-E", "s1", real_sha, cfg=cfg, path=p) is not None
    assert re_.verify_step("RID-E", "s2", empty_sha, cfg=cfg, path=p) is None

    state = il.replay(il.read_all(path=p))
    anc = re_.gather_ancestry(state, cfg=cfg)
    plan = rz.resume_plan(state, anc)
    assert plan.verdict is Resume.RESUMABLE
    assert plan.verified == ("s1",)
    assert "s2" in plan.residual           # the forged step must be redone
    assert plan.resume_sha == state.verified["s1"].sha

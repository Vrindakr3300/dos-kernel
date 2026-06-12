"""Contract tests for `dos.drivers.nemo_action` (issue #51).

The action function offline against a real tmp git repo — the issue's
done-condition rows (witnessed claim accepted, forged claim refused) — plus
the action-metadata surface a rails config loader reads, with a lockstep
slice against the REAL ``nemoguardrails`` decorator when installed (the
structural-twin discipline: the hand-set ``action_meta`` must match the
genuine article's, byte for byte).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from dos.drivers._effect_gate import CommitClaim, FileClaim
from dos.drivers.nemo_action import make_dos_effect_check


def _nemo_available() -> bool:
    try:
        from nemoguardrails.actions import action  # noqa: F401
        return True
    except ImportError:
        return False


needs_nemo = pytest.mark.skipif(
    not _nemo_available(),
    reason="real host package required: pip install nemoguardrails",
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    ).stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "ws"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    (r / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(r, "add", "seed.txt")
    _git(r, "commit", "-q", "-m", "seed")
    return r


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# The done-condition rows: forged claim refused, witnessed claim accepted.
# ---------------------------------------------------------------------------


def test_forged_claim_is_refused(repo: Path) -> None:
    check = make_dos_effect_check(str(repo), expect=[CommitClaim()])
    verdict = _run(check(claim_text="done! committed the fix."))
    assert verdict["tripped"] is True
    assert verdict["outcome"] == "TRIPPED"
    assert "do the work" in verdict["reason"]


def test_witnessed_claim_is_accepted(repo: Path) -> None:
    check = make_dos_effect_check(str(repo), expect=[CommitClaim()])
    (repo / "fix.txt").write_text("f\n", encoding="utf-8")
    _git(repo, "add", "fix.txt")
    _git(repo, "commit", "-q", "-m", "land the fix")
    verdict = _run(check(claim_text="done! committed the fix."))
    assert verdict["tripped"] is False
    assert verdict["outcome"] == "CLEAR"


def test_abstain_on_unreachable_witness(tmp_path: Path) -> None:
    bare = tmp_path / "no-repo"
    bare.mkdir()
    check = make_dos_effect_check(str(bare), expect=[CommitClaim()])
    verdict = _run(check(claim_text="done"))
    assert verdict["tripped"] is False           # advisory: never a fabricated trip
    assert verdict["outcome"] == "ABSTAINED"


# ---------------------------------------------------------------------------
# The context fallback — the conventional output-rail subject.
# ---------------------------------------------------------------------------


def test_claim_text_falls_back_to_context_bot_message(repo: Path) -> None:
    check = make_dos_effect_check(str(repo), expect=[FileClaim("missing.md")])
    verdict = _run(check(context={"bot_message": "wrote missing.md, all done"}))
    assert verdict["tripped"] is True
    assert verdict["rows"][0]["narrated"] == "wrote missing.md, all done"


# ---------------------------------------------------------------------------
# The action-metadata surface a rails loader reads.
# ---------------------------------------------------------------------------


def test_action_meta_attached_with_default_and_custom_name(repo: Path) -> None:
    check = make_dos_effect_check(str(repo))
    assert check.action_meta["name"] == "dos_effect_check"
    named = make_dos_effect_check(str(repo), name="dos_gate")
    assert named.action_meta["name"] == "dos_gate"
    assert check.action_meta["is_system_action"] is False


@needs_nemo
def test_action_meta_lockstep_with_real_decorator(repo: Path) -> None:
    # The hand-set metadata (used when nemoguardrails is absent) must carry
    # exactly the keys the real decorator sets — a drift here is invisible
    # until a rails loader crashes on it.
    from nemoguardrails.actions import action

    @action(name="reference")
    async def reference() -> None:  # pragma: no cover - metadata carrier
        return None

    ours = make_dos_effect_check(str(repo))
    assert set(ours.action_meta.keys()) == set(reference.action_meta.keys())

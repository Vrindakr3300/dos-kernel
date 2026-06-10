"""Pin the `examples/demo/verify_demo` money-moment against the real `dos` CLI.

`examples/demo/verify_demo.sh` (+ its `.ps1` twin) is the runnable on-ramp the
README and `examples/demo/verify_visual.html` point a newcomer at — and the demo
header promises *"every line in the walkthrough is verbatim output of this
script."* But the script is package-DATA that nothing imports, so until now
nothing in the suite caught it if a kernel change broke the exact contract the
demo depends on: a renamed verb, a changed `SHIPPED`/`NOT_SHIPPED` headline, or a
flipped exit code would silently turn the newcomer's first experience into a
contradiction (the page says one thing, their terminal says another).

This test replays the demo's command sequence — `dos init` → commit `AUTH1:` →
`dos verify AUTH AUTH1` → `dos verify AUTH AUTH2` — THROUGH the real `dos.cli`
subprocess path and asserts the four load-bearing facts the demo renders:

  * `AUTH1` verifies **SHIPPED** with exit **0** and the `via grep-subject` rung
    (the commit-subject stamp the demo just made);
  * `AUTH2` verifies **NOT_SHIPPED** with exit **1** and the `via none` rung
    (nothing landed for it).

It is the same "a claim isn't shipped until a witness pins it" discipline that
`test_hermes_integration_example.py` applies to the Hermes example — here aimed at
the demo a first-time user runs first. If the CLI contract drifts, this reddens
instead of the demo quietly lying to a stranger.

The test does NOT shell `bash`/`pwsh` (neither is guaranteed in CI); it drives the
identical command *contract* in Python, which is what the demo scripts are a thin
wrapper over. The companion `test_docs_version_drift.py` pins the same docs' version
banner; together they keep the newcomer surface honest.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def _env() -> dict:
    return {
        **os.environ,
        "PYTHONPATH": str(_SRC_DIR),
        "NO_COLOR": "1",
        "PYTHONIOENCODING": "utf-8",
    }


def _cli(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", "from dos.cli import main; raise SystemExit(main())", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_env(),
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def demo_repo(tmp_path: Path) -> Path:
    """Reproduce exactly what `verify_demo.sh` builds: a fresh git repo scaffolded
    by `dos init`, with a single `AUTH1:`-subject commit and nothing for `AUTH2`."""
    repo = tmp_path / "demo"
    repo.mkdir()

    init = _cli("init", str(repo))
    assert init.returncode == 0, init.stderr

    _git(repo, "init")
    _git(repo, "config", "user.email", "demo@example.com")
    _git(repo, "config", "user.name", "Demo")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "login.py").write_text("def login(): pass\n", encoding="ascii")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "AUTH1: ship the login endpoint")
    return repo


def test_verify_demo_auth1_is_shipped(demo_repo: Path) -> None:
    """The first half of the contrast: `AUTH1` shipped, exit 0, `via grep-subject`."""
    cp = _cli("verify", "--workspace", str(demo_repo), "AUTH", "AUTH1")
    assert cp.returncode == 0, f"expected SHIPPED exit 0, got {cp.returncode}: {cp.stdout}{cp.stderr}"
    assert "SHIPPED" in cp.stdout
    assert "AUTH AUTH1" in cp.stdout
    # The demo's whole teaching point is the *rung*: the ship was found in a commit
    # subject, not taken on anyone's word. If that tag changes, the visual's
    # annotation is wrong, so pin it.
    assert "via grep-subject" in cp.stdout
    # And it must be SHIPPED, not the NOT_SHIPPED negative.
    assert "NOT_SHIPPED" not in cp.stdout


def test_verify_demo_auth2_is_not_shipped(demo_repo: Path) -> None:
    """The second half: `AUTH2` — claimed, never landed — is NOT_SHIPPED, exit 1, `via none`."""
    cp = _cli("verify", "--workspace", str(demo_repo), "AUTH", "AUTH2")
    assert cp.returncode == 1, f"expected NOT_SHIPPED exit 1, got {cp.returncode}: {cp.stdout}{cp.stderr}"
    assert "NOT_SHIPPED" in cp.stdout
    assert "AUTH AUTH2" in cp.stdout
    # `via none` is the demo's punchline — DOS looked everywhere it knows and found
    # nothing. It is what makes "the agent can claim it all day" land.
    assert "via none" in cp.stdout


def test_verify_demo_scripts_exist() -> None:
    """Guard the guard: the demo scripts this test stands in for must still exist.

    If a refactor deletes or renames `verify_demo.{sh,ps1}`, this Python contract
    test would keep passing while protecting an artifact that no longer ships —
    so fail loudly and make someone reconcile the two.
    """
    demo_dir = _SRC_DIR.parent / "examples" / "demo"
    for name in ("verify_demo.sh", "verify_demo.ps1"):
        assert (demo_dir / name).is_file(), (
            f"{name} is missing — this test pins its CLI contract; update or remove "
            f"this test if the demo was intentionally retired."
        )

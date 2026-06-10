"""Shared fixture for the runnable fleet-framework recipes.

Builds the cookbook's throwaway repo — one real ``AUTH1: …`` commit — and
returns the `SubstrateConfig` every recipe verifies/arbitrates against. This
module is pure stdlib + `dos`; each framework recipe imports its own framework,
never through here, so a missing framework only fails the recipe that needs it.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import dos
from dos import arbiter, oracle


def make_demo_repo(root: Path | str | None = None) -> dos.SubstrateConfig:
    """A throwaway git repo where AUTH1 verifiably shipped and AUTH2 did not.

    One commit, subject ``AUTH1: ship the login endpoint`` (the canonical
    caught-lie example — `dos._demo_story`). The generic stamp grammar
    `dos.default_config` carries reads that subject as the phase's ship stamp,
    so ``oracle.is_shipped("AUTH", "AUTH1", cfg=...)`` answers SHIPPED via the
    grep-subject rung — from git ancestry alone, no plan, no registry. AUTH2
    has no artifact anywhere, so every claim about it is a lie the recipes
    must refuse to believe.
    """
    repo = Path(root) if root is not None else Path(tempfile.mkdtemp(prefix="dos_fleet_demo_"))
    repo.mkdir(parents=True, exist_ok=True)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "fleet@example.com")
    git("config", "user.name", "fleet-demo")
    (repo / "auth.py").write_text("def login(): ...\n", encoding="utf-8")
    git("add", "auth.py")
    git("commit", "-q", "-m", "AUTH1: ship the login endpoint")
    return dos.default_config(repo)


# ---- Recipe 0's two functions — everything else relocates these ------------

def verified_done(plan: str, phase: str, cfg: dos.SubstrateConfig) -> bool:
    """An agent SAID it shipped (plan, phase). Ask git, not the agent."""
    return oracle.is_shipped(plan, phase, cfg=cfg).shipped


def admit(lane: str, tree: list[str], live_leases: list[dict],
          cfg: dos.SubstrateConfig):
    """May a worker start on this file region without colliding?"""
    return arbiter.arbitrate(
        requested_lane=lane, requested_kind="cluster",
        requested_tree=tree, live_leases=live_leases, config=cfg,
    )

"""dos.verified — the in-process gate over the truth syscall (issue #75).

The contract being pinned: a function (or `with` body) gated by
``verified(plan, phase)`` runs ONLY when `oracle.is_shipped` confirms the
claim from git evidence; otherwise a typed `NotShippedError` carrying the
full `ShipVerdict` is raised and the body never executes. Enforcement is in
the user's process (the raise) — the kernel stays advisory.

Covers the issue's done-condition: decorator + context-manager forms, the
typed exception carrying the verdict, and workspace/config injection
(explicit arg over ambient default). Plus the load-bearing timing property:
adjudication happens at CALL time, so a gate decorated before its phase
ships opens the moment the evidence lands.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import dos
from dos import config as dos_config
from dos.config import default_config
from dos.verified import NotShippedError, verified


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _repo_with_ship(repo: Path) -> None:
    """A plain git repo where (RS, RS1) verifiably shipped and nothing else did."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-m", "docs/RS: RS1 — ship the surfacer")


# ---------------------------------------------------------------------------
# Decorator form
# ---------------------------------------------------------------------------


def test_decorator_runs_body_when_shipped(tmp_path: Path):
    _repo_with_ship(tmp_path)
    cfg = default_config(tmp_path)

    @verified("RS", "RS1", cfg=cfg)
    def release() -> str:
        return "released"

    assert release() == "released"


def test_decorator_refuses_unshipped_and_never_runs_body(tmp_path: Path):
    _repo_with_ship(tmp_path)
    cfg = default_config(tmp_path)
    ran = []

    @verified("RS", "RS9", cfg=cfg)
    def release() -> None:
        ran.append(True)

    with pytest.raises(NotShippedError) as exc_info:
        release()
    assert ran == []  # the gated body never executed

    # The typed exception carries the FULL verdict, not just a message.
    v = exc_info.value.verdict
    assert v.plan == "RS"
    assert v.phase == "RS9"
    assert v.shipped is False
    assert v.source == "none"
    assert "NOT_SHIPPED" in str(exc_info.value)
    assert "(via none)" in str(exc_info.value)


def test_decorator_adjudicates_at_call_time_not_decoration_time(tmp_path: Path):
    """A gate built BEFORE its phase ships opens once the evidence lands."""
    _repo_with_ship(tmp_path)
    cfg = default_config(tmp_path)

    @verified("RS", "RS2", cfg=cfg)
    def follow_up() -> str:
        return "ran"

    with pytest.raises(NotShippedError):
        follow_up()  # nothing in git yet

    _git(tmp_path, "commit", "--allow-empty", "-m", "docs/RS: RS2 — ship the follow-up")
    assert follow_up() == "ran"  # same gate, fresh evidence, no rebuild


def test_decorator_preserves_function_identity_and_exposes_gate(tmp_path: Path):
    _repo_with_ship(tmp_path)
    cfg = default_config(tmp_path)

    @verified("RS", "RS1", cfg=cfg)
    def release() -> None:
        """Release the thing."""

    assert release.__name__ == "release"
    assert release.__doc__ == "Release the thing."
    gate = release.__dos_verified__
    assert (gate.plan, gate.phase) == ("RS", "RS1")


# ---------------------------------------------------------------------------
# Context-manager form
# ---------------------------------------------------------------------------


def test_context_manager_yields_verdict_when_shipped(tmp_path: Path):
    _repo_with_ship(tmp_path)
    cfg = default_config(tmp_path)

    with verified("RS", "RS1", cfg=cfg) as v:
        assert v.shipped is True
        assert v.source == "grep-subject"  # the git-log SUBJECT rung answered


def test_context_manager_refuses_unshipped_before_body(tmp_path: Path):
    _repo_with_ship(tmp_path)
    cfg = default_config(tmp_path)
    entered = []

    with pytest.raises(NotShippedError):
        with verified("RS", "RS9", cfg=cfg):
            entered.append(True)
    assert entered == []


# ---------------------------------------------------------------------------
# Config injection — explicit arg over ambient default
# ---------------------------------------------------------------------------


def test_explicit_cfg_wins_over_ambient_active(tmp_path: Path):
    """A gate holding an explicit cfg ignores the process-active config."""
    shipped_repo = tmp_path / "shipped"
    bare_repo = tmp_path / "bare"
    _repo_with_ship(shipped_repo)
    bare_repo.mkdir()
    _git(bare_repo, "init")
    _git(bare_repo, "config", "user.email", "t@t")
    _git(bare_repo, "config", "user.name", "t")
    _git(bare_repo, "commit", "--allow-empty", "-m", "init: nothing shipped here")

    prev = dos_config.active()
    try:
        dos_config.set_active(default_config(bare_repo))  # ambient says NOT shipped
        with verified("RS", "RS1", cfg=default_config(shipped_repo)) as v:
            assert v.shipped is True  # the explicit cfg answered, not the ambient
    finally:
        dos_config.set_active(prev)


def test_ambient_active_config_is_resolved_at_check_time(tmp_path: Path):
    """With no cfg/workspace, the gate reads `config.active()` per check —
    a `set_active` AFTER the gate was built is honored."""
    _repo_with_ship(tmp_path)
    gate = verified("RS", "RS1")  # built before the active config points anywhere useful

    prev = dos_config.active()
    try:
        dos_config.set_active(default_config(tmp_path))
        assert gate.check().shipped is True
    finally:
        dos_config.set_active(prev)


def test_workspace_path_injection(tmp_path: Path):
    """`workspace=` does the same dos.toml readback the CLI does."""
    _repo_with_ship(tmp_path)

    with verified("RS", "RS1", workspace=tmp_path) as v:
        assert v.shipped is True

    with pytest.raises(NotShippedError):
        with verified("RS", "RS9", workspace=str(tmp_path)):
            pass  # pragma: no cover — must not be reached


def test_cfg_and_workspace_together_is_a_type_error(tmp_path: Path):
    with pytest.raises(TypeError):
        verified("RS", "RS1", cfg=default_config(tmp_path), workspace=tmp_path)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_package_exports_the_callable_not_the_module():
    """`from dos import verified` yields the decorator/CM (the issue-#75
    surface) — the package attribute is the callable, not the submodule."""
    assert dos.verified is verified
    assert callable(dos.verified)
    assert dos.NotShippedError is NotShippedError
    assert "verified" in dos.__all__
    assert "NotShippedError" in dos.__all__

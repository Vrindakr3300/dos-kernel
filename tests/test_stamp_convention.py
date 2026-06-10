"""The ship-stamp convention is per-workspace DATA — verify() honors a declared
`[stamp]` grammar (SCV), **generic by default so it works out of the box**.

The truth syscall's grep rung used to hardcode the *reference userland app's*
commit-subject grammar (`docs|go|agents|job_search|scripts` dir prefixes), so a foreign repo
that stamps ships as a bare `<SERIES>: <PHASE>` (no dir prefix) resolved to
`NOT_SHIPPED (source=none)` even though the subject names the phase. The SCV seam
lifts that grammar into `dos.stamp.StampConvention` on `SubstrateConfig.stamp`,
declarable in a workspace's `dos.toml` `[stamp]` table.

The default was originally job-strict ("loosen knowingly"), but that made every
foreign repo resolve its real ships `via none` until it hand-wrote a `dos.toml`
— the F9 friction. The default now follows the lane/path asymmetry instead: the
*generic* config (`default_config`, the no-`--job` path) carries the
**generic** grammar, so a bare `<SERIES>: <PHASE>` / `<slug> Phase <N>:` subject
verifies from git history with **zero config**. The reference userland app is
unaffected: it consumes `job_config`, which keeps the strict grammar + job's bookkeeping
guards. Generic is not a free-for-all — it retains the universal release-bundle
and bulk-snapshot guards, and a real ship subject must still look like a direct
attribution (a `docs/_plans: AUTH2 …` bookkeeping commit does NOT false-ship).

This test pins the two ends of that seam together:

  * **generic by default** — a workspace with NO `[stamp]` table (the generic
    config) recognises a bare `<SERIES>:` subject as a ship, so `verify` works
    out of the box against a foreign repo's convention.
  * **strict by opt-in** — a workspace that opts into the job grammar (the
    `job_config` base, i.e. `--job`, or a `[stamp] subject_dirs=[…]` declaring
    real dirs) requires the dir prefix, so the strict grammar is still reachable
    for a host that wants it.

Both the library (`oracle.is_shipped(cfg=…)`) and the real CLI (`dos verify`,
which marshals the convention across the grep-rung subprocess boundary) are
driven, so a regression in either the `phase_shipped` wire-through or the
`cli._apply_workspace` `[stamp]` readback is caught.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

from dos import oracle
from dos.config import default_config, job_config
from dos.stamp import GENERIC_STAMP_CONVENTION, JOB_STAMP_CONVENTION


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _repo_with_generic_ship(repo: Path) -> None:
    """A plain git repo whose ship is stamped the GENERIC way: `<SERIES>: <PHASE>`.

    No dir prefix (`docs/`…), no plan doc, no registry — the shape an external
    repo that never heard of the job grammar would use.
    """
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-m", "init: empty repo")
    _git(repo, "commit", "--allow-empty", "-m", "AUTH: AUTH2 — ship token refresh")


def _write_toml(repo: Path, body: str) -> None:
    (repo / "dos.toml").write_text(body, encoding="utf-8")


# --- library path: the convention rides on cfg.stamp ------------------------


def test_library_generic_default_verifies_bare_series_subject(tmp_path: Path):
    """The DEFAULT (generic) config verifies a bare `<SERIES>: <PHASE>` from git.

    `default_config` carries `GENERIC_STAMP_CONVENTION`, so a prefix-less subject
    (`AUTH: AUTH2`) is a direct-ship attribution out of the box — no `dos.toml`,
    no plan doc, no registry. This is the F9 contract: verify works against a
    foreign repo's convention by default.
    """
    _repo_with_generic_ship(tmp_path)
    cfg = default_config(tmp_path)  # cfg.stamp defaults to GENERIC_STAMP_CONVENTION

    assert cfg.stamp is GENERIC_STAMP_CONVENTION  # the default flipped (F9)
    v = oracle.is_shipped("AUTH", "AUTH2", cfg=cfg)
    assert v.shipped is True
    # `grep-subject` (docs/118): the git-log SUBJECT rung under the generic grammar.
    assert v.source == "grep-subject"


def test_library_job_config_keeps_strict_grammar(tmp_path: Path):
    """Opting into the job policy (`job_config`) keeps the strict grammar.

    The strict, dir-prefixed grammar is still reachable — it is just no longer
    the silent default. A repo that consumes `job_config` (the `--job` path, and
    `job` itself) requires the `docs/AUTH:` dir prefix, so a bare `AUTH: AUTH2`
    is NOT a ship under it. This pins that the F9 default-flip did not delete the
    strict grammar, only demote it from default to opt-in.
    """
    _repo_with_generic_ship(tmp_path)
    cfg = job_config(tmp_path)

    assert cfg.stamp is JOB_STAMP_CONVENTION
    v = oracle.is_shipped("AUTH", "AUTH2", cfg=cfg)
    assert v.shipped is False
    assert v.source == "none"


def test_library_generic_convention_verifies_bare_series_subject(tmp_path: Path):
    """Declaring the generic convention makes the same subject verify from git."""
    _repo_with_generic_ship(tmp_path)
    cfg = default_config(tmp_path)
    cfg = dataclasses.replace(cfg, stamp=GENERIC_STAMP_CONVENTION)

    v = oracle.is_shipped("AUTH", "AUTH2", cfg=cfg)
    assert v.shipped is True
    # `grep-subject` (docs/118): the git-log SUBJECT rung under the new grammar.
    assert v.source == "grep-subject"


def test_library_generic_convention_no_false_positive(tmp_path: Path):
    """A phase that never shipped stays NOT-shipped even under the loose grammar."""
    _repo_with_generic_ship(tmp_path)
    cfg = dataclasses.replace(default_config(tmp_path), stamp=GENERIC_STAMP_CONVENTION)

    v = oracle.is_shipped("AUTH", "AUTH9", cfg=cfg)
    assert v.shipped is False


# --- the batch wire protocol (F7): a multi-word phase must survive ----------


def test_parse_batch_line_tab_preserves_spaces():
    """Tab-delimited batch lines keep spaces in BOTH series and phase (F7).

    The programmatic producer (`oracle.default_grep_fallback_batch`) tab-joins
    the fields; `_parse_batch_line` must return them verbatim so a phase like
    `Phase 4` — or a series like `blktrace auto-install` — is not truncated. The
    old `split(None, 2)` is what dropped `"Phase 4"` to `"Phase"`.
    """
    from dos.phase_shipped import _parse_batch_line

    assert _parse_batch_line("hybrid-cache-type\tPhase 4") == (
        "hybrid-cache-type", "Phase 4", None)
    assert _parse_batch_line("blktrace auto-install\tPhase 1") == (
        "blktrace auto-install", "Phase 1", None)
    # A 3rd tab field is the plan doc; a trailing empty doc field collapses to None.
    assert _parse_batch_line("AUTH\tAUTH2\tdocs/x-plan.md") == (
        "AUTH", "AUTH2", "docs/x-plan.md")
    assert _parse_batch_line("AUTH\tAUTH2\t") == ("AUTH", "AUTH2", None)


def test_parse_batch_line_whitespace_legacy():
    """The legacy whitespace form (manual CLI use) is unchanged.

    A human running `python -m dos.phase_shipped --batch` and typing
    `RS RS4 docs/x.md` still splits on whitespace — multi-word ids were never
    expressible in that form, and aren't now; the producer emits tabs for those.
    """
    from dos.phase_shipped import _parse_batch_line

    assert _parse_batch_line("RS RS4") == ("RS", "RS4", None)
    assert _parse_batch_line("RS RS4 docs/x.md") == ("RS", "RS4", "docs/x.md")
    assert _parse_batch_line("") == ("", "", None)
    assert _parse_batch_line("solo") == ("", "", None)


# --- CLI path: dos.toml [stamp] readback + subprocess marshalling -----------


def _cli_verify(repo: Path, plan: str, phase: str, *extra: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "dos.cli", "verify",
         "--workspace", str(repo), plan, phase, "--json", *extra],
        capture_output=True, text=True,
    )
    assert proc.stdout, proc.stderr
    return json.loads(proc.stdout)


def test_cli_generic_default_without_stamp_table(tmp_path: Path):
    """`dos verify` with no `[stamp]` table verifies the bare-series ship (F9).

    Out of the box — no `dos.toml` at all — the CLI resolves a generic-stamped
    repo's ship from git history. This is the headline F9 behavior the benchmark
    repo needs.
    """
    _repo_with_generic_ship(tmp_path)
    payload = _cli_verify(tmp_path, "AUTH", "AUTH2")
    assert payload["shipped"] is True, payload
    # `grep-subject` (docs/118): the bare-series subject ship is the forgeable rung.
    assert payload["source"] == "grep-subject"


def test_cli_job_flag_keeps_strict_grammar(tmp_path: Path):
    """`dos verify --job` opts into the strict grammar, so the bare ship misses.

    The strict grammar stays reachable on the CLI via `--job` (the job-policy
    opt-in). Under it, the prefix-less `AUTH: AUTH2` is not a direct ship.
    """
    _repo_with_generic_ship(tmp_path)
    payload = _cli_verify(tmp_path, "AUTH", "AUTH2", "--job")
    assert payload["shipped"] is False, payload
    assert payload["source"] == "none"


def test_cli_reads_back_declared_stamp_table(tmp_path: Path):
    """A declared `[stamp] subject_dirs=[]` makes `dos verify` find the git ship.

    This is the end-to-end SCV North Star: the CLI reads `[stamp]` out of
    `dos.toml` (`_apply_workspace`) and marshals it through the grep-rung
    subprocess, so a foreign repo's commit convention is honored.
    """
    _repo_with_generic_ship(tmp_path)
    _write_toml(tmp_path, '[stamp]\nstyle = "grep"\nsubject_dirs = []\n')
    payload = _cli_verify(tmp_path, "AUTH", "AUTH2")
    assert payload["shipped"] is True, payload
    # `grep-subject` (docs/118): the declared-grammar subject ship, graded.
    assert payload["source"] == "grep-subject"


def test_cli_malformed_stamp_table_warns_and_falls_back(tmp_path: Path):
    """A present-but-malformed `[stamp]` table warns, never crashes the command.

    The contract under test is *warn-and-fall-back-to-base*, not a specific ship
    outcome: a broken `[stamp]` must not crash a `verify` (it produces a verdict
    and a stderr warning). The base it falls back to is now the generic
    convention (F9), so the fallen-back verdict ships the bare-series subject —
    the point is simply that the command survived the malformed table.
    """
    _repo_with_generic_ship(tmp_path)
    _write_toml(tmp_path, "[stamp]\nsubject_dirs = 42\n")
    proc = subprocess.run(
        [sys.executable, "-m", "dos.cli", "verify",
         "--workspace", str(tmp_path), "AUTH", "AUTH2", "--json"],
        capture_output=True, text=True,
    )
    # The command still produced a verdict and warned on stderr (never crashed).
    assert "malformed [stamp]" in proc.stderr
    payload = json.loads(proc.stdout)
    # Fell back to the base (generic) convention → the bare-series ship verifies.
    assert payload["shipped"] is True, (proc.stdout, proc.stderr)
    assert proc.returncode == 0  # exit 0 = shipped, under the generic fallback

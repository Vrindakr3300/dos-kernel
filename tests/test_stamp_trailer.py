"""docs/289 — trailer-form ship stamps: `(<PLAN> <PHASE>)` at the END of a subject.

The Conventional-Commits shape (`feat(pypi): … (docs/286 Phase 3)`) carries the
plan/phase as a parenthesized trailer, which no start-anchored grammar can see —
this repo's own recent phases resolved `via none` while the commit subject
literally named them. The fix is a per-convention OPT-IN (`[stamp]
trailer_stamp = true`); these tests pin:

  * the flag is data (defaults off everywhere; TOML-declared; dict round-trip
    across the grep-rung subprocess boundary);
  * the matcher recognizes exactly the three documented spellings, end-anchored,
    and refuses everything the start anchor used to refuse (mid-subject parens,
    prose ids, phase-prefix collisions, progress-marked trailers);
  * the bookkeeping / snapshot / release guards still exclude (FQ-77 posture);
  * the probes (`recognizes_direct_ship` / `ship_shaped_under_generic`) and the
    doctor verifiability surfaces see trailer ships, so a trailer-stamping repo
    is told to declare the flag instead of "nothing names a unit of work";
  * the end-to-end path (library `is_shipped(cfg=…)` and the real `dos verify`
    CLI over a `dos.toml`-declared workspace) flips to SHIPPED.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dos import phase_shipped as ps
from dos.stamp import (
    GENERIC_STAMP_CONVENTION,
    JOB_STAMP_CONVENTION,
    StampConvention,
    convention_coverage_finding,
    convention_from_table,
    ship_shaped_under_generic,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
TRAILER_ON = StampConvention(style="grep", trailer_stamp=True)

# The real-world line that motivated the feature (commit 9de9bb0 on the kernel
# repo), verbatim.
CC_LINE = (
    "9de9bb0 feat(pypi): CI builds the per-platform wheel matrix; "
    "fix the build/ staging leak (docs/286 Phase 3)"
)
FULL_PLAN = "docs/286_shipping-the-go-binary-through-pypi-per-platform-wheels"


def _check(series: str, phase: str, lines: list[str], conv: StampConvention) -> dict:
    """Run the oneline scan with an explicit convention (no git, no I/O)."""
    matchers = ps._subject_matchers(SimpleNamespace(stamp=conv))
    return ps._check_phase_with_cache(series, phase, lines, [], matchers)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _repo(repo: Path, *commits: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-m", "init: empty repo")
    for c in commits:
        _git(repo, "commit", "--allow-empty", "-m", c)


def _cli(repo: Path, *argv: str):
    env = dict(os.environ)
    src = str(Path(__file__).resolve().parent.parent / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *argv, "--workspace", str(repo)],
        capture_output=True, text=True, env=env,
    )


# ---------------------------------------------------------------------------
# the flag is data: defaults, TOML, dict round-trip
# ---------------------------------------------------------------------------
def test_flag_defaults_off_everywhere():
    """Opt-in means opt-in: neither shipped default recognizes trailers."""
    assert JOB_STAMP_CONVENTION.trailer_stamp is False
    assert GENERIC_STAMP_CONVENTION.trailer_stamp is False
    assert GENERIC_STAMP_CONVENTION.trailer_ship_core("docs/286", "Phase\\ 3") is None


def test_trailer_core_built_when_on():
    core = TRAILER_ON.trailer_ship_core("docs/286", "Phase\\ 3")
    assert core is not None and core.endswith(r"\)\s*$")


def test_from_table_parses_trailer_stamp():
    conv = convention_from_table(
        {"trailer_stamp": True}, base=GENERIC_STAMP_CONVENTION
    )
    assert conv.trailer_stamp is True
    # Omitted → inherits the base (off).
    conv = convention_from_table({"style": "grep"}, base=GENERIC_STAMP_CONVENTION)
    assert conv.trailer_stamp is False


def test_from_table_rejects_non_bool_trailer_stamp():
    with pytest.raises(ValueError, match="trailer_stamp must be a boolean"):
        convention_from_table({"trailer_stamp": "yes"}, base=GENERIC_STAMP_CONVENTION)


def test_from_table_still_rejects_unknown_keys():
    with pytest.raises(ValueError, match="unknown key"):
        convention_from_table({"trailer_stamps": True}, base=GENERIC_STAMP_CONVENTION)


def test_dict_round_trip_carries_the_flag():
    """The `DISPATCH_STAMP_CONVENTION` hand-off into the grep-rung subprocess
    serializes via to_dict/from_dict — the flag must survive, and an OLD payload
    without the key must default off (forward compatibility)."""
    assert StampConvention.from_dict(TRAILER_ON.to_dict()) == TRAILER_ON
    legacy = TRAILER_ON.to_dict()
    legacy.pop("trailer_stamp")
    assert StampConvention.from_dict(legacy).trailer_stamp is False


# ---------------------------------------------------------------------------
# the series bridge: full plan id ↔ short `<head>` before the first underscore
# ---------------------------------------------------------------------------
def test_series_variants_bridge():
    import re as _re
    assert ps._series_variants(FULL_PLAN) == sorted(
        [_re.escape("docs/286"), _re.escape(FULL_PLAN)]
    )
    assert ps._series_variants("82_liveness-oracle-plan") == sorted(
        [_re.escape("82"), _re.escape("82_liveness-oracle-plan")]
    )
    # Already the head / no digit head / hyphenated sub-phase id → no extra form.
    assert ps._series_variants("docs/286") == [_re.escape("docs/286")]
    assert ps._series_variants("my_plan") == [_re.escape("my_plan")]
    assert ps._series_variants("RS4-port") == [_re.escape("RS4-port")]


# ---------------------------------------------------------------------------
# the matcher: ships exactly the documented spellings (synthetic, no git)
# ---------------------------------------------------------------------------
def test_trailer_ships_real_world_line_full_plan_id():
    r = _check(FULL_PLAN, "Phase 3", [CC_LINE], TRAILER_ON)
    assert r["shipped"] is True
    assert r["sha"] == "9de9bb0"
    assert r["via"] == "trailer"


def test_trailer_ships_short_series_query():
    r = _check("docs/286", "Phase 3", [CC_LINE], TRAILER_ON)
    assert r["shipped"] is True and r["via"] == "trailer"


def test_trailer_colon_and_refs_spellings():
    colon = "abc1234 feat(x): wire the matrix (docs/286: Phase 3)"
    refs = "abc1234 fix(ci): close the staging leak (refs docs/286 Phase 3)"
    assert _check(FULL_PLAN, "Phase 3", [colon], TRAILER_ON)["shipped"] is True
    assert _check(FULL_PLAN, "Phase 3", [refs], TRAILER_ON)["shipped"] is True


def test_trailer_requires_opt_in():
    """The same line under the plain generic convention stays `via none`."""
    r = _check(FULL_PLAN, "Phase 3", [CC_LINE], GENERIC_STAMP_CONVENTION)
    assert r["shipped"] is False


def test_trailer_must_close_the_subject():
    """Mid-subject parens and bare prose mentions are references, not ships."""
    mid = "abc1234 fix the (docs/286 Phase 3) leak in CI"
    prose = "abc1234 fix the docs/286 Phase 3 leak in CI"
    assert _check(FULL_PLAN, "Phase 3", [mid], TRAILER_ON)["shipped"] is False
    assert _check(FULL_PLAN, "Phase 3", [prose], TRAILER_ON)["shipped"] is False


def test_trailer_phase_boundary_is_the_paren():
    """`Phase 3` must not match `(… Phase 30)` / `(… Phase 3.1)`, and a
    progress-marked trailer (`(… Phase 3 audit)`) is not a ship — fail-closed."""
    assert _check(
        FULL_PLAN, "Phase 3",
        ["abc1234 feat(x): widen the window (docs/286 Phase 30)"], TRAILER_ON
    )["shipped"] is False
    assert _check(
        FULL_PLAN, "Phase 3",
        ["abc1234 feat(x): widen the window (docs/286 Phase 3.1)"], TRAILER_ON
    )["shipped"] is False
    assert _check(
        FULL_PLAN, "Phase 3",
        ["abc1234 feat(x): soak notes (docs/286 Phase 3 audit)"], TRAILER_ON
    )["shipped"] is False


def test_trailer_admits_trailing_issue_ref():
    """docs/289 (#128) — a trailing issue ref inside the stamp paren
    (`(docs/318 P2, #21)`, `(docs/286 Phase 3, fixes #5)`) is a common
    Conventional-Commits habit and must NOT demote the ship to invisible."""
    # The exact witness from the issue (docs/318 P2, the adjacent commit whose
    # only difference from a recognized ship was the `, #21` tail).
    p2 = "d0b4ab3 feat(benchmark): improve_ablation P2 ratchet (docs/318 P2, #21)"
    r = _check("docs/318", "P2", [p2], TRAILER_ON)
    assert r["shipped"] is True and r["via"] == "trailer" and r["sha"] == "d0b4ab3"

    # The `fixes #NN` spelling, with the verbose `Phase N` phase form.
    fixes = "abc1234 feat(x): wire the matrix (docs/286 Phase 3, fixes #5)"
    assert _check(FULL_PLAN, "Phase 3", [fixes], TRAILER_ON)["shipped"] is True

    # Bare `#NN` with no comma, and `closes`/`refs` keywords, all admitted.
    for tail in ("#5", "closes #5", "refs #5", ", #5", ", #5, #6"):
        line = f"abc1234 feat(x): wire it (docs/286 Phase 3 {tail})"
        assert _check(FULL_PLAN, "Phase 3", [line], TRAILER_ON)["shipped"] is True, tail


def test_trailing_issue_ref_does_not_loosen_the_phase_boundary():
    """The `#`-required issue group never lets a wrong phase / progress marker /
    mid-subject paren slip through — the guards that motivated the tightness
    (test_trailer_phase_boundary_is_the_paren) still hold WITH the issue tail."""
    # `Phase 3` must still NOT match `Phase 30` even with an issue ref present.
    assert _check(
        FULL_PLAN, "Phase 3",
        ["abc1234 feat(x): widen (docs/286 Phase 30, #21)"], TRAILER_ON
    )["shipped"] is False
    # A progress-marked trailer with an issue ref is still not a ship.
    assert _check(
        FULL_PLAN, "Phase 3",
        ["abc1234 feat(x): soak (docs/286 Phase 3 audit, #21)"], TRAILER_ON
    )["shipped"] is False
    # The end anchor still bites: a mid-subject paren + issue ref then more text
    # is a reference, not a ship.
    assert _check(
        FULL_PLAN, "Phase 3",
        ["abc1234 fix (docs/286 Phase 3, #21) leak in CI"], TRAILER_ON
    )["shipped"] is False
    # An issue ref WITHOUT a phase token is a plain plan+issue reference.
    assert _check(
        FULL_PLAN, "Phase 3",
        ["abc1234 feat(x): ship it (docs/286, #21)"], TRAILER_ON
    )["shipped"] is False


def test_trailer_without_phase_token_is_not_a_ship():
    """A plain plan reference — `(docs/286)` / `(docs/286 follow-up)` — names the
    plan without stamping a phase; it must not satisfy any phase query."""
    assert _check(
        FULL_PLAN, "Phase 3",
        ["abc1234 feat(pypi): ship the native binary (docs/286)"], TRAILER_ON
    )["shipped"] is False
    assert _check(
        FULL_PLAN, "Phase 3",
        ["abc1234 fix(kernel): vendor literal (docs/286 follow-up)"], TRAILER_ON
    )["shipped"] is False


def test_trailer_excluded_on_bookkeeping_subjects():
    """FQ-77 posture: a NAMES-but-doesn't-ship subject never ships, trailer or
    not — both a declared prefix and the universal snapshot guard."""
    declared = dataclasses.replace(
        TRAILER_ON, bookkeeping_prefixes=("docs/_plans:",)
    )
    rollup = "abc1234 docs/_plans: soft-claim sweep (docs/286 Phase 3)"
    snap = "abc1234 working-dir snapshot: bulk sweep (docs/286 Phase 3)"
    assert _check(FULL_PLAN, "Phase 3", [rollup], declared)["shipped"] is False
    assert _check(FULL_PLAN, "Phase 3", [snap], TRAILER_ON)["shipped"] is False


def test_trailer_skips_release_subjects():
    """A `vX.Y.Z:` version cut ending in a phase-shaped paren stays on the weak
    release rung (with its footprint guards) — never promoted to a direct ship."""
    rel = "abc1234 v0.21.0: wheel-bundled fast path (docs/286 Phase 3)"
    r = _check(FULL_PLAN, "Phase 3", [rel], TRAILER_ON)
    assert r["via"] != "trailer"


def test_direct_ship_still_wins_over_a_newer_trailer():
    """A start-anchored ship anywhere in the window stays the canonical
    attribution; the trailer pass runs only after the whole direct pass."""
    newer_trailer = "bbb2222 feat(x): follow-up polish (docs/286 Phase 3)"
    older_direct = "aaa1111 docs/286: Phase 3 — ship the wheel matrix"
    r = _check("docs/286", "Phase 3", [newer_trailer, older_direct], TRAILER_ON)
    assert r["shipped"] is True
    assert r["via"] == "direct"
    assert r["sha"] == "aaa1111"


# ---------------------------------------------------------------------------
# the probes: recognizes_direct_ship / ship_shaped_under_generic
# ---------------------------------------------------------------------------
def test_recognizes_trailer_subject_iff_opted_in():
    subj = "feat(pypi): CI builds the wheel matrix (docs/286 Phase 3)"
    assert TRAILER_ON.recognizes_direct_ship(subj) is True
    assert GENERIC_STAMP_CONVENTION.recognizes_direct_ship(subj) is False
    # A plan reference without a phase token is not a ship under the probe either.
    assert TRAILER_ON.recognizes_direct_ship(
        "fix(kernel): vendor literal (docs/286 follow-up)"
    ) is False


def test_ship_shaped_breadth_sees_trailers():
    """The breadth predicate's contract is "would SOME convention recognize
    it?" — a trailer-stamped subject is ship-shaped even though no DEFAULT
    convention recognizes it; plain conventional commits stay non-ship-shaped
    (the 'never cries wolf' pins in test_stamp_doctor must keep holding)."""
    assert ship_shaped_under_generic(
        "feat(pypi): CI builds the wheel matrix (docs/286 Phase 3)"
    ) is True
    assert ship_shaped_under_generic("fix: typo") is False
    assert ship_shaped_under_generic("chore: bump deps") is False
    # Release cuts and snapshots are excluded before the trailer probe runs.
    assert ship_shaped_under_generic(
        "v0.21.0: wheel-bundled fast path (docs/286 Phase 3)"
    ) is False
    assert ship_shaped_under_generic(
        "working-dir snapshot: bulk sweep (docs/286 Phase 3)"
    ) is False


def test_coverage_finding_fires_on_undeclared_trailer_repo():
    """A declared [stamp] WITHOUT the flag on a repo whose real ships live in
    trailers → the 3c finding (the rail can now SEE the mismatch)."""
    finding = convention_coverage_finding(
        GENERIC_STAMP_CONVENTION,
        ["feat(pypi): wheel matrix (docs/286 Phase 3)", "fix: typo"],
        declared=True,
    )
    assert finding is not None and "recognizes none" in finding
    # Declaring the flag heals it.
    assert convention_coverage_finding(
        TRAILER_ON,
        ["feat(pypi): wheel matrix (docs/286 Phase 3)", "fix: typo"],
        declared=True,
    ) is None


# ---------------------------------------------------------------------------
# end to end: library, CLI, doctor
# ---------------------------------------------------------------------------
def test_library_is_shipped_via_trailer(tmp_path: Path):
    from dos import oracle
    from dos.config import default_config

    _repo(tmp_path, "feat(pypi): wire the wheel matrix (docs/286 Phase 3)")
    cfg = dataclasses.replace(default_config(tmp_path), stamp=TRAILER_ON)

    v = oracle.is_shipped(FULL_PLAN, "Phase 3", cfg=cfg)
    assert v.shipped is True
    # The trailer is agent-authored subject text → the FORGEABLE rung, graded
    # honestly as grep-subject like the direct rung it mirrors.
    assert v.source == "grep-subject"
    assert v.rung == "trailer"

    # Honest-negative: an unshipped phase stays not-shipped under the flag.
    v = oracle.is_shipped(FULL_PLAN, "Phase 9", cfg=cfg)
    assert v.shipped is False
    assert v.source == "none"


def test_cli_verify_trailer_with_declared_toml(tmp_path: Path):
    """The user-facing path: `dos.toml [stamp] trailer_stamp = true` + the real
    `dos verify` subprocess — the exact repro this plan exists to flip."""
    _repo(tmp_path, "feat(pypi): wire the wheel matrix (docs/286 Phase 3)")
    (tmp_path / "dos.toml").write_text(
        '[stamp]\nstyle = "grep"\ntrailer_stamp = true\n', encoding="utf-8"
    )
    proc = _cli(tmp_path, "verify", FULL_PLAN, "Phase 3", "--json")
    assert proc.stdout, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["shipped"] is True, (proc.stdout, proc.stderr)
    assert payload["source"] == "grep-subject"
    assert proc.returncode == 0

    # Without the declaration the same repo honestly answers via none.
    (tmp_path / "dos.toml").write_text('[stamp]\nstyle = "grep"\n', encoding="utf-8")
    proc2 = _cli(tmp_path, "verify", FULL_PLAN, "Phase 3", "--json")
    payload2 = json.loads(proc2.stdout)
    assert payload2["shipped"] is False
    assert payload2["source"] == "none"


def test_doctor_verifiability_counts_trailer_ships_when_declared(tmp_path: Path):
    _repo(
        tmp_path,
        "feat(pypi): wire the wheel matrix (docs/286 Phase 3)",
        "feat(exporter): statsd connector (docs/266 Phase 2)",
        "fix: typo",
    )
    (tmp_path / "dos.toml").write_text(
        '[stamp]\nstyle = "grep"\ntrailer_stamp = true\n', encoding="utf-8"
    )
    out = _cli(tmp_path, "doctor").stdout
    line = next(l for l in out.splitlines() if l.startswith("verifiability"))
    assert "can check" in line
    assert "+ trailer" in line

    proc = _cli(tmp_path, "doctor", "--json")
    v = json.loads(proc.stdout)["verifiability"]
    assert v["recognized"] == 2
    assert v["ship_shaped"] == 2
    assert "+ trailer" in v["grammar"]


def test_doctor_verifiability_actionable_on_undeclared_trailer_repo(tmp_path: Path):
    """A trailer-stamping repo with NO declaration now gets the actionable
    'reconcile [stamp]' cold open instead of 'none name a unit of work' — the
    breadth probe sees the ships, the active grammar doesn't recognize them."""
    _repo(tmp_path, "feat(pypi): wire the wheel matrix (docs/286 Phase 3)")
    out = _cli(tmp_path, "doctor").stdout
    line = next(l for l in out.splitlines() if l.startswith("verifiability"))
    assert "via none" in line and "reconcile [stamp]" in line

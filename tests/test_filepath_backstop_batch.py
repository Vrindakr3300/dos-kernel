"""docs/284 — the file-path backstop's batched-git path is BYTE-IDENTICAL.

The AAR-FQ230 file-path backstop (`_check_phase_by_filepath`) ran one
``git log --oneline -800 -- <file>`` subprocess PER named file PER pair — 364 git
subprocesses for a 262-pair job snapshot, ~19s. docs/284 hoists that into ONE
windowed ``git log --name-only`` scan over the union of every pair's files
(`build_batch_filepath_cache` → `_build_filepath_log_cache`), and the per-pair
overlap becomes a pure in-memory lookup against that cache.

The load-bearing contract (the ⚓ never-under-count pin): the batched path must
produce **byte-identical** `{(plan,phase): verdict}` to the per-file-subprocess
path. The job side SUBTRACTS the shipped-set from `remaining`, so a verdict that
flips `shipped=False→True` incorrectly would drop a genuinely-live pick (lost
work). This module pins parity across the rung's distinct ship shapes — multi-file
overlap, single-file series-attributed, bookkeeping exclusion, cross-series guard,
and the plain not-shipped case — and pins that the batched path actually makes far
fewer `git log` calls than the per-pair path it replaces.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

from dos import config as C
from dos import phase_shipped as PS
from dos.stamp import GENERIC_STAMP_CONVENTION


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-m", "init: empty repo")


def _commit(repo: Path, subject: str, *files: str) -> None:
    for f in files:
        p = repo / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((p.read_text() if p.exists() else "") + "\nx", encoding="utf-8")
    if files:
        _git(repo, "add", *files)
        _git(repo, "commit", "-m", subject)
    else:
        _git(repo, "commit", "--allow-empty", "-m", subject)


def _generic_cfg(repo: Path) -> "C.SubstrateConfig":
    return dataclasses.replace(C.default_config(repo), stamp=GENERIC_STAMP_CONVENTION)


def _build_mixed_repo(repo: Path) -> tuple[Path, list[tuple[str, str, str]]]:
    """A repo with one of every file-path verdict shape. Returns (plan_doc, triples).

    Each pick exercises a distinct branch of `_check_phase_by_filepath`:
      * `vllm/Phase 2` — multi-file overlap (3 files, one commit) → SHIPPED.
      * `mamba/P1.3`  — single-file, series-attributed subject → SHIPPED.
      * `auth/A4`     — single-file, NON-attributed subject → NOT shipped.
      * `cfg/C9`      — names only a shared-infra hub → NOT shipped.
      * `ghost/G1`    — names a file with no commit history → NOT shipped.
      * `book/B7`     — its files were only co-touched by a bookkeeping sweep → NOT shipped.
    """
    _init_repo(repo)
    plan = repo / "docs" / "plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "### Phase 2 — wire config\n"
        "`server/_config.py`, `commands/_serve_presets.py`, `commands/_subparsers.py`\n"
        "\n### P1.3 — wire mamba pool flags\n"
        "Edits `engine/_mamba.py`.\n"
        "\n### A4 — touch the auth helper\n"
        "Edits `auth/_helper.py`.\n"
        "\n### C9 — shared-infra only\n"
        "Edits `src/dos/config.py`.\n"
        "\n### G1 — names a file with no history\n"
        "Edits `never/_committed.py`.\n"
        "\n### B7 — only a bookkeeping sweep touched these\n"
        "`work/_a.py`, `work/_b.py`\n",
        encoding="utf-8",
    )
    _git(repo, "add", "docs/plan.md")
    _git(repo, "commit", "-m", "docs: add plan")
    # multi-file overlap ship (subject lacks the phase id — the #230 shape)
    _commit(
        repo,
        "engine refactor: --engine CLI + config-builder branch",
        "server/_config.py", "commands/_serve_presets.py", "commands/_subparsers.py",
    )
    # single-file, series-attributed
    _commit(repo, "mamba P1.3: wire pool flags", "engine/_mamba.py")
    # single-file, NOT series-attributed (subject names no series token)
    _commit(repo, "tidy a helper", "auth/_helper.py")
    # sole shared-infra hub, even series-attributed → too weak
    _commit(repo, "cfg C9: tweak config", "src/dos/config.py")
    # a bookkeeping sweep co-touches B7's files — must be excluded from overlap
    _commit(
        repo,
        "working-dir snapshot: 20260610T010101Z",
        "work/_a.py", "work/_b.py",
    )
    triples = [
        ("vllm", "Phase 2", str(plan)),
        ("mamba", "P1.3", str(plan)),
        ("auth", "A4", str(plan)),
        ("cfg", "C9", str(plan)),
        ("ghost", "G1", str(plan)),
        ("book", "B7", str(plan)),
    ]
    return plan, triples


def test_batched_filepath_is_byte_identical_to_per_pair(tmp_path: Path):
    """The cache path's verdict map equals the per-file-subprocess map, byte-for-byte."""
    plan, triples = _build_mixed_repo(tmp_path)
    cfg = _generic_cfg(tmp_path)
    C.set_active(cfg)
    m = PS._subject_matchers(cfg)

    cache = PS.build_batch_filepath_cache(triples, m)
    assert cache is not None, "the union scan should not saturate on this tiny repo"

    per_pair: dict[tuple[str, str], dict] = {}
    batched: dict[tuple[str, str], dict] = {}
    for series, phase, doc in triples:
        per_pair[(series, phase)] = PS._check_phase_by_filepath(series, phase, doc, m)
        batched[(series, phase)] = PS._check_phase_by_filepath(series, phase, doc, m, cache)

    assert batched == per_pair, (
        "batched file-path verdicts diverged from the per-pair path (never-under-count "
        f"pin):\n  per-pair: {per_pair}\n  batched : {batched}"
    )
    # And the shapes really are exercised (not all NOT_SHIPPED by accident).
    assert per_pair[("vllm", "Phase 2")]["shipped"] is True
    assert per_pair[("mamba", "P1.3")]["shipped"] is True
    assert per_pair[("auth", "A4")]["shipped"] is False
    assert per_pair[("cfg", "C9")]["shipped"] is False
    assert per_pair[("ghost", "G1")]["shipped"] is False
    assert per_pair[("book", "B7")]["shipped"] is False


def test_batched_sha_is_abbreviated_like_oneline(tmp_path: Path):
    """The cached scan uses `%h` — the abbreviated sha the `--oneline` path returns.

    Regression pin for the docs/284 build bug: `%H` (full sha) made the `sha`/
    `summary` fields differ from the per-pair path, silently breaking byte-identity
    on a SHIPPED verdict. The abbreviated sha keeps every field equal.
    """
    plan, triples = _build_mixed_repo(tmp_path)
    cfg = _generic_cfg(tmp_path)
    C.set_active(cfg)
    m = PS._subject_matchers(cfg)
    cache = PS.build_batch_filepath_cache(triples, m)
    pp = PS._check_phase_by_filepath("vllm", "Phase 2", str(plan), m)
    bt = PS._check_phase_by_filepath("vllm", "Phase 2", str(plan), m, cache)
    assert pp["sha"] == bt["sha"]
    assert len(bt["sha"]) < 40, f"expected an abbreviated sha, got {bt['sha']!r}"
    assert pp["summary"] == bt["summary"]


def test_batched_path_makes_far_fewer_git_calls(tmp_path: Path, monkeypatch):
    """One union scan replaces the per-file `git log` storm — the docs/284 win.

    Pins the MECHANISM (call count), not a millisecond budget: the batched path
    runs `_git_log` ONCE (the union `--name-only` scan); the per-pair path runs it
    once PER named file PER pick (here 9 named files across the picks).
    """
    plan, triples = _build_mixed_repo(tmp_path)
    cfg = _generic_cfg(tmp_path)
    C.set_active(cfg)
    m = PS._subject_matchers(cfg)

    calls: list[list[str]] = []
    real = PS._git_log

    def _spy(args):
        calls.append(list(args))
        return real(args)

    monkeypatch.setattr(PS, "_git_log", _spy)

    # Batched: build the cache (1 git call), then resolve every pick from memory.
    calls.clear()
    cache = PS.build_batch_filepath_cache(triples, m)
    for series, phase, doc in triples:
        PS._check_phase_by_filepath(series, phase, doc, m, cache)
    batched_calls = len(calls)

    # Per-pair: every named file is its own `git log`.
    calls.clear()
    for series, phase, doc in triples:
        PS._check_phase_by_filepath(series, phase, doc, m)
    per_pair_calls = len(calls)

    assert batched_calls == 1, f"expected ONE union scan, got {batched_calls}: {calls}"
    assert per_pair_calls > batched_calls, (
        f"the per-pair path should make many more git calls "
        f"({per_pair_calls} vs {batched_calls})"
    )


def test_saturated_window_returns_none_for_safe_fallback(tmp_path: Path, monkeypatch):
    """A saturated union window returns None so the caller re-runs the exact per-file path.

    The never-under-count safety degrade: if the bounded union scan could have
    dropped a commit a per-file 800-window would reach, the builder must NOT answer
    from a possibly-narrower window — it returns None, and `_apply_filepath_backstop`
    falls back to the per-file subprocess path (identical to pre-docs/284).
    """
    plan, triples = _build_mixed_repo(tmp_path)
    cfg = _generic_cfg(tmp_path)
    C.set_active(cfg)
    m = PS._subject_matchers(cfg)
    # Force the cap to 1 commit so the union scan saturates immediately.
    monkeypatch.setattr(PS, "_FILEPATH_WINDOW", 1)
    monkeypatch.setattr(PS, "_BATCH_SCAN_CAP_FACTOR", 1)
    cache = PS.build_batch_filepath_cache(triples, m)
    assert cache is None, "a saturated union window must degrade to the per-file path"


def test_merge_commit_history_is_byte_identical(tmp_path: Path):
    """Merge commits are excluded from BOTH paths, keeping them byte-identical.

    docs/284 merge contract: a union `git log --name-only` over many pathspecs
    cannot reproduce git's per-PATH simplification through MERGE commits (default
    `--oneline -- <file>` follows a TREESAME parent and prunes a merge that carried
    no new change to <file>, but lists an evil-merge that did; the union scan has no
    single parent to follow). `--no-merges` on BOTH paths removes the ambiguity at
    the source — a merge is never a phase's ship of record, and the underlying
    feature commit (the real ship) is retained either way. This builds a real
    branch+merge and asserts (a) the merge appears in neither path, (b) the feature
    commit appears in both, and (c) the per-file lists are equal commit-for-commit.
    """
    _init_repo(tmp_path)
    target = "engine/_pool.py"
    # base commit on master
    _commit(tmp_path, "base: seed pool", target)
    _git(tmp_path, "checkout", "-b", "feature")
    # the change to <target> lives on the feature branch
    _commit(tmp_path, "feature: extend pool", target)
    _git(tmp_path, "checkout", "master")
    # an unrelated commit on master so the merge is a real (non-fast-forward) merge
    _commit(tmp_path, "master: unrelated", "docs/notes.md")
    _git(tmp_path, "merge", "--no-ff", "-m", "Merge feature into master", "feature")

    cfg = _generic_cfg(tmp_path)
    C.set_active(cfg)
    cache = PS._build_filepath_log_cache([target])
    assert cache is not None
    per_file = []
    for line in PS._git_log(
        ["--oneline", "--no-merges", f"-{PS._FILEPATH_WINDOW}", "--", target]
    ):
        parts = line.split(None, 1)
        if parts:
            per_file.append((parts[0], parts[1] if len(parts) > 1 else ""))
    assert cache[target] == per_file, (
        "the per-file lists must be byte-identical (no-merges on both):\n"
        f"  cache    : {cache[target]}\n  per-file : {per_file}"
    )
    # (a) no `Merge …` subject survived into the cache; (b) the feature ship did.
    subjects = [subj for _, subj in cache[target]]
    assert not any(s.startswith("Merge ") for s in subjects), subjects
    assert any("feature: extend pool" in s for s in subjects), subjects


def test_backstop_with_none_cache_matches_no_cache(tmp_path: Path):
    """`_apply_filepath_backstop(..., fp_cache=None)` is the unchanged per-file path.

    The fallback wiring pin: passing a None cache (the saturation/error signal)
    must behave exactly as the pre-docs/284 backstop did (no cache argument).
    """
    plan, triples = _build_mixed_repo(tmp_path)
    cfg = _generic_cfg(tmp_path)
    C.set_active(cfg)
    m = PS._subject_matchers(cfg)
    for series, phase, doc in triples:
        base = {"shipped": False, "sha": "", "summary": "", "via": ""}
        no_arg = PS._apply_filepath_backstop(dict(base), series, phase, doc, m)
        none_cache = PS._apply_filepath_backstop(dict(base), series, phase, doc, m, None)
        assert no_arg == none_cache

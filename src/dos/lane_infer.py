"""Infer a starter lane taxonomy from a repo's top-level directory layout.

This is the **public, reusable** form of the inference `dos init` already does
internally when it scaffolds a `dos.toml` (`cli._render_init_config`). The CLI
keeps its own inline copy for the scaffold-text path; this module is the importable
API a *foreign caller* — a host driver, a skill, an adopter's own tooling — calls to
get a `LaneTaxonomy` object directly, without parsing the scaffolded TOML back out
or re-deriving the `"<dir>/**"` tree convention by hand.

The rule (identical to `dos init`'s): every immediate subdirectory that is not a
dotdir and not obvious noise (VCS / caches / build output / deps / venvs) becomes a
**concurrent** lane owning `<dir>/**`, plus an **exclusive** `global` over the whole
repo. A repo with no source dirs falls back to the honest single-writer default —
one exclusive `main` over `**/*`, no concurrent lanes — so `dos doctor --check`
stays clean (an exclusive lane never enters the disjointness algebra).

Why a separate module rather than just calling the CLI helper: the CLI helper
(`_render_init_config`) returns *TOML text* and is private to the scaffold path; an
adopter wants the *typed object* (`LaneTaxonomy`) to pass into `SubstrateConfig`,
compare against a declared `dos.toml [lanes]`, or render however they like. Keeping
this pure (Path in → LaneTaxonomy out, the only I/O a single `iterdir`) makes it
testable and free of the CLI's argument/scaffold concerns — the
"I/O at the boundary, data to the pure core" rule, applied to lane discovery.

The constants are duplicated from `cli` deliberately (not imported): this module
must not import the CLI (a layer-3 helper) — the dependency arrow points the other
way. The two copies are pinned equal by `tests/test_lane_infer.py`, the same
discipline `cooldown` uses for the lane-journal schema family it inlines.
"""

from __future__ import annotations

from pathlib import Path

from dos.config import LaneTaxonomy

# Cap on auto-derived concurrent lanes — a repo with hundreds of top-level dirs
# should not scaffold a hundred-lane taxonomy; beyond a handful the operator wants
# to curate by hand. Mirrors `cli._INIT_LANE_MAX` (pinned equal by the test).
LANE_INFER_MAX = 12

# Top-level entries that are never a source lane: VCS, caches, build output,
# dependency trees, virtualenvs, IDE/tooling dirs. Mirrors `cli._INIT_NOISE_DIRS`
# (pinned equal by the test). Dotdirs are skipped wholesale by the leading-`.`
# check in `detect_source_dirs`, so they need no entry here.
LANE_INFER_NOISE_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", "dist", "build", "target",
    "venv", ".venv", "env", ".env", ".idea", ".vscode", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", "site-packages", ".dos",
    "htmlcov", ".eggs",
})


def detect_source_dirs(
    root: Path,
    *,
    cap: int = LANE_INFER_MAX,
    noise_dirs: frozenset[str] | None = None,
) -> list[str]:
    """The repo's top-level source directories — sorted, noise-filtered, capped.

    A "source dir" is any immediate subdirectory of ``root`` that is not a dotdir
    and not in ``noise_dirs``. Returns at most ``cap`` names (sorted, so the
    selection is deterministic). On any filesystem error (``root`` missing / not a
    dir / unreadable) returns ``[]`` — the caller then gets the single-writer
    fallback taxonomy, which is the safe default for an unscannable root.
    """
    noise = LANE_INFER_NOISE_DIRS if noise_dirs is None else noise_dirs
    try:
        entries = sorted(
            p.name for p in Path(root).iterdir()
            if p.is_dir()
            and not p.name.startswith(".")
            and p.name not in noise
        )
    except OSError:
        return []
    return entries[:cap]


def infer_lanes_from_directory(
    root: Path,
    *,
    cap: int = LANE_INFER_MAX,
    noise_dirs: frozenset[str] | None = None,
) -> LaneTaxonomy:
    """Infer a starter ``LaneTaxonomy`` from ``root``'s top-level directories.

    Each top-level source dir (see :func:`detect_source_dirs`) becomes a
    **concurrent** lane owning ``<dir>/**`` and is added to ``autopick``; an
    **exclusive** ``global`` owns ``**/*``. With no source dirs, falls back to the
    honest single-writer default: one exclusive ``main`` over ``**/*``, no
    concurrent lanes.

    Returns a typed :class:`~dos.config.LaneTaxonomy` — byte-equivalent to the
    ``[lanes]`` table ``dos init`` scaffolds — so a caller can drop it straight into
    a ``SubstrateConfig(lanes=…)`` or compare it against a declared ``dos.toml``.
    Pure but for the single ``iterdir`` inside ``detect_source_dirs``.
    """
    dirs = detect_source_dirs(root, cap=cap, noise_dirs=noise_dirs)
    if dirs:
        trees: dict[str, tuple[str, ...]] = {d: (f"{d}/**",) for d in dirs}
        trees["global"] = ("**/*",)
        return LaneTaxonomy(
            concurrent=tuple(dirs),
            exclusive=("global",),
            autopick=tuple(dirs),
            trees=trees,
            aliases={},
        )
    # Honest single-writer fallback — no source dirs to make disjoint, so one
    # exclusive whole-repo lane (matches `cli._render_init_config`'s else branch).
    return LaneTaxonomy(
        concurrent=(),
        exclusive=("main",),
        autopick=(),
        trees={"main": ("**/*",)},
        aliases={},
    )


__all__ = [
    "LANE_INFER_MAX",
    "LANE_INFER_NOISE_DIRS",
    "detect_source_dirs",
    "infer_lanes_from_directory",
]

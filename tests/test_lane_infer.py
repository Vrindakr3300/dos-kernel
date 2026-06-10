"""Tests for the public lane-inference API (`dos.lane_infer`).

`infer_lanes_from_directory` is the importable form of the inference `dos init`
does inline. These pin (a) the inferred taxonomy shape, (b) the single-writer
fallback, (c) the noise-filter + dotdir skip + cap, and — load-bearing — (d) that
this module's behavior and constants stay EQUAL to the CLI's inline copy, the
duplication-discipline the module docstring promises (the same pin `cooldown` uses
for the lane-journal schema it inlines).
"""

from __future__ import annotations

from pathlib import Path

from dos import lane_infer
from dos.config import LaneTaxonomy


def _mkdirs(root: Path, *names: str) -> None:
    for n in names:
        (root / n).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# The inferred taxonomy
# ---------------------------------------------------------------------------
class TestInferLanes:
    def test_source_dirs_become_concurrent_lanes(self, tmp_path):
        _mkdirs(tmp_path, "src", "docs", "tests")
        tax = lane_infer.infer_lanes_from_directory(tmp_path)
        assert tax.concurrent == ("docs", "src", "tests")          # sorted
        assert tax.exclusive == ("global",)
        assert tax.autopick == ("docs", "src", "tests")
        # each concurrent lane owns "<dir>/**"; global owns the whole repo
        assert tax.trees["src"] == ("src/**",)
        assert tax.trees["docs"] == ("docs/**",)
        assert tax.trees["tests"] == ("tests/**",)
        assert tax.trees["global"] == ("**/*",)
        assert tax.aliases == {}

    def test_returns_a_lanetaxonomy(self, tmp_path):
        _mkdirs(tmp_path, "src")
        assert isinstance(lane_infer.infer_lanes_from_directory(tmp_path),
                          LaneTaxonomy)

    def test_no_source_dirs_falls_back_to_single_writer_main(self, tmp_path):
        # empty repo (or all-noise) -> one exclusive 'main', no concurrent lanes
        tax = lane_infer.infer_lanes_from_directory(tmp_path)
        assert tax.concurrent == ()
        assert tax.exclusive == ("main",)
        assert tax.autopick == ()
        assert tax.trees == {"main": ("**/*",)}

    def test_missing_root_falls_back_cleanly(self, tmp_path):
        tax = lane_infer.infer_lanes_from_directory(tmp_path / "nope")
        assert tax.exclusive == ("main",)         # OSError -> [] -> fallback

    # -- detect_source_dirs filtering --------------------------------------------
    def test_dotdirs_and_noise_are_skipped(self, tmp_path):
        _mkdirs(tmp_path, "src", ".git", "__pycache__", "node_modules",
                ".venv", "dist")
        (tmp_path / "README.md").write_text("x")   # a file, not a dir
        assert lane_infer.detect_source_dirs(tmp_path) == ["src"]

    def test_cap_limits_lane_count(self, tmp_path):
        _mkdirs(tmp_path, *[f"d{i:02d}" for i in range(20)])
        got = lane_infer.detect_source_dirs(tmp_path, cap=5)
        assert got == ["d00", "d01", "d02", "d03", "d04"]          # sorted, capped

    def test_custom_noise_dirs_override(self, tmp_path):
        _mkdirs(tmp_path, "keep", "drop")
        got = lane_infer.detect_source_dirs(tmp_path,
                                            noise_dirs=frozenset({"drop"}))
        assert got == ["keep"]


# ---------------------------------------------------------------------------
# Parity with the CLI's inline copy — the duplication discipline
# ---------------------------------------------------------------------------
class TestCliParity:
    def test_noise_dirs_equal_cli(self):
        from dos import cli
        assert lane_infer.LANE_INFER_NOISE_DIRS == cli._INIT_NOISE_DIRS

    def test_lane_cap_equal_cli(self):
        from dos import cli
        assert lane_infer.LANE_INFER_MAX == cli._INIT_LANE_MAX

    def test_detect_source_dirs_matches_cli(self, tmp_path):
        from dos import cli
        _mkdirs(tmp_path, "src", "docs", ".git", "node_modules", "tests")
        assert (lane_infer.detect_source_dirs(tmp_path)
                == cli._detect_source_dirs(tmp_path))

    def test_inferred_lanes_match_cli_scaffold(self, tmp_path):
        """The taxonomy this module infers equals the [lanes] table the CLI
        scaffolds — same concurrent set + same trees, so an adopter calling the
        public API gets exactly what `dos init` would write."""
        from dos import cli
        _mkdirs(tmp_path, "src", "docs", "tests")
        tax = lane_infer.infer_lanes_from_directory(tmp_path)
        toml_text, _summary = cli._render_init_config(tmp_path)
        # the scaffolded TOML names exactly the inferred concurrent lanes...
        for lane in tax.concurrent:
            assert f'{lane} = ["{lane}/**"]' in toml_text
        # ...and the inferred concurrent set is the CLI's detected dir set.
        assert list(tax.concurrent) == cli._detect_source_dirs(tmp_path)

"""The `[data_class]` seam — path → data-class (TRAJECTORY/AUDIT/BASELINE/PRODUCT)
as per-workspace DATA, the "tag agent-trajectory vs actual product" answer.

A repo's emission tree mixes re-derivable agent-run scratch (run dirs, result
envelopes, audit reports) with deliverables (plans, schemas, baselines). A reaper
can only treat them differently if it can ASK a path which it is — and that WHICH
is policy (it differs per workspace), so it rides `SubstrateConfig` next to
`.retention`/`.stamp`, declarable in `dos.toml [data_class]`, with a generic
default keyed only off `.dos/`-relative shapes so DOS stays domain-free.

These tests pin: the pure `classify` (priority order, dir-expansion, `**`-depth,
default-class fallthrough), the `policy_from_table`/`load_from_toml` loaders (the
unknown-key + bad-default-class raises, the BOM tolerance), and the config wiring
(the seam reaches `SubstrateConfig.data_class`, malformed warns-and-keeps-base).

Litmus for the layering: `data_class.py` is a pure stdlib leaf (layer 2b
seam-data, like `retention.py`/`stamp.py`) — importing `dos.data_class` pulls in
no driver and no host name.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from dos import config as _config
from dos import data_class as _data_class
from dos.data_class import (
    AUDIT,
    BASELINE,
    GENERIC_DATA_CLASS,
    NONE_DATA_CLASS,
    PRODUCT,
    TRAJECTORY,
    DataClassPolicy,
    load_from_toml,
    policy_from_table,
)


def _write_toml(repo: Path, body: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "dos.toml").write_text(body, encoding="utf-8")


# ===========================================================================
# The pure classifier — classify (priority, dir-expansion, **-depth, default)
# ===========================================================================


def _job_like() -> DataClassPolicy:
    """A policy shaped like the reference userland app's `docs/_*` tree."""
    return DataClassPolicy(
        trajectory_patterns=(
            "docs/_chained_runs",
            "docs/_dispatch_loops",
            "docs/_fanout_runs",
        ),
        audit_patterns=("docs/_audits", "docs/_lane_audits"),
        baseline_patterns=("docs/_*_baselines",),
        default_class=PRODUCT,
    )


def test_classify_trajectory_dir_and_subtree():
    pol = _job_like()
    # the bare dir AND its whole subtree classify as trajectory (dir-expansion)
    assert pol.classify("docs/_chained_runs") == TRAJECTORY
    assert pol.classify("docs/_chained_runs/20260601T0000Z/README.md") == TRAJECTORY
    assert pol.classify("docs/_dispatch_loops/20260601T0000Z/iter-1/result.json") == TRAJECTORY


def test_classify_audit_and_baseline():
    pol = _job_like()
    assert pol.classify("docs/_audits/clutter-20260604.md") == AUDIT
    assert pol.classify("docs/_lane_audits/20260601/summary.json") == AUDIT
    # `docs/_*_baselines` — the `*` matches the series name within the segment
    assert pol.classify("docs/_acr0_baselines/20260512T0121Z/x.json") == BASELINE
    assert pol.classify("docs/_aar12_baselines/20260505T182235Z/y.json") == BASELINE


def test_classify_product_is_default():
    pol = _job_like()
    assert pol.classify("docs/61_modularity-and-code-quality-plan.md") == PRODUCT
    assert pol.classify("scripts/lc3_retention_cron.py") == PRODUCT
    assert pol.classify("docs/baselines.yaml") == PRODUCT


def test_classify_priority_trajectory_beats_later_classes():
    """A path matching both a trajectory and a baseline pattern lands in trajectory
    (the earlier class in the fixed priority order wins)."""
    pol = DataClassPolicy(
        trajectory_patterns=("docs/_x/**",),
        baseline_patterns=("docs/_x/**",),
    )
    assert pol.classify("docs/_x/thing.json") == TRAJECTORY


def test_classify_doublestar_any_depth_including_zero():
    pol = DataClassPolicy(trajectory_patterns=("a/**/b",))
    assert pol.classify("a/b") == TRAJECTORY           # zero intermediate segments
    assert pol.classify("a/x/b") == TRAJECTORY         # one
    assert pol.classify("a/x/y/z/b") == TRAJECTORY     # many
    assert pol.classify("a/b/c") == PRODUCT            # b is not the tail → no match


def test_classify_single_star_within_segment_only():
    pol = DataClassPolicy(trajectory_patterns=("docs/_*_baselines/**",))
    assert pol.classify("docs/_acr0_baselines/x") == TRAJECTORY
    # `*` does not cross a `/`, so a nested dir before `_baselines` does not match
    assert pol.classify("docs/sub/_acr0_baselines/x") == PRODUCT


def test_classify_normalizes_backslashes_and_leading_dotslash():
    pol = _job_like()
    assert pol.classify("docs\\_chained_runs\\20260601\\README.md") == TRAJECTORY
    assert pol.classify("./docs/_chained_runs/r/README.md") == TRAJECTORY


def test_classify_trailing_slash_means_subtree():
    pol = DataClassPolicy(trajectory_patterns=("docs/_runs/",))
    assert pol.classify("docs/_runs/a/b.md") == TRAJECTORY
    # the trailing-slash form matches the subtree; the bare dir itself is covered
    # by the `**` it expands to needing at least the dir prefix
    assert pol.classify("docs/_runs/x") == TRAJECTORY


def test_classify_product_pattern_is_explicit_keep_checked_last():
    """product_patterns is checked last, so a trajectory pattern still wins over it;
    to pin a path as product, the trajectory pattern must not match it."""
    pol = DataClassPolicy(
        trajectory_patterns=("docs/_runs/scratch/**",),
        product_patterns=("docs/_runs/keep/**",),
    )
    assert pol.classify("docs/_runs/scratch/a.md") == TRAJECTORY
    assert pol.classify("docs/_runs/keep/important.md") == PRODUCT


def test_none_policy_everything_is_product():
    for p in ("docs/_chained_runs/r/README.md", ".dos/audits/trajectory-audit-1.md",
              "anything/at/all"):
        assert NONE_DATA_CLASS.classify(p) == PRODUCT


def test_generic_default_is_dos_relative_only():
    """The kernel default names NO host tree — `.dos/` shapes classify, a host
    `docs/` path falls through to PRODUCT until the host declares patterns."""
    assert GENERIC_DATA_CLASS.classify(".dos/runs/abc/README.md") == TRAJECTORY
    assert GENERIC_DATA_CLASS.classify(".dos/audits/trajectory-audit-1.md") == AUDIT
    assert GENERIC_DATA_CLASS.classify(".dos/baselines/anc0/x.json") == BASELINE
    # a host docs tree is NOT named by the generic default
    assert GENERIC_DATA_CLASS.classify("docs/_chained_runs/r/README.md") == PRODUCT


# ===========================================================================
# The toml loader — policy_from_table / load_from_toml
# ===========================================================================


def test_policy_from_table_overrides_named_keys_only():
    base = _job_like()
    pol = policy_from_table({"audit_patterns": ["docs/_new_audits"]}, base=base)
    assert pol.audit_patterns == ("docs/_new_audits",)
    # untouched fields inherit base (override, not merge)
    assert pol.trajectory_patterns == base.trajectory_patterns
    assert pol.baseline_patterns == base.baseline_patterns


def test_policy_from_table_single_string_wraps_to_tuple():
    pol = policy_from_table({"trajectory_patterns": "docs/_runs"}, base=NONE_DATA_CLASS)
    assert pol.trajectory_patterns == ("docs/_runs",)


def test_policy_from_table_unknown_key_raises():
    try:
        policy_from_table({"trajctory_patterns": ["x"]}, base=GENERIC_DATA_CLASS)
    except ValueError as e:
        assert "unknown [data_class] key" in str(e)
        assert "trajctory_patterns" in str(e)
    else:
        raise AssertionError("expected ValueError on typo'd key")


def test_policy_from_table_bad_default_class_raises():
    try:
        policy_from_table({"default_class": "GARBAGE"}, base=GENERIC_DATA_CLASS)
    except ValueError as e:
        assert "default_class" in str(e)
    else:
        raise AssertionError("expected ValueError on invalid default_class")


def test_policy_from_table_non_string_pattern_element_raises():
    try:
        policy_from_table({"trajectory_patterns": ["ok", 5]}, base=GENERIC_DATA_CLASS)
    except ValueError as e:
        assert "trajectory_patterns" in str(e)
    else:
        raise AssertionError("expected ValueError on non-string pattern element")


def test_load_from_toml_absent_returns_base(tmp_path: Path):
    assert load_from_toml(tmp_path / "dos.toml", base=GENERIC_DATA_CLASS) is GENERIC_DATA_CLASS
    # present file but no [data_class] table → base unchanged
    _write_toml(tmp_path, "[retention]\naudits_keep_last = 3\n")
    assert load_from_toml(tmp_path / "dos.toml", base=GENERIC_DATA_CLASS) is GENERIC_DATA_CLASS


def test_load_from_toml_present_overrides(tmp_path: Path):
    _write_toml(
        tmp_path,
        "[data_class]\n"
        'trajectory_patterns = ["docs/_chained_runs", "docs/_dispatch_loops"]\n'
        'baseline_patterns = ["docs/_*_baselines"]\n',
    )
    pol = load_from_toml(tmp_path / "dos.toml", base=NONE_DATA_CLASS)
    assert pol.classify("docs/_chained_runs/r/README.md") == TRAJECTORY
    assert pol.classify("docs/_acr0_baselines/x.json") == BASELINE


def test_load_from_toml_tolerates_utf8_bom(tmp_path: Path):
    """PowerShell's `utf8` writes a BOM; the loader strips it (utf-8-sig)."""
    body = "[data_class]\ntrajectory_patterns = [\"docs/_runs\"]\n"
    (tmp_path / "dos.toml").write_text(body, encoding="utf-8-sig")
    pol = load_from_toml(tmp_path / "dos.toml", base=NONE_DATA_CLASS)
    assert pol.classify("docs/_runs/a.md") == TRAJECTORY


# ===========================================================================
# Config wiring — the seam reaches SubstrateConfig
# ===========================================================================


def test_config_default_is_generic_data_class(tmp_path: Path):
    cfg = _config.load_workspace_config(tmp_path)
    assert cfg.data_class == GENERIC_DATA_CLASS


def test_config_reads_data_class_table(tmp_path: Path):
    _write_toml(
        tmp_path,
        "[data_class]\ntrajectory_patterns = [\"docs/_chained_runs\"]\n",
    )
    cfg = _config.load_workspace_config(tmp_path)
    assert cfg.data_class.classify("docs/_chained_runs/r/README.md") == TRAJECTORY


def test_config_malformed_data_class_warns_keeps_base(tmp_path: Path):
    """A malformed [data_class] warns and keeps the base — never crashes config
    load (the shared warn-and-fall-back posture)."""
    _write_toml(tmp_path, "[data_class]\ndefault_class = \"NOPE\"\n")
    warnings = []
    cfg = _config.load_workspace_config(
        tmp_path, warn=lambda label, msg: warnings.append((label, msg)))
    assert cfg.data_class == GENERIC_DATA_CLASS  # base kept
    assert any(label == "data_class" for label, _ in warnings)

"""Bench layering litmus — the standardized benchmark runner is a CONSUMER of the
kernel, never part of it.

This is the rail behind the CLAUDE.md litmus "benchmarks are consumers, never the
kernel — the same one-way arrow as the MCP server and the release tooling." It
pins, by AST walk (not a fragile substring grep):

  * NO module under `src/dos/*.py` imports `benchmark` (or any `benchmark.*`),
    just as none imports `scripts` or `dos_mcp`;
  * the registry's named arms resolve to the SAME DOS_* env as the shared
    `_arms` vocabulary (single source of truth — no parallel copy can drift);
  * the registry is well-formed: every prereq kind is in the closed vocabulary,
    every entrypoint argv {token} has a default or is a known multi-word knob.

The runner (`benchmark/_run.py`) and registry (`benchmark/registry.py`) live
under `benchmark/`, so they may import benchmark internals freely; what this test
forbids is the REVERSE arrow — the kernel reaching into the benchmark suite.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import dos

_SRC_DOS = Path(dos.__file__).parent
_REPO = _SRC_DOS.parent.parent            # src/dos -> src -> repo root
_BENCH = _REPO / "benchmark"


# --------------------------------------------------------------------------- the arrow
def _imports_in(path: Path) -> set:
    """Every top-level module name imported by a python file (via AST, so a string
    'benchmark' in a comment or docstring never false-trips)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


def test_no_kernel_module_imports_benchmark():
    """The reverse arrow is forbidden: nothing under src/dos/*.py may import the
    benchmark suite (the analogue of the no-scripts / no-dos_mcp litmus)."""
    offenders = []
    for py in sorted(_SRC_DOS.rglob("*.py")):
        if "benchmark" in _imports_in(py):
            offenders.append(py.relative_to(_REPO))
    assert not offenders, f"kernel modules import benchmark (one-way arrow violated): {offenders}"


# --------------------------------------------------------- load the consumer-side modules
def _load_bench_module(name: str):
    """Import a benchmark/ top-level helper the way `python -m benchmark._run` does:
    with benchmark/ on sys.path so `import _arms` / `import registry` resolve."""
    if str(_BENCH) not in sys.path:
        sys.path.insert(0, str(_BENCH))
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _BENCH / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    # register BEFORE exec so dataclasses with string annotations can resolve
    # cls.__module__ during field processing (the InitVar/default_factory path).
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_registry_arms_match_shared_vocabulary():
    """Every arm any entrypoint declares resolves through the shared _arms vocabulary
    — there is no second, drifting copy of {arm -> DOS_* env}."""
    _arms = _load_bench_module("_arms")
    registry = _load_bench_module("registry")
    for spec in registry.BENCHMARKS.values():
        for e in spec.entrypoints:
            if e.arm:
                # must be a known arm, and registry.arm_env_for == _arms.arm_env (same source)
                assert e.arm in _arms.ARM_ENV, f"{spec.name}/{e.name} arm {e.arm!r} not in _arms"
                assert registry.arm_env_for(e.arm) == _arms.arm_env(e.arm)


def test_registry_is_well_formed():
    registry = _load_bench_module("registry")
    for spec in registry.BENCHMARKS.values():
        assert spec.entrypoints, f"{spec.name} has no entrypoints"
        for e in spec.entrypoints:
            assert e.cost in ("free", "paid"), f"{spec.name}/{e.name} bad cost {e.cost!r}"
            for pr in e.prereqs:
                assert pr.kind in registry.PREREQ_KINDS, \
                    f"{spec.name}/{e.name} bad prereq kind {pr.kind!r}"
            # every {token} in the argv must have a default (so a bare `run` works)
            for tok in e.argv:
                if tok.startswith("{") and tok.endswith("}"):
                    assert tok[1:-1] in e.defaults, \
                        f"{spec.name}/{e.name} token {tok} has no default"


def test_live_ab_uses_the_shared_arms():
    """The enterpriseops live runner must source its arms from the shared module
    (the single-source refactor), so the standardized runner and live_ab agree."""
    text = (_BENCH / "enterpriseops" / "live_ab.py").read_text(encoding="utf-8")
    assert "from _arms import" in text, "live_ab.py must import the shared arm vocabulary"
    # and the inline dict literal must be GONE (no parallel copy)
    assert '"rewind_natural": {"DOS_CONSULT"' not in text, \
        "live_ab.py still has an inline _ARM_ENV copy — it must derive from _arms"


# ============================================================ cure 2: stamped run-records
def test_stamp_slug_distinguishes_arms():
    """Two arms of the SAME entry at the SAME SHA must NOT collide to one stamp file
    (the per-arm-record requirement of cure 2). The slug carries the arm."""
    _run = _load_bench_module("_run")

    class _E:  # a minimal Entrypoint stand-in (name + arm are all the slug reads)
        def __init__(self, name, arm=""):
            self.name, self.arm = name, arm

    none = _run._stamp_slug(_E("live", ""))
    warn = _run._stamp_slug(_E("live", "warn"))
    block = _run._stamp_slug(_E("live", "block"))
    assert warn != block, "two arms of one entry collide to one slug — cure-2 record loss"
    assert warn != none and block != none
    # filesystem-safe: no path separators / spaces survive
    weird = _run._stamp_slug(_E("live/x", "a b"))
    assert "/" not in weird and " " not in weird


def test_now_iso_is_a_parseable_utc_date():
    """The cure-2 `date` field is an ISO-8601 UTC timestamp a reader can order/parse."""
    import datetime
    _run = _load_bench_module("_run")
    iso = _run._now_iso()
    # round-trips through fromisoformat (py3.11+ parses the +00:00 offset)
    dt = datetime.datetime.fromisoformat(iso)
    assert dt.tzinfo is not None, "the run date must carry a timezone (UTC)"


# ============================================================ cure 5: RESULTS freshness
def test_results_stamp_roundtrips_canonical():
    """read_results_stamp parses the canonical stamp results_stamp_line emits."""
    _run = _load_bench_module("_run")
    line = _run.results_stamp_line(kernel="9.9.9", sha="deadbee", date="2026-01-02")
    p = _BENCH / "_runs_stamp_probe.md"
    try:
        p.write_text(f"# title\n{line}\n\nbody\n", encoding="utf-8")
        st = _run.read_results_stamp(p)
        assert st["found"] and st["source"] == "canon"
        assert st["kernel"] == "9.9.9" and st["sha"] == "deadbee" and st["date"] == "2026-01-02"
    finally:
        p.unlink(missing_ok=True)


def test_results_stamp_reads_legacy_grammar():
    """The legacy `# dos kernel X.Y.Z` line (already in fleet_horizon/RESULTS.txt) is
    parsed too, so an un-migrated summary is not reported as unstamped."""
    _run = _load_bench_module("_run")
    p = _BENCH / "_runs_stamp_probe.txt"
    try:
        p.write_text("# FleetHorizon results\n# dos kernel 0.6.0\n# more\n", encoding="utf-8")
        st = _run.read_results_stamp(p)
        assert st["found"] and st["source"] == "legacy" and st["kernel"] == "0.6.0"
    finally:
        p.unlink(missing_ok=True)


def test_missing_summary_is_unstamped_not_crash():
    _run = _load_bench_module("_run")
    st = _run.read_results_stamp(_BENCH / "does-not-exist.md")
    assert st["found"] is False and st["source"] == "none"


def test_committed_summaries_carry_a_parseable_stamp():
    """Every benchmark that DECLARES a committed results_summary must carry a parseable
    provenance stamp — else cure 5's `status` cannot judge the published numbers' freshness."""
    _run = _load_bench_module("_run")
    registry = _load_bench_module("registry")
    for spec in registry.BENCHMARKS.values():
        if not spec.results_summary:
            continue
        path = _REPO / spec.results_summary
        assert path.is_file(), f"{spec.name} declares {spec.results_summary} but it is missing"
        st = _run.read_results_stamp(path)
        assert st["found"], (
            f"{spec.name}'s committed summary {spec.results_summary} carries no "
            f"dos-bench-stamp / legacy kernel line — `status` cannot judge its freshness")
        assert st["kernel"], f"{spec.name}'s stamp has no kernel version"

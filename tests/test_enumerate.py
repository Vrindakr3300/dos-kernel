"""Tests for `dos.enumerate` — the phase-list producer (docs/168 Concept 1, docs/207 Phase 2).

Groups:
  * unit cases — generic markdown headings, series-anchored ids, the data-table
    trap rejection, code-fence skip, meta-shipped, parent/child rollup.
  * degrade-never-crash — empty/malformed body → typed DriftNote, never a raise,
    never a silently-empty universe (the picker-invisibility cure).
  * the `[enumerate]` grammar config seam (grammar_from_table / load_from_toml /
    with_series), modelled on `dos.stamp`.
  * `TestByteParityJob` — THE byte-parity gate docs/207 §Phase 2 names: replay
    over the `job` repo's plan docs and assert `enumerate_units` produces the
    IDENTICAL unit universe + shipped/remaining partition the host's
    `derive_phase_universe` does. Skips cleanly when the job repo is absent.
  * the module-naming litmus — no `from dos import enumerate` (bare) anywhere
    under src/, so the builtin is never shadowed (docs/207-seam-ledger §4.1).
"""
from __future__ import annotations

import glob
import os
import re
import sys

import pytest

from dos import enumerate as _enumerate
from dos.enumerate import EnumerateGrammar, enumerate_units


# ---------------------------------------------------------------------------
# Generic markdown grammar (no series).
# ---------------------------------------------------------------------------


class TestGenericGrammar:
    def test_numbered_headings_enumerate(self):
        doc = "### 1. Set up\nbody\n### 2 — Wire it\nbody\n### 3. Finish\n"
        e = enumerate_units(doc)
        assert e.units == ("1", "2", "3")

    def test_shipped_stamp_partitions(self):
        doc = "### 1. Setup\nDone. — SHIPPED 2026-01-01\n### 2. Next\nnot done\n"
        e = enumerate_units(doc)
        assert "1" in e.shipped
        assert "2" in e.remaining

    def test_empty_body_is_typed_drift_not_crash(self):
        e = enumerate_units("")
        assert e.units == ()
        assert any(d.kind == "empty" for d in e.drift)

    def test_no_units_body_is_typed_empty(self):
        e = enumerate_units("# A doc with prose and no numbered headings.\n")
        assert e.units == ()
        assert any(d.kind == "empty" for d in e.drift)

    def test_none_body_does_not_raise(self):
        e = enumerate_units(None)
        assert e.units == ()
        assert any(d.kind == "empty" for d in e.drift)


# ---------------------------------------------------------------------------
# Series-anchored grammar (the reference shape).
# ---------------------------------------------------------------------------


class TestSeriesGrammar:
    def test_series_headings_enumerate(self):
        doc = "### AUTH0 — base\n### AUTH1 — refresh\n### AUTH2 — logout\n"
        e = enumerate_units(doc, grammar=EnumerateGrammar(series="AUTH"))
        assert e.units == ("AUTH0", "AUTH1", "AUTH2")

    def test_data_table_trap_is_rejected(self):
        # The anti-brittleness core: a data table whose first cells are NOT the
        # series must not enumerate (the FQ/PPG trap).
        doc = (
            "### AUTH1 — real phase\n"
            "| Class | Count |\n|---|---|\n| (c) | 25 |\n| AWP | other plan |\n"
        )
        e = enumerate_units(doc, grammar=EnumerateGrammar(series="AUTH"))
        assert e.units == ("AUTH1",)

    def test_code_fence_phase_id_does_not_enumerate(self):
        doc = "### AUTH1 — real\n```\n### AUTH9 — in a code sample\n```\n"
        e = enumerate_units(doc, grammar=EnumerateGrammar(series="AUTH"))
        assert e.units == ("AUTH1",)

    def test_meta_shipped_forces_shipped(self):
        doc = "### AUTH0 — base\n### AUTH1 — refresh\n"
        e = enumerate_units(
            doc, grammar=EnumerateGrammar(series="AUTH"), meta_shipped=["AUTH0"]
        )
        assert "AUTH0" in e.shipped
        assert e.by_unit["AUTH0"].shipped_by == "meta-shipped"

    def test_parent_child_rollup(self):
        doc = (
            "### AUTH1 — parent\n"
            "#### AUTH1.1 — child a — SHIPPED 2026-01-01\n"
            "#### AUTH1.2 — child b — SHIPPED 2026-01-02\n"
        )
        g = EnumerateGrammar(series="AUTH", rollup_parents=True)
        e = enumerate_units(doc, grammar=g)
        assert "AUTH1" in e.shipped
        assert e.by_unit["AUTH1"].shipped_by == "child-rollup"

    def test_rollup_blocked_by_not_done_parent(self):
        doc = (
            "### AUTH1 — parent (still in progress)\n"
            "#### AUTH1.1 — child — SHIPPED 2026-01-01\n"
        )
        g = EnumerateGrammar(series="AUTH", rollup_parents=True)
        e = enumerate_units(doc, grammar=g)
        assert "AUTH1" in e.remaining  # the not-done guard

    def test_cached_list_ghost_is_drift(self):
        # meta-shipped names a unit the body never declares → list_table_mismatch.
        doc = "### AUTH1 — only one\n"
        e = enumerate_units(
            doc, grammar=EnumerateGrammar(series="AUTH"), meta_shipped=["AUTH9"]
        )
        assert any(d.kind == "list_table_mismatch" for d in e.drift)


# ---------------------------------------------------------------------------
# The `[enumerate]` config seam.
# ---------------------------------------------------------------------------


class TestGrammarTable:
    def test_unknown_key_raises(self):
        with pytest.raises(ValueError):
            _enumerate.grammar_from_table({"bogus": 1})

    def test_series_is_not_a_table_key(self):
        # series is per-plan, never repo-wide — declaring it raises.
        with pytest.raises(ValueError):
            _enumerate.grammar_from_table({"series": "AUTH"})

    def test_known_keys_override(self):
        g = _enumerate.grammar_from_table(
            {"scan_tables": False, "rollup_parents": True, "style": "series"}
        )
        assert g.scan_tables is False
        assert g.rollup_parents is True
        assert g.style == "series"

    def test_with_series_layers_per_plan(self):
        base = _enumerate.GENERIC_GRAMMAR
        g = _enumerate.with_series(base, "auth")
        assert g.series == "AUTH"
        assert g.style == "series"  # flipped from generic

    def test_load_from_toml_absent_is_base(self, tmp_path):
        g = _enumerate.load_from_toml(tmp_path / "nope.toml")
        assert g is _enumerate.GENERIC_GRAMMAR

    def test_load_from_toml_reads_table(self, tmp_path):
        p = tmp_path / "dos.toml"
        p.write_text("[enumerate]\nscan_tables = false\nstyle = \"series\"\n", encoding="utf-8")
        g = _enumerate.load_from_toml(p)
        assert g.scan_tables is False
        assert g.style == "series"

    def test_to_from_dict_round_trips(self):
        g = EnumerateGrammar(series="X", scan_tables=False, rollup_parents=True)
        assert EnumerateGrammar.from_dict(g.to_dict()) == g


# ---------------------------------------------------------------------------
# Phase 2c — enumerate as the doc-side producer of the declared extent.
# (The honest task: NOT removing a non-existent callback — supplying the doc-side
#  declared set so the closed concept oracle→enumerate→completion closes.)
# ---------------------------------------------------------------------------


class TestDeclaredExtent:
    def test_declared_extent_is_full_universe_in_order(self):
        doc = "### AUTH0 — base — SHIPPED 2026-01-01\n### AUTH1 — refresh\n### AUTH2 — out\n"
        e = enumerate_units(doc, grammar=EnumerateGrammar(series="AUTH"))
        assert _enumerate.declared_extent(e) == ("AUTH0", "AUTH1", "AUTH2")

    def test_residual_from_enumeration_is_remaining(self):
        doc = "### AUTH0 — base — SHIPPED 2026-01-01\n### AUTH1 — refresh\n### AUTH2 — out\n"
        e = enumerate_units(doc, grammar=EnumerateGrammar(series="AUTH"))
        # AUTH0 shipped (stamp) → residual is the rest, end-to-end, no callback.
        assert _enumerate.residual_from_enumeration(e) == ("AUTH1", "AUTH2")

    def test_doc_only_residual_needs_no_intent_ledger(self):
        # The modularity payoff: a doc-declared workspace computes "what's left"
        # from the plan doc alone (enumerate folds the ship verdicts itself).
        doc = "### 1. a\nSHIPPED 2026-01-01\n### 2. b\n### 3. c\nSHIPPED 2026-01-02\n"
        e = enumerate_units(doc)
        assert _enumerate.residual_from_enumeration(e) == ("2",)


# ---------------------------------------------------------------------------
# The byte-parity gate (docs/207 Phase 2) — replay over the job repo offline.
# ---------------------------------------------------------------------------

# The job reference repo is an external sibling clone of this repo, resolved from
# this file's location (never a hardcoded machine path). The gate below skips when
# it is absent — which it is anywhere but a dev box with both repos checked out.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JOB_ROOT = os.path.join(os.path.dirname(_REPO_ROOT), "job")
_JOB_PLANS = os.path.join(_JOB_ROOT, "docs", "_plans")
_JOB_SCRIPTS = os.path.join(_JOB_ROOT, "scripts")


def _parse_job_meta(body: str) -> dict:
    m = re.search(r"<!--\s*plan-meta\b(.*?)-->", body, re.DOTALL)
    block = m.group(1) if m else ""
    out: dict = {}
    for key in ("id", "phase_prefix"):
        km = re.search(rf"(?im)^\s*{key}\s*:\s*([A-Za-z][A-Za-z0-9.+\-]*)", block)
        if km:
            out[key] = km.group(1).strip()
    sm = re.search(r"(?im)^\s*shipped\s*:\s*\[(.*?)\]", block)
    out["shipped"] = (
        [x.strip().strip('"').strip("'") for x in sm.group(1).split(",") if x.strip()]
        if sm
        else []
    )
    return out


@pytest.mark.skipif(
    not (os.path.isdir(_JOB_PLANS) and os.path.isfile(os.path.join(_JOB_SCRIPTS, "plan_phases.py"))),
    reason="the job reference repo is not present on this machine (offline gate)",
)
class TestByteParityJob:
    """THE byte-parity gate: the relocated `enumerate` must reproduce the host
    `derive_phase_universe`'s unit universe AND shipped/remaining partition,
    byte-for-byte, over the job repo's committed plan docs (offline, $0)."""

    def _host(self):
        if _JOB_SCRIPTS not in sys.path:
            sys.path.insert(0, _JOB_SCRIPTS)
        import plan_phases  # type: ignore
        return plan_phases

    def _doc_plans(self):
        host = self._host()
        out = []
        for p in sorted(glob.glob(os.path.join(_JOB_PLANS, "*.md"))):
            body = open(p, encoding="utf-8", errors="replace").read()
            meta = _parse_job_meta(body)
            series = (meta.get("id") or "").upper()
            pp = meta.get("phase_prefix")
            if not series and not pp:
                continue
            out.append((os.path.basename(p), body, series, pp, meta.get("shipped", [])))
        return host, out

    def test_at_least_some_doc_plans_present(self):
        _host, plans = self._doc_plans()
        assert len(plans) >= 5, "expected ≥5 doc-resolvable job plans for the gate"

    def test_unit_universe_is_byte_identical(self):
        host, plans = self._doc_plans()
        mismatches = []
        for name, body, series, pp, shipped in plans:
            host_d = host.derive_phase_universe(body, series, shipped=shipped, phase_prefix=pp)
            host_units = set(host_d.remaining) | set(host_d.shipped)
            g = EnumerateGrammar(series=(pp or series).upper(), style="series", rollup_parents=True)
            ke = enumerate_units(body, grammar=g, meta_shipped=shipped)
            if set(ke.units) != host_units:
                mismatches.append((name, sorted(host_units - set(ke.units)), sorted(set(ke.units) - host_units)))
        assert not mismatches, f"unit-universe drift vs host deriver: {mismatches}"

    def test_shipped_remaining_partition_is_byte_identical(self):
        host, plans = self._doc_plans()
        mismatches = []
        for name, body, series, pp, shipped in plans:
            host_d = host.derive_phase_universe(body, series, shipped=shipped, phase_prefix=pp)
            g = EnumerateGrammar(series=(pp or series).upper(), style="series", rollup_parents=True)
            ke = enumerate_units(body, grammar=g, meta_shipped=shipped)
            if set(host_d.shipped) != set(ke.shipped) or set(host_d.remaining) != set(ke.remaining):
                mismatches.append((name, sorted(set(host_d.shipped) ^ set(ke.shipped))))
        assert not mismatches, f"shipped/remaining partition drift vs host deriver: {mismatches}"


# ---------------------------------------------------------------------------
# Module-naming litmus — the enumerate.py shadow guard (docs/207-seam-ledger §4.1).
# ---------------------------------------------------------------------------


def test_no_bare_from_dos_import_enumerate_under_src():
    """No kernel module may do `from dos import enumerate` (bare) — it would shadow
    the builtin in that scope. Consumers use `from dos import enumerate as _…` or
    `import dos.enumerate`. Grep-checkable, pinned here."""
    src_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src", "dos")
    bare = re.compile(r"^\s*from dos import enumerate\s*$", re.MULTILINE)
    offenders = []
    for path in glob.glob(os.path.join(src_root, "**", "*.py"), recursive=True):
        text = open(path, encoding="utf-8", errors="replace").read()
        if bare.search(text):
            offenders.append(os.path.relpath(path, src_root))
    assert not offenders, f"bare `from dos import enumerate` shadows the builtin in: {offenders}"

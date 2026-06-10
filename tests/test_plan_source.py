"""Tests for the plan-source seam (`dos.plan_source`) — the declared row source.

The plan-source seam is the kernel-pure analogue of `dos.judges`: a Protocol + a frozen
`PlanRow` + a fail-to-empty runner + a by-name resolver over `dos.plan_sources` + the
built-in `MarkdownPlanSource`. These tests pin the contracts that keep it honest:

  * the markdown harvester reads `### N. PLAN PHASE` headings + `- **PHASE` bullets and
    the CLAIMED status off each section, from the DECLARED `plans_glob` — never a literal;
  * `run_plan_source` fails to EMPTY (a raising / bad-return source contributes nothing,
    never a fabricated row), the inverse of `run_judge`'s fail-to-abstain;
  * built-ins resolve first and are unshadowable; an unknown name fails loud;
  * the no-host litmus — the seam + built-in name no host directory / lane / commit prefix.

Pure throughout: no git, no oracle — a source only enumerates candidates.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from dos import plan_source as PS
from dos.config import default_config


# ---------------------------------------------------------------------------
# The markdown harvester — `### N. PLAN PHASE` + `- **PHASE` + claimed status.
# ---------------------------------------------------------------------------


class TestMarkdownHarvest:
    def test_numbered_heading_yields_plan_phase(self):
        rows = PS._harvest_markdown(
            "## 2. Next items\n### 1. IF IF4.1 — registry split\n", "p.md")
        assert [(r.plan, r.phase) for r in rows] == [("IF", "IF4.1")]
        assert rows[0].doc_path == "p.md"

    def test_section_shipped_stamp_is_claimed_shipped(self):
        text = (
            "### 1. IF IF4.1 — registry split\n"
            "Some prose. · SHIPPED 2026-05-01 abc1234\n"
            "### 2. IF IF4.2 — ancestry check\n"
            "still open, no stamp\n"
        )
        rows = {(r.plan, r.phase): r for r in PS._harvest_markdown(text, "p.md")}
        assert rows[("IF", "IF4.1")].claimed_status == PS.CLAIMED_SHIPPED
        assert rows[("IF", "IF4.2")].claimed_status == PS.CLAIMED_OPEN

    def test_soak_word_is_claimed_blocked(self):
        rows = PS._harvest_markdown(
            "### 1. RS RS4 — surfacing\nawaiting SOAK until 2026-06-04\n", "p.md")
        assert rows[0].claimed_status == PS.CLAIMED_BLOCKED

    def test_bullet_subphase_inherits_enclosing_numbered_heading_plan_id(self):
        """A bolded `- **PHASE` bullet inherits the most-recent NUMBERED heading's plan
        token. Only a numbered `### N. PLAN …` heading scopes bullets — a prose heading
        does not (that is what stops `### Design …` lending its word to step bullets)."""
        text = (
            "### 4. AUTH AUTH4 — the auth cluster\n"
            "- **AUTH4.1 — registry split · SHIPPED\n"
            "- **AUTH4.2 — ancestry check\n"
        )
        rows = PS._harvest_markdown(text, "p.md")
        assert [(r.plan, r.phase) for r in rows] == [
            ("AUTH", "AUTH4"), ("AUTH", "AUTH4.1"), ("AUTH", "AUTH4.2")]
        by_phase = {r.phase: r for r in rows}
        assert by_phase["AUTH4.1"].claimed_status == PS.CLAIMED_SHIPPED
        assert by_phase["AUTH4.2"].claimed_status == PS.CLAIMED_OPEN

    def test_prose_heading_does_not_scope_bullets(self):
        """The live-repo failure mode: a prose `### Why …` heading + bolded design-
        principle bullets must yield NOTHING (no phantom `(Why, never-stall)` phase)."""
        text = (
            "### Why never-stall is the floor\n"
            "- **Rendering is downstream of the kernel** — never leak policy.\n"
            "- **Built-ins stay built-in.**\n"
        )
        assert PS._harvest_markdown(text, "p.md") == []

    def test_digit_guard_drops_prose_pairs(self):
        """`## 2. Next items` and a digit-less heading pair never harvest as a phase."""
        assert PS._harvest_markdown("## 2. Next items — overview\n", "p.md") == []
        assert PS._harvest_markdown("### 1. Out TOML — note\n", "p.md") == []

    def test_prose_heading_does_not_leak_plan_id_to_bullets(self):
        """A PROSE numbered heading (`### 1. The rationale — why`) must NOT scope the
        bullets below it: leaving its first token (`The`) as the plan id would let a
        digit-bearing bullet inherit a phantom plan (`(The, v2.0)`). The heading clears
        the plan scope when its OWN second token isn't a phase id (review finding)."""
        text = (
            "### 1. The rationale — why\n"
            "- **v2.0 — ship it\n"
            "- **P3: do the thing\n"
        )
        assert PS._harvest_markdown(text, "p.md") == []

    def test_bare_ordinal_phase_is_not_harvested(self):
        """A prose heading whose 2nd token is a BARE ORDINAL (`### 1. Phase 2 of 3 — done`)
        must NOT harvest the phantom phase `(Phase, 2)` — a real phase id needs a letter
        AND a digit, so a bare `2` is rejected (the over-claim-noise cut)."""
        assert PS._harvest_markdown("### 1. Phase 2 of 3 — done\n", "p.md") == []
        # The documented tradeoff: the bare-ordinal `### Phase 6:` dialect is under-
        # harvested by the default (ship a dos.plan_sources plugin for it).
        assert PS._harvest_markdown("### Phase 6: the sixth phase\n- **6 — do it\n", "p.md") == []

    def test_letter_and_digit_ids_are_harvested(self):
        """Real phase ids — series+ordinal — are all recognised: IF4.1, P2, AUTH4, 1a."""
        for plan, phase in [("IF", "IF4.1"), ("AUTH", "P2"), ("RS", "RS4"), ("STEP", "1a")]:
            rows = PS._harvest_markdown(f"### 1. {plan} {phase} — title\n", "p.md")
            assert [(r.plan, r.phase) for r in rows] == [(plan, phase)], (plan, phase)

    def test_shipped_stamp_does_not_bleed_across_section_boundary(self):
        """A SHIPPED stamp in a LATER phase's section body must not leak into an EARLIER
        phase — the claimed status is read only from each heading's own section slice."""
        text = (
            "### 1. IF IF4.1 — split\n"
            "still open, no stamp here\n"
            "### 2. IF IF4.2 — ancestry\n"
            "· SHIPPED 2026-05-01 abc1234\n"
        )
        rows = {(r.plan, r.phase): r for r in PS._harvest_markdown(text, "p.md")}
        assert rows[("IF", "IF4.1")].claimed_status == PS.CLAIMED_OPEN     # NOT bled-shipped
        assert rows[("IF", "IF4.2")].claimed_status == PS.CLAIMED_SHIPPED

    def test_dedup_preserves_first_seen_order(self):
        text = (
            "### 1. IF IF4.1 — first\n"
            "### 2. IF IF4.1 — a duplicate heading\n"
            "### 3. IF IF5 — later\n"
        )
        rows = PS._harvest_markdown(text, "p.md")
        assert [(r.plan, r.phase) for r in rows] == [("IF", "IF4.1"), ("IF", "IF5")]

    def test_no_recognised_heading_yields_empty(self):
        assert PS._harvest_markdown("# Title\n\nNarrative with no phase headings.\n", "p.md") == []


# ---------------------------------------------------------------------------
# MarkdownPlanSource over the declared plans_glob (live, against a tmp tree).
# ---------------------------------------------------------------------------


class TestMarkdownPlanSource:
    def test_reads_declared_glob_under_root(self, tmp_path: Path):
        cfg = default_config(tmp_path)  # plans_glob defaults to docs/**/*-plan.md
        plans = tmp_path / "docs" / "_plans"
        plans.mkdir(parents=True)
        (plans / "if-plan.md").write_text(
            "### 1. IF IF4.1 — split · SHIPPED 2026-05-01 abc\n"
            "### 2. IF IF4.2 — ancestry\n",
            encoding="utf-8",
        )
        rows = PS.MarkdownPlanSource().rows(cfg)
        assert [(r.plan, r.phase) for r in rows] == [("IF", "IF4.1"), ("IF", "IF4.2")]
        assert rows[0].claimed_status == PS.CLAIMED_SHIPPED
        # The doc_path is workspace-relative for drill-in.
        assert rows[0].doc_path.replace("\\", "/") == "docs/_plans/if-plan.md"

    def test_no_plans_yields_empty(self, tmp_path: Path):
        """A repo with NO plan docs yields [] — the plan view's no-plan floor."""
        cfg = default_config(tmp_path)
        assert PS.MarkdownPlanSource().rows(cfg) == []

    def test_directory_matching_glob_is_skipped(self, tmp_path: Path):
        """A DIRECTORY whose name matches the glob is skipped (only files are read)."""
        cfg = default_config(tmp_path)
        plans = tmp_path / "docs" / "_plans"
        plans.mkdir(parents=True)
        (plans / "subdir-plan.md").mkdir()  # a dir named like a plan file
        (plans / "real-plan.md").write_text("### 1. IF IF4.1 — split\n", encoding="utf-8")
        rows = PS.MarkdownPlanSource().rows(cfg)
        assert [(r.plan, r.phase) for r in rows] == [("IF", "IF4.1")]

    def test_non_utf8_file_degrades_safely(self, tmp_path: Path):
        """A file with invalid UTF-8 bytes is read with errors='replace', never crashes."""
        cfg = default_config(tmp_path)
        plans = tmp_path / "docs" / "_plans"
        plans.mkdir(parents=True)
        (plans / "bad-plan.md").write_bytes(b"### 1. IF IF4.1 \xff\xfe bad bytes\n")
        # Must not raise; the heading may or may not parse, but the call is safe.
        rows = PS.MarkdownPlanSource().rows(cfg)
        assert isinstance(rows, list)

    def test_overridden_glob_is_honoured(self, tmp_path: Path):
        """A foreign repo whose plans live in planning/*.md is read via the declared glob,
        NOT a hardcoded docs/_plans literal."""
        base = default_config(tmp_path)
        cfg = dataclasses.replace(base, paths=base.paths.with_overrides({"plans_glob": "planning/*.md"}))
        planning = tmp_path / "planning"
        planning.mkdir()
        (planning / "roadmap.md").write_text("### 1. AUTH P2 — login\n", encoding="utf-8")
        # The default docs/_plans location has a decoy that must be IGNORED.
        decoy = tmp_path / "docs" / "_plans"
        decoy.mkdir(parents=True)
        (decoy / "x-plan.md").write_text("### 1. DECOY D1 — ignore me\n", encoding="utf-8")
        rows = PS.MarkdownPlanSource().rows(cfg)
        assert [(r.plan, r.phase) for r in rows] == [("AUTH", "P2")]


# ---------------------------------------------------------------------------
# run_plan_source — fail-to-EMPTY (the inverse of run_judge's fail-to-abstain).
# ---------------------------------------------------------------------------


class TestRunPlanSourceFailSafe:
    def test_raising_source_yields_empty(self):
        class Boom:
            name = "boom"
            def rows(self, config):
                raise RuntimeError("source down")
        assert PS.run_plan_source(Boom(), object()) == []

    def test_non_list_return_yields_empty(self):
        class Bad:
            name = "bad"
            def rows(self, config):
                return "not a list"
        assert PS.run_plan_source(Bad(), object()) == []

    def test_non_planrow_items_are_dropped(self):
        class Mixed:
            name = "mixed"
            def rows(self, config):
                return [PS.PlanRow(plan="IF", phase="IF4.1"), {"plan": "X", "phase": "Y"}, None]
        out = PS.run_plan_source(Mixed(), object())
        assert [(r.plan, r.phase) for r in out] == [("IF", "IF4.1")]

    def test_out_of_vocab_claimed_status_normalised_to_unknown(self):
        class Smuggle:
            name = "smuggle"
            def rows(self, config):
                return [PS.PlanRow(plan="IF", phase="IF4.1", claimed_status="totally-done")]
        out = PS.run_plan_source(Smuggle(), object())
        assert out[0].claimed_status == PS.CLAIMED_UNKNOWN

    def test_valid_claimed_status_preserved(self):
        class Ok:
            name = "ok"
            def rows(self, config):
                return [PS.PlanRow(plan="IF", phase="IF4.1", claimed_status=PS.CLAIMED_SHIPPED)]
        out = PS.run_plan_source(Ok(), object())
        assert out[0].claimed_status == PS.CLAIMED_SHIPPED


# ---------------------------------------------------------------------------
# Resolution — built-ins first + unshadowable; unknown fails loud.
# ---------------------------------------------------------------------------


class TestResolution:
    def test_markdown_is_a_built_in(self):
        src = PS.resolve_plan_source("markdown")
        assert isinstance(src, PS.MarkdownPlanSource)

    def test_unknown_name_fails_loud(self):
        with pytest.raises(ValueError) as ei:
            PS.resolve_plan_source("nope")
        assert "unknown plan source" in str(ei.value)
        assert "markdown" in str(ei.value)  # names the known set

    def test_active_names_include_markdown(self):
        assert "markdown" in PS.active_plan_source_names()

    def test_default_rows_uses_markdown(self, tmp_path: Path):
        cfg = default_config(tmp_path)
        plans = tmp_path / "docs" / "_plans"
        plans.mkdir(parents=True)
        (plans / "a-plan.md").write_text("### 1. AUTH P1 — seed\n", encoding="utf-8")
        rows = PS.default_rows(cfg)
        assert [(r.plan, r.phase) for r in rows] == [("AUTH", "P1")]


# ---------------------------------------------------------------------------
# THE NO-HOST LITMUS — the seam + built-in name no host directory/lane/prefix.
# The plan-altitude analogue of "kernel imports no host" / the SKP skill litmus.
# ---------------------------------------------------------------------------


class TestNoHostLitmus:
    def test_module_code_names_no_host(self):
        """`plan_source.py`'s CODE must not import a host or use a host dir/lane/prefix as
        a value — every host specific comes from config.paths.plans_glob (declared data).

        Matches the established kernel-module litmus (`test_home_layering.test_home_names_
        no_host`): the explanatory DOCSTRING may NAME the rule ("no hardcoded docs/_plans
        literal") — that prose is the contract being stated, not a violation. So we strip
        the module docstring + comments and assert the executable code carries no host
        token (import or string literal)."""
        import ast
        src = Path(PS.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        # Drop the module docstring node, then unparse the remaining code (no comments
        # survive parse) — what's left is the executable body + the kept string literals.
        body = tree.body[1:] if (tree.body and isinstance(tree.body[0], ast.Expr)
                                 and isinstance(getattr(tree.body[0], "value", None), ast.Constant)
                                 and isinstance(tree.body[0].value.value, str)) else tree.body
        code = "\n".join(ast.unparse(n) for n in body)
        # No host import.
        for tok in ("import job", "drivers.job", "drivers.llm_judge"):
            assert tok not in code, f"plan_source code names a host: {tok!r}"
        # No host plan directory / lane / commit prefix as a CODE literal.
        for tok in ("docs/_plans", "output/next-up", "docs/dispatch:",
                    '"apply"', "'apply'", '"tailor"', "'tailor'", '"discovery"', "'discovery'"):
            assert tok not in code, f"plan_source code hardcodes a host literal: {tok!r}"

    def test_default_glob_is_generic(self, tmp_path: Path):
        """The generic default plans_glob is a domain-free `docs/**/*-plan.md`, and the
        source reads it from config — it does not bake in the reference app's tree."""
        cfg = default_config(tmp_path)
        assert cfg.paths.plans_glob == "docs/**/*-plan.md"

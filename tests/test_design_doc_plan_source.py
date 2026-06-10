"""Tests for the design-doc plan dialect (`dos.drivers.design_doc_plan`, docs/293).

The first occupant of the `dos.plan_sources` entry-point group — DOS's own
`docs/NN_<slug>-plan.md` prose dialect, dogfooding the axis the kernel ships instead
of loosening the built-in `markdown` harvester. These tests pin the closed grammar:

  * the `Phase N` keyword form and the id-led series form harvest; every observed
    noise shape (numbered sections, prose words, version refs, `## Phased roadmap`)
    does not — the under-harvest posture, held shape by shape;
  * claims come from the heading line's CLOSED vocabulary (word-bounded SHIPPED /
    upper DONE / ✅ / the kernel's blocked words) or the leading-✅ `> **Status:**`
    plan-wide close-out — never mined from body prose or 🚧 mixed-status sentences;
  * the plan id is the doc path minus `.md` — the positional string the oracle takes;
  * the source is resolvable by its entry-point name and never shadows the built-in.

Pure throughout (no git, no oracle) except the entry-point resolution tests, which
exercise the installed package metadata — the load-bearing wiring itself.
"""

from __future__ import annotations

from pathlib import Path

from dos import plan_source as PS
from dos.config import default_config
from dos.drivers import design_doc_plan as DDP


def _harvest(text: str, doc_path: str = "docs/82_liveness-oracle-plan.md"):
    return DDP._harvest_design_doc(text, doc_path)


# ---------------------------------------------------------------------------
# The keyword form — `## Phase N — title` (the bare-ordinal dialect the built-in
# deliberately rejects; the literal keyword is what makes it trustworthy here).
# ---------------------------------------------------------------------------


class TestKeywordForm:
    def test_phase_heading_yields_row_with_doc_derived_plan(self):
        rows = _harvest("## Phase 1 — `[lanes]` read-back (the throughline)\n")
        assert [(r.plan, r.phase) for r in rows] == [
            ("docs/82_liveness-oracle-plan", "Phase 1")]
        assert rows[0].doc_path == "docs/82_liveness-oracle-plan.md"

    def test_all_heading_depths_and_colon_separator(self):
        for h in ("## Phase 0 — base", "### Phase 2: wire it", "#### Phase 3 — rail"):
            assert len(_harvest(h + "\n")) == 1, h

    def test_sub_lettered_and_dotted_ordinals(self):
        rows = _harvest("## Phase 1a — split\n### Phase 3.2 — sub\n")
        assert [r.phase for r in rows] == ["Phase 1a", "Phase 3.2"]

    def test_prose_phase_words_do_not_match(self):
        """`## Phased roadmap`, `## Phases`, a numbered `## 2. Phases` section, and a
        body sentence are all noise — the keyword form anchors `Phase <digit>` at the
        heading start."""
        noise = (
            "## Phased roadmap\n"
            "## Phases (throughline-first — each ships an enabled slice)\n"
            "## 2. Phases\n"
            "The plan has a Phase 9 in prose, not a heading.\n"
        )
        assert _harvest(noise) == []

    def test_inline_shipped_mark_is_claimed_shipped(self):
        rows = _harvest("## Phase 1 — the verdict — ✅ SHIPPED 2026-06-01\n")
        assert rows[0].claimed_status == PS.CLAIMED_SHIPPED

    def test_lowercase_shipped_in_heading_is_a_claim(self):
        # docs/290's `### Phase 1 — shipped (2026-06-10): the red/green witness`.
        rows = _harvest("### Phase 1 — shipped (2026-06-10): the red/green witness\n")
        assert rows[0].claimed_status == PS.CLAIMED_SHIPPED

    def test_upper_done_is_a_claim_lower_done_is_prose(self):
        assert _harvest("## Phase 0 — DONE by the concurrent agent\n")[0].claimed_status \
            == PS.CLAIMED_SHIPPED
        assert _harvest("## Phase 1 — get it done right\n")[0].claimed_status \
            == PS.CLAIMED_OPEN

    def test_bare_checkmark_is_a_claim(self):
        # docs/72's `## Phase 1 — … (the throughline) ✅`.
        rows = _harvest("## Phase 1 — the Renderer protocol (the throughline) ✅\n")
        assert rows[0].claimed_status == PS.CLAIMED_SHIPPED

    def test_phase_shipped_module_name_is_not_a_claim(self):
        """The word-boundary trap: `phase_shipped` (the module) must not read as a
        SHIPPED claim — `_` is a word char, so `\\bSHIPPED\\b` cannot match inside it."""
        rows = _harvest("## Phase 1 — WIRE the convention into phase_shipped\n")
        assert rows[0].claimed_status == PS.CLAIMED_OPEN

    def test_blocked_vocabulary_reuses_kernel_words(self):
        rows = _harvest("## Phase 2 — GATED on the publish pipeline\n")
        assert rows[0].claimed_status == PS.CLAIMED_BLOCKED

    def test_future_parenthetical_stays_open(self):
        rows = _harvest("### Phase 3 — value-aware spawn ranking (future)\n")
        assert rows[0].claimed_status == PS.CLAIMED_OPEN

    def test_body_prose_never_sets_a_claim(self):
        """The claim is read from the HEADING LINE ONLY — a body that says SHIPPED
        (design docs quote the word constantly) must not upgrade the claim."""
        rows = _harvest("## Phase 2 — the seam\nThe sibling plan ✅ SHIPPED already.\n")
        assert rows[0].claimed_status == PS.CLAIMED_OPEN


# ---------------------------------------------------------------------------
# The id-led series form — `### GHF1 — title` (letter-start, digit, separator).
# ---------------------------------------------------------------------------


class TestIdLedForm:
    def test_series_id_headings_harvest(self):
        text = (
            "### GHF1 — `pretool` served by Go, end-to-end\n"
            "### ISV0 — Baseline (measure-then-change)\n"
            "### F2 — A natural collision stream — *$0 measure*\n"
        )
        assert [r.phase for r in _harvest(text)] == ["GHF1", "ISV0", "F2"]

    def test_digitless_token_is_prose_not_a_phase(self):
        assert _harvest("### Design A — the *dependent-task* contrast\n") == []

    def test_digit_led_section_numbers_are_rejected(self):
        # `### 8.2.1 — Scoping RESULT`, `## 3a. How much…` — numbered-section noise.
        assert _harvest("### 8.2.1 — Scoping RESULT\n## 3a. How much is tied?\n") == []

    def test_version_shaped_token_is_rejected(self):
        assert _harvest("## v0.23.0 — registry-first installs\n") == []

    def test_separator_is_required(self):
        """An id with no em/en-dash or colon after it is a sentence, not a phase
        declaration (`### GHF1 pretool …` reads as prose)."""
        assert _harvest("### GHF1 pretool served by Go\n") == []

    def test_id_led_heading_claim_vocabulary_applies(self):
        rows = _harvest("### ISV3 — typed refusals — ✅ SHIPPED\n")
        assert rows[0].claimed_status == PS.CLAIMED_SHIPPED


# ---------------------------------------------------------------------------
# The plan-wide ✅ close-out — and the 🚧 mixed-status refusal.
# ---------------------------------------------------------------------------


class TestPlanWideStatus:
    def test_leading_checkmark_shipped_status_claims_every_phase(self):
        text = (
            "# 73 — admission predicates\n\n"
            "> **Status:** ✅ **SHIPPED** (all three phases, 2026-06-01).\n\n"
            "## Phase 1 — the verdict\n## Phase 2 — the predicate\n"
        )
        rows = _harvest(text)
        assert [r.claimed_status for r in rows] == [PS.CLAIMED_SHIPPED] * 2

    def test_mixed_status_sentence_is_not_parsed(self):
        """🚧 'Phases 1–2 shipped; Phase 3 design' must NOT plan-wide-claim — the
        per-heading marks carry those docs (the no-prose-range-mining rule)."""
        text = (
            "> **Status:** 🚧 **Phases 1–2 shipped** (2026-06-01); Phase 3 design.\n\n"
            "## Phase 1 — built — ✅ SHIPPED 2026-06-01\n"
            "## Phase 3 — still design\n"
        )
        rows = {r.phase: r for r in _harvest(text)}
        assert rows["Phase 1"].claimed_status == PS.CLAIMED_SHIPPED
        assert rows["Phase 3"].claimed_status == PS.CLAIMED_OPEN

    def test_only_the_first_status_line_is_consulted(self):
        """A later ✅ status note (docs/97's mid-doc update shape) never retro-claims
        the doc — the genre keeps the authoritative status at the top."""
        text = (
            "> **Status:** PLAN (not yet built).\n\n"
            "## Phase 1 — the seam\n\n"
            "> **Status:** ✅ **SHIPPED** (a later note).\n"
        )
        assert _harvest(text)[0].claimed_status == PS.CLAIMED_OPEN

    def test_per_heading_blocked_wins_over_plan_wide(self):
        text = (
            "> **Status:** ✅ **SHIPPED** (all phases).\n\n"
            "## Phase 1 — done\n## Phase 2 — GATED on the soak window\n"
        )
        rows = {r.phase: r for r in _harvest(text)}
        assert rows["Phase 1"].claimed_status == PS.CLAIMED_SHIPPED
        assert rows["Phase 2"].claimed_status == PS.CLAIMED_BLOCKED


# ---------------------------------------------------------------------------
# Dedup, plan-id derivation, and the source walk over the declared glob.
# ---------------------------------------------------------------------------


class TestHarvestMechanics:
    def test_duplicate_phase_keeps_first_seen_claim(self):
        """docs/290 declares `## Phase 1` as a section and `### Phase 1 — shipped` as
        its close-out record — first-seen reads open (a benign under-claim, never a
        manufactured over-claim)."""
        text = (
            "## Phase 1 — the litmus tier\n"
            "### Phase 1 — shipped (2026-06-10): the red/green witness\n"
        )
        rows = _harvest(text)
        assert [r.phase for r in rows] == ["Phase 1"]
        assert rows[0].claimed_status == PS.CLAIMED_OPEN

    def test_plan_id_strips_md_and_normalises_slashes(self):
        rows = DDP._harvest_design_doc(
            "## Phase 1 — x\n", "docs\\293_design-doc-plan-dialect-plan.md")
        assert rows[0].plan == "docs/293_design-doc-plan-dialect-plan"

    def test_doc_with_no_recognised_heading_yields_empty(self):
        # docs/75 / docs/97 / docs/263 today: numbered sections, no Phase headings.
        text = "## 1. The gap this closes\n### 4.1 RESOLVED — the registry location\n"
        assert _harvest(text) == []


class TestSourceWalk:
    def test_reads_declared_glob_under_root(self, tmp_path: Path):
        cfg = default_config(tmp_path)  # plans_glob defaults to docs/**/*-plan.md
        docs = tmp_path / "docs"
        docs.mkdir(parents=True)
        (docs / "7_seam-plan.md").write_text(
            "> **Status:** ✅ **SHIPPED** (both phases).\n\n"
            "## Phase 1 — the seam\n## Phase 2 — the rail\n",
            encoding="utf-8",
        )
        (docs / "notes.md").write_text("## Phase 9 — not in the glob\n", encoding="utf-8")
        rows = DDP.DesignDocPlanSource().rows(cfg)
        assert [(r.plan, r.phase) for r in rows] == [
            ("docs/7_seam-plan", "Phase 1"), ("docs/7_seam-plan", "Phase 2")]
        assert {r.claimed_status for r in rows} == {PS.CLAIMED_SHIPPED}

    def test_no_paths_config_yields_empty(self):
        assert DDP.DesignDocPlanSource().rows(object()) == []

    def test_runner_holds_it_to_fail_to_empty(self, tmp_path: Path):
        """Through `run_plan_source` the dialect inherits the seam's guarantee — a
        config whose glob raises contributes nothing, never a crash."""
        cfg = default_config(tmp_path)
        rows = PS.run_plan_source(DDP.DesignDocPlanSource(), cfg)
        assert rows == []


# ---------------------------------------------------------------------------
# Resolution — the entry-point wiring itself (the installed-metadata contract).
# ---------------------------------------------------------------------------


class TestResolution:
    def test_resolves_by_entry_point_name(self):
        src = PS.resolve_plan_source("design-docs")
        assert isinstance(src, DDP.DesignDocPlanSource)

    def test_listed_among_active_sources_after_the_builtin(self):
        names = PS.active_plan_source_names()
        assert "markdown" in names and "design-docs" in names
        assert names.index("markdown") < names.index("design-docs")  # built-ins first

    def test_does_not_shadow_the_builtin(self):
        assert isinstance(PS.resolve_plan_source("markdown"), PS.MarkdownPlanSource)

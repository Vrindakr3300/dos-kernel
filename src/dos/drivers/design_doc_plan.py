"""dos.drivers.design_doc_plan — the design-doc plan dialect (a `dos.plan_sources` driver).

The kernel's built-in `markdown` plan source deliberately under-harvests DOS's own
plan-doc convention (`plan_source.py` names it verbatim: *"DOS's own `### Phase N:`
design-doc dialect … wants a `dos.plan_sources` plugin, not a guess"*): its phase
tokens are bare ordinals (`Phase 1`), which the generic letter+digit guard rejects
to keep prose from harvesting as phantom phases. This module is that plugin — the
dialect of the `docs/NN_<slug>-plan.md` corpus, built per `docs/293_*`:

  * phases live under ``## Phase N — title`` / ``### Phase N: title`` headings
    (the keyword form) or ``### GHF1 — title`` series-id headings (the id-led form);
  * the plan's self-reported status lives in the HEADING line (``— ✅ SHIPPED
    2026-06-01``, ``— DONE by …``) or, plan-wide, in a leading-``✅``
    ``> **Status:**`` close-out sentence;
  * the plan id is the doc's root-relative path minus ``.md``
    (``docs/82_liveness-oracle-plan``) — the exact positional string
    `oracle.is_shipped` takes, whose ``docs/82`` head the trailer rung's
    `_series_variants` bridges to this repo's ``(docs/NN Phase M)`` ship stamps.

Why a DRIVER and not a kernel edit: the grammar above is a *host convention* — one
repo's way of writing plans — and the kernel holds no plan schema. The built-in
stays byte-identical and unshadowable; this dialect is selected by name
(``dos plan --source design-docs``) or declared as workspace data
(``[plan] source = "design-docs"`` in `dos.toml`), exactly the judges/llm_judge
split. The one-way arrow holds: this module imports the kernel seam
(`dos.plan_source`); nothing in the kernel imports it — it is discovered through
the `dos.plan_sources` entry-point group in `pyproject.toml`.

The under-harvest posture (the seam's fail direction) is kept by construction:

  * the keyword form must START the heading with the literal ``Phase <digits>`` —
    ``## Phased roadmap``, ``## 2. Phases`` and prose that merely mentions a phase
    never match;
  * the id-led token must start with a LETTER (rejects numbered-section noise:
    ``### 8.2.1 — Scoping RESULT``, ``## 3a. How much…``), contain a DIGIT
    (rejects prose words: ``### Design A — …``), not be version-shaped (rejects a
    ``### v0.23.0 — …`` release note), and be followed by an em/en-dash or colon;
  * claims are read from a CLOSED vocabulary on the heading line only — long
    design-doc bodies mention "shipped" incidentally, and a word-bounded match
    keeps ``phase_shipped`` (the module name) from reading as a claim;
  * a doc with no recognised heading yields NO rows, and `run_plan_source` holds
    the whole source to fail-to-empty like every other.
"""

from __future__ import annotations

import re
from pathlib import Path

from dos.plan_source import (
    CLAIMED_BLOCKED,
    CLAIMED_OPEN,
    CLAIMED_SHIPPED,
    PlanRow,
)


# ---------------------------------------------------------------------------
# The closed heading grammar — two shapes, each guard documented in docs/293.
# ---------------------------------------------------------------------------

# The keyword form: `## Phase 1 — title`, `### Phase 0: title`, `#### Phase 3b.2 …`.
# The heading must START with the literal keyword — that is the whole guard: a bare
# ordinal is only trusted as a phase id when the author wrote the word `Phase` in a
# heading position. The ordinal admits an optional sub-letter / dotted sub-phase
# (`1a`, `3.2`) mirroring `stamp._PHASE_LABEL_RE`'s body.
_PHASE_KEYWORD_RE = re.compile(r"^#{2,4}\s+Phase\s+(\d+[a-z]?(?:\.\d+)?)\b")

# The id-led series form: `### GHF1 — title`, `### ISV0 — …`, `### F2 — …`.
# Captures a letter-led alphanumeric token; the digit / version-shape guards are
# applied in code (clearer to test and to refuse). The separator set is the
# em/en-dash and colon ONLY — a plain hyphen would split hyphenated prose words
# (`Ground-truthed`) into a false token boundary.
_ID_LED_RE = re.compile(r"^#{2,4}\s+([A-Za-z][A-Za-z0-9.]*)\s*[—–:]")

# A version-shaped token (`v0.23.0`, `V2`) is a release reference, never a phase id
# of the doc it appears in — the heading analogue of stamp's release anchor.
_VERSION_TOKEN_RE = re.compile(r"^[vV]\d")

# The heading-line claim vocabulary (CLOSED — never mined from body prose):
#   shipped — a word-bounded SHIPPED (any case: docs/290 writes `— shipped (…)`;
#             the \b rejects the module name `phase_shipped`), an upper-case-only
#             DONE (lower-case "done" is ordinary prose), or a ✅ mark (docs/72's
#             bare trailing checkmark).
#   blocked — the kernel built-in's own soak/gate vocabulary, reused verbatim.
_HEAD_SHIPPED_RE = re.compile(r"\bSHIPPED\b", re.IGNORECASE)
_HEAD_DONE_RE = re.compile(r"\bDONE\b")
_HEAD_BLOCKED_RE = re.compile(
    r"\b(?:SOAK|SOAKING|BLOCKED|AWAITING|GATED|DEFERRED)\b", re.IGNORECASE
)
_CHECKMARK = "✅"

# The plan-wide close-out mark: the doc's FIRST `> **Status:**` line, and only when
# its text BEGINS with ✅ and carries a word-bounded SHIPPED (docs/70/72/73/74's
# `> **Status:** ✅ **SHIPPED** (all three phases, …)`). A 🚧 mixed-status sentence
# ("Phases 1–2 shipped; Phase 3 design") is deliberately NOT parsed — per-heading
# marks carry those docs, and prose ranges are exactly the mining this refuses.
_STATUS_LINE_RE = re.compile(r"^>\s*\*\*Status:?\*\*:?\s*(.+)$")


def _heading_claim(line: str) -> str:
    """The claim the HEADING line itself carries, or "" when it claims nothing.

    Pure. Shipped wins over blocked when both appear (a `✅ SHIPPED … was GATED`
    close-out reads as the final state, not the history)."""
    if (
        _HEAD_SHIPPED_RE.search(line)
        or _HEAD_DONE_RE.search(line)
        or _CHECKMARK in line
    ):
        return CLAIMED_SHIPPED
    if _HEAD_BLOCKED_RE.search(line):
        return CLAIMED_BLOCKED
    return ""


def _plan_wide_shipped(lines: list[str]) -> bool:
    """True iff the doc's FIRST status line is the leading-✅ SHIPPED close-out.

    Only the first `> **Status:**` line is consulted — the genre keeps status at
    the doc top, and a later status note (docs/97's mid-doc partial-landing update)
    must not retro-claim the whole plan."""
    for ln in lines:
        m = _STATUS_LINE_RE.match(ln)
        if not m:
            continue
        text = m.group(1).strip()
        return text.startswith(_CHECKMARK) and bool(_HEAD_SHIPPED_RE.search(text))
    return False


def _plan_id(doc_path: str) -> str:
    """The doc's root-relative path, forward slashes, minus `.md` — the positional
    plan string the oracle takes (`docs/82_liveness-oracle-plan`)."""
    plan = doc_path.replace("\\", "/")
    if plan.lower().endswith(".md"):
        plan = plan[:-3]
    return plan


def _harvest_design_doc(text: str, doc_path: str) -> list[PlanRow]:
    """Parse one design-doc's text into ordered PlanRows. Pure, no I/O.

    One row per recognised heading; claim = the heading's own (closed-vocabulary)
    claim, else the doc's plan-wide ✅-SHIPPED close-out, else open. De-duped on
    ``(plan, phase)`` preserving the FIRST-seen claim — docs/290 declares
    `## Phase 1` as a section and `### Phase 1 — shipped` as its close-out record,
    and first-seen reads open: a benign under-claim, never a manufactured
    over-claim. A doc with no recognised heading yields ``[]``.
    """
    plan = _plan_id(doc_path)
    lines = text.splitlines()
    plan_wide = _plan_wide_shipped(lines)
    rows: list[PlanRow] = []
    seen: set[str] = set()

    def _add(phase: str, heading_line: str) -> None:
        if not phase or phase in seen:
            return
        seen.add(phase)
        claimed = _heading_claim(heading_line) or (
            CLAIMED_SHIPPED if plan_wide else CLAIMED_OPEN
        )
        rows.append(
            PlanRow(plan=plan, phase=phase, doc_path=doc_path, claimed_status=claimed)
        )

    for line in lines:
        km = _PHASE_KEYWORD_RE.match(line)
        if km:
            _add(f"Phase {km.group(1)}", line)
            continue
        im = _ID_LED_RE.match(line)
        if im:
            token = im.group(1)
            # The two in-code guards: a real series id carries a digit (`GHF1`,
            # `ISV0`, `F2`); a version reference (`v0.23.0`) is not a phase.
            if any(c.isdigit() for c in token) and not _VERSION_TOKEN_RE.match(token):
                _add(token, line)
    return rows


class DesignDocPlanSource:
    """The design-doc dialect as a `PlanSource` — `dos plan --source design-docs`.

    The same declared-glob walk as the built-in `MarkdownPlanSource` (globs
    ``config.paths.plans_glob`` under the workspace root, names no host literal),
    parsing each doc with the dialect grammar above instead of the strict
    ``### N. PLAN PHASE`` form. Registered under the `dos.plan_sources`
    entry-point group; resolved by name, held to fail-to-empty by
    `run_plan_source` like every source.
    """

    name = "design-docs"

    def rows(self, config: object) -> list[PlanRow]:
        paths = getattr(config, "paths", None)
        if paths is None:
            return []
        root = Path(getattr(paths, "root", "."))
        glob = str(getattr(paths, "plans_glob", "") or "")
        if not glob:
            return []
        try:
            matched = sorted(root.glob(glob))
        except (OSError, ValueError):
            return []
        out: list[PlanRow] = []
        for p in matched:
            try:
                if not p.is_file():
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                rel = str(p.relative_to(root))
            except ValueError:
                rel = str(p)
            out.extend(_harvest_design_doc(text, rel))
        return out

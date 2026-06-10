"""GH4 commit-coverage predicates — pure ship-stamp / claim-footprint matching.

Lifted from the job userland's ``scripts/fanout_state.py`` (MQ3X P1, docs/62).
These three predicates answer two distrust questions the GH4 post-commit
auto-stamp asks before believing "this commit shipped (plan, phase)":

  * ``claim_covered``          — does any committed path fall inside the claim's
                                 declared footprint? (explicit glob / explicit
                                 files / fanout-archive bundle / plan-doc edit)
  * ``coverage_is_plandoc_only`` — was the claim covered ONLY by a plan-doc edit
                                 (branch 3b) and none of the stronger footprints?
                                 The surface of the CRS3 false-stamp (2026-06-02):
                                 a sibling phase's ship edits the SHARED plan doc
                                 and would auto-stamp a phase whose deliverable
                                 was never touched → the picker drops a live phase
                                 → the lane wedges.
  * ``subject_matches_stamp``  — does the commit SUBJECT look like the expected
                                 ship-stamp for this plan?

This module is a ``dos`` Layer-1 leaf in the ``scope`` / ``sibling_scan`` mold:
**pure** ``(entry, committed_paths, subject)`` → ``bool``, zero fs / git / clock /
config. All I/O — running ``git show --name-only``, resolving the plan-doc path,
reading ``STATE_PATH`` — happens in the CALLER (the job adapter's
``_gh4_scan_claims_after_commit``), which gathers the evidence then calls these.
That is what lets the whole predicate family be replay-tested on frozen fixtures.

Two impure GH4 siblings (``subject_is_prelaunch_staging_only``,
``plandoc_only_lacks_deliverable``) deliberately stay job-side: they transitively
reach ``STATE_PATH`` via ``_gh4_claim_plan_files → _resolve_phase_plan_files →
_resolve_plan_doc_path`` (the boundary litmus in docs/62 §0). Only these three
leaf-pure predicates lift.

Function names drop the ``_gh4_`` prefix (the module namespace carries it); the
job shim re-exports them under their old ``_gh4_*`` names so every existing
caller resolves unchanged.
"""
from __future__ import annotations

import fnmatch
import re

# A ``dispatched_by: fanout-<TS>`` tag — the claim was dispatched by a fanout run
# whose archive bundle lives under ``docs/_fanout_runs/<TS>/``.
FANOUT_TS_RE = re.compile(r"^fanout-(\d{8}T\d{6}Z)$", re.IGNORECASE)

# Commit-subject shapes accepted as a generic ship-stamp (matched against the
# SUBJECT line only). Permissive on purpose — a false-positive auto-transition is
# safer than over-routing to the warn queue (a mistaken transition surfaces as a
# stamp-drift row on the next pre-screen; over-routing buries real signal under
# noise). The plan-token check is tightened with the actual plan id at match time.
STAMP_PATTERNS_GENERIC = (
    re.compile(r"^chore\(working-tree\)", re.IGNORECASE),
    re.compile(r"^docs/fanout:", re.IGNORECASE),
    re.compile(r"^docs/dispatch:", re.IGNORECASE),
    re.compile(r"^docs/_fanout_runs", re.IGNORECASE),
)


def claim_covered(entry: dict, committed: list[str],
                  plan_doc_path: str | None) -> bool:
    """Return True iff any committed path is inside the claim's footprint.

    Resolution order:
      1. Explicit ``path_glob`` on the entry (str): fnmatch any committed path.
      2. Explicit ``files`` on the entry (list[str]): exact match or prefix match
         (treat a trailing ``/`` as a directory prefix).
      3. Fallback (the common case — schema rows today carry NEITHER):
         a) ``dispatched_by: fanout-<TS>`` AND any committed path is under
            ``docs/_fanout_runs/<TS>/`` (archive-bundled ship).
         b) ``plan_doc_path`` resolves and any committed path equals it (a
            plan-doc edit covering this plan).
    """
    if not committed:
        return False
    norm_committed = [p.replace("\\", "/") for p in committed if p]

    # 1) explicit path_glob
    glob = entry.get("path_glob")
    if isinstance(glob, str) and glob.strip():
        pat = glob.strip().replace("\\", "/")
        for p in norm_committed:
            if fnmatch.fnmatch(p, pat):
                return True

    # 2) explicit files
    files = entry.get("files")
    if isinstance(files, list) and files:
        explicit = {str(f).replace("\\", "/") for f in files if f}
        for p in norm_committed:
            if p in explicit:
                return True
            for f in explicit:
                if f.endswith("/") and p.startswith(f):
                    return True

    # 3a) fanout-archive bundled commit
    by = (entry.get("dispatched_by") or "").strip()
    m = FANOUT_TS_RE.match(by)
    if m:
        ts = m.group(1)
        prefix = f"docs/_fanout_runs/{ts}/"
        for p in norm_committed:
            if p.startswith(prefix):
                return True

    # 3b) plan-doc covered
    if plan_doc_path:
        pdp = plan_doc_path.replace("\\", "/")
        for p in norm_committed:
            if p == pdp:
                return True

    return False


def coverage_is_plandoc_only(
    entry: dict, committed: list[str], plan_doc_path: str | None,
) -> bool:
    """True iff ``claim_covered`` would pass ONLY via branch 3b (a plan-doc edit)
    — i.e. the commit touched the plan doc but matched NONE of the stronger
    footprints (explicit ``path_glob`` / explicit ``files`` / fanout-archive
    bundle 3a).

    This is the surface of the CRS3 false-stamp (2026-06-02): a real ship commit
    (``CRS2: …``) edits the SHARED plan doc that holds both CRS2 and CRS3 meta, so
    3b covers the CRS3 claim even though no CRS3 deliverable was touched; combined
    with the permissive subject token-match (``\\bCRS3\\b`` in the body) it
    auto-stamps CRS3 shipped → ship_oracle reads registry→SHIPPED → the picker
    drops a phase whose deliverable does not exist → every dispatch on that lane
    WEDGEs. Caller uses this to demand a *deliverable* overlap before stamping such
    a coverage. Best-effort; pure.
    """
    if not committed or not plan_doc_path:
        return False
    norm = [p.replace("\\", "/") for p in committed if p]
    pdp = plan_doc_path.replace("\\", "/")
    if pdp not in norm:
        return False  # not covered via 3b at all
    # Stronger footprints — if ANY of these match, coverage is NOT plan-doc-only.
    glob = entry.get("path_glob")
    if isinstance(glob, str) and glob.strip():
        pat = glob.strip().replace("\\", "/")
        if any(fnmatch.fnmatch(p, pat) for p in norm):
            return False
    files = entry.get("files")
    if isinstance(files, list) and files:
        explicit = {str(f).replace("\\", "/") for f in files if f}
        for p in norm:
            if p in explicit or any(
                    f.endswith("/") and p.startswith(f) for f in explicit):
                return False
    by = (entry.get("dispatched_by") or "").strip()
    m = FANOUT_TS_RE.match(by)
    if m and any(p.startswith(f"docs/_fanout_runs/{m.group(1)}/") for p in norm):
        return False
    # Covered, and the ONLY thing that covered it was the plan-doc edit.
    return True


def subject_matches_stamp(subject: str, plan: str) -> bool:
    """Return True iff the commit ``subject`` looks like the expected ship-stamp
    for a claim against ``plan``. Permissive — see ``STAMP_PATTERNS_GENERIC``."""
    if not subject:
        return False
    s = subject.strip().splitlines()[0] if subject else ""
    plan_lc = (plan or "").strip().lower()
    if plan_lc:
        # `<plan>:` / `docs/<plan>:` / `<plan>/` / `docs/<plan>-plan` etc.
        if re.match(rf"^(?:docs/)?{re.escape(plan_lc)}(?:-plan)?[:/]", s,
                    re.IGNORECASE):
            return True
        # Plan id may appear anywhere in the subject as a token (e.g.
        # `docs/git-hygiene: GH4 — ...` for a GH4 claim).
        if re.search(rf"\b{re.escape(plan_lc)}\d*\b", s, re.IGNORECASE):
            return True
    for pat in STAMP_PATTERNS_GENERIC:
        if pat.match(s):
            return True
    return False

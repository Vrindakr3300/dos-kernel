"""dos._job_policy — the reference app's STRUCTURAL lane fallback, as a leaf.

This is the domain-free **structural fallback** taxonomy: only the exclusive
lanes (``orchestration`` / ``global``), no curated work-lane trees. The
authoritative work-lane taxonomy is NOT here — it lives in the consumer repo's
``dos.toml [lanes]`` (read by ``job_config`` via ``load_workspace_config``). This
literal stands in only when a workspace has no ``[lanes]`` declaration (a foreign
checkout, a test tmp_path).

History: this module held the full job domain taxonomy (``apply`` / ``tailor`` /
``discovery`` / ``recruiter`` / … with job-specific file globs). That was
userland policy baked into the kernel package — the layering wart the
``dos.drivers.job`` docstring called out (2026-06-01 audit). It first moved here
from ``dos.config`` (the "third home both layers may import" relocation); then on
2026-06-06, per dos/119 + the dynamic-claim-area model, the domain names and
their globs were removed entirely (a lane is a HANDLE resolving to a derived
per-pick claim, not a curated tree — ``--scope apply`` resolves via the host's
``_dynamic_claim_space``). What remains is the structural fallback only. See
``docs/_design/kernel-userland-taxonomy-split-2026-06-06.md`` in the consumer repo.

Layer position: it imports ONLY ``LaneTaxonomy`` (the domain-free dataclass) from
``dos.config``, and nothing else from the package. ``dos.config.job_config`` reads
this literal back via a **lazy import inside the function body** (not a module-top
import), so there is no module-load cycle: ``_job_policy`` statically depends on
``config`` (for the class); ``config`` depends on ``_job_policy`` only at
``job_config()`` *call* time. ``dos.drivers.job`` (layer 4) re-exports from here,
so the public import surface is ``from dos.drivers.job import JOB_LANE_TAXONOMY``
while the kernel core (``dos.config``) no longer *defines* the domain taxonomy.

The de-clustering (2026-06-02, operator directive "delete the cluster concept,
it's bad"): ``concurrent`` and ``autopick`` are **empty**. The kernel arbiter
(`dos.arbiter.arbitrate`) admits concurrency purely by tree-disjointness
(`DisjointnessPredicate`) — it never consults ``concurrent``; that tuple only fed
the legacy bare-walk fallback and the TUI/`man lane` display. So an empty
``concurrent`` does NOT serialize anything: two disjoint lanes still both acquire.
And ``autopick=()`` means a bare request no longer auto-picks a privileged trio —
the host supplies an explicit priority-first ``auto_pick_order`` (built from its
``dispatch_lane_priority`` ladder), so a bare loop picks the top-priority pickable
plan's lane.

The dynamic-claim-area step (2026-06-06, dos/119): ``trees`` no longer carries the
work-lane regions either. ``--scope apply`` does NOT look up a curated
``trees["apply"]`` — the host resolves it to the narrow per-pick footprint via
``_dynamic_claim_space``. So ``trees`` here holds ONLY the ``global`` exclusive
lane's region (``**/*``). ``orchestration`` is declared exclusive but carries NO
tree: exclusive lanes are EXEMPT from ``config_lint.LANE_WITHOUT_TREE`` (the
arbiter admits them on liveness alone, never a tree — ``config_lint.py`` only
checks ``concurrent``/``autopick`` members), and ``tree_for`` returns ``[]``
cleanly for it. The host phased-plan globs that used to sit on ``orchestration``
(``scripts/next_up*.py``/``scripts/replan_*.py``/``docs/_plans/``) were userland
policy — they belong in the consumer repo's ``dos.toml [lanes.trees]``, not in
this kernel leaf — and were reaped 2026-06-08 (the userland-coupling audit; see
``docs/_audits/USERLAND_REAP_AUDIT_2026-06-08.md``). ``aliases`` is empty (the
``ff``/``recruiter``/``ui``/``auth`` self-aliases were userland and are gone).
The authoritative job taxonomy is the consumer repo's ``dos.toml [lanes]``; this
literal is the structural fallback.
"""

from __future__ import annotations

from dos.config import LaneTaxonomy

# The reference userland app's STRUCTURAL lane fallback — domain-free, NOT the
# authoritative taxonomy. The authoritative work-lane taxonomy now lives in the
# consumer repo's `dos.toml [lanes]` (read by `job_config` via
# `load_workspace_config`); this literal is only the fallback used when a
# workspace has no `[lanes]` declaration (a foreign checkout, a test tmp_path).
#
# dos/119 + DCA (dynamic-claim-area): a lane is a HANDLE that resolves to a
# derived per-pick CLAIM, not a curated tree. So there are NO curated work-lane
# trees here anymore — the domain names (apply/tailor/discovery/recruiter/fleet/
# ui/auth) and their job-specific globs (`agents/apply_*.py`, `go/internal/ui/`,
# …) were userland policy that does not belong in this kernel package; they were
# removed 2026-06-06 (see `docs/_design/kernel-userland-taxonomy-split-2026-06-06.md`
# in the consumer repo). `--scope apply` now resolves dynamically via the host's
# `_dynamic_claim_space` (the narrow per-pick footprint), never a curated tree.
#
# What remains is structural ONLY: the two exclusive lanes, which run ALONE and
# never enter the disjointness algebra. Only `global` carries a tree (`**/*`);
# `orchestration` carries NONE — exclusive lanes are exempt from the
# `LANE_WITHOUT_TREE` lint (the arbiter admits an exclusive lane on liveness
# alone), so a tree-less `orchestration` is correct and `tree_for` returns `[]`
# for it. The host phased-plan globs it used to carry
# (`scripts/next_up*.py`/`scripts/replan_*.py`/`docs/_plans/`) were userland
# policy that does not belong in this kernel leaf; the consumer declares them in
# its own `dos.toml [lanes.trees]`. `concurrent`/`autopick` are empty
# (de-clustered 2026-06-02): concurrency is gated by tree-disjointness alone;
# bare auto-pick is priority-first via the host's ladder.
JOB_LANE_TAXONOMY = LaneTaxonomy(
    concurrent=(),
    exclusive=("orchestration", "global"),
    autopick=(),
    trees={
        "global": ("**/*",),
    },
    aliases={},
)

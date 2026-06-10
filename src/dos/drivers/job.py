"""dos.drivers.job — the reference userland app's policy pack (the reference driver).

This is the concrete *policy* the reference userland app supplies to the kernel
mechanism: a STRUCTURAL lane fallback (the exclusive `orchestration`/`global`
lanes) plus a factory that binds the workspace's authoritative taxonomy. The
authoritative work-lane taxonomy is NOT here — it lives in the consumer repo's
`dos.toml [lanes]` (read by `job_config` via `load_workspace_config`); this pack's
literal is only the domain-free fallback for a workspace with no `[lanes]`. It is
the reference example of what a host-repo driver looks like — the kernel ships
only the generic `main`/`global` default (`dos.config.default_config`) and reads
policy through `SubstrateConfig`; it hardcodes none of these names.

The structural-fallback literal lives in the `dos._job_policy` leaf (a near-leaf
that imports only `LaneTaxonomy` from `dos.config`). This module re-exports it as
the public host-policy surface: new code says `from dos.drivers.job import
JOB_LANE_TAXONOMY`. `job_config` is the binding factory — it still lives in
`dos.config` (it constructs the full `SubstrateConfig` from paths + facts, then
layers the workspace `dos.toml` over the fallback taxonomy) and is re-exported
here for the one-stop driver import.

Layering (resolves the 2026-06-01 audit's deferred relocation): `config` is
layer 2, `drivers` is layer 4, and the taxonomy leaf `_job_policy` is a near-leaf
(`_job_policy → config` for the `LaneTaxonomy` class only). So both layers import
the leaf without inverting the one-way arrow — the move the old audit said
"needs a third home BOTH layers may import (a `dos._job_policy` leaf, say)" is
now done. `dos.config` no longer DEFINES the domain taxonomy; it exposes
`JOB_LANE_TAXONOMY` only as a PEP-562 backward-compatible lazy attribute.

De-clustering note (2026-06-02): the taxonomy has `concurrent=()` / `autopick=()`
— there is no privileged concurrency/auto-pick set. Concurrency is gated by
tree-disjointness alone (the arbiter never reads `concurrent`), and bare auto-pick
is priority-first via the host's ladder.

Dynamic-claim-area note (2026-06-06, dos/119): the work-lane trees
(apply/tailor/discovery/recruiter/…) and their aliases were removed from the
fallback literal — they were userland policy and now live in the consumer's
`dos.toml`. A `--scope apply` request resolves to the narrow per-pick footprint
via the host's `_dynamic_claim_space`, not a curated `trees["apply"]`. The
fallback literal carries only the two exclusive lanes' structural trees.
"""

from __future__ import annotations

from dos._job_policy import JOB_LANE_TAXONOMY
from dos.config import job_config

__all__ = ["JOB_LANE_TAXONOMY", "job_config"]

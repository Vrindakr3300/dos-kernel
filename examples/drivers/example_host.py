"""example_host — a MINIMAL copy-me DOS host driver (layer-4 policy pack).

This is the smallest thing that is a real DOS driver. Copy this file into your
own consumer (see ``examples/drivers/README.md`` for *where*), rename the module
and the two ``example_host`` tokens to your host's name, and edit the lane
taxonomy. That is the whole job — the kernel/CLI never learns your host's name.

For the **rich, fully-annotated reference** — concurrent tree-disjointness, the
shared-``docs/``-by-filename-prefix trick, the exclusive whole-repo lane, keyword
aliases — read ``src/dos/drivers/workshop.py``. This file is deliberately the
bare skeleton; ``workshop.py`` is the teaching version.

A driver is exactly two things:

  * a ``LaneTaxonomy`` constant — the concurrency policy as pure data, and
  * an ``<name>_config(workspace)`` factory — binds that taxonomy to a workspace
    root and returns a ``SubstrateConfig``.

The factory name MUST match the module stem (module ``example_host`` →
``example_host_config``). That is the **by-convention contract** the generic
``dos --driver example_host`` loader resolves (``dos.drivers.<name>.<name>_config``).
There is no entry-point and no ``dos.toml`` key for this — the wiring is the
module name alone.
"""

from __future__ import annotations

from pathlib import Path

from dos.config import (
    LaneTaxonomy,
    PathLayout,
    SubstrateConfig,
    gather_workspace_facts,
    resolve_workspace_root,
)

# This host's concurrency policy, as data. Two concurrent build lanes over
# provably tree-disjoint regions, plus the exclusive whole-repo catch-all.
EXAMPLE_HOST_LANE_TAXONOMY = LaneTaxonomy(
    # CONCURRENT lanes run in parallel *iff* their file trees are provably
    # disjoint (no glob-prefix of one is a prefix of the other). `api` and `web`
    # touch different directories, so the arbiter admits a `web` request while an
    # `api` lease is live — two agents build at once.
    concurrent=("api", "web"),
    # EXCLUSIVE lanes never run alongside anything: holding one refuses every
    # other request. `global` is the whole-repo escape hatch (mirrors the kernel
    # default) — a release / migration / anything that touches everything runs
    # here, alone.
    exclusive=("global",),
    # AUTOPICK is the ordered set a bare (lane-less) request walks to find a free,
    # non-empty lane. Usually your concurrent lanes; never an exclusive one.
    autopick=("api", "web"),
    # TREES are each lane's canonical file region as repo-relative globs. This is
    # what the arbiter normalizes to a path prefix and checks for disjointness, so
    # keep concurrent lanes' trees non-overlapping. `global`'s `**/*` is the whole
    # repo (correct for an exclusive lane — its blast radius really is everything).
    trees={
        "api": ("api/**/*", "service/**/*"),
        "web": ("web/**/*", "ui/**/*"),
        "global": ("**/*",),
    },
    # ALIASES route a keyword to a canonical lane, so `--lane backend` reaches
    # `api`. Optional — omit (or pass `{}`) if you don't want keyword routing.
    aliases={
        "backend": "api",
        "frontend": "web",
    },
)


def example_host_config(workspace: Path | str | None = None) -> SubstrateConfig:
    """This host's policy, pointed at ``workspace``.

    Mirrors ``dos.drivers.workshop.workshop_config`` exactly: resolve the
    workspace root (explicit arg › ``DISPATCH_WORKSPACE`` › cwd), bind this
    driver's lane taxonomy with the default path layout, and gather the workspace
    facts.

    ``gather_workspace_facts(root)`` is MANDATORY, not decoration: it caches
    *which kernel runtime files exist under this root* so the pure SELF_MODIFY
    guard is workspace-scoped. Omit it and ``config.workspace`` is ``None``, which
    forces the guard to its conservative full static set and can wrongly refuse a
    whole-repo lane in a foreign checkout. A driver factory MUST gather facts,
    exactly as the kernel's own factories (``default_config`` / ``job_config``) do.

    A host whose plans/state live off the default layout either swaps
    ``PathLayout`` here or declares ``[paths]`` in its workspace's ``dos.toml``
    (the no-code path); likewise ``[stamp]`` / ``[reasons]`` are optional and
    layered from ``dos.toml`` — so the factory stays minimal.
    """
    root = resolve_workspace_root(workspace)
    return SubstrateConfig(
        lanes=EXAMPLE_HOST_LANE_TAXONOMY,
        paths=PathLayout.for_root(root),
        workspace=gather_workspace_facts(root),
    )


__all__ = ["EXAMPLE_HOST_LANE_TAXONOMY", "example_host_config"]

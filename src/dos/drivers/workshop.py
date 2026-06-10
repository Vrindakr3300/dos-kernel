"""dos.drivers.workshop — a generic, self-contained reference host policy pack.

This is the **copy-me template** for adding a new host to DOS. It is a driver
(layer 4): the *policy* a particular host workload supplies on top of the kernel
*mechanism*. Where `dos.drivers.job` (the kernel's first userland app) delegates
its taxonomy back to `dos.config` for backward-compatibility, `workshop` declares
everything it needs **inline, in this one file** — so a new host can read a single
module and see the whole shape of "what a driver is."

The "workshop" frame: a shop where two benches build distinct parts of one product
*concurrently*, and a single release bench *exclusively* ships it. It names no
company, no challenge, no real product — it is a deliberately generic stand-in
whose lanes are evocative enough to host real-looking trees.

A driver is two things, the same two `job` has:

  * a `LaneTaxonomy` constant (`WORKSHOP_LANE_TAXONOMY`) — the concurrency policy
    as pure data, and
  * a `<name>_config(workspace)` factory (`workshop_config`) — binds that taxonomy
    to a workspace root and returns a `SubstrateConfig`.

The factory name matches the module stem (`workshop` → `workshop_config`), which
is the **by-convention contract** the generic `dos --driver <name>` CLI loader
resolves (`dos.drivers.<name>.<name>_config`), exactly as `job` → `job_config`.
Adding a host = a module like this one; the kernel/CLI never learns its name.

## The lane taxonomy — why these lanes, and the four things it teaches

Two **concurrent** cluster lanes, `frontend` and `backend`, plus an **exclusive**
`release` lane and the catch-all exclusive `global` (the same escape hatch the
generic `default_config` and `job_config` carry — keeping the taxonomy a clean
superset of the default).

1. **Concurrent + tree-disjoint.** `frontend` (`app/`, `web/`, `ui/`) and
   `backend` (`service/`, `api/`, `worker/`) touch provably disjoint file trees,
   so the arbiter (`dos.arbiter` + `dos.lane_overlap`) admits a `backend` request
   *alongside* a live `frontend` lease — two build agents run at once. No prefix of
   one tree is a prefix of the other, which is the whole disjointness rule.

2. **The docs-prefix distinction trick.** Both clusters also own a doc tree under
   the SAME `docs/` directory, kept disjoint by FILENAME PREFIX: `frontend` owns
   `docs/UI-*`, `backend` owns `docs/SVC-*`. `dos._tree.norm_tree_prefix` truncates
   a glob at its first `*` but keeps the literal before it — so `docs/UI-*` →
   `docs/UI-` and `docs/SVC-*` → `docs/SVC-`, which do NOT collide (neither
   `startswith` the other). A bare `docs/` would normalize to `docs/` and collide,
   defeating concurrency — so this is the load-bearing teaching point: two lanes can
   share a parent directory and still run concurrently if their globs discriminate.

3. **Exclusive `release`.** While `release` is held, every other request refuses;
   a deploy / version-cut never races a build. NOTE the honesty of its tree:
   `**/VERSION` normalizes to the *universal* (empty) prefix, so `release`'s blast
   radius really is the whole repo — which is exactly WHY it must run alone. An
   exclusive lane is admitted/refused on liveness (is another lease live?), never on
   tree-disjointness, so this whole-repo glob is correct, not a bug. (One consequence
   worth knowing: because `**/VERSION` collides with the kernel's own source files,
   a `release` request arbitrated through the workspace-blind PURE path would trip
   the SELF_MODIFY guard; the CLI's `dos arbitrate` scopes the guard to files that
   actually exist under the served workspace, so in a foreign repo `release` admits.)

4. **`--lane` keyword aliases.** A request can say `--lane ui` / `--lane api` /
   `--lane ship` and reach the canonical lane; `aliases` routes keyword → named lane.

The lane trees are the discriminating *path prefixes* the kernel normalizes a glob
to (`dos._tree.norm_tree_prefix`), so `docs/UI-` and `docs/SVC-` stay distinct even
though both live under `docs/`.
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

# The workshop's concurrency policy, as data. `frontend` ∩ `backend` is provably
# tree-disjoint (`app/` vs `service/`; `docs/UI-` vs `docs/SVC-`), so the two build
# agents run concurrently; `release`/`global` are exclusive so a deploy/version-cut
# runs alone.
WORKSHOP_LANE_TAXONOMY = LaneTaxonomy(
    concurrent=("frontend", "backend"),
    exclusive=("release", "global"),
    autopick=("frontend", "backend"),
    trees={
        # The UI half — its source + its plan/ship docs (docs/UI-*).
        "frontend": (
            "app/**/*",
            "web/**/*",
            "ui/**/*",
            "docs/UI-*",
        ),
        # The service half — API + workers + its docs (docs/SVC-*).
        "backend": (
            "service/**/*",
            "api/**/*",
            "worker/**/*",
            "docs/SVC-*",
        ),
        # The exclusive deploy / version-cut ceremony. `**/VERSION` is a
        # whole-repo glob (honest: a release touches everything), which is why
        # the lane is exclusive.
        "release": (
            "deploy/**/*",
            ".github/workflows/**/*",
            "docs/REL-*",
            "**/VERSION",
        ),
        # The catch-all exclusive lane (mirrors the kernel default's escape hatch).
        "global": ("**/*",),
    },
    aliases={
        # Keyword routing so a request can say `--lane ui` / `--lane api` /
        # `--lane ship` and reach the canonical lane.
        "ui": "frontend",
        "web": "frontend",
        "frontend": "frontend",
        "svc": "backend",
        "api": "backend",
        "service": "backend",
        "backend": "backend",
        "ship": "release",
        "deploy": "release",
        "release": "release",
    },
)


def workshop_config(workspace: Path | str | None = None) -> SubstrateConfig:
    """The workshop reference policy, pointed at ``workspace``.

    Mirrors `dos.config.job_config`: binds this driver's lane taxonomy to the
    workspace root (resolved by the standard precedence — explicit arg ›
    ``DISPATCH_WORKSPACE`` › cwd) with the job-repo-shaped default path layout.
    A host whose plans/state live elsewhere either swaps `PathLayout` here or
    declares `[paths]` in its workspace's ``dos.toml`` (the no-code path); the
    ship-stamp grammar is likewise layered from ``dos.toml`` ``[stamp]``, so it is
    not hardcoded — the factory stays minimal and parallel to `job_config`.

    Like `job_config` / `default_config`, it gathers the workspace facts
    (`gather_workspace_facts`) and caches them on the config so the SELF_MODIFY
    guard is workspace-scoped: in a foreign repo (no `src/dos/` runtime files) the
    exclusive `release` lane's whole-repo `**/VERSION` glob admits rather than
    tripping self-modify against kernel files that aren't there. Omitting this
    leaves `config.workspace=None`, which forces the guard to the conservative full
    static set and (wrongly) refuses `release` — so a driver factory MUST gather
    facts, exactly as the kernel's own factories do.
    """
    root = resolve_workspace_root(workspace)
    return SubstrateConfig(
        lanes=WORKSHOP_LANE_TAXONOMY,
        paths=PathLayout.for_root(root),
        workspace=gather_workspace_facts(root),
    )


__all__ = ["WORKSHOP_LANE_TAXONOMY", "workshop_config"]

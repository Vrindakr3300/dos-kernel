"""A custom DOS overlap policy — the disjointness-scorer axis of hackability (Axis 7).

DOS's built-in disjointness scorer is the `prefix` policy: two lanes may run
concurrently when their path-prefixes barely intersect (the calibrated ⅓ ratio).
It is sound — it never admits a path-colliding pair — but it is **path-shaped**, so
it misses *semantic* collisions whose files live under disjoint paths: a feature
flag in `src/featureflags.py` and the config it reads in `config/flags.yaml`, two
services that both write one shared schema, a notebook and the feature table it
mutates. A workspace whose notion of "overlap" is richer than path-prefix ships an
`OverlapPolicy` and registers it via a `dos.overlap_policies` entry_point (see this
package's `pyproject.toml`). `dos overlap-eval --policy semantic-groups` then scores
it against a labelled corpus, so you can SHOW it catches collisions the prefix rule
misses — the bring-your-own-scorer research loop (HACKING.md Axis 7, `docs/113`).

The two invariants that keep an OPEN scorer set safe (HACKING.md Axis 7):

  1. **The deterministic prefix floor is always under you.** Whatever this policy
     returns, the kernel AND-s it with the unforgeable prefix-disjointness verdict
     (`overlap_policy.admissible_under_floor`): a policy can turn an ADMIT into a
     REFUSE (catch a semantic collision the floor missed — the useful direction),
     but it can NEVER turn a REFUSE into an ADMIT. So a buggy or hostile policy is
     *structurally incapable* of admitting a path-colliding pair — the worst it can
     do is refuse too much (a visible, safe-direction loss of parallelism). You do
     not have to get the floor right; the kernel owns it.
  2. **Fail-closed.** A policy that raises, or returns the wrong type, degrades to
     the floor verdict alone — i.e. to today's prefix behavior, never to something
     looser. (The kernel does that for you in `admissible_under_floor`; you just
     write the scoring.)

This example is a PURE policy (no model, no I/O) — it reads a small declared map of
"semantic groups" off `config` and refuses any pair whose two trees touch files in
the SAME group, regardless of path. That is the *shape* a real richer scorer takes;
swap the body for an import-graph walk, an embedding-similarity call (then it's a
`dos.drivers.*` module, since it does I/O), or a learned conflict predictor — the
contract and the floor stay identical. Because it can only ADD refusals on top of
the prefix floor, registering it can never make the arbiter admit a collision.
"""

from __future__ import annotations

from dos.lane_overlap import OverlapDecision, Verdict, overlap_verdict


# A tiny illustrative "semantic group" map: a group name → the path fragments that
# belong to it. A real policy would derive this from an import graph, a service
# manifest, or a learned model; here it is a literal so the example is runnable with
# zero dependencies. Two trees "semantically collide" when each touches a fragment
# in the SAME group, even if their paths never prefix-nest.
_DEFAULT_SEMANTIC_GROUPS: dict[str, tuple[str, ...]] = {
    # the feature-flag plane: code + the config it reads are coupled though their
    # paths are disjoint (this is exactly the leak `dos overlap-eval` surfaces for
    # the prefix policy in the README walkthrough).
    "feature-flags": ("featureflags", "flags.yaml", "flags.json"),
    # a shared schema two services both write:
    "shared-schema": ("schema/", "proto/", "migrations/"),
}


def _groups_touched(tree: list[str], groups: dict[str, tuple[str, ...]]) -> set[str]:
    """The set of semantic-group names any entry in ``tree`` touches."""
    touched: set[str] = set()
    for entry in tree:
        e = (entry or "").replace("\\", "/").casefold()
        for gname, fragments in groups.items():
            if any(frag.casefold() in e for frag in fragments):
                touched.add(gname)
    return touched


class SemanticGroupPolicy:
    """Refuse pairs that touch the same semantic group, ELSE defer to the prefix scorer.

    The both-known scorer the arbiter consults (under the prefix floor). It reads an
    optional ``overlap_semantic_groups`` map off ``config`` (a host stashes it on its
    `SubstrateConfig`); absent that, it uses the illustrative default above. The
    logic, in two steps:

      1. If the two trees touch a COMMON semantic group → REFUSE (a coupling the
         path-prefix rule cannot see — the value this policy adds).
      2. Otherwise → fall through to the built-in `overlap_verdict` (the same ⅓
         ratio the prefix policy uses), so on everything outside a declared group
         this policy is identical to the default.

    Crucially, step 2 can itself only REFUSE-or-ADMIT within what the kernel's floor
    permits: even if this method returned ADMIT for a path-colliding pair, the
    `admissible_under_floor` wrapper would override it to REFUSE. So the policy is
    free to be as strict as it likes and *cannot* be too lax — the floor guarantees
    it. This is why a researcher can experiment with an aggressive scorer safely.
    """

    name = "semantic-groups"

    def overlaps(
        self, requested_tree: list[str], lease_tree: list[str], config: object,
    ) -> OverlapDecision:
        groups = getattr(config, "overlap_semantic_groups", None) or _DEFAULT_SEMANTIC_GROUPS
        a_groups = _groups_touched(requested_tree, groups)
        b_groups = _groups_touched(lease_tree, groups)
        shared_groups = a_groups & b_groups
        if shared_groups:
            preview = ", ".join(sorted(shared_groups))
            return OverlapDecision(
                Verdict.REFUSE_OVERLAP, 0, len(requested_tree),
                (f"semantic-group overlap: both lanes touch group(s) {preview} — a "
                 f"coupling path-prefixes cannot see (e.g. code + the config it "
                 f"reads). Refusing concurrent writes (pass --force to override)."),
            )
        # No semantic coupling — defer to the path-prefix ratio (the default scorer).
        return overlap_verdict(requested_tree, lease_tree)


# A module-level instance, so the entry_point can point at either the class
# (`...:SemanticGroupPolicy`, which `dos` instantiates) or this ready-made object.
semantic_group_policy = SemanticGroupPolicy()

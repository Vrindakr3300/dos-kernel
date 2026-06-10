"""SCF — the scope-fidelity verdict: *did the diff stay inside the lane it claims?*

docs/85 §4 + docs/86 — a distrust verdict in the `liveness` mold, the
**footprint sibling of `verify()`**. `verify` distrusts "I shipped P"; SCF
distrusts "the change I stamped as (plan, phase) stays inside that phase's
declared lane." The disease it catches is SHIPPED-stamp-drift one level up: an
agent stamps `phase 3` onto a diff whose blast radius reaches files the phase's
lane never owned — silently stomping another effort's lane on shared state. The
self-report ("I touched the picker") is exactly what a believer cannot check; the
**diff's actual footprint** is ground truth the agent cannot forge, and this
verdict reads it.

This module is `liveness`'s sibling — a **pure** verdict function, the
`arbitrate()` / `classify` shape:

    arbiter.arbitrate          (request, live_leases, config)  -> decision
    liveness.classify          (ProgressEvidence, policy)       -> LivenessVerdict
    scope.classify             (ScopeEvidence, policy)          -> ScopeVerdict
                               ^ THIS module

All I/O — running `git diff --name-only`, reading the lane taxonomy — happens in
the CALLER (the `dos scope` CLI's evidence-gather, the benchmark's sink), exactly
as `liveness`'s git read happens outside `classify()`. `classify()` makes no
subprocess, file, or clock call: it takes the already-gathered touched-file set
and the already-resolved lane tree as frozen evidence. That is what lets the whole
verdict be replay-tested on frozen fixtures (the `liveness` design value, restated
for the footprint axis).

The algebra is **reused, not reinvented**: a file is *inside* the lane when some
normalized directory prefix of the lane's tree (`dos._tree.norm_tree_prefix` — the
exact normalization the arbiter's `lane_trees_disjoint` runs pairwise) is a
path-prefix of the file. SCF runs that test one-directionally (file-vs-tree)
where the arbiter runs it tree-vs-tree.

The verdict ladder, top to bottom — the whole point is that a reader holds it in
their head:

  1. IN_SCOPE     — every touched file falls under some declared prefix of the
                    lane's tree (or there is nothing to judge: an empty diff
                    creeps on nothing). The footprint is contained.
  2. SCOPE_CREEP  — the lane's files ARE touched, AND so are files outside the
                    tree (beyond an optional tolerance): a superset of the
                    declared scope. The stamp is right but the blast radius
                    overran it.
  3. WRONG_TARGET — NONE of the touched files fall in the lane's tree: the stamp
                    names a lane the diff never entered. The most severe — the
                    claim and the footprint disagree entirely.

SCF says where the bytes LANDED, never that they landed *well*: a contained diff
can still be wrong code, and that is an advisory judge's call (`llm_judge`), never
this deterministic kernel verb (the distrust-state / distrust-judgment line).

SCF (`classify`) is ADVISORY. It reports; it never reverts a commit or refuses a
lease. A caller may consult it and choose to refuse a write (the natural consumer
is the arbiter's admission seam — a `ScopePredicate` over ADM's conjunction is a
possible *separate* opt-in driver policy, not SCF), and the decisions queue may
surface a SCOPE_CREEP — but the scope verdict and the admission decision stay
different syscalls (the same line `liveness`/SPINNING holds).

The BINDING pre-effect gate — `gate()`, the docs/102 §5 fix.
-----------------------------------------------------------
`classify` grades a diff *after* it landed; that is collision-DETECTION, and for
the irreversible blast radius of a silent clobber the trust law
(`docs/102_when-to-trust-an-agent.md` §3 clause 3, §5) demands collision-
PREVENTION instead: *"you cannot un-clobber."* The arbiter admits two lanes at
contention on their DECLARED trees, but `classify` only checks conformance once
the commit is in — so two agents that each *under-declare* their trees are
admitted concurrently, both write, and one silently stomps the other. The
declared tree is a *prior* commitment (clause 2) but it is not *binding* at the
moment it matters.

`gate()` makes it binding. It is the SAME conformance logic as `classify`, moved
from after the commit to BEFORE the write: the caller gathers the *proposed*
write-set (the staged diff's footprint, the patch about to be applied) and asks
`gate()` whether that write is contained by the lane it claims. A write outside
the declared tree is **refused, not recorded** — the pre-effect boundary the §4
trust table assigns to "(detectable, NOT reversible) → the kernel at the
contention/pre-effect boundary." This is what converts the declared scope from a
report the arbiter believes into a commitment the work is held to.

`gate()` stays PURE for the identical reason `classify` does — the I/O of
*gathering* the proposed write-set is the caller's (a `git diff --cached`, a
patch-header parse, the broker's `declared_paths`), exactly as `classify`'s
`git diff` lives in `verdict_cli._git_diff_names`. The difference between the two
verbs is **not** the algebra (they share `classify`) and **not** purity — it is
*when the caller runs them* and *what they do with the answer*: `classify` grades
a past footprint advisorily; `gate` decides a future write bindingly. A consumer
that wants prevention calls `gate` before the write and honors the refuse; a
consumer that only wants a post-hoc report calls `classify`. The natural
production consumer is a single-writer commit broker / an edit-time hook that
refuses an out-of-tree patch before applying it (the job repo's
`scripts/commit_broker.py` fence is exactly this seam; `gate` is its kernel
verdict).

No-plan discipline (`test_verify_no_plan` sibling): SCF must return a verdict with
nothing but a touched-file set and a lane tree. The GENERIC lane tree is
`("**/*",)`; `norm_tree_prefix` truncates it at the first `*` to the empty prefix
`""`, which every path starts with — so a repo that declared no lanes gets the
honest "no scope to violate" answer (IN_SCOPE), never a crash. Every richer input
is OPTIONAL.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from . import _tree


class Scope(str, enum.Enum):
    """The typed scope verdict — three states, mutually exclusive.

    `str`-valued so it round-trips through a CLI stdout token / exit-code map
    without a lookup table (mirrors `liveness.Liveness`, `gate_classify.Verdict`).
    """

    IN_SCOPE = "IN_SCOPE"        # every touched file is inside the lane's tree
    SCOPE_CREEP = "SCOPE_CREEP"  # the lane is touched AND so is something outside it
    WRONG_TARGET = "WRONG_TARGET"  # nothing touched is inside the lane's tree

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# Hub files almost every change incidentally edits — config, package markers,
# the umbrella CLI. A footprint that spills ONLY onto these is not a meaningful
# scope violation, the same judgement `phase_shipped._SHARED_INFRA_BASENAMES`
# makes for ship-attribution (a shared-infra touch is not a phase's *distinctive*
# deliverable). Matched by basename so a path anywhere in the tree is caught.
# Tolerated only when `ScopePolicy.allow_shared_infra` is set (the default).
_SHARED_INFRA_BASENAMES = frozenset({
    "config.py", "__init__.py", "settings.py", "constants.py",
    "cli.py", "conftest.py", "pyproject.toml", "setup.py", "setup.cfg",
})


@dataclass(frozen=True)
class ScopePolicy:
    """The knobs that separate IN_SCOPE/SCOPE_CREEP/WRONG_TARGET — policy, not mechanism.

    The same "mechanism is kernel, thresholds are config" split as
    `liveness.LivenessPolicy`. The defaults are GENERIC (no host tuning); a
    workspace declares its own in `dos.toml [scope]` read back through
    `SubstrateConfig`, the closed-config-as-data pattern (`[lanes]` / `[stamp]` /
    `[reasons]` / `[liveness]`).

      allow_shared_infra — when True (default), a footprint that spills ONLY onto
                           shared-infra hub files (`config.py`, `__init__.py`, …)
                           is still IN_SCOPE: those are touched by nearly every
                           change and are never a phase's distinctive deliverable,
                           so counting them as creep is a false positive (the
                           `phase_shipped` shared-infra judgement, restated).
      creep_tolerance    — the number of non-infra out-of-tree files allowed
                           before the verdict escalates from IN_SCOPE to
                           SCOPE_CREEP. Default 0 — strict: any genuine spill is
                           creep. A host that expects small incidental spill can
                           raise it.
    """

    allow_shared_infra: bool = True
    creep_tolerance: int = 0

    def __post_init__(self) -> None:
        if self.creep_tolerance < 0:
            raise ValueError("creep_tolerance must be non-negative")


DEFAULT_POLICY = ScopePolicy()


@dataclass(frozen=True)
class ScopeEvidence:
    """Everything `classify()` needs, gathered by the CALLER before the call.

    No git, no config read inside the verdict — the arbiter rule. The CLI's
    evidence-gather (the boundary) runs `git diff --name-only <base>..<head>` (or
    `git show --name-only <sha>`) for the touched set and resolves the lane's tree
    from `SubstrateConfig.lanes.trees[lane]`, then freezes both here and hands
    them to the pure classifier.

      touched_files — the repo-relative paths the candidate commit(s) changed.
                      The agent cannot forge which files a commit object touches;
                      this is the unforgeable footprint. An empty set is a diff
                      that changed nothing — IN_SCOPE (creeps on nothing).
      lane_tree     — the declared path globs of the lane the diff is stamped
                      against (`config.lanes.trees[lane]`). The GENERIC default
                      `("**/*",)` normalizes to the empty prefix → everything is
                      in scope (the no-plan floor). An EMPTY tree is an *unknown*
                      blast radius, not a zero one (the `_tree.lane_trees_disjoint`
                      stance): with a non-empty diff it yields WRONG_TARGET — we
                      cannot certify containment against an undeclared lane.
      lane          — the lane name, carried for the operator-facing reason / the
                      `--output json` consumer; not an input to the verdict ladder.
    """

    touched_files: frozenset[str]
    lane_tree: tuple[str, ...]
    lane: str = ""

    def __post_init__(self) -> None:
        # Normalize to a frozenset of clean, forward-slashed paths so the prefix
        # test matches the `_tree` normalization on the tree side. (A tuple/list
        # passed in is accepted — frozenset() copies it.)
        cleaned = frozenset(
            (p or "").replace("\\", "/").strip()
            for p in self.touched_files
            if p and str(p).strip()
        )
        object.__setattr__(self, "touched_files", cleaned)


@dataclass(frozen=True)
class ScopeVerdict:
    """The single verdict `classify()` returns, with the evidence echoed back.

    `verdict` is the typed `Scope`. `reason` is a one-line operator-facing summary
    that NAMES the offending files (so the operator sees not just SCOPE_CREEP but
    *which* spill — legible distrust, the RND/Axis-4 renderer seam, exactly like
    `liveness`'s "0 commits, heartbeat 8m fresh"). `evidence` is the
    `ScopeEvidence` that drove the call, carried so `dos scope --output json` can
    emit the verdict AND the facts behind it in one object.

      in_scope_files  — touched files inside the lane tree (sorted, for stable output)
      out_of_scope_files — touched files outside it (the spill that drove the verdict)
    """

    verdict: Scope
    reason: str
    evidence: ScopeEvidence
    in_scope_files: tuple[str, ...] = ()
    out_of_scope_files: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        ev = self.evidence
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "in_scope_files": list(self.in_scope_files),
            "out_of_scope_files": list(self.out_of_scope_files),
            "evidence": {
                "lane": ev.lane,
                "touched_files": sorted(ev.touched_files),
                "lane_tree": list(ev.lane_tree),
            },
        }


def _file_in_tree(path: str, prefixes: list[str]) -> bool:
    """True when `path` falls under some normalized directory prefix of the tree.

    Reuses `dos._tree.norm_tree_prefix`'s normalization (already applied to
    `prefixes`). The empty prefix `""` (from a `**/*` glob) is a prefix of every
    path, which is what makes the GENERIC lane match everything (the no-plan
    floor). A prefix that names a file exactly (`job_search/scoring.py`) matches
    that file and, harmlessly, anything textually under it.

    The touched ``path`` is run through the SAME `norm_tree_prefix` normalization
    (slash-canonicalized + case-FOLDED) as the prefixes it is compared against, so
    containment is decided on the identical footing — a `Src/Dos/x.py` diff is
    correctly judged inside a `src/**` lane on a case-insensitive FS (and the fold
    is unconditional for the same cross-platform-determinism reason `_tree` folds).
    `norm_tree_prefix` truncates at the first ``*``; a concrete file path has none,
    so for touched files it is exactly "fold + canonicalize slashes".
    """
    folded = _tree.norm_tree_prefix(path)
    return any(folded.startswith(pref) for pref in prefixes)


def classify(ev: ScopeEvidence, policy: ScopePolicy = DEFAULT_POLICY) -> ScopeVerdict:
    """Classify one diff's scope fidelity from already-gathered evidence. PURE.

    No subprocess, no file, no clock — the arbiter discipline. Reads the ladder
    top to bottom (this function IS the answer to "did it stay in its lane?"):

      1. IN_SCOPE     — empty diff (nothing to judge), OR every touched file is
                        inside the lane tree, OR the only out-of-tree files are
                        tolerated shared-infra / within `creep_tolerance`.
      2. SCOPE_CREEP  — at least one touched file IS inside the lane tree AND the
                        out-of-tree spill exceeds tolerance: a superset of scope.
      3. WRONG_TARGET — nothing touched is inside the lane tree (and the diff is
                        non-empty): the stamp names a lane the diff never entered.

    The IN_SCOPE/rest split is pure set membership against the normalized prefix
    tree. The SCOPE_CREEP/WRONG_TARGET split is whether ANY touched file landed in
    the lane: a partial overrun (some in, some out) is creep; a total miss (none
    in) is a wrong target.
    """
    touched = ev.touched_files
    # 1a. Empty diff — nothing to adjudicate. A footprint of zero files creeps on
    #     nothing and targets nothing; the benign IN_SCOPE (mirrors liveness's
    #     0-commit floor returning a verdict, not an error).
    if not touched:
        return ScopeVerdict(
            verdict=Scope.IN_SCOPE,
            reason="empty footprint — no files touched, nothing to judge",
            evidence=ev,
        )

    prefixes = [_tree.norm_tree_prefix(p) for p in ev.lane_tree if p]

    # An EMPTY (or all-blank) lane tree is an UNKNOWN blast radius, not a zero one
    # — the `_tree.lane_trees_disjoint` conservative stance. We cannot certify a
    # non-empty diff is contained by an undeclared lane, so it is WRONG_TARGET
    # (the caller asked us to check scope against a lane that named no tree).
    if not prefixes:
        return ScopeVerdict(
            verdict=Scope.WRONG_TARGET,
            reason=(
                f"lane {ev.lane or '(unnamed)'} declares no tree — cannot certify "
                f"containment of {len(touched)} touched file(s) (unknown blast radius)"
            ),
            evidence=ev,
            out_of_scope_files=tuple(sorted(touched)),
        )

    in_tree = sorted(f for f in touched if _file_in_tree(f, prefixes))
    out_tree = sorted(f for f in touched if not _file_in_tree(f, prefixes))

    # Partition the out-of-tree spill into tolerated shared-infra vs genuine. The
    # basename is case-FOLDED before membership (the set is lowercase) so a mis-cased
    # hub file (`Config.py` == `config.py` on a case-insensitive FS) is correctly
    # tolerated rather than mis-counted as genuine spill — the same fold the in-tree
    # split (`_file_in_tree` → `_tree.norm_tree_prefix`) and `stamp.is_shared_infra`
    # use, so this last membership cannot drift case-sensitive while the rest folds.
    if policy.allow_shared_infra:
        genuine_out = [
            f for f in out_tree if f.rsplit("/", 1)[-1].casefold() not in _SHARED_INFRA_BASENAMES
        ]
    else:
        genuine_out = list(out_tree)

    # 2/3. There IS out-of-tree spill beyond tolerance.
    if len(genuine_out) > policy.creep_tolerance:
        if in_tree:
            # 2. SCOPE_CREEP — touched the lane AND overran it.
            return ScopeVerdict(
                verdict=Scope.SCOPE_CREEP,
                reason=(
                    f"stamped lane {ev.lane or '(unnamed)'} and touched its tree "
                    f"({len(in_tree)} file(s)) but ALSO {len(genuine_out)} file(s) "
                    f"outside it: {', '.join(genuine_out[:5])}"
                    + (" …" if len(genuine_out) > 5 else "")
                ),
                evidence=ev,
                in_scope_files=tuple(in_tree),
                out_of_scope_files=tuple(out_tree),
            )
        # 3. WRONG_TARGET — nothing landed in the lane at all.
        return ScopeVerdict(
            verdict=Scope.WRONG_TARGET,
            reason=(
                f"stamped lane {ev.lane or '(unnamed)'} but NONE of the "
                f"{len(touched)} touched file(s) fall in its tree — "
                f"footprint: {', '.join(genuine_out[:5])}"
                + (" …" if len(genuine_out) > 5 else "")
            ),
            evidence=ev,
            out_of_scope_files=tuple(out_tree),
        )

    # 1b. IN_SCOPE — no genuine spill (everything is in the tree, or the only
    #     out-of-tree files are tolerated shared-infra / within tolerance).
    note = ""
    if out_tree:
        note = (
            f" ({len(out_tree)} shared-infra/tolerated file(s) outside the tree, "
            f"not counted as creep)"
        )
    return ScopeVerdict(
        verdict=Scope.IN_SCOPE,
        reason=(
            f"all {len(in_tree)} touched file(s) fall inside lane "
            f"{ev.lane or '(unnamed)'}'s tree{note}"
        ),
        evidence=ev,
        in_scope_files=tuple(in_tree),
        out_of_scope_files=tuple(out_tree),
    )


# ===========================================================================
# The binding pre-effect gate (docs/102 §5) — refuse an out-of-tree WRITE
# before it lands, rather than DETECT it after the commit.
# ===========================================================================

# The verdicts that a binding gate treats as "do not let this write land" by
# default. IN_SCOPE is the only ALLOW: a contained footprint is the commitment
# kept. SCOPE_CREEP (overran its tree) and WRONG_TARGET (never entered it / an
# undeclared lane = unknown blast radius) are both REFUSE — each is a footprint
# the declared tree did not authorize, which is exactly the under-declaration the
# §5 silent-clobber needs prevented. (The same frozenset is the policy default and
# the policy floor; a host can only ADD to it — see `ScopeGatePolicy`.)
_DEFAULT_REFUSE_ON: frozenset[Scope] = frozenset({Scope.SCOPE_CREEP, Scope.WRONG_TARGET})


@dataclass(frozen=True)
class ScopeGatePolicy:
    """How the binding gate maps a scope verdict to an ALLOW / REFUSE decision.

    Mechanism-vs-policy, the kernel's standing split (`ScopePolicy`,
    `LivenessPolicy`): the *containment algebra* is fixed in `classify`; this
    object is the *enforcement strictness* a host tunes. Two knobs, and they
    compose — the inner `scope` policy decides what COUNTS as in-scope (shared-
    infra tolerance, creep tolerance); `refuse_on` decides which resulting
    verdicts BLOCK the write.

      scope     — the underlying `ScopePolicy` handed to `classify` (so a host's
                  `allow_shared_infra` / `creep_tolerance` tuning flows straight
                  through to the gate — the gate never re-implements containment).
      refuse_on — the set of `Scope` verdicts that REFUSE the write. Default:
                  {SCOPE_CREEP, WRONG_TARGET} — i.e. only IN_SCOPE is allowed.
                  IN_SCOPE can never be added (allowing the gate to refuse a
                  perfectly-contained write would make it refuse *everything*, a
                  bricked workspace, never a sound stance) — `__post_init__`
                  rejects that, the one-way-safety floor: a host may make the gate
                  STRICTER only in the sense of which non-contained verdicts it
                  blocks, never make a contained write refusable.
    """

    scope: ScopePolicy = DEFAULT_POLICY
    refuse_on: frozenset[Scope] = _DEFAULT_REFUSE_ON

    def __post_init__(self) -> None:
        if Scope.IN_SCOPE in self.refuse_on:
            raise ValueError(
                "refuse_on may not include IN_SCOPE — a gate that refuses a "
                "fully-contained write refuses everything (a bricked workspace). "
                "Tighten containment via the inner ScopePolicy instead."
            )
        # Normalize a passed-in set/iterable to a frozenset so the policy is hashable
        # and immutable like every other frozen kernel policy.
        if not isinstance(self.refuse_on, frozenset):
            object.__setattr__(self, "refuse_on", frozenset(self.refuse_on))


DEFAULT_GATE_POLICY = ScopeGatePolicy()


@dataclass(frozen=True)
class ScopeGate:
    """The binding pre-effect decision: may this proposed write LAND?

    The arbiter-`LaneDecision` analogue for the edit boundary — a decision a
    consumer ACTS on (apply the patch / refuse it), not a report it files. It
    carries the underlying advisory `ScopeVerdict` so the refuse is legible
    (the operator sees not just REFUSE but WHICH files escaped the tree — the same
    legible-distrust seam `ScopeVerdict.reason` serves), and so a consumer that
    wants both the binding bit AND the graded verdict gets them from one call.

      allowed       — True iff the write is contained by the lane it claims and
                      may land; False iff it must be REFUSED before the effect.
      verdict       — the underlying `Scope` (IN_SCOPE / SCOPE_CREEP / WRONG_TARGET)
                      that drove the decision (the advisory grade behind the gate).
      reason        — one-line operator-facing summary; on a refuse it NAMES the
                      out-of-tree spill (carried up from the `ScopeVerdict`).
      scope_verdict — the full `ScopeVerdict`, so a consumer can reach its
                      `in_scope_files` / `out_of_scope_files` / `evidence` without
                      a second `classify` call.
      refused_files — the out-of-tree files that drove a refusal (empty on ALLOW);
                      a convenience projection of `scope_verdict.out_of_scope_files`,
                      the set a consumer reports back to the agent ("these writes
                      were refused; they are outside lane X's tree").
    """

    allowed: bool
    verdict: Scope
    reason: str
    scope_verdict: ScopeVerdict
    refused_files: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "refused_files": list(self.refused_files),
            "scope": self.scope_verdict.to_dict(),
        }


def gate(ev: ScopeEvidence, policy: ScopeGatePolicy = DEFAULT_GATE_POLICY) -> ScopeGate:
    """Decide whether a PROPOSED write may land — the binding pre-effect gate. PURE.

    docs/102 §5: the same conformance logic as `classify`, moved from AFTER the
    commit to BEFORE the write, so an out-of-tree write is *refused, not recorded*.
    The caller gathers the *proposed* footprint (`ev.touched_files` = the staged
    diff / the patch about to apply, NOT the post-commit `git show`), and this
    function answers "is that write contained by the lane it claims?" — `allowed`
    is the bit a consumer acts on at the edit boundary.

    No subprocess, no file, no clock — `classify`'s purity, inherited by delegation
    (the containment algebra is NOT re-implemented; this is `classify` + a verdict→
    decision map). That is what lets the gate be replay-tested on frozen fixtures
    exactly like `classify`, and what keeps the durability/I/O at the caller's edge
    (the arbiter discipline: state in, decision out).

    The decision: ALLOW iff the underlying verdict is NOT in `policy.refuse_on`
    (default: refuse SCOPE_CREEP + WRONG_TARGET, i.e. allow only IN_SCOPE). An
    empty footprint is IN_SCOPE (a write of nothing escapes nothing → allowed, the
    benign floor `classify` already returns), so the gate never blocks a no-op.
    An undeclared lane (empty tree) yields WRONG_TARGET → REFUSED: the gate will
    NOT let a write land against a lane whose blast radius it cannot certify (the
    conservative `_tree.lane_trees_disjoint` stance, now enforced pre-effect).
    """
    verdict = classify(ev, policy.scope)
    allowed = verdict.verdict not in policy.refuse_on
    if allowed:
        reason = f"write ALLOWED — {verdict.reason}"
        refused: tuple[str, ...] = ()
    else:
        reason = f"write REFUSED ({verdict.verdict.value}) — {verdict.reason}"
        refused = verdict.out_of_scope_files
    return ScopeGate(
        allowed=allowed,
        verdict=verdict.verdict,
        reason=reason,
        scope_verdict=verdict,
        refused_files=refused,
    )

# docs/267 — Lifting the durable release concepts from the userland app

> **Status:** Phase 1–3 shipped (release-context `active_leases`, the
> commit-prefix lint, the `release`/`stable-release` skill upgrades). Phase 4
> (a `scoped_release_stage` analogue) is deferred — argued below.

## The question

The reference userland app (`job`, the sibling checkout) has the most mature
release tooling in the work tree: a `release` skill with eight steps, a
`stable-release` skill with a hero-metric gate, and five supporting scripts
(`release_context.py`, `release_bump.py`, `scoped_release_stage.py`,
`check_release_commit_prefix.py`, `stable_release_promote.py`). DOS's two release
skills were lifted from that source and then **deliberately thinned** — DOS is a
substrate, not an app, so it dropped the Go binary, the zip, screenshots, the
versioned-install snapshot, plan-state regeneration, the apply-loop gate, and the
fanout/dispatch manifest.

The thinning was correct. But it threw out a few concepts that are **not
host-specific** — they are about *cutting a release safely on a concurrently
written git tree*, which is exactly DOS's situation (the working tree here is
"multi-session hot": several agents commit to `master` at once; see the
`project-dos-multi-session-hot-tree` and `feedback-shared-index-*` memories). This
doc is the gap analysis and the decision for each concept.

## The rule that decides every row

A release concept ports to DOS **iff it is about git-tree mechanics, not about
the host's workflow.** The litmus is the same one `CLAUDE.md` enforces on the
kernel: if it names a host artifact (a fanout run dir, an apply-audit funnel, a
versioned-install pointer, a `plans.yaml`), it stays in the userland app. If it is
a property of "many writers, one trunk, one tag" — index races, lease ownership,
commit-subject hygiene — it is substrate-shaped and belongs here. And where DOS
has a *better* primitive than the userland app improvised (its own lane journal,
its own `commit-audit` witness), the DOS version should dogfood that primitive
rather than re-import the host's bolt-on.

## The gap analysis

| Concept (userland app) | Ports? | DOS form |
|---|---|---|
| **Auto-defer paths under a live lease** (`release` Step 1.6, `active_leases`) | ✅ **yes — and it's DOS-native** | Fold `lane_journal.read_all → replay` to the live-lease set; defer any dirty path matching a non-stale lease's `tree` globs. The userland app reads a bespoke `active_leases` field its dispatch loop writes; DOS reads its **own kernel WAL**, the same fold `dos top` uses. |
| **Concurrent-write index race protection** (`scoped_release_stage.py`) | ⚠️ **concept yes, code no** | The 944-line helper couples to `agents.lease_state.state` and a job-only index lock. Port the *discipline* (commit by pathspec from the worktree; never bare `git add -A`; the hot-file patch→reset→apply recipe) into the skill body — DOS's own memories already encode the hard-won recipe. A standalone script is deferred (Phase 4 below). |
| **Opt-in commit-prefix lint** (`check_release_commit_prefix.py`, `--lint-prefix`) | ✅ **yes** | A thin, warn-never-block lint that recognizes `vX.Y.Z:` + DOS's commit-subject grammar. DOS-native: no `_NOISE_PREFIXES` import (that taxonomy is the userland app's dispatch/fanout bookkeeping); DOS subjects are plain imperative or `area:`-prefixed. |
| **Dogfood the honesty witness post-release** | ✅ **yes — DOS-only** | The userland app has no commit-audit. DOS *does* (`dos commit-audit`, the docs/179 flip off ground truth). The release skill should run it after committing — the kernel's own contract (`CLAUDE.md` "Committing — close the loop") says to. The userland app can't do this; DOS should. |
| **Idempotent re-run after partial failure** (`stable_release_promote.py`) | ✅ **yes** | Detect the already-done tag / evidence file and surface an `idempotent_skips` list instead of erroring. Critical for `stable-release` (operator Ctrl-C between tag-create and push). DOS has no pointer flip, so the set of side-effects is smaller, but the property is the same. |
| **`--from-manifest` structured scope** (`release` Step 0.5) | ❌ **no** | The manifest (`release-manifest.json`, RMC schema) is emitted by the fanout/dispatch producer skills. Those are host workflow; DOS has no producer that writes one. Skip. |
| **Versioned-install snapshot advance** (`release` Step 7.5) | ❌ **already correctly dropped** | DOS is a pip package; there is no snapshot pointer. The existing skill is right to omit it. |
| **Hero-metric / KEEP-slot gate** (`stable-release` Step 3) | ❌ **already re-grounded** | DOS has no apply-loop funnel. The existing skill already re-grounds the gate on suite + truth-syscall + CI + soak. No change. |
| **Force-promote rationale capture** | — already in DOS | The DOS `stable-release` already requires a `## Force-promote rationale` section. No change. |

## Why the four "yes" rows are the durable ones

**Lease auto-defer is the single highest-value port,** because it is the release
flow *consuming a kernel syscall*. DOS's whole thesis is that a fleet of agents
needs a referee that serializes their effects on shared state. The release skill
is itself one of those agents — and it writes the single most contended region (a
version bump + a tag on `master`). Today it has no idea another loop is mid-write
in `src/dos/`; it can sweep a lane's in-flight edit into the release commit. The
fix is not a new mechanism — it is to read the lane journal the kernel already
maintains and defer the leased region, exactly as `dos arbitrate` would refuse a
contended lane. The release flow becomes a *client of the arbiter's evidence*,
which is the dogfooding the `CLAUDE.md` "DOS on DOS" section asks for.

**The index-race discipline is the lesson the memories paid for.** Five separate
memory entries (`feedback-commit-pathspec-on-shared-tree`,
`feedback-shared-index-commit-by-pathspec-from-worktree`,
`feedback-shared-index-bare-commit-grabs-concurrent-staged`,
`feedback-pathspec-commit-pulls-working-tree`, `project-dos-multi-session-hot-tree`)
record the same scar from different angles: on a hot tree, a bare `git add`/
`git commit` grabs another session's staged or unstaged content. The userland
app's answer is a 944-line atomic-staging helper; DOS's answer (for now) is to
write the recipe those memories distilled into the skill body, so the release flow
follows it by default instead of re-learning it. Encoding it as *prose the skill
obeys* is cheaper than a script and captures everything the memories know.

**The commit-prefix lint and the commit-audit dogfood are two witnesses on the
same surface, at different strengths.** The lint is a *cheap, syntactic* check
("does this subject match the grammar?") run before the commit. `commit-audit` is
the *semantic, ground-truth* witness ("does this subject's claim match its own
diff?") run after. The userland app has only the former; DOS has both and should
use both — the lint catches a malformed subject, `commit-audit` catches a lying
one. Running `commit-audit` at the end of a release is the natural place: a
release is a batch of fresh commits, and the contract says to witness them from
outside the loop that wrote them.

## Phase 4 (deferred): a `scoped_release_stage` analogue

The userland app's `scoped_release_stage.py` stages only *your* hunks of an
interleaved file as a git blob, gates out foreign symbols, and commits the index
atomically under a lock. It is the heavy-weapons answer to hunk-level interleave
(two lanes editing the same file).

DOS defers this for three reasons:

1. **DOS's lane model makes hunk-level interleave rarer.** Lanes here mirror
   top-level dirs (`src`, `docs`, `tests`, …). Two agents editing the *same file*
   is the exclusive-`global`-lane / `SELF_MODIFY` hazard the arbiter already
   refuses — so the contended-file case is supposed to be prevented upstream, not
   reconciled at release time. The lease auto-defer (Phase 1) handles the common
   case (whole files under a leased dir) without any blob surgery.
2. **The discipline-in-prose (Phase 2) covers the residual** — the patch→reset→
   apply recipe in the memories handles a genuinely interleaved file by hand, and
   the skill now names it.
3. **A faithful port needs an index-lock primitive DOS doesn't expose yet.** DOS
   has `archive_lock.py` (a CAS steal) but no worktree-index lock equivalent to
   the userland app's. Building that is real work for a case the first two phases
   already de-risk.

If hunk-level interleave at release time turns out to bite in practice, the build
is: a `scripts/scoped_stage.py` that reuses `dos._tree` for the in-scope/foreign
path algebra and `archive_lock` for atomicity. Not before there's evidence it's
needed — the same YAGNI the `stable-release` skill applies to multi-channel.

## What shipped

- **`scripts/release_context.py`** gains an `active_leases` key: the lane journal
  folded to live leases, each `{lane, lane_kind, tree, stale, holder, age_s}`. A
  `stale` lease (heartbeat past TTL) is reported but not deferred — a dead loop's
  region is fair game. Empty/absent journal → `[]`, never an error.
- **`scripts/check_commit_prefix.py`** — the DOS commit-prefix lint. Always exit
  0; silent on a known prefix; one stderr line on an unknown one.
- **`release/SKILL.md`** — new Step 1.6 (lease auto-defer), hardened Step 1.5/5
  staging discipline, `--lint-prefix` opt-in, post-release `dos commit-audit`
  step, updated JSON-keys table + final-summary shape.
- **`stable-release/SKILL.md`** — an idempotency contract: re-running with the
  same codename detects the already-created tag + evidence file and reports an
  `idempotent_skips` list rather than erroring.

## What did NOT change (and why that's correct)

The version-bump surface (`release_bump.py`, 4 markers + drift guard) and the
stable gate (suite + CI + truth-syscall + soak) were already mature and
DOS-correct. The scope rules (derive-then-proceed, `--scope`, `--whole-tree`) were
already faithfully carried over. This doc adds *safety on a hot tree* and
*dogfooding the kernel's own witnesses* — it does not re-litigate the parts that
were already right.

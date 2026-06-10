<!-- RELOCATED 2026-05-31 from the reference userland app. This is a native DOS plan: its owner code (the foreign-repo solve path) is research that informs this repo, so the plan belongs here, not in the userland app. (The DOS next-stage-plan.md item 4 still lists ISV as host-side — that line predates this relocation and is superseded by it.) The plan-meta block below carries the reference app's historical priority/lane/memory_anchor fields and is no longer read by its /next-up; a pointer stub remains at the old path. -->
<!-- plan-meta
id: ISV
classification: ACTIVE
depends_on: []
priority: P39
percent: 0
shipped: []
remaining: [ISV0, ISV1, ISV2, ISV3, ISV4, ISV5, ISV6, ISV7]
gh_issue: null
lane: orchestration
layer: TOOLING
memory_anchor: project_dispatch_os_issue_solve_plan.md
headline: "The DOS proof point that makes the unique value undeniable: `dispatch-os solve --workspace <repo> --issues 12,15,18,21` points the dispatch OS at a FOREIGN git repo + its GitHub issues and produces verified PRs — N issues fanned out across N truly-isolated git worktrees as N concurrent headless `claude -p` agents, each opening its own PR, but ONLY if the agent's diff passes the foreign repo's own tests/build AND the ship-oracle confirms a real diff that closes that issue. Refusals surface as typed WEDGEs (NO_DIFF / TESTS_RED / NO_ISSUE_LINK), never a silently-bad PR. The differentiator is NOT throughput (anyone can spawn agents that open PRs) — it is the verified-or-it-doesn't-open gate, ported and proven against a repo whose tests the OS did not write. This is the first WRITE graft of the foreign-repo solve path: the separation litmus evolves from 'writes NOTHING into the target' to 'writes ONLY PR branches into the target, never its default branch, and nothing into the OS repo except run logs'. Throughline-first: ISV1 solves ONE real issue end-to-end into ONE verified PR on the live foreign path the same day; later phases thicken that working slice to N-concurrent isolated worktrees, typed refusals, and the demo surface. ANTI-GOAL: do NOT fork the in-repo fanout's shared-tree model — that path correctly refuses worktrees (file-scope partition); this foreign-repo path is the first real consumer of the WT-series worktree isolation, scoped to the foreign workspace only."
-->

# Dispatch OS — Concurrent Issue→PR Solve Plan (ISV-series)

**Status:** ACTIVE · 0% · no dependencies · the WRITE sequel to the Graft-0 read-only research; first real consumer of the WT-series worktree isolation.

**Owner code.** New, all under the foreign-repo solve package (the workspace-parameterized package — pure stdlib, no host-source imports, mirroring the existing research's isolation discipline):
- `solve.py` — the `solve` entrypoint: enumerate issues → fan out → verify → open PRs → reconcile. The orchestrator.
- `gh_issues.py` — the foreign-repo GitHub adapter: `gh issue list/view --json` (read) + `gh pr create` (write). The ONLY module that shells out to `gh`. Thin, mockable, every call goes through one `_gh()` helper so the separation litmus has one chokepoint to assert against.
- `worktree.py` — per-issue isolated `git worktree add` in the **foreign** workspace, branch `dos/issue-<n>`, with an orphan reaper (auto-remove if unchanged) and a never-stall timeout. The WT-series invariants, scoped to the foreign tree.
- `issue_verdict.py` — the typed result envelope (`SOLVED` / `WEDGE(<reason>)`), reusing the closed-enum discipline of `wedge_reason.py`. Reasons: `NO_DIFF`, `TESTS_RED`, `BUILD_RED`, `NO_ISSUE_LINK`, `WORKTREE_CONFLICT`, `AGENT_TIMEOUT`, `AGENT_ERROR`.
- `verify.py` — runs the foreign repo's OWN test/build command (discovered or operator-supplied) and reuses the workspace-parameterized ship-rung logic from the read-only research to confirm "this branch carries a real diff that references this issue".
- `check_solve_isolation.py` — the CI guard (modeled on the host's core-isolation guard + the ratchet-guard pattern): asserts (a) no host-source import anywhere in the package, (b) every `gh`/`git` write in the package targets the foreign workspace and a `dos/*` branch — never the OS repo, never the foreign default branch.

**Reuses (does not fork):**
- The read-only research's `--workspace` resolution, its git-log grep rung, its "reuse the target's own parser" discipline. ISV's verify step is the same rung pointed at a branch diff instead of `git log`.
- `run_id` (CID) — every `solve` run mints a root `run_id`; each per-issue worktree agent is a child `run_id` with `parent_id`/`root_id` lineage. The whole fan-out is one JOIN, not a timestamp grep. (Hard dependency on CID1 landing; ISV1 stamps the run-dir the same way `/dispatch` does.)
- The fanout launch shape from the host's own fanout skill — N background `claude -p` subprocesses, one prompt file + one log + one result envelope each, orchestrator waits on notifications (never polls). ISV reuses the *shape*; the prompt is issue-derived, not phase-derived, and the working dir is the per-issue worktree, not the shared main tree.
- The lease arbiter (the host's fanout-state `dispatch-lane`) + `_StateFileLock` — one lease per `(workspace, run)` so two concurrent `solve` runs against the same foreign repo can't collide; the existing tree-disjointness escape already models "these agents touch disjoint paths".

**Why now.** Operator ask 2026-05-31: *"a proof point being that it can be pointed at a new repo and git issue, and generate a PR for that issue directly… more than that, a user can ask for N PRs at the same time and it does them concurrently… 'one shot' solve 10 git issues… something to really showcase the unique value."* This is the adoption question the cluster has been circling. The gap and the answer are already understood:

- The unanswered question (*"how does a stranger get from zero to a working loop in their own repo?"*) and its root cause (*"the front door is the most operator-coupled layer — the portfolio scheduler — and the domain-invariant layer, the verdict spine, is buried behind it"*).
- The verdict spine has been proven to survive contact with a foreign repo, **read-only** (Graft 0: 4 unconfirmed of 82 claimed phases on a foreign repository, writing nothing).
- The `not-ai-slop` lens: *"don't defend on 'code is good' (unverifiable) — defend on artifacts slop can't fake."* A PR that opened only because it passed the foreign repo's own tests + a ship-oracle that distrusts the agent's own claim **is** such an artifact.

ISV is the WRITE graft that turns the read-only proof into a live demo, and it leads with the domain-invariant layer (verify + concurrency), not the operator-coupled planner — exactly the on-ramp inversion the adoption story argues for. A stranger never has to author a single plan-meta block to get value: they point it at issues they already have.

---

## The differentiator, stated precisely

The demo is **not** "AI opens PRs." That is commodity. The demo is:

> **N issues → N concurrent isolated worktrees → N agents → only the PRs that pass the foreign repo's own gate ever open; the rest surface as typed refusals.**

Two properties no slop tool has:

1. **Verified-or-it-doesn't-open.** A PR opens iff `verify.py` returns green on the foreign repo's own test/build command AND the ship-rung confirms the branch diff references the issue. An agent that produces an empty diff, a red build, or a diff with no issue linkage produces a `WEDGE(<reason>)` — recorded, routed, no PR. The bad number can only shrink. This is the repo's closed-loop-under-distrust ethos (the pure-Python `ship_oracle` that distrusts the model's own SHIPPED) applied to a foreign repo.

2. **Provable isolation at scale.** Each issue runs in its own `git worktree` on its own `dos/issue-<n>` branch. Two agents physically cannot touch the same index. The litmus is checkable in 30s: the foreign repo's reflog shows N `dos/*` branches and nothing on its default branch; the OS repo's `git status` shows only logs under the solve package.

If those two hold, the demo answers the operator ask *and* the adoption gap in one artifact a skeptic can verify by hand.

---

## The separation litmus evolves (the load-bearing boundary)

Graft 0's litmus (port-plan §5.5.3): **the OS writes NOTHING into the target.** ISV is the first write, so the litmus tightens rather than relaxes:

| | Graft 0 (read-only) | ISV (first write) |
|---|---|---|
| Reads from foreign repo | yes (issues, git log, parser) | yes (issues, git log, test cmd) |
| Writes to foreign repo | **never** | **only** `dos/issue-<n>` branches + worktrees + PRs |
| Writes to foreign default branch | n/a | **never** (guard-enforced) |
| Writes to OS repo | only the solve package's run logs | only the solve package's run logs |
| Enforced by | manual (read-only by construction) | `check_solve_isolation.py` (ratchet guard, CI) |

The guard makes the boundary mechanical, not prose — per the repo's own "wire the rule into the step that runs the write" discipline (CLAUDE.md). A merge into the foreign default branch is the human's decision after reviewing the PR; the OS never does it.

---

## Why this needs real worktrees (and why that does NOT contradict fanout)

The host's own fanout skill deliberately **refuses** `git worktree add` and bets on **file-scope partition**: in-repo, the orchestrator knows each agent's target files up front and proves them disjoint, so a shared tree with explicit pathspecs is safe and cheaper.

That bet **cannot** hold here, for two structural reasons:

1. **The file set is unknown a priori.** "Solve issue #18" does not tell you which files the fix touches until the agent has explored. You cannot partition by file when you don't yet know the partition.
2. **Branch-per-issue is the unit of delivery.** A PR is a branch. N PRs = N branches checked out concurrently = N working trees. One shared tree cannot hold N branches at once.

So ISV is the **first real consumer of the WT-series** (the host's worktree-isolation plan, currently DRAFT — its throughline WT1 was scoped to "same-target divergent exploration, judge, winner-to-main"). ISV generalizes WT to "N **disjoint-target** isolated worktrees, each a delivery branch" and inherits WT's hard invariants:
- **Orphan reaper**: a worktree with no diff at agent exit is removed (WT2).
- **Never-stall**: a wedged agent emits `WEDGE(AGENT_TIMEOUT)` and is reaped; the run does not hang (WT4 never-stall invariant).
- **No winner-to-main auto-merge**: ISV never merges to the foreign default branch at all (stricter than WT — the PR is the handoff).

This plan does **not** touch the in-repo fanout path. The shared-tree model stays exactly as it is for in-repo dispatch. Worktrees live only in the solve package's `worktree.py`, only against the foreign workspace. (If WT-series lands its core primitive first, `worktree.py` imports it; if not, `worktree.py` ships the minimal foreign-scoped version and WT adopts it later. Either order works — ISV1 does not block on WT.)

---

## Phases (throughline-first)

The throughline is **one verified PR on the live foreign path**, thickened outward. Phase 1 is end-to-end and enabled — never a buried final integration.

### ISV0 — Baseline (measure-then-change, observation-only, NO release)
Freeze the starting truth before any code writes to a foreign repo. On a foreign repository (the existing brownfield target): count open issues via `gh issue list --json`, record how many have enough signal to be solvable (title + body + a referenced file/path), and record the target's own test/build command (or note its absence — that's a finding). Write `ISV0-baseline-<repo>.json` in the solve package + register in `docs/baselines.yaml:isv0`. This is the denominator the demo's "X of N issues → verified PR" ratio is honest against. Reuses the Graft-0 baseline shape. **No code path enabled, no release.**

### ISV1 — Throughline: ONE issue → ONE verified PR, live (the smallest end-to-end slice) — RELEASE
`dispatch-os solve --workspace <repo> --issue <n>` (singular), no concurrency yet. End to end, the same day:
1. mint a root `run_id` (CID), stamp `_runs/<run_id>/run.json` in the solve package;
2. `gh_issues.fetch(<n>)` → issue title/body;
3. `worktree.create(<n>)` → `dos/issue-<n>` branch in a fresh worktree in the foreign tree;
4. launch ONE headless `claude -p` in that worktree with an issue-derived prompt (fix the issue, commit on the branch, do not push);
5. `verify.run()` → foreign repo's own test/build + ship-rung "diff references issue #<n>";
6. **iff green**, `gh_issues.open_pr(<n>, branch)` with a body that cites the issue (`Closes #<n>`) and embeds the verify evidence;
7. emit `issue_verdict` (`SOLVED` + PR url, or `WEDGE(<reason>)`).
ISV1 ships `solve.py` (single-issue path), `gh_issues.py`, `worktree.py`, `verify.py`, `issue_verdict.py`, and `check_solve_isolation.py` (the guard green from day one). This is the live differentiator in miniature: a real PR that opened only because it passed a foreign repo's own gate. **Release** (user-visible new capability). Demo-able alone.

### ISV2 — Concurrency: N issues → N PRs, isolated, one command — RELEASE
`dispatch-os solve --workspace <repo> --issues 12,15,18,21`. Generalize ISV1's single path to a fan-out:
- take a `(workspace, run)` lane lease (`fanout_state.py dispatch-lane`) so two `solve` runs can't collide;
- one child `run_id` per issue (lineage under the root);
- N background `claude -p`, each in its own worktree, capped by the existing concurrency cap (CPU-2);
- orchestrator waits on notifications, never polls (CLAUDE.md hard rule);
- per-issue `verify` → per-issue PR or per-issue WEDGE, fully independent (one red build does not block the others).
Ship the progress surface that the demo screenshot shows (per-issue worktree + agent progress + PR/WEDGE outcome, wall-clock total). **Release.** This is the headline demo.

### ISV3 — Typed refusals + the WEDGE wall (honesty surface) — RELEASE
Harden the refusal path to the repo's standard: `issue_verdict` reasons become a closed enum shared between producer (`solve.py`) and any reader, exactly as `wedge_reason.py` is shared between `next_up_render` and `picker_oracle`. Each WEDGE carries a one-line human cause (`see: …`) and the evidence (empty diff / failing test names / missing issue link). A completeness check asserts no `UNCLASSIFIED` reason can be emitted (the FQ-410-style guard). The demo now shows the refusals as a feature: "#18 → WEDGE(NO_DIFF), no PR — the gate caught it." **Release** (user-visible refusal envelope).

### ISV4 — `--combine`: N issues → ONE PR (the "one-shot solve 10 issues" variant) — RELEASE
The operator's stretch ask. After the ISV2 fan-out, an optional integrate stage grafts the per-issue branches onto one `dos/batch-<run_id>` branch:
- attempt to graft each verified branch in turn; a branch that conflicts with an already-grafted one drops to `WEDGE(WORKTREE_CONFLICT)` and is reported (not silently dropped);
- run `verify` once on the combined branch (all tests green together, not just individually);
- open ONE PR: `Closes #12 #15 #18 #21`, body lists each grafted diff + the combined verify result.
This is genuinely harder than N PRs (cross-diff conflicts are real) and showcases the integration/synthesis the fan-out enables. `--combine` is a flag on the ISV2 core — the fan-out is unchanged; the graft is an added final stage. **Release.**

### ISV5 — Adoption on-ramp: the zero-plan path documented + a `--dry-run` audit (Ring-1 framing) — RELEASE
Wire ISV into the adoption story. `dispatch-os solve --workspace <repo> --issues … --dry-run` enumerates what it *would* do (issues picked, worktrees it would cut, the verify command it would run) and writes nothing — the "ten-minutes, zero-risk" first contact. Document the cold-start path: a stranger with zero plan-meta blocks points it at their existing issues and gets verified PRs; the planner/portfolio layer is never required. Update the adoption docs with the live command. **Release** (docs + dry-run capability).

### ISV6 — Soak + harden (the close-out monitor)
Run ISV against ≥2 distinct foreign repos (the brownfield target + one more — a real open-source clone with real issues) over a short soak; record the honest ratio (verified PRs / issues attempted, WEDGE breakdown by reason) in `ISV6-soak-<repo>.json` in the solve package. Attach a CI invariant: the isolation guard (`check_solve_isolation.py`) runs in the repo's existing guard sweep so no future edit can let `solve` write to the OS repo or a foreign default branch. The plan is TOMB-eligible once ISV6 ships + the guard is wired (per phased-plan: implementation + a monitor = done). `gates_on_soak` set here if the soak window is calendar-bound.

### ISV7 — (PARK candidate) Pull the issue list from a tracker, not a flag
The natural extension of the earlier conversation: instead of `--issues 12,15,18`, accept `--label good-first-issue` or `--all-open` and let `gh_issues.py` enumerate + rank. This is where "gobble up existing issues" fully lands — but it's strictly additive on top of the ISV2 core (the fan-out doesn't care where the issue list came from). Parked until ISV2-ISV6 prove the solve path; unpark trigger: ISV6 soak shows ≥1 verified PR on a foreign repo.

---

## Non-goals / anti-patterns (explicit)

- **Do NOT fork the in-repo fanout's shared-tree model.** Worktrees are foreign-workspace-only, in `worktree.py`. The in-repo dispatch path is untouched.
- **Do NOT auto-merge to a foreign default branch.** Ever. The PR is the handoff; merge is the human's call. The isolation guard enforces this.
- **Do NOT add a 91st series prefix to the reference app's portfolio concerns.** ISV is a standalone solve package (the standalone-product surface), not new host machinery. It reuses CID's run_id, the existing lease arbiter, and the existing fanout shape.
- **Do NOT open a PR on an unverified diff.** The gate is the product. A demo that opens PRs unconditionally is the slop tool we are explicitly differentiating from.
- **Do NOT poll agent logs/worktrees in a loop.** Wait on notifications; arm a `Monitor` if streaming progress is needed (CLAUDE.md hard cap).

## Open questions (for ISV0/ISV1, not blocking the plan)

1. **Test-command discovery.** How does `verify.py` find a foreign repo's test/build command? ISV1 takes it as an explicit `--verify-cmd` (honest, zero magic); ISV6 can add heuristics (detect `pytest`/`npm test`/`go test`). Start explicit.
2. **`gh` auth in the foreign repo.** `gh` must be authed for the foreign repo's owner. Document as a precondition (like the `setup-browser` bootstrap); `--dry-run` (ISV5) surfaces an auth failure before any write.
3. **Worktree base.** Branch `dos/issue-<n>` cuts from the foreign repo's default branch HEAD at run start; stale-base handling (foreign default moved mid-run) is an ISV6 hardening case, not ISV1.

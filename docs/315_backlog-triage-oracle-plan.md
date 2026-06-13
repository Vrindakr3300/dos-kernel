# docs/315 — the backlog triage oracle: a deterministic floor under "work the backlog"

> **Status:** P1 and P2 executed 2026-06-12, each stamped in its own commit —
> `dos verify docs/315_backlog-triage-oracle-plan P1` (and `P2`) is the
> adjudicator, never this sentence. P3 is a named design follow-up, not started.
> Tracking handle: issue #103.

## The problem — the backlog process is stuck

This repo's real backlog lives in GitHub issues (~50 open at the time of
writing, 15+ labeled `ready`). The kernel ships a picker substrate built for
exactly this shape of problem — `cooldown` (anti re-pick), `pick-priority`
(freshness ordering), `pickable` (typed holds) — but the issue backlog uses
none of it. Five measured consequences:

1. **The kernel picker is blind.** `dos pickable` answers `unit: null` while
   dozens of `ready` issues wait. The picker reads the plan portfolio only;
   issues are not units it can see.
2. **Triage is re-done from scratch, by judgment, every run.** The issue-work
   skill's Step 1 is "read up to 60 issues and rank them." Each run pays the
   full read cost, picks vary run to run, and the ranking evaporates (only
   labels survive — and most issues carry no priority label).
3. **No attempt memory.** Nothing records an `OP_ATTEMPT` for an issue, so
   `dos cooldown issue-N` always answers CLEAR. The re-pick storm the
   cooldown fold was built to break (docs/207 §3) is alive at the issue tier.
4. **No feasibility typing.** Nothing encodes "this issue's fix surface is a
   guarded kernel runtime file." Loops pick those issues, get SELF_MODIFY
   denied at edit time, retry, and wedge — the ENFORCE_BREAKER storms in
   `dos decisions` (4, 6, 11, and 62 consecutive denies in the queue as this
   plan is written) are this failure, recorded.
5. **Half the backlog has no default route.** `design` issues are skipped by
   the skill ("they need a plan first"), and nothing produces those plans —
   so ~25 issues sit permanently invisible to the dispatch process.

## The shape of the fix

A **deterministic triage oracle at the dev-tooling tier**. It names a vendor
(`gh`/GitHub), so it cannot live under `src/dos/` — the same placement
argument the issue-work skill makes for itself. It lives in `scripts/`,
imports `dos` (the allowed direction), and follows the kernel's own
discipline: a pure classify/order core over plain dicts, with every read
(gh, the lane journal, the guard surface set, the plan index) gathered at
the boundary in `main()`.

The floor is **advisory and conservative** (the JUDGE-rung split, docs/86
applied to triage): it can only TYPE and ORDER the backlog. The agent may
still deviate from the top pick, but must state why — deterministic-first,
judgment on the residue. Detection is **under-matching** by construction: a
T1 gate fires only when the issue text literally names a guarded runtime
file; a missed gate degrades to today's behavior (the edit-time hook deny),
never worse.

The closed disposition set:

| Disposition | Meaning | Routed to |
|---|---|---|
| `READY` | offerable now; code/docs work | the queue (ordered) |
| `NEEDS_PLAN` | `design`-labeled, no plan doc yet — offerable as **plan-writing** work | the queue (ordered) |
| `COOLING` | recently attempted and didn't move (the cooldown fold holds it) | skip until the wall |
| `T1_GATED` | fix surface names a guarded kernel runtime file | the operator |
| `OPERATOR_GATED` | `human-only` label | the operator |

`NEEDS_PLAN` being *offerable* is the unsticking move for the design half of
the backlog: writing the `docs/NN` plan IS the next unit of work for a design
issue, so the queue hands it out instead of hiding it.

Ordering for the offerable rows, deterministic end to end:
`(priority tier, ready-label bias, freshness sort_key, issue number)` —
priority labels first (`high` < `medium` < unlabeled < `low`), the
`pick-priority` freshness fold breaks ties *within* a tier (never-attempted
first, then least-recently-tried), and the issue number is the FIFO
tie-break so old work cannot starve.

The unit-id convention is `issue-N`. Recording an attempt
(`--record-attempt N --outcome shipped|drained|blocked|error`) appends the
standard `lane_journal.attempt_entry` so the existing kernel folds —
`dos cooldown issue-N`, `dos pick-priority issue-N` — answer truthfully with
no new mechanism.

## Phase 1 — the triage script + its tests

`scripts/backlog_triage.py`:

- Pure core: `classify_issue` (issue dict → disposition + reason + work
  kind), `order_queue` (the deterministic sort above), `triage` (the full
  fold), `queue_exit_code`.
- Boundary: `gather_issues` (`gh issue list --json …`, or `--issues-json`
  replay mode — the `--attempts JSON` idiom), `gather_t1_surfaces` (from
  `dos.self_modify`, fail-open to empty with a warning), `gather_plan_index`
  (which issue numbers any `docs/**/*-plan.md` references, and which plan
  numbers exist), `gather_attempts` (the lane-journal `OP_ATTEMPT` rows,
  `ts` → ms exactly as `dos cooldown`'s CLI derives it), `record_attempt`.
- Output: a human table grouped by disposition with the top pick named, or
  `--json`. The verdict IS the exit code: `0` work available, `3` open
  issues exist but all are gated/cooling, `4` empty backlog.

`tests/test_backlog_triage.py` pins: each disposition; the under-matching
direction of the T1 gate (synthetic surface set — the classifier takes
surfaces as a parameter); NEEDS_PLAN vs plan-exists routing; the ordering
invariants (freshness reorders within a priority tier and never across one;
FIFO tie-break); the exit-code map; and a journal round-trip (a recorded
attempt makes the real `cooldown_verdict` hold the unit).

**Done when:** `python scripts/backlog_triage.py --json` returns the typed,
ordered queue on this repo, and the test file passes in the kernel suite.

## Phase 2 — wire the issue-work skill to consume it

The skill's Step 1 becomes: run the triage script; the top offerable row is
the default pick; deviating requires one stated sentence of reasoning. A new
final step records the attempt outcome so the next run's cooldown/freshness
folds see it. The skill keeps its judgment guidance — as the residue rung,
not the floor.

**Done when:** the skill's Step 1 shows the script invocation, and the
attempt-recording step names the outcome vocabulary.

## Phase 3 — (design, future) a unit-source seam for `pickable`

The kernel-side completion: an entry-point seam (the `dos.judges` /
`dos.notifiers` pattern) through which a **driver** can enumerate external
backlog units, so `dos pickable issue-42` and the SKP dispatch loops see the
issue backlog natively — the vendor named only in the driver, the kernel
still vendor-clean. Out of scope here; this plan names it so the scripts-tier
oracle is understood as the working surface, not the end state.

## What this deliberately does NOT do

- It does not let the floor *block* a pick — advisory-only, like every
  verdict in the kernel (docs/99).
- It does not write labels or close issues — labeling stays a judgment act
  (skill Step 7), closure stays with git ancestry (`Fixes #N`).
- It does not put `gh` anywhere near `src/dos/` — the vendor litmus holds.

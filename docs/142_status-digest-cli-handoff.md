# docs/142 — `dos status <run_id>`: the Phase-2 CLI handoff (start-here)

**Date:** 2026-06-04
**Status:** ✅ **SHIPPED (Phase 2 + Phase 3), 2026-06-04, commit `5ffc7cd`.** Phase 1 was already shipped + green; this doc was the on-ramp, and the build it opened is now done. `dos status <run_id>` (the CLI verb, `cli.py:cmd_status`) and `dos_status` (the MCP tool, `dos_mcp/server.py`) both land the four-read boundary-gather + the pure fold, with the no-`claimed`-key invariant pinned at both boundaries (`tests/test_cmd_status.py` ×13, + 4 `dos_status` cases in `tests/test_mcp_server.py`; full kernel suite 1890 green). Design decisions §3.1–§3.4 were each pressure-tested by an adversarial design probe against live code — see the "How it actually landed" note below. *Original start-here text retained below for lineage.*

> **How it actually landed (vs the §3 gotchas):**
> - **§3.1 verb name** — top-level `dos status` was FREE; the "collision" was a false alarm (the existing `status` claimants — `dos lease status` → `archive_lock.cmd_status`, and the `lsub` projects `status` — are nested subparsers, structurally disjoint). Registered top-level.
> - **§3.4 stopped predicate** — an explicit `--stopped` flag was the obvious move but was REFUTED by the adversarial pass (it mirrors neither `cmd_liveness`, which gathers unconditionally, nor `cmd_resume`, which calls `gather_ancestry` unconditionally). Shipped the AUTOMATIC predicate instead: `LedgerState.suspended OR liveness == STALLED`, with `--stopped`/`--live` as overrides; the expensive `gather_ancestry` is gated on it (+ `has_intent`), never run on a live run.
> - **§3.3 start_sha** — three-tier: `--start-sha` arg › the ledger INTENT record's `start_sha` › `""` (a conservative 0-commit floor).
> - **§2/§3.5 region** — the spine join: filter replayed leases by `lease.get("run_id") == run_id` (`.get`, never bracket-index — an old un-stamped ACQUIRE must not `KeyError`), read `tree`; `()` when no lease (a valid "not attributable" fact).
> - Exit code IS the liveness verdict (ADVANCING=0/SPINNING=3/STALLED=4), published in the `dos doctor --json` `exit_codes` table next to the sibling verbs.
**Origin:** Selected as the vetted next real build by an adversarial low-hanging-wins audit (2026-06-04) over the DOS strategy corpus's candidate wins. Of 8 candidates, 7 "it's just plumbing" claims were refuted against live code; `dos status` was the one whose leverage survived with a bounded, honest effort.
**Lineage.** Phase 2/3 of **docs/120** (`120_the-status-digest-a-folded-fact-for-a-fleet.md`, the turnkey contract). The surface was specced in **docs/116 §5** (the durable-commons / constrained-A2A problem). Strategy payoff: **`dispatch-os-big-tech-adoption.md` §4** (the threshold-crossing surface: a hand-run CLI verdict → a standardizable A2A fact a platform/SRE team builds a panel on) and **`dispatch-os-the-durable-commons-for-a-fleet.md` §5** (the one honest *not-yet*: the commons is readable but not *legible* until this fail-closed digest folds the four reads into one A2A-shaped fact).

---

## 0. One-line task

> **Fold the four already-shipped run verdicts (liveness · ledger-verified progress · held lease · resume) into one fail-closed `dos status <run_id>` CLI verb (Phase 2) and a `dos_status` MCP tool (Phase 3). The pure fold (`status_digest()`) is done; what remains is gathering the four inputs at the CLI boundary — exactly the `cmd_liveness` pattern, repeated for four verdicts instead of one.**

## 1. What is already shipped (don't rebuild it)

`src/dos/status.py` — Phase 1, **pure and green** (`tests/test_status_digest.py`):

- `status_digest(*, run_id, ledger_state, liveness_verdict, live_region=(), resume_plan=None) -> StatusDigest` — the pure fold. State in, verdict out, **no I/O** (same posture as `liveness.classify` / `resume.resume_plan`).
- `StatusDigest` / `ProgressView` — frozen dataclasses. The **load-bearing invariant**: there is **no `claimed` field** anywhere in the digest, by construction. `ProgressView` reads `ledger_state.verified` ONLY, never `ledger_state.claimed`. `to_dict()` (the `--json` A2A contract) has no `claimed` key. A consumer structurally *cannot* pick up a self-report it is never handed (docs/120 §3, the fail-closed invariant). **Preserve this through Phase 2/3 — it is the whole point of the surface.**
- Carries a `durable_schema` `schema:` tag (refuse-don't-guess across kernel versions).

So Phase 2 writes **no new verdict logic** — it only *gathers* the four inputs `status_digest()` already consumes.

## 2. The four boundary reads (all exist, all run_id-keyed)

| Digest field | Source verdict | Module / fn | Boundary note |
|---|---|---|---|
| `liveness` | `LivenessVerdict` | `liveness.classify(ProgressEvidence, policy)` | evidence = commit-delta (`git_delta`) + journal-delta (`journal_delta.fold_since`), scoped to the run's `(loop_ts, lane)` lease. This is the `cmd_liveness` path (cli.py:872) — copy it. |
| `progress` | `LedgerState` | `intent_ledger.replay(read_all(run_id, cfg))` | the WAL replay → `.verified` (minted) + `.declared_steps`. run_id-keyed via `intent_ledger.ledger_path_for(run_id)`. |
| `region` | held-lease globs | `lane_journal.replay(read_all(cfg.paths.lane_journal))` then filter to the run's `(loop_ts, lane)` lease | the `dispatch_top` filter pattern is the reference. `()` if the run holds no lease — a valid fact, not an error. |
| `resume` | `ResumePlan` \| None | `resume.resume_plan(LedgerState, AncestryFacts, policy)`; ancestry via `resume_evidence.gather_ancestry` | **conditional**: only when the run is *stopped* (None while live). `gather_ancestry` re-adjudicates claimed SHAs vs git ancestry — the expensive I/O path; gate it on a "stopped" detection. |

## 3. The honest gotchas (from the adversarial pass — heed these, they are why this is 3-5 days not 1-2)

1. **CLI namespace collision — resolve this FIRST.** `dos status` is **not free** as a top-level verb. `archive_lock.cmd_status` already exists (cli.py ~1639) and there is already a `lsub` `"status"` subparser (cli.py ~3895, the projects/label surface). **Decide the verb shape before coding:** top-level `dos status <run_id>` (and disambiguate from the existing handlers), or a deliberately distinct spelling. Grep `cmd_status` / `add_parser("status")` and map every existing claimant before registering.
2. **Three gather-paths, not one.** The scout's "200 LOC parallel to `cmd_liveness`" is too rosy — `cmd_liveness` handles *one* verdict; this is liveness + ledger + region + the resume-evidence overhead, each with its own defaults/error modes, each fail-closed. Budget for four boundary readers, not a single copy.
3. **`start_sha` binding is underdefined.** Both liveness and resume need the run's start SHA; it can come from the intent ledger or a `run.json`. **Pick one source** and thread it consistently.
4. **"Stopped" detection gates resume.** `resume_plan` must be None for a live run. Define the stopped/live predicate (liveness `SPINNING`/`STALLED` vs a `SUSPEND` op in the ledger?) before wiring the conditional, or `gather_ancestry` runs needlessly on live runs.
5. **Fail-closed everywhere (docs/120 §3).** Missing ledger → zero `ProgressView` (declared 0 / verified 0), never a raise, never an optimistic guess. No lease → `region=()`. A run that declared no adjudicable intent is still a *valid fact*, not an error.

## 4. The first diff (smallest visible-value wedge)

1. Resolve §3.1 (the verb name).
2. Add `cmd_status(args)` to `cli.py`, **modeled on `cmd_liveness` (cli.py:872)** — gather the four inputs at the boundary, call `status_digest(...)`, print human + `--json`.
3. Register the subparser (`<verb> <run_id> [--workspace] [--json] [--lane] [--loop-ts]`).
4. Add `tests/test_cmd_status.py`: one run with all four verdicts present; one with no lease (`region=()`); one no-intent run (zero `ProgressView`); assert the `--json` output has **no `claimed` key** (the invariant test).

## 5. The checkpoint that proves it landed

```
dos status <run_id> --workspace .          # prints the folded digest (human)
dos status <run_id> --workspace . --json   # the A2A shape
```

- The `--json` output has **zero `claimed` keys** (`... --json | grep -c claimed` → 0). This is the fail-closed proof, not a nicety.
- A run that never took a lease yields `region: []` and does not raise.
- A live (still-running) run yields `resume: null`; a stopped one yields a `ResumePlan` dict.

## 6. Phase 3 (after Phase 2 is green)

The `dos_status` MCP tool in `src/dos_mcp/` — the zero-Python-coupling adoption surface (the big-tech-adoption §4 "a tool the host already calls, not a dependency to risk-review"). It wraps the same gather + `status_digest()` and returns `to_dict()`. Same fail-closed shape; same no-`claimed` invariant. Pin in `tests/test_mcp_server.py`.

## 7. What this is NOT

- Not a new verdict — it folds existing ones. If you find yourself writing ship/liveness/resume *logic*, stop; that logic is already in the kernel.
- Not a place to surface `claimed`. If a `claimed` field appears in the digest or its JSON, the surface has failed its one job.
- Not coupled to the phased-plan host layer — `status_digest` takes a `run_id` + verdicts, names no host, reads no plan schema (the `verify`-needs-no-plan discipline, applied to the digest).

---

## Related reading

- `docs/120_the-status-digest-a-folded-fact-for-a-fleet.md` — the turnkey contract; §11 is the integration map, §3 the fail-closed invariant. This doc is its Phase 2/3 on-ramp.
- `docs/116_the-durable-commons-and-the-constrained-a2a-problem.md` §5 — where the surface was specced (fold four reads into one A2A fact).
- `src/dos/status.py` + `tests/test_status_digest.py` — the shipped Phase 1.
- `src/dos/cli.py:872` (`cmd_liveness`) — the boundary-gather pattern to copy.
- Strategy (in `dos-private`): `dispatch-os-big-tech-adoption.md` §4 (threshold-crossing surface), `dispatch-os-the-durable-commons-for-a-fleet.md` §5 (the not-yet-legible commons this closes).

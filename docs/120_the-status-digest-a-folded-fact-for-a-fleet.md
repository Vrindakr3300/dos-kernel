# 120 — The status digest: one folded, fail-closed fact for a fleet

> **`dos status <run_id>` folds the four shipped reads about a run — liveness
> verdict, ledger-*verified* progress, held lease region, resume verdict — into a
> single A2A-shaped fact that *structurally cannot expose a self-report*. It is the
> phased build of the one surface [`116 §5`](116_the-durable-commons-and-the-constrained-a2a-problem.md)
> specced and left as theory: the projection that turns the durable commons from
> *readable* (a peer can stitch four folds together and risk reading a claim by
> mistake) into *legible* (one verb, one fact, fail-closed by construction). It mints
> no new evidence and no new durable record — it is a Layer-3 projection over folds
> the kernel already ships, the same posture as `dos top` and `dos decisions`.**

Status: design plan. Phase 0 is a re-statement of shipped code (the four folds all
exist). Phases 1–3 are the build (pure digest → CLI verb → MCP tool). Phase 4 is the
named follow-up tier. **No new mechanism is invented here** — the contribution is the
*fold* and its fail-closed *construction*, not a new thing to trust. The theory this
plan executes is [`116`](116_the-durable-commons-and-the-constrained-a2a-problem.md)
(the durable commons / constrained-A2A note, §5 "status as a folded fact"); the
positioning sibling — *why a buyer wants this* — is `dos-private/dispatch-os-big-tech-adoption.md`
§4 (the surface that crosses the threshold "a CLI an engineer runs by hand" → "infra
a platform team builds a panel on") and `dos-private/dispatch-os-the-durable-commons-for-a-fleet.md`
§5. One-way arrow: those docs reference this code; nothing here depends on them.

---

## 1. The problem: the commons is readable but not legible

The durable commons is already *readable* (`116 §5`): a peer agent or a human can
call `liveness.classify`, `replay` the intent ledger, `replay` the lane-journal WAL,
and `resume.resume_plan`. What it lacks is a single verb that folds **"where is run R
right now?"** into one fact. The status tax of [`116 §1`](116_the-durable-commons-and-the-constrained-a2a-problem.md)
(status need ∝ runtime × downstream dependents) wants exactly that: a peer that
depends on R should poll **one** adjudicated status, not stitch four reads together —
because every read it stitches by hand is a chance to read the wrong field and
re-open the trust hole.

> The danger is not that the four folds are hard to call. It is that a hand-rolled
> status read *can* call the wrong one. `LedgerState` carries both `claimed` (the
> agent's forgeable self-report) and `verified` (the kernel's minted belief) side by
> side (`intent_ledger.py:284-285`). A peer that reads `claimed.get(step)` instead of
> `verified.get(step)` has built a blackboard (`103`) by accident — it is now
> believing a self-report. The status digest's whole job is to make that mistake
> *unreachable*: the only fields it exposes are adjudicated, so a consumer cannot
> pick a self-report even if it tries.

This is the [`big-tech-adoption §4`](https://github.com/anthony-chaudhary/dos-private)
threshold in mechanism terms. A platform/SRE team's recurring ask is *"give me one
fact about this run I can trust and put on a dashboard."* Today the answer is "call
these four functions and be careful which field you read," which is not a thing a team
standardizes on. `dos status --json` is.

---

## 2. What already exists — Phase 0 (the four folds are shipped)

The digest composes four pure verdicts, each already shipped, each already a *no* in
disguise ([`82`](182_the-kernel-is-a-taxonomy-of-refusal.md)'s taxonomy — the reason
the fold is sound is that every field is a re-derivation, not a belief):

| Field | Shipped fold | Signature | What it refuses to believe |
|---|---|---|---|
| **liveness** (is it moving) | `liveness.classify` | `(ProgressEvidence, policy) -> LivenessVerdict` (`liveness.py:227`) | "I'm making progress" — verdict from git/journal delta |
| **progress** (what verifiably shipped) | `intent_ledger.replay` → `LedgerState` | `LedgerState.verified: {step: VerifiedStep}` (`intent_ledger.py:285`) | `claimed` — reads the **minted** map, never the self-report |
| **region** (what's fenced off) | `lane_journal.replay` | the run's live lease in the folded live-lease set | a narration of "I'm working on X" — only adjudicated `ACQUIRE` folds |
| **resumability** (if stopped) | `resume.resume_plan` | `(LedgerState, AncestryFacts, policy) -> ResumePlan` (`resume.py` enum `resume.py:60`) | the dead run's last `STEP_CLAIMED` — re-entry SHA is ancestry-checked |

The boundary pattern to mirror already exists too: `dispatch_top._lease_liveness`
(`dispatch_top.py:182`) shows how to build `ProgressEvidence` from a lease row at the
CLI boundary and hand it to the *pure* `classify` — the digest does the same per run.
So Phase 0 is **done**: nothing in §2 is a gap. The build is the fold and the verb.

---

## 3. The invariant — fail-closed by construction (the load-bearing rule)

Everything below is in service of one property, and any step that violates it is
wrong:

> **The digest reads only adjudicated fields. It reads `verified`, never `claimed`;
> the liveness *verdict*, never a "progress" field; the resume *verdict*, never the
> dead run's last `STEP_CLAIMED`. A consumer of `dos status` therefore cannot
> accidentally consume a self-report, because the digest's construction never exposes
> one. Legibility without re-opening the trust hole — the A2A-shaped fact is, by
> construction, only ever the adjudicated residue.**

Two corollaries that become test obligations (§Phase 1):

- **"Fail-closed" means refuse, don't guess.** When a fold cannot produce a verdict
  (no intent ledger for the run, corrupt-past-fold, a `durable_schema` tag from a
  newer kernel), the digest reports the *refusing* verdict (`UNRESUMABLE`,
  `UNKNOWN`) — never an optimistic default, never a fabricated "looks fine." A digest
  that guesses is a self-report with extra steps.
- **`claimed` is never a field of the output.** Not hidden, not "advisory" — absent.
  The output type has no slot for a self-report, so no consumer and no future edit can
  surface one. (The grep litmus of §Phase 1: `claimed` does not appear in the digest's
  output dataclass.)

---

## 4. Phase 1 — the pure `StatusDigest` and its fold

**Goal.** A pure function `status_digest(...) -> StatusDigest` that folds the four
shipped verdicts into one dataclass, with all I/O gathered at the caller boundary
(the `arbitrate`/`classify` rule: state-in, verdict-out). New module
`src/dos/status.py` (Layer 1 sibling — it imports the four folds; it is internally
cohesive, no host, no I/O policy).

**Steps.**

1. **`StatusDigest` dataclass** (`src/dos/status.py`): fields
   `run_id`, `liveness: LivenessVerdict`, `progress` (a small derived view over
   `LedgerState.verified` — `{verified_count, declared_count, verified_steps}`,
   reading **only** `verified`), `region` (the run's held lease glob-set or `()`),
   `resume: ResumePlan | None` (None while live; the verdict once stopped),
   `schema:` tag per the `durable_schema` floor ([`116 §6`](116_the-durable-commons-and-the-constrained-a2a-problem.md) discipline; the digest is a record other
   tools read; tag it so a newer-kernel digest is refused, not misparsed).
2. **`status_digest(ledger_state, liveness_verdict, live_lease, resume_plan)`** — the
   pure fold. Takes the four *already-computed* verdicts (the boundary computed them),
   assembles the dataclass. No subprocess, no file, no clock — pure, like
   `resume_plan`. The `progress` view is computed here from `ledger_state.verified`
   *only*; `ledger_state.claimed` is read by nothing.
3. **Fail-closed assembly** — if `ledger_state` is the empty/UNRESUMABLE floor
   (`LedgerState.has_intent()` false, `intent_ledger.py:293`), `progress` is
   `{0, 0, ()}` and `resume` is the `UNRESUMABLE` verdict; the digest is still a valid
   fact ("this run declared no adjudicable intent"), never an exception and never a
   guess.

**Tests** (`tests/test_status_digest.py`):

- `claimed` does not appear in `StatusDigest` (grep the dataclass fields + an
  assertion that a `LedgerState` with a `claimed` step the agent never landed shows
  `verified_count == 0` in the digest — the self-report is invisible).
- A live run (no resume) → `resume is None`, liveness carried through verbatim.
- A stopped run with empty residual → `resume.verdict == COMPLETE`.
- A run with no intent ledger → fail-closed floor (UNRESUMABLE, zero progress), no
  raise.
- Purity: `status_digest` makes no I/O (same harness as the `resume_plan`/`classify`
  purity tests).

**Ship gate.** `pytest -q tests/test_status_digest.py` green; `dos verify` this phase
once committed.

---

## 5. Phase 2 — the `dos status <run_id>` CLI verb (boundary I/O lives here)

**Goal.** `dos status <run_id>` and `dos status --json <run_id>`. This is the
*boundary*: it gathers the four verdicts (the I/O) and calls the pure Phase-1 fold.
Read-only, takes no lease, launches nothing — the posture of `dos top` /
`dos decisions`.

**Steps.**

1. **A boundary builder** (`src/dos/status.py`, the impure half kept distinct from the
   pure fold, the `dispatch_top` split): for `run_id`, gather
   - `LedgerState` via `intent_ledger.read_all(run_id, cfg=…)` → `intent_ledger.replay(entries)`
     (both `replay` folds are **pure over entries** — the I/O is the `read_all`, the
     fold is pure; see the §11 handoff for the corrected call shape);
   - the live lease via `lane_journal.read_all(cfg.paths.lane_journal)` →
     `lane_journal.replay(entries)`, then filter the live-lease list to the run's
     `(loop_ts, lane)` lease (`dispatch_top.py:471-475` is the exact pattern);
   - `LivenessVerdict` via the `_lease_liveness`-style path (`dispatch_top.py:182`) —
     build `ProgressEvidence` from `git_delta` (commits since the run's `start_sha`)
     + `journal_delta.fold_since` (events-since-start + newest-beat-age scoped to the
     run's lease), hand to the pure `classify`;
   - `ResumePlan` via `resume_evidence` (the ancestry read) → `resume.resume_plan`,
     *only if the run is stopped* (live → `None`).
   Then call `status_digest(...)`.
2. **CLI wiring** (`src/dos/cli.py`): `dos status <run_id>` prints a human view (one
   block: liveness chip, `verified/declared` progress, held region, resume verdict);
   `--json` emits the digest (the MCP/peer-agent consumer surface). Match the existing
   verb registration + `--workspace`/`--json` conventions.
3. **The `--json` shape is the A2A contract** — stable field names, the `schema:` tag
   present, `claimed` absent. This is what a peer agent or a dashboard parses, so it is
   the load-bearing output (the human view can change freely; the JSON is the ABI).

**Tests** (`tests/test_status_cli.py`):

- End-to-end on a fixture run-dir: `dos status --json <id>` round-trips to a
  `StatusDigest` with the expected verified count and liveness verdict.
- A live run prints no resume line; a stopped-complete run prints `COMPLETE`.
- `--json` output contains no `claimed` key (the §3 grep litmus at the CLI boundary).
- A bogus / unknown `run_id` → fail-closed (a digest that says "no such adjudicable
  run," exit non-zero, not a stack trace).

**Ship gate.** CLI tests green; `dos status --json <a-real-dogfood-run-id>` returns a
fact on this repo (dogfood — the kernel reads its own commons).

---

## 6. Phase 3 — the `dos_status` MCP tool (the big-co adoption surface)

**Goal.** Expose the digest as an MCP tool so an MCP-speaking host (Claude Desktop,
Cursor, Cline, an Agent-SDK app, an internal platform tool) can poll one run's
adjudicated status with **zero Python coupling** — the
[`big-tech-adoption §4`](https://github.com/anthony-chaudhary/dos-private) surface that enters
a company that would never `pip install` the kernel. This is the same kernel/consumer
split as the existing MCP tools ([`80`](80_mcp-server-surface.md)): the server
`import dos`, nothing under `src/dos/` imports `dos_mcp`.

**Steps.**

1. **`dos_status` tool** (`src/dos_mcp/`): a `FastMCP` tool taking `run_id` (+ optional
   `workspace`), resolving the served workspace via the same `SubstrateConfig` seam as
   the other tools (explicit `workspace` › `DISPATCH_WORKSPACE` › cwd), passing the
   built config **explicitly** into the boundary builder (the long-lived-server /
   concurrent-workspace rule, `test_mcp_server.py`), returning the `--json` digest.
2. **Fail-closed across the wire** — an unknown run / unreadable ledger / newer-schema
   record returns a *structured* refusal (the [`115`](115_the-under-what-axis-environment-and-version-provenance.md)
   `SCHEMA_UNREADABLE` MCP error precedent: a typed error code, never a guessed-fine
   payload). A peer that polls over MCP must be able to tell "refused" from "fine."

**Tests** (`tests/test_mcp_server.py`, extended): the `dos_status` tool returns the
digest for a fixture run; an unknown run returns the structured refusal, not a fabricated
status; `claimed` absent from the wire payload.

**Ship gate.** MCP tests green under the `[mcp]` extra; the tool callable over stdio.

---

## 7. Phase 4 — the named follow-ups (each a fold over existing state, none a new trust)

Deliberately deferred; listed so the contract knows the shape and the discipline (every
one is a projection over shipped state, never a new thing to believe — the §3 invariant
holds for all of them):

- **Cross-run fleet view** — `dos status` with no arg folds *every* tracked run into a
  table (the `dispatch_top` altitude, but the digest's adjudicated fields rather than
  swimlanes). One fact per run, fail-closed each.
- **The env-print fold** ([`115`](115_the-under-what-axis-environment-and-version-provenance.md))
  — add "under what did R declare its intent" (kernel/SHA/Python/OS) to the digest, so a
  consumer sees not just *what* R did but *under what* — `FLEET_ENV_MISMATCH` becomes a
  status field.
- **A push channel** — a peer *subscribes* to R's transitions (liveness flips,
  `STEP_VERIFIED` mints, the COMPLETE edge) rather than polling. This is the only
  follow-up with real new surface (a transition stream over the WAL tail), and it wants
  its own design pass — it must stay fail-closed (emit the adjudicated transition, never
  a "progress" ping).
- **`completion` integration** ([`117`](117_completion-as-a-verdict-the-end-of-working-in-passes.md))
  — once the *live* COMPLETE verdict lands, the digest's `resume` field generalizes to a
  live `completion` field (CONVERGING/THRASHING/COMPLETE), so "is R done *now*" is a
  status field, not only a resume-time answer. 120 and 117 compose: 117 makes the live
  completion verdict; 120 is where a peer reads it.

---

## 8. Why this is the kernel's shape, not a status feature ([`116 §6`](116_the-durable-commons-and-the-constrained-a2a-problem.md), made executable)

A blackboard could also offer a "status" read — and it would be worthless, because it
would report what the agent wrote about itself. DOS's status read is worth polling for
exactly one reason: **the same distrust that makes every syscall a refusal makes every
field in the digest a re-derivation.** The four folds are each a *no* (`82`): liveness
refuses "I'm making progress"; the ledger refuses to read `claimed` as done; the WAL
refuses to record a narration as an effect; resume refuses to trust the dead run's last
claim. The digest is not a second thing DOS does alongside refusing — **it is what
refusing produces, folded into one fact.** That is why Phase 1's invariant (§3) is the
whole plan and the CLI/MCP phases are just transports for it.

---

## 9. Dogfood — close the loop on this repo

When a phase is built and green, adjudicate it with the kernel itself (the
[`CLAUDE.md`](../CLAUDE.md) ritual):

```bash
# Phase 2 lands → the kernel reads its own commons:
dos status --json <a-recent-dogfood-run-id>     # one fail-closed fact, claimed absent
dos verify --workspace . docs/120_the-status-digest-a-folded-fact-for-a-fleet status
```

If `dos status` ever surfaces a `claimed` field, or returns an optimistic default for a
run with no ledger, the §3 invariant has drifted from the code and the phase is not
shipped — let the oracle, not the narration, close it.

---

## 10. See also

- [`116_the-durable-commons-and-the-constrained-a2a-problem.md`](116_the-durable-commons-and-the-constrained-a2a-problem.md)
  §5 — the **spec this plan executes** (status as a folded fact). 116 is the theory
  (why the commons is sound + the one buildable surface); 120 is the phasing.
- [`107_resumable-work-and-the-intent-ledger.md`](107_resumable-work-and-the-intent-ledger.md)
  — the intent ledger (`STEP_CLAIMED` vs `STEP_VERIFIED`); the digest's progress field
  reads `verified`, never `claimed`.
- [`117_completion-as-a-verdict-the-end-of-working-in-passes.md`](117_completion-as-a-verdict-the-end-of-working-in-passes.md)
  — the **live** COMPLETE verdict the §7 follow-up folds into the digest; 117 computes
  it, 120 is where a peer reads it.
- [`182_the-kernel-is-a-taxonomy-of-refusal.md`](182_the-kernel-is-a-taxonomy-of-refusal.md)
  — every fold the digest composes is a kind of *no*; the digest is what refusing
  produces.
- [`80_mcp-server-surface.md`](80_mcp-server-surface.md) — the kernel/consumer split the
  Phase-3 `dos_status` tool follows (the server imports the kernel; the kernel is
  unaware of it).
- [`115_the-under-what-axis-environment-and-version-provenance.md`](115_the-under-what-axis-environment-and-version-provenance.md)
  — the env-print the §7 follow-up folds in, and the `SCHEMA_UNREADABLE` structured-MCP-
  refusal precedent the Phase-3 fail-closed wire error follows.
- `dos-private/dispatch-os-big-tech-adoption.md` §4 / `dispatch-os-the-durable-commons-for-a-fleet.md`
  §5 — the positioning siblings (why a platform/SRE team wants this surface; the
  threshold from hand-run CLI to standardized infra). One-way arrow: those reference
  this code.

---

## 11. Implementation handoff — what another agent can pick up and type *now*

This section is the turnkey contract for Phase 1 (the self-contained, ready-to-build
piece). §1–§10 are the design; this is the *do*. An agent should be able to start
typing without re-deriving a single signature. **The lane is `src` (a new
`src/dos/status.py`) + `tests` — disjoint from any other in-flight work; it is NOT a
`SELF_MODIFY`/`global` hazard.** Everything below was verified against source at
`abd0692` — but re-run the two-line check in §11.1 first, because a sibling agent may
have moved a line.

### 11.0 Two corrections to the prose above (so you don't repeat the author's drift)

While writing §5 the author cited two call shapes wrong; they are fixed in §5 now, but
state them once more because they are the *most likely* place to go wrong:

1. **Both `replay` folds are PURE over entries — the I/O is a separate `read_all`.**
   `intent_ledger.replay(entries)` (`intent_ledger.py:318`) and
   `lane_journal.replay(entries)` (`lane_journal.py:286`) take an *iterable of dict
   entries*, not a `run_id`. The boundary reads first:
   `intent_ledger.read_all(run_id, cfg=…)` (`intent_ledger.py:162`) →
   `replay(...)`; `lane_journal.read_all(cfg.paths.lane_journal)` →
   `replay(...)` (the exact pattern is `dispatch_top.py:471-475`).
2. **`LedgerState.has_intent` is a `@property`, not a method** (`intent_ledger.py:293`).
   Write `state.has_intent`, not `state.has_intent()`.

### 11.1 Confirm the ground before you start (10 seconds)

```bash
cd dos
python -m pytest -q                                  # must be green before you touch anything
dos verify --workspace . docs/120_the-status-digest-a-folded-fact-for-a-fleet status
#   expect: NOT_SHIPPED ... (via none)   ← Phase 1 is not built; that's the starting line
```

### 11.2 Phase 1 — the exact module skeleton (`src/dos/status.py`)

The **pure** half. Two types + one pure function. The fail-closed invariant (§3) is
*structural*: `StatusDigest` and its `ProgressView` have **no `claimed` field**, so no
consumer can read a self-report. Copy this shape:

```python
"""The status digest — one fail-closed, folded fact about a run (docs/120).

Layer-1 projection: folds four shipped verdicts (liveness / ledger-verified /
held lease / resume) into one record. PURE — the four verdicts are computed at
the caller boundary and handed in (the arbitrate/classify rule). The record
carries NO `claimed` field by construction: a consumer cannot read a self-report.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from dos.liveness import LivenessVerdict
from dos.resume import ResumePlan
from dos.intent_ledger import LedgerState

STATUS_DIGEST_SCHEMA = 1          # durable_schema floor (116 §6): tag the record

@dataclass(frozen=True)
class ProgressView:
    """The adjudicated progress view — reads LedgerState.verified ONLY.

    `verified_count` / `declared_count` / `verified_steps` are derived from the
    kernel-minted `verified` map. There is deliberately no `claimed` here.
    """
    verified_count: int
    declared_count: int
    verified_steps: tuple[str, ...] = ()

@dataclass(frozen=True)
class StatusDigest:
    run_id: str
    liveness: LivenessVerdict
    progress: ProgressView
    region: tuple[str, ...] = ()          # the run's held lease globs (or ())
    resume: ResumePlan | None = None      # None while live; the verdict once stopped
    schema: int = STATUS_DIGEST_SCHEMA

    def to_dict(self) -> dict:
        # The --json A2A contract. `claimed` is ABSENT — that absence is the point.
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "liveness": self.liveness.to_dict(),          # liveness.py:210
            "progress": {
                "verified_count": self.progress.verified_count,
                "declared_count": self.progress.declared_count,
                "verified_steps": list(self.progress.verified_steps),
            },
            "region": list(self.region),
            "resume": self.resume.to_dict() if self.resume else None,  # resume.py:217
        }

def status_digest(
    *,
    run_id: str,
    ledger_state: LedgerState,
    liveness_verdict: LivenessVerdict,
    live_region: tuple[str, ...] = (),
    resume_plan: ResumePlan | None = None,
) -> StatusDigest:
    """Fold the four already-computed verdicts into one digest. PURE.

    `progress` is built from `ledger_state.verified` ONLY — `ledger_state.claimed`
    is read by nothing here. Fail-closed: an empty/no-intent LedgerState yields a
    zero ProgressView, never a raise and never a guess.
    """
    verified = ledger_state.verified                     # {step_id: VerifiedStep}
    progress = ProgressView(
        verified_count=len(verified),
        declared_count=len(ledger_state.declared_steps),
        verified_steps=tuple(sorted(verified)),
    )
    return StatusDigest(
        run_id=run_id,
        liveness=liveness_verdict,
        progress=progress,
        region=live_region,
        resume=resume_plan,
    )
```

That is the whole pure surface. Note what is *not* here: no file read, no clock, no
`run_id` → entries lookup. The boundary (Phase 2) does that and calls this.

### 11.3 Phase 1 — the exact test file (`tests/test_status_digest.py`)

Name these tests; each maps to a §3/§Phase-1 obligation:

- `test_claimed_field_absent_from_digest` — the **load-bearing** test. Build a
  `LedgerState` with a `claimed` step the agent never landed (`claimed={"s1":"deadbeef"}`,
  `verified={}`). Assert `digest.progress.verified_count == 0` AND
  `"claimed" not in digest.to_dict()` AND `"claimed" not in digest.to_dict()["progress"]`.
  The self-report is invisible.
- `test_live_run_has_no_resume` — `resume_plan=None` → `digest.resume is None`,
  `to_dict()["resume"] is None`.
- `test_stopped_complete_run` — pass a `ResumePlan(verdict=Resume.COMPLETE, …)` →
  it round-trips through `to_dict()`.
- `test_no_intent_is_fail_closed` — an empty `LedgerState(run_id="r")` (has_intent
  False) → `progress == ProgressView(0, 0, ())`, no raise.
- `test_status_digest_is_pure` — call `status_digest(...)` and assert it touched no
  disk/clock (mirror the purity assertion style in `tests/test_resume.py` /
  `tests/test_liveness.py` — find their pattern and copy it).
- `test_verified_count_tracks_verified_map` — N verified steps → `verified_count == N`,
  independent of how many were `claimed`.

Build the `LedgerState` / `VerifiedStep` / `ResumePlan` fixtures directly (they are
plain frozen dataclasses — see `intent_ledger.py:236,303` and `resume.py:196` for the
fields). No I/O needed for Phase 1 tests — that is the point of the pure/boundary split.

### 11.4 The integration map for Phase 2 (when you get there — don't start here)

The boundary builder (impure half of `src/dos/status.py`) reuses gather logic that
already exists; do **not** re-write it:

| Need | Reuse | At |
|---|---|---|
| run-start ms from run-id | `run_id.ts_ms_of(run_id)` | `cli.py:904` |
| commits since start | `_git_delta_count(start_sha, cfg)` | `cli.py:915` (or `git_delta.count_commits_since`) |
| journal delta for the lease | `_journal_delta(cfg, started_ms=…, now_ms=…, lease_key=(loop_ts,lane))` | `cli.py:923` |
| build `ProgressEvidence` + classify | the block at `cli.py:943` → `liveness.classify` | `cmd_liveness`, `cli.py:871` |
| ledger entries → state | `intent_ledger.read_all(run_id, cfg=…)` → `replay` | `intent_ledger.py:162,319` |
| live lease for the run | `lane_journal.read_all(cfg.paths.lane_journal)` → `replay`, filter to `(loop_ts,lane)` | `dispatch_top.py:471-475` |
| ancestry → resume verdict | the gather in `cmd_resume` (`resume_evidence.gather_ancestry` → `resume.resume_plan`) | `cli.py:984` |

The cleanest Phase-2 move is to **factor the gather out of `cmd_liveness`/`cmd_resume`
into small boundary helpers** that both the existing verbs and the new `cmd_status`
call — so the digest cannot drift from what `dos liveness`/`dos resume` compute. (If
that refactor feels too broad for one commit, copy the gather into `status.py`'s
boundary half for Phase 2 and leave a `TODO: dedupe with cmd_liveness` — but the
factor-out is the right end state.)

CLI wiring: add `cmd_status(args) -> int` next to `cmd_decisions` (`cli.py:2298`) and a
subparser with `.set_defaults(func=cmd_status)` (the pattern at `cli.py:3250+`), with
`run_id` positional, `--json`, and the `--workspace` shared option. `cmd_memory`
(`cli.py:2362`) is the model for a verb that *also* has an MCP twin — follow it for
Phase 3 (`dos_status` in `src/dos_mcp/`, mirroring the shipped `dos_recall` tool).

### 11.5 Done-criteria for Phase 1 (the ship gate, restated as a checklist)

- [ ] `src/dos/status.py` exists with `StatusDigest` / `ProgressView` / `status_digest`
      exactly as §11.2 (no `claimed` field anywhere in the module).
- [ ] `tests/test_status_digest.py` green, all six §11.3 tests present.
- [ ] `python -m pytest -q` still fully green (no regressions).
- [ ] `grep -rn "claimed" src/dos/status.py` returns **nothing** (the structural litmus).
- [ ] Commit on `master`, staging ONLY `src/dos/status.py` + `tests/test_status_digest.py`
      (disjoint `src`/`tests` lane; do not sweep concurrent work). Subject grammar:
      `status: pure StatusDigest fold (docs/120 Phase 1)`.
- [x] `dos verify --workspace . docs/120_the-status-digest-a-folded-fact-for-a-fleet status`
      — **OBSERVED after the Phase-1 commit: `SHIPPED ... status <sha> (via grep-subject)`.**
      Note the *rung*: the commit subject `status: pure StatusDigest fold …` literally
      contains the phase token `status`, so the **grep-subject** rung matched it and
      flipped the verdict — NOT the file-path/execution rung. The author's first guess
      (that it would stay `NOT_SHIPPED` until the Phase-2 verb) was wrong: the coarse
      grep rung keys on the subject line, not on the verb existing (the docs/114
      "grep floor is gameable" coarseness, observed live). Phase 1 *did* genuinely ship,
      so SHIPPED is not *false* — it is just coarser than "the verb exists." Don't read
      `(via grep-subject)` as "the CLI is built"; read the rung. A sharper future rung
      (file-path on `src/dos/status.py`, or execution) would be a tighter signal.

### 11.6 Ordered first-session checklist (the literal next 30 minutes)

1. Run §11.1 (confirm green + the NOT_SHIPPED starting line).
2. Open `tests/test_resume.py`, find its purity-assertion + dataclass-fixture style.
3. Write `tests/test_status_digest.py` first (TDD) — the six tests in §11.3, RED.
4. Write `src/dos/status.py` from the §11.2 skeleton — tests GREEN.
5. `grep -rn "claimed" src/dos/status.py` → nothing.
6. Full `pytest -q` → green.
7. Commit the two files only (§11.5 grammar).
8. Update the docs/README.md row for 120 from `📋 planned` to `🚧 Phase 1 shipped`
   (and leave a one-line note in the handoff memory `project-dos-big-tech-adoption.md`).
9. Stop. Phase 2 (the CLI boundary) is the next agent's pickup, with §11.4 as its map.

The discipline that makes this safe to hand off: **Phase 1 is pure and self-contained.**
It cannot break the running kernel (nothing imports it yet), it has no I/O to get wrong,
and its one invariant (`claimed` absent) is grep-checkable. An agent can land it, prove
it, and stop — exactly the small, verifiable unit the kernel is built to make cheap.

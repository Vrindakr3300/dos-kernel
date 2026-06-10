# 281 — Bug: the PRE-admission hook reads a phantom "live" lane (WAL fold has no TTL/heartbeat/PID expiry)

**Date:** 2026-06-09
**Severity:** HIGH — silently revokes the Read/Edit tools for an unrelated interactive session, and warns on every tool call, whenever an orphaned lease sits in the lane-journal WAL.
**Reported from:** the reference userland app, where the `dos-kernel@dos` plugin hook is enabled and the bug bites. Reproduced live during a field audit of that host's lane journal.

## Symptom

With the `dos-kernel@dos` plugin installed, an interactive Claude Code session in a workspace whose lane-journal contains an **orphaned (un-released) `ACQUIRE`** gets, on essentially every tool call:

> DOS PRE-admission (advisory): lane 'Bash' has an EMPTY tree (unknown blast radius) and cannot share live lane 'alpha' — unknown blast radius is never safe to admit concurrently. …

and **hard denials** on KNOWN-tree tools:

> DOS PRE-admission: lane 'Read' … cannot share live lane 'DTE' …
> DOS PRE-admission: lane 'Edit' cannot share live lane 'replan': exact-glob overlap …

…even though `dos lease-lane live`, `dispatch_loop_status --leases`, and `dos doctor` all show **no live loop**. The cited lane rotates (`alpha`→`DTE`→`replan`) as different orphans appear. Reproduced live during the audit; clearing the orphan immediately restored the tool.

## Root cause (4 stacked defects, root first)

### 1 (ROOT) — `LiveLeasesFromWAL` / `replay` have no liveness expiry

`go/internal/hook/wal.go::replayJournal` and its Python twin `src/dos/lane_journal.py::replay` fold the journal **purely structurally**:
- `ACQUIRE`/`RECONCILE` → add a lease keyed `(loop_ts, lane)`
- `RELEASE`/`SCAVENGE` → remove it
- `HEARTBEAT`/`ADOPT` → update `heartbeat_at` etc.

`LiveLeasesFromWAL` returns whatever is structurally un-released. **Nothing compares `ttl_minutes`, `heartbeat_at`, or the holder PID against wall-clock `now`.** So a loop that `ACQUIRE`s and then crashes/exits without `RELEASE` leaves an **immortal** lease — it dies only when *another* actor appends a `SCAVENGE` (`reconcile_orphan` writer-side, `dead_for_reclaim` supervisor-side). Between those, the orphan is "live" and the PRE hook enforces against it on every tool call.

The Python module docstring even references a separate **`journal_delta` "heartbeat-freshness fold … the instant the heartbeat-freshness fold trusts"** — but the hook's reader (`LiveLeasesFromWAL` → `pretool_sensor.live_leases_for`) **never calls it**. Expiry is simply not part of the live-set the admission gate sees.

Field proof:
```
23:10:29 ACQUIRE alpha  pid=47172  reason="lane-lease:a1"
  … (every Bash call warns "cannot share live lane 'alpha'") …
23:24:03 SCAVENGE alpha pid=47172  reason="reconcile_orphan"   # dies 14 min later
```
and a DEAD-holder `replan` lease (holder `…:33968`, PID confirmed dead via `tasklist`) hard-DENIED an `Edit` to the findings queue — a dead orphan blocking a live session's legitimate write.

### 2 — Two lease namespaces over one file ⇒ `--leases` and the hook structurally disagree

`dispatch_loop_status --leases` reads the host's `execution-state.yaml::dispatch_loop_leases`; the hook reads the lane-journal WAL via `LiveLeasesFromWAL`. A `dos arbitrate` / a pytest fixture / a sibling session can `ACQUIRE` in the WAL without writing the host registry block, so "0 live loops" and "live lane alpha" are *both correct about their own store*. This is what makes the phantom invisible to the operator's liveness probes.

### 3 — `decide.go::Decide` escalates contention-only refusals to a hard DENY for known-tree tools

```go
provable := av.reasonClass != "" || treeKnown
if provable { return deny } else { return warn-and-pass }
```
A `SELF_MODIFY` deny (typed `reasonClass`) is justified. But a *contention-only* refusal — "cannot share live lane X", **no `reasonClass`**, refused solely because a lane was held — becomes a hard `permissionDecision: deny` as soon as the request tree is known (Read/Edit). So a **phantom** X silently revokes Read/Edit, while Bash (unknown tree) only warns. That asymmetry is why operators reach for the "route everything through Bash" workaround.

### 4 — Test fixtures + sibling sessions farm orphans into a real workspace journal

In the field repo, `dos.toml [paths] lane_journal = docs/_plans/lane-journal.jsonl`, and `JournalPath(workspace)` honors that override relative to `--workspace .` (= cwd). So **every** dos invocation with cwd in that repo writes the same journal — including the **dos pytest suite** (the `a1`/lane `alpha`/`tree ["alpha/**"]`/`reason "lane-lease:a1"` fixtures; 2 `pytest -q` runs were in flight) and ~12 concurrent `claude.exe /goal` dogfooding sessions auto-picking lanes (`pid:0`). 17 distinct `<host>:<pid>` holders + `a1` appeared as lease holders. Multi-writer orphan farm; Defect 1 makes each orphan immortal between reconciles.

## Proposed fixes (kernel)

1. **(Defect 1, do this first)** Apply the `ttl_minutes` + heartbeat-freshness expiry that `journal_delta` already encodes **inside** the live-set the admission hook reads — i.e. `LiveLeasesFromWAL` (and the Python `live_leases_for`) drop any folded lease whose `acquired_at + ttl_minutes` (or last `heartbeat_at + grace`) is in the past. This makes the admission gate **self-heal** instead of depending on an external SCAVENGE. Keep the existing fail-safe direction (read fault → no leases). Parity test + corpus update.
2. **(Defect 3)** Do not escalate a contention-only refusal (empty `reasonClass`) to DENY purely on `treeKnown`. Keep "cannot share live lane X" advisory (WARN-and-pass) regardless of tree-known; reserve hard DENY for typed `reasonClass` refusals (`SELF_MODIFY`, etc.). A phantom-lane false positive should never be able to revoke a tool.
3. **(Defect 4)** The dos pytest suite must construct its lease/journal fixtures against a **tmp workspace / tmp `lane_journal`**, never inherit a cwd-resolved real-workspace journal. Separately, reconsider whether read / non-mutating tools (`Read`, `Grep`, `Glob`) should enter admission at all (treating the tool *name* as the request "lane" means every call is an empty-tree admission request).

## Interim workaround (host-side, already shipped in the reference userland app)

A host-side `clear_phantom_lane_leases.py` — reads `dos lease-lane live`, probes each holder PID, and issues an **append-only** `dos lease-lane release` for **dead-holder / fixture** orphans only (never a live sibling's lane; never a WAL truncate). It cleared the `DTE`/pid-32220 and `replan`/pid-33968 phantoms during the audit and restored Read+Edit. This is a mitigation, not a fix — Defect 1 is the durable fix.

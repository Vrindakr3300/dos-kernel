# 139 — Phase 1: wire `run_id` onto the dispatch-path ACQUIRE

> **Status:** implementation spec. **WIRE-ONLY on the kernel** — no `src/dos/*`
> change; the kernel receiver already ships (`acquire_entry(run_id=)`,
> `replay`/`ADOPT` carry it, the `trajectory_audit` consumer reads it back, the
> `dos lease-lane acquire --run-id` / `heartbeat` verbs exist). All Phase-1 work is
> **host-side producer wiring** in `job` + one regression test here. This doc is the
> *buildable* companion to docs/118 (the attribution-join it makes fire) and the
> Phase-1 anchor of the strategy arc `dos-strategy/dispatch-os-self-healing-observability.md`.
> Cross-refs: docs/118 (the postmortem/attribution join), docs/137 (the trace
> spine + cross-surface join — the `run_id` source), docs/82/99 (liveness — the
> verdict that becomes attributable once the hold carries an id).
>
> **One line:** a *held* lane (unlike a *refused* one, which already carries
> `run_id`) cannot be traced back to the run that took it, so the WAL↔session join
> measures **0 join-ready ACQUIREs** and every liveness/recurring-wedge verdict has
> no spine id to attach to. This phase stamps `run_id` onto the dispatch-path
> ACQUIRE — flipping **0 → N attributed holds** — by threading the run's CID id
> through *all* the host's lane-acquire writers and minting+exporting it at the
> screenplay Step-0 that fills the carrier.
>
> **Origin:** the self-healing observability audit (2026-06-04). Its largest finding
> — the open detect→act→record loop — has its keystone here: the record cannot be
> joined until the held lane is attributable. This spec is the de-risked, red-teamed
> build plan for that keystone.
>
> **Provenance:** produced by a verified multi-agent spec workflow (3 mappers →
> design → 3-lens adversarial red-team → synthesis), then re-verified against the
> live tree by hand (the §6-P pin check passes: the job venv's `dos` 0.8.0 already
> carries `acquire_entry(run_id=)`).

---

## 1. The honest success metric (read before building)

Stamping `run_id` makes a held lane **attributable** — it does **not**, by itself,
move the live `triples` count above 0 on real fleet data. The join's 1:1 rule
(`join_sessions_to_leases`, `trajectory_audit.py:529-564`) requires a session window
that overlaps **exactly one** lane whose lease overlaps **exactly one** session;
`run_id` is read **after** that gate is satisfied (`:537`), purely to *name* an
already-confident triple. A live run against `job` today returns **0 triples
/ 22 ambiguous**, and **9 of those 22 are single-lane-but-contended** — they would
not become triples even with `run_id` perfectly stamped, because median session
windows are ~79 min (max ~880 min, peak 15 concurrent sessions) so every lease
instant falls inside many sessions' windows. Therefore:

- **The Phase-1 exit gate is the `dos` unit test + a producer-side live assertion**
  (newest dispatch ACQUIREs carry a non-null `RID-…` `run_id`; `benchmark_only` is
  `False`) — **not** `triples > 0`.
- A single live audit returning `triples == 0` on lane-dense sessions is **expected
  and is not a wiring failure.** Lifting the live count (lane-isolated windows / a
  non-time disambiguation key) is a **separate, larger problem, out of Phase-1 scope**
  — it belongs to a later phase of the observability arc.

## 2. The change set — every writer site

Two repos. **dos:** one test (Commit 1). **job:** six edits landing as one coherent
unit (Commit 2). Diff 1 is the choke-point producer surface; Diff 2 is the
root-cause stamp (the one place the registry lease, the WAL ACQUIRE, and the
replay-reconstructed live lease converge); Diffs 3/5/6 are the *non-choke-point
writers* the C1 lesson demands we enumerate exhaustively — there are **four** acquire
shell-outs, not one; Diff 4 fills the carrier. **Apply by anchor text, not line
number** — `fanout_state.py` + the SKILL.md files carry other lanes' in-flight hunks.

| # | Repo · File · Anchor | Change | Risk |
|---|---|---|---|
| **1** | job · `scripts/fanout_state.py` · the `p_dl.add_argument("--threshold-kb", …)` block (last arg before `parse_args`) | Add `--run-id` to the dispatch-lane subparser (`dest="run_id"`, default `""`), read only in the `acquire` branch. | LOW — additive flag |
| **2** | job · `scripts/fanout_state.py` · the lease dict in the `decision.outcome == "acquire"` branch | **Root-cause stamp.** Resolve `_run_id = args.run_id or $CID_RUN_ID or $DISPATCH_RUN_ID`; after building the lease dict, `if _run_id: lease["run_id"] = _run_id`. Stamps the dict itself (not an `acquire_entry` kwarg) so the id rides into the registry, the WAL ACQUIRE (`acquire_entry` picks it up via `lease.get("run_id")`), and the replayed live lease in one place. Empty guard ⇒ byte-identical replay. **Robust to a stale kernel pin by construction** (works on any kernel that nests the lease). | MED-LOW |
| **3** | job · `scripts/dispatch_loop_preflight.py` · `_acquire_lane` cmd list | **Non-choke writer #1 (loop's primary acquire).** (3a) add `import os` — **genuinely absent**, else `NameError` on first run. (3b) `_rid = os.environ.get("CID_RUN_ID","").strip(); if _rid: cmd += ["--run-id", _rid]`. Env-only — signature/caller untouched. | MED-LOW |
| **4** | job · `.claude/skills/dispatch-loop/SKILL.md` · Step-0, after `LOOP_TS` is minted | **Fills the carrier (red-team blocker).** Mint one run via `fanout_state.py mint-run --process dispatch-loop`, parse `.run_id` out of its JSON (there is **no `--print` flag**), `export CID_RUN_ID`. Single-mint discipline: `mint-run` delegates to `dos.run_id.mint_child_from_env` (inherits an outer id if a parent loop set one). Degrade-safe: mint fault ⇒ empty ⇒ loop runs as today. | LOW |
| **5** | job · `.claude/skills/dispatch-loop/SKILL.md` · the disjoint-repick re-acquire | **Non-choke writer #2.** Append `${CID_RUN_ID:+--run-id "$CID_RUN_ID"}` — a separate hand-emitted acquire that does **not** route through `_acquire_lane`. The re-picked lane is the *most* likely to be singly-isolated (the best triple candidate), so attributing it matters most. | LOW |
| **6** | job · `.claude/skills/dispatch/SKILL.md` · the `LEASE_INHERITED=0` acquire branch | **Non-choke writer #3 (bare `/dispatch` transient lease).** Mint+export `CID_RUN_ID` (guarded by `if [ -z "${CID_RUN_ID:-}" ]` so a `/dispatch` inside a loop inherits, never re-mints) + append `${CID_RUN_ID:+--run-id "$CID_RUN_ID"}`. Leave the `LEASE_INHERITED=1` branches alone (they correctly skip acquire). | LOW |
| **7** | dos · `tests/test_trajectory_audit.py` | The acceptance test (§4). Test-only, no `src/dos/*`. | LOW |

> **Standing invariant (C1 lesson):** *every* literal `dispatch-lane acquire` under
> `.claude/skills/` that is not an inherited-lease branch is a writer that must carry
> `${CID_RUN_ID:+--run-id "$CID_RUN_ID"}`. Diffs 3/5/6 cover the three live ones.
> Before landing, `Grep "dispatch-lane acquire"` across `.claude/skills/` and confirm
> no fourth non-inherited writer slipped in.

Full before/after snippets for each diff live in the build-handoff (the workflow
output); the table is the authoritative site list.

## 3. HEARTBEAT / SCAVENGE — already wired (the audit line was stale)

Phase 1 touches **neither**, and the feared kernel gap is **refuted**:

- **HEARTBEAT emission already lands on the job dispatch path** (`fanout_state.py`
  `_heartbeat` → `_journal_lease_event("heartbeat", …)`; landed job `e3e807fa`), and
  the kernel verb the audit thought missing exists as `dos lease-lane heartbeat`
  (not `--beat`). So `journal_delta`'s heartbeat rung (`_HEARTBEAT_OPS =
  {ACQUIRE, HEARTBEAT}`) is already reachable on real job data.
- **SCAVENGE emission already lands** (dead-for-reclaim + reconcile-orphan sites);
  replay folds SCAVENGE like RELEASE.
- A beat/scavenge **carries no `run_id` by kernel design and needs none** — it
  refreshes the already-reconstructed live lease, which **inherited `run_id` from its
  ACQUIRE**. So the whole-audit payoff — `liveness=SPINNING` / recurring-wedge
  becoming *attributable* — falls out of the ACQUIRE stamp alone. **Do not pad
  Phase 1 with re-emission work that already shipped.**

## 4. The acceptance test (Commit 1, dos, ship first)

`tests/test_trajectory_audit.py`, inserted after `test_join_one_to_one_emits_triple`.
The existing triple test starts from a **pre-folded** `_lease()` dict — it bypasses
`_lease_run_id` and `fold_journal`. This one folds a **raw ACQUIRE** carrying
`loop_ts` + a nested `lease.run_id` through `fold_journal` (exercising the
`_lease_run_id` extraction + the `ts`→`ts_ms` parse), then joins to exactly one
`(session, run_id, lane)` triple — and is built to defeat the two red-team-confirmed
traps: the **window-floor pass-on-empty** (asserts a too-high `since_ms` empties the
fold, so a silent empty can never masquerade as a pass) and the **benchmark-pollution
poison** (asserts `benchmark_only is False`), plus a length guard against `[0]`
fragility.

```python
def test_raw_acquire_with_run_id_folds_and_joins_to_one_triple():
    """End-to-end: a RAW ACQUIRE carrying loop_ts AND a nested lease.run_id folds
    through fold_journal (exercising _lease_run_id) and joins to exactly one
    (session, run_id, lane) triple — the docs/118 acceptance shape measured at 0."""
    raw = {
        "op": "ACQUIRE", "lane": "apply",
        "loop_ts": "20260601T150045Z",
        "ts": "2026-06-01T15:00:45Z",
        "lease": {"run_id": "RID-1KT1TC5V0JDH0G5", "lane": "apply",
                  "loop_ts": "20260601T150045Z", "tree": ["agents/apply_*.py"]},
    }
    folded = ta.fold_journal([raw], since_ms=None)
    assert folded["benchmark_only"] is False          # poison guard
    assert len(folded["leases"]) == 1                  # [0]-fragility guard
    assert folded["leases"][0]["run_id"] == "RID-1KT1TC5V0JDH0G5"
    lts = folded["leases"][0]["ts_ms"]
    sess = [_session("sessA", lts - 1000, lts + 1000)]
    j = ta.join_sessions_to_leases(sess, folded, slack_ms=1000)
    assert len(j["triples"]) == 1
    assert j["triples"][0]["run_id"] == "RID-1KT1TC5V0JDH0G5"
    assert j["triples"][0]["lane"] == "apply"
    floored = ta.fold_journal([raw], since_ms=lts + 1)  # window-floor trap
    assert floored["leases"] == []
```

**Live producer-side acceptance** (NOT `triples > 0`, per §1) — compute the in-window
count from `len(folded['leases'])`, **not** `total_entries` (which is raw/pre-floor):

```powershell
cd job
$env:CID_RUN_ID = (.venv/Scripts/python.exe scripts/fanout_state.py mint-run --process dispatch-loop | ConvertFrom-Json).run_id
.venv/Scripts/python.exe scripts/fanout_state.py dispatch-lane acquire --loop-ts (Get-Date -Format yyyyMMddTHHmmssZ) --pid 0 --run-id $env:CID_RUN_ID --scope apply
cd dos
python scripts/trajectory_audit.py --workspace job --last 5 --format json
#   PASS (producer-side): benchmark_only False AND >=1 ACQUIRE lease with a non-null RID- run_id.
#   triples >= 1 is NOT required (lane-dense sessions stay AMBIGUOUS — §1).
```

## 5. Adversarial checklist (every blocker/high, resolved in-spec)

| Hole | Sev | Resolution |
|---|---|---|
| `run_id` source is never set — the carrier is dry, join stays 0 even after producer diffs | **blocker** | Diffs 4 + 6 mint + `export CID_RUN_ID` at the screenplay Step-0s. Promoted from "open question" to **required**. |
| Success metric wrong — `run_id` does not make the live join fire (1:1 contention) | **blocker** | §1 reframes the exit gate to the unit test + producer-side assertion, not `triples > 0`. A live `0` on dense sessions is documented as expected. |
| Missed writer: bare `/dispatch` transient lease | **high** | Diff 6. |
| Missed writer: dispatch-loop disjoint-repick re-acquire | **high** | Diff 5. |
| `import os` absent in `dispatch_loop_preflight.py` → `NameError` | **high** | Diff 3a makes it an unconditional hunk. |
| Window-floor pass-on-empty (`fold_journal` exposes only pre-floor `total_entries`) | **med** | Test asserts `floored["leases"] == []`; live harness uses `len(folded['leases'])`. |
| Stale dos-kernel pin could lack the `lease.get("run_id")` fallback | **low** | Lease-dict stamp is robust by construction; **§6 pin check passed (job venv dos 0.8.0 has the param)** — no bump needed. |
| arbiter gating on `run_id` / forgery / replay byte-identity / compaction invariant / CRLF-fsync | **CLEAR** | All positive: `arbiter.py` has zero `run_id` refs (record-don't-decide, docs/76); `run_id` is an attribution key, never a trust rung; empty-guard ⇒ byte-identical replay; `replay(compact(E)) == replay(E)` holds for the nested field; `lane_journal.append` writes UTF-8 via `os.write` on an `O_APPEND` fd + `os.fsync`, and `run_id` is a newline-free `RID-` token ⇒ JSONL one-line invariant safe. |

## 6. Sequencing + commit plan (local-only, no push)

Two independently-shippable commits; **no mono-fold** (job pins `dos-kernel`), no
cross-repo derived-artifact regeneration (`plans.yaml`).

- **Commit 1 — dos (test-only, ship FIRST).** The §4 test (+ optional ADOPT/compaction
  asserts). Touches no `src/dos/*`, lands on the `tests` lane, **no version bump**.
  `python -m pytest -q` green.
- **Commit 2 — job (ship AFTER, as ONE unit).** All six job edits — a flag with no
  caller, or a caller with no minted env, attributes nothing, so they are useless
  apart. **Pre-land gate:** the §6-P pin check (passed). **Scoped staging:**
  `fanout_state.py` routinely carries other lanes' interleaved hunks — stage only
  these, confirm zero foreign symbols, leave siblings dirty; do **not** sweep
  `plans.yaml`. Watch job tests asserting the exact 10-key lease shape (the new
  `run_id` key only appears when an id resolves).

**Kernel receiver already ships in the pinned dos**, so the job wiring functions the
instant it lands — the only reason the dos commit ships first is to have the
regression guard present when the producer fix arrives. Do not push.

## 7. What this unblocks

Before this, a held lane could not be traced to the run that took it — the WAL↔session
join measured **0 join-ready ACQUIREs**, so liveness (`SPINNING`/`STALLED`) and
recurring-wedge had no spine id to attach to and the observability scorecard could not
be computed. Stamping `run_id` makes every hold **attributable**; the beat/scavenge
machinery (already wired, §3) structurally inherits the id from the reconstructed live
lease. The flip is **0 → N attributed ACQUIREs** — the *necessary* substrate for the
scorecard — with the honest caveat (§1) that turning attributed holds into *confident*
`(session, run_id, lane)` triples on real fleet data is a separate, larger problem
later phases of the arc own.

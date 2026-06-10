# 207 — friction log (Phase 8c deliverable)

> The Phase-7 discipline ("record any genericization insight that has no home yet
> rather than coding ahead of proof") applied to the operator tier. Each entry is
> a place a `job` skill behavior could NOT be made generic, or a seam this plan
> opened/closed. Extends the SKP [74-friction-log](74-friction-log.md) — the F1/F2/
> F6 status below is the update docs/207 §8c asks for.

## What this plan genericized (and how)

| `job` house-specific | This plan's home | Status |
|---|---|---|
| `plan_phases.py` series-anchored deriver | `enumerate.py` + `[enumerate]` grammar | **relocated byte-for-byte** (17/17 plan parity) |
| `pick_cooldown.py` 6h window + outcome-awareness | `cooldown.py` + `[cooldown]` + `OP_ATTEMPT` | **relocated** (the storm-breaker backtest) |
| `plan_pickability.py` gate | `pickable.py` (shipped `8357ac0`) + `dos pickable` | **shipped; CLI added** |
| `class_cycle.py` 5-class / 9-trigger taxonomy | `[lifecycle]` data + `dos-class-cycle` skill | **taxonomy → data; cycle → skill** |
| `unstick_audit.py` cause clustering | `recurring_wedge.py` (shipped) + `dos-unstick` | **shipped; skill added** |
| the FQ-336 quiet-DRAIN keep | `reconcile.py` + `dos reconcile` | **new gate** (toolathlon precision 1.0) |

---

## P1 — the judge *content* stays a host driver (deliberate, SKP §"not genericized")

`class_cycle.py`'s `_JUDGE_PROMPT_TEMPLATE` is the LLM-judge prompt that rules on
a class transition. It is NOT genericized — it goes to a host `dos.judges` driver
(the same kernel/driver split as `llm_judge`). The `dos-class-cycle` skill spawns
the judge via the `dos.judges` seam (resolve-by-name, fail-to-abstain), reads its
verdict, and enacts only auto-approved transitions. **Why correct:** the prompt is
domain content (what makes a plan "done" / "stale" in *this* host); forcing it
generic would re-couple the kernel to a house's classification semantics. The
*cycle mechanism* (evaluate → judge → gated-enact → log) is domain-free and ships;
the *content* is a driver. **Open work:** no host `dos.judges` lifecycle-judge
driver ships in DOS yet — a reference one (mirroring `llm_judge`) is a follow-up.

## P2 — host evidence streams have no generic ingestion (still SKP F2)

`unstick_audit.py` (and `replan`) read a curated postmortem stream, a hand-ranked
next-hits file, and an INDEX of past runs. The generic `dos-unstick` ranks by the
**domain-free signal only** — the run-archive BLOCKED/DRAIN verdicts + the
`recurring_wedge` fold — and `log`s when it is not consulting a host evidence
source. **Status: still F2 (open seam).** docs/207 adds a second consumer
(`dos-unstick`) that wants the same `dos.evidence_sources` driver hook SKP named
for `dos-replan`; the hook is still unbuilt. The skill surfaces the gap at runtime
(no silent skip), so the floor is honest — but a host with a rich postmortem
stream cannot feed it generically yet.

## P3 — the heavy soft-claim leasing core stays host-side (still SKP F3)

`fanout_state.py`'s per-pick soft-claim core, `next_up_focus.py`'s value-greedy
scheduler, the rate-limit resume machinery — parked by the layer contract. The
**cooldown primitive (Phase 3) is the anti-churn SLICE that is genuinely
kernel-shaped** (a pure fold over a durable WAL event), and it shipped; the full
soft-claim core is not kernel-shaped and stays host-side. **Status: still F3
(deliberate scope-out).** docs/207 narrowed F3 — the anti-churn memory the loop
lacked is now in the kernel — without porting the heavy tier. A full port is a
separate plan if demand pulls it.

## P4 — `dos decisions add` is still read-only (SKP F6 — partially relevant)

The three operator skills all SURFACE findings via `dos decisions` (a held unit, a
recurring cause, a deferred transition). But `dos decisions` is still READ-ONLY —
there is no generic verb that WRITES a decision row (SKP F6). The skills route by
producing a finding the host's queue consumes; the write stays host-side. **Status:
SKP F6 still open** — docs/207 added three more *readers* of the decisions queue,
which sharpens the case for the `dos decisions add` over `home.append_decision`
that F6 named, but did not build it (it is the host's PEP-adjacent write, kept out
of the kernel's PDP role).

## P5 — the `enumerate.py` module-name shadow (resolved by convention)

Naming a module `enumerate.py` risks shadowing the builtin `enumerate()` used at
20+ kernel call sites. **Resolved (seam-ledger §4.1):** the module is named
`enumerate.py` (so the verb reads `dos enumerate`), but its public function is
`enumerate_units` — never `enumerate` — and consumers import it as `from dos import
enumerate as _enumerate` / `import dos.enumerate`, never the bare `from dos import
enumerate`. Pinned by `test_enumerate.py::test_no_bare_from_dos_import_enumerate_under_src`.
**Status: resolved by a pinned convention**, not a rename (the verb name was worth
keeping).

## P6 — the cooldown ⟷ lane_journal schema-constant inline (resolved by a pin)

`cooldown.py` reads `OP_ATTEMPT` records under the lane-journal schema family/
version. Importing those constants from `lane_journal` would close a
`config → cooldown → lane_journal → config` import cycle (`config` carries the
`[cooldown]` seam; `lane_journal` imports `config`). **Resolved:** `cooldown.py`
INLINES the family/version, and `test_cooldown.py::test_schema_constants_match_lane_journal`
pins them equal to `lane_journal`'s source of truth, so they can never silently
drift. **Status: resolved by an inline + a pin** — the standard kernel-leaf
cycle-break.

---

## Plan-prose corrections this build made (the false premises, recorded)

Two premises the plan rested on were wrong; the build adapted (full detail in
[207-seam-ledger §4](207-seam-ledger.md)):

- **Phase 2c "remove a host callback" was a non-task.** `completion.classify` reads
  `declared` from the intent-ledger `LedgerState`, never a callback. Re-scoped:
  `enumerate` is the *doc-side* producer of the `declared` extent
  (`declared_extent` / `residual_from_enumeration`), an alternative source for a
  doc-declared workspace — not a callback removal.
- **The toolathlon corpus is ~7,116 trajectories, not the cited "751."** The Phase-4
  scoring gate reads the available `_data/*.jsonl` and cites the real count; no
  held-out 751 subset exists.

---

## Status roll-up

| Item | This plan | State |
|---|---|---|
| P1 judge content | host `dos.judges` driver | **deliberate** — reference lifecycle-judge driver is a follow-up |
| P2 / SKP F2 host evidence | `dos.evidence_sources` hook | **open seam** — now wanted by `dos-unstick` too |
| P3 / SKP F3 soft-claim core | cooldown SLICE shipped; full core parked | **deliberate scope-out** — narrowed, not closed |
| P4 / SKP F6 decisions write | `dos decisions add` | **open seam** — 3 more readers added, write still host-side |
| P5 enumerate name shadow | `enumerate_units` + import convention | **resolved (pinned)** |
| P6 cooldown↔journal schema | inline + equality pin | **resolved (pinned)** |

The genuinely-open seams (P2/F2, P4/F6, and the P1 reference judge driver) are the
named targets the next iteration inherits; P3/F3 stays parked by the layer
contract; P5/P6 are resolved by pinned conventions.

# docs/287 — F3: the second witness. The coordination A/B ported to Agent-Diff; two independent witnesses agree

> **One sentence.** The fleet program's coordination payoff was measured only on tau2
> (objection O3: "one benchmark, one domain") — this run ports the believe-vs-adjudicate
> coordination A/B to **Agent-Diff** with its **production `AssertionEngine`** as the
> witness and finds the same result off the second witness: **J = 3 of 4 naturally-
> contending pairs** are lost updates the naive compose silently reverts and the
> arbiter-serialized compose lands, with the kernel refusing every second concurrent
> same-row lease and admitting every disjoint control.

**Status: shipped (frozen layer).** **Date: 2026-06-10.** **Reads on:** docs/245 (the
fleet-scale plan; this is STEP 5 / F3), docs/255 (F2 — the tau2 natural-collision result
this must agree with), docs/233 (the original coordination payoff), docs/237 (the
Agent-Diff *write-admission* port — the single-agent half; this doc is the coordination
half), `benchmark/agentdiff/coord.py` (+ `test_coord.py`).

---

## 1. The objection this kills

docs/245 named four skeptic objections; three are dead (F1 docs/251/253, F2 docs/255,
F4 docs/256). The last one standing was **O3**:

> "Both live results sit on tau2 — one benchmark, one domain (airline/retail). Your
> 'environment-agnostic witness discipline' is a claim, not a measurement."

The discipline's whole pitch is that the kernel needs only *a state verdict the agent
cannot author* — any tamper-evident witness should do. If that is true, porting the
coordination A/B to a second environment with a *different* witness should cost one env
adapter and produce the same verdict shape. If it is false — if the tau2 result secretly
leaned on something tau2-specific — the port exposes it. Either way the port is the
cheapest decisive datum left in the plan.

## 2. What was ported, and what was NOT re-fit

Agent-Diff (docs/237 introduced it) is a write-heavy agent benchmark over four wrapped
services (Slack, Linear, Box, calendar). Its witness is **richer and entirely its own**:
each task carries a gold assertion spec authored by the task author, and the production
`AssertionEngine` judges the observed state diff against it — `{passed, failures, score}`
instead of tau2's single DB-hash. The agent authors zero bytes of spec, diff, or verdict.

| layer | tau2 (docs/255) | Agent-Diff (this doc) | changed? |
|---|---|---|---|
| kernel call | `dos.arbiter.arbitrate(request, live_leases)` | the same call, byte-identical | **no** |
| region grammar | `reservations/<id>` | `<service>/<entity>/<row>` | string only |
| witness | env DB-hash equality | production `AssertionEngine.evaluate(diff)` | **independent witness** |
| contention source | gold actions naming a reservation | gold specs pinning a changed row | env adapter |
| compose model | replay tool-calls on a shared env | full-object write-back (PUT) on the shared row | env adapter |

The port is `benchmark/agentdiff/coord.py` — ~300 lines, of which the kernel-facing part
(`row_region` + `arbiter_admits`) is the same two functions `coord_loop.py` has, with a
different region string. That is the measurement: *nothing in the kernel was re-fit.*

## 3. The natural contention stream ($0 — the F2-STEP-1 question, second benchmark)

Before composing anything: do independent Agent-Diff tasks, as authored, naturally target
the same entity row? The contention key is env-authored (a gold `changed` assertion whose
`where` fully pins a row — every predicate a bare scalar or `eq`); tasks within a service
share one seed workspace (`info.seed_template`), so two tasks pinning one row genuinely
contend when run concurrently against a shared backend.

```
  write tasks                      45
  tasks pinning a changed row      21
  task pairs / naturally colliding 210 / 4     natural pairwise rate 1.90%
  natural contention sites         2           VERDICT: GO
    linear/issues   ENG-1          linear_6 (priority->Urgent) + linear_26 (unassign)
    slack/channels  C05ALPHA       slack_109 (archive) + slack_112 (archive) + slack_114 (rename)
```

tau2's natural rate was 2.35% (docs/255). A second, unrelated task distribution lands in
the same band — natural contention is a property of *write-heavy multi-task workloads*,
not of one benchmark's authoring quirks. (The rate here is a floor: predicate-region
wheres that may overlap a pinned row are conservatively excluded.)

## 4. The compose, and the verdict off the second witness

The lost-update mechanism on these services is **full-object write-back** (the PUT
semantics Slack/Linear/Box-style APIs actually have): agent B, having read the row before
agent A's write landed, writes the whole row back and silently reverts A's field.

- **NAIVE** (no coordination): B's write-back is computed against the ORIGINAL row.
- **SERIAL** (what the arbiter forces): B re-derives against the post-A row.
- The net before→after diff of each arm goes to the **production engine**, judged against
  each task's own gold assertion on the shared row (selected verbatim, never edited).

```
  linear_26 + linear_6   on issues ENG-1       naive: A REFUTED  | serial: both PASS   J=1
  slack_109 + slack_112  on channels C05ALPHA  naive: both PASS  (both archive)        J=0  benign
  slack_109 + slack_114  on channels C05ALPHA  naive: A REFUTED  | serial: both PASS   J=1
  slack_112 + slack_114  on channels C05ALPHA  naive: A REFUTED  | serial: both PASS   J=1

  J = 3 / 4    arbiter serialized every contended pair: YES
               admitted every disjoint control:         YES
```

Three things to read off this:

1. **The engine names the lost update itself.** The refutation is the witness's own
   failure text — `"priority did not change (before=3.0, after=3.0)"` — not this
   harness's interpretation. The forensic bytes are the env's.
2. **The benign pair is the honest tail, classified by the witness, not by us.**
   slack_109 and slack_112 both archive C05ALPHA — convergent same-value writes lose
   nothing, and the naive compose *passes both specs*, so the pair scores J=0. The
   classifier (`classify_pair`) is a pure function of the engine's four verdicts; a
   harness that wanted a bigger J could not get one without the witness agreeing.
   (docs/255 had the same shape: its two J=0 pairs.)
3. **The floor held.** Every second concurrent same-row lease was refused (serialized);
   every disjoint-row control was admitted. Coordination did not tax disjoint work — the
   refuse-MORE-only direction, byte-same kernel call as tau2.

### 4.1 The train split: the classifier refuses to inflate J

The train split (179 write tasks) replicates the contention finding at scale — 95 tasks
pin a changed row, **30 naturally-colliding pairs across 12 sites** (0.67% pairwise; all
four services now represented) — and it stress-tests the classifier's honest direction:

```
  pairs: 30   lost-update-prevented (J): 2   benign: 0   true-conflict: 28
  arbiter serialized every contended pair: YES   admitted every disjoint control: YES
```

Train's collisions are dominated by **same-field conflicts** (two tasks renaming or
moving the SAME Box file to *different* targets). For those, serialization orders the
writes but cannot make both gold specs land — the second write overwrites the first even
when re-derived — so the engine refuses the serial arm too and the pair classifies
TRUE_CONFLICT, J=0. The arbiter still serialized every one (in a live run the second
agent, re-deriving against the post-first state, would *see* the contested file changed
and could surface the conflict rather than silently clobber — but that is an
agent-behavior claim the frozen layer does not get to make, so it is not counted). J
counts only what serialization PROVABLY recovers — the witness, not the harness, draws
that line. Combined across both splits: **34 natural pairs → J=5 prevented, 1 benign,
28 true conflicts**, floor intact on all 34.

## 5. Two witnesses agree — the F3 deliverable

| | tau2 / F2 (docs/255) | Agent-Diff / F3 (this) |
|---|---|---|
| witness | env **DB-hash** (live) | production **AssertionEngine** (frozen) |
| natural pairwise rate | 2.35% (14/595) | 1.90% (4/210) |
| natural sites | 18 | 2 |
| payoff | **J = 4/6** (67%) | **J = 3/4** (75%) |
| honest J=0 tail | 2 pairs (non-destructive compose) | 1 pair (convergent writes) |
| arbiter floor | serialized contended, admitted disjoint | same, byte-same call |

Two unrelated benchmarks, two independently-authored witnesses, one unmodified kernel —
the same verdict shape: *most natural collisions are silent lost updates; serialization
recovers exactly those; the witness itself separates the benign tail.* O3 is dead at the
mechanism level. With F1 (docs/251/253), F2 (docs/255), and F4 (docs/256), all four
docs/245 objections now have a measured answer.

## 6. Honest scope — what "frozen" does and does not claim

- **The writes composed are the GOLD writes** (each task's env-authored intended effect),
  not live-agent-produced tool calls. This is deliberately the strongest *mechanism*
  form: it asks "when two CORRECT agents' intended effects collide, does the naive
  compose lose one and does the arbiter recover it?" — with the production witness
  adjudicating. What it does NOT measure: live-agent variance (an agent that fails its
  task never reaches the collision). docs/255 already paid for that live on tau2; the
  gated live arm here (two live agents + the Docker backend + `GEMINI_API_KEY`, the
  docs/237 SDK loop) would upgrade J to live form if a skeptic demands it.
- **The row states are synthesized** (gold `from` values where declared, type-consistent
  placeholders else); the engine's verdict depends only on did-the-field-change +
  the gold predicate, both of which the synthesis preserves. The spec bytes and verdict
  bytes are entirely the env's.
- **Order is fixed** (A first, B second), matching docs/255's single-direction
  convention; the lost update is order-symmetric for disjoint-field pairs.
- **The falsifier stands**: with one writer there is no pair, no compose, no J — the
  value goes to zero at fleet=1 (docs/204 §1), structurally.

Pinned by `benchmark/agentdiff/test_coord.py` (11 tests: the compose algebra, the
arbiter invariant, and the corpus numbers above, clone-gated).

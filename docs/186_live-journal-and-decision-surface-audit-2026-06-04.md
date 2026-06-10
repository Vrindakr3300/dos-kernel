# 186 — Live journal + decision-surface audit (2026-06-04)

**Date:** 2026-06-04
**Scope:** What does the kernel's *own* runtime state look like right now, run
live against this repo (`dos/`)? Three questions, answered with real
commands, not inspection: (1) is the dogfood lane-journal still the 34.7k-line
unbounded mess the [unbounded-growth audit](../MEMORY.md) recorded on 2026-06-03,
or did the fix land? (2) what does the `dos decisions` operator surface actually
emit on live state? (3) is the [`132`](132_what-the-operator-may-resolve-the-authority-floor-of-an-untrusted-driver.md)
claim — that an `--auto-clear ORACLE` is "90% present" — true against the shipped
CLI? **Method:** ~10 live probes (`dos decisions`, `dos doctor --json`, `dos
journal`, direct journal reads + op-distribution folds) on Windows 11 / PowerShell
against the editable install. Every number below is from this session.

Status: data-collection audit, the docs/127 genre. Builds nothing. It records
empirical state, corrects two stale memories, and surfaces one **new, reproducible
finding** (a refusal written under the wrong op is invisible to the operator
queue). The new finding is a *driver/fixture* defect, not a kernel defect — but it
shows a way the operator-visibility guarantee can be silently defeated from the
write side, which is load-bearing for [`132`](132_what-the-operator-may-resolve-the-authority-floor-of-an-untrusted-driver.md)
(the operator can only resolve what the queue surfaces).

---

## Verdict

The dogfood WAL is **healthy now** — the unbounded-growth pollution was fixed by
**relocation, not deletion** (test-isolation moved the noise into the benchmark's
own `.dos/`, exactly the fix the prior audit recommended). The `[retention]` seam
+ `dos journal compact` that the prior audit listed as "absent / to-ship" have
**both shipped**. But the relocated benchmark journals are themselves now
multi-MB and only-ACQUIRE, and — the headline — they record refusals under
`op:ACQUIRE` with a `REFUSED:` reason string instead of the kernel's `OP_REFUSE`
op, which makes **4,505 refusals invisible** to `dos decisions` in that workspace.

| Question | Finding | vs. memory |
|---|---|---|
| Dogfood WAL still 34.7k lines? | **No — 3 lines / 901 bytes**, a clean ACQUIRE→HEARTBEAT→RELEASE cycle | **STALE (fixed)** |
| Where did the 34.7k go? | **Relocated** to `benchmark/.dos/` (10,289 lines / 5.3MB) + `benchmark/fleet_horizon/.dos/` (2,071 / 1.05MB) | new detail |
| `[retention]` seam absent? | **No — shipped** (`config.py:46`, `dos.retention`); `dos journal compact` verb exists | **STALE (shipped)** |
| `dos decisions` on live state? | **(none pending)** — only ACQUIRE/HEARTBEAT/RELEASE on record, no refusals/halts | confirms `132` |
| `dos decisions --auto-clear`? | **Not present** — flags are `--all/--no-tui/--json/--output/--driver` only | confirms `132`'s honesty |
| **NEW:** benchmark refusals visible? | **No — 4,505 refusals logged as `op:ACQUIRE`, `dos decisions --all` shows "(none)"** | new finding |

---

## 1. The dogfood WAL is healthy — the pollution relocated, it didn't get deleted

The prior audit (`[[project-dos-unbounded-growth-audit]]`) recorded the live
dogfood journal at **34,722 lines / 17MB, 34,722 ACQUIRE vs 1 RELEASE** — test +
FleetHorizon fixtures writing into the REAL dogfood WAL. Live today:

```
$ wc -l .dos/lane-journal.jsonl        →  3
$ ls -la .dos/lane-journal.jsonl       →  901 bytes
  op distribution:  1 ACQUIRE · 1 HEARTBEAT · 1 RELEASE   (total 3)
```

The three rows are one balanced lease lifecycle (holder `audit-live-join-demo`,
`benchmark` lane, 2026-06-04T01:31:04→01:32:19Z) — a deliberate join-demo run, not
pollution. The file is **gitignored** (`git check-ignore` → ignored), so it is
genuine machine-local runtime state, not a committed fixture.

**Where the 34.7k went.** It did not vanish — it moved to where it belongs:

```
benchmark/.dos/lane-journal.jsonl                10,289 lines  5.27 MB
benchmark/fleet_horizon/.dos/lane-journal.jsonl   2,071 lines  1.05 MB
```

Both are FleetHorizon-benchmark output (holders `lane-00/01/02`, spans
2026-06-01→02). This is **exactly the prior audit's recommended fix working**:
"journal-path test isolation" — the benchmark now writes to its own workspace's
`.dos/`, so the noise is out of the dogfood WAL. The memory entry should be
updated: the root WAL is clean; the pollution is isolated to the benchmark
workspaces (where it is expected texture, though see §3 for a residual).

## 2. The retention seam shipped (prior audit "absent" is stale)

The prior audit said the docs/106 `[retention]` seam was "confirmed absent in
config.py" and listed shipping Steps 2–5 as the fix. Live:

```
$ grep -n retention src/dos/config.py
46:  from dos.retention import RetentionPolicy, GENERIC_RETENTION
552: ``retention`` is the **retention seam** (`docs/106 §3.3` ...)
554:   ... the WAL compaction threshold (``journal_max_entries`` ...)
559:   host declares its own in `dos.toml [retention]` (`dos.retention.load_from_toml`)

$ dos journal --help   →   {tail,replay,seq,compact}
    compact   fold the WAL to a single CHECKPOINT snapshot of the end
```

So the seam (`dos.retention.RetentionPolicy` + `should_compact` +
`load_from_toml`) **and** the `dos journal compact` operator verb both exist. The
benchmark journals at 5.3MB show retention is **available but not wired into the
FleetHorizon write path** — it is opt-in (`should_compact` is a pure threshold the
*caller* must check), and the benchmark harness never opted in. That is a
benchmark-config gap, not a missing kernel feature.

## 3. The new finding: a refusal under the wrong op is invisible to the operator

`dos decisions` is empty on this repo — correctly, because the only journal ops
are ACQUIRE/HEARTBEAT/RELEASE and the queue projects over `OP_REFUSE` / `OP_HALT`
(`decisions._from_lane_journal`, `decisions.py:255,273`). No refusals on record →
nothing pending. That confirms the projection is faithful.

But run the same surface against the **benchmark** workspace, which has thousands
of refusals on record, and the queue is **still empty** — and that is wrong:

```
$ python  (fold benchmark/.dos/lane-journal.jsonl)
  distinct ops:                              {'ACQUIRE': 10288}
  ACQUIRE rows whose reason starts "REFUSED": 4505

$ dos decisions --workspace ./benchmark --no-tui --all
  # operator decisions
    (none pending)
```

**4,505 refusals are on disk, and the operator surface reports none.** The cause
is a write-side category error: the FleetHorizon harness records a refused lease
as `op:ACQUIRE` with `reason:"REFUSED: lane 'lane-01' is already held ..."`, never
as the kernel's `OP_REFUSE` op. The queue reader keys on the op
(`if op == lane_journal.OP_REFUSE`), so a refusal mislabeled `ACQUIRE` is
**structurally invisible** to it.

This is the precise pain `decisions.py:8` was built to end — "the most common
dispatch outcome is the least observable" — reappearing not because the *reader*
is wrong but because the *writer* (a driver/test fixture, outside the kernel)
bypassed the `OP_REFUSE` op the [LJ write-side closure](../MEMORY.md) added for
exactly this reason. It ties directly to
[`132`](132_what-the-operator-may-resolve-the-authority-floor-of-an-untrusted-driver.md):
the operator can only resolve decisions the queue *surfaces*, and here the
write-side silently emptied the queue. The kernel's guarantee ("every refusal is a
journaled, surfaced decision") holds **only if every refusing writer uses
`OP_REFUSE`** — which is a discipline the kernel cannot enforce on an out-of-tree
driver today (it accepts whatever op the appender writes).

**Severity: LOW for the kernel, but a real visibility hole for any host that
hand-rolls its journal writes.** The benchmark is a fixture, so no operator is
actually blinded in production. But it is a reproducible demonstration that the
operator-visibility invariant is a *write-side contract*, not a kernel-enforced
one — worth knowing before a real host's dispatch loop writes refusals its own
way.

### The fix that landed: a reader-side defense (the option-2 move)

The §3 finding became a hardening the same session. Of the three fix candidates
this note named, the **reader-side defense** is the one that needs no cooperation
from the out-of-tree writer — so it shipped: `_from_lane_journal` now also reads
`OP_ACQUIRE` rows, and any whose `reason` (or nested `lease.reason`) begins with
`REFUSED` is lifted into a **degraded `ARBITER_REFUSE`** row. This is the docs/103
move applied to the op field itself — *distrust the self-labeled op, read the
reason* (the more honest signal). A new pure helper `_acquire_refusal_reason`
(`decisions.py`) gates it: a genuine grant returns `""` and is **not** surfaced, so
the queue stays the "what needs me" projection and does not fill with every granted
lease. The recovered row carries an evidence marker —
`"recovered: refusal logged under op=ACQUIRE (docs/139)"` — so an operator can tell
it apart from a first-class `OP_REFUSE`.

**Measured result (live, the whole point of the pass):**

```
$ dos decisions --workspace ./benchmark --json --all   (after the fix)
  distinct rows: 21  ·  sum(dup_count): 4505
```

The defense recovers **all 4,505** hidden refusals, and the *existing* `_dedup`
(`decisions.py`, collapse by `(kind, lane, reason_token, reason_text)`) folds them
into **21 distinct actionable decisions** — one per real `(lane, reason)` situation
— with `dup_count` preserving the full hidden total (626× on lane-02, 586× on
lane-05, …). So `4,505 invisible → 21 actionable, nothing lost`. The two
mechanisms compose exactly: recovery surfaces, dedup collapses. The clean dogfood
WAL stays empty (its one genuine ACQUIRE is correctly *not* a decision), verified
live. Pinned by `tests/test_decisions.py::TestAcquireRefusalRecovery` (9 tests:
the helper's admit/reject cases, top-level + nested reason, the genuine-acquire
negative, the dedup-to-distinct shape in miniature, and a coexists-with-real-
OP_REFUSE case). Full suite: **1806 passed, 1 skipped.**

This does **not** retire the write-side contract — a host should still emit
`OP_REFUSE` for a refusal (the recovered row is explicitly *degraded*, and only the
`REFUSED:`-prefixed convention is recognized). It is a safety net: a refusal can no
longer be *silently* invisible just because a writer used the wrong op. The
remaining two candidates (kernel appender normalizes an ACQUIRE-that-refused;
fix the FleetHorizon writer) stay open as the write-side half.

### One smaller datum: a single torn line, no encoding bug

The benchmark journal has **1 torn line in 10,289** (line 6174 lost its
`{"host_id"...` prefix — a classic interleaved-append tear:
`'26-06-01T15:41:37Z", "ttl_minutes": null}'`). The `�` that appeared in a naïve
read of the `REFUSED:` reasons is a **terminal display artifact, not stored
corruption** — re-read with `errors='replace'`, **0** rows contain `�` in the
stored reason (the em-dash in "is already held by a live loop — pick a different
…" round-trips fine). So: no systemic encoding bug; one genuinely-torn row from a
concurrent append, which the queue reader already degrades past
(`decisions.py` "every reader degrades to [] on a malformed source").

---

## Memory corrections (what to re-stamp)

1. **`project-dos-unbounded-growth-audit`** — the live dogfood WAL is **no longer
   34.7k lines**; it is 3 lines / 901 bytes, clean. The pollution **relocated** to
   `benchmark/.dos/` (5.3MB) + `benchmark/fleet_horizon/.dos/` (1.05MB) — the
   test-isolation fix landed. The `[retention]` seam + `dos journal compact` it
   listed as "absent / to-ship" have **both shipped**. Residual: the benchmark
   journals are themselves unbounded (retention available, not wired into that
   write path).

2. **No memory yet captures the new finding** — a refusal logged under
   `op:ACQUIRE` (vs `OP_REFUSE`) is invisible to `dos decisions`; the
   operator-visibility invariant is a write-side contract the kernel does not
   enforce on out-of-tree writers. Worth a short entry linked to
   `[[project-dos-operator-decisions-queue]]`,
   `[[project-dos-lj-write-side-closure]]`, and `132`.

---

## What this confirms about the design

- **The decisions queue is a faithful projection** — it shows exactly the refusals
  on record under the right op, and nothing it cannot see. Its emptiness on clean
  state is correct, not a bug. (Confirms `132` and the `decisions.py` projection
  thesis.)
- **`132` did not overclaim.** It said `--auto-clear ORACLE` is "not built, the
  natural extension"; the live CLI confirms it is absent. Honest.
- **The fix-by-relocation pattern is the right shape.** Test isolation that moves
  fixture noise into the fixture's own workspace (rather than scrubbing a shared
  WAL) is the durable fix — it keeps the dogfood WAL a true reflection of dogfood
  activity. The lesson for the benchmark: wire `retention.should_compact` into its
  write loop so its own `.dos/` doesn't grow unbounded either.

---

*Evidence note: every command was run live on Windows 11 / PowerShell against the
editable install this session (2026-06-04). The journal folds are deterministic
re-reads of on-disk files; the `dos decisions` outputs are verbatim. Related:
`docs/127` (the prior live audit genre), `docs/106` (the retention/GC seam now
shipped), `docs/132` (the operator-authority map this finding tests), `decisions.py`
(the projection reader), `dos.retention` (the shipped seam).*

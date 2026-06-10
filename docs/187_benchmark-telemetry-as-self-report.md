# docs/187 — Benchmark telemetry is self-report: the L3-token verification problem

> *"The big question is often: can we believe these numbers?"* — the operator,
> 2026-06-05, on the Benchmark cache verdict.

This is a design analysis, not yet a build plan. It answers one question — **how
does DOS verify a number like "L3 cache tokens = N" when the data scraped may
itself be wrong?** — by tracing the real provenance chain in `Benchmark/`
and mapping it onto the kernel's accountability ladder. It also catalogs the two
distinct insertion surfaces (runtime-verify and development) and ranks the work.

The throughline (the one sentence): **Benchmark's deepest problem is that the
system under test is the author of the evidence that grades it.** That is the DOS
problem (`the kernel is the part that doesn't believe the agents`) re-aimed from
agents onto telemetry. It is the same disease as the job-adoption hole
(`track_mutations.py:358`: agent says SUCCESS, applied no artifact) — here it is
*server says 92% hit-rate, no independent witness attests*.

## 0. The three reference points

- **A third-party RAG take-home** — the
  *first userland app done right*. Typed claims → independent witness → 
  `believe_under_floor` → typed verdict. The LLM judge is `AGENT_AUTHORED`
  (advisory); a non-forgeable witness (`THIRD_PARTY` SQL re-run / `OS_RECORDED`
  PDF span) is required to grant belief. **This is the gold-standard pattern to
  copy.**
- **EnterpriseOps-Gym live runs** (`dos/benchmark/enterpriseops/`) — DOS aimed at
  a *running agent*. Proven law: **detector-soundness ⊥ intervention-safety**;
  **WARN beats BLOCK** (live A/B: WARN +6.2pp integrity, BLOCK +0.0, because BLOCK
  broke ~6× more downstream steps). A correct verdict can be net-harmful if
  enforcement is too disruptive.
- **Benchmark** (`Benchmark/`) — DGX/NVMe cache benchmarking tool, ~12
  verdict producers, takes nearly every number on faith. DOS used: none.

## 1. The provenance ladder for an L3-token number (traced from code)

When Benchmark reports **"L3 cache tokens = N"**:

1. **Birth.** L3 is *defined* as `prefetch_delta = sglang:prefetched_tokens_total
   [now] − [prev]` — two scrapes of a Prometheus counter the **inference server
   reports about its own cache** (`engine/_classification_mixin.py:53`). **The
   thing being benchmarked is the sole author of the bytes that grade it.** A
   self-report in the exact DOS sense (generation #2 narrating generation #1).
2. **Transform.** Baseline subtraction with `max(0, …)` clamps — a **server
   restart mid-run silently zeroes the delta**; the reset is invisible in JSON
   (`monitoring/strategies.py:399-410`).
3. **Transform.** If `total_flow > our_cached`, L2/L3 get *proportionally scaled*
   (`engine/_classification_mixin.py:62-71`) — an accounting assumption, not a
   measurement.
4. **Cross-checks that EXIST** (`health/_integrity.py`, ~8 invariants: #22
   `total_cached ≈ l1+l2+l3`, #27 `load_back ≥ prefetch`, #31 prom-vs-computed
   hit-rate within 15pp). **But every one checks the server's numbers against the
   server's OTHER numbers.** They prove internal arithmetic consistency; they
   prove nothing about whether the server told the truth. *Consistency ≠
   grounding.*
5. **Non-forgeable witnesses that exist but are NOT wired in.** Mooncake/PrisKV
   expose *their own* `get_operations` counters — a **different byte-author** than
   the SGLang process. The harness **already scrapes them** into
   `mooncake_store_samples` (`engine/_scraper.py:257`) and then **never reconciles
   them against `prefetch_delta`.** The independent witness is collected and
   thrown away. Likewise NVMe SMART / iostat bytes-read (`hardware.py`,
   `nvme_profiler.py`) is collected and never used to bound cache claims.

### The accountability mapping

| Number | Byte-author | DOS rung | Forgeable by the benchmarked system? |
|---|---|---|---|
| `prefetched_tokens_total` (→ L3) | the SGLang server | `AGENT_AUTHORED` | **Yes** — it grades its own cache |
| Mooncake `get_operations` | the storage backend | `THIRD_PARTY` | No — different process |
| NVMe SMART / iostat bytes-read | the OS/kernel | `OS_RECORDED` | No — non-forgeable floor |
| harness-sent `prompt_tokens` | the harness | `THIRD_PARTY` (re-derivable) | No |

## 2. The answer: the third-party RAG witness pattern, re-aimed at telemetry

```python
# Benchmark-side driver (imports dos; never imported by dos — the one-way arrow)
from dos.evidence import EvidenceFacts, Accountability, believe_under_floor

facts = (
    # the claim under test — the SERVER's self-report, advisory only
    EvidenceFacts.attest("sglang_prefetch", Accountability.AGENT_AUTHORED,
                         subject="L3_tokens", detail=f"prefetch_delta={server_l3}"),
    # independent witnesses — DIFFERENT byte-authors
    mooncake_get_ops_witness(server_l3),      # THIRD_PARTY: attest iff within tol
    nvme_bytes_read_plausibility(server_l3),  # OS_RECORDED: refute if impossible
)
bv = believe_under_floor(facts)
# bv.believe is True ONLY if a non-forgeable witness attested.
# A bare server number → believe=False → verdict reported as UNWITNESSED, not fact.
# Witnesses disagree → believe & refuted both True → CONFLICT, surfaced not buried.
```

**The honest reframe.** DOS *cannot make a wrong scraped number right.* What it
does is stop a *self-reported* number from being laundered into a *verdict*
without a corroborating witness from a different author. `CACHE_SUFFICIENT` stops
meaning "the server said 92%" and starts meaning "the server said 92% **and**
Mooncake's own op-counter corroborates within tolerance **and** NVMe bytes-read is
physically consistent." Report the **rung that answered** (THIRD_PARTY-corroborated
vs. only AGENT_AUTHORED), never a bare boolean — the *measure-the-rung-not-the-
verdict* law.

**There is no perfect oracle here.** The strongest available witness for a cache
hit-rate is *another self-interested process* (the storage backend) plus *physical
bounds* (NVMe throughput can't exceed the link). That is an honest forgeable hole,
declared — exactly like the kernel's own honest holes. The floor is the OS; the
backend is corroboration; the server's self-report alone earns no belief.

## 3. The two insertion surfaces

### Surface 1 — VERIFY (can we believe the numbers?)

The numbers Benchmark takes on faith (from the claim map):

- `export/_verdict.py:55-226` — emits `CACHE_SUFFICIENT`/`CAPACITY_CLIFF`/… from
  `time_series[-1].token_hit_ratio_pct` with **no re-derivation, no operand
  bounds-check**. The #1 highest-frequency claim.
- `_exec_sweep.py:3439` — `pass_rate_pct = resolved / graded * 100`, no
  `resolved ≤ graded` bound, grader stdout parsed by regex.
- `sweep_eligibility.py:97` — eligibility from self-assigned status + a
  duration heuristic; no JSON-schema / non-empty-time-series check.
- `sweep.py:534` — combo `status` ("completed"/"oom_stopped"/…) is **self-
  reported by the orchestrator**, never cross-checked against observed facts.

### Surface 2 — DEVELOPMENT (distrust the agent that builds Benchmark)

- **Build-time `dos verify`** — Benchmark is agent-developed across multiple
  worktrees on `main`. Copy the third-party RAG take-home's `BUILD<n>:` ship-stamp pattern; let
  `dos verify` adjudicate "did it ship?" from git ancestry, exit-code-as-verdict.
  ⚠ Read the **rung** (`via grep-subject` is subject-gameable) not the bare verdict.
- **Arbiter lanes** — the claim map found **no inter-process locking**; two sweeps
  can corrupt `sweep_summary.json`, two graders can double-grade a combo.
  Benchmark's `CLAUDE.md` is entirely about this hazard. `dos.arbiter.arbitrate()`
  + the lane-journal WAL = collision-*prevention* (a lane is a leased region-lock)
  instead of corruption-after-the-fact.
- **Distrust the running benchmark agent** — the EnterpriseOps transfer, with the
  enforcement law baked in: default to **advisory WARN** (re-surface, let the turn
  proceed); reserve BLOCK/DEFER as high-stakes safety valves. Detector-soundness ⊥
  intervention-safety.

## 4. Priority order

| # | Insertion | Surface | Effort | Rationale |
|---|---|---|---|---|
| 1 | L3/cache-token witness reconciliation — fold prefetch (AGENT_AUTHORED) + Mooncake get_ops (THIRD_PARTY) + NVMe (OS_RECORDED) through `believe_under_floor`; verdict reports the rung | Verify | Medium (witness already scraped) | Answers the operator's exact question; the verdict is the product headline |
| 2 | Verdict-operand re-derivation gate in `export/_verdict.py` — re-derive `token_hit_ratio` from `time_series`, bounds-check `cached ≤ prompt`; refuse with a closed `dos.reasons` token | Verify | Low | #1 highest-frequency claim; pure arithmetic re-check |
| 3 | `dos verify` build gate + `BUILD<n>:`/phase ship-stamps in CI | Dev | Low (copy the RAG take-home) | Cheapest win |
| 4 | Arbiter lanes for sweep/grade regions via `dos.toml` | Dev | Medium | Closes the multi-worktree corruption hazard the CLAUDE.md is about |
| 5 | Eligibility + grader pass-rate witnesses (`resolved ≤ graded`; golden-cassette grader replay) | Verify | Medium | High-stakes self-reported numbers |

## 5. Shipped kernel API this rests on (dos-kernel 0.12.0, verified live)

`dos.evidence`: `believe_under_floor`, `EvidenceFacts.{attest,refute,no_signal}`,
`Accountability.{THIRD_PARTY,OS_RECORDED,AGENT_AUTHORED}`, `BeliefVerdict`
(`.believe`, `.refuted`). `dos.reasons` (closed refusal vocabulary via
`dos.toml`). `dos.verdict.conforms` (TypedVerdict contract). `dos.arbiter`
(lane arbitration). `dos.tool_stream.classify_stream` (env-result repeat
distrust — relevant if a scrape stalls/repeats). `dos.intervention` ladder
(OBSERVE‹WARN‹BLOCK‹DEFER, for the dev-agent surface). All confirmed importable.

## 6. The one-way arrow (litmus)

Every insertion lives **Benchmark-side** (it `import dos`); **nothing under
`src/dos/` imports Benchmark.** The witnesses (Mooncake reconciliation, NVMe
plausibility) are drivers/host policy — the kernel supplies only the floor
discipline (`believe_under_floor`), the rungs, the refusal vocabulary, and the
arbiter. Same kernel/driver split as the third-party RAG take-home's `witnesses.py` over
`dos.evidence`.

## 7. BUILT — `Benchmark/dos_verify/` (commits `ac52491`, `0c3b3ea`, 2026-06-05)

Insertion #1 is shipped: a Benchmark-side `dos_verify/` package that folds a
reported cache verdict through `believe_under_floor` and reports the rung
(GROUNDED / UNWITNESSED / CONFLICT). `python -m dos_verify <run.json>`,
exit-code-as-verdict (0/2/3), conforms to `dos.verdict.TypedVerdict`, closed
reasons in `dos.toml [reasons.*]` validated against the kernel registry, 11 tests
green, grounded on real `replay-data/*.json` + `outputexample/*.json` runs.

**The witness ladder now spans all three byte-authors** (`0c3b3ea` added the top
rung):

| Witness | Author | Rung | Power |
|---|---|---|---|
| server `prefetched_tokens_total` | the SGLang server | AGENT_AUTHORED | seen, never believed |
| hit-ratio re-derivation | (same — server's operands) | AGENT_AUTHORED | refutes export bugs |
| Mooncake store occupancy | the storage backend | THIRD_PARTY | grounds / refutes |
| disk + network read bytes | the OS kernel | OS_RECORDED | strongest floor |

The OS_RECORDED witness bounds a claimed L3 token volume by the disk+net bytes the
kernel actually recorded (`hardware_profiling.summary`): L3 reads physically cross
storage/network, so the server cannot have fetched more L3 token-bytes than the OS
saw move. On a real archived run, ~11.8 GB of OS-recorded reads back up to ~46M L3
tokens at 1024 B/token — a 1M-token claim GROUNDS, a 500B-token (~512 TB) claim is
CONFLICT-refuted **by the kernel itself**, on real bytes the inference server cannot
forge. Critically it stays SILENT when L3=0: lots of disk I/O does *not* prove cache
hits — the witness only bounds an over-claim, never manufactures a hit (the §5a
satisfaction-predicate line held).

**The headline empirical finding, on real archived bytes:** every cache verdict in
the archived runs lands **UNWITNESSED**. A confident `CACHE_SATURATED` /
`token_hit_ratio_pct: 0.0` sits on top of `sglang_prometheus_metrics:
{available: false, "No metrics snapshots collected"}`, `cache_saturation.latest:
{DGX2: null}`, `available_layers: {DGX2: []}`, `total_requests: 1`. **The verdict
rests on essentially no witnessable evidence** — "0% hit → SATURATED" is
structurally indistinguishable from "we measured almost nothing." DOS doesn't call
it wrong; it refuses to call it *believed*, and says exactly why.

### Lessons the build surfaced (these generalize past this one driver)

1. **Internal consistency is `AGENT_AUTHORED`, not `THIRD_PARTY` — pin it below the
   floor.** The tempting mistake is to treat "I re-derived the hit ratio from the
   operands and it matched" as independent grounding. It is not: the operands AND
   the reported ratio came from the *same author* (the server). Agreement proves the
   export math is self-consistent, never that the server told the truth. So the
   re-derivation witness must sit at `AGENT_AUTHORED` — it can REFUTE a
   self-contradiction (export bug) but can never GRANT belief. **This is the
   `health/_integrity.py` distinction made structural:** all ~8 of Benchmark's
   existing invariants are server-vs-server's-own-numbers, i.e. consistency checks
   that belong at the advisory rung. The general law: *re-arranging an author's own
   bytes never crosses that author's forgeability floor — only a different
   byte-author or a physical impossibility does.*

2. **Occupancy-vs-flow witness asymmetry — the strongest available witness is often
   a BOUND, not a match.** I went in expecting Mooncake's `get_operations` counter
   to per-step-match `prefetch_delta`. The real Mooncake endpoint
   (`network.py:377`) exposes *occupancy* (`used_bytes`, `key_count`), not a
   per-step op-flow. So the honest independent test is a **plausibility ceiling**
   (the store can't have served more L3 tokens than it could physically hold), not
   an equality. The general law: *when the independent witness measures a different
   quantity than the claim, the witness still works — as a one-sided BOUND (refute
   on impossibility, attest on fits-under-ceiling), with a deliberately LOOSE
   constant so you only ever kill a gross over-claim you can defend.* A loose bound
   that refutes 1-in-1000 impossible numbers beats a tight match you can't justify.

3. **UNWITNESSED is a first-class verdict, distinct from REFUTED — and it's the
   common case.** The binary "believe / refute" misses the modal real-world state:
   *nobody independent checked.* On a number nobody can corroborate, REFUTED is
   wrong (it isn't proven false) and BELIEVED is wrong (it isn't proven true).
   UNWITNESSED names the gap and is, empirically, where almost every real verdict
   lands. The general law: *a verification surface must report "no independent
   witness was reachable" as its own outcome; collapsing it into pass OR fail is the
   silent-truncation-reads-as-success error ([[feedback-workflow-schema-agent-mass-failure]])
   pointed at telemetry.* (`believe_under_floor`'s `silent` tuple is exactly the
   primitive for this — the no-signal sources are the UNWITNESSED evidence.)

4. **CONFLICT must beat corroboration — the safe direction is structural.** When a
   `THIRD_PARTY` attest and an `OS_RECORDED` refute both fire (`believe=True,
   refuted=True`), the audit returns CONFLICT, never GROUNDED. A real witness cannot
   launder a mathematical impossibility. This is `believe_under_floor`'s
   independent-axes design (`believe` ⟂ `refuted`) used as intended — the same
   conjunctive-only / refuse-MORE-only safety the arbiter and the predicate seam
   have. The general law: *attest and refute are not a sum; a single non-forgeable
   refute outranks any amount of attestation.*

5. **Probe-first paid off again (the [[feedback-probe-target-and-verify-reuse-before-building]]
   tax).** Three premises that "sounded right" were false until I read the bytes:
   `believe_under_floor` takes a flat tuple (not facts-per-claim); `time_series` is
   sometimes a dict not a list; Mooncake is occupancy not op-flow; `SubstrateConfig`
   has no `.load` (it's `load_workspace_config`). Each would have produced
   consistent-but-unbuildable code. The witness driver is honest *because* it was
   built against real archived run JSONs, not against the prose of how the pipeline
   "should" work.

6. **The witness ladder is monotone in author-independence; ground only at a rung
   whose author is independent of the claimant — but the BOUND's direction is set by
   what the witness measures.** The three independent witnesses form a strict trust
   order by *who authored the bytes*: server (AGENT_AUTHORED) ‹ storage backend
   (THIRD_PARTY) ‹ OS kernel (OS_RECORDED). You can only believe a number at a rung
   above the claimant's own. Orthogonally, each witness gives a *one-sided* bound
   fixed by its physical meaning: occupancy and I/O-volume are both CEILINGS (they
   cap how much could be true, so they refute over-claims and attest fits-under), and
   neither can ever be a *floor* that manufactures a positive — *lots of disk I/O
   does not prove cache hits.* The general law: *trust-rung (can this author ground
   anything?) and bound-direction (which way can this measurement cut?) are
   independent design axes — get both right, or a witness either can't ground or
   silently invents a satisfaction predicate.* The hardware witness staying SILENT at
   L3=0 is this law enforced: a strong author with nothing to bound says nothing.

### Where this is still honest about its limits

- The Mooncake/hardware ceilings use a deliberately tiny `min_kv_bytes_per_token`
  (1024) so they only refute gross over-claims; a tight bound needs the real
  `effective_kv_bytes_per_token` (`models/cache.py:208`) threaded in — a follow-up,
  not a guess.
- The archived runs all report L3=0 (and carry no Mooncake samples), so the
  GROUNDED/CONFLICT rungs are exercised by folding *synthetic* L3 claims against the
  *real* OS-recorded bytes from `hardware_profiling`. The proof boundary (the
  [[feedback-probe-target-and-verify-reuse-before-building]] "state the boundary"
  rule): **the UNWITNESSED finding and the OS-byte totals are real-data; the
  GROUNDED/CONFLICT paths are unit-proven on real bytes + synthetic claims,
  live-directional.** A live run with non-zero L3 + hardware sampling closes it.
- The OS_RECORDED floor (`0c3b3ea`) is now wired and is the strongest witness; the
  per-server attribution of box-wide I/O is left generous-on-purpose (whole-box I/O
  bounds a single server → only loosens the ceiling, never tightens unsafely).

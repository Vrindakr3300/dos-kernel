# 196 — DOS × KV-cache integration: the witness, the verified-prefix verdict, and the trust-aware route

> *Dated build plan — written 2026-06-06. The execution sibling of docs/178 (the
> backward soundness analysis) and docs/195 (the forward direction: adjudicate,
> don't manage). Where docs/195 ruled *what* to build, this doc is the
> file-level, phased, litmus-pinned plan to integrate DOS with the real KV-cache
> stack — Anthropic API, vLLM, SGLang, Mooncake, LMCache, NVIDIA Dynamo — after
> the operator said "yes, integrate with those things." Produced from a multi-agent
> workflow (`wf_0cd7b6b7-a02`): 3 surface-research agents (real cache APIs, cited)
> + 3 design lenses, each adversarially verified (18 verdicts; the
> NEEDS_QUALIFICATION ones are folded in below, not papered over) + a build-plan
> synthesis. Status: **DESIGN — nothing here is built yet.** Doc numbers 179–194
> were taken by concurrent work; this lands at 196 (its forward sibling is 195).*

## 0. The line that governs every phase

DOS is a **PDP, not a PEP**: it **witnesses** the engine's own cache bytes and
**emits** verdicts/hints the engine *may ignore*. It never calls
put/evict/transfer/pin. The litmus: *if the engine can ignore DOS's output, DOS is
adjudicating, not managing* — and a read-only witness emits nothing the engine
could even act on. This is docs/195's bright line, now an enforced build
constraint. **Value is 0 at N=1** (the engine's content-addressed prefix cache
already self-verifies a single agent's own prefix); the whole payoff is
**cross-agent fanout** (docs/170 horizon × fanout). Phases are ordered
smallest-trust-cost-first (docs/164 §5 / docs/126); each later phase is gated
behind the witness the earlier one establishes.

## 1. What the integration actually attaches to (the seams are already there)

The decisive finding: **DOS already has the exact extension points a cache
integration needs — no kernel change required.** A cache witness is just another
`EvidenceSource`; the floor that adjudicates its claim already ships.

| DOS seam | File:line | Role in the cache integration |
|---|---|---|
| `EvidenceSource` Protocol + `gather() -> EvidenceFacts` | `evidence.py:260-286` | the contract a cache witness implements |
| `believe_under_floor` | `evidence.py:412-485` | adjudicates the cache claim — belief ONLY on a non-forgeable (`OS_RECORDED`/`THIRD_PARTY`) source; an `AGENT_AUTHORED` "it's warm" is structurally filtered (`:446-450`) |
| `Accountability` enum | `log_source.py:84-114` | the rung tag carried as class-level DATA, never inferred from content |
| entry-point group `dos.evidence_sources` | `evidence.py:612` (+ `pyproject.toml`) | where the cache-witness driver registers — kernel stays unaware |
| driver templates `ci_status` / `os_acceptance` / `paste_log` | `drivers/*.py` | the THIRD_PARTY / OS_RECORDED witness pattern to mirror (boundary `gather` does I/O, pure `classify` returns the verdict, never raises) |
| `arbiter` + `rank_key` | `arbiter.py:146-215` | the pure state-in/decision-out *skeleton* a route verdict reuses (NOT the gate — see §4) |
| `digest_turn` / `transcript_digest` | `rewind.py:384` | the non-forgeable **prefix identity** a trust-aware key uses |
| `run_id` `parent_id`/`root_id` | `run_id.py:134-150` | the **lineage** that authorizes cross-agent reuse |
| `KNOWN_CATEGORIES` + `BASE_REASONS` | `reasons.py:67` | the closed-enum-as-data seam new cache refusals roll up to |

Everything engine-specific (zmq, prometheus parsing, an Anthropic usage object)
lives in `drivers/*` behind a `[cache-witness]` extra; the **kernel stays
PyYAML-only** (the litmus in §6).

## 2. The phases

### Phase 0 — collapse the char/4 cost proxy to one callsite (no new trust)

The restart cost ledger's `prefix_tokens_repaid` (`restart_arm.py:142-156`) is a
`char/4` proxy (`estimate_window_tokens`, `restart_arm.py:64`) — and the
adversarial pass corrected a stale assumption: it has **at least four+ consumers**
(`restart_arm.py`, `dos_react.py:705-731`, `restart_counterfactual.py`,
`abandon_counterfactual.py`; `score_ab.py`/`live_ab.py` read the field), not one.
Extract it behind a single seam first so Phase 2's witness upgrade is a single,
safe edit. Pure plumbing; `estimate_window_tokens` stays, tagged
`AGENT_AUTHORED`. **Litmus:** exactly one definition of the cost computation.
**Eval:** `test_restart_arm.py` stays green, model-free.

### Phase 1 — the cache-witness driver (the #1 best bet) — READS, never manages

`src/dos/drivers/cache_witness.py` — a dual `EvidenceSource` (load-bearing) + thin
`LogSource` (for `dos trace`), mirroring `ci_status`/`os_acceptance`. Three
boundary readers + one pure `classify`:

| Reader | Surface read (confirmed-real) | Rung |
|---|---|---|
| `witness_anthropic_usage(usage, subject)` | `usage.cache_read_input_tokens` (in-process, on the response the agent already received; no network) | **THIRD_PARTY, exact** |
| `gather_vllm_metrics(url, subject)` | `GET /metrics` → `gpu_prefix_cache_hit_rate`; LMCache `lmcache:num_hit_tokens`/`retrieve_hit_rate` (`LMCStatsMonitor`, SHIPPED) | **OS_RECORDED, aggregate** |
| `gather_kv_events(events, subject, expected_seq)` | ZMQ `BlockStored{block_hashes, parent_block_hash, seq}` / `BlockRemoved` (`ZmqEventPublisher`, 8-byte BE replay seq) | **THIRD_PARTY, drift-guarded** |

Pure `classify(facts, accountability) -> EvidenceFacts`, fail-safe order:
`reachable=False` → NO_SIGNAL; **`seq_gap=True` → NO_SIGNAL** (drift, abstain —
the gap-fold is a *precondition* for the published-event stream to attest, not an
afterthought); `cache_read>0 or hit_rate>0` → ATTESTED; `cache_read==0 and
input>0` → REFUTED (cold); else NO_SIGNAL.

**Accountability ruling, per surface (the adversarial pass sharpened these):**
- **Anthropic usage** — THIRD_PARTY, exact, per-request, deterministic. The
  strongest witness; in-process, needs no network.
- **vLLM/LMCache `/metrics`** — OS_RECORDED but **aggregate**: a hit *rate*, not a
  fact about *this* turn. Legibly weaker than the per-request count.
- **Published KV events (vLLM/Dynamo/Mooncake)** — THIRD_PARTY by authorship but
  **approximate over lossy pub/sub**; the 8-byte-BE-seq gap fold is what earns the
  attestation. Authorship nuance: in vLLM the engine's `BlockPool`/scheduler emits
  `BlockStored` (no "master"); only **Mooncake** has a distinct Master Service
  authoring the event.
- **LMCache caveat:** THIRD_PARTY *only if LMCache runs outside the agent's
  process*. It often runs inside the serving stack's trust boundary — if so it is
  the agent's own process and drops to **AGENT_AUTHORED** (the floor filters it).
  The driver must tag by deployment, never assume.

**Registration:** `pyproject.toml [project.entry-points."dos.evidence_sources"]`;
engine SDKs in a `[cache-witness]` extra. **Litmus:** the driver imports no
mutation symbol (§6 — with the honest caveat that the grep is *weak*; the real
floor is the import-arrow + the `EvidenceFacts` return type). **Eval:**
`tests/test_cache_witness.py` — frozen-fixture replay of every `classify` branch,
the seq-gap → NO_SIGNAL fixture, the fail-safe (unreachable → no_signal, never
raises, enforced by `gather_evidence` at `evidence.py:321`).

### Phase 2 — wire the witness into the rewind/restart cost ledger (attest the cost half)

`witnessed_prefix_tokens(...)` reads the last AI message's `usage_metadata` —
**already captured at `dos_react.py:888`** — runs it through
`witness_anthropic_usage` → `classify`; if ATTESTED returns
`(cache_read_tokens, "THIRD_PARTY")`, else falls back to the char/4 value tagged
`AGENT_AUTHORED`. The per-arm summary runs the totals through `believe_under_floor`
so the cost comparison is reported as **believed (engine-attested)** vs **asserted
(char/4 fallback)** — never silently mixed. This turns docs/178 §4's cost half
(today asserted) into attested fact *when a real engine ran*, with the offline
test green via the labeled fallback. **Eval:** a fixture asserting a present
`usage_metadata` flips the rung to THIRD_PARTY, a missing one stays AGENT_AUTHORED.

### Phase 3 — the verified-prefix admission verdict (pure kernel HINT, cross-agent only)

`src/dos/prefix_admission.py` (kernel leaf, sibling of `rewind`/`arbiter`) —
`prefix_admission(anchor, trust, residency, policy) -> PrefixVerdict` over
`PrefixAdmission ∈ {ADMIT_REUSE, REFUSE_POISONED, ABSTAIN}`. PURE fold over frozen
value objects (imports kernel siblings `oracle`/`rewind`/`evidence` only):

1. **Poison dominates (fail-closed):** `anchored=False` → REFUSE_POISONED
   (UNANCHORED); `rewind_fired=REWIND` → REFUSE_POISONED; `ship is not None and
   not ship.shipped` → REFUSE_POISONED (NOT_SHIPPED terminal).
2. **Admit only on witnessed + verified + anchored:** `belief.believe is True` AND
   anchored AND not-rewound AND (ship None or shipped) → ADMIT_REUSE with a
   `pin_priority`.
3. **Else ABSTAIN** — incl. `belief.refuted` (an *evicted* block is cache
   pressure, not trust poison; the engine's LRU decides).

Poison **reuses three existing detection verdicts** (NOT_SHIPPED / UNANCHORED /
DIVERGED) rather than inventing poison-detection — but it still needs new *wiring*
(an anchor→prefix mapping + an eviction-hint emitter). `pin_priority =
log1p(reuse_count) * matched_prefix_len_weight`, gated `reuse_count >=
policy.pin_floor_reuse` (default 2) — **the N=1 cut encoded in data** (below 2
distinct reusing `root_id`s, no pin pressure). Three new closed reasons via
`BASE_REASONS.extend` (must roll up to `KNOWN_CATEGORIES` or construction raises):
`UNVERIFIED_PREFIX`→`OPERATOR_GATE`, `POISONED_PREFIX`→`STALE_CLAIM`,
`STALE_RESIDENCY`→`MISROUTE`. Driver `drivers/prefix_cache.py` reads LMCache
`/lookup` `layout_info` into a `ResidencyWitness`. **Byte-clean — with the
caveat:** byte-clean because the trust-bearing *seal* on each input is
non-forgeable (kernel-authored anchor hash; engine-authored cache witness), so the
agent cannot manufacture a verified-reusable verdict — **but today the anchor
seals ONE turn, not the cumulative prefix** (docs/178 §5 q1). Phase 3 ships the
turn-granular verdict; whole-prefix byte-cleanliness needs a cumulative-prefix
digest (deferred, §5). **Surface:** `dos prefix-admit --json` + MCP tool,
read-only.

### Phase 4 — the trust-aware route verdict (the arbiter's skeleton, inverted gate)

`src/dos/cache_route.py` (kernel sibling of `arbiter`) —
`route(*, request, residency, ancestry, policy, rank_key=None) -> RouteDecision`
over `Route ∈ {REUSE, COLD_WALK}`. **NOT an arbiter gate-swap** (confirmed): the
arbiter's disjointness gate composes conjunctively and can only *refuse* — it
would veto every real cache hit (a reused prefix IS a colliding tree). `route`
reuses the *skeleton* (state-in/decision-out, lineage spine, optional `rank_key`)
with a distinct verdict and an inverted gate. Three conjunctive sub-gates, any
failure → COLD_WALK (fail-safe):

| Gate | Mechanism |
|---|---|
| (a) digest-matched | `rewind._digests_match(request.prefix_digest, entry.digest)` |
| (b) witnessed-cached | `believe_under_floor(entry.witnesses).believe is True` — never a bare `is_warm` bool |
| (c) lineage-authorized | `request.requester.root_id == entry.producer_root_id` (default `same_root`; cross-tree = opt-in, the PROMPTPEEK NDSS'25 hazard) |

`fold_residency(entries) -> ResidencyDirectory` — pure `lane_journal.replay()`-
shaped fold: `STORED~ACQUIRE`, `REMOVED/EVICTED~RELEASE/SCAVENGE`, `HIT~HEARTBEAT`
(a warmth beat that ages out). **The place() lineage, corrected:** `route()` is
*not* a "half" of docs/77's never-started `place()` verb — it is the arbiter's
pure-admission **skeleton re-aimed** with a `believe_under_floor` residency gate +
a residency-affinity `rank_key`; it *overlaps* docs/77's routing idea but is a
distinct, lighter design. **Honestly phase-2, value-thin** (docs/195 §5 ranking).
**Ship the pure verdict + fold + tests; leave the router shim un-wired** until a
real witness stream exists.

### Phase 5 — DEFER (named so it is not silently attempted): see §5.

## 3. The integration matrix

| Engine | Witness surface DOS reads | Rung | What DOS emits back | Consumer |
|---|---|---|---|---|
| **Anthropic API** | `usage.cache_read_input_tokens` (in-process) | **THIRD_PARTY, exact** | attested `prefix_tokens_repaid` + rung (Phase 2) | the restart cost ledger / A/B summary |
| **vLLM** | `/metrics gpu_prefix_cache_hit_rate`; ZMQ `BlockStored`/`BlockRemoved` (seq-replay) | OS_RECORDED (metrics); THIRD_PARTY drift-guarded (events) | `EvidenceFacts`; residency records | `believe_under_floor`; `cache_route.fold_residency` |
| **SGLang** | `gpu_prefix_cache_hit_rate`; router radix-event stream | OS_RECORDED | `RouteDecision(REUSE, node, len)` affinity hint | **`sgl-router`** (disposes on load) |
| **Mooncake** | `BlockUpdateEvent` (RFC #1408, residency); `/query_by_hash` (RFC #1403); `/metrics :9003` (aggregate) | THIRD_PARTY drift-guarded | residency records (a **producer**, not a consumer) | `cache_route.fold_residency`; **NOT** the Conductor (no external decision API) |
| **LMCache** | `/lookup layout_info{instance_id:(loc, matched_prefix_len)}`; `lmcache:num_hit_tokens`; ZMQ events | **THIRD_PARTY only if out-of-process**, else AGENT_AUTHORED | `ResidencyWitness` → `PrefixVerdict` (Phase 3) | `prefix_admission`; `cache_route` |
| **NVIDIA Dynamo** | KV-router worker-published `BlockStored`/`BlockRemoved` (approximate radix, lossy pub/sub) | THIRD_PARTY drift-guarded | `RouteDecision` as a trust-overlay term on locality-vs-load | **Dynamo KV-router** (disposes) |

## 4. Litmus tests (grep-checkable, CLAUDE.md-style — each a test)

- **The cache driver READS, never manages.** No `.put(`/`.store(`/`.evict(`/
  `free_blocks`/`transfer_submit_write`/`pin(`/`move_block` *call* under
  `drivers/cache_witness.py` / `prefix_cache.py`. **Honest caveat:** the blocklist
  is *weak* — only `free_blocks`/`evict`/`.put(`/`.store(` are confirmed-real
  engine mutation names; the others are unverified. **The real safety floor is the
  one-way import arrow + the `EvidenceFacts` return type**, not the blocklist.
- **The witness is THIRD_PARTY/OS_RECORDED or it abstains.** `accountability` is
  class-level DATA; `believe_under_floor` filters AGENT_AUTHORED (a test asserts an
  AGENT_AUTHORED fixture can never flip `believe=True`).
- **The kernel stays PyYAML-only.** `rg 'import zmq|prometheus|anthropic|vllm|
  lmcache' src/dos/ -g '!drivers/*'` → no matches. `prefix_admission.py`/
  `cache_route.py` import only stdlib + kernel siblings.
- **A verified-prefix/route verdict is a HINT — the engine may ignore it.** No
  kernel/driver call site invokes an engine pin/place API; the verdict exposes
  `to_dict()` + a numeric priority only.
- **The driver is imported by nothing under `src/dos/`** (the one-way arrow,
  AST-test-enforced for all drivers).
- **The verdict needs no live engine** (pure folds over frozen fixtures; the
  `rewind`/`liveness` test discipline).
- **The three reasons roll up to `KNOWN_CATEGORIES`** (construction-time check;
  lockstep emittable∧verifiable∧refusable test).

## 5. What stays out (the rejected line)

- **KV-block management / a block-granular scheduler.** Engine management; the
  stale-positive TOCTOU is *sharp* at block granularity (turn granularity bounds
  it). Out.
- **Mid-prefix splice / cumulative-prefix digest stitching.** Phase 3 seals one
  turn; whole-prefix byte-cleanliness needs the unbuilt cumulative-prefix digest
  (docs/178 §5 q1). Named as the gate to a future phase, out of shipped scope.
- **Any PEP-side mutation** (`put`/`evict`/`transfer`/`pin`/`move`/`free_blocks`;
  Mooncake `transfer_submit_write`/`EvictDiskReplica`, LMCache
  `storage_manager.put`, vLLM `free_blocks`). DOS emits a number; the engine's
  router is the PEP.
- **Mooncake Conductor as a consumer.** RFC #977 exposes no external decision API
  (dispatch pushes inward) — Mooncake is a witness *producer* only.
- **docs/77 `place()` as a hardware-assigner** (that mutates placement = PEP).
  `route()` is the PDP face only; docs/77 is an unstarted plan, not scaffolding.

## 6. Risk register (honest)

**Confirmed-real (ship with confidence):** Anthropic `usage.cache_read_input_tokens`
(exact, server-authored); LMCache `lmcache:num_hit_tokens`/`retrieve_hit_rate`
(SHIPPED `LMCStatsMonitor`); LMCache `/lookup layout_info`; ZMQ `BlockStored` with
8-byte-BE replay seq (vLLM/LMCache `ZmqEventPublisher`); and all DOS kernel seams
(verified in-tree, §1).

**Need-verification (gate the phase that touches them):** Mooncake
`BlockUpdateEvent`/`/query_by_hash` are **RFC-stage, transport unfinalized** —
Phase 4's Mooncake feed is contingent; the shipped Mooncake read today is only
`/metrics :9003` (fleet-aggregate). The exact `gpu_prefix_cache_hit_rate` series
name varies by version — the reader must degrade to no_signal on a missing series.
Mooncake Conductor confirmed to expose **no** consumer API.

**Cost: asserted vs witnessed.** Today `prefix_tokens_repaid` is asserted
(char/4 = AGENT_AUTHORED). Phase 2 makes it witnessed (Anthropic `cache_read`,
THIRD_PARTY) *only when a real engine ran*; the fallback stays tagged. Never mix
asserted and witnessed totals in one number. The `/metrics` rung is aggregate
(a rate, not this-turn) — believed but legibly weaker than the per-request count.

**N=1 → 0 (encoded, not just prose).** A single agent reusing its own warm prefix:
the engine's content-addressed cache already self-verifies it; `prefix_admission`/
`route` add pure overhead. `pin_floor_reuse=2` + `reuse_count` in `pin_priority`
encode the cut structurally. Value materializes only at cross-agent fanout — an
overlay on a router DOS does not own, not a frontier keystone.

**Residency-coherence TOCTOU (the one window the floor does NOT close).**
`believe_under_floor` attests warmth *was* present, not that it *persists*. Stale-
*negative* (under-report) → COLD_WALK, self-correcting (closed). Stale-*positive*
(directory says warm, silently evicted, no RELEASE) → the router re-prefills: **a
performance miss, not a correctness bug**. Mitigation is a residency TTL/freshness
bound (`max_residency_age_s`, the `journal_delta` heartbeat-age pattern), not the
floor alone. This is exactly why the block-granular version (window sharp) is
deferred and only the turn-granular version (window bounded; turns coarse, stream
sequenced+replayable) ships.

**Build sequence is fixed by dependency:** 0 → 1 (the witness — everything else is
worthless without a non-forgeable residency byte) → 2 (cost-ledger attest, the
immediate payoff) → 3 (the trust verdict, pure + fixture-testable today, shim
un-wired) → 4 (the route verdict, same) → 5 (deferred, named). Phases 1–4 touch
disjoint lanes (`drivers/`, kernel leaves, `benchmark/`) and each lands
independently.

## 7. Provenance / cross-refs

- docs/178 (the only sound deletion is tail-truncation); docs/195 (adjudicate,
  don't manage — the forward ruling this plan executes); docs/164/126 (phasing +
  PDP/PEP); docs/170 (the N=1→0 / horizon×fanout value test); docs/185 (the
  LogSource witness seam); docs/89/90/91 (arbiter + rank-never-re-admit + the
  value-aware picker `rank_key`); docs/77 (the never-started `place()` plan
  `route()` overlaps but does not implement).
- Kernel seams: `evidence.py:260,412,612`, `log_source.py:84`, `rewind.py:384`,
  `run_id.py:134`, `arbiter.py:146`, `reasons.py:67`, `dos_react.py:888`,
  `restart_arm.py:64`.
- Cache surfaces (cited in the workflow): Mooncake (Transfer Engine, Store,
  Conductor RFC #977, KV-Events RFC #1408, Indexer RFC #1403, `/metrics :9003`);
  LMCache (`LMCacheEngine.lookup`, Controller `/lookup`, `CacheEngineKey`,
  `LMCStatsMonitor`, `ZmqEventPublisher`); vLLM (`/metrics`, `KVConnectorBase`,
  `kv_events`); SGLang (RadixAttention, `sgl-router`); Dynamo (KVPublisher,
  approximate radix router).
- The workflow: `wf_0cd7b6b7-a02` (8 agents; one surface agent rate-limited, its
  cache-side Dynamo deep-dive flagged need-verification above).

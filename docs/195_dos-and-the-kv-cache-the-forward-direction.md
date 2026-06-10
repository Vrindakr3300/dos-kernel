# 195 — DOS and the KV cache, the forward direction: manage, route, or adjudicate?

> *Dated analysis — written 2026-06-06. The forward sibling of docs/178 (which
> settled the backward question: how DOS manages a bad prefix today = tail-
> truncation only, never touches the cache). This doc pushes the OPPOSITE way:
> what if DOS DID reach into the cache, what is the real blocker, where is the
> value, and is there a cache-ROUTING concept (Mooncake / LMCache / Dynamo-style
> disaggregation)? Produced from a multi-agent workflow
> (`wf_775501d7-684`, run + resume across two server-side rate-limits): 3 research
> agents (cache-routing systems · DOS routing primitives · value-and-blocker, the
> last grounding in 2024–2026 prior art) → 4 design lenses. The `real-blocker`
> lens carries 6 adversarial verdicts (5 CONFIRMED, 1 NEEDS_QUALIFICATION); the
> `value` and `routing` lenses are full but did NOT get their adversarial pass
> (rate-limited) — their stronger claims are flagged ⚠ unverified inline. docs/178
> §6 pointed this forward to "docs/179", but 179–194 were taken by concurrent
> work, so this lands at 195; the integration build plan is its sibling docs/196.
> Every status label is a dated observation.*

## 0. The one bright line

The word **"manage"** hides two operations DOS treats completely differently:

> **DOS can ADJUDICATE / ADVISE about the cache. DOS cannot MANAGE the cache.**
> *Adjudicate* = a pure verdict over the engine's *reported* cache facts, emitted
> as a HINT the engine may honor (PDP). *Manage* = DOS moving / evicting /
> transferring / re-rotating cache bytes inside the engine (PEP).

The litmus: **if the engine is free to ignore DOS's output, DOS is adjudicating;
if DOS's output mutates engine memory, DOS is managing.** This is the same PDP/PEP
line the kernel draws everywhere (CLAUDE.md glossary), and the same line docs/178
drew at the transcript ("the kernel never truncates the transcript; the host owns
the transcript", `rewind.py:58-63`) — re-drawn one layer down at token/KV
granularity. **A cache hint is the `rewind_plan` of the token layer; cache
management is the `dos apply` of the token layer** — and `dos apply` is the *one*
opt-in host PEP that deliberately lives outside the kernel (docs/126).

## 1. The real blocker (vs. the merely unbuilt)

Managing the cache is blocked by **four structural invariants at once** — each one
redefines what the kernel *is*. All four are REAL, not effort. (5 of 6 adversarial
verdicts CONFIRMED; the 6th qualified, and the qualification *strengthens* the
case — see (b).)

**(a) Layering inversion — KV state lives in the ENGINE, not the transcript.**
DOS keys whole turns by `(index, sha256)`; KV management needs token positions,
block tables, attention K/V that exist only in the engine's address space (vLLM
chains a block hash `hash(parent_hash, block_tokens)`; SGLang keys a position-0
radix trie). The layering contract is strictly one-directional — a module may
import the layer *above*, never below. Reaching into block tables is a strict
layer-DOWN move, the inverse of the kernel's defining arrow. **This is the
load-bearing blocker and it is permanent**: docs/178 §2 supplies the soundness
reason — a survivor's K/V was *computed attending to* bytes a mutation would
remove (attention-content staleness), and that invariant is invisible from the
opaque turn bytes DOS hashes. Only the engine holds the attention graph, so only
the engine can soundly mutate a block.

**(b) Provenance — a cache HIT/MISS is the engine's self-report.** A cache verdict
is *positive evidence*, so it lives under `believe_under_floor`
(`evidence.py:412-485`): belief is granted ONLY when a non-forgeable
(`OS_RECORDED`/`THIRD_PARTY`) source attests; an `AGENT_AUTHORED` claim is
*structurally incapable* of moving abstain→believe (CONFIRMED). Today DOS measures
cache cost as `char//4` (`restart_arm.py:64`) — an *asserted* proxy, never the
engine-authored `cache_read_input_tokens`. ⚠ *Qualification (from the adversarial
pass):* even the engine's witness can drift — NVIDIA Dynamo's default KV-router
builds an **approximate** radix tree from worker-published events over lossy
PUB/SUB (needs gap-detection + replay + periodic resync). So the witness is not
free even from the engine; a robust cache witness needs the same care the WAL
fold gets. This blocker is **asymmetric with (a)**: it blocks *measurement* and
**falls** the moment the engine emits a (gap-handled) `THIRD_PARTY` witness on the
docs/185 LogSource seam; (a) blocks *mutation* and never falls.

**(c) Determinism — prefix caching itself changes outputs.** Every shipped verdict
is pure: state-in/decision-out, no I/O, no clock (`arbiter.py:4-7`). KV state is
the opposite: timing-, version-, GPU-residency-dependent, evicted under memory
pressure. Worse (CONFIRMED): prefix caching **changes model outputs** unless
batch-invariant kernels are used (Thinking Machines — FlashAttention-with-KV-cache
breaks batch-invariance). So cache state is not an observationally-neutral input
to a pure verdict. This cuts cleanly: a verdict that *reads a frozen cache fact*
stays pure (the `git_delta`→`liveness.classify` shape); a verdict that *drives
eviction* cannot. **Purity is fully compatible with adjudication and fully
incompatible with management** — the distinction, restated at the type level.

**(d) Dependency posture — managing means an engine SDK.** The kernel is
deliberately `pyyaml>=6.0`-only; even the MCP framework is quarantined to a `[mcp]`
extra in a *separate top-level package* so a plain `pip install dos-kernel` stays
near-stdlib (CONFIRMED: grep of `src/dos/` for `vllm|sglang|torch|transformers|
openai|anthropic|httpx` returns nothing). To *manage* the cache a module would
`import vllm` — dragging a GPU-bound, fast-moving dependency into the core every
consumer installs. A *reader* driver pulling the witness is fine (it lives in
`drivers/*`, one-way arrow); a *mutator* driver is the host's PEP, outside the
kernel by the same arrow as `dos apply`.

### Merely unbuilt (NOT blockers — they stay PDP/advisory)

Three things are sometimes mistaken for blockers. They live entirely inside the
PDP and never cross the line: **cache instrumentation** (read the engine's
reported tokens into the ledger), **anchor-alignment** (digest the cumulative
prefix / align the anchor to a cache breakpoint — docs/178 §5 q1), and **advisory
cache hints** (recommend a cut/pin/evict the engine may honor). The common
thread: instrumentation *measures*, alignment *describes*, hints *propose* — none
*mutate*. The bright line is whether DOS authors the cache effect. It must not.

## 2. What if DOS DID? — the concrete forward moves, ranked

Two independent adjudications (run + resume) converged on the same ranked
scoreboard. Scoring: **BLOCKER** real-structural vs unbuilt · **VALUE** durable
(docs/170 model-orthogonal) vs decaying · **CLEAN** advisory-PDP vs inversion-PEP
· **EFFORT**.

| # | Direction | Blocker | Value | Clean | Effort | Net |
|---|---|---|---|---|---|---|
| **1** | **Cache-hit cost instrumentation** — read the engine's reported `cache_read_input_tokens` into the rewind A/B ledger (replace `char//4`), labeled engine-reported. The reader already exists in `scripts/trajectory_audit.py`. | unbuilt | durable | PDP | **Low** | **BEST BET** |
| **2** | **Cache provenance/admission verdict** — "admit this prefix for reuse only if its terminal anchor is attested / not poisoned." Shape-compatible with `arbitrate` over the *reported* index. | unbuilt | durable + super-linear in fanout; **owned by no one** | PDP | Med | strongest durable slot |
| **3** | **Verified-prefix pin / poison-evict hint** — "this prefix ends at a kernel-stamped anchor, reused across N agents → pin it" / "ends in `NOT_SHIPPED`/`UNANCHORED` → evict." | unbuilt | durable — the content-aware signal LRU/TTL provably lack (vLLM #36311) | PDP iff a hint | Low–Med | cheapest new value |
| **4** | **Cache-aware anchor strengthening** — digest the cumulative prefix, align the anchor to a warm breakpoint (fixes docs/178 §5 q1, `rewind.py:546`). | unbuilt | durable but narrow | PDP | Low | good hygiene, low ceiling |
| **5** | **Trust-aware cache router** (§3) — route a child to a parent's warm+verified prefix. | half-blocked | durable at fanout, →0 at N=1 | PDP at turn-granularity; PEP at KV-granularity | High | real primitive, premature |
| **6** | **Arbiter locality-term** — a `rank_key` that prefers warm-but-disjoint regions, locality folded *under* the safety floor. | none structural (seam exists, `arbiter.py:158`) | thin | clean by construction (rank, never re-admit) | Low–Med | cheap, marginal |
| **✗** | **Cache MANAGER** (DOS pins/evicts/moves blocks) | **REAL/PERMANENT** (a) | n/a | **inversion-PEP** | — | **REJECTED — must not build** |

**#1 is the best bet and the ranking is not close.** Every other direction's
honesty *depends* on it: #2's "is reuse cheap," #3's pin/evict economics, #5's
entire value proposition (the ~0.1× read vs ~12.5× miss asymmetry, docs/178 §2),
and the rewind A/B's cost half are all `char//4` assertions today. **Until DOS
holds one engine-authored `cache_read` token, every cache claim it makes is
`AGENT_AUTHORED` — "`git commit --allow-empty -m deployed` in a different font"**
(docs/185 §1). #1 is low-effort, fully byte-clean (boundary-I/O → pure data), the
partial-fall of blocker (b), and the unlock for everything above it.

## 3. The routing concept — DOS's arbiter as a cache-aware router?

⚠ *This section is full but did not receive its adversarial pass (rate-limited);
the "exact homology" and "genuine new primitive" claims are the author's, not yet
independently refuted.*

**The structural analogy is exact, not loose.** Mooncake's Conductor and DOS's
`arbitrate` are the same *machine*: a pure admission kernel over a WAL-folded live
set, state-in → placement-out. The correspondence maps term-for-term:

| Cache router (Mooncake / Dynamo) | DOS arbiter | Evidence |
|---|---|---|
| node / replica | **lane** (a leased region) | `LaneDecision.lane` (`arbiter.py:64-78`) |
| cache residency (which node holds the prefix) | **region-lease** (which lane is held) | `live_leases` (`arbiter.py:151`) |
| cache-aware route (warm node busy → peer with same shard) | **auto-pick redirect** (lane busy → free disjoint lane) | `arbiter.py:641-707` |
| global cache directory | **WAL** folded to live state | `lane_journal.replay()` (deterministic) |
| prefix-hash key | **run_id** lineage token (sortable, parent/root) | `run_id.py:134-160` |

**But the gate is the WRONG SHAPE.** The arbiter optimizes **disjointness** —
`admit ⟺ the requested tree collides with no live lease` (a SAFETY/distrust goal:
*NO to overlap*). A cache router optimizes **locality** — route to the replica
whose cached prefix *most overlaps* the prompt (a PERFORMANCE goal: *YES to
overlap*). Disjointness has no cache analog and prefix-affinity has no safety
analog. So the arbiter's *gate* cannot be a router's gate.

**The skeleton, however, already carries the hook.** Auto-pick is not first-fit —
it is *ranked*: `rank_key` (`arbiter.py:158`) reorders candidates and admits the
argmax over the admissible set, under the soundness law "rank, never re-admit"
(docs/91 value-aware picker). A `rank_key` scoring each free lane by "how much warm
KV does this region leave for me" makes the arbiter prefer warm-but-disjoint
regions — **locality folded UNDER safety, never instead of it** (direction #6).
The gate is wrong; the rank is right.

**The genuinely novel slot: a TRUST-AWARE cache router.** Mooncake routes by *who
has the cache*. A fleet of mutually-distrusting agents needs *who has the cache AND
is that prefix verified AND safe to share with THIS requester*. DOS already ships
every primitive that key needs, and zero of the cache machinery:

- a **prefix identity with a byte-authorship floor** — `rewind.transcript_digest`
  is "the kernel's hash, the rewind anchor's author" (`rewind.py:385-390`); reuse
  is valid only if the live turn still digests to it. *A verified-prefix-cache key
  in everything but name* — at turn granularity, not KV-block granularity.
- **lineage** — `run_id` `parent_id`/`root_id` authorizes *which* requester may
  share a prefix.
- a **non-forgeable belief gate** — `believe_under_floor`: don't believe a prefix
  is reusable because someone *says* it is warm; believe it because a `THIRD_PARTY`
  witness attests AND its digest matches AND lineage admits the sharer.

> A child routes to its **parent's warm, verified prefix**, keyed by
> `(verified-prefix-digest, provenance)`, reusing the cached KV *iff* (a) the
> digest matches, (b) a non-forgeable witness attests, (c) lineage authorizes it.
> Cache reuse **gated by adjudicated trust** — the cache analog of `verify`.

This is DOS's signature move a fifth time: take a temporal/admission verdict and
re-aim it (git → tool-stream → resume → completion → **admission**). It is
unclaimed by Mooncake (pure performance, no trust) and unbuilt by DOS (pure trust,
no cache). The 2024–2026 literature is *converging* on it from the other side:
"Token Coherence" applies MESI + single-writer + monotonic versioning + TLA+ to
multi-agent caches; CachePrune/KVCOMM have "no notion of verified-safe" and "treat
the producing agent as ground truth"; PROMPTPEEK (NDSS'25) shows shared prefixes
are a trust hazard the field wants to gate by "prefixes verified safe" — exactly
DOS's lane/arbiter+witness shape.

**The strongest objection (build-blocker for the KV-granular version).** The
arbiter's claim to fame is *purity*, and a cache router is purity's natural enemy.
Disjointness is a deterministic predicate over data-in-hand — two disjoint trees
*stay* disjoint. Cache residency is volatile, per-millisecond, eviction-driven:
**a warm cache goes cold without anyone logging a RELEASE.** The TOCTOU window the
arbiter closed for region-locks *reopens* for residency, and `believe_under_floor`
does not close it — a witness attests warmth *was* present, not that it *persists*
to use-time. And the deepest cut: a router's whole reason to exist is the
read-vs-miss cost asymmetry, and **DOS has never measured one `cache_read` token.**

**RULING — split it and sequence it.** The **trust half is real, shipped, and
byte-clean at TURN granularity**: a child routing to its parent's verified,
lineage-authorized prefix needs nothing new — build this. The **performance half
(KV-block scheduling) is a forced analogy *as a kernel concern***: it imports a
residency-coherence problem disjointness never had, rests on a cost DOS only
asserts, and any mutation is a driver-PEP. Defer it until #1's ledger proves the
asymmetry is worth importing the coherence problem. The HRM `place()` verb (docs/77)
was never built; the arbiter is the endpoint — and a trust-aware `route()` would be
the arbiter's *skeleton* (pure admission over a WAL-folded directory) with the
disjointness gate swapped for a `believe_under_floor` residency gate and a
residency-affinity `rank_key`.

## 4. Where is the value — and does it survive a strong model?

⚠ *Full but un-verified (rate-limited).* Applying the docs/170 rubric without
flinching (defensive lift decays to ~0 on a strong model; what survives is
loop-hygiene under horizon × fanout):

1. **The axis is DURABLE, not decaying.** Cache-economics does *not* depend on the
   model being wrong, so it does not decay on a model upgrade: a smarter model
   still has a finite context window, still cold-pays a shared prefix per agent at
   fanout, still benefits from running where its cache is warm. It is
   throughput-amplified, co-monotone with DOS's coordination value — the *right*
   coordinate (docs/170 §1b), not defensive lift.
2. **But the engine already captures almost all of it.** vLLM/SGLang own the
   cache; Mooncake/LMCache own store+transfer; Dynamo/sgl-router own routing.
   These see the one thing reuse needs — the prefix hash — far below DOS. **DOS's
   incremental value is strictly the residual the engine cannot see.**
3. **The residual = the trust×cache intersection.** The engine is content-blind to
   provenance: it caches a confident-but-false "done" prefix (docs/170 §1c: strong
   models fail silently ~92% with substantial final narration) *just as eagerly*
   as a verified one. Only DOS knows `oracle.is_shipped == NOT_SHIPPED`, knows
   *which agent authored* a prefix, knows whether it is *safe to share*. Three
   unowned, DOS-shaped decisions: **(1) which prefix is verified-reusable vs
   poisoned** (routers cache content-agnostically); **(2) cross-agent sharing as an
   adjudicated admission problem** (PROMPTPEEK's hazard); **(3) eviction PRIORITY
   of a kernel-verified anchor** (engines evict by LRU/TTL — none pin a prefix
   *because* it ends at a non-forgeable anchor, vLLM #36311).
4. **The honest scoreboard.** A real slot, but a **thin** one: → 0 at N=1
   (docs/136 — a single agent verifying its own cached prefix is the plant grading
   itself), a genuine coordination win only at fanout, and a **provenance overlay
   on a router DOS does not own**, not a fat frontier slot. Calling it a keystone
   would be the exact over-claim docs/170 §6 exists to cut. The defensible claim:
   *"the engine routes and evicts on the hash; DOS stamps which shared prefix is
   verified-reusable and safe across agents, and which is poisoned."*

## 5. The bottom line

The real value is one thin-but-genuine slot — **the trust×cache intersection the
engine is structurally blind to**: "this shared prefix is verified-reusable and
safe to share across these agents / this one is poisoned, evict it." It is durable
by the docs/170 rubric, a real coordination win at horizon × fanout, and honestly
→ 0 at N=1 and mostly the engine's job. The real blocker is **not** effort and
**not** the layering inversion (that one is permanent and correctly forbidden — DOS
must never *manage* the cache); the real blocker is **evidentiary**: every cache
claim DOS can make today is an `AGENT_AUTHORED` `char//4` assertion with no
engine-authored witness. **The one thing worth building is #1: wire the engine's
`cache_read_input_tokens` into the rewind A/B ledger as a `THIRD_PARTY` cache
witness on the docs/185 LogSource seam** — low-effort, byte-clean, the partial-fall
of the byte-authorship blocker, and the precondition that turns every other
direction (verified-prefix pinning, the trust-aware route, even honest cache-hint
advice) from an assertion into attested fact. **Build the witness; defer the
router; never touch the blocks.**

## 6. Provenance / cross-refs

- The backward sibling: docs/178 (tail-truncation is the only sound + cheap cut).
- Routing primitives: `arbiter.py` (`arbitrate` + `rank_key`), `run_id.py`
  (lineage spine), `lane_journal.py` (WAL fold), `drivers/watchdog.py` (fleet
  poll), `rewind.py:385` (`transcript_digest` as a prefix identity),
  `evidence.py:412` (`believe_under_floor`). The HRM `place()` verb (docs/77) was
  never built.
- Prior art (research grounding): Mooncake (KVCache-centric disaggregation,
  Conductor cache-aware routing), LMCache (KV pooling/transfer), NVIDIA Dynamo /
  sgl-router (approximate-radix KV routing, drift-prone published events),
  KVCOMM/KVFlow (multi-agent prefill recompute scaling), CachePrune (heuristic,
  no verified-safe), PROMPTPEEK (NDSS'25, shared-prefix trust hazard), "Token
  Coherence" (MESI + TLA+ for multi-agent cache), Thinking Machines
  (batch-invariance / caching changes outputs), vLLM #36311 (no semantic eviction
  priority).
- The cost-instrumentation gap: `restart_arm.py:64` (char/4 proxy) vs
  `scripts/trajectory_audit.py` (real `cache_read_input_tokens` +
  `cache_miss_premium`). The witness seam: docs/185 LogSource.
- The workflow: `wf_775501d7-684` (run + 2 resumes across server-side
  rate-limits). The `if-it-did` lens never ran clean; its content is reconstructed
  from the §2 scoreboard + §1 "merely unbuilt", both of which DID run + verify.

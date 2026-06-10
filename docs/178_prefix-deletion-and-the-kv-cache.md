# 178 — Prefix deletion and the KV cache: why tail-truncation is the only sound cut

> *Dated analysis — written 2026-06-06. Produced from a 12-agent grounded
> workflow (`wf_ff4eaf71-00d`): 4 grounding readers (DOS rewind mechanism ·
> self-hosted KV mechanics vLLM/SGLang/RoPE · API prefix-caching Anthropic ·
> soundness theory) → 4 design lenses, each adversarially verified against
> file:line and vendor docs. Every status label and number is a dated observation
> against the working tree on that day. Companion to docs/164 (the FIX/rewind
> verdict), docs/172/175 (the live rewind refutation), and docs/176 (live
> trajectory walk/re-walk/prune) — this doc supplies the **KV-cache layer** those
> docs gesture at ("warm prefix when warm", "the cost half asserted, never
> instrumented") but never analyze.*

## 0. The headline

**DOS never touches the KV cache.** A grep of `src/dos/` for
`kv_cache|attention_mask|token_position|prompt_cache|cache_control` returns
nothing but one unrelated retry-backoff *comment* in `loop_decide.py:440,451`
(about whether a retry stays inside the provider's prompt-cache TTL — narration,
not manipulation). DOS operates one layer above: on **whole transcript turns**,
each identified by an `(index, sha256-digest)` pair (`rewind.py:140`, `TurnRef`).
The KV cache is entirely the host's concern. What DOS controls is the single
decision that *determines* the cache outcome: **where the cut lands.** And there
is exactly one cut it will propose.

## 1. What DOS actually does to a bad section today

When a ground-truth stop signal fires (`Resume.DIVERGED` or
`Convergence.THRASHING`/`STARVED` — `rewind.FireVerdict.should_surface`),
`rewind.rewind_plan` proposes **tail-truncation only** — drop every turn
*strictly after* a kernel-stamped anchor:

```python
# rewind.py:573 — the SOLE deletion computation in the entire kernel
dropped = tuple(sorted(t.index for t in turns if t.index > checkpoint.turn_index))
```

Three properties, all confirmed at file:line + pinned by `tests/test_rewind.py`:

- **Tail-only, never mid-prefix.** The filter is `index > anchor`. The kept set is
  always a contiguous prefix `{≤ anchor}`; the dropped set is always the
  contiguous tail `{> anchor}`. **There is no code path anywhere in the kernel
  that excises a middle span while keeping later turns**
  (`test_dropped_turns_are_exactly_those_after_the_anchor`). The live consumer
  enacts it as a pure `del messages[cut:]` (`dos_react.py:750`).
- **Advisory.** The kernel returns a `RewindPlan`; **the host enacts it** — "the
  kernel never truncates the transcript; the host owns the transcript"
  (`rewind.py:58-63`, docs/164 P1.5). PDP, not PEP.
- **Non-forgeable anchor.** The cut index is honored only if the live turn
  re-hashes to the digest the kernel stamped (`_digests_match`, `rewind.py:546`).
  On mismatch → `UNANCHORED`, `rewind_to_turn = -1`, drop nothing. The digest's
  byte-author is the *kernel's* SHA256, not the agent — the
  `evidence.believe_under_floor` discipline on the conversation axis.

## 2. The asymmetry that is the whole answer

Every production cache — hosted API or self-hosted engine — reuses KV **only along
an unchanged byte-prefix from position 0.** That single fact creates a hard
asymmetry:

| Operation | Anthropic prefix cache | Self-hosted (vLLM / SGLang) | Sound? |
|---|---|---|---|
| **Tail-truncate** (what DOS does) | kept prefix byte-identical → reads back at **~0.1×** (`cache_read`) | KV blocks `[0..P)` reused directly (block-chain hash / radix path unchanged) | **Yes — by construction** |
| **Delete a middle turn**, keep suffix | prefix diverges at the cut → entire suffix repriced at **1.0× + 1.25× write (~12.5× swing)**; only the part *before* the cut survives | unsupported: every downstream block invalidates | **No** |

- **API (Anthropic, authoritatively grounded in the claude-api skill's
  `shared/prompt-caching.md`):** caching is a strict prefix match over rendered
  bytes (`tools → system → messages`). "Cache hits require 100% identical
  segments; changes at each level invalidate that level and all subsequent
  levels." Delete `T1` from `[T0,T1,T2,T3]` and `T2`'s cached prefix
  `(T0·T1·…·T2)` no longer matches the presented `(T0·T2)` — `T2,T3` reprocess
  uncached + rewrite. Only `T0` survives. Breakpoints (max 4/request; min
  cacheable prefix 4096 tokens on Opus 4.x / Haiku 4.5, 2048 on Sonnet 4.6) mark
  *read points along the one prefix* — they do not create independent caches of
  disjoint sections.
- **Self-hosted:** vLLM PagedAttention block hashes *chain* the parent hash
  (`hash(parent_hash, block_tokens, …)`); SGLang RadixAttention keys a position-0
  prefix trie. A middle deletion fails for **two independent** reasons: (i)
  **position shift** — every suffix token's position id moves (CacheSlide, FAST'26:
  "even shifting by one token invalidates the cache"); (ii) **attention-content
  staleness** — the surviving suffix K/V were *computed attending to the now-deleted
  middle*. Reason (ii) is the deep one: re-rotating RoPE keys fixes the position id
  but **not** the staleness (the values encode bytes that no longer exist).
  Research systems (CacheBlend, KVLink) only approximate non-prefix reuse by
  *recomputing* 10–20% of tokens — never a free splice.

**The non-coincidence that ties it together:** the deletion that is *cache-cheap*
and the deletion that is *provably sound* are the **same deletion**, because both
fall out of one fact — **causality flows forward.** A survivor at position ≤ A
neither attended to, nor was sampled conditioned on, anything at position > A. That
is simultaneously (a) the soundness guarantee and (b) the exact prefix-reuse
precondition both cache regimes require. The middle deletion that breaks soundness
(a survivor's K/V depends on deleted bytes) is *the same fact* that breaks the
cache (the suffix KV encodes the gone middle). **One failure, seen from two
layers.**

## 3. Can you safely "delete" a mid-prefix section?

**No — not soundly, not cheaply, and the reasons are independent.** A naive middle
splice fails three ways at once:

- **Unsound (the dependency hazard).** The surviving suffix was *generated
  conditioned on* the deleted middle. That is an **implicit conditioning edge**
  with no byte-level evidence to refute — the case taint analysis famously cannot
  track from bytes. Keeping the suffix is sound only when it is provably
  independent of the deleted section, which requires a model/human (the
  JUDGE/HUMAN rung), not a deterministic kernel.
- **Cache-destroying.** §2 — the suffix reprices at ~12.5×.
- **Ill-formed (a *separate* trap).** Deleting a middle turn with a `tool_use`
  while keeping a later `tool_result` orphans it → **hard API 400** (real:
  claude-code #40305/#37452; docs/176 §4 hazard (b)). DOS does **not** check this
  in-kernel — it hashes opaque turn bytes — so well-formedness is the host's
  burden. *Even a tail cut can orphan* if it lands between a `tool_use` and its
  `tool_result`.

The design space, ranked on DOS's trust ladder (ORACLE → JUDGE → HUMAN) and the
F0–F3 fix rungs (who authors the fix bytes):

| Approach | Trust cost | Cache cost | Verdict |
|---|---|---|---|
| **(a) Tail-truncate to a verified anchor *before* the bad section, re-walk forward** | lowest (ORACLE — forward-causality discharges the dependency proof for free) | lowest (kept prefix warm) | **The principled move. DOS ships this.** |
| (b) Dependency-tracked excision (prove no survivor depends on the deleted span) | high (implicit edge → JUDGE; unsound in general) | high (still a prefix change → suffix repriced) | needs a taint/slice proof DOS deliberately lacks |
| (c) Compression / eviction (StreamingLLM, H2O, Scissorhands, SnapKV) | a *different* operation — explicitly **lossy**, keeps behavior approximately, removes no logical section | — | not deletion of a known-bad turn |
| (d) Re-summarize the middle | highest (F3 — *authors content* → forgeable, gated) | high + injects an un-adjudicated belief | the rung DOS forbids: "never author-and-believe" |

**So DOS's answer to "delete a bad section" is to *refuse the operation as stated
and convert it*:** turn "excise the middle" into "tail-truncate to the last
kernel-verified anchor *before* the bad section, then let the agent re-walk." That
is the only deletion it can prove sound and the only one that is cache-cheap — and
it is not a limitation being papered over; it is the same forward-causality fact,
enforced.

## 4. How to *prove* it — four obligations, and which DOS discharges

A deletion of section `S` is *sound* iff the continuation is (a) dependency-sound,
(b) well-formed, and ideally (c) observationally equivalent (Morris contextual
equivalence — the compiler-transformation standard; undecidable in general).
That decomposes into four *checkable* proof obligations:

| Obligation | What it proves | DOS status |
|---|---|---|
| **1. ANCHOR** | you cut to exactly the stamped boundary | **Discharged, mechanized** — kernel-authored SHA256 digest match; `UNANCHORED` on mismatch (`rewind.py:544-569`) |
| **2. SUFFIX-INDEPENDENCE** | no survivor depends on a deleted token | **Discharged by construction** — tail-truncation + forward autoregressive causality. Survivors' dependency set `⊆ {<A}` is disjoint from dropped `{>A}`; *no analysis needed* |
| **3. WELL-FORMEDNESS** | the re-entered transcript is valid for the API | **Partially** — consumer guards leading-orphan `ToolMessage`; the **multi-tool-call-strand cut is unguarded** (docs/176 §4, unmeasured). Mechanizable but not in-kernel today |
| **4. CACHE-HIT** | the warm prefix was *actually* reused (the cost claim) | **Not discharged** — the A/B ledger is `char//4` (`restart_arm.py:64`), never `cache_read_input_tokens`. The right instrument exists (`scripts/trajectory_audit.py` reads the usage object + a `cache_miss_premium`) but is not wired to the rewind A/B |

**The synthesis: DOS proves deletion-soundness the same way it proves everything —
by *who authored the bytes* (the anchor digest is kernel-authored, non-forgeable)
and by *reducing the hard case (middle excision) to the provable case (tail
truncation)*.** Obligations 1 + 2 are jointly *sufficient* for tail deletion — but
only tail deletion. A mid-prefix deletion keeping a suffix is the **unbuilt rung**:
it would need a backward-slice proof including the implicit conditioning edge
(→ JUDGE/HUMAN, not ORACLE), a no-good to prevent re-derivation, and structural
re-pairing of any split `tool_use`/`tool_result`.

## 5. Three honest qualifications (surfaced by adversarial verification)

These came from the workflow's own skeptics refuting the draft claims — stated
plainly rather than papered over:

1. **The anchor proves *one turn*, not the whole prefix.** `intent_ledger.py:247`'s
   docstring says `transcript_digest` is "the kernel's hash of the
   transcript-up-to-`turn_index`," but the code
   (`rewind_evidence.turns_from_records`) digests **each turn independently** and
   `rewind.py:546` re-hashes **only the turn at the anchor index**. So an actor who
   rewrites a turn *before* the anchor while leaving the anchor turn byte-identical
   **passes the check**. The anchor proves boundary-turn integrity, not
   surviving-prefix integrity — **the docstring overstates what the code
   verifies.** A real, fixable gap (either digest the cumulative prefix, or correct
   the docstring).
2. **In the live arm there is no separate SUSPEND event.** `dos_react.py`
   synthesizes the checkpoint at rewind time from the same live tool-result tuple
   whose digests it just computed — so the re-hash-and-compare is structurally a
   **self-match** there, not a check against an independently-earlier stamp. The
   non-forgeability property (kernel-authored digest) still holds; the "minted at
   SUSPEND time" framing describes the *pure-kernel design*, not the experimental
   path. The two-axes-one-anchor design (git-`resume` + transcript-`rewind` sharing
   one `OP_SUSPEND`) is not realized in-flight (docs/176 §5 gap 2).
3. **Soundness ≠ usefulness** — the load-bearing caveat, from DOS's *own* live
   data. The powered A/B (`70d946e`, n=48) found tail-rewind **placement-proven but
   it did not convert**: rewind 44.9% < block 48.3% < none 49.2%. The mechanism is
   the **upstream-cause livelock** — when the bad section's *cause* is an omission
   *before* the anchor, re-entering the clean (and cache-warm) prefix faithfully
   reproduces it, and the agent re-invents the same dead end. "Safe to delete" (the
   invariant holds) and "correct to delete" (the bad section was the cause) are
   different predicates. The four obligations prove the first; if the cause is
   upstream of every clean anchor, no deletion — however sound — removes it, and the
   right move is the next rung (F3/PEP or a human), not a deeper cut.

## 6. The one-line answer

DOS does not manage the KV cache — it manages *where you are allowed to cut*, and
it allows exactly one cut: **tail-truncation to a non-forgeable, kernel-stamped
anchor.** That is the only deletion that is simultaneously **cache-cheap**
(unchanged prefix → warm reuse) and **provably sound** (forward causality → no
survivor depends on what is dropped) — and those two properties are the *same
fact* viewed from two layers. A true mid-prefix excision is both unsound (implicit
suffix dependency, unobservable from bytes) and cache-destroying (~12.5× reprice),
so the principled move is to **convert** it into a tail cut to the last verified
anchor *before* the bad section. Proof is by byte-authorship (the kernel hashes the
anchor) plus reduction (tail-causality discharges suffix-independence for free) —
with three live gaps worth knowing: the anchor checks one turn not the whole
prefix, well-formedness (tool-call pairing) is the host's job, and the cache-hit
cost is asserted but not yet instrumented.

> The forward direction — **what if DOS *did* manage the cache directly, what is
> the blocker, where is the value, and is there a cache-routing concept here
> (Mooncake-style disaggregation)?** — is **docs/195**, and the concrete
> integration build plan is **docs/196** (179–194 were taken by concurrent work).
> This doc draws the soundness boundary those start from. The short version: DOS
> can *adjudicate/advise* the cache (a byte-clean hint the engine acts on) but not
> *manage* it (the layering inversion); the real blocker is evidentiary (cache cost
> is asserted, not witnessed); the one slot the engine can't see is the trust×cache
> intersection (verified-reusable vs poisoned, safe-to-share-across-agents).

## 7. Provenance / cross-refs

- The mechanism: `src/dos/rewind.py` (the tail-deletion verdict),
  `rewind_tokens.py` (byte-clean no-good vocabulary), `rewind_evidence.py`
  (boundary digesting), `intent_ledger.py:236-284` (the `SuspendCheckpoint`
  anchor), `resume.py:69` (the git-axis `DIVERGED` graftability proxy).
- The KV-cache facts: claude-api skill `shared/prompt-caching.md` (Anthropic
  prefix-match + pricing); vLLM PagedAttention + SGLang RadixAttention docs;
  CacheSlide (FAST'26), CacheBlend, KVLink (non-prefix reuse needs recompute);
  StreamingLLM / H2O / Scissorhands / SnapKV (lossy eviction, not deletion).
- The live refutation: docs/172 §8 + docs/176 §4 (`3225fc8` / `70d946e`), powered
  A/B n=48; the cost-instrumentation gap: `restart_arm.py:64-79` (char/4 proxy)
  vs `scripts/trajectory_audit.py` (real `cache_read_input_tokens`).
- The workflow: `wf_ff4eaf71-00d` (12 agents, 1.1M tokens, 8 design+verify lenses).

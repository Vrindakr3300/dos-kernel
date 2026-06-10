# 124 — The Go-core build plan: what the parity contract is actually over

> **[`100`](100_native-spine-port-plan.md) (NSP) named the boundary and ranked the
> phases; [`122`](122_the-core-go-runtime-and-the-on-device-kernel.md) showed the
> same binary is the on-device runtime. Both rest on one unexamined load-bearing
> claim — *"the Go decider returns byte-identical output to Python"* — and that
> claim is FALSE as stated, for a reason that only shows up when you read the
> actual verdict structs: the kernel's verdicts carry a human-facing `reason`
> string, and those strings bake in float formatting (`f"{ratio:.0%}"`,
> `lane_overlap.py:221`), truncated previews, and prose that no two language
> runtimes will emit byte-for-byte without heroics. The decision a fleet trusts —
> the enum verdict, the structured counts, the lane/tree — IS byte-matchable and
> cheap to freeze. The prose is neither, and freezing it is low-value. So the
> central design act this plan adds to NSP is splitting the parity contract in
> two: a BYTE-EXACT tier over the decision-bearing fields (the ratchet that
> matters) and a SEPARATE, weaker discipline for the `reason` prose (keep its
> generation Python-side, or canonicalize it) — because conflating them either
> blocks the port on un-matchable prose or, worse, tempts a "close enough" parity
> gate that silently lets the decision drift. This note is the build plan re-cut
> around that distinction, grounded in a line-level audit of where Python and Go
> genuinely diverge.**

Status: build plan, sharpening [`100`](100_native-spine-port-plan.md) with a
line-level cross-language determinism audit (done against the current tree, not
inferred) and folding in the device targets from
[`122`](122_the-core-go-runtime-and-the-on-device-kernel.md). §1 is the audit
(where Python/Go actually diverge, with file:line). §2 is the parity-contract
split — the core design decision. §3 re-cuts the phase order around what is
*provable* first, not just *clean* first. §4 is the envelope ABI in concrete
detail. §5 is the determinism rulebook the Go side must follow. §6 is the build/
ship/test mechanics. §7 is the risk register, corrected. Nothing here is built.

This is the mechanism half; *why* an edge trust kernel is a market stays in
[`dos-private`](../../dos-private) (CLAUDE.md split).

---

## 1. The audit: where Python and Go actually diverge (read, not inferred)

NSP's audit scored modules on purity and hot-path criticality. It did **not** ask
the question that decides whether the whole approach works: *given identical
input, where would CPython and a Go RE2 build produce different bytes?* I audited
the pure-decider set for the seven known cross-language divergence sources. The
result is sharper and more encouraging than "it's all risky" — the hazards are
**few, localized, and fall into two buckets**: float-formatted prose, and
lookbehind regex. Everything else is matchable.

### 1.1 Float formatting into the `reason` string — the real hazard (localized)

The single load-bearing finding. `lane_overlap.overlap_verdict` formats a float
ratio into three human-readable reason strings:

```python
# lane_overlap.py:216–228
ratio = shared / requested
... f"{ratio:.0%} of requested tree shared, threshold {ratio_max:.0%}"   # REFUSE_OVERLAP
... f"{shared}/{len(requested_tree)} = {ratio:.0%} of requested tree shared (≤{ratio_max:.0%})"  # ADMIT_SOFT
```

Python's `:.0%` does float multiply-by-100 + round-half-to-even + format. **A first
draft asserted Go's `fmt` rounds half-away-from-zero, so the percentage would drift;
running real Go refuted that** — Go's `fmt`/`strconv` also use IEEE-754
round-half-to-even, so the `:.0%` *fixed-precision* path agrees byte-for-byte with
Python (see A.1, where this was caught). The float-prose hazard is nonetheless real,
just on a different path: Python `repr`/`str` and Go `%v`/`%g` disagree on
*shortest-decimal* output (`0.1+0.2` → Python `0.30000000000000004` vs Go `0.3`), and
`%.17g` exposes the raw IEEE bits with a differing last digit. The bytes of a reason
that formats a derived float can differ even when **the decision (ADMIT/REFUSE) is
identical** — the decision is the comparison `ratio > ratio_max`, which agrees; only
the rendered number can drift, and *which* formatting path drifts is not visible from
the f-string. (Plus the strings carry non-ASCII — `—`, `≤`, `…` — a second, certain
prose-only divergence source.) The lesson stands and is *strengthened*: do not gate
prose, because you cannot predict per-path whether a float rendering will agree.

**Crucially, this is the *only* float-into-output hazard in the arbiter / liveness
/ loop clusters.** I grepped all three for `:.Nf` / `:%` / `round(` / float
division feeding a string: every other hit is a `/` inside a comment or a docstring
(`liveness.py`, `loop_decide.py` describe ratios in prose; they don't *format*
them). The liveness and loop verdict reasons interpolate **ints and enum `.value`
strings only** — byte-matchable trivially. So the float hazard is one function,
three f-strings, and it lives entirely in the reason *prose*, never in the
*decision*. That is the whole basis for §2's split.

### 1.2 Lookbehind regex — the RE2 blocker, scoped to the oracle cluster

NSP listed "regex dialect mismatch" as a med-likelihood Phase-0 audit item. The
audit resolves it concretely: **the kernel already uses lookbehind today**, and Go's
RE2 does not support it. Every occurrence:

```
phase_shipped.py:201   _BOUNDARY_PRE_NEG = r"(?<![A-Za-z0-9.\-])"      # negative lookbehind
stamp.py:158           re.sub(r"(?<=\d)s$", "", tok)                   # positive lookbehind
stamp.py:465           r"(?<![\w./-])(?:\.\.?/)*(\w[\w\-]*/...)"       # negative lookbehind
```

All three are in the **oracle cluster** (`phase_shipped` + `stamp`). The arbiter,
liveness, and loop clusters use **zero** lookbehind/lookahead/backreference
(confirmed by grep across all three). So:

- The arbiter / liveness / loop clusters are **RE2-clean** — portable as-is.
- The oracle's stamp grammar is **not** portable to RE2 without rewriting those
  three boundaries (they're expressible as RE2 with capture-and-check or
  `\b`-style alternations, but it's a genuine, careful rewrite that must
  differentially match on the live corpus).

This confirms — at line level — docs/122 §5.3's instinct to port the oracle *last*
and to let the device `verify` answer from a non-grep `EvidenceSource` (the remote
commons / content-hash) rather than depend on a RE2 rewrite of the stamp grammar.

### 1.3 The matchable-with-care set (CAUTION, not BLOCKER)

- **Set/dict iteration into output** (`arbiter.py:313,325–330,344–345,610`): every
  set the audit found that feeds *output* is wrapped in `sorted()` before
  rendering (`_known_sorted`, the `free_clusters` list comes from an *ordered* list
  filtered against a set — membership, not iteration). So the final bytes are
  deterministic; the Go side just must apply the same final `sort`. The rule (§5):
  **never iterate a Go map into output; collect, sort, emit** — which Python is
  already doing.
- **`casefold()`** (`arbiter.py:311`, `_tree.py:60`): Unicode case-folding differs
  from Go's `strings.ToLower` on exotic codepoints (ß, Turkish ı). Lane names and
  path prefixes are ASCII in every real workspace, so this is OK *in practice* —
  but the parity corpus must include a non-ASCII lane name to **prove** the chosen
  Go fold matches, or the seam must constrain lane keys to ASCII (the honest fix).
- **Millisecond timestamp truncation** (`journal_delta.py:178,225`):
  `int(parsed.timestamp()*1000)` and `//1000*1000` floor. Integer floor/truncation
  agree across languages **for non-negative values** (all real timestamps); the
  hazard is only sub-millisecond float precision in `timestamp()`, which the
  envelope sidesteps because **the evidence carries already-computed
  `now_ms`/`*_ms` ints** (NSP's "evidence gathered by the caller" rule) — the Go
  decider never parses a datetime. So this is a Python-boundary concern, not a Go
  decider concern.
- **The `float | None` rank_key** (`arbiter.py:158,416`): the auto-pick rank is an
  *injected host callable* returning `float | None`. It is **evidence, not
  decider logic** — Python computes the rank and the envelope carries the resulting
  order (or the per-candidate float). The Go decider must not *recompute* a rank;
  it consumes the ranks as given. With that discipline the float never crosses the
  language boundary as arithmetic, only as a value to compare — and the sort is
  already stabilized by `enumerate` index (`arbiter.py:433,440`).

### 1.4 Verdict — the corrected cluster ranking

NSP called the arbiter the "cleanest cut." The determinism audit *mostly* agrees
but corrects the nuance: the arbiter's **decision** is the cleanest, but its
**reason prose** carries the one float hazard. The honest ranking for *byte-parity
readiness of the decision*:

| Cluster | RE2-clean? | Float-in-output? | Set→output? | Decision-parity readiness |
|---|---|---|---|---|
| **Liveness** (`liveness`+`journal_delta`) | yes | no | no | **A+** — ints + enums only; the genuinely cleanest |
| **Loop** (`loop_decide`+`gate_classify`core+`tokens`) | yes | no | no | **A** — enums + lookup tables |
| **Arbiter** (`arbiter`+`lane_overlap`+`_tree`+`admission`) | yes | **yes (1 fn, prose only)** | yes (all `sorted()`) | **A on decision, B on reason** |
| **Oracle** (`oracle`+`phase_shipped`+`stamp`+`picker`) | **no (3 lookbehinds)** | no | no | **C** — needs the RE2 rewrite + corpus |

The reshuffle matters for §3: **liveness is the cleanest decision to prove the
harness on**, not the arbiter — it has *zero* of the three hazard classes. NSP put
the arbiter first for "most useful standalone"; for *de-risking the parity claim*,
liveness is the better first port. The plan does both (§3).

## 2. The parity contract split — the core design decision

NSP's exit criterion says the Go binary returns *"byte-identical verdicts vs.
Python … on the full unit corpus."* §1 shows that, taken literally over the whole
`to_dict()`, this is either unachievable (the float-formatted reason) or achievable
only by porting Python's exact float-formatting and prose-assembly into Go — which
*reintroduces* the kind of incidental, churny logic the port was supposed to leave
in Python. The fix is to be precise about **what the ratchet is protecting**.

A verdict struct has two populations of fields, with opposite parity needs:

| Field population | Examples | What it is | Parity need |
|---|---|---|---|
| **Decision-bearing** | `outcome`, `verdict.value`, `lane`, `lane_kind`, `tree`, `auto_picked`, `shared`/counts, `free_clusters`, `pick_count` | the adjudication a fleet *acts on* — the thing downstream trust rests on | **BYTE-EXACT** — this is the ratchet; any drift here is a trust bug |
| **Explanatory prose** | `reason` (the `f"{ratio:.0%} …"` strings) | a human-readable *rendering* of why; never machine-parsed by a consumer | **looser** — same *meaning*, byte-drift tolerable; freezing it is low-value and high-cost |

**The contract this plan adopts:**

> **The differential-parity gate is BYTE-EXACT over the decision-bearing fields
> (a canonical projection of the verdict), and the `reason` prose is excluded from
> the byte gate. The ratchet freezes the decision; the prose is free to differ.**

Two ways to honour it; the plan picks (A) as default and keeps (B) as the option:

- **(A) Reason-generation stays Python-side (default, simplest).** The Go decider
  returns the *decision-bearing fields plus a structured reason code* (an enum +
  the structured operands: `{code: REFUSE_OVERLAP, shared, requested,
  ratio_max_num, ratio_max_den}`). Python's existing reason f-strings render the
  human prose from those operands — unchanged, still the spec for the wording. The
  float never crosses into Go; Go emits the *integers* `shared`/`requested` and the
  *rational* threshold (`1/3` as `{num:1, den:3}`, not `0.333…`), Python formats.
  This is strictly cleaner: it also kills the `casefold`-of-non-ASCII and the
  ratio-rounding hazards in one move, because all the lossy formatting lives where
  it always did.
- **(B) Canonical reason grammar (only if a consumer ever needs the reason from
  the Go path directly — e.g. a device with no Python at all).** Define the reason
  as a structured, language-neutral template (`reason_code` + ordered operands) and
  render it with a *shared, spec'd* formatter (rational percentages rendered by an
  explicit round-half-up rule, no locale). More work; only justified for the pure
  on-device tier where Python isn't present to render.

**Why this is the right call and not a dodge.** The reason string is, by the
kernel's own design, *advisory rendering* — `decisions`/`dispatch_top` show it to a
human; no verdict consumer branches on its bytes. Byte-freezing prose would (i)
block the port on the least-valuable surface, and (ii) create pressure to declare a
"99% match" parity gate "good enough," which is exactly the hole that lets a *real*
decision divergence slip through under cover of prose noise. Splitting the contract
makes the byte gate **strict where strictness is load-bearing and absent where it
is theatre** — the same discipline as the kernel's own "distrust the effect, not
the narration": the decision is the effect; the reason is the narration.

This split is the single most important thing this plan adds to NSP, and it should
be written into the envelope ABI (§4) as a first-class distinction: the decision
projection is versioned and gated; the reason is carried but not gated.

## 3. The re-cut phase order — provable-first, not just clean-first

NSP ordered: harness → arbiter → liveness+loop → oracle. The determinism audit
(§1.4) and the contract split (§2) reorder the early phases to **prove the riskiest
assumption with the cleanest decider first**, then claim the standalone-useful win.

### Phase 0 — Harness + corpus + the *contract projection* (unchanged in spirit, sharpened)
Everything NSP's Phase 0 says, **plus** the §2 decision: the corpus exporter dumps
two things per case — the **canonical decision projection** (byte-gated) and the
**full struct including reason** (recorded, diffed advisory-only). The replay
harness asserts byte-equality on the projection and *logs* reason diffs without
failing. Build the stub Go binary, the `DOS_SPINE_NATIVE` flag, the structural
fallback. **Write the missing corpora** NSP named (`gate_classify`-core,
`picker_oracle`) — still required.

*New Phase-0 exit add:* a **negative test that the projection actually excludes the
reason** — feed two verdicts identical in decision but different in reason prose;
the gate must pass. This pins the contract itself before any decider exists.

### Phase 1 — Liveness cluster *(NEW first port: proves parity on the cleanest decider)*
Port `liveness.classify` + `journal_delta.fold_since`. **Why first (corrected from
NSP):** §1.4 shows liveness has *zero* of the three hazard classes — no RE2, no
float-in-output, no set-into-output, ints+enums only. It is the cleanest possible
proof that the harness, the envelope, the projection gate, and the fallback all
work end-to-end, with the *least* chance that a determinism gremlin muddies the
first result. It also lights up the supervisor-loop / `dos top` / MCP
`dos_liveness` native path (a real, if modest, perf surface) and is the verdict an
*unattended* agent leans on most (docs/122 §5.3 Phase C) — so it doubles as the
first device-relevant port.
**Exit:** `test_liveness.py` (7 pure litmus) + `test_journal_delta.py` byte-match on
the decision projection across engines; reason diffs (none expected — no floats)
logged clean.

### Phase 2 — Arbiter cluster *(the standalone-useful win; first encounter with the float split)*
Port `arbitrate` + `overlap_verdict` + `_tree` + `run_predicates`. **This is where
§2 earns its keep:** `overlap_verdict` returns the decision (`Verdict`, `shared`,
`requested`) from Go; the `:.0%` reason is rendered Python-side from those operands
(option A). The Go side carries `ratio_max` as the rational `1/3`, never a float.
**Why second not first:** it's the most *useful* standalone ("fastest file-region
lock manager," and the one a robot wants offline) but it's the first decider with
the float-prose hazard, so prove the harness on liveness first, *then* exercise the
contract split here where it's load-bearing.
**Exit:** all `test_arbiter.py` + `test_admission.py` + `test_lane_overlap.py`
**decision projections** byte-match; the overlap reason renders identically because
Python still renders it; `dos arbitrate`/`lease-lane`/MCP native behind the flag
with clean shadow diff.

### Phase 3 — Loop cluster *(the daemon decider; enums + tables)*
Port `loop_decide.decide` + `gate_policy` + `tokens`. RE2-clean, float-clean,
enum/table-shaped. Requires Phase-0's new `gate_classify`-core corpus.
**Exit:** `test_oracle_and_loop.py` loop cases byte-match on projection.

### Phase 4 — Oracle decider *(last; the RE2 rewrite + the headline CI-storm perf)*
Port `is_shipped`/`batch_is_shipped` + the stamp grammar + `picker_oracle.classify`.
**This is the phase gated on the §1.2 lookbehind rewrite:** the three lookbehind
boundaries (`phase_shipped.py:201`, `stamp.py:158,465`) must be re-expressed in RE2
and proven on the live stamp corpus, or that rung stays Python and the *device*
`verify` answers from a non-grep `EvidenceSource` (docs/122 §5.3 Phase D). The git
grep + state-YAML read stay Python (evidence in the envelope); Go owns only the
registry-first verdict + the stamp matching.
**Exit:** oracle cases + `test_stamp_convention.py` data round-trips + the new
`picker_oracle` corpus byte-match on projection; CI-storm benchmark shows the
per-`verify` wall-clock drop (NSP's headline perf Win A).

### Phase 5 — Device targets + ABI freeze *(folds in docs/122 §5)*
Extend the build matrix to `linux/arm64`, `android/arm64`, `darwin/arm64`
(c-archive for iOS), `wasip1/wasm`; add the cgo `//export dos_spine_decide` +
WASM in-process entry (docs/122 §5.2 — a phone can't `fork`). Promote live
shadow-diff to fatal once soaked. **Freeze the envelope ABI**: version it, add the
schema-compat test, document that schema changes gate like core changes.
**Exit:** docs/122's `test_spine_arm64_byte_parity` (decision projection, on the
cross-compiled target) green; `dos doctor` reports native-spine presence + parity
state.

## 4. The envelope ABI (concrete)

NSP described `{config, evidence, op} -> {verdict}`. §2 requires the *response* to
distinguish gated decision from ungated prose. Concretely:

**Request** (Python → Go, JSON over stdin **or** the FFI/WASM string arg):
```jsonc
{
  "abi": 1,                       // versioned, frozen (Phase 5)
  "op": "arbitrate",              // dispatch key
  "config": { ... },              // resolved SubstrateConfig as data — NO disk reads in Go
  "evidence": { ... }             // already-gathered facts: ints, strings, pre-sorted lists,
                                  //   rational thresholds {num,den} NOT floats, now_ms as int
}
```

**Response** (Go → Python):
```jsonc
{
  "abi": 1,
  "decision": {                   // the BYTE-GATED projection (§2) — canonical, sorted, no floats
    "outcome": "acquire",
    "lane": "benchmark",
    "lane_kind": "cluster",
    "tree": ["benchmark/**"],     // ordered as the algorithm produced, then canonicalized
    "auto_picked": true,
    "shared": 0, "requested": 1,  // structured operands (ints)
    "free_clusters": [],          // collected, sorted, emitted (§5 rule)
    "pick_count": null,
    "reason_code": "AUTO_PICK_REDIRECT",   // enum, not prose
    "reason_operands": { "requested_lane": "src", "picked_lane": "benchmark" }
  },
  "reason": "auto-picked free cluster lane 'benchmark' (requested 'src' was busy)."
                                  // CARRIED but NOT byte-gated; Python may instead render
                                  //   this itself from reason_code+operands (option A default)
}
```

Properties:
- **No float ever crosses the boundary as a value to be formatted.** Thresholds are
  rationals; ratios are emitted as `shared`/`requested` integer pairs. Python (or a
  spec'd canonical formatter) does any percentage rendering.
- **The `decision` object is the parity contract.** Its keys are fixed-order, its
  lists are canonicalized (sorted where the algorithm's output order isn't itself
  semantic), its values are ints/strings/bools/null only. `json.dumps(decision,
  sort_keys=True, ensure_ascii=False)` on both sides must be byte-identical.
- **`reason_code` + `reason_operands` make the prose *reconstructible* without
  byte-freezing it** — the bridge to option (B) if a Python-less device ever needs
  the reason, without paying for (B) now.
- **`config` is passed in, never read.** NSP's non-goal, restated as ABI: the Go
  binary has no filesystem, no `dos.toml` parser, no git. A device's host shim
  resolves config and gathers evidence in its own language; Go decides.

## 5. The determinism rulebook (what the Go side must obey)

These are the invariants the Go implementation follows so the §2 byte-gate holds.
Each maps to a §1 finding:

1. **Never iterate a map into output.** Go map iteration is randomized. Collect into
   a slice, `sort.Strings`/`sort.Slice` with the *same key Python uses*, then emit.
   (Python already does this — `sorted({…})`; Go mirrors it.) — §1.3 set hazard.
2. **No floats in the decision projection.** Carry rationals (`{num,den}`) and
   integer pairs; compare with integer cross-multiplication (`shared*den >
   requested*num` instead of `shared/requested > num/den`) so the *threshold
   comparison itself* is exact and language-independent. — §1.1 float hazard.
3. **Stable sort with explicit tiebreak.** Where Python stabilizes with an
   `enumerate` index (`arbiter.py:433`), Go carries the original index in the sort
   key. No reliance on sort *stability* differences. — §1.3 sort hazard.
4. **ASCII-only key folding, or a proven fold.** Constrain lane/path keys to ASCII
   at the seam (the honest fix) OR include non-ASCII corpus cases proving the Go
   fold matches `casefold`. Default: constrain + document. — §1.3 casefold hazard.
5. **Ints arrive as ints.** The Go decider never parses a datetime or does
   sub-second float math; `now_ms` and all `*_ms` are integers in the envelope.
   Integer floor/`//` agree for non-negative values (the only kind here). — §1.3
   timestamp hazard.
6. **RE2 or Python, never a silent dialect swap.** A regex that uses
   lookbehind/lookahead/backref (the three in the oracle cluster, §1.2) is either
   rewritten to RE2 *and proven on the live corpus*, or that rung stays Python.
   Never "approximate" a Python regex in RE2. — §1.2 regex hazard.
7. **`ensure_ascii=False`, fixed key order, on both sides.** The projection's JSON
   encoding is pinned: no `\uXXXX` escaping divergence, no key reordering. — the
   serialization hazard.

This rulebook is short *because* §1 found the hazards are few. It is the concrete
content of NSP's airy "byte-identical" — the seven rules that make it true.

## 6. Build, ship, test (mechanics)

- **Repo layout.** A `spine/` Go module at repo root (a sibling of `src/`, *outside*
  the wheel — a Go binary is not Python package-data, NSP Phase 4). `go.mod`, the
  dispatcher, one file per cluster decider, a `cmd/dos-spine` (stdin/stdout) and a
  `cgo`/`wasm` export. The Python kernel is untouched in shape (NSP non-goal).
- **The harness lives in Python tests.** `tests/test_spine_parity.py`: export
  corpus → run Python decider + shell/FFI the Go binary → assert projection
  byte-equality, log reason diffs. Runs in CI as the standing ratchet *even with the
  native path off* (NSP Phase-0 quality use). Skips gracefully if the Go binary
  isn't built (so the Python-only dev loop is unaffected).
- **Cross-compile matrix** (Phase 5): `CGO_ENABLED=0` static builds for the §3
  Phase-5 target list; `c-archive` for FFI; `GOOS=wasip1` for WASM. Shipped as
  release artifacts, resolved by path like a driver, Python fallback when absent.
- **`dos doctor` line:** report whether the native spine is present, its `abi`
  version, and whether the last parity run was clean — the operator-visible honesty
  surface (mirrors docs/122 §5.2 #4).
- **The fallback is structural and total:** no flag, non-zero exit, schema mismatch,
  missing binary, *or any projection mismatch in shadow mode* → Python runs the
  original decider. The native path is never the only path (NSP).

## 7. Risk register (corrected against the audit)

| Risk | Likelihood | Impact | Mitigation (grounded in §1–§5) |
|---|---|---|---|
| **Reason prose can't byte-match across languages** | **certain** (it's the float-format finding) | would block the port if mis-scoped | **§2 split** — exclude reason from the byte gate; render Python-side from operands. *This is the headline correction to NSP.* |
| RE2 lacks lookbehind (3 real sites) | **certain** (audited, §1.2) | blocks oracle port only | rewrite the 3 boundaries to RE2 + prove on corpus, OR keep that rung Python and let device `verify` use a non-grep `EvidenceSource` (docs/122 §5.3 D). Arbiter/liveness/loop are RE2-clean. |
| Float threshold comparison drifts | low (after §5.2) | high if it reached the decision | integer cross-multiplication for the ratio test; rationals in the envelope — the *comparison* is exact, only the *rendering* was ever lossy |
| Map-iteration order leaks into output | med (easy Go mistake) | high | §5.1 rule + the projection gate catches it immediately (a reordered list fails byte-equality) |
| Non-ASCII lane name folds differently | low | med | §5.4: constrain keys to ASCII at the seam + a non-ASCII corpus case as proof |
| Port chases the wrong regime | low | med | unchanged from NSP: perf bar is the CI-storm Win A (Phase 4 exit is a benchmark); device win is energy (docs/122 §3), proven separately |
| Dual-impl tax slows legit core evolution | med | med | intended ratchet; cheap for periphery, expensive only for the decision projection — and the projection is exactly the code that *should* be expensive to change |
| Build complexity (a compiled binary in a near-stdlib project) | med | med | ship outside the wheel; total structural fallback means a missing/incompatible binary degrades to Python, never breaks |

## 8. What this plan adds to NSP, in one paragraph

NSP is right that the cores are port-ready and that the boundary is a quality
ratchet; docs/122 is right that the same binary is the device runtime. This plan
supplies the missing rigor under the word *byte-identical*: a line-level audit
showing the hazards are **few and localized** (one float-formatting function, three
lookbehind regexes, a handful of already-sorted sets), and the design decision that
falls out of it — **gate byte-parity over the decision, not the prose.** That split
turns "byte-identical verdicts" from an over-claim that would either block the port
or invite a leaky gate into a precise, enforceable contract: strict where the
fleet's trust lives, absent where it would only be theatre. With it, the cleanest
decider (liveness, not the arbiter) proves the harness first, the arbiter's float
hazard is handled by keeping rendering in Python, and the oracle's RE2 debt is
isolated to the one cluster that actually carries it — and is exactly the cluster
docs/122 already routes around on a device.

---

## Appendix A — Worked examples (run, not invented)

The §2 split is abstract until you watch it on real input. Every example below was
produced by **running the actual kernel** in this repo (`PYTHONIOENCODING=utf-8;
cd src; python -c …`) and reading the cited lines — the outputs are verbatim
captures, not reconstructions. They are the empirical floor under §1's audit.

> Provenance note: these were built inline against the live code (a parallel
> construct-then-adversarially-verify workflow was attempted first but the session
> token budget was exhausted before any subagent ran; the examples were instead
> captured and checked by hand against real Python output). Each is reproducible by
> the command shown.

### A.1 — The float-prose divergence (the reason this plan exists)

The verdict whose reason bakes in `f"{ratio:.0%}"` is `lane_overlap.overlap_verdict`
(`lane_overlap.py:216–228`). Run it on a request that shares **1 of 8** prefixes
with a held lease (a nested collision, *not* an identical glob — which would short
out to `REFUSE_EXACT_GLOB` first, `lane_overlap.py:200`):

```python
# cd src; PYTHONIOENCODING=utf-8 python -c …
from dos.lane_overlap import overlap_verdict as ov
d = ov(['src/a1.py','docs/b.md','tests/c.py','bench/d.py',
        'spk/e.py','ex/f.py','scr/g.py','tl/h.py'], ['src/**'])
# d.verdict.value -> 'admit_soft'
# d.reason        -> 'soft-overlap admit — 1/8 = 12% of requested tree shared (≤33%)'
```

The ratio is `1/8 = 12.5%`, rendered `'12%'`. **A first, *wrong* draft of this
example claimed Go's `fmt.Sprintf("%.0f%%", 12.5)` rounds half-away-from-zero to
`'13%'` while Python's `format(0.125,'.0%')` rounds half-to-even to `'12%'`. An
adversarial review compiled and ran the Go — and refuted it:**

```
# Go, run for real:                 # Python:
fmt.Sprintf("%.0f", 12.5)  -> "12"   format(0.125, '.0%') -> '12%'
fmt.Sprintf("%.0f", 2.5)   -> "2"    # both use round-half-to-EVEN (IEEE-754 default)
fmt.Sprintf("%.0f", 13.5)  -> "14"   # → on THIS path the two AGREE, byte-for-byte
```

So the `:.0%` *fixed-precision* path does **not** diverge — Go's `fmt` and Python's
`format` share IEEE-754 round-half-to-even. The original example was a bad witness,
and leaving it would have been the exact sin the doc warns against (asserting a
divergence without running it; the workflow that was meant to verify never ran).

But the float-prose hazard is **real** — it just lives on the *shortest-decimal /
`repr`* path, not the fixed-precision one. Run for real on `0.1 + 0.2`:

| path | Python | Go | agree? |
|---|---|---|---|
| `%.0f` / `:.0%` (fixed) | `12` | `12` | **agree** (round-half-even) |
| `%.2f` of `0.1+0.2` | `0.30` | `0.30` | **agree** |
| `str()` / `%v` of `0.1+0.2` | `0.30000000000000004` | `0.3` | **DIVERGE** |
| `%.17g` of `0.1+0.2` | `0.30000000000000004` | `0.29999999999999999` | **DIVERGE** |

Python's `repr`/`str` emit the full shortest round-trip decimal; Go's `%v`/`%g`
round to a shorter default; high-precision `%.17g` exposes the raw IEEE bits and the
two differ in the last digit. **Both are "correct shortest decimal" by their own
rule — and they disagree in bytes.**

**The sharpened lesson — stronger than the wrong original.** You *cannot tell by
looking at an f-string* which side of the agree/diverge line a float formatting lands
on: `:.0%` agrees, `str()` doesn't, and a future edit to a reason string could
switch a field from one to the other without anyone noticing. So the only safe rule
is the §5.2 one: **no float in the gated projection at all** — carry rationals and
integer pairs, render any human percentage Python-side, and exclude the reason prose
from the byte gate (§2). If the gate byte-compared the whole `to_dict()`, a reason
that *today* formats with `:.0%` (agrees) could *tomorrow* format a derived float
with `str()` (diverges) and silently start failing the gate on identical decisions —
blocking the port on the least-valuable surface. Gate the decision; carry the prose.
(Independently real: the reason string contains `—` and `≤` — non-ASCII that crashed
a `cp1252` terminal mid-capture this session, the live argument for §5 rule 7's
pinned `ensure_ascii=False`.)

### A.2 — Rational threshold + integer cross-multiply (the decision-flip this kills)

`OVERLAP_RATIO_MAX = 1/3` (`lane_overlap.py`). In Python that literal **is** the
truncated float `0.3333333333333333`, and the decision is `ratio > ratio_max`
(`lane_overlap.py:217`). At the exact boundary (`shared=1, requested=3` via nesting):

```python
# repr(1/3)               -> '0.3333333333333333'
# 1/3 > OVERLAP_RATIO_MAX  -> False        (same truncated float, not greater)
ov(['src/a.py','docs/b.md','tests/c.py'], ['src/**']).verdict.value
#   -> 'admit_soft'        (ratio == 1/3 is NOT > 1/3 → ADMIT)
```

Now the **danger a naive Go port introduces**: if the Go side hardcodes the
threshold as a 6-digit literal `0.333333` instead of `1.0/3.0`, then
`0.3333333333333333 > 0.333333` is **`True`** → **REFUSE** — a *decision flip* from
identical input, caused purely by float-representation drift between the two
implementations. The same lane pair admits in Python and is refused in Go.

The §5.2 fix removes the float from the decision entirely. The test
`ratio = shared/requested > num/den` is exactly equivalent to the integer
`shared·den > requested·num`:

```
shared=1, requested=3, threshold = 1/3  →  1·3 > 3·1  →  3 > 3  →  False  →  ADMIT
```

No float exists; every language computes `3 > 3` identically. The envelope carries
`ratio_max: {num: 1, den: 3}`; the Go decider does integer cross-multiplication; the
`12%`/`33%` percentage is rendered Python-side for humans only. **Floats live in the
prose, never in the comparison.**

### A.3 — The RE2 lookbehind blocker (scoped to the oracle cluster)

Go's `regexp` (RE2) has no lookbehind/lookahead/backreferences. The kernel uses
lookbehind in exactly three places, **all in the oracle cluster**:

```
phase_shipped.py:201   _BOUNDARY_PRE_NEG = r"(?<![A-Za-z0-9.\-])"        # negative lookbehind
stamp.py:158           re.sub(r"(?<=\d)s$", "", tok)                     # positive lookbehind (P0s → P0)
stamp.py:465           r"(?<![\w./-])(?:\.\.?/)*(\w[\w\-]*/[\w./-]+\.[A-Za-z0-9]+)"  # negative lookbehind
```

The `stamp.py:465` lookbehind is a **left boundary**: it matches a file-path token
only when *not* preceded by a word char / `.` / `/` / `-`. Its job (per the comment
at `stamp.py:459`) is to avoid a `len(files)`-inflation false-negative — so
`a/b.py` is matched standalone but the `a/b.py` *inside* `zza/b.py` is not. RE2
cannot express that assertion at all; a faithful port must either capture the
preceding character into a group and check it in host code, or restructure the
pattern around `\b`-style alternations — **a genuine rewrite that must
differentially match the live stamp corpus, not a mechanical translation.**

This is precisely why §3 Phase 4 ports the oracle **last** and gates it on this
rewrite, and why docs/122 §5.3-D routes a *device* `verify` around the grep rung to
a non-grep `EvidenceSource` (the remote commons / content hash). The arbiter,
liveness, and loop clusters contain **zero** lookbehind — they are RE2-clean and
port without this debt.

### A.4 — Liveness is the cleanest decider (so it ports first)

`LivenessVerdict.to_dict()` (`liveness.py:210–224`) returns only ints, `null`,
bools, and enum/prose strings — **no float, no formatted number, no set iteration**.
A real round-trip:

```python
# cd src; PYTHONIOENCODING=utf-8 python -c …
from dos.liveness import classify, ProgressEvidence
ev = ProgressEvidence(run_started_ms=1000, now_ms=600000, commits_since_start=3,
        journal_events_since=5, last_heartbeat_age_ms=8000,
        tokens_spent_since=1200, process_alive=True)
json.dumps(classify(ev).to_dict(), sort_keys=True, ensure_ascii=False)
```
```json
{"evidence":{"commits_since_start":3,"journal_events_since":5,"last_heartbeat_age_ms":8000,
"now_ms":600000,"process_alive":true,"run_started_ms":1000,"tokens_spent_since":1200},
"reason":"3 commit(s) since the run's start SHA — ground-truth state moved","verdict":"ADVANCING"}
```
```python
# zero commits, no heartbeat:
ProgressEvidence(..., commits_since_start=0, last_heartbeat_age_ms=None, ...)
# -> verdict "STALLED", reason "no heartbeat and 0 commits since start — run is dead or hung (never beat)"
```

Every value is language-independent; `json.dumps(decision, sort_keys=True,
ensure_ascii=False)` is the exact byte string a Go struct emits. Liveness has **zero
of the three hazard classes** (no float-in-prose — the reason interpolates the
*integer* commit count; no lookbehind; no set-into-output). That is why §3 corrects
NSP and ports **liveness first** to prove the harness, before the arbiter's float
hazard or the oracle's RE2 debt are in play. (Note: liveness reasons *do* carry the
`—` em-dash, so §5 rule 7's `ensure_ascii=False` still applies — but the rule, not
rounding, is all that's needed: the bytes are otherwise identical across engines.)

### A.5 — A full `arbitrate` envelope (the split, end-to-end)

The live CLI in this repo (where concurrent agents hold the `src`/`docs` lanes)
redirects to a free cluster lane — captured verbatim:

```jsonc
// dos arbitrate --workspace . --lane src
{"auto_picked": true, "free_clusters": [], "lane": "benchmark", "lane_kind": "cluster",
 "outcome": "acquire", "pick_count": null,
 "reason": "auto-picked free cluster lane 'benchmark' (requested 'src' was busy).",
 "tree": ["benchmark/**"]}
```

`LaneDecision.to_dict()` (`arbiter.py:80–87`) emits these fields. The §4 envelope
splits them:

```jsonc
// RESPONSE
{ "abi": 1,
  "decision": {                          // BYTE-GATED
    "outcome": "acquire", "lane": "benchmark", "lane_kind": "cluster",
    "tree": ["benchmark/**"], "auto_picked": true,
    "free_clusters": [],                 // a LIST-comp over the ordered autopick_clusters (arbiter.py:301,348)
    "pick_count": null,
    "reason_code": "AUTO_PICK_REDIRECT",
    "reason_operands": { "requested_lane": "src", "picked_lane": "benchmark" } },
  "reason": "auto-picked free cluster lane 'benchmark' (requested 'src' was busy)."  // CARRIED, not gated
}
```

The determinism subtlety (corrected by the same adversarial review — the first
draft misattributed it): `free_clusters` is **not** a set. It is a *list*
comprehension over the **ordered** list `autopick_clusters = list(lanes.autopick)`
(`arbiter.py:301`), filtered against the `live_lanes` set for membership only
(`_free_clusters`, `arbiter.py:347–348`; inline twins at `:765/:777`). Its output
order is the declared autopick order — deterministic by *list iteration*, not by a
`sorted()`. The set comprehensions the first draft cited (`arbiter.py:313` =
`exclusive_lanes`, `:344` = `live_lanes`) are **membership filters**, never iterated
into output; the lone `sorted({…})` (`arbiter.py:610`) feeds the *UNKNOWN_LANE
reason prose* (`Known lanes: …`), which is itself carried-not-gated. This matches
§1.3, which already stated it correctly — A.5's first draft contradicted the body.

The Go rule that falls out is still §5 rule 1, just aimed precisely: where Python's
determinism comes from **ordered-list iteration** (`free_clusters`), Go must iterate
the *same source slice in the same order* and must **never** back such a field with
a Go map (randomized); where Python's comes from `sorted()` (the UNKNOWN_LANE prose),
Go must `sort` with the same key. A field is deterministic because of *how it was
built*, and the Go port must reproduce that construction, not guess. And because the
prose is reconstructible from `reason_code` + `reason_operands`, a Python-less device
tier can render it without the prose ever being byte-frozen.

**What the five examples establish together:** the decision-bearing fields are
byte-matchable across languages with the §5 rulebook (rationals, integer
cross-multiply, collect-sort-emit, pinned encoding); the `reason` prose is *not*
(shortest-decimal float divergence on the `repr`/`%v` path, non-ASCII) and *need
not* be (no consumer parses it). That is exactly the line §2 draws — and A.1–A.2
show that drawing it anywhere else either blocks the port (over-gating the prose) or
admits a silent decision flip (under-specifying the threshold). And A.1's own
correction is the meta-lesson: the *fixed-precision* float path (`:.0%`) actually
*agrees* across Python and Go, so even the prose is matchable on some paths and not
others — which is precisely why the gate must be drawn at the decision boundary,
where the rule is clean, rather than chasing which prose happens to match. The split
is not a convenience; it is the only placement that is both achievable and safe.

---

## References

- [`100_native-spine-port-plan.md`](100_native-spine-port-plan.md) — the parent plan: the pure-decider set, the JSON envelope, the ratchet, the ship-outside-the-wheel mechanics. This note sharpens its "byte-identical" claim and reorders its early phases.
- [`122_the-core-go-runtime-and-the-on-device-kernel.md`](122_the-core-go-runtime-and-the-on-device-kernel.md) — the device synthesis: the cross-compile/FFI targets (§3 Phase 5), the §5.3 oracle-routes-around-grep ordering this plan's §4 oracle phase honours.
- [`86_the-typed-verdict-surface.md`](86_the-typed-verdict-surface.md) — the `classify(Evidence,Policy)->Verdict` contract; §2's decision-vs-reason split is its `Verdict`-has-a-typed-core-and-a-prose-rendering structure made into a parity boundary.
- `src/dos/lane_overlap.py:216–228` — the float-formatted reason strings (the §1.1 hazard, the reason §2 exists).
- `src/dos/phase_shipped.py:201`, `src/dos/stamp.py:158,465` — the three lookbehind regexes (the §1.2 RE2 blocker, scoped to the oracle cluster).
- `src/dos/arbiter.py:80–87,311,433,610` — the `to_dict` projection, the `casefold`, the `enumerate`-stabilized sort (the §1.3 matchable-with-care set).

# 100 — NSP: Native-spine port plan (the pure verdict cores → Go)

> **Status:** PLAN (not yet built — greenfield; no Go scaffolding exists in the
> tree as of 2026-06-02, 843 tests green). Supersedes the job-side `DSP` plan
> (`67_dispatch-spine-native-port-plan.md`, never ported into DOS; its `_ctx*.txt`
> scratch is gone). Re-derived against the *current* kernel by reading the
> hot-path and purity-critical code directly. Sibling to the typed-verdict
> contract ([`86`](86_the-typed-verdict-surface.md)) — this plan turns that
> contract's already-drawn `Evidence | classify | Verdict` line into a **process
> boundary**, and uses that boundary as a **quality ratchet** that freezes the
> pure core while the I/O periphery stays free to churn.

## Problem (one line)

Two problems, one boundary solves both: **(perf)** every `dos` syscall pays Python
interpreter cold-start (~80–150 ms) before any work — and `verify()` on a registry
miss pays it *twice* — so a CI gate firing dozens of parallel `dos verify` calls is
dominated by startup, not by the cheap git/regex it actually does; **(quality)**
the kernel's most load-bearing code — the verdicts a fleet's trust rests on — has
no hard line forcing it to *stop changing*, so the pure adjudication logic and the
churny I/O plumbing are free to drift together, with no mechanism asserting that a
verdict computed today is byte-identical to the same verdict a year from now.

## Goal

Reimplement the kernel's **pure verdict cores** — and *only* those — as a single
statically-linked Go binary, behind a `DOS_SPINE_NATIVE=1` flag, with Python as the
always-available fallback **and** the differential oracle. Two payoffs, ranked:

1. **Quality / stability (the deeper win).** The differential boundary makes the
   pure core a **frozen, dual-implemented contract**: a change to adjudication
   logic must now land *byte-identically in two languages and pass a cross-engine
   replay* before it ships. That cost is a feature — it converts "the core happens
   to be stable" into "the core is *mechanically held* stable while everything
   around it moves freely." See §"The boundary as a quality ratchet" below; it is
   the reason to do this even if the perf win were zero.
2. **Performance (the headline metric).** In the CI-storm regime, eliminating
   cold-start turns an est. ~1.5 s/`verify` into ~150–400 ms/`verify`. The loop and
   MCP-daemon cores come along for free.

The enabling fact: the kernel was **built port-ready and didn't know it.**
`verdict.py` already names the contract — `classify(Evidence, Policy) -> Verdict`
with *"Evidence GATHERED BY THE CALLER (no I/O inside the verdict)."* This plan
makes that boundary a language boundary: Python gathers evidence — reads git, YAML,
the clock — and hands a frozen struct to a pure Go decider that returns a verdict
struct. **Nothing about the kernel's shape changes.**

## Non-goals (the line that makes this safe, not a rewrite)

- **Do NOT port the I/O boundary.** `config`/`dos.toml` loading, `load_state`, the
  `git show`/`git log` shells, the `lane_journal` WAL, `archive_lock`'s file-lock
  CAS — these stay in Python. Reimplementing YAML/git/file-format semantics in Go
  would void the differential-test guarantee the whole port rests on. A Go binary
  *receives* resolved config + gathered evidence as JSON; it never reads the disk.
- **Do NOT port the CLI, the TUIs, the renderers, the MCP server, or any driver.**
  They are `rich`/`mcp`/provider-anchored and language-specific.
- **Do NOT byte-match `run_id`'s minter.** ID generation is intrinsically impure
  (clock + pid + entropy); port only the *parser* (`parse_run_id`, pure and
  sortable-comparison-testable) and reimplement the minter as ordinary code.
- **Do NOT port for the loop/daemon alone.** Their per-call CPU win is ms-scale
  (the cores are already pure); only the CI-storm cold-start win clears the *perf*
  bar. (The *quality* bar is cleared regardless — that's the point of goal #1.)
- **Do NOT change any Python module's public shape.** The Python kernel stays the
  executable spec; the Go binary is an optional accelerator swapped in at the call
  site, never a fork of the logic.

---

## The boundary as a quality ratchet (why this stabilizes the core)

This is the part that matters most, and it is *independent of Go's speed.* A
deterministic, dual-implemented, differentially-tested boundary does four things
that no amount of Python-only testing does:

### 1. It mechanically *freezes* the core relative to the periphery
A DOS kernel has two populations of code with opposite ideal change-rates:

- **The pure verdicts** (`arbitrate`, `is_shipped`, `liveness.classify`, …) — the
  adjudication logic a fleet's trust rests on. These *should* approach
  steady-state: a verdict that changes is a verdict downstream consumers can't rely
  on. The whole `79_primitives-not-features` thesis is that these stay small and
  still.
- **The I/O periphery** (config loaders, git shells, the WAL, renderers, drivers,
  the CLI) — these *should* keep moving: new hosts, new evidence sources, new
  output surfaces, bug-fixes in plumbing.

Today nothing enforces that split; both live in the same Python modules and change
under the same (single-language, same-author) pressure. **The port draws a physical
line between them.** Once a decider is dual-implemented, changing it is
*deliberately expensive* (two languages + a cross-engine parity gate), while
changing the periphery stays cheap (one language, no parity gate). The change-rate
asymmetry the design *wants* becomes the change-rate asymmetry the build
*enforces*. The core goes still not by exhortation but by friction applied exactly
where stillness is the goal.

### 2. A second implementation is an independent spec-check
Bugs that a single implementation can't see — an unstated assumption, a
silently-wrong default, an edge case the author and the test author *both* missed
because they share a mental model — surface the moment a *second author in a second
language* must reproduce the behavior byte-for-byte. The Go port is, in effect, a
full independent re-derivation of every verdict, graded against the Python one. The
differential corpus turns "we think this is right" into "two independent engines
agree on 843 cases + the live corpus." (This is the same logic as the kernel's own
`evidence-over-narrative` law, applied to the kernel's *own* code: don't trust one
implementation's self-report that it's correct — adjudicate it against an
independent witness.)

### 3. Determinism becomes a *checked* property, not a *claimed* one
`verdict.py` and the purity tests already *assert* the cores are pure
(`test_classify_is_pure` poisons subprocess/open/time). The differential boundary
goes further: byte-identical output across two runtimes is only *possible* if the
logic is genuinely deterministic and I/O-free — so the parity gate is a continuous,
adversarial proof of the determinism the kernel promises. Replayability
(`re-run a verdict a year later, get the same bytes` — `79 §3`) stops being an
aspiration and becomes a CI invariant.

### 4. It makes "the core changed" a loud, reviewable event
Because a core change must touch two languages and pass a new parity case, it
*cannot* slip in as an incidental diff inside a periphery PR. Every adjudication
change becomes a visible, intentional, separately-reviewed act — which is exactly
the review posture you want for the code a fleet trusts. The boundary is, in
governance terms, a **change-budget on the core**: cheap to evolve the plumbing,
expensive (and therefore scrutinized) to evolve the verdicts.

> **The synthesis:** the same property that makes a module *portable* (pure,
> deterministic, evidence-in/verdict-out) is the property that makes it *worth
> freezing*. So the port is not a detour from stability — it is the mechanism that
> *produces* stability. The boundary is where you put the ratchet.

**Design consequence carried into the plan:** treat the JSON envelope schema
(`{config, evidence, op} -> {verdict}`) as a **versioned, frozen ABI** — the
contract between the moving periphery and the still core. Schema changes are
themselves gated and versioned (Phase 4), so even the *shape* of the boundary
ratchets rather than drifts.

---

## The audit this plan rests on (evidence base)

Scored on four axes; a module is an ideal target only at their intersection.

| Axis | Why it gates a port | Method |
|---|---|---|
| **Purity** | A pure `f(data)->verdict` ports byte-for-byte and is worth freezing; an I/O-tangled one drags git/YAML/clock into Go and can't be differentially tested. | Grepped real (non-comment) `subprocess`/`read_text`/`exists`/`os.environ`/`time.*`/`open(`, then **read each file**. |
| **Hot-path criticality** | `freq × per-call-cost`. Cold-start dominates CI storms; per-call CPU dominates the daemon. | Traced `cli` → `supervise` → `oracle`/`arbiter`/`liveness` chains. |
| **Dependency self-containment** | The cut (and the freeze) is clean only if the cluster's boundary to the rest of `dos` is thin (ideally just `config` + pure seam-data). | Built the intra-package import graph. |
| **Differential-test readiness** | "Python is the spec; Go must match on the live corpus or it doesn't ship." The ratchet needs rich, pure, table-driven tests. | Counted test cases/module; classified pure-IO vs. git/fixture-coupled. |

### Ground-truthed purity (read, not inferred)

The broad grep over-counts (it matches the *word* "subprocess" in docstrings —
`loop_decide` describes the child it supervises without calling one), so every
contested module was opened and the real call sites confirmed.

**PURE-CORE — 0 real I/O lines, port + freeze as-is:**

| Module | Lines | Pure decider | Note |
|---|---|---|---|
| `arbiter.py` | 604 | `arbitrate(request, live_leases, config)` | crown jewel: state-in, decision-out |
| `_tree.py` | 103 | `prefixes_collide`, `lane_trees_disjoint` | ~50 ln glob-prefix algebra |
| `lane_overlap.py` | 197 | `overlap_verdict` | ratio-threshold comparison |
| `admission.py` | 399 | `run_predicates` + built-in DISJOINTNESS/SELF_MODIFY | predicate seam is a Protocol |
| `liveness.py` | 315 | `classify(ProgressEvidence, policy)` | purity proven by `test_classify_is_pure` |
| `scope.py` | 344 | `classify(ScopeEvidence, policy)` | same monkeypatch purity proof |
| `journal_delta.py` | 308 | `fold_since(entries, …)` | pure fold over caller-read entries |
| `loop_decide.py` | 830 | `decide(…)`, `wait_marker_budget` | every `subprocess` hit is a comment |
| `tokens.py` | 443 | `normalize_token`, `blocked_reason_for_key` | lookup tables |
| `wedge_reason.py` | 239 | `coerce`, `category_for` | closed enum + registry |
| `reasons.py` | 395 | `ReasonRegistry`, `specs_from_table` | pure stdlib |
| `stamp.py` | 912 | `parse_phase_labels`, regex builders, `to_dict`/`from_dict` | the *grammar*; the grep that uses it is in `phase_shipped` |

**PURE-WITH-IO-BOUNDARY — pure decider + a thin, named I/O shell (the high-value set, because the pure half is the hot half *and* the freeze-worthy half):**

| Module | Pure decider (PORT + FREEZE) | I/O shell (LEAVE in Python, free to churn) |
|---|---|---|
| `oracle.py` | `is_shipped`, `batch_is_shipped` — **already takes `state` + `grep_fallback` as injected hooks** (`oracle.py:729`) | `load_state*`, `default_grep_fallback_*`, footprint `git show` (`oracle.py:352,1014,1133`) |
| `picker_oracle.py` | `classify(…)` | `_load_yaml`, README/state readers (20 I/O lines) |
| `gate_classify.py` | `classify_packet`, `gate_policy`, `classify_replan_productivity` (pure) | `classify_packet_file`, `_race_envelope_for` — the `_file`-suffixed sidecar readers (`gate_classify.py:349,394`) |
| `git_delta.py` | — (it *is* the boundary) | `commits_since`, `count_commits_since` — trivial `git log` wrappers |
| `verdict.py` | the `classify`/`Verdict` Protocols (a pure contract) | 1 boundary line; not behavior |

**Intrinsic-impurity (real nuance):** `run_id.py` mints from
`time.time()`/`time.monotonic_ns()`/`os.getpid()`/`os.environ`
(`run_id.py:99,130,260`) — port the parser, reimplement the minter.
`config.py` (967 ln) is the seam by definition — never port; pass it in as JSON.

### The four clusters (where the cut — and the freeze — is clean)

The pure set has **zero** third-party imports (no yaml/rich/mcp) and **zero**
kernel→driver/scripts/MCP edges; the only shared dependency is the `config` seam,
which pulls only the two pure seam-data leaves (`reasons`, `stamp`).

| Cluster | Modules | External boundary | Clean? |
|---|---|---|---|
| **Arbiter** | `arbiter` + `lane_overlap` + `_tree` + `admission` | `config` (data only) | **9.5/10** |
| **Liveness** | `liveness` + `git_delta` + `journal_delta` | `lane_journal` consts (one-way) | **9/10** |
| **Loop** | `loop_decide` + `gate_classify`(core) + `tokens` | `liveness.Liveness` enum (read-only) | **9/10** |
| **Oracle** | `oracle` + `phase_shipped` + `stamp` + `picker_oracle` + `wedge_reason` | `config` (root + stamp grammar) | **8/10** |

### Hot path (why Go pays — and only here)

The hottest chain is **`verify()`**:

```
dos verify PLAN PHASE
  → oracle.is_shipped(cfg=…)            # pure verdict, registry-first
    → default_grep_fallback_batch(…)    # on registry miss
      → subprocess → dos.phase_shipped  # spawns a SECOND Python interpreter
        → git log + regex + plan-doc read
```

Two interpreter starts per registry-miss verify; in a CI gate the startup tax is
the dominant wall-clock and **git itself is not the bottleneck** (a couple of
`git show`/`git log` calls — `phase_shipped.py:160`, `oracle.py:352/1133`). Ranked:

| Rank | Chain | Regime | Bound by | Go win |
|---|---|---|---|---|
| 1 | `verify` → grep rung (2 interp. starts) | CI storms | **cold-start** | **large (3–10×)** |
| 2 | `arbitrate` tree-disjointness | dispatch/MCP loop | per-call CPU | modest (~10×, ms-scale) |
| 3 | `liveness` (after `git_delta`) | supervisor loop | git subprocess | modest (git unchanged) |
| 4 | `loop_decide`/`supervise` | supervisor loop | per-call CPU | small (already cheap) |

### Differential-test readiness (the ratchet needs this)

843 tests, 0.70 s collect. Candidate modules:

| Module | Test file (ln) | Shape | Ready? |
|---|---|---|---|
| `arbiter` | `test_arbiter.py` (340) | pure → exact verdict, ~28 cases | **A+** |
| `admission` | `test_admission.py` (645) | pure predicate assertions | **A+** |
| `lane_overlap`+`_tree` | `test_lane_overlap.py` (195, ~28) | exact closed-enum, edge-heavy | **A+** |
| `journal_delta` | `test_journal_delta.py` (368, ~18) | pure fold on frozen dicts | **A+** |
| `liveness` | `test_liveness.py` (463) | 7 pure litmus + CLI | **A** |
| `scope` | `test_scope.py` (210, ~15) | pure ladder on frozen evidence | **A** |
| `loop_decide` | `test_oracle_and_loop.py` (393) | pure state-machine | **A** |
| `oracle` | `test_oracle_and_loop.py` | pure core, injected grep | **A** (pure half) |
| `stamp` | `test_stamp_*` (718) | data pure; grep rung uses git repos | **C** (port data layer only) |
| `gate_classify` | thin direct; via `loop_decide` | core under-tested directly | **B** — corpus first |
| `picker_oracle` | lockstep enum only | **no behavioral tests** | **D** — corpus first |
| `git_delta` | indirect, live-git | — | **D** — it's a seam, wrap not port |

---

## Architecture of the port

```
  ┌──────────────── Python (the moving periphery — free to churn) ─────────┐
  │ cli.py / dos_mcp / drivers                                             │
  │   ├─ resolve SubstrateConfig  ─┐                                       │
  │   ├─ gather Evidence (git log, │  serialize to JSON  (the FROZEN ABI)  │
  │   │  state YAML, journal, clock)│                                      │
  │   └─ call spine ───────────────┴──────────┐                           │
  └────────────────────────────────────────────│──────────────────────────┘
                                                │ stdin: {config, evidence, op}
                       DOS_SPINE_NATIVE=1?      ▼
        ┌──────────── dos-spine (Go, static — the STILL core) ──────────┐
        │  pure deciders, NO I/O — dual-implemented + parity-gated:      │
        │   arbitrate · overlap · tree · predicates                      │
        │   liveness.classify · journal fold                             │
        │   loop.decide · gate_policy · tokens                           │
        │   is_shipped · stamp grammar · picker.classify                 │
        └────────────────────────────────│──────────────────────────────┘
                                          │ stdout: {verdict}  (frozen struct)
                                          ▼
                          Python renders / acts (unchanged)
```

- **The seam is JSON over stdin/stdout** — a **versioned, frozen ABI**, the
  contract between the moving periphery and the still core. It mirrors how
  `dos_mcp` already passes `cfg=` explicitly into each syscall — no process-global
  state, correct for the concurrent-workspace MCP case.
- **The Go binary is stateless and pure**: no file reads, no git, no clock (except
  where a verb's evidence legitimately *is* the clock, in which case `now_ms`
  arrives in the evidence struct, exactly as `liveness`/`scope` already require).
- **Fallback is structural**: absent the flag (or on any spine non-zero exit /
  schema-mismatch / missing binary), Python runs the original decider. The native
  path can never be the *only* path.

---

## The differential-test harness (the ratchet mechanism; gates every phase)

This is the load-bearing mechanism for *both* goals; build it in Phase 0.

1. **Corpus export.** A `pytest` fixture/CLI dumps every pure-decider test case as
   a JSON record `{op, config, evidence, expected_verdict}` — sourced from the
   existing A/A+ tables, so the corpus *is* the current suite, not a new spec.
2. **Replay both engines.** A harness feeds each record to (a) the Python decider
   and (b) `dos-spine`, asserting byte-identical `to_dict()` output. Any divergence
   fails CI and **blocks the native path for that op**.
3. **Live-corpus shadow.** In a real repo, run `verify`/`arbitrate` through *both*
   engines and diff (the "live corpus" half of the discipline) — catches cases the
   unit tables miss. Logged, not fatal, until parity is established; then promoted
   to fatal.
4. **Gate per-op, not per-binary.** Each verb flips to native independently only
   once its corpus is 100% green on both unit + shadow. A laggard op
   (`picker_oracle`) never holds back a ready op (`arbitrate`).
5. **(Quality use, even without the flag)** Run the dual-engine replay in CI as a
   *standing parity check* on the core. This is the ratchet: any PR that changes an
   adjudication path fails unless the change is reproduced in both engines + a new
   parity case is added. The harness is therefore valuable *before* anyone enables
   the native path in production — it is the freeze enforcer first, the accelerator
   second.

---

## Phased roadmap

### Phase 0 — Harness + corpus + precursor tests *(prereq for everything; ships the ratchet)*
**Build:**
- The JSON corpus exporter + dual-engine replay harness above.
- **Write the missing corpora** that block ports *and* the freeze: table-driven
  tests for `gate_classify`-core (lift the `loop_decide` exercises into direct
  `classify_packet`/`gate_policy` tables) and `picker_oracle.classify` (currently
  only a lockstep enum check → needs behavioral input→verdict cases).
- A stub `dos-spine` Go binary: reads the JSON envelope, dispatches on `op`,
  returns `{"error":"unimplemented"}` for every op. Wire the Python call site +
  `DOS_SPINE_NATIVE` flag + structural fallback now, so later phases only fill in
  deciders.

**Exit gate:** harness runs green against the all-unimplemented binary (fallback +
schema round-trip work); `gate_classify`-core + `picker_oracle` are now A-grade.
*Quality milestone reached here:* the corpus + replay harness already raise the
core's coverage and pin its determinism, independent of any Go decider existing.

### Phase 1 — Arbiter cluster *(proof-of-concept; cleanest cut; first frozen cluster)*
**Port + freeze:** `arbitrate` + `overlap_verdict` + `_tree` algebra +
`run_predicates` (built-in DISJOINTNESS + SELF_MODIFY). Pure, fundamental, A+
tested, and useful standalone ("the fastest file-region lock manager for task
scheduling").
**Why first:** highest test confidence, zero I/O shell, smallest surface — proves
the harness, the seam, and the ratchet end-to-end before the fiddlier oracle work.
**Exit gate:** all `test_arbiter.py` + `test_admission.py` + `test_lane_overlap.py`
cases byte-match across engines; `dos arbitrate`/`dos lease-lane`/MCP
`dos_arbitrate` run native behind the flag with green shadow diff; the arbiter
cluster is now **change-budgeted** (edits require a parity case).

### Phase 2 — Liveness + Loop clusters *(the daemon cores)*
**Port + freeze:** `liveness.classify` + `journal_delta.fold_since`;
`loop_decide.decide` + `gate_policy` + `tokens`. Git/journal reads stay Python
(evidence in the envelope).
**Why second:** A-tested and orthogonal to the arbiter; lights up the supervisor
loop / `dos top` / MCP `dos_liveness` native path (perf Win B, free).
**Exit gate:** `test_liveness.py` (7 pure litmus) + `test_journal_delta.py` +
`test_oracle_and_loop.py` loop cases byte-match; `dos liveness` native green.

### Phase 3 — Oracle decider *(the headline: claim perf Win A)*
**Port + freeze:** `is_shipped`/`batch_is_shipped` + the `stamp` grammar
(regex/parse) + `picker_oracle.classify`. The git grep + state-YAML read stay
Python and feed the decider via the envelope; the Go binary owns only the
registry-first verdict logic and the stamp matching.
**Why last:** the I/O shell is the most reference-app-shaped and `stamp`'s grep rung
is only C-grade for differential testing — so its *shell* needs the most care and
`picker_oracle` needs Phase 0's new corpus. **This is the phase that eliminates the
second interpreter start and claims the CI-storm win.**
**Exit gate:** `test_oracle_and_loop.py` oracle cases + `test_stamp_convention.py`
data round-trips + the new `picker_oracle` corpus byte-match; a CI-storm benchmark
shows the targeted per-`verify` wall-clock drop with shadow diff clean.

### Phase 4 — Hardening + ABI freeze + rollout
- Promote live shadow-diff from advisory to fatal once parity has soaked.
- **Freeze the envelope ABI**: version it, add a schema-compat test, and document
  that schema changes are gated like core changes (the boundary itself ratchets).
- Build/release: a `dos-spine` build step (CI matrix for host OSes — Windows is the
  primary dev platform here), shipped *outside* the wheel (a Go binary is not
  Python package-data; distribute via release artifacts, resolved by path like any
  driver, with Python fallback when absent).
- Document the flag + fallback in `QUICKSTART.md`; add a `dos doctor` line
  reporting whether the native spine is present and parity-clean.

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Go decider diverges from Python on an edge case | med | high | the harness — per-op gate, byte-match on unit **+** live shadow; native is never the only path |
| Reimplementing YAML/git/regex in Go reintroduces I/O semantics | low | high | **non-goal**: those stay Python; Go gets a frozen envelope, never the disk |
| `stamp`/`picker_oracle` thin coverage hides a behavioral gap | med | med | Phase 0 writes the corpus *before* Phase 3 ports them |
| The dual-implementation tax slows *legitimate* core evolution | med | med | that friction is the **intended** ratchet (§quality); keep it cheap for the periphery, so only true adjudication changes pay it |
| Build/ship complexity (a compiled binary in a near-stdlib Python project) | med | med | ship outside the wheel as a release artifact; Python fallback means a missing binary degrades, never breaks |
| Port chases the wrong regime (loop/daemon, not CI) | low | med | the *perf* bar is **Win A**; Phase 3 exit gate is a CI-storm benchmark, not a microbench |
| Regex dialect mismatch (Python `re` vs Go RE2) in `stamp` | med | med | RE2 lacks backrefs/lookaround — audit `stamp`'s patterns in Phase 0; if any use unsupported features, keep that rung in Python and port only the rest |

---

## Exit criteria (whole plan)

1. **Quality:** the dual-engine parity check runs in CI as a standing invariant; a
   change to any ported decider fails unless reproduced byte-identically in both
   engines with a new parity case. The pure core is demonstrably *change-budgeted*.
2. **Perf:** `DOS_SPINE_NATIVE=1` runs `verify`, `arbitrate`, `liveness` (and their
   MCP tools) through `dos-spine` with byte-identical verdicts vs. Python on the
   full unit corpus **and** a clean live shadow diff; a CI-storm benchmark shows a
   material per-`verify` wall-clock reduction.
3. **No regression:** the 843-test Python suite is unchanged and green — the spec
   did not move; only an optional accelerator + a parity ratchet were added beside
   it. With the flag off (or the binary absent), behavior is byte-identical to today.

---

## What would make this a mistake (restated — it's the whole discipline)

- Porting `config` or any YAML/git reader → reimplements file-format/git semantics
  in Go and **voids** the differential guarantee (and so the freeze).
- Porting for the loop/daemon perf alone → that win is ms-scale; only the CI-storm
  cold-start win clears the *perf* bar.
- Porting `picker_oracle`/`gate_classify`-core **before** their corpora exist → you
  can't prove equivalence, which nullifies both the accelerator and the ratchet.
- Letting core changes ride in as incidental diffs → defeats the entire point of
  goal #1; the parity gate exists precisely to make that impossible.

---

## See also

- [`86_the-typed-verdict-surface.md`](86_the-typed-verdict-surface.md) — the
  `classify(Evidence, Policy) -> Verdict` contract this plan turns into a process
  boundary and a freeze line.
- [`79_primitives-not-features.md`](79_primitives-not-features.md) — why the
  deciders are small and *should* stop changing (the stability this plan enforces).
- [`CLAUDE.md`](../CLAUDE.md) — the layering table; the pure set above is exactly
  the "Kernel (mechanism)" row **minus its I/O-gathering helpers**.

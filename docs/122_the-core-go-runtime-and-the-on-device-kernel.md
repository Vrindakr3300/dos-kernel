# 122 — The core Go runtime and the on-device kernel: the same project from two ends

> **Two prior notes circle the same artifact without naming it. [`100`](100_native-spine-port-plan.md)
> (NSP) reimplements the kernel's pure verdict cores as a static Go binary — and
> justifies it on *datacenter* grounds (CI-storm cold-start, a quality ratchet),
> explicitly ruling the loop/daemon perf win "too small to clear the bar" and
> never once saying the word *device*. [`121`](121_first-class-on-devices-and-unattended.md)
> argues DOS is *least* finished exactly where it matters *most* — the
> unattended, on-device agent — and §8 concedes "don't port the git-backed kernel
> onto an MCU." Put the two together and the gap closes: the thing NSP built for
> speed in the datacenter is the *only* thing that makes the on-device kernel
> physically deployable, because the constraint at the edge is not CPU — it is
> that **a CPython interpreter does not ship to a phone, and a 6 MB static Go
> binary cross-compiles to `arm64-android` / `arm64-ios` / `riscv` / WASM with no
> runtime at all.** The device regime also *resurrects* the very perf win NSP
> dismissed: cold-start that is a rounding error in a datacenter is a battery and
> a wake-lock on an MCU. This note is the synthesis neither parent makes — that
> the Go core is not a datacenter optimization that *might* help at the edge, but
> the load-bearing enabler of [`121`](121_first-class-on-devices-and-unattended.md)
> §8's "local non-forgeable rung for the offline window."**

Status: theory + spec note, fusing [`100`](100_native-spine-port-plan.md) (the
Go port) and [`121`](121_first-class-on-devices-and-unattended.md) (the device/
unattended axes). §1 names the gap between the two parents. §2 is the deployability
argument (why Python is the actual blocker and Go the actual fix). §3 re-derives the
perf case NSP dismissed, for the edge regime. §4 is the runtime tier-map (what runs
on a watch vs a phone vs a Pi vs a server, and which seam degrades where). §5 is the
buildable delta on top of NSP + the §5/§6 seams of 121. §6 steelmans "WASM/Rust
instead" and "no on-device kernel at all" (the latter inherited from 121 §8). §7 is
the litmus set. Nothing here is built; it composes two unbuilt plans into one
buildable ordering.

The positioning half — *why edge agents are a market a trust kernel should own* —
stays in [`dos-private`](../../dos-private) (CLAUDE.md: how-a-module-behaves →
`dos/docs`; why-it-matters → `dos-private`). This is the mechanism half.

---

## 1. The gap between the two parents

[`100`](100_native-spine-port-plan.md) and [`121`](121_first-class-on-devices-and-unattended.md)
were written days apart and never reference each other. Read side by side they
leave a precise hole:

| | NSP ([`100`](100_native-spine-port-plan.md)) | Devices ([`121`](121_first-class-on-devices-and-unattended.md)) |
|---|---|---|
| **What it builds** | the pure verdict cores as a static Go binary, behind `DOS_SPINE_NATIVE=1` | the `EvidenceSource` / `DurableLog` seams so ground-truth + durability stop assuming a capable host |
| **What it optimizes for** | datacenter CI storms (cold-start) + a quality ratchet | the unattended, offline, on-device agent — maximal blast radius, no human |
| **Its stance on the *other's* domain** | "**Do NOT port for the loop/daemon alone** … only the CI-storm cold-start win clears the *perf* bar" (non-goal) | §8: "the objection correctly kills *port the git-backed kernel onto an MCU*" |
| **The word it never says** | *device*, *phone*, *edge*, *battery*, *ARM* | *Go*, *binary*, *interpreter*, *cross-compile* |

Each ruled out the other's territory **for reasons that are correct in
isolation and wrong in composition**:

- NSP dismissed the loop/daemon perf win because, *on a server*, the cores are
  already cheap and cold-start is amortized by a long-lived process. True there.
  On a battery-powered device woken to adjudicate one verdict and then put back to
  sleep, there is no long-lived process to amortize against — every verdict pays
  cold-start, and cold-start is measured in joules, not milliseconds (§3).
- 121 §8 killed "the git-backed kernel onto an MCU" — but it was killing a
  *strawman*: the *full* kernel, with `git` and `fsync` and a CPython runtime.
  121's own §5/§6 already replace `git` and `fsync` with seams. What 121 never
  asked is *what language the seam-bearing, git-free, fsync-free residual core is
  written in* — and that residual is exactly NSP's pure-decider set, which NSP
  already proved ports to Go byte-for-byte.

**The synthesis: NSP's frozen Go ABI core + 121's seams are the same artifact.**
NSP says *the pure cores port to a static binary with no third-party imports and a
JSON envelope ABI.* 121 says *on a device, ground-truth and durability must be
seams, and the offline window needs a local non-forgeable rung.* Stack them: a
static Go binary that runs the pure verdicts, takes evidence through 121's
`EvidenceSource` seam and writes through 121's `DurableLog` seam, and ships to an
edge target with no interpreter. That is **the on-device kernel** — and neither
parent describes it because each stopped at its own boundary.

## 2. The real blocker at the edge is the interpreter, not the CPU

121 §2 correctly named the two assumptions that break on a device (git-as-truth,
fsync-as-durability) and §5/§6 sketched the seams that fix them. But it left
*unstated* the most basic deployment fact, the one that makes the seams moot if
unaddressed:

> **You cannot `pip install` onto a phone.** A CPython runtime + the `dos` package
> + PyYAML is not a thing that ships inside an Android app, an iOS app, a robot's
> firmware image, a browser tab, or a 256 MB-RAM MCU. The kernel could have
> perfect `EvidenceSource`/`DurableLog` seams and *still* not run there, because
> the **host language** doesn't fit.

This is the blocker NSP already solved without realizing it was solving a *device*
problem. The relevant properties of the NSP artifact, re-read through the edge lens:

| NSP property (datacenter rationale) | Same property, edge rationale |
|---|---|
| "a single statically-linked Go binary" (perf: one process, no import graph) | a single static binary is the *only* deployable unit on a target with no package manager — `CGO_ENABLED=0 GOOS=android GOARCH=arm64 go build` produces a ~5–10 MB file with zero runtime deps |
| "the pure set has **zero** third-party imports (no yaml/rich/mcp)" (clean cut) | zero third-party imports = nothing to vendor onto the device; the heavy `rich`/`mcp`/PyYAML surface stays server-side where it belongs |
| "JSON over stdin/stdout — a versioned, frozen ABI" (mirrors `dos_mcp` cfg-passing) | a JSON envelope over a pipe / FFI boundary / `postMessage` is *exactly* how a host app (Kotlin, Swift, JS, C) calls into an embedded decider — the ABI is host-language-agnostic by construction |
| "the Go binary is stateless and pure: no file reads, no git, no clock" (purity) | a stateless pure decider needs no filesystem, no `subprocess`, no `fork` — the three things 121 §2 said a device may lack. **NSP's purity discipline is 121's portability requirement, already enforced.** |
| Go cross-compiles trivially (`GOOS`/`GOARCH`); can emit WASM (`GOOS=wasip1`) | the one runtime that targets phone + embedded + browser sandbox from one source, statically, with a GC tuned for small heaps |

The punchline: **the discipline NSP imposed for the *quality ratchet* — pure,
deterministic, evidence-in/verdict-out, zero deps — is identical to the discipline
a runtime needs to *fit on a device*.** 121 §3 already noticed the parallel one
level up ("the same property that makes a module *portable* is the property that
makes it *worth freezing*"); this note observes that NSP *did the port*, and the
port's output is the edge runtime. The freeze-worthy core and the device-deployable
core are the same bytes.

### 2.1 Why not just keep Python and use a Python-on-mobile runtime?

The honest alternative: Pyodide (CPython→WASM), BeeWare/Briefcase, Kivy,
Chaquopy (CPython-in-an-APK). They exist; they work; people ship apps with them.
They are the *wrong* tool here for three reasons specific to a **trust kernel**:

1. **Size and cold-start.** A CPython-in-WASM payload is 5–10 MB *compressed of
   interpreter alone* and cold-starts in hundreds of ms to seconds — before any
   verdict. A static Go decider is comparable in size but cold-starts in
   single-digit ms and runs the verdict in microseconds. On a device the kernel is
   woken *often and briefly* (adjudicate, sleep), which is the worst case for an
   interpreter and the best case for a static binary (§3).
2. **The dependency surface is the attack/bloat surface.** A trust kernel's whole
   pitch is *small, deterministic, near-stdlib*. Dragging a full CPython +
   `importlib` + the stdlib onto a device to run ~3 k lines of pure verdict logic
   inverts that — the runtime dwarfs the kernel. NSP's "zero third-party imports"
   cut is what keeps the *shipped* surface proportional to the *logic*.
3. **The ratchet is already there.** Choosing Python-on-mobile forfeits NSP's
   differential-parity guarantee for free — you'd be running the *same* Python
   logic, so there's no second implementation pinning determinism. Choosing Go
   *gets the device runtime and the quality ratchet from one effort*. The two
   payoffs NSP ranked (quality #1, perf #2) gain a third — deployability — at no
   additional porting cost, because it's the *same* port.

So the Go core is not "an optimization we could also do in Python on mobile." It is
the choice that makes the device case *and* the ratchet *and* the CI-storm win one
artifact instead of three.

## 3. The perf win NSP dismissed, re-derived for the edge

NSP's risk register lists "Port chases the wrong regime (loop/daemon, not CI)" and
its non-goals say "Do NOT port for the loop/daemon alone — that win is ms-scale."
**Both judgements are correct for a server and invert for a battery.** The variable
NSP didn't have in scope is *energy per wake*, and on a device it dominates.

| Regime | Process model | What cold-start costs | NSP's call | Edge correction |
|---|---|---|---|---|
| CI storm (datacenter) | N short-lived `dos verify` | wall-clock; the headline | **port (Win A)** | unchanged — still true |
| Supervisor loop (server) | one long-lived process | amortized to ~0 over the run | **don't bother** | true *on a server* |
| **On-device adjudication** | **woken per-verdict, then sleeps** | **a full interpreter spin-up per wake = CPU cycles drawn from a battery + a wake-lock held longer** | (out of scope) | **port is the point** — the loop/daemon regime NSP dismissed *is* the device regime, and at the edge its win is energy, not ms |

The mechanism: a device agent's runtime shape is *not* "one long-lived loop" (that
drains the battery by staying resident) — it is "wake on an event, adjudicate,
emit, sleep." Every wake that has to cold-start CPython pays the ~80–150 ms NSP
measured **as joules off a battery and as milliseconds of held wake-lock**, on a
duty cycle that may repeat thousands of times a day. A static Go decider that
cold-starts in single-digit ms and returns in microseconds turns each wake from a
visible power event into a negligible one. The same number NSP called "too small to
matter" (per-call CPU) is, multiplied by a battery constraint and a high wake count,
the difference between an agent that can run unattended for a day and one that
can't.

So the regime NSP explicitly de-scoped is the regime this note re-scopes *in* — not
by disputing NSP's datacenter measurement, but by changing the cost function from
*wall-clock* to *energy × wake-count*, which only appears at the edge.

## 4. The runtime tier-map — what fits where, and which seam degrades

The device axis is not one target; it is a gradient, and the kernel should degrade
*honestly* along it (the 121 discipline: a swapped witness can only abstain-more,
never trust-more). One static Go core; the **seams** (`EvidenceSource`,
`DurableLog`, from 121 §5/§6) pick the rung available at each tier.

| Tier | Example target | Go core runs? | Strongest `EvidenceSource` available (121 §3.1) | `DurableLog` (121 §6) | Honest verdict floor |
|---|---|---|---|---|---|
| **Server / workstation** | Linux box, CI runner | yes (also the Python spec) | **git** (the unforgeable VCS rung) | `fsync` POSIX JSONL | full — today's behaviour |
| **Edge server / Pi-class** | factory Pi, NUC, on-prem gateway | yes, native | git *or* remote commons append-log | `fsync` POSIX JSONL | full |
| **Phone (mostly online)** | Android/iOS app agent | yes (static `arm64` lib via FFI) | **remote commons append-log** (121 §3.1 #1) — the deferred-client steady state (121 §8) | IndexedDB-class KV / remote append-log | full *while online*; reconciles on reconnect (121 §4.3) |
| **Phone / robot (long-offline window)** | autonomous field robot, offline mobile agent | yes | **local non-forgeable rung** — OS exit-code (121 §3.1 #3) / content-hash (#4) / TEE signature (#2) | local KV / flash ring, projected to commons on reconnect | **bounded** — a local rung attests *an effect of content X occurred*, not *that it was the right effect* (121 §10 intent residue persists) |
| **MCU / deeply embedded** | microcontroller, no MMU | core *subset* only (arbiter + liveness fit; oracle's stamp regex may not — see RE2/§6.1) | content-hash (#4) or attestation (#2); no git, no network assumed | flash ring | **narrow** — only the verdicts whose deciders fit; the rest abstain (`via none`) honestly |
| **Browser sandbox** | extension / web-app agent | yes (WASM, `GOOS=wasip1`/`js`) | remote commons (the page can `fetch` the witness it can't rewrite) | IndexedDB | full while online; no local FS, so offline durability is the KV store |

Two properties make this a *map* and not a *fork*:

1. **One core, many rungs.** The Go binary is identical across tiers; only the
   injected `EvidenceSource`/`DurableLog` change. This is the 121 §5 promise
   (discovery at the boundary, handed to a pure classifier as facts) realized — the
   *boundary* is now also the language boundary, so the per-tier wiring lives in the
   host-language shim (Kotlin/Swift/JS/C), never in the verdict.
2. **The floor only ever tightens going down the table.** Every tier's verdict is
   AND-ed under the strongest *available verified* source (121 §5's
   `believe ⟺ some non-forgeable source attests`, the dual of
   `admissible_under_floor`). A weaker tier can only make `verify` *abstain more*
   (`via none`), never fabricate a SHIPPED. That is what makes shipping the *same*
   core to a watch and a server safe: the watch can't lie harder than the server
   can; it can only know less, and say so.

## 5. The buildable delta (on top of NSP + 121 §5/§6)

Almost everything is already specced in the two parents. This note adds the
*ordering* and the small connective tissue that makes the Go core a device runtime
rather than a datacenter accelerator. Nothing here contradicts NSP's non-goals — it
**extends the build targets and the injection points**, not the ported logic.

### 5.1 What is reused verbatim
- **The pure-decider port** (NSP Phases 1–3): `arbitrate` + overlap + tree +
  predicates; `liveness.classify` + `journal_delta.fold_since`; `loop_decide.decide`
  + `gate_policy` + `tokens`; `is_shipped` + `stamp` grammar + `picker_oracle`. The
  edge runtime ports *the same set*, in the same dependency-clean clusters.
- **The JSON envelope ABI** (NSP architecture): `{config, evidence, op} -> {verdict}`,
  versioned and frozen. On a device this is the FFI / `postMessage` / pipe payload.
- **The differential-parity harness** (NSP Phase 0): the device build is gated by
  the *same* corpus — a verdict on a phone must byte-match the Python spec, or the
  device path for that op stays dark. The ratchet that freezes the core *is* the
  thing that lets you trust a verdict computed on hardware you can't attach a
  debugger to.
- **The `EvidenceSource` / `DurableLog` seams** (121 §5/§6): unchanged contracts.
  The Go core takes `EvidenceFacts` in the envelope and emits records the host's
  `DurableLog` driver persists.

### 5.2 The connective delta (new, small)
1. **Cross-compile + embed targets in the build matrix.** NSP Phase 4 already plans
   a `dos-spine` build step "shipped outside the wheel, resolved by path like any
   driver." Extend the matrix from {host OSes} to {`linux/amd64`, `linux/arm64`,
   `android/arm64`, `darwin/arm64` (iOS via c-archive), `wasip1/wasm`}. Add a
   `c-archive` / `c-shared` build mode so a host app links the core as a static lib
   and calls it over FFI, not only as a subprocess (a phone app can't `fork` a
   subprocess; it calls a function).
2. **Two invocation shapes, one core.** NSP assumed stdin/stdout (a subprocess). Add
   an in-process entry: `dos_spine_decide(op, json_in) -> json_out` exported via
   cgo (`//export`) for FFI and as the WASM export. Same dispatch, same envelope;
   the transport is the host's. This is the only genuinely new *code* shape, and it
   is a thin wrapper over the existing dispatcher.
3. **The seam drivers are host-language, not Go.** A `RemoteLogEvidenceSource` on
   Android is Kotlin calling the commons; on iOS it's Swift; in a browser it's JS
   `fetch`. The Go core never grows them — it receives their *output* as
   `EvidenceFacts` in the envelope, exactly as the server-side Python boundary does.
   This keeps the 121 "kernel imports no evidence driver" litmus true *across
   languages*: the device's evidence drivers are as out-of-kernel as `llm_judge`.
4. **A `dos doctor`-equivalent for the tier.** The host shim reports which rung is
   live (git / commons / OS-exit / content-hash / none) and which `DurableLog` is
   backing it — the device analogue of 121's "operator surface says *cannot
   establish here*." On a phone this is a debug screen; the point is the same: the
   tier's *honesty floor* is visible, not hidden.

### 5.3 Build/freeze ordering (concrete)
- **Phase A — ride NSP.** Do nothing device-specific until NSP Phase 1 (the arbiter
  cluster) is byte-parity green. The arbiter is the cleanest cut *and* the most
  useful standalone edge verb ("the fastest file-region lock manager," NSP Phase 1)
  — a robot coordinating effects across its own subsystems wants exactly this,
  offline, with no git.
- **Phase B — add the embed targets** for the arbiter cluster only: cross-compile
  matrix + the cgo/WASM entry (§5.2 #1–#2). Prove `arbitrate` runs on an
  `android/arm64` build with byte-parity against the Python spec on the NSP corpus.
  This is the smallest end-to-end proof that the device runtime is real.
- **Phase C — liveness + loop clusters** (NSP Phase 2) on the edge targets — the
  verdicts an *unattended* agent leans on most (is it advancing? should it
  self-stop?). Pair with 121 §4's fail-closed defaults so an offline agent that
  can't reach a human refuses into a durable record rather than proceeding.
- **Phase D — oracle decider** (NSP Phase 3) on the edge, gated on the RE2 audit
  (§6.1): if `stamp`'s regex uses lookaround/backrefs, the oracle's grep rung stays
  Python/server-side and the *device* `verify` answers from the remote-commons or
  content-hash `EvidenceSource` instead — which is the 121 §3.1 ordering anyway
  (the strongest witness is remote, not a local grep).

## 6. Steelmen

### 6.1 "Use Rust/WASM, not Go"
Rust produces smaller, GC-free binaries and is the conventional pick for the
tightest embedded targets; WASM is the browser-and-sandbox lingua franca. The
counter is *NSP already chose Go and built the differential discipline around it* —
re-choosing the language reopens a settled, working decision and forfeits the
"one port, three payoffs" property of §2.1. Go cross-compiles to WASM
(`GOOS=wasip1`) and to static `c-archive` libs for FFI, which covers the browser and
the phone; its GC is tunable (`GOGC`, `GOMEMLIMIT`) for small heaps. The honest
residue: on a *deeply* constrained MCU (no MMU, tens of KB RAM) Go's runtime+GC may
not fit, and **that tier is exactly where §4 already says only a verdict *subset*
runs** — so the gap is acknowledged, not papered over. Rust would buy that bottom
tier at the cost of a second implementation language and a fork of the ratchet.
Decision: Go for everything the tier-map covers; revisit Rust *only* for the
MCU-subset tier, and only as a *third* differentially-tested engine (the ratchet
extends to it), never as a fork. **Plus**: the one regex concern (RE2 lacks
backrefs/lookaround) is NSP's own Phase-0 audit item — it bites the *oracle's stamp
grammar* identically in datacenter Go and edge Go, so it is not a new edge risk.

### 6.2 "No on-device kernel at all — defer everything to the server" (inherited from 121 §8)
121 §8 already adjudicated this and the answer stands, now sharpened by the runtime
question. The deferred-client model (device reports; server's git-backed kernel
adjudicates) is the right *steady state* for a mostly-online device and needs no Go
core — the Python server kernel suffices, the device is a dumb reporter. **But the
long-offline window is a trust vacuum** (121 §8): between disconnect and reconnect
the agent acts with no referee present, scoring maximal on both 121 axes. To put
*any* non-self-report rung in that window you need a decider running *on the
device* — and a decider on the device is a runtime question, which is this note. So
§6.2 doesn't dispute §8; it supplies §8's missing half: *the local non-forgeable
rung 121 §8 demanded for the offline window is only real if something can run the
verdict locally, and the static Go core is that something.* The deferred-client
model is the steady state; the Go core is what keeps the offline interval from
being open-loop.

### 6.3 "The kernel's verdicts need git; a phone has no git, so the core is useless there"
This is the 121 §2 worry, and §3 of 121 already answered it: *git is one
`EvidenceSource`, not the contract.* The Go core doesn't embed git; it takes
`EvidenceFacts` through the seam. On a device the facts come from the remote commons
(#1), the OS exit-code (#3), or a content-hash (#4) — and where only the forgeable
floor exists, the verdict honestly returns `via none`. The core is not "useless
without git"; it is *as useful as the strongest witness the tier can produce, and
honest about the ceiling* — which is strictly the 121 §5 floor discipline, now
running on the device instead of the server.

## 7. Litmus tests (acceptance gates)

Each extends an NSP or 121 gate to the edge; all are byte-parity or honesty
properties, the same shape as the existing seam tests.

- **`test_spine_arm64_byte_parity`** — the `android/arm64` (and `wasip1`) build of
  the arbiter cluster produces byte-identical verdicts to the Python spec on the
  full NSP corpus. (NSP's parity gate, run on the cross-compiled target — the
  device path for an op stays dark until this is green.)
- **`test_spine_no_io_on_device`** — the device build performs no filesystem, no
  network, no clock read inside a verdict; all such facts arrive in the envelope.
  (NSP's `test_classify_is_pure`, re-asserted for the FFI/WASM entry point — purity
  is what makes the core fit a sandbox.)
- **`test_tier_floor_only_tightens`** — for every tier in §4, a verdict is AND-ed
  under the strongest available verified `EvidenceSource`; a weaker tier can only
  return `via none` where a stronger tier returns SHIPPED, never the reverse.
  (121 §5's `believe ⟺ non-forgeable attests`, proven across the tier-map.)
- **`test_offline_window_has_a_local_rung`** — on the long-offline tier, with no git
  and no network, a content-hash / OS-exit `EvidenceSource` yields a non-`via-none`
  verdict for an effect it can attest, and `via none` for one it cannot — proving
  the offline window is not a pure self-report vacuum (the 121 §8 requirement, made
  executable).
- **`test_reconnect_reconciles_device_ledger`** — a device's local `DurableLog`,
  reconnected, reconciles against the commons via `reconcile_plan` (121 §7):
  CONFIRMED / DIVERGED / CONFLICTED, residual = `declared − verified`, never the
  device's narration. (121 §4.3, with the durable log being the on-device one.)
- **`test_host_shim_imports_no_kernel`** — the device evidence/durable drivers
  (Kotlin/Swift/JS) feed the core through the envelope and are never linked *into*
  the Go core; the core ships no ruling `EvidenceSource`. (121's
  `test_kernel_imports_no_evidence_driver`, extended across the language boundary —
  the cross-language form of "kernel imports no driver.")
- **`test_python_spec_unchanged`** — the entire device effort adds build targets and
  an FFI entry point; it changes *no* Python module's public shape and the full
  Python suite stays green. (NSP exit criterion #3 — the spec did not move; a new
  deployment target was added beside it.)

## 8. What this note claims, and what it does not

- **Does claim:** NSP ([`100`](100_native-spine-port-plan.md)) and the device note
  ([`121`](121_first-class-on-devices-and-unattended.md)) describe one artifact from
  two ends (§1); the actual edge blocker is the CPython runtime, not the CPU, and
  NSP's zero-dep static Go core is the deployable fix — *and* simultaneously the
  quality ratchet *and* the CI-storm win, from one port (§2). The loop/daemon perf
  win NSP de-scoped reappears at the edge as energy-per-wake (§3). One core degrades
  honestly across a tier gradient, with the 121 floor guaranteeing a weaker tier can
  only abstain more (§4). The build is mostly NSP + 121 §5/§6 with a small
  cross-compile/FFI delta and a build ordering (§5).
- **Does not claim:** that the *full* kernel runs on an MCU (§4 and §6.1 concede
  only a verdict *subset* fits the smallest tier), that Go is provably the only
  right language (§6.1 leaves Rust open for the MCU tier as a third ratchet engine),
  that a local rung *solves* offline trust (§6.3 inherits 121 §10's intent residue —
  a content hash attests *that an effect occurred*, not *that it was the right
  one*), or that any of this is built (it composes two unbuilt plans). The device
  runtime *bounds* the offline trust vacuum; it does not eliminate the intent gap a
  human would have closed.

The meta-answer: **DOS runs on a low-power device the moment its pure verdict cores
are a static binary instead of a Python package — and NSP already proved that port
is clean, byte-parity-testable, and zero-dependency. The Go core was specced as a
datacenter accelerator; read against the device note it is the on-device kernel's
runtime, the thing that turns 121's "local non-forgeable rung for the offline
window" from a contract into a binary that fits on a phone.**

---

## References

*The two parents this note fuses:*
- [`100_native-spine-port-plan.md`](100_native-spine-port-plan.md) — the pure-decider Go port, the JSON envelope ABI, the differential-parity ratchet, the cross-compile/ship-outside-the-wheel plan (§5 reuses all of it).
- [`121_first-class-on-devices-and-unattended.md`](121_first-class-on-devices-and-unattended.md) — the supervision/topology split, the git-as-truth / fsync-as-durability assumptions, the `EvidenceSource`/`DurableLog` seams, the deferred-client steelman, reconnection-as-ARIES (§4/§6 reuse all of it).

*The contract that made the port possible (and the freeze worth it):*
- [`86_the-typed-verdict-surface.md`](86_the-typed-verdict-surface.md) — `classify(Evidence, Policy) -> Verdict`, the evidence-in/verdict-out line NSP turned into a process boundary and this note turns into a language boundary.
- [`79_primitives-not-features.md`](79_primitives-not-features.md) — why the deciders are small and still (the property that makes them fit a device).

*The seam pattern the device runtime inherits:*
- `src/dos/overlap_policy.py` — `admissible_under_floor` (the refuse-more floor the §4 tier-map AND-s every tier under).
- `src/dos/judges.py` — the kernel/driver split (the §5.2 host-language evidence drivers are out-of-kernel, the same as `llm_judge`).

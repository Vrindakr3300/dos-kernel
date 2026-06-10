# The "under-what" axis — environment and version provenance

> **DOS records *who did what* — which run took which lane, which agent claimed
> which step, which commit shipped which phase. It records nothing about *under
> what*: which kernel, which Python, which OS, which toolchain, which model
> adjudicated or produced the record. So two runs in different environments can
> reach different verdicts on the same input with no trace of the divergence in
> the durable surface. This note adds the missing axis as the kernel already adds
> every axis — facts gathered once at the boundary, frozen as data, stamped into
> the fossils, and refused on when they drift — and it does it without the kernel
> ever judging what a "good" environment is. Provenance, not policy.**

This is one axis delivered in four primitives of rising novelty. They share a
single object (`EnvPrint`) and a single discipline (the docs/76 flexibility
geometry: *the flexibility lives in the provenance and the which-signals, never
in the adjudication*). Taken together they answer the reproducibility question the
kernel currently cannot: **"this verdict — recompute it; was it the code that
changed, or the environment?"**

The four, and what each kills:

1. **`EnvPrint` on every durable record** (directionally obvious). A
   content-addressed digest of the adjudicating environment — kernel version,
   kernel git SHA, Python version, OS/arch, and a small declared set of tool
   versions — gathered once at the boundary (an `EnvPrint` is a `WorkspaceFacts`
   sibling) and stamped into the WAL, the intent ledger, and the ship verdict.
   Makes every adjudication *contestable*: recompute it under the recorded print
   and see if the verdict holds.

2. **Producer provenance in the intent ledger** (forward extension of docs/107).
   `STEP_VERIFIED` already mints a belief over git ancestry; extend the minted
   record to carry the producing *model id* and *agent/tool version* alongside the
   `EnvPrint`. Turns "did it ship" into "did *this attested producer*, under *this
   environment*, ship it." The Sigstore/in-toto attestation is a driver, never the
   kernel.

3. **The fleet env-pin refuse** (the prevented-not-detected move). A new
   structured refusal — `FLEET_ENV_MISMATCH` — where the arbiter refuses a worker
   whose `EnvPrint` differs from the fleet's pinned print. Turns the industry's
   by-convention anti-drift (one Dockerfile → N identical clones) into an
   *adjudicated* kernel guarantee.

4. **Schema-version as a first-class structured refuse** (cheapest; aligns an
   existing mechanism with a now-normative wire form). `durable_schema` already
   refuses a record a newer kernel wrote. Promote that read-gate verdict into the
   closed reason vocabulary as `SCHEMA_UNREADABLE`, carrying the kernel's
   *supported schema set* — exactly MCP's `UnsupportedProtocolVersionError`
   (`-32004`, payload `{supported, requested}`), which standardized this wire form
   in late 2025.

The dependency arrow is `1 → {2, 3}`; `4` is independent and can land first or
last. Phase 1 (this session) builds primitive 1's object and stamps it into one
surface. The rest are sequenced in §6.

---

## 1. The asymmetry this closes

The kernel's epistemic stance is **distrust the self-report; believe the
evidence** (docs/103). It has been applied to *what an agent did* — the
`STEP_CLAIMED` vs `STEP_VERIFIED` asymmetry, the ship oracle reading git ancestry
instead of "I'm done", the arbiter believing only the lease WAL. But there is a
second self-report the kernel currently swallows whole: **the environment the
verdict was computed in.** Nothing records it, so nothing can distrust it.

This matters because verdicts are environment-dependent in ways the kernel already
knows about and has fixed *case by case* without ever naming the general problem:

- The **Windows case-fold + lock-steal** hardening (v0.7.0) exists because the
  same collision check returned different verdicts on Windows vs Linux. That is an
  *environment-dependent verdict* — fixed in the code, but with no record in the
  fossil of which OS produced any historical verdict.
- The **generic-vs-strict stamp default** (F9, `docs/74-friction-log.md`) exists
  because `verify` returned `NOT_SHIPPED` under one config and `SHIPPED` under
  another for the same git state. The config is part of the environment; the
  verdict does not record which config won.
- The **stale editable `.pth` / PYTHONPATH-must-be-absolute** friction
  (`install.py`, every `_cli` test helper) exists because *which `dos` source tree
  is on PATH* silently changes the answer. The verdict records neither the kernel
  version nor its git SHA, so a `NOT_SHIPPED` from a stale worktree is
  indistinguishable from a real one.
- The **eval non-determinism** result ("On Randomness in Agentic Evals", 60k
  SWE-bench trajectories, March 2026): single-run pass@1 varies 2.2–6.0 points and
  σ > 1.5 even at temperature 0, because the *verifier's* hardware/batch/env shifts
  the result. A reproducible verdict must pin the verifier's environment, not just
  the input.

Each of these is the same gap seen from a different side: **the kernel adjudicates
under an environment it does not record.** The fix is not to make the kernel
*judge* environments — that would be policy, and it would couple the kernel to a
notion of "good toolchain" it has no business holding. The fix is to make the
environment a *recorded fact* (primitives 1–2) and to let a host *refuse on
drift* it declares (primitive 3) — provenance and a which-signal, exactly the two
places docs/76 says flexibility is allowed to live.

### Why this is on-trend, not speculative

The industry arrived at the same primitives in the last two months, independently:

- **The env is a content-addressed, forkable object.** Devin's `blockdiff`
  (open-sourced June 2025) makes a 20 GB disk snapshot in ~200 ms; E2B boots from
  versioned templates; Codex pins runtime versions with a cache key that
  auto-invalidates on config change; Claude Code's dev container pins the CC
  version. An `EnvPrint` is the kernel-grade handle for exactly this object.
- **The producer is pinned.** Every Claude model id is now an immutable snapshot
  (`claude-opus-4-8` is the pin, not an evergreen alias) — "Anthropic does not
  update the weights of an existing model id; a new version ships under a new id."
  That is the canonical "record the producer" token, with a documented caveat
  (*serving infra can still drift behavior under a fixed id*) that is itself an
  argument for keeping git-evidence above the version string.
- **Refuse-on-unknown-version is normative.** MCP's `UnsupportedProtocolVersionError`
  (`-32004`) returns `{supported, requested}` so the caller can re-negotiate; A2A
  negotiates versioned URI extensions; schema registries ship BACKWARD/FORWARD/FULL
  compat modes. DOS's `durable_schema` *is* this pattern — primitive 4 just gives
  it the same wire form.

The kernel is not chasing a fashion here; it is naming a problem it has already
hit four times and giving it the same treatment every other axis got.

---

## 2. The object — `EnvPrint`

A frozen, content-addressed record of the environment a verdict was computed in.
The `WorkspaceFacts` sibling: gathered **once at the build boundary** (the same
place `gather_workspace_facts` runs), cached as data on the `SubstrateConfig`, and
read by every later durable write — never re-probed inside a pure verdict.

```python
@dataclass(frozen=True)
class EnvPrint:
    kernel_version: str          # dos.__version__ (e.g. "0.8.0")
    kernel_sha: str | None       # git SHA of the kernel's OWN tree, or None
    python: str                  # "3.13.1" (sys.version_info, not the full banner)
    platform: str                # "win32" / "linux" / "darwin" + arch
    tools: tuple[ToolVersion, ...]  # declared, e.g. (("git", "2.43.0"),)
    digest: str                  # content hash of the above — the EnvId
```

- **`digest` is the `EnvId`** — a short, stable hash over the other fields
  (Crockford base32, the run-id idiom). It is what primitive 3 compares and what a
  `--json` consumer keys on. Two environments with the same `digest` are
  interchangeable *by declaration*; the kernel does not assert they are *behaviorally*
  identical (the model-id caveat applies to the whole print).
- **`kernel_sha`** is the one fact that catches the stale-`.pth` hazard directly:
  two worktrees at the same `kernel_version` but different commits print different
  SHAs, so a verdict from the wrong tree is now self-evident in the fossil.
- **`tools`** is a *declared* set — `dos.toml [env] tools = ["git", "node"]` — not
  an open probe of everything on PATH. The kernel records only what a workspace
  says matters, keeping the print small, stable, and free of ambient noise. This is
  the closed-set-as-data discipline (`reasons`/`stamp`), applied to the env axis.
- **Gathering is boundary I/O**; the dataclass itself is pure and constructible in
  tests with no I/O (the `WorkspaceFacts(root=…)` idiom — a hand-built print for a
  unit test never shells `git`).

`EnvPrint` lives in a new leaf module `src/dos/env_print.py` (Layer 1 kernel,
pure-dataclass + a boundary gatherer, exactly the `run_id` shape: the type and the
mint/gather helper in one file, the I/O confined to the gatherer). It carries a
`durable_schema` family (`"env-print"`, version 1) like every other durable record,
so an `EnvPrint` a newer kernel wrote is refused-don't-guessed, not misparsed —
primitive 4 closes the loop on the print itself.

### What it is NOT

- **Not a sandbox manager.** DOS does not create, snapshot, or enforce
  environments — that is the host's container/Nix/devcontainer layer (the docs/99
  actuation boundary: the kernel records and refuses, it does not actuate). It
  records the *print* of whatever environment it was run in.
- **Not a behavioral guarantee.** A matching `digest` means "the same declared
  inputs," not "the same output" — the model-id and temp-0-nondeterminism caveats
  forbid that claim. The print is *evidence for a reproduction attempt*, not a
  proof of reproducibility.
- **Not mandatory on the pure core.** A `SubstrateConfig` built without gathering
  (the test path) carries `env=None`, and every consumer treats `None` as "not
  recorded" — exactly as `WorkspaceFacts=None` is treated today. The pure verdicts
  (`arbitrate`, `is_shipped`, `classify`) never *require* a print; they are handed
  one to *stamp*, the same way they are handed a clock.

---

## 3. Primitive 1 — stamp `EnvPrint` into the durable surfaces

The print earns its keep only when it rides the fossils. Three write-sites, each
additive (a new optional field → no `durable_schema` version bump, by the additive
contract):

- **The WAL (`lane_journal`).** An `ACQUIRE`/`RELEASE`/`HALT` entry gains an
  optional `env` field carrying the `digest` (the full print is written once per
  run-dir, not per entry — the entry carries the cheap key). So "which environment
  held this lease" is answerable from the WAL alone.
- **The intent ledger (`intent_ledger`).** `INTENT` records the full print at
  birth; `STEP_VERIFIED` records the `digest` (primitive 2 adds the producer fields
  here). So a resumed run can see whether it is continuing under *the same*
  environment the original ran in — a `DIVERGED` signal `resume_plan` can read.
- **The ship verdict (`oracle.ShipVerdict`).** Gains an optional `env` field. A
  `dos verify --json` now answers "SHIPPED under env X at SHA Y" — the reproducible-
  verification provenance the eval-nondeterminism result calls for.

Each is a *recorded fact*, not a new verdict. `is_shipped` does not change its
answer because of the print; it merely stamps the print onto the answer. This is
the load-bearing litmus for Phase 1: **the entire existing suite stays green**,
because stamping an optional field changes no verdict (the `DisjointnessPredicate`-
through-`run_predicates` precedent: a seam that adds plumbing without moving a
verdict proves itself by the green suite).

---

## 4. Primitive 2 — producer provenance (the docs/107 forward extension)

`STEP_VERIFIED` is the kernel's strongest minted belief: "this claimed step is real
because its SHA is in git ancestry on the non-forgeable rung." Today it records the
*structure* (the SHA, the verification). It records nothing about the *producer*.
Extend the minted record with two declared fields:

- **`model_id`** — the producing model's immutable id (`claude-opus-4-8`), passed
  in by the driver that minted the step. The kernel does not *infer* it (it has no
  provider surface); it records what the boundary declares, the same as `tools`.
- **`agent_version`** — the agent/tool version string (the harness, the SDK build).

This turns the ledger into a producer-attributed progress log: "step S was claimed
by producer P under environment E, and verified against SHA Y." The honest caveat
is recorded *with* it: a `model_id` pins weights, not behavior (serving infra
drifts), so the kernel still treats the *git evidence* as the load-bearing fact and
the `model_id` as provenance metadata — never as a reason to trust a claim it could
not verify. This is docs/76 exactly: the producer id is a *which-signal on the
provenance*, it does not enter the *adjudication* (a `STEP_VERIFIED` is verified by
ancestry regardless of who produced it).

The **signed attestation** (Sigstore `gitsign` keyless commit signing, an in-toto
SLSA `ai-generation` predicate binding plan-hash → code-hash → model identity) is a
**driver**, never the kernel — the same kernel/driver split as `llm_judge`. The
kernel records the plaintext provenance fields; a `drivers/attest_sigstore.py`
(future) can sign them and verify the signature at read. The kernel's job is to
*record the claim*; verifying a cryptographic signature is provider-backed I/O that
lives outside the boundary, exactly where a ruling judge lives.

---

## 5. Primitive 3 — the fleet env-pin refuse (`FLEET_ENV_MISMATCH`)

This is the one primitive that *moves a verdict*, so it is the most careful. Today
the arbiter refuses a lease for region collision (`overlap`), for self-modification
(`SELF_MODIFY`), and for an exhausted class budget (`CLASS_BUDGET_EXHAUSTED`). Add
one more refusal, emitted only when a host opts in by declaring a **pinned fleet
print**:

> A worker requesting a lease carries its own `EnvPrint.digest`. If the config
> declares a `pinned_env` digest and the worker's digest differs, the arbiter
> refuses with `FLEET_ENV_MISMATCH` — "this worker is running a different
> environment than the fleet was pinned to; admitting it risks the env-drift the
> pin exists to prevent."

The discipline that makes this safe is the same conjunctive, refuse-only,
opt-in-by-data discipline every other admission rule rides:

- **Opt-in.** With no `pinned_env` declared (the default, and every existing
  workspace), the check is inert and the arbiter behaves byte-for-byte as today.
  The litmus: the entire existing arbiter suite stays green because `pinned_env` is
  `None` everywhere it isn't set.
- **Refuse-only.** Like `SELF_MODIFY` and the overlap floor, this rule can only
  *refuse more*; it never admits a lease the rest of the arbiter would have refused.
  It composes conjunctively (`admit ⟺ all-other-checks AND env-matches`).
- **A which-signal, not a judgment.** The kernel does not decide *which*
  environment is correct — the host declares the pin (`dos.toml [env] pinned =
  "<digest>"`, or `dos arbitrate --pinned-env <digest>`). The kernel only
  adjudicates *match vs mismatch* against the declared value. This is the docs/76
  line held exactly: the flexibility is in the declared pin (provenance + a
  which-signal), the adjudication is a fixed equality check.
- **Structured + complete.** `FLEET_ENV_MISMATCH` is a `ReasonSpec` in the closed
  vocabulary (category `MISROUTE` — a fleet running the wrong environment is a
  misrouted worker, the `SELF_MODIFY` sibling), so it is simultaneously emittable,
  verifiable (`category_for`), refusable (`is_refusal`), and `dos man wedge
  FLEET_ENV_MISMATCH`-documented — the Axis-1 completeness rail every arbiter refuse
  rides.

This is the "prevented, not detected" move the FleetHorizon work calls for: the
industry pins one Dockerfile and *hopes* the fleet stays consistent; DOS makes the
pin an *adjudicated admission gate* — a worker on a drifted toolchain is refused at
the lease, not discovered after it has written.

---

## 6. Primitive 4 — `SCHEMA_UNREADABLE` as a first-class refuse

`durable_schema.classify` already returns `UNREADABLE_NEWER` with a legible reason
("this `intent-ledger` record is v3 but this kernel reads ≤ v2"). Today that
verdict is a *read-side gate* internal to each durable reader. Promote it to a
first-class member of the closed refusal vocabulary so it is part of the syscall
ABI, and give it MCP's wire shape:

- A `SCHEMA_UNREADABLE` `ReasonSpec` (category `MISROUTE` — a record this kernel
  cannot soundly parse is work it must route elsewhere, not guess at), so the
  refuse-don't-guess floor surfaces through the *same* structured-refusal channel as
  every other "no" (the docs/82 taxonomy: all refusals are kinds of "no", and this
  is one).
- The refuse **carries the supported set** — the `{family, understood_version,
  record_version}` triple `ReadabilityVerdict` already holds — rendered exactly as
  MCP's `{supported, requested}`. So a caller (a resuming successor, a cross-version
  fleet member, the MCP server) gets the *remedy with the refusal*: "I read
  `intent-ledger` ≤ v2; this record is v3; upgrade the kernel or run `dos runs
  migrate`," not a bare failure.

This is the cheapest primitive (the mechanism exists; this wires its verdict into
the vocabulary and the CLI/MCP surface) and the most directly validated by industry
direction: MCP made `{supported, requested}` a normative MUST in late 2025, and
DOS's `durable_schema` predates it with the same shape. Promoting it is pure
alignment — the kernel's existing refuse-don't-guess floor, surfaced through the
channel the rest of the world standardized on.

---

## 7. The litmus tests (each enforced by a test or trivially checkable)

- **The print is gathered at the boundary, never in a verdict.** `env_print.py`'s
  pure `EnvPrint` dataclass is constructible with no I/O; the `gather_env_print`
  function is the only one that shells `git`/reads `sys`/`platform`, and it is
  called only by the config builders — the `gather_workspace_facts` rule. Grep:
  no `subprocess`/`platform.`/`sys.version` inside any `*_verdict`/`classify`/
  `arbitrate`/`is_shipped` body.
- **Stamping moves no verdict.** Phase 1 adds optional `env` fields to the WAL
  entry, the ledger record, and `ShipVerdict`; the entire existing suite stays
  green, because an additive optional field changes no decision (the
  `run_predicates` precedent). A dedicated test asserts `is_shipped` returns the
  identical `shipped`/`sha`/`source` with and without a print supplied.
- **The fleet refuse is inert by default.** With no `pinned_env` declared,
  `arbitrate` returns byte-for-byte the same decisions as today — pinned by the
  existing arbiter suite passing unchanged, plus a test that a mismatched worker is
  *admitted* when no pin is set and *refused* with `FLEET_ENV_MISMATCH` only when a
  pin is set.
- **The refuse can only refuse more.** A test asserts that for every input where
  the env check fires, the rest of the arbiter would also have to pass for an
  admit — i.e. the env gate never flips a refuse into an admit (the overlap-floor
  conjunctive litmus, re-aimed).
- **Every new reason is complete.** `FLEET_ENV_MISMATCH` and `SCHEMA_UNREADABLE`
  are in `BASE_REASONS`, roll up to a `KNOWN_CATEGORIES` value, and are
  `dos man wedge`-documented — the existing reason-completeness test covers them by
  enumerating the registry.
- **The print is itself version-guarded.** An `EnvPrint` carries a `durable_schema`
  `"env-print"` tag; a print tagged at a version this kernel predates is refused via
  `SCHEMA_UNREADABLE` (primitive 4 closing on primitive 1), not misparsed — pinned
  by a `classify`-over-`env-print` test.
- **The kernel still trusts evidence over the print.** A test asserts a
  `STEP_VERIFIED` is minted iff the SHA is in ancestry *regardless of `model_id`* —
  the producer field is recorded provenance, never an input to the verification
  (the docs/76 line: provenance does not enter adjudication).
- **No host, no I/O policy, no sandbox.** `env_print.py` names no host, creates no
  environment, and reads only `sys`/`platform`/`git` + the declared `tools` list —
  it records a print, it does not manage an environment (the docs/99 actuation
  boundary).

---

## 8. Build order

| Phase | Deliverable | Moves a verdict? | Depends on |
|---|---|---|---|
| **1** (this session) | `env_print.py`: `EnvPrint` + `ToolVersion` + `gather_env_print` (boundary) + `digest`; `durable_schema` `"env-print"` family; stamp the `digest` into **one** surface (the intent ledger `INTENT` record) end-to-end as the proof-of-shape; tests + `dos doctor` row. | No | — |
| **2** | Stamp into the WAL + `ShipVerdict`; surface in `dos verify --json` / `dos top`. | No | 1 |
| **3** | Producer provenance: `model_id` + `agent_version` on `STEP_VERIFIED`; `resume_plan` reads env-divergence as a `DIVERGED` signal. | No | 1 |
| **4** | `SCHEMA_UNREADABLE` reason + carry the supported set; surface in the MCP server's error shape ({supported, requested}). | No (read-gate already exists) | — |
| **5** | `FLEET_ENV_MISMATCH` reason + arbiter gate behind `pinned_env`; `[env] pinned` in `dos.toml`; `--pinned-env` CLI flag. | **Yes** (opt-in) | 1 |
| **6** (future, driver) | `drivers/attest_sigstore.py`: sign the producer-provenance record, verify at read. Out-of-kernel, the `llm_judge` sibling. | No | 3 |

Phase 1 is deliberately the smallest end-to-end slice that proves the *shape*: the
object, the boundary gather, the schema tag, and one durable stamp — the
`EnvPrint` analogue of how `intent_ledger` shipped its first `INTENT` record before
the rest of docs/107. Everything policy-bearing (primitive 3) waits for review.

---

## Provenance of this note

The gap was surfaced by a cross-cut of three reads against the live tree (the
existing version/env/schema surface), the documented run scars (the F-series
friction log, the v0.4.0/v0.7.0 release gotchas, the PYTHONPATH/`.pth` test
helpers), and the April–June 2026 industry direction (Devin `blockdiff`, Codex
pinned-env cache, immutable Claude model ids, MCP `UnsupportedProtocolVersionError`,
the eval-nondeterminism result). It implements no new epistemics — it applies the
existing distrust-the-self-report stance to the one self-report the kernel still
swallows: the environment it ran in.

# docs/135 — What DOS learns from Microsoft's Agent Governance Toolkit

> A direct, code-grounded audit of `microsoft/agent-governance-toolkit` (AGT)
> against the DOS kernel. Cloned `agt-msft` @ `8fd0b61` (Public Preview,
> MIT). Read firsthand: the Rust ACS core, the four AGT-*-1.0 wire specs, the
> identity/audit/authority stack, the hypervisor PEP, the benchmarks, and the
> positioning docs. Every claim below carries a `file:line` anchor.

This is an **engineering analysis** (mechanism-vs-mechanism + what to build), so
it lives in `dos/docs/`, not `dos-private`. The one-way arrow holds: nothing in
`src/dos/` depends on AGT; this doc references AGT to sharpen DOS's design.

It also **corrects a memory**: the docs/121 external sweep recorded "Microsoft
AGT shipped a fail-closed PDP+PEP+kill-switch → CHALLENGES advisory-only, DOS
behind on in-band prevention." That is *half right*. The accurate picture is
below in §1 and §7.

---

## 0. What AGT is, in one breath

AGT is **runtime, application-layer governance** for agents: a host calls a
stateless, deterministic, **fail-closed** policy engine (the vendored *Agent
Control Specification*, ACS, a Rust core) at one of **eight intervention points**
across the agent loop, passing a complete JSON snapshot; the engine returns a
five-valued verdict the host enforces in-band. Its tagline is the cleanest
statement of its axis: *"They guard LLM outputs. We govern agent actions"*
(`docs/COMPARISON.md:3`). Around that core sit a per-agent cryptographic identity
mesh, a Merkle-chained audit log, execution rings, a kill-switch, OS sandboxes, an
SRE stack, 20+ framework adapters, and SDKs in 5 languages.

DOS and AGT are **adjacent, not the same**. AGT positions as a *governance
platform/SDK you wrap your agent in*; DOS positions as a *trust substrate/referee
that does not believe agents*. AGT never compares itself to reference monitors,
OPA-as-substrate, Saltzer complete-mediation, or CaMeL — a repo-wide grep for
"reference monitor / complete mediation / Saltzer / CaMeL" returns **zero**
(`positioning brief`). It competes on **breadth + OWASP-10/10 coverage**; DOS
competes on **epistemic discipline** (witness≠actor, evidence-over-narrative).

---

## 1. The keystone contrast: fail-to-DENY vs fail-to-ABSTAIN

AGT's closed verdict enum is `Decision { Allow, Deny, Warn, Escalate, Transform }`
(`policy-engine/core/src/verdict.rs:10-16`); `permits()` ⟺ `Allow|Warn|Transform`
(`:32-34`). **Fail-closed is the keystone**: `Verdict::runtime_error()` maps *any*
`RuntimeError` → `Decision::Deny` (`:124-139`); `runtime.rs:156-166` wraps the
whole evaluation so any error collapses to that one Deny. Panics are caught
(`catch_unwind`, `runtime.rs:286-292`) → Deny. Policy output is forbidden from
forging the reserved `runtime_error:*` reason prefix (`verdict.rs:246-249`), so a
hostile policy can't fake a runtime reason.

This is the **structural opposite of DOS's fail-to-ABSTAIN** (`run_judge` converts
any raise/bad-return to `ABSTAIN`, never `AGREE`; `gather_evidence` →
`NO_SIGNAL`). The divergence is **principled, not a deficiency on either side**,
and the reason is *position in the path*:

- AGT is a **gate in the path** → its safe default is **deny** (block the action).
- DOS is an **advisor beside the path** → its safe default is **abstain** (say
  nothing false).

And AGT *can* deny safely only because the **host declared what the intervention
point IS** (`pre_tool_call` with a `policy_target`). DOS, by docs/99's
domain-freedom law, **refuses to know what a process is**, so it cannot safely
deny — abstaining is the honest floor. This is defended by code on both sides, not
asserted. **Keep this framing as the spine of the whole comparison.**

`Escalate` is a *verdict value* (≈ DOS's HUMAN rung) rather than a separate
syscall — a design contrast with DOS's ORACLE→JUDGE→HUMAN ladder worth noting but
not adopting (DOS's ladder buys the deterministic-first discipline AGT's flat enum
doesn't encode).

---

## 2. The five things DOS should genuinely take or build

Ranked by value. Each is a real gap or sharpening, confirmed against DOS source.

### 2.1 The TRANSFORM verdict — sanitize-and-admit (DOS structurally lacks it) — **BUILD A PLAN**

AGT's fifth verdict **rewrites the action before it executes**: `Transform` sets a
new value at a path rooted only at `$policy_target` (`verdict.rs:58-97, 304-317`);
e.g. it redacts a PII account number out of a prompt and the agent's `execute()`
only ever sees the redacted value. The whole `effects.rs` redaction engine
(pattern/values/spans, character-offset-correct) backs it (`effects.rs:204-372`)
— though AGT is *collapsing* the multi-op effects array into the single
constrained `Transform` (`effects.rs:1-7`, "sunset by §14"); their refactor
direction (fewer, more-constrained primitives) mirrors DOS's *primitives not
features*.

DOS's vocabulary is purely **ACQUIRE/REFUSE/ABSTAIN/verdict-only** (`arbiter.py`,
`judges.py` three-valued; grep across `src/dos` for transform/redact/sanitize/IFC
returns nothing real). A DOS adjudicator can **refuse-MORE but never
sanitize-and-admit**. This collides head-on with the docs/76 flexibility-geometry
law (*flexibility lives in provenance, NEVER the adjudication*) and the
mechanism-never-mutates rule. So a transform almost certainly belongs in a
**driver** (transform = policy + I/O), but the kernel would need an **outcome
token** for it and a **non-forgeable enforced-action digest**.

> **Action:** a new `docs/NN` design plan — *is a sanitize-and-admit outcome
> compatible with "mechanism is the kernel, never mutates"?* It is the question
> that decides whether DOS's verdict vocabulary stays strictly less expressive
> than AGT's. This is also the **context the audit's one survived mapping
> depends on** (see §2.2).

### 2.2 A bisected `declared_identity` vs `enforced_identity` pair at the apply-gate — **IMPROVE_ON (fold into docs/126)**

AGT carries **two SHA-256 identities on every request**: `input_identity` (what
the policy saw) and `enforced_identity` (what the host carries out — differs only
on an enforced `Transform`), both over the canonical policy-input JSON
(`runtime.rs:400-432`, `policy_input.rs:43-56`). The invariant that
`EvaluateOnly` (advisory) ⇒ `enforced_identity == input_identity`
(`runtime.rs:369-374, 414-432`) is a **checkable witness that advisory mode
performed no transform**.

DOS already has the *core* — declared-vs-enforced bisection — **three times over
and more rigorously**: `intent_ledger` splits `STEP_CLAIMED` (forgeable) from
`STEP_VERIFIED`, which `resume.py` + `resume_evidence.py` **re-adjudicate at read**
(`resume.py:230-262`); `scope.gate()` binds the declared lane_tree vs the actual
diff footprint pre-effect (`scope.py:482-520`); `evidence.believe_under_floor`
structurally bars an agent-authored attestation from ever moving `verify`→belief
(`evidence.py:411-484`); and `env_print.digest` is SHA-256 recompute-never-store.
So *"bind identity to content, distrust the declared one"* is **not new to DOS**.

The genuinely additive piece, confirmed by the adversarial verifier against
`docs/126` lines 149-179: the unbuilt `dos apply` gate has **no per-effect typed
identity pair**, no **content-digest of the admitted footprint**, and §3 rule-3
("the out-of-band PDP path survives unchanged") is **prose, not a structural
proof**.

> **Action:** in docs/126 Phase 1, make `dos apply` return a typed
> `(declared_identity, enforced_identity)` pair — declared = the lease's region/
> intent as it arrived; enforced = the SHA-256 content-digest of the footprint
> actually admitted (reuse `env_print`'s content-addressing, don't mint a new
> hash) — and assert as a kernel invariant + test that in advisory mode the two
> are byte-equal. That hardens §3 rule-3 from prose into a witness.

### 2.3 A hash-chained, tamper-EVIDENT lane journal — **TAKE (cheap, high value) — but read AGT's own caveat**

AGT's `MerkleAuditChain` chains each `AuditEntry` by `previous_hash` + `entry_hash`
(SHA-256 over canonical-JSON) and offers Merkle inclusion proofs
(`agentmesh/governance/audit.py:172-190, 283-441`). DOS's `lane_journal.py` WAL is
**append-only but not hash-chained** — a journal writer can silently rewrite
history. Adding `previous_hash` chaining is a **small change with real value**:
it makes after-the-fact tampering *detectable*.

But take AGT's own failures as the spec for doing it right — the `audit-sre` brief
found that AGT's implementation is **half-built and partly broken**, and DOS
should not repeat the mistakes:
- The high-value fields `arguments_hash`, `approver_did`, `policy_version` are
  **explicitly OUTSIDE the hash** ("NOT part of the canonical entry hash in spec
  v1.0", `audit.py:95-137`) — so *who approved*, *which policy decided*, and *the
  arguments* can be mutated without breaking the chain. `verify_integrity` even
  returns `"""Always valid."""` (`audit.py:604`).
- The production sink is unsigned (`audit_collector.py:44` builds a `FileAuditSink`
  with no `secret_key`); the in-memory chain has no signing at all.
- The log endpoint **accepts `agent_did` from the request body without
  authenticating the caller** — a documented "SECURITY (known gap)" — so the agent
  **self-asserts its own identity into the "immutable" record**.

> **Lesson, two-sided:** (a) tamper-EVIDENT ≠ tamper-PROOF — an in-process chain
> protects against *later* alteration, not a malicious writer at append time
> (same fundamental limit DOS has). (b) If DOS chains its WAL, chain **every**
> load-bearing field, and remember the witness must not be the actor: a journal
> entry whose `agent_did` is self-asserted proves order, not authorship. DOS's
> "the witness is the receiver of the effect" (docs/121) is **sharper** than
> AGT's asserted-DID audit row.

### 2.4 The capability-attenuation delegation calculus — **IMPROVE_ON / feed docs/131**

AGT's identity stack answers DOS's open *ID-JAG principal* question concretely
(`agentmesh/identity/agent_id.py`, `core/identity/ca.py`):
- Per-agent `did:mesh:<128-bit>` + **Ed25519 keypair**; the agent signs its own
  actions; a **CA mints** a SPIFFE/SVID X.509 cert that requires a **human
  sponsor's signature** over `agent_name:sponsor_email:capabilities`
  (`ca.py:197-231`). **The agent cannot forge its own identity** — minting needs a
  signature it doesn't hold. Revocation propagates ≤5s.
- **`delegate()` attenuation calculus** (`agent_id.py:237-302`): a child's
  capabilities **MUST be a subset** of the parent's; wildcard propagation blocked;
  depth-capped; **lineage-bound trust** ("child's initial trust ≤ parent's" =
  Sybil resistance). `verify_delegation_chain` + `get_effective_capabilities`
  (= intersection across the chain).

This is the **same shape** as DOS's region-claim (docs/119, a claim can only
narrow) and the docs/131 authority-plane — but AGT ships it as a **cryptographic
delegation chain with a non-forgeable minted credential**, where DOS has a
region-digest. The *attenuation-only* law is the transferable jewel: **authority
composes by narrowing, never widening — verifiable structurally.**

> **Action:** feed docs/131 — model the DOS capability-as-lease so that
> sub-delegation is **subset-only by construction** (the arbiter analogue of
> AGT's `delegate()` subset check + the docs/113 overlap-floor "can only
> refuse-MORE"). The sponsor-signature minting + ≤5s revocation are the answer to
> "who mints the principal, and can the agent forge it" — DOS should adopt the
> *non-forgeable mint by a sponsor* property, not necessarily the SPIFFE stack.

### 2.5 The named "silent-downgrade" attack class — **TAKE the threat name**

AGT's `policy_version` field exists "to defend against silent policy downgrade
(replaying old decisions under a newer policy version)" (`audit.py:129`), and the
ACS spec **fails closed on a version that differs between a parent and child
manifest** (`SPEC §2.2`, refuse-not-best-effort). This is **DOS's `durable_schema`
refuse-don't-guess discipline applied to the *policy*, not the record schema** — a
second consumer of the same instinct. The *silent-policy-downgrade* attack is one
DOS hasn't named.

> **Action:** add "silent-decision-downgrade" (re-adjudicating an old effect under
> a stale policy/oracle version) to the DOS threat vocabulary, and confirm
> `verify`/`resume` stamp the *adjudicator* version the way `env_print` stamps the
> environment.

---

## 3. The convergences — AGT independently validates six DOS designs

These are not gaps; they are **external corroboration** that DOS's designs are
the ones a well-funded competitor also arrived at. Worth citing in strategy.

| DOS design | AGT's independent reinvention | Citation |
|---|---|---|
| **Advisory mode** (detect/record/propose) | `EnforcementMode::EvaluateOnly` — DOS's entire posture as a built-in toggle; `AuthorityDecision.audit` = "logged but not enforced (shadow mode)" | `intervention_point.rs:78-82`; `authority.py:109` |
| **EvidenceSource: evidence = pointer to a re-verifiable witness** | `Evidence { artefact: sha256:…\|uri, verification_pointers }`, opaque, 4 KiB cap; "if the proof verifies, the decision is **reproducible**" | `verdict.rs:142-227`; `AGT-EVIDENCE-1.0 §1-4` |
| **EnvPrint / docs/115 under-what axis** (capture once at boundary, recompute never store) | `AuditEntry` auto-captures `sandbox_id/environment/compute_driver`, snapshotted once at init, "never re-read per-entry" | `audit.py:35-54, 480` |
| **Pluggable adjudicator seam** (judges.py / overlap_policy.py Protocol + by-name resolver) | `AuthorityResolver` Protocol called "at the enforcement boundary", closed `AuthorityDecision` | `authority.py:8-117` |
| **Region-claim narrowing** (a claim can only narrow) | `allow_narrowed` verdict + `effective_spend_limit` (attenuation + value-aware admission) | `authority.py:109-111` |
| **I/O at the boundary, pure verdict at the core** | `build_policy_input` is pure state-in; non-determinism quarantined into annotators/dispatchers that can only fail-closed | `policy_input.rs:6-41`; `runtime.rs:444-540` |

The strongest convergence is **EvaluateOnly**: AGT *subsumes DOS's advisory stance
as one configuration of a system that can also enforce.* That is simultaneously a
validation (the posture is real and named) and a challenge (AGT can flip to
Enforce; DOS cannot — §7).

---

## 4. Where DOS is genuinely AHEAD — the durable spine and the neutrality axis

The ACS core is **stateless and deterministic with NO durable spine** (`spec
brief`): no lease/arbiter, no liveness, no resume/WAL, no intent ledger. "Replay"
in AGT means *re-derive the same canonical action-identity and re-verify* — there
is no checkpoint, no resume verdict, no `schema:`-tagged durable record. DOS's
whole second half — `arbiter` (admission), `liveness` (temporal verdict),
`resume`/`intent_ledger` (ARIES third phase), `durable_schema`, the correlation
spine — **has no AGT analogue.** AGT is a referee for the *single next action*;
DOS is a referee for a *fleet over time*.

DOS is also ahead on the **neutrality/witness axis**, and this is the honest edge
to foreground (§7): AGT's PDP is **co-resident with the agent runtime** — "the
policy engine and agents share the same process boundary" (`README.md:370`),
production guidance is to run each agent in its own container precisely because the
in-process gate shares the adversary's process (`ARCHITECTURE.md:101`). DOS's
ground truth is **git ancestry — an external, un-authored witness the agent did
not write**. AGT's "never trust the self-reported trust score" handshake rule
(`handshake.py:542`) is DOS's evidence-over-narrative law, but AGT has **no
judge-from-generator independence coordinate** (docs/123) at all.

---

## 5. The efficacy reckoning — corrects the docs/121 "AGT is proven" memory

The single most important finding for honest positioning: **AGT's prevention
efficacy is as unproven as DOS's.**

- AGT **does not publish an in-house ASR benchmark** and "intentionally avoids
  quoting unsourced violation-rate percentages" (`docs/BENCHMARKS.md:208`).
- Its splashy **"26.67% / 0.00%"** pair is **disavowed** by BENCHMARKS.md:222 as
  "not yet substantiated by a published methodology" — *yet still cited as live
  fact in ≥4 other docs* (`FAQ.md:564`, `modern-agent-architecture-overview.md:21`,
  the i18n READMEs). An internal contradiction.
- The one with/without-AGT run (AgentDojo) uses a **scripted LLM that replays
  ground-truth so every injection is forced to land** — baseline ASR=1.000 is a
  **tautology** and "1.000→0.000" is a **unit test of "does my deny-rule deny,"
  not a measurement against an adaptive adversary** (`benchmarks brief`;
  `pipeline.py:217-285`, `policy.py:19-25`). No results are committed (gitignored).
- The case studies are **explicitly fictional** ("hypothetical… no real-world
  data") yet state hard numbers ("$142K+", "80x return").
- The real, reproducible benchmark is **latency only**: <0.11ms p99 is a
  *policy-eval microbenchmark*, and AGT concedes the full mesh path is "5–50ms per
  governed inter-agent interaction" (`LIMITATIONS.md:68-87`).
- The prevention claim ultimately rests on a **categorical argument**: "moving the
  decision off the model entirely… the probabilistic failure mode ASR measures
  does not apply to that path" (`BENCHMARKS.md:220`) — **the same posture DOS takes
  about its deterministic oracle.**

> **Corrected memory:** AGT is ahead on **HAVING a PEP**, not on **PROVING it
> works**. Its prevention is shipped as *mechanism*; its *efficacy* is argued, not
> measured — exactly DOS's situation. This is a point in favor of DOS's docs/130
> measurement discipline (with/without ablation on un-forgeable fossils), which is
> *more honest* than AGT's retracted-but-still-cited numbers. **Do not let the
> docs/121 sweep's "98%-vs-6% field gap" stand unqualified — that figure is from
> the external literature AGT cites, not from an AGT ablation.**

---

## 6. The honest gaps DOS still has (no flattering)

The completeness critic was right to flag a DOS-flattering tilt. Stated plainly:

- **No transform/sanitize verdict** (§2.1) — DOS's vocabulary is strictly less
  expressive.
- **No Information-Flow-Control / no-write-down.** AGT has a real IFC lattice
  (`public<internal<confidential<secret`) denying a confidential record routed to
  an external sink (`ifc_clearance_violation`). DOS has **nothing comparable**, and
  — confirmed firsthand — `src/dos/data_class.py` is **NOT** this: it classifies
  paths for *retention/reaping* (TRAJECTORY/AUDIT/BASELINE/PRODUCT), not data
  *sensitivity* for egress. Same word "class," orthogonal problem. This is exactly
  the docs/121 "git witnesses one effect class, blind to data exfiltration" blind
  spot. **A labels-on-data + sink-clearance model is a new axis, not a re-aim.**
- **No OS-level enforcement.** AGT ships real isolation in `agent-sandbox`
  (hardened Docker: `cap_drop=ALL`, seccomp, non-root, read-only rootfs;
  **gVisor/Kata** kernel isolation when present; Hyperlight micro-VMs). DOS is
  advisory-only by charter. On *prevention*, AGT is ahead; DOS's only counter is
  the **unbuilt docs/126**.
- **No multi-agent fault attribution.** AGT's hypervisor models joint liability +
  vouching/slashing + a `CausalAttributor` assigning root-cause across a saga.
  DOS's spine records *who held which lease* (provenance) but never *who is at
  fault* (attribution) or propagates consequence. Adjacent to docs/116; a decision
  to make about whether causal attribution is kernel-shaped (a verdict over
  fossils) or a driver.
- **No training-time governance.** AGT's `agent-lightning` turns policy violations
  into negative RL rewards (the reward-hacking surface). DOS is inference-time,
  post-hoc by charter — likely a deliberate NON-GOAL, but it should be *named* as
  one, not silently absent.

---

## 7. The bottom line — the corrected scorecard

**AGT is genuinely ahead of DOS on:** (a) a synchronous **in-band PEP** (Enforce
mode, Deny/Transform at 8 enumerated intervention points); (b) per-agent
**cryptographic identity + a sponsor-minted, non-forgeable credential + an
attenuation-only delegation calculus**; (c) **real OS isolation** (gVisor/Kata/
micro-VM sandboxes); (d) **IFC / no-write-down** data control; (e) the
**standards stack** (DID/JWK/SPIFFE/CloudEvents/Cedar/OPA); (f) **breadth** (20+
adapters, 5 SDKs, OWASP 10/10 mapping); (g) **the TRANSFORM verdict** (sanitize-
and-admit), which DOS structurally lacks.

**DOS is genuinely ahead of AGT on:** (h) the **durable spine** — admission
(arbiter), temporal liveness, resume/intent-ledger, the correlation spine,
`durable_schema` — *AGT has none of it*; (i) **neutrality/witness independence** —
git ancestry is an external un-authored witness; AGT's PDP is co-resident with the
adversary's process; (j) **the judge-from-generator independence coordinate**
(docs/123) — absent in AGT; (k) **measurement honesty** — DOS's docs/130 with/
without ablation discipline beats AGT's retracted-but-still-cited numbers.

**They tie (both unproven) on:** prevention *efficacy* — both rest on "the
mechanism is deterministic by construction," neither on a clean adaptive-adversary
ablation.

**The single sentence to remember:** *AGT is a reference monitor with teeth that
is co-resident with the agent and cannot yet prove it works; DOS is a neutral
referee with no teeth that watches an external witness and is honest that it only
detects. The five things to take are the TRANSFORM question, the apply-gate
identity bisection, the hash-chained journal, the attenuation-only delegation
calculus, and the silent-downgrade threat name — and AGT independently validated
six DOS designs in the process.*

---

## 8. Concrete next steps (each a small, scoped lift)

1. **docs/136 (or next free): the sanitize-and-admit question** — can a transform
   outcome exist without violating "mechanism never mutates"? (drives §2.1)
2. **Fold the `(declared, enforced)` identity pair + EvaluateOnly byte-equality
   witness into docs/126 Phase 1** (§2.2) — reuse `env_print` content-addressing.
3. **A `[journal] hash_chain` seam** adding `previous_hash`/`entry_hash` to
   `lane_journal.py`, chaining EVERY load-bearing field, with the witness≠actor
   caveat documented (§2.3).
4. **Feed docs/131** the subset-only sub-delegation model + non-forgeable
   sponsor-mint property (§2.4).
5. **Add "silent-decision-downgrade" to the threat vocabulary** and stamp the
   adjudicator version in `verify`/`resume` (§2.5).
6. **Name the four honest gaps** (transform, IFC, OS-PEP, fault-attribution) and
   the one NON-GOAL (training-time governance) in the relevant plans so they stop
   reading as silent absences (§6).

> Method note: the multi-agent read-phase succeeded (8/8 subsystem briefs); the
> per-concept map-phase hit the known schema-agent mass-failure (108/108 mapping
> agents read but never emitted StructuredOutput — the
> silent-truncation-reads-as-success trap). The mapping here was done in-context
> from the briefs + firsthand reads of `verdict.rs`/`effects.rs`/`agent_id.py`/
> `audit.py`/`authority.py`/`quarantine.py`/the specs, plus the one survived
> mapping and the completeness critic's six missing concepts. `conceptsMapped:1`
> was NOT read as "one learning."

# Externalizing the house-style verdict — what outside evidence does to the "70% house style" split

**Date:** 2026-06-02
**Status:** Method + findings note. Records an experiment; the one small arbiter
bug it surfaced (§4) is now **fixed + regression-tested** in the same session
(`TestRedirectReasonHonesty`, `arbiter.py` `_redirect_why`).
**Origin:** Operator — *"think about how to get more information to make this more
general not just house style."* The "this" is the audit verdict in
`dos-private/dispatch-os-symbolic-adjudication-tier.md` (§1): that ~70% of the DOS
strategy corpus is *house style* (OS-metaphor inflation, ritual steelmanning,
coinage density, a self-citation lattice) and ~30% is the durable invariant (the
"symbolic adjudication tier"). This note is the answer to *how to generalize that
verdict* — and the result of actually doing it.

---

## 0. The problem with the verdict (why "get more information" is the right instinct)

The "70% house style / 30% real" split was produced **by the same corpus it
audits, from inside the same self-citation lattice.** Every piece of its evidence
is internal:

- the narration↔effect gap is the corpus's own observation;
- the "three fields re-derived it" claim cites papers *the corpus selected*
  (selection bias — nobody searched for the fields that did **not** converge);
- "OS is house style" is the vision doc confessing about itself;
- "verify+refuse were the most useful" is one operator on one repo (N=1).

The corpus already names this as its single deepest weakness — *"no external
validation, this is real and unfixed"* recurs in nearly every strategy doc. So the
verdict is **real-by-internal-coherence, and coherence is exactly what house style
manufactures.** You cannot subtract house style with the same pen that wrote it.
To *generalize* the verdict — promote any of the "real 30%" from *coherent* to
*defensible* — the evidence has to come from outside the writers. This is the
docs/103 move (*re-verify a frozen claim against external ground truth at read
time*) applied to a strategy verdict instead of a memory.

Three external probes were run, each attacking a different surface.

---

## 1. Probe A — adversarial literature search (attack the claims from outside)

A hostile, well-read skeptic agent, briefed to find the **strongest disconfirming**
case (not a balanced one), across four fronts: *is the idea already named? does
self-verification work without separation? is vendor-neutrality economically real?
what is the base rate for elegant-N=1 infra?* 18 searches, primary sources fetched.

**The single most important external fact: the prior name exists, and it is 25–50
years old.** What the corpus calls "the symbolic adjudication tier" is, precisely:

- the **Simplex Architecture / Runtime Assurance** monitor (Lui Sha, *Using
  Simplicity to Control Complexity*, IEEE Software 2001) — *a verified, minimal,
  deterministic supervisor that bounds an untrusted high-capability actor*, fielded
  and certified in flight (Auto-GCAS). `liveness()=classify(Evidence,Policy)->Verdict`
  **is** a Runtime-Assurance Monitoring-and-Assurance module with the switch removed
  (advisory-only).
- fused with the **reference monitor / minimal TCB** doctrine (Anderson 1972) — the
  "kernel is the small part you trust, mediating every access" idea, which is
  `arbitrate()`/`refuse()`;
- and the **verifier-vs-prover asymmetry** (proof-carrying code, Necula 1997;
  IP=PSPACE) — "checking is cheaper than doing, so make the untrusted party carry
  the witness," which is `verify()` (notably DOS gives a *weaker* guarantee — a
  commit-subject regex + merge-base ancestry is a heuristic witness check, not a
  sound proof checker).

**What this does to the verdict — it makes it constructive instead of aesthetic.**
"70% house style" is an *aesthetic* judgment (too much costume). The prior-name
finding is a *structural* one:

- It **demolishes the "novel / genuinely under-built invariant" leg** (the strategy
  doc's §2.2–2.3). The corpus cited the tri-field re-derivation as evidence of *a
  real invariant being discovered from three sides*. That is true — and it cuts the
  **other** way: a pattern this obvious, this old, and this convergent is
  *well-trodden*, not unclaimed. An independent 2026 paper (**Parallax**, arXiv
  2604.12986) already publishes DOS's exact LLM-agent thesis — "agents that think
  must never act," reason/execute structurally separated by a trusted deterministic
  Shield — citing the same 50-year security lineage DOS stands in.
- But it **strengthens the honest core**, because Simplex/RTA/reference-monitor is a
  *credible* lineage with 40 years of external validation. The defensible reframe is
  not "novel quadrant" (already retired) but **"runtime assurance / a reference
  monitor, applied to a fleet of code-writing LLM agents"** — which *inherits* the
  prior art's credibility instead of claiming to be new. The genuine ~20% delta is
  the **application substrate**: git ancestry, glob-region leases, closed refusal
  enums for software-producing agents. A new *domain* for an old *idea*.

**The base rate is damning and specific (Front 4).** Every nearest neighbour died,
and **none died of low quality**:

- **CaMeL** (DeepMind, arXiv 2503.18813) — the *empirical tombstone*. A
  deterministic separated layer constraining a probabilistic agent, with *provable*
  guarantees DOS lacks, went **un-adopted in 10 months because the discipline costs
  up to ~30% task-completion utility with "no metric to quantify the benefit."**
  That is DOS's exact pattern and exact advisory-refusal trade, and it lost on the
  utility-vs-safety curve.
- **Cyc** — $200M, 40 years, an elegant internally-coherent *symbolic* tier the
  field routed around because the *probabilistic* approach scaled. The Bitter Lesson
  aimed straight at DOS's category.
- **Mesos / DC/OS** (the literal "Datacenter OS"), **AutoGPT / BabyAGI**,
  **LangChain** (being exited for raw SDKs) — "OS-for-X," agent-orchestration, and
  winning-abstraction deaths respectively. Failure modes: ecosystem absorption,
  utility cost, the too-minimal-core bet. Elegance and internal coherence are
  *uncorrelated with survival* in this category.

**Vendor-neutrality is the weakest leg, economically (Front 3).** The strategy
doc's *last-line structural defense* (§6.3: only a vendor-neutral referee is
durable) maps onto the **credit-rating-agency failure**: whoever pays the referee
captures it (issuer-pays → the 2008 FCIC "essential cogs"), and the structurally
honest *investor-pays* alternative **doesn't form** because verification is a public
good (free-riding; NBER w18923). The market's revealed preference is conflicted
*first-party* CI (GitHub Actions, vendor eval suites). Vendor-neutrality is a
**virtue, not a moat**.

**The honest counter-weight — Front 2 backfired in DOS's favour.** The strongest
self-verification paper, *LLMs Cannot Self-Correct Reasoning Yet* (Huang et al.,
ICLR 2024, arXiv 2310.01798), **confirms** DOS's grounding premise: intrinsic
self-correction without an external signal fails and *degrades* performance. The
surviving dent is narrower than the corpus fears — where a deterministic signal
exists, the agent can wield it *in-loop* (self-debug, +12%, Chen et al. 2304.05128),
so the seam is **useful, not necessary**; DOS overclaims only when it says
adjudication *must* be structurally separated.

## 2. Probe B — a blind external read (attack the self-grade)

Two memory-less agents, walled off from MEMORY.md and from the docs' own
self-grading sections.

- **Reader A (prose only)** graded the corpus independently at **~55–60%
  decoration** — vs. the corpus's own **~70% house style**. The *delta is the
  finding*: an outside reader thinks the corpus is *more* voluminous-with-decoration
  but *less* purely-fluff than its own audit claims, because it found a **checkable
  spine the self-audit underweighted** — the syscall code claims, the *datable*
  Dynamic-Workflows competitive comparison, the tri-field convergence with real
  arXiv IDs. It independently isolated the **same load-bearing claim** the whole
  identity rests on — *"verification is a trust property capability cannot erase"* —
  and flagged that it is **asserted as definitional exactly where it most needs to
  be empirical**, with the corpus's own §6.3 escape hatch (a vendor *could* ship a
  separated first-party verifier) already denting it from the side.
- **Reader B (code only — no prose, no README, no CLAUDE.md)** was asked "what is
  this, in one line?" and answered, unprompted: **"a reference monitor kernel,"**
  explicitly *rejecting* "workflow engine." It reached this purely from
  `oracle.is_shipped`, `arbiter.arbitrate`, `liveness.classify`, `scope.classify`
  being pure deterministic verdict functions with evidence gathered at the boundary,
  and from what is *conspicuously absent* (no DAG, no scheduler, no agent runner, no
  model calls in the kernel).

**Why B is the decisive probe.** Two agents — one reading only adversarial
*literature*, one reading only the *source* — **independently converged on the same
external category: reference monitor / runtime verification.** That convergence is
real evidence that the "real 30%" is real *in the code*, not merely coherent in the
prose. The corpus's coinage "symbolic adjudication tier" *names a true thing* — but
the honest external name already exists, and a cold reader of either the code or the
field finds it without the prose's help.

## 3. Probe C — foreign-repo evidence (manufacture the missing external datapoint)

The only probe that produces *new* evidence rather than re-reading old. `dos`
syscalls were run **out-of-the-box against repos DOS did not grow up in**, with no
`dos.toml`, spanning two foreign commit grammars: **Conventional Commits**
(`CloakBrowser`: `feat:`/`fix:`) and **bare-version** (`slack-helpers`: `v0.2.1:`).

- **`verify` survives contact — genuinely.** `dos verify CloakBrowser extension_paths
  feat` → `SHIPPED … 8fdaa5a (via grep)`. DOS verified a phase against a *public*
  convention it never grew up with, no config. The "domain-free truth syscall" claim
  is **real, demonstrated externally** — the strongest pro-thesis evidence of the
  session, and it is from outside the lattice.
- **The generic default is honestly partial, not universal.** On the bare-version
  grammar (`slack-helpers`), `doctor` reported *"none of your last 5 commits name a
  unit of work — no referee can check agent claims yet."* The grep rung **degrades
  honestly** (it admits it cannot parse `vX.Y.Z:`) rather than over-claiming — good
  — but this also *quantifies* "domain-free": conventional-commits **yes**,
  bare-version **no**. The claim is now measured, not asserted.
- **A real bug fell out (see §4):** `arbitrate` emits a **false reason string** on a
  foreign repo. This is the most useful single artifact of the whole exercise — the
  narration-vs-truth disease DOS exists to cure, found in DOS's own output, visible
  *only* by running it foreign.

---

## 4. The bug the exercise surfaced (`arbiter.py` false "was busy")

On a foreign repo whose lane taxonomy is the generic default `{global, main}`:

```
$ dos arbitrate --workspace /c/work/CloakBrowser --lane src
{"outcome":"acquire","lane":"main","auto_picked":true,
 "reason":"auto-picked free cluster lane 'main' (requested 'src' was busy).", …}

$ dos arbitrate --workspace /c/work/CloakBrowser --lane zzz_nonexistent   # zero leases
{… "reason":"auto-picked free cluster lane 'main' (requested 'zzz_nonexistent' was busy)." …}
```

`zzz_nonexistent` is a lane that **never existed in the taxonomy**, on a repo with
**no live leases** — yet the reason asserts it "was busy." The string at
`arbiter.py:522-523` hardcodes `(requested {requested_lane!r} was busy)` on the
auto-pick-grant branch, conflating two distinct causes:

1. the requested lane is real but **held** (genuinely busy), vs.
2. the requested lane name is **absent from the taxonomy** (the foreign-repo case).

Case 2 is false narration in the kernel that is built to refuse false narration —
the dogfood ritual (CLAUDE.md) wants the kernel's own output to be honest.

**Fixed (same session).** A `_redirect_why(default)` helper in `arbiter.py` computes
the known-lane universe once (`concurrent ∪ exclusive ∪ autopick ∪ trees ∪ aliases ∪
{global, orchestration}`, case-folded) and returns *"requested 'X' is not a lane in
this workspace"* when `X` is absent, else the genuine *"was busy"*. Applied at **both**
redirect sites (the ladder path and the legacy fallthrough). Pinned by
`tests/test_arbiter.py::TestRedirectReasonHonesty` (held-known still says "was busy";
unknown lane never does; honesty holds on the ladder branch too).

**The reproduction lesson (a dogfood win).** The first test draft asserted the wrong
entry path — it passed `requested_kind="cluster"`, but the CLI run that exposed the
bug used **no `--kind`** (`requested_kind=""`). With `job_config`, a *cluster*-kind
request for an unknown lane is **granted directly** (empty tree, "free — admitted"),
never reaching the redirect; only the **empty-kind** path falls through to it. So the
real reproduction is `requested_kind=""` — the exact `dos arbitrate --lane X` default.
*Testing the path you assumed instead of the path that broke* would have green-washed
the fix. (Aside worth its own look: a cluster-kind request for an unknown lane name
getting admitted with an empty/unknown blast radius is arguably a *separate* hazard.)
A secondary nit also stands: `arbitrate --json` produced no parseable stdout on these
runs while the non-`--json` path prints JSON anyway — `--json` is unrecognized or
dropping output; worth its own check.

---

## 5. The generalized verdict (what replaces "70% house style")

The aesthetic verdict — *"~70% of this is decoration"* — is an inside judgment that
external evidence can neither confirm nor refute. Replace it with a **claim-by-claim
external scorecard**, which is what "more general" actually means here:

| Load-bearing claim | External test applied | Result |
|---|---|---|
| The idea is novel / under-built | Prior-art search | **Refuted** — it is Simplex/RTA + reference-monitor + PCC, 25–50 yrs old; Parallax republished the LLM-agent form |
| It survives the bitter lesson (trust ≠ capability) | Self-correction literature | **Survives** — intrinsic self-correction fails (Huang 2024) *grounds* the premise; but "must be *separated*" overclaims (in-loop oracles work) |
| Vendor-neutral attestor is the durable moat | Attestation economics | **Refuted as a moat** — credit-rating capture + investor-pays-doesn't-form; it is a virtue, not a moat |
| Elegant N=1 abstraction will become a position | Base-rate search | **Against** — Cyc / Mesos / CaMeL / AutoGPT / LangChain all died, none of quality; CaMeL is the exact-pattern tombstone |
| `verify` is a domain-free truth syscall | Foreign-repo run | **Confirmed (partial)** — works on conventional-commits out-of-box; honestly abstains on bare-version |
| "It's a reference monitor, not a workflow engine" | Blind code read | **Confirmed** — independent code-only reader named it; prose's "symbolic tier" = a true thing with an older name |

**The one-paragraph generalization.** The durable core of DOS is real and it is
**older and humbler than the corpus says**: it is *runtime assurance / a reference
monitor for a fleet of code-writing LLM agents* — a 25-to-50-year-old pattern given
a genuinely new substrate (git ancestry, glob-region leases, closed refusal enums).
Naming it that is *more* defensible than "the symbolic adjudication tier," because it
**inherits** the prior art's external validation instead of asserting novelty. The
load-bearing strategic claim — *verification is a trust property capability cannot
erase* — **survives external attack** (the self-correction literature grounds it),
but two of its supporting legs **fail external attack**: novelty (refuted by prior
art) and the vendor-neutral moat (refuted by attestation economics + the CaMeL
adoption tombstone). And the deepest cut is not in the prose at all: running the
kernel against a foreign repo shows **even the "real 30%" carries a
narration-vs-truth gap in its own surface** (the false "was busy" reason), the same
disease docs/103 found in the memory store. The generalizing move, stated once: *you
cannot subtract house style with the pen that wrote it — you subtract it by handing
each load-bearing claim to a hostile outsider, the prior-art record, and a foreign
repo, and keeping only what they let you keep.*

---

## See also

- `dos-private/dispatch-os-symbolic-adjudication-tier.md` — the verdict this note
  externalizes (its §1 audit, §2.2–2.3 novelty legs, §6.3 vendor-neutral defense are
  the claims tested above).
- `docs/103_memory-is-an-unverified-agent.md` — the same move (re-verify frozen
  claims at read time) applied to the memory store; this note applies it to a
  strategy verdict.
- `docs/102_when-to-trust-an-agent.md` §6 — "beat the next-best on a named narrow
  cell, not own a quadrant"; the prior-art finding here is what *forces* that humbler
  framing (the quadrant is Simplex/RTA-shaped and 25 years occupied).
- `docs/100_native-spine-port-plan.md` — the structural-separation discipline the
  blind code reader detected (evidence at the boundary, pure verdict core).

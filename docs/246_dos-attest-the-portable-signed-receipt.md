# 246 — `dos_attest`: the portable, signed receipt

> **Status:** Phase 1 SHIPPED (the `Receipt` value type, the canonical serialization,
> HMAC sign/verify, `dos attest` + `dos verify-receipt`, `tests/test_attest.py`); the
> asymmetric (Ed25519) signer + `dos attest keygen` (Phase 2) and the MCP `dos_attest`
> tool (Phase 3) remain. This doc is the argument for the missing *non-participant*
> surface over the already-shipped `effect_witness` engine — a portable, signed
> **Receipt** a third party verifies WITHOUT trusting the agent or the operator — plus
> the genuine crypto decision the receipt forces and the phasing. It reuses the verdict
> logic wholesale: the four-valued `witness_effect` join and the `believe_under_floor`
> discipline already ship and are replay-tested. The *new* thing is **packaging + a
> caller-is-not-the-actor surface**, not a new verdict.
>
> **Phase 1 — what shipped (the kernel `dos.attest` module + two CLI verbs).** A frozen
> `Receipt` (the §2 fields) with `to_dict`/`from_dict` and a FIXED canonical
> serialization (§3.2) that commits to every field — including `witness_author`,
> `accountability_tier`, the `algorithm` token, and a versioned schema tag — but NOT the
> signature itself. `sign_hmac`/`verify_hmac` (stdlib `hmac` + `hashlib.sha256`, NO new
> dependency, constant-time `compare_digest`). `dos attest --claim … (--accept-cmd CMD |
> --before B --after A)` gathers an independent read-back at the boundary (the shipped
> `os_acceptance` / `state_diff` witnesses, resolved BY NAME so the kernel imports no
> driver), joins it via `witness_effect`, wraps + HMAC-signs the verdict (key from
> `--key-file` / `$DOS_ATTEST_KEY`), and exits the carried verdict (CONFIRMED 0 /
> REFUTED 1 / UNWITNESSED|NO_CLAIM 3 / contract-error 2). `dos verify-receipt --receipt
> PATH` (or stdin) is the third-party check: it re-derives the canonical bytes, checks
> the signature with the shared key alone, renders the carried verdict WITH its tier
> (REFUTED flagged ADVERSE, UNWITNESSED as explicitly non-adverse), and FAILS LOUD on a
> tamper/forge (INVALID, exit 1) — never a silent downgrade. The HMAC verify path is
> dependency-free, so `verify-receipt` ships in Phase 1 alongside `attest`; only the
> *asymmetric* signer is deferred to Phase 2. `tests/test_attest.py` pins the
> four-valued round-trip, the inherited floor (a forgeable-floor read-back → UNWITNESSED,
> never CONFIRMED), UNWITNESSED≠REFUTED, the sign→mutate-any-field→INVALID contract
> (including the tier-escalation chain-of-custody attack), and the kernel-names-no-host/
> vendor litmus.
>
> **One line:** Today `effect_witness.witness_effect(...)` returns a verdict
> (`CONFIRMED` / `REFUTED` / `UNWITNESSED` / `NO_CLAIM`) — but it returns it *to the
> loop*. There is no surface where an **auditor, inspector general, counterparty, or
> allied partner** is handed a `(claim, independent read-back)` and receives a
> **portable certificate it can check on its own**. `dos_attest` mints that
> certificate: it wraps `witness_effect`, signs the verdict together with *which
> witness authored the read-back and at what accountability tier*, and emits a
> `Receipt` a skeptic verifies with the public/shared half alone. The DocuSign step —
> turning a private check into a record a non-participant can verify — applied to the
> kernel's existing notary engine.
>
> **Lineage.** The **WHY** is strategy, and this plan does not restate it — it points
> to it. `../dos-private/dispatch-os-the-notary-for-agent-work.md` §6 names
> `dos_attest` as *the one concrete build the notary frame demands* (and §1 / §7.1 is
> the honest-scope ceiling, §7.2 the evidentiary-not-legal limit);
> `../dos-private/dispatch-os-national-security.md` §3 is the provenance/custody rung
> — *"chain of custody is the byte-author ≠ agent doctrine, renamed,"* and *"the buyer
> of attestation is never the actor — it is the future skeptic"* — and its §6 step 1
> sequences this as the **first** accreditation move, the place FIPS-validated crypto
> first enters DOS. The **HOW** — the value type, the CLI verb, the verify path, the
> MCP tool — is this doc. The **engine** it packages is `effect_witness` (docs/181,
> `src/dos/effect_witness.py`) over the evidence floor (docs/179/138,
> `src/dos/evidence.py`). Siblings in the same security/national-security build
> cluster: docs/125 (trifecta color → its enforcement is docs/126), docs/247 (the
> clearance lattice), docs/248 (instruction provenance) — each a `docs/NN` plan
> delivering the HOW for a build a strategy doc named. The accreditation/control-
> mapping plan that this receipt is the cryptographic on-ramp for (FIPS path, NIST SP
> 800-53 AU-/SI- mapping, an ATO sequence) is its sibling **[docs/249](https://github.com/anthony-chaudhary/dos-private/blob/master/249_the-accreditation-surface-mapping-the-verdicts-to-controls.md)** (national-
> security §6 steps 2–4; now in the `dos-private` repo — later `docs/249` mentions
> here refer to it there); §3.3 below references it.

---

## 0. The gap, stated once

`effect_witness.witness_effect(claim, readbacks)` already does the hard, soundness-
load-bearing part: it joins **two independently-authored facts** — the agent's
*claim* (the forgeable floor, `AGENT_AUTHORED`) and an independent *read-back* of
world state (a witness whose byte-author is not the agent) — and returns a four-valued
verdict whose trust is **capped by the read-back's accountability**. A forgeable
read-back can never reach `CONFIRMED`; that ceiling is enforced structurally by
`evidence.believe_under_floor`, in one place, not re-implemented here.

But the verdict is returned **to the caller** — to the loop, or to an operator
running `dos verify` over their own fleet. Inventory the surfaces that consume it
today: a Python return value, the `dos.drivers.state_diff` / `dos.drivers.os_acceptance`
CLIs (which print a verdict for the operator at the terminal), and — by their
*absence* — the MCP server (`src/dos_mcp/server.py` exposes `dos_verify` /
`dos_arbitrate` / `dos_doctor` / `dos_recall`; it does **not** expose
`witness_effect`). **Every one of those presumes the caller is the agent or its
operator** — a party *inside* the loop, supervising its own work.

The missing surface is the **non-participant** one. A notary's value is not the SHA;
it is that *the party holding the record is neither signer.* There is no DOS surface
where someone who was **not present** — an auditor at quarter-end, an inspector
general, a counterparty in an agent-to-agent transaction, an allied partner verifying
a shared system — is handed `(claim, independent read-back)` and receives a
**portable certificate they can verify without access to the agent, the operator, or
the original loop.** That certificate is the gap this plan fills. It is precisely the
distance between *"I checked"* (a private return value) and *"here is proof anyone can
check"* (a record a skeptic verifies for themselves) — the distance between a
`git log` and a notary stamp.

---

## 1. Why this reuses `effect_witness` wholesale — the verdict logic is NOT re-written

The load-bearing economy of this plan, identical in spirit to docs/126 §2 (*"the same
verdicts, made binding — not new policy"*): **`dos_attest` writes no new decision
logic.** Three facts about the *current* kernel make the receipt a packaging layer,
not a subsystem:

1. **The verdict already exists, four-valued and frozen.** `witness_effect` returns
   an `EffectWitnessVerdict` (`src/dos/effect_witness.py`) with exactly the fields a
   certificate needs and no more: `verdict` ∈ {`CONFIRMED`, `REFUTED`, `UNWITNESSED`,
   `NO_CLAIM`}, `believe` (True only on `CONFIRMED`), `refuted` (surfaced separately
   so a consumer may red-flag), `claim_key`, `narrated`, `witness` (the read-back's
   `source_name`), and `accountability` (the read-back's rung). It already has
   `.to_dict()`. The receipt is that dict, *plus a timestamp and a signature.*

2. **The floor discipline is already structural and lives in one place.** A receipt
   must never overclaim, and the one thing it must never do is mint a `CONFIRMED` for
   an effect that did not happen. That guarantee is not something `dos_attest`
   re-asserts — it is inherited: `witness_effect` delegates belief to
   `evidence.believe_under_floor`, which grants belief **only** when a NON-FORGEABLE
   read-back (`OS_RECORDED` / `THIRD_PARTY`) attested. A receipt signed over a
   forgeable-floor read-back is, by construction, an `UNWITNESSED` (or, on a positive
   disconfirmation from an accountable witness, a `REFUTED`) — never a `CONFIRMED`.
   The notary cannot be one of the signers, and that is enforced upstream of the
   signature, not by it.

3. **The read-back authors already ship as drivers.** A receipt carries *which
   witness re-read the world and at what rung*. Those witnesses already exist:
   `dos.drivers.os_acceptance` (the kernel runs a command, the **OS** authors the
   exit code → `OS_RECORDED`) and `dos.drivers.state_diff` (the kernel snapshots a
   state surface before/after, the **store** authors the delta → `OS_RECORDED`, or
   `THIRD_PARTY` for a remote store). `dos_attest` does not invent a witness; it
   *records the witness's name and tier into the signed payload* so a third party can
   see — and a future, richer verifier can re-run — the surface the verdict rests on.

So the build is: a `Receipt` value type (the verdict dict + timestamp + signature), a
signer, a verifier, and the surfaces that emit/check them. The verdict the receipt
carries is `witness_effect`'s, untouched. The litmus for whether a proposed addition
belongs in this plan is docs/126 §2's, restated: **if it changes the verdict rather
than packaging it, it is not this doc.**

---

## 2. The Receipt shape

The certificate is a small, closed record — every field is either echoed from the
`EffectWitnessVerdict` or added by the act of signing:

```
Receipt {
  claim               # the opaque effect key the agent asserted (EffectClaim.key)
  narrated            # the agent's original phrasing — shown, never parsed for truth
  witness_surface     # the read-back subject (the command run / the state-key probed)
  witness_author      # the witness source_name (e.g. "os_acceptance", "state_diff")
  accountability_tier # the read-back's rung: OS_RECORDED / THIRD_PARTY / AGENT_AUTHORED
  verdict             # CONFIRMED | REFUTED | UNWITNESSED | NO_CLAIM
  timestamp           # when the attestation was minted (RFC 3339, UTC)
  signature           # over a canonical serialization of all the above
}
```

It is verifiable by a third party holding the **public/shared half** of the signing
key, **without** access to the agent, the operator, or the original loop. Three
properties are load-bearing and each is a deliberate constraint, not a nicety:

**2.1 The signed payload includes the witness's author and tier, not just the
verdict token.** A bare signed `CONFIRMED` is unfalsifiable theatre — it tells a
skeptic nothing about *what was checked.* The receipt signs `witness_author` and
`accountability_tier` *into* the payload so the skeptic reads the verdict **together
with the rung it stands on**: a `CONFIRMED` at `OS_RECORDED` (the OS authored the
exit code) is a different evidentiary object than a `CONFIRMED` at `THIRD_PARTY` (a
counterparty's API confirmed it), and a verifier can apply its own policy to the tier
(*"I accept `THIRD_PARTY` from this issuer; I do not accept anything lower"*). The
tier is the chain-of-custody field — national-security §3's *"who/what witnessed
this, provably."*

**2.2 `REFUTED` is the load-bearing receipt.** The notary frame's whole point is the
*adverse* certificate: a confidently-narrated success the world does not corroborate,
**made portable.** A `REFUTED` receipt is the silent frontier-fail (docs/177) turned
into a record a counterparty can hold up — *"your agent claims it issued the refund;
here is a signed, independently-witnessed certificate that the refund is absent from
the ledger."* This is the receipt a dispute, an audit, or an after-action review
actually turns on, and the design must make it as easy to mint and as cryptographically
solid as `CONFIRMED`.

**2.3 `UNWITNESSED` must stay LOUD and stay distinct from `REFUTED` — a notary may
never overclaim.** This is the single most important honesty rule in the plan, and it
is the one thing a notary may *never* do (notary §6). `UNWITNESSED` means *"no
accountable witness could be reached, OR the only read-back was on the forgeable
floor"* — **could-not-tell**. `REFUTED` means *"an accountable witness re-read the
world and the effect is ABSENT"* — **checked-and-absent**. Collapsing the two would
let a notary that simply *failed to reach a witness* emit a certificate that reads as
*"the effect did not happen,"* which is a false adverse finding — the notary
overclaiming in the adverse direction. The receipt keeps them as separate verdict
tokens (they already are, in `_Verdict`), and the verifier surface (§4) renders
`UNWITNESSED` as a visibly distinct, non-adverse outcome. A receipt that cannot tell
must *say* it cannot tell.

---

## 3. The genuine design decisions

Two things this plan must decide before code, because they are not mechanical. (The
rest — the value type, the CLI plumbing, the JSON shape — follows the existing
`to_dict()` / CLI conventions and is not a decision.)

### 3.1 HMAC shared-secret vs. asymmetric signature — and *who the verifier is* decides it

The receipt's verifier is, by the entire premise of this doc, **a third party who was
not present.** That party's relationship to the issuer determines the crypto, and the
two cases are genuinely different:

* **HMAC (shared secret).** Cheap, stdlib-only (`hmac` + `hashlib`, already in the
  kernel's dependency set — `hashlib.sha256` is used in `home.py`, `posttool_sensor.py`,
  `rewind.py`, `env_print.py` today, so this adds **no** new dependency and keeps the
  PyYAML-only core intact). It is the right tool when the verifier **shares a secret
  with the issuer** — an internal auditor, a same-org oversight function, a CI gate.
  It is the literal "Tool Receipts — an HMAC receipt the LLM cannot forge" shape the
  `effect_witness` module header already cites. **Its hard limit:** anyone who can
  *verify* an HMAC receipt can also *forge* one (the secret is symmetric). So HMAC
  cannot serve the load-bearing notary case — *prove an effect to a counterparty who
  does not, and must not, hold your secret.* A receipt the verifier could have minted
  themselves is a self-signed cert, which is exactly what the category exists to
  forbid (notary §7.4).

* **Asymmetric signature (public-key).** For a **third party who does not share a
  secret** — the counterparty, the regulator, the allied partner — verification must
  use the **public half** while only the issuer holds the private half. This is the
  DocuSign property: the verifier can check, and *cannot* forge. It needs a signing
  primitive the near-stdlib kernel does not have (Ed25519 / ECDSA via the
  `cryptography` package, or equivalent), so it arrives **behind an extra**
  (`[attest]`), exactly as `mcp` lives in `[mcp]` and the Slack transport in
  `[notify-slack]` — the kernel core stays PyYAML-only, the crypto dependency is
  opt-in. This is the surface that makes the notary frame real, and it is therefore
  the one that gates accreditation.

**Decision:** ship **HMAC in Phase 1** (zero new dependency, immediately useful for
the same-org auditor / CI gate, proves the value type and the verify path), and
**asymmetric signing in Phase 2** (the true non-participant case, behind the
`[attest]` extra). The signing primitive is a strategy chosen by a flag/config
(`--sign hmac` / `--sign ed25519`), the same kernel/driver split the rest of DOS uses
— the *which-algorithm* is policy at the boundary; the *what-is-signed* (the canonical
Receipt payload) is fixed mechanism.

**FIPS is where accreditation first enters the kernel.** National-security §6 step 1
is explicit: `dos_attest` is *"also where FIPS-validated crypto first enters (the
signing path)."* Today DOS has **no signing path at all** (it hashes with stdlib
`hashlib` for content-addressing — `rewind.py`, `posttool_sensor.py` — but signs
nothing). So this plan introduces the first byte of crypto that an accreditor will
test, and the asymmetric path must be implementable against a FIPS-validated provider.
That is a constraint on the Phase-2 dependency choice (the `cryptography` backend can
target OpenSSL's FIPS module), **not** a Phase-1 blocker. The control-mapping /
ATO work that consumes this is its sibling **docs/249** (national-
security §6 steps 2–4); see §3.3.

### 3.2 The canonical serialization is part of the signature contract

A signature is only checkable if the issuer and the verifier serialize the payload
**byte-identically** before signing/verifying. This is a real decision because a naive
`json.dumps` is not canonical (key order, whitespace, unicode escaping all vary). The
plan fixes a canonical form once — sorted keys, no insignificant whitespace, UTF-8,
explicit field ordering — and signs over *that*. The verifier reconstructs the same
canonical bytes from the receipt's fields and checks the signature against them. A
receipt whose canonical re-serialization does not match its signature is **invalid**,
loudly (§4) — never silently downgraded to "unsigned but probably fine." This is the
one place where a serialization bug is a security bug, so it is specified, pinned by a
round-trip test (sign → mutate one field → verify must fail), and not left to a
library default.

### 3.3 Honest scope — the receipt attests PRESENCE at a tier, never CORRECTNESS

This is the Wall §3 ceiling (`docs/204`, Wall §3 — *presence, not goal*), and it is
inherited unchanged from the engine: `witness_effect` verifies **claim ⊆
witnessed-delta** (was the specific change the agent took credit for actually made?),
**not** *"is the end-state globally correct / wise / intended?"*. A `Receipt` is a
notarized statement of *presence at an accountability tier and a time* — exactly the
scope a notary has always had (*this party signed this document on this date*; it says
nothing about whether the deal was good). The notary doc leads with this limit (§1)
precisely so the analogy cannot be read as overclaiming, and this plan does the same:

* The receipt certifies *the specific effect the agent took credit for is really
  there* (or is really absent, or could-not-be-witnessed). It does **not** certify
  the effect was the right thing to do.
* Correctness-of-intent routes where it always has in DOS: ORACLE → JUDGE → HUMAN
  (`docs/86`). The receipt covers the *existence* question — the one that turns into a
  dispute — and explicitly cedes the *correctness* question.
* The legal-vs-evidentiary limit (notary §7.2): a `dos_attest` receipt mints
  **evidentiary** weight (a tamper-evident, independently-authored record), **not
  legal** weight. DocuSign began evidentiary and accreted legal standing over years
  *because the evidentiary artifact was good*; the play is the same — ship the honest
  evidentiary primitive, let standards/regulation attach where the stakes demand
  (the FIPS/control-mapping/ATO sequence, sibling **docs/249**).

---

## 4. Phase plan

**Phase 1 — the `Receipt` value type + `dos attest` (HMAC, the smallest useful core).**
- A `dos.attest` kernel module: a frozen `Receipt` dataclass (the §2 fields) with
  `.to_dict()` / `.from_dict()` and the **canonical serialization** (§3.2). It is
  pure — it takes an already-computed `EffectWitnessVerdict` plus a clock, and produces
  the unsigned payload. (Signing is the one boundary step, see below.)
- A `dos attest` CLI verb (mirroring the `dos.drivers.state_diff` / `os_acceptance`
  CLIs): it gathers a read-back at the boundary (via an evidence source — the same
  `gather_evidence` path the drivers use), calls `witness_effect`, wraps the verdict
  in a `Receipt`, signs it with **HMAC** (`--sign hmac`, key from `--key-file` /
  `$DOS_ATTEST_KEY`), and prints the receipt (`--json` for the machine shape). The
  exit-code map matches `dos verify` / the witness drivers: `CONFIRMED`→0,
  `REFUTED`→1, `UNWITNESSED`/`NO_CLAIM`→3.
- `tests/test_attest.py`: `CONFIRMED`/`REFUTED`/`UNWITNESSED`/`NO_CLAIM` each round-
  trip through `to_dict`/`from_dict`; a forgeable-floor read-back yields `UNWITNESSED`
  not `CONFIRMED` (the floor inheritance, proved at the receipt layer too); the
  canonical-serialization round-trip (sign → mutate one field → verify FAILS); the
  `kernel-imports-no-host` litmus (the module names no host, no vendor).

**Phase 2 — `dos verify-receipt` + asymmetric signing + key management.**
- `dos verify-receipt` (the third-party surface, NO loop access): given a `Receipt`
  and the **public/shared half**, it re-derives the canonical bytes and checks the
  signature, then renders the verdict **with its tier** — and renders `UNWITNESSED`
  as a visibly distinct, non-adverse outcome (§2.3). It verifies the *signature and
  the tier*; it does **not** re-run the witness (that is a richer future verifier, and
  is out of this phase). Invalid signature → loud failure, never a silent downgrade.
- Asymmetric signing (`--sign ed25519`) behind the **`[attest]` extra** (the
  `cryptography` dependency, FIPS-targetable per §3.1) so the kernel core stays
  PyYAML-only. Key generation/rotation helpers (`dos attest keygen`) and the
  documented key-distribution shape (issuer holds private; verifier holds public).
- Tests: a receipt signed with the private half verifies with the public half and
  fails with the wrong public half; an HMAC receipt and an Ed25519 receipt are both
  verifiable through `verify-receipt`; tamper detection on every field.

**Phase 3 — the MCP `dos_attest` tool (the non-participant surface).**
- A `dos_attest` MCP tool in `src/dos_mcp/server.py` (the lowest-friction adoption
  surface; the strategy doc names this surface's *absence* as the concept's ceiling —
  notary §3.3). Input: a `claim` (opaque effect key) + the means to obtain an
  **independent read-back** (a witness surface the caller does not control). Output:
  the signed `Receipt`, JSON over stdio. It resolves its served workspace via the same
  `SubstrateConfig` seam as every other MCP tool (explicit `workspace` arg ›
  `DISPATCH_WORKSPACE` › cwd, never `__file__`) and passes the built config explicitly
  into the syscall — correct for a long-lived server fielding concurrent workspaces.
  This is the surface where the caller is *not* the actor being judged.
- Tests: the MCP tool returns a verifiable receipt; `verify-receipt` accepts it; the
  server litmus (`tests/test_mcp_server.py`) stays green; the kernel still never
  imports `dos_mcp`.

(The phasing mirrors docs/125/126: a cheap, dependency-free, immediately-useful core
first; the dependency-bearing and surface-exposing steps after; the
accreditation-consuming work named but deferred to its own doc.)

---

## 5. What this is NOT (the litmus, so the build stays in its lane)

- **NOT a new verdict.** `dos_attest` reuses `effect_witness.witness_effect` and
  `evidence.believe_under_floor` verbatim — the four-valued verdict and the floor
  discipline are *not* re-implemented. The receipt is the verdict *packaged and
  signed*. If a proposed change touches the verdict logic rather than the packaging,
  it is docs/181, not this doc (the docs/126 §2 litmus, restated: *no certificate
  without a pre-existing pure verdict behind it*).
- **NOT legal force — evidentiary only.** A receipt is a tamper-evident,
  independently-authored record (evidentiary weight), **not** a notarization with
  legal standing conferred by the state (notary §7.2). It is the honest starting
  position DocuSign itself started from; legal/accreditation standing attaches later,
  where the stakes demand it (docs/249).
- **NOT a key-management product.** Phase 2 ships the *minimum* key handling a signed
  receipt requires (generate, distribute the public half, rotate) — not a KMS, not a
  PKI, not a certificate-authority hierarchy. A deployment that needs enterprise key
  management brings its own; `dos_attest` consumes a key, it does not manage a key
  estate.
- **NOT host-coupled.** The module names no host directory, no host lane, no host
  commit prefix, and no vendor as a code identifier — the `kernel imports no host`
  and `kernel names no vendor in code` litmus tests hold, pinned the same way
  `test_self_modify_*` and `test_vendor_agnostic_kernel.py` pin their guards. The
  effect-key grammar, the witness surface, and the signing key are all caller/config
  inputs; the receipt mechanism is generic.
- **NOT a place where failure is silent.** Every other DOS verdict degrades *quietly*
  toward abstain (the fail-safe-never-fail-open posture: a witness that cannot read
  produces `NO_SIGNAL`). The **signature path is the one place that must fail LOUD**:
  an invalid signature, a tampered field, or a canonical-serialization mismatch makes
  the receipt **invalid**, surfaced as such — never downgraded to "unsigned but
  probably fine," never silently accepted. A notary whose stamp is forgeable-without-
  detection is not a notary; the loud-failure rule is what makes the certificate worth
  signing.

The whole plan is one sentence made buildable: *we built the notary
(`effect_witness`) and described it by the stamp; `dos_attest` mints the certificate —
the verdict, plus which non-forgeable witness saw it and at what tier, signed so a
skeptic who was not there can verify it without trusting the agent or the operator,
and loudly refuse a forgery — which is the one surface that makes the kernel's reach
match its generality.*

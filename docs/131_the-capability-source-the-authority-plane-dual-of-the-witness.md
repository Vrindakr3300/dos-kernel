# 131 — The capability source: the authority-plane dual of the witness, and why a counterparty grant is a lease pointed outward

> **[`121`](121_first-class-on-devices-and-unattended.md) and
> [`129`](129_the-apply-confirmation-as-the-proving-ground-for-non-git-evidence.md)
> established the *evidence* half of the counterparty asymmetry: the un-forgeable
> witness for an outward effect is whoever *received* it, because the agent can
> narrate the effect but cannot author the receiver's record of it. There is an
> exact dual the two notes flagged but did not develop. The same party that can
> author bytes the agent can't *after* an effect (the confirmation) can author
> bytes the agent can't *before* one (a login session, an OTP, an issued
> credential, a session cookie) — and those bytes are not a *proof* that something
> happened, they are a *capability* the agent must present to be *permitted to
> act at all*. The reference userland app already implements the full taxonomy —
> an auth-probe that classifies the gate, an acquisition ladder (SSO > vault creds
> > new-SSO-bind > create-account > emailed OTP), and a per-`(company, ATS)`
> cookie store that persists the session and *invalidates it on failure*
> (`agents/config_pkg/apply_auth_walls.py`, `apply_login.py`, `apply_cookie_store.py`,
> `inbox_otp.py`). Read structurally, an external capability is a **lease the
> counterparty grants**: time-bounded, revocable, presented-to-act, and minted by
> a party the agent does not control. That makes the `CapabilitySource` not a new
> idea but `arbitrate` pointed *outward* — and it slots into DOS as the
> authority-plane sibling of the `EvidenceSource` seam, with the same
> trust-the-minter-not-the-asker floor that makes the lease arbiter safe.**

Status: theory + spec note, the authority-plane companion to
[`121`](121_first-class-on-devices-and-unattended.md) (the evidence seam) and
[`129`](129_the-apply-confirmation-as-the-proving-ground-for-non-git-evidence.md)
(the shipped witness proof). It develops the §4/§6 "open thread" 129 named. Like
129 it argues from a *shipped* userland system rather than from design; nothing new
is built here. §1–§3 are the argument; §4 sorts the verb through the four-gate test
and places it; §5–§6 are the buildable shape + the disciplines; §7 is the honest
residue. The userland specifics (Gmail, ATS auth walls, SSO) stay userland; the
*shape* — "a counterparty-minted, revocable token presented before an effect" — is
the kernel's.

The job-search fleet is the reference userland app (CLAUDE.md); this note cites its
code as a downstream consumer, never a dependency (the one-way arrow).

---

## 1. The symmetry the evidence notes half-stated

[`129 §4`](129_the-apply-confirmation-as-the-proving-ground-for-non-git-evidence.md)
noticed that the inbound-counterparty channel is used at *both* ends of a run and
named the two ends but did not work the second out:

- **A witness is a counterparty artifact consumed *after* an effect** — proof the
  thing happened, the input to `verify()`. (The ATS confirmation email; the bank
  receipt; the cloud control-plane state.) This is the evidence plane,
  [`121 §2.1`](121_first-class-on-devices-and-unattended.md).
- **A capability is a counterparty artifact consumed *before* an effect** — a
  token the agent must *present* to be *allowed* to act. (The login session; the
  OTP that gates submit; an issued API credential; the session cookie.) This is
  the **authority plane**.

The deep fact is one asymmetry with two faces: **the counterparty controls bytes
the agent cannot forge, and that control is leverage at both ends of the effect.**
After the effect, the bytes are *evidence the kernel trusts more than the agent's
claim*. Before the effect, the bytes are *authority the agent cannot manufacture
for itself*. [`121 §1`](121_first-class-on-devices-and-unattended.md)'s
before/during/after framing of a run already had a slot for this — the **before**
moment is `arbitrate` ("may I act?") — and the capability source is what fills it
when the gate is held by an *external* party rather than the internal lease table.

This matters most in exactly the [`121`](121_first-class-on-devices-and-unattended.md)
regime — unattended, on a device, close to a real effect. An unattended agent that
cannot obtain a capability must not *pretend* it did and proceed (the open-loop
failure); and a capability offered by an *untrusted* minter must be *refused*, not
consumed (an attacker who emails a fake "OTP" must not be able to drive the agent's
submit). Both are authority-plane statements of the same distrust the kernel runs
on the evidence plane.

## 2. What the userland app already built — the full auth-wall taxonomy, not just OTP

[`129`](129_the-apply-confirmation-as-the-proving-ground-for-non-git-evidence.md)
cited `inbox_otp.py` as the worked example. The reality is broader and sharper: the
apply fleet has a complete **out-of-band authentication** subsystem
(`agents/config_pkg/apply_auth_walls.py`, the R4 carve), and its structure *is* the
seam. Its own docstring states the shared architectural problem precisely:

> "the apply agent lives in-browser, but many ATS gates require reading the
> candidate's inbox (login verification emails, post-submit OTP codes,
> create-account confirmation codes). They compose sequentially inside a single
> apply attempt."

Three sub-mechanisms, and each maps to a piece the `CapabilitySource` seam needs:

1. **The auth probe — classify the gate *before* spending budget.**
   `apply_auth_probe_*` "classifies auth state before burning Scout budget on a
   login-walled page." This is the capability analogue of
   [`129 §5.2`](129_the-apply-confirmation-as-the-proving-ground-for-non-git-evidence.md)'s
   "does a witness exist here?" — the *before*-side question is **"what capability
   does this effect require?"** A `CapabilitySource` must first answer *which* gate
   is present (none / login / OTP / account-creation), because the wrong answer
   wastes the run or walks it into a wall.

2. **The acquisition ladder — graded ways to obtain a non-forgeable capability.**
   The login micro-phase runs a strict preference order: **SSO > vault creds >
   new-SSO-bind > create-account (with Gmail round-trip)**, and the post-submit
   path adds the **emailed OTP** wall. Read this as an accountability ladder, the
   authority-plane twin of
   [`129 §2`](129_the-apply-confirmation-as-the-proving-ground-for-non-git-evidence.md)'s
   A/B/C/D: SSO (a federated identity provider mints the session — strongest, the
   agent never holds the secret) ranks above a stored credential the agent
   presents, which ranks above creating an account, with the emailed OTP as the
   counterparty's live challenge. **Same shape as the witness spectrum: graded by
   how little the agent has to be trusted with.**

3. **Persistence + invalidation — a capability has a lifetime.**
   `apply_cookie_store.py` persists the CDP session per `(company, ATS)` so a
   repeat apply "skip[s] re-auth," `save_cookies` on success, and crucially
   **`invalidate_cookies` runs post-submit on FAILED.** A capability is acquired,
   cached, *and revoked when it goes bad.* That is not an evidence property at all
   — evidence is immutable once observed. **It is a lease property:** grant, hold,
   expire, revoke. (The store is careful that cookies are "non-secret
   session-state," routed as plain JSON, *not* through the broken
   `creds_vault.set_credential` — the seam must distinguish a *secret* credential
   from a *session capability*; they have different substrates and lifetimes.)

The OTP path's own guard-rails (from
[`129 §4`](129_the-apply-confirmation-as-the-proving-ground-for-non-git-evidence.md)
plus the full read) complete the picture and are the *floor* the seam needs:

- **A trusted-minter allowlist.** `inbox_otp.py` will only accept a code from a
  sender on `otp_sender_domains` (defaulting to the known ATS domains —
  `greenhouse.io`, `lever.co`, `workday`, …), with subdomain matching for
  tenant senders (`waymo.mail.clinchtalent.com`). "Callers cannot poll an
  unfiltered inbox." **The agent accepts a capability only from a minter it was
  told to trust.**
- **Unmapped minter → refuse, don't consume.** A code from a sender *not* on the
  allowlist emits an `otp_unmapped_sender` failure (`_emit_unmapped_sender`,
  AAR8) rather than being silently used. **An unrecognized issuer is a typed
  refusal, not a free capability.**
- **Honest retry.** The cursor "does not suppress results … so the apply agent's
  retry loop stays honest" — a capability fetch must not lie to the loop about
  freshness (the [`99 §2.3`](99_runtime-validation-and-the-actuation-boundary.md)
  no-self-deception instinct).
- **Fail-safe degrade.** A missing/malformed allowlist degrades to hardcoded
  defaults and "never raises … rather than breaking the apply path."

## 3. The deep claim: an external capability is a lease the counterparty grants

The kernel already owns a model of "may I act?" — the lease arbiter
([`89`](89_the-lane-is-a-region-lock.md): a lane is a leased range-lock; `arbitrate`
is the lock manager). The whole of §2 is that *same model with the granting party
moved outside the process*:

| Lease property (the internal `arbitrate`) | The external capability (auth wall) |
|---|---|
| A grant authorizes an action over a region | A session/OTP authorizes the submit on this ATS |
| Time-bounded (TTL) | The session/cookie expires; the OTP is single-use, short-lived |
| Revocable | `invalidate_cookies` on FAILED; the ATS can revoke the session |
| Held in a table the *asker does not control* | Minted by the counterparty (SSO IdP, the ATS mailer) — the asker *especially* doesn't control it |
| Granting party is trusted; the asker is not | The minter is trusted (allowlist); the agent presenting it is not |
| Refuse if the region is contended / budget exhausted | Refuse if the minter is unrecognized (`otp_unmapped_sender`) |

The correspondence is exact enough to be more than analogy: **a `CapabilitySource`
is `arbitrate` pointed outward.** Internally the kernel adjudicates a claim on a
*region of files*; on the authority plane the *counterparty* adjudicates a claim on
*the right to affect their system*, and the kernel's job is not to grant it (it
can't — it doesn't hold the ATS's session table) but to (a) *recognize which
capability is required*, (b) *obtain it only from a trusted minter*, (c) *present
it*, and (d) *track its lifetime and revoke it when stale* — exactly the lease
lifecycle, with acquisition delegated to a driver that speaks the counterparty's
protocol.

This is why the capability source belongs next to the evidence source and not
folded into it: **evidence is read and is immutable; a capability is leased and has
a lifecycle.** The witness law answers `verify`; the capability law answers
`arbitrate` — the two planes [`121 §1`](121_first-class-on-devices-and-unattended.md)
already separated as *after* vs *before*.

### 3.1 No novelty claim — this is a crowded, standards-track field (external check, June 2026)

A June-2026 landscape sweep (the `dos-strategy`
`dispatch-os-aaa-agent-trust-landscape-2026-06` essay) makes one thing
unambiguous: **the capability/authority plane is a crowded, well-funded,
standards-track field, and this note must claim *zero* invention on it.** The
"counterparty-minted, scoped, revocable token the agent must present; trust the
minter, not the asker" framing is convergent with — not ahead of — a live cluster:
the IETF `draft-klrc-aiagent-auth` (authors from OpenAI/AWS/Okta/Ping/Zscaler) and
the OAuth identity-chaining + ID-JAG drafts (the cross-trust-domain delegation
standard), MCP's merged RFC-9207 `iss`-validation (minter-binding as a spec
requirement), Microsoft Entra **Agent ID** (GA, a credential-less agent whose
authority lives on a "blueprint" minter), Okta/Auth0's Agent-as-Principal +
On-Behalf-Of + Auth-for-MCP, and the MIT-licensed Cubitrek **Agent Passport**
(an Ed25519/DNS-anchored authority declaration with a hard spend ceiling + an
SLA'd human-in-loop threshold). So the contribution of this note is **not** the
capability primitive; it is (a) the *recognition that it is `arbitrate` pointed
outward* (the lease-lifecycle framing, §3), and (b) its pairing with the
**effect-witness** law as the half the standards stack does *not* cover — every
one of those efforts authorizes the *call* (grants standing at admission) and is
silent on adjudicating whether the agent's claimed *effect* actually happened.
DOS's place is the effect-witness complement that **rides** these standards, never
a competitor to them. (Same lesson as `dos/docs/104`: convergence validates the
frame; vendor-neutrality, not novelty, is the only durable edge.)

## 4. Placing the verb — the four-gate sort ([`85 §2`](85_extending-the-verifiable-surface.md))

Run a `CapabilitySource` through the same test
[`94 §4.4`](94_checkpoints-and-recovery-from-slop.md) /
[`99 §5.1`](99_runtime-validation-and-the-actuation-boundary.md) use to place a
verb:

- **Gate 1 — a claim about ground-truth state? → DELIBERATELY FAILS.** Obtaining a
  capability does not *answer* a question about the world; it *acquires authority*
  to change it. Like `arbitrate`/`halt`, it produces no belief that can be true or
  false. Failing Gate 1 is the signal it is **not a verdict** — it is a
  `spawn`/`reap`/`arbitrate`-family boundary verb, a *cousin* of the `verdict.py`
  contract, never a registered classifier.
- **Gate 2 — evidence unforgeable by the agent? → PASSES (this is the whole
  point).** The capability is minted by the counterparty/trusted issuer; the agent
  cannot author it. A capability the *agent* could mint is not a capability — it is
  `--force` (the floor is the allowlist: the minter must be a party other than the
  asker, the authority-plane statement of "trust is non-self-certifiable").
- **Gate 3 — domain-free? → PASSES by contract, exactly as `halt` does.** The
  kernel branches on **nothing** about *how* the capability is obtained: SSO,
  vault, OTP, cookie restore are all driver-specific protocols. The kernel holds
  an **opaque capability handle** (a token/session reference — a string), the
  *trusted-minter policy* (an allowlist, declared in config), and the *lifecycle*
  (acquired / presented / expired / revoked). A grep of the kernel verb for
  `imap` / `oauth` / `cookie` / `sso` returns nothing — the same split as
  `supervise` emitting a REAP that names only a lane while the driver owns the
  platform eviction.
- **Gate 4 — mechanical closed-enum verdict? → N/A.** It is not a verdict; its
  output is a `CapabilityGrant` record (handle / minter / acquired-at / expiry /
  state), pure data — consistent with `HaltResult`/`LanePlan` being data, not a
  `TypedVerdict`.

**Sort:** fails Gate 1, passes Gate 3 → an `arbitrate`/`reap`-family **boundary
verb + a seam**, with a *pure* recognizer (which capability is required) and a
*driver* acquirer (how to get it). The kernel ships the protocol + the
trusted-minter floor + the lifecycle; **the acquisition is always a driver**,
because it needs the counterparty's domain knowledge — precisely
[`99 §3`](99_runtime-validation-and-the-actuation-boundary.md)'s reason the kernel
doesn't kill a process restated for the authority plane.

## 5. The buildable shape (sketch — the spec lives with [`121 §5`](121_first-class-on-devices-and-unattended.md)'s seam)

- **`dos.capabilities` (kernel seam).** A `CapabilitySource` Protocol with two
  pure-at-the-edge calls: `required(effect_descriptor) -> CapabilityNeed` (the
  *auth-probe* analogue — which capability, if any, this effect requires) and
  `present(grant) -> PresentedCapability` (hand an already-acquired, opaque handle
  to the effect site). A by-name resolver over a `dos.capability_sources`
  entry-point group, mirroring `dos.judges` / `dos.overlap_policies` /
  `dos.evidence`.
- **The trusted-minter floor (load-bearing, the allowlist).** A `CapabilityGrant`
  is admissible **only** if its minter is on the deployment's trusted-minter set
  (declared in `dos.toml`, the `inbox_otp` `otp_sender_domains` generalized). An
  unrecognized minter yields a typed refusal (`UNTRUSTED_MINTER`, the
  `otp_unmapped_sender` generalized), never a usable grant. This is the
  authority-plane analogue of [`121 §5`](121_first-class-on-devices-and-unattended.md)'s
  "a swapped source can only abstain-more": **a swapped acquirer can only obtain
  *fewer* capabilities (those from trusted minters), never manufacture one the
  agent could forge.** Safe direction guaranteed structurally.
- **The lifecycle, on the WAL.** `acquired` / `presented` / `expired` / `revoked`
  are recorded on the lease journal as a capability's life, the `invalidate_cookies`
  revoke made a first-class op — so an auditor replaying the journal can see *which
  authority the agent held when it acted*, the authority-plane completion of the
  [`115`](115_the-under-what-axis-environment-and-version-provenance.md) "under-what did this verdict run" provenance.
- **Drivers (out of kernel).** An `OtpCapabilitySource` (the `inbox_otp` shape — a
  trusted-sender allowlist + a code extractor), an `SsoCapabilitySource`, a
  `CookieSessionCapabilitySource` (acquire/persist/invalidate per `(host)`), a
  `VaultCredentialSource` (a stored secret — distinct substrate from a session, per
  §2.3). All driver-resolved by name; the kernel imports none (the existing
  `no dos.drivers import` litmus covers them).

## 6. The disciplines map to kernel laws — same convergence as 129

As with the evidence pipeline, the auth-wall system was built userland with no
kernel intent and landed on the kernel's authority-plane laws independently:

| Auth-wall discipline (from the shipped code) | Kernel law it instantiates |
|---|---|
| trusted-minter allowlist; "callers cannot poll an unfiltered inbox" | trust-the-granting-party-not-the-asker — the lease arbiter floor (docs/89), here pointed at an external minter |
| unmapped sender → `otp_unmapped_sender` failure, not silent use | refusal-as-primitive (docs/82); `UNTRUSTED_MINTER` is a named "no", not a crash |
| SSO > vault > create-account > OTP preference order | graded accountability (the authority-plane twin of 129's A/B/C/D); strongest = agent holds the least secret |
| auth probe classifies the gate before spending budget | the *before* moment (docs/121 §1) — recognize the capability need, don't blunder into the wall |
| `invalidate_cookies` on FAILED; per-`(company,ATS)` lifetime | a capability is a **lease** (TTL + revoke), not immutable evidence (§3) |
| cookies are non-secret session-state, NOT routed through the creds vault | a session capability ≠ a secret credential — different substrate, different lifetime |
| allowlist missing → defaults, "never raises … rather than breaking the apply path" | fail-safe degrade (the no-plan / safe-floor discipline) |

## 7. What this note claims, and what it does not

- **Does claim:** the counterparty asymmetry has two faces, and 121/129 worked only
  one. The *before*-the-effect face — a counterparty-minted, revocable token the
  agent must present to be permitted to act — is the **authority-plane dual of the
  witness**, it answers `arbitrate` rather than `verify`, and it is **already
  shipped in full** in the reference app's auth-wall subsystem (probe + acquisition
  ladder + cookie persistence/invalidation + the OTP trusted-minter floor), which
  converged independently on the kernel's lease/refusal/grading laws (§6).
  Structurally an external capability is a lease the counterparty grants, so a
  `CapabilitySource` is `arbitrate` pointed outward (§3), it sorts as an
  `arbitrate`-family boundary verb + seam with a pure recognizer and a driver
  acquirer (§4), and its safe direction is guaranteed by a trusted-minter floor
  exactly parallel to the evidence seam's abstain-more floor (§5).
- **Does not claim:** that the userland Gmail/SSO/cookie specifics belong in the
  kernel (they are drivers), that the capability source *verifies* anything (it
  authorizes; the *witness* that the authorized effect then landed is still the
  `EvidenceSource`'s job — the two planes compose: capability → effect →
  witness), or that any kernel code is written here. The honest residue is the same
  bootstrapping floor the safety-floor essay named for intent: **the trusted-minter
  allowlist is itself an artifact, and a capability source can only be as honest as
  the set of minters it was told to trust.** If the agent (or an attacker) can edit
  the allowlist, the floor is gone — so the trusted-minter set is a human-seeded,
  high-authority artifact (the onboarding seed), never an agent-autonomous one. The
  capability source bounds *who* the agent will accept authority from; it cannot
  bootstrap *that* trust from nothing.

The meta-answer: **the same reason the kernel doesn't believe the agent about what
it *did* is the reason the kernel doesn't let the agent authorize *itself* to act —
in both cases the only trustworthy bytes are the ones a party other than the agent
authored. The witness is that party after the fact; the capability is that party
before it. DOS already adjudicates the internal version of "may I act" with the
lease arbiter; the capability source is that verb meeting the external world, and
the apply fleet has been running it in production all along.**

---

## References

*The shipped authority-plane system (userland — consumed, never depended on):*
- `agents/config_pkg/apply_auth_walls.py` — the auth-wall taxonomy: auth probe → login micro-phase (SSO > vault > create-account) → email-verification/OTP wall; "they compose sequentially inside a single apply attempt."
- `agents/apply_login.py` + `agents/_phase_login_prompts.py` — the login micro-phase / acquisition ladder.
- `agents/apply_cookie_store.py` — per-`(company, ATS)` session persistence; `save_cookies`/`invalidate_cookies` — the capability-as-lease lifecycle (revoke on FAILED); the non-secret-session vs secret-credential distinction.
- `agents/inbox_otp.py` — `fetch_recent_otp`; the trusted-minter allowlist (`otp_sender_domains`, subdomain match), the `otp_unmapped_sender` refusal, the honest cursor, the fail-safe degrade — the seam's floor.

*The kernel frame this completes:*
- [`121_first-class-on-devices-and-unattended.md`](121_first-class-on-devices-and-unattended.md) — §1 before/during/after (the *before* slot this fills), §2.1 the counterparty asymmetry (this is its authority-plane face), §5 the seam apparatus this reuses.
- [`129_the-apply-confirmation-as-the-proving-ground-for-non-git-evidence.md`](129_the-apply-confirmation-as-the-proving-ground-for-non-git-evidence.md) — §4/§6 named this dual ("a capability the agent cannot forge, consumed before an effect") and left it open; this note develops it.
- [`89_the-lane-is-a-region-lock.md`](89_the-lane-is-a-region-lock.md) — the lease arbiter / lock-manager model an external capability is `arbitrate` pointed outward of.
- [`99_runtime-validation-and-the-actuation-boundary.md`](99_runtime-validation-and-the-actuation-boundary.md) — the boundary-verb placement (§4) + the domain-freedom reason acquisition is always a driver.
- [`85_extending-the-verifiable-surface.md`](85_extending-the-verifiable-surface.md) — the four-gate sort used in §4.

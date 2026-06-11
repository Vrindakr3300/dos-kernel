# 296 — the operator-armed SELF_MODIFY override: a wired affordance for the HUMAN rung

> **Status:** 📋 **PLANNED** (commissioned 2026-06-10) — the operator asked for
> this seam directly, after a session in which the guard worked exactly as
> designed and the sanctioned escape hatch turned out not to exist as a
> *mechanism*, only as a *sentence*. Phases below; Phase 1 touches the T1 set,
> so its own application is the bootstrap case this plan exists to retire (see
> "the bootstrap irony").

## The gap this closes

The SELF_MODIFY guard refuses to let a live agent session rewrite the kernel
that is adjudicating it. That refusal is right, it held twice in the field on
2026-06-10 (issue #11), and nothing in this plan weakens it.

But the guard's own typed fix names a counterparty move that has no wired
mechanism. `dos man wedge SELF_MODIFY` says:

> TYPICAL FIX: Edit kernel runtime files OUTSIDE a live dispatch loop, or pass
> `--force` to override (the operator's explicit "I am deliberately editing the
> kernel between loop runs").

`--force` exists on `dos arbitrate` — but the PreToolUse hook ABI deliberately
gives the *agent* no force, and gives the *operator* nothing at all. So when
the human genuinely wants a supervised kernel edit, the protocol degenerates to
out-of-band tooling. The issue-#11 session is the type specimen:

1. agent Edit calls on `arbiter.py` → DENIED (correct);
2. operator explicitly authorizes the change, on the record;
3. the edit lands via a byte-exact Python script run from a temp dir — i.e.
   through the same arbitrary-exec hole the guard cannot close anyway;
4. `git add <path>` → DENIED by the path-MENTION matcher (issue #12), so
   staging routes through `--pathspec-from-file`;
5. nothing in the journal or the stats log records that an override happened.

Every step was sanctioned and visible in the conversation — and invisible to
DOS. The kernel's trust ladder is ORACLE → JUDGE → HUMAN; the HUMAN rung ruled,
and the kernel had no way to *hear* the ruling. Related field evidence: a
sibling loop burned 21 identical refused Writes on one T1 file because a deny
never escalates anywhere (issue #14).

## The design — an arm file the operator writes, the hook reads, the clock expires

One new piece of **declared, operator-authored, expiring data**, read at the
hook boundary; one new evidence field on the pure classify; zero behavior
change while unarmed.

### The arm file

```toml
# .dos/override/self-modify.toml — hand-written by the operator, never by an agent
until  = 2026-06-10T23:30:00Z          # hard deadline, UTC; REQUIRED
scope  = ["src/dos/arbiter.py"]        # optional; absent/empty = the whole T1 set
reason = "issue #11 — refuse-reason rename"   # REQUIRED; lands in the audit row
```

* **Arming is manual by construction.** There is deliberately NO `dos override
  arm` verb: any verb an agent's shell can call is an arming path an agent can
  take. The docs print the two lines the operator types. The arm path itself
  joins the hook's deny set (a cooperative agent's Write/Edit to
  `.dos/override/` is refused exactly like a T1 file).
* **Expiry is a clock, not a consume.** The hook is a PDP — a read-only
  adjudicator — so the one-shot semantics come from `until`, not from the hook
  deleting the file on use (a hook that mutates state on admit is a layering
  break). The clock is env-authored ground truth, the same witness the
  temporal-verdict family already trusts. Recommended window ≤ 30 minutes; the
  kernel never extends it.
* **Fail closed, every branch.** Missing file, unparseable TOML, missing
  `until`/`reason`, expired deadline, target outside `scope` → exactly today's
  deny, byte-identical. A malformed override can only fail to admit, never
  fail to deny.
* **Disarm is always safe, for anyone.** `dos override disarm` deletes the arm
  file; `dos override status` reports it. The asymmetry IS the security
  property: anyone may lower the drawbridge's gate; only the human raises it.

### The verdict and the audit trail

`dos.self_modify` classify gains an optional evidence input (`OverrideFacts`:
armed-until, scope, reason — a frozen value gathered at the boundary, the
"I/O at the boundary, data to the pure core" rule). On a T1 hit with a live,
in-scope, unexpired override the verdict is **ADMIT-with-note**, distinguishable
from a plain admit: the hook emits `additionalContext` ("operator override
armed until T — admitting supervised kernel edit: <reason>") instead of a
silent pass, the observation log row carries `override=until-T`, and
`dos stats` folds an "override-admitted" count. The path-mention matcher
(issue #12) honors the same override, which retires the `--pathspec-from-file`
workaround inside the window.

### The threat model, stated honestly

This guard was never proof against adversarial exec — an agent with a shell can
write any file through a subprocess, and the issue-#11 session demonstrated
exactly that (with permission). The guard's real job is stopping *heedless*
self-modification by cooperative agents, and that job is unchanged: unarmed
behavior is byte-identical, the arm path is deny-listed against cooperative
writes, and the new channel is time-boxed, scoped, reasoned, and audited. The
seam strictly improves the status quo by replacing an invisible out-of-band
script with a recorded protocol move. What the arm file is NOT: a forgeproof
witness in the docs/138 sense — its authorship is trust-on-convention, exactly
as strong as the machine's single trust domain allows, and the plan claims
nothing stronger.

## Phases

### Phase 1 — the pure core: `OverrideFacts` + classify

`dos.self_modify` (T1): the frozen `OverrideFacts` value, the optional
`override=` parameter on the classify path, the ADMIT-with-note verdict
variant. PURE — no I/O, no clock read inside the verdict (the boundary passes
`now`). Pinned by classify-level tests: armed/expired/out-of-scope/malformed ×
T1-hit/no-hit.

**The bootstrap irony, named:** this phase edits a T1 file, so its own
application is the last ride of the out-of-band playbook (operator
authorization on record → byte-exact apply script → pathspec-file staging).
After it ships, that playbook retires in favor of the arm file.

### Phase 2 — the boundary: reader + hook wiring + arm-path guarding

A new non-T1 boundary leaf (`dos.override_facts`: tomllib read of the arm
file + `now` capture → `OverrideFacts | None`, fail-closed) wired into the
Python `dos hook pretool` path; `.dos/override/` joins the deny set; the
`additionalContext` note + observation-log field. End-to-end tests: armed file
→ admitted Edit with note; agent Write to the arm path → denied; expiry →
deny restored.

### Phase 3 — the operator surface: `dos override status|disarm`, doctor, stats, man page

The read/disarm verb (no arm verb — see design), a `doctor` row
(`self-modify override   disarmed` / `armed until T (reason)`), the `dos stats`
fold, and the `dos man wedge SELF_MODIFY` TYPICAL FIX text gains the third
path: "or arm the operator override (docs/296)".

### Phase 4 — Go hook parity

`go/internal/hook/decide.go` learns the same arm-file read (same fail-closed
branches), pinned by the existing Go/Python parity corpus pattern.

## What this plan does NOT do

* No agent-side force, no arm verb, no env-var override — arming stays a human
  hand on a guarded file.
* No change to any verdict while unarmed: the entire diff is reachable only
  through a file that does not exist on an unarmed workspace.
* No claim of forgeproof-ness the single-machine trust domain cannot deliver.

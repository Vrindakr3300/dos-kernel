# Non-git evidence in the `verify()` verdict — a driver-oracle rung above the git ladder

> **`verify()` today answers from git alone: every rung it can stand on —
> `registry` ⋈ ancestry, distinctive file-path overlap, direct-ship subject,
> release-body, `none` — reads a commit object ([`oracle.py:142`](../src/dos/oracle.py),
> the `source` field is `"registry" | "grep" | "none"`). That is the floor of
> ground truth and not the ceiling ([`84 §3`](183_how-much-does-this-lean-on-git.md)):
> a clean `verify()` means *a commit of the right shape is reachable*, never *the
> build is green / the migration ran / a human approved*. One non-git oracle already
> ships — [`drivers/ci_status.py`](../src/dos/drivers/ci_status.py) — but it sits
> OUTSIDE `verify()`, consulted only by `scripts/stable_release_context.py`. This
> note specifies the missing **seam**: a generic way for `verify()`'s verdict to
> carry a non-git rung ABOVE the git rungs, where the evidence is GATHERED AT THE CLI
> BOUNDARY exactly as `liveness` gathers `git_delta`/`journal_delta`, the rung is
> ADVISORY and CONJUNCTIVE (it never fabricates a SHIP, only sharpens or withholds
> one), and the driver that produces it is discovered BY NAME so the kernel never
> imports it — the same one-way arrow as `dos.judges` / `dos.predicates` /
> `dos.drivers.watchdog`. The kernel MINTS a richer `ShipVerdict` (a more-accountable
> `source=` than `grep`) and PROPOSES nothing it cannot stand on; it never runs a
> provider's API inside the pure core, never lets a non-git rung *manufacture* a
> ship the git rungs deny, and never names a driver in `oracle.py`. NOT YET BUILT.**

A theory-plus-spec note in the family of [`84`](183_how-much-does-this-lean-on-git.md)
(git necessary-not-sufficient; the §4 rung ladder this note adds a top rung to),
[`85`](85_extending-the-verifiable-surface.md) (extend deeper before broader; the
four-gate test that sorts every candidate), [`93`](93_verifying-live-non-git-sources.md)
(the accountability spectrum + the move-B reference driver `ci_status.py` this note
finally *plumbs into the verdict*), [`95`](95_os-level-evidence-and-the-proc-liveness-rung.md)
(the local OS sequel — the `proc_delta.py` rung, demote-only, into `liveness` not
`verify`, whose build order Phase 2 reuses), and [`76`](76_flexible-goals-and-verification.md)
(the give lives in *which-signals/provenance*, never the adjudication — a new
evidence source enters as a rung/driver, the verdict stays mechanical).

It carries no litmus and is not in the `next-stage-plan` table. **Nothing below is
built.** `ci_status.py` exists (the occupant); the *seam that lets `verify` consult
it* does not, and the `[ci]`/`[verify]` `dos.toml` table it would read is referenced
in [`CiPolicy`'s docstring](../src/dos/drivers/ci_status.py) but **not yet folded
into `SubstrateConfig`** (config.py folds only `[lanes]`/`[paths]`/`[stamp]`/`[reasons]`).

---

## 1. Problem (one line)

`verify()`'s every rung is git — registry/file-path/direct-grep/release-body/none
([`oracle.py`](../src/dos/oracle.py)) — so it can certify *a commit exists* but never
*the build is green at it*, even though the kernel already ships a non-git oracle
([`ci_status.py`](../src/dos/drivers/ci_status.py)) that answers exactly that and is
stranded outside the verdict.

## 2. Goal

Give `ShipVerdict` a **non-git rung ABOVE the git rungs** — a new `source` value
(e.g. `"ci-green"`) minted only when a host has WIRED a non-git oracle and the
evidence the oracle returns is itself unforgeable by the judged agent
([`93 §2`](93_verifying-live-non-git-sources.md) gate 2). Do it without (a) moving a
provider's network I/O into the pure core, (b) letting a non-git rung *fabricate* a
ship the git ladder denies, or (c) naming a driver inside `oracle.py`. The whole move
is the [`76`](76_flexible-goals-and-verification.md) one restated for `verify`: the
*signal* becomes more accountable; the adjudication stays mechanical.

## 3. The model — a rung above the ladder, gathered at the boundary, conjunctive

### 3.1 Where it sits — the [`84 §4`](183_how-much-does-this-lean-on-git.md) / [`93 §5`](93_verifying-live-non-git-sources.md) ladder, with `verify` now reading the top

[`ci_status.py`](../src/dos/drivers/ci_status.py) already DRAWS this ladder in its
own docstring — *above* every git rung, because a CI conclusion is mutable
third-party state the agent cannot author. The gap is that nothing connects the top
rung to `ShipVerdict`:

```
non-git oracle (build/test/CI green)   ← drivers/ci_status.CiVerdict   ← THIS NOTE plumbs it into verify
  registry stamp ⋈ git ancestry        ← oracle.ShipVerdict source="registry"
    distinctive file-path overlap       ← oracle grep rung, file backstop
      direct-ship subject match         ← oracle grep rung, subject
        source="none" / via=""          ← git history alone / could not confirm
```

### 3.2 The asymmetry that keeps it sound — conjunctive, never disjunctive

This is the load-bearing safety property, and it is the dual of [`95 §4.4`](95_os-level-evidence-and-the-proc-liveness-rung.md)'s
demote-only rung. A non-git oracle may make `verify` answer **more skeptically**, never
more permissively:

- **A non-git rung NEVER promotes `shipped=False → shipped=True`.** If git has no
  reachable commit (`source="none"`), a GREEN CI run does not manufacture a ship —
  there is no artefact for CI to be green *about*. CI green without a commit is the
  forgeable-floor trap wearing a build badge. So the non-git rung is **conjunctive
  with the git rung**: it can confirm/strengthen a git-positive ship (mint
  `source="ci-green"` over a commit the git rung already found), and it can WITHHOLD
  one (a RED CI run on the very commit a `grep` rung matched → the verdict is *not*
  upgraded, and the host may route a decision), but it cannot conjure a ship from
  nothing. The git rung is the *necessary* gate; the non-git rung is the
  *accountability upgrade* layered on top. This is the same `failing`-dominates,
  fail-safe-never-fail-open ordering `ci_status.classify` already enforces internally
  ([`ci_status.py:344`](../src/dos/drivers/ci_status.py)), lifted to the verdict
  boundary.
- **`NO_SIGNAL` / `PENDING` / unreachable degrades to the git answer, byte-identical.**
  A repo with no CI wired, an unauthenticated `gh`, a commit with no checks yet — all
  return the git verdict unchanged (`source="registry"`/`"grep"`/`"none"`), exactly as
  `verify` degrades to `source="none"` today and `ci_status` degrades to `NO_SIGNAL`.
  The non-git rung is **opt-in by configuration and absent-by-default**; an unconfigured
  `verify` is the same bytes it is now (the [`test_verify_no_plan.py`](../tests/test_verify_no_plan.py)
  no-plan contract is untouched).

The meta-property mirrors [`95`](95_os-level-evidence-and-the-proc-liveness-rung.md):
*new evidence may only make the verdict more accountable or more skeptical, never less.*

### 3.3 The seam — three pieces, mechanism in the kernel, policy/provider in the driver

1. **`ShipVerdict` gains a richer `source` vocabulary (kernel, mechanism).** Today
   `source` is `"registry" | "grep" | "none"` ([`oracle.py:142`](../src/dos/oracle.py)).
   Add the open-ended non-git rung label (`"ci-green"` is the first; an infra-log or
   approval driver would mint its own, e.g. `"approved"`). The label is *data the
   verdict carries* — the renderer already prints it as `(via <source>)`
   ([`cli.py:321`,`382`](../src/dos/cli.py): the `(via …)` evidence-grade suffix is
   `verify`'s most-differentiated idea). No provider name, no host name, enters
   `oracle.py` — only a string the boundary handed in.

2. **A pure boundary parameter on `is_shipped` (kernel, mechanism).** The non-git
   verdict enters `is_shipped`/`batch_is_shipped` as an **already-gathered, injected
   datum**, exactly as `grep_touched_files` / `soaks` / `commit_touches_doc` already do
   (all `Callable`/data hooks, defaulting to `None` = gate OFF = byte-identical —
   [`oracle.py:737-739`](../src/dos/oracle.py)). The shape: an optional
   `non_git_rung: NonGitRung | None = None` (a tiny frozen dataclass: the upgraded
   `source` label + a one-line `reason` + the rung's own verdict-state), or a
   `Callable[[ShipVerdict], ShipVerdict | None]` upgrade hook. It is applied ONLY to a
   `shipped=True` git verdict and ONLY in the conjunctive direction of §3.2. **No
   network, no subprocess, no `gh` inside `is_shipped`** — the arbiter/`git_delta`
   rule the whole kernel lives by.

3. **The boundary gathers it by resolving the driver BY NAME (CLI, not kernel).**
   `cmd_verify` ([`cli.py:556`](../src/dos/cli.py)) is the existing evidence-gather
   boundary — it already builds the cfg and calls `oracle.is_shipped(..., cfg=...)`.
   When the workspace declares a non-git oracle (a `[verify] non_git_oracle = "ci_status"`
   / `[ci]` table in `dos.toml`), the boundary resolves that driver **by name via
   `importlib`** — the EXACT pattern `_load_watchdog` uses
   ([`cli.py:1336`](../src/dos/cli.py): `importlib.import_module("dos.drivers.watchdog")`,
   "the same mechanism `_resolve_driver_config` uses for host policy packs, and the
   `dos.judges` seam uses for adjudicators"), calls its `status_of(sha)` at the
   boundary (where the `gh api` subprocess lives, in the DRIVER's `gather()`), maps the
   `CiVerdict` to a `NonGitRung`, and passes it into `is_shipped`. The kernel verb stays
   provider-blind; the wiring is a host's.

### 3.4 Why this respects the kernel-imports-no-driver litmus

`oracle.py` never gains `import dos.drivers.ci_status` (nor a string mention that a
litmus could trip). The driver is reached only at the **CLI boundary**, resolved by
name from a config string, the same one-way arrow pinned by
[`tests/test_vendor_agnostic_kernel.py::test_no_kernel_module_imports_a_driver`](../tests/test_vendor_agnostic_kernel.py)
(line 195) — which already forbids any non-driver kernel module from importing
`dos.drivers` or `dos.drivers.*`. `ci_status.py` keeps its existing one-way import (it
imports the kernel; the kernel never imports it — `tests/test_ci_status.py::test_kernel_does_not_import_this_driver`),
and the new seam does not weaken it. The `NonGitRung` datum `is_shipped` accepts is
**pure data** (a label + a reason + a state enum), carrying no provider type — so even
the *type* `oracle.py` mentions is a kernel-local dataclass, not a driver class. This
is the `render`/`admission`/`judges` split exactly: the SEAM is kernel, the
IMPLEMENTATIONS (CI, infra-log, approval) are drivers discovered by name.

### 3.5 What is explicitly DESIGNED OUT — forgeable "OS-costume" evidence

[`95 §2`](95_os-level-evidence-and-the-proc-liveness-rung.md) and
[`93 §3`](93_verifying-live-non-git-sources.md) already settled this and the seam must
not re-open it:

- **File mtimes / `stat` ctimes are NOT a rung.** The agent authors every byte it
  writes; an mtime is `heartbeat_at`, not `ts` ([`journal_delta.py:217`](../src/dos/journal_delta.py)).
  It fails gate 2 and does not enter `verify`'s evidence in any form.
- **Bare artefact-diffs are NOT a *new* rung — they are already the file-path rung.**
  A git-committed artefact diff is a commit object the distinctive file-path backstop
  ([`oracle.py:1102` `default_commit_touches_doc`](../src/dos/oracle.py)) already
  reads. A *bare* (uncommitted) diff is a self-report; it stays out.
- **The agent's own application logs / screenshare are JUDGE inputs, never a verify
  rung** ([`93 §3`](93_verifying-live-non-git-sources.md)): they fail gate 2 whenever
  the agent produces the frames. A non-git *verify* rung admits only sources the judged
  agent cannot author (CI conclusions, infra audit logs, an approval-envelope's
  who/when).

## 4. Phases (throughline-first; each ships an ENABLED slice, smallest-first, behind the old behavior so it can't regress)

- **Phase 1 — the seam + plumb the EXISTING `ci_status` as the first occupant, byte-identical when unconfigured.** ◻ NOT BUILT.
  The whole leverage, smallest-first. Add the `NonGitRung` dataclass + the optional
  conjunctive parameter on `is_shipped`/`batch_is_shipped` (default `None` = OFF =
  byte-identical, the [`oracle.py`](../src/dos/oracle.py) gate-OFF convention every
  existing opt-in hook uses). Add the richer `source` label (`"ci-green"`). Wire
  `cmd_verify` ([`cli.py:556`](../src/dos/cli.py)) to read a `[verify] non_git_oracle`
  / `[ci]` `dos.toml` table (NEW: fold it into `SubstrateConfig` the way
  `[lanes]`/`[stamp]` are — config.py does NOT do this yet), resolve the named driver
  by `importlib` (the [`_load_watchdog`](../src/dos/cli.py) pattern), call
  `ci_status.status_of(sha)` at the boundary, map GREEN→upgrade / RED→withhold /
  PENDING|NO_SIGNAL→passthrough, and pass the `NonGitRung` in. Unconfigured workspaces
  (no table) get `verify` unchanged — pinned against
  [`test_verify_no_plan.py`](../tests/test_verify_no_plan.py). This is the throughline:
  one end-to-end non-git rung lights up, reusing the already-shipped, already-tested
  `ci_status` driver as the occupant.

- **Phase 2 — the proc-liveness rung ([`95`](95_os-level-evidence-and-the-proc-liveness-rung.md)), demote-only, into `liveness` NOT `verify`.** ◻ NOT BUILT.
  The other half of "more proof than git", but it belongs to a *different* verdict.
  [`95`](95_os-level-evidence-and-the-proc-liveness-rung.md) already specs it fully:
  `src/dos/proc_delta.py` boundary reader (every failure → `None`), an optional
  `ProgressEvidence.process_alive: Optional[bool] = None` field, and a **demote-only**
  branch in `liveness.classify` (a `False` OS probe flips fresh-heartbeat SPINNING →
  STALLED; a `True` probe corroborates, never overrides). It reuses
  [`95 §7`](95_os-level-evidence-and-the-proc-liveness-rung.md)'s exact build order
  (reader → field → demote-only classifier branch → CLI wire → `to_dict`), and the PID
  is already in the WAL ([`lane_journal.py:267`](../src/dos/lane_journal.py)). Sequenced
  here because it is the same "OS-evidence beyond git" instinct, and naming it keeps
  this plan from accidentally trying to route process-liveness into `verify` — it
  sharpens the alive/dead boundary, which is `liveness`'s, not the ship boundary.

- **Phase 3 — the infra-log driver oracle ([`93 §3`](93_verifying-live-non-git-sources.md), the next driver after CI).** ◻ NOT BUILT.
  A second occupant of the Phase-1 seam, proving it is generic and not CI-shaped: a
  `drivers/<infra>_audit.py` boundary oracle over a cloud audit trail / migration
  catalog / load-balancer access log — mutable-to-immutable third-party records the
  agent cannot write ([`93 §3`](93_verifying-live-non-git-sources.md) ranks this #2
  after CI). Field-for-field the `ci_status.py` template (`gather` boundary reader +
  pure `classify(Evidence, Policy) -> Verdict` + `status_of`), mints its own non-git
  `source` label through the unchanged Phase-1 seam. No kernel change — the seam was
  built in Phase 1; this is a driver.

- **Phase 4 — the approval-envelope driver oracle ([`93 §3`](93_verifying-live-non-git-sources.md), the human-in-the-loop fossil).** ◻ NOT BUILT.
  The narrow driver for the one claim git can never leave: *an accountable human
  approved this* (`APPROVED / NO-APPROVAL-FOUND`), read from a Slack/audit-API ENVELOPE
  (who/when, attested by the provider) — never the message CONTENT
  ([`93 §3`](93_verifying-live-non-git-sources.md): "only the envelope, never the
  content"). Same seam, same conjunctive discipline: an approval upgrades a
  git-positive ship's accountability; it never manufactures one.

- **Phase 5 — bench proof (the honesty discipline, [`93`](93_verifying-live-non-git-sources.md)/[`84 §2`](183_how-much-does-this-lean-on-git.md)).** ◻ NOT BUILT.
  Wire the non-git rung into FleetHorizon the way [`86 §3`](86_the-typed-verdict-surface.md)
  wired scope/liveness: inject commits whose *git shape ships but whose build is RED*,
  and measure the false-clear rate of git-only `verify` vs git+CI `verify`. The claim
  to falsify: the non-git rung strictly reduces false-SHIPPED on broken builds AND
  never false-clears a real ship when the oracle is silent (NO_SIGNAL passthrough),
  the same fail-safe-degradation honesty the §3.2 asymmetry guarantees.

## 5. Test obligations

- **Unconfigured `verify` is byte-identical.** With no `[verify]`/`[ci]` table, the
  new `is_shipped` parameter defaults `None` and the verdict's `source`/bytes match
  today — pinned against [`test_verify_no_plan.py`](../tests/test_verify_no_plan.py)
  (the no-plan contract) and the existing `test_oracle`/`test_phase_shipped` suites.
- **Conjunctive, never disjunctive (the §3.2 safety pin).** A frozen fixture where
  the git rung is `shipped=False` (`source="none"`) and the injected `NonGitRung` is
  GREEN → the verdict STAYS `shipped=False` (CI green never manufactures a ship). A
  `shipped=True` git verdict + RED non-git rung → not upgraded (withheld). A
  `shipped=True` + GREEN → upgraded to `source="ci-green"`. All on frozen data, no
  `gh`, the `ci_status`/`liveness` replay-testable discipline.
- **Degrade-to-git on silence.** NO_SIGNAL / PENDING / unreachable → the git verdict
  passes through unchanged (byte-identical `source`).
- **Kernel imports no driver — string-level.** `oracle.py` contains no
  `dos.drivers`/`ci_status` import (re-asserted by the existing
  [`test_vendor_agnostic_kernel.py::test_no_kernel_module_imports_a_driver`](../tests/test_vendor_agnostic_kernel.py)
  and `test_ci_status.py::test_kernel_does_not_import_this_driver`; add a `verify`-path
  assertion if the seam touches new modules).
- **The driver is resolved by name at the boundary.** A `cmd_verify` test with a
  `[verify] non_git_oracle` table monkeypatching the `importlib` resolver proves the
  CLI reaches the driver by name, not by static import.
- **Phase 2 (`proc_delta`) pins** are [`95 §7`](95_os-level-evidence-and-the-proc-liveness-rung.md)'s
  verbatim: live-self-PID→`True`, impossible PID→`False`, foreign `host_id`→`None`,
  unsupported→`None`, no raise on any input; `False` flips fresh-heartbeat
  SPINNING→STALLED; `True` does not override; `None` byte-identical.

## 6. Boundary — DOS-vs-host / what stays a driver

- **Kernel (mechanism):** the `source` vocabulary, the `NonGitRung` dataclass, the
  optional conjunctive parameter on `is_shipped`, the renderer's `(via <source>)`
  suffix. All provider-blind — they carry a *label and a reason*, never a provider's
  type or API.
- **Boundary (CLI):** the gather — resolve the named driver by `importlib`, run its
  `status_of(sha)` (where the `gh api` subprocess lives), map its verdict to a
  `NonGitRung`. This is where I/O happens, exactly as `cmd_liveness` gathers
  `git_delta`/`journal_delta` and `cmd_verify` builds the cfg today.
- **Driver (policy + provider):** every non-git oracle — `ci_status` (built),
  infra-audit (Phase 3), approval-envelope (Phase 4) — speaks a specific system, fails
  gate 3 (domain-free), and lives in `drivers/`. It owns the network I/O, the provider
  vocabulary, and the `[ci]`/`[<driver>]` policy knobs. The host WIRES which oracle
  `verify` consults via `dos.toml`; an unwired host gets git-only `verify`,
  byte-identical to today.
- **Stays a driver, never a kernel verb:** because a CI/infra/approval signal is tied
  to a provider ([`93 §4`](93_verifying-live-non-git-sources.md) move B), it can NEVER
  become a `dos <verb>`. The only kernel surface is the *seam* that lets `verify`
  CARRY the driver's verdict as a more-accountable rung. The one local OS signal that
  *is* domain-free (process-liveness) lands as a *rung in `liveness`*, not a driver and
  not in `verify` — Phase 2, per [`95 §3`](95_os-level-evidence-and-the-proc-liveness-rung.md).

## 7. See also

- [`183_how-much-does-this-lean-on-git.md`](183_how-much-does-this-lean-on-git.md) — git
  necessary-not-sufficient; the §4 rung ladder this note adds a top rung to; the
  `source=`/`via=` typed-provenance the new label extends.
- [`85_extending-the-verifiable-surface.md`](85_extending-the-verifiable-surface.md) —
  the four-gate test; "extend deeper before broader"; the three homes (verb / driver
  oracle / judge) the non-git rung's occupants land in.
- [`93_verifying-live-non-git-sources.md`](93_verifying-live-non-git-sources.md) — the
  accountability spectrum, the gate-2 "who authors this byte?" test, the
  `ci_status.py` move-B reference this note plumbs into the verdict, and the
  infra-log / Slack-approval drivers Phases 3–4 build.
- [`95_os-level-evidence-and-the-proc-liveness-rung.md`](95_os-level-evidence-and-the-proc-liveness-rung.md)
  — the local-OS sequel; the demote-only `proc_delta` rung Phase 2 reuses
  verbatim (into `liveness`, not `verify`); the file-mtime trap this note designs out.
- [`76_flexible-goals-and-verification.md`](76_flexible-goals-and-verification.md) —
  the give lives in which-signals/provenance, never the adjudication: the non-git rung
  is more accountable evidence on a verdict that stays mechanical.
- [`src/dos/oracle.py`](../src/dos/oracle.py) — `ShipVerdict.source`
  (`registry|grep|none`, :142); the opt-in injected-hook pattern (`grep_touched_files`/
  `soaks`/`commit_touches_doc`, gate-OFF=`None`) the new parameter copies.
- [`src/dos/drivers/ci_status.py`](../src/dos/drivers/ci_status.py) — the first
  occupant: `gather`/`classify`/`status_of`, the `Ci` GREEN/RED/PENDING/NO_SIGNAL
  ladder, the ABOVE-git-rungs placement, the one-way import.
- [`src/dos/cli.py`](../src/dos/cli.py) — `cmd_verify` (:556), the
  `(via <source>)` evidence-grade renderer (:321/:382), and `_load_watchdog` (:1336),
  the `importlib`-by-name driver-resolution pattern the seam reuses.

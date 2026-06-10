# 265 — Wiring the non-git evidence seam into `verify()`: the stranded-driver gap

> **The drivers exist; the socket doesn't.** `src/dos/drivers/{ci_status,
> os_acceptance,paste_log}.py` are three finished, tested `EvidenceSource` /
> `LogSource` witnesses — and `evidence.py` ships the full by-name resolver for them
> (`active_evidence_sources`, `resolve_evidence_source`, the
> `EVIDENCE_SOURCE_ENTRY_POINT_GROUP = "dos.evidence_sources"` constant at
> `evidence.py:612`). But the group is **not declared in `pyproject.toml`**, no
> occupant is registered, and — the load-bearing gap — **`verify()` does not consult
> any of them**. `oracle.is_shipped` answers from git alone. So DOS's truth syscall
> cannot say "the phase shipped *and the build is green at that commit*," even though
> the driver that knows the build is green is sitting on disk one import away. This
> plan plumbs the existing `ci_status` driver into `verify()` as a **conjunctive,
> opt-in, accountability-only** rung — the docs/109 design, made concrete against the
> code as it actually stands on 2026-06-09.

*Status: design. The seam pieces this plan needs are split between "shipped but
unwired" (the drivers + the `evidence.py` resolver) and "not built" (the
`is_shipped` parameter, the `[verify]`/`[ci]` config fold, the `dos.evidence_sources`
pyproject group, the CLI gather). docs/109 specified this; nothing below is built.*

## 0. The one finding that motivates the plan (probe, 2026-06-09)

I grepped the live tree, not the contract:

| Piece | State on disk | Evidence |
|---|---|---|
| `ci_status` / `os_acceptance` / `paste_log` drivers | **SHIPPED + tested** | `src/dos/drivers/*.py`; `tests/test_ci_status.py` |
| `EvidenceSource` Protocol + `believe_under_floor` | **SHIPPED** | `evidence.py:260-286`, `:412-485` |
| `dos.evidence_sources` resolver (`active_evidence_sources` etc.) | **SHIPPED** | `evidence.py:607-692` |
| `dos.evidence_sources` entry-point GROUP in `pyproject.toml` | **MISSING** | `grep evidence_sources pyproject.toml` → nothing |
| `verify()` consulting a non-git rung | **MISSING** | `oracle.py` `source ∈ {registry, grep, none}` only |
| `[verify]` / `[ci]` table folded into `SubstrateConfig` | **MISSING** | `config.py` folds `[lanes]`/`[paths]`/`[stamp]`/`[reasons]` only |

So this is the rarest kind of gap: **most of the work is already done and tested, and
the verdict still can't reach it.** The whole plan is a socket, not a rewrite — the
same shape docs/217 found for the hook dialect ("the verdict is the kernel and the
envelope is the last step"), here on the *input* side of `verify`.

## 1. What "non-git evidence" is, and the asymmetry that keeps it sound

`verify()` today certifies *a commit of the right shape is reachable* (docs/183: git
necessary, not sufficient). A clean `verify` means a ship happened; it never means
*the build is green / the migration ran / a human approved*. Those are mutable
third-party facts the **judged agent cannot author** — exactly the `Accountability =
THIRD_PARTY` / `OS_RECORDED` rungs `evidence.py` already grades.

The safety property is the dual of docs/95's demote-only rung, and it is the entire
reason this is safe to ship: **a non-git rung may make `verify` answer MORE
skeptically, never more permissively.**

- **It NEVER promotes `shipped=False → shipped=True`.** Green CI without a reachable
  commit manufactures nothing — there is no artefact for CI to be green *about*. The
  git rung is the **necessary gate**; the non-git rung is an **accountability upgrade
  layered on top** (mint a richer `source="ci-green"` over a commit the git rung
  *already* found) or a **withhold** (RED CI on the very commit a grep rung matched →
  not upgraded, host may route a decision). It is conjunctive with git, never
  disjunctive.
- **`NO_SIGNAL` / `PENDING` / unreachable degrades to the git answer, byte-identical.**
  No CI wired, unauthenticated `gh`, a commit with no checks yet → the git verdict
  unchanged. The rung is **opt-in by config, absent by default**; an unconfigured
  `verify` is the same bytes it is today (the `test_verify_no_plan.py` contract is
  untouched).

This is the docs/76 move restated for `verify`: the *signal* gets more accountable;
the *adjudication* stays mechanical.

## 2. The seam — three pieces, mechanism in the kernel, provider in the driver

### 2a. `ShipVerdict` gains a richer `source` vocabulary (kernel, mechanism)

`source` today is `"registry" | "grep" | "none"` (`oracle.py:142`). Add the
open-ended non-git label (`"ci-green"` first; an infra-log or approval driver mints
its own — `"approved"`, `"audit-green"`). The label is **data the verdict carries** —
the renderer already prints it as `(via <source>)` (`cli.py`, the evidence-grade
suffix that is `verify`'s most-differentiated idea). No provider name, no host name,
enters `oracle.py` — only a string the boundary handed in.

### 2b. A pure boundary parameter on `is_shipped` (kernel, mechanism)

The non-git verdict enters `is_shipped`/`batch_is_shipped` as an **already-gathered,
injected datum** — exactly as `grep_touched_files` / `soaks` / `commit_touches_doc`
already do (all `Callable`/data hooks, defaulting to `None` = gate OFF = byte-identical).

```python
@dataclass(frozen=True)
class NonGitRung:
    source: str          # the upgraded label ("ci-green") — data, no provider type
    reason: str          # a one-line why ("checks green at <sha>")
    state: str           # "GREEN" | "RED" | "NO_SIGNAL" (the rung's own verdict word)
```

`is_shipped(..., non_git_rung: NonGitRung | None = None)`. It is applied **only** to a
`shipped=True` git verdict and **only** in the conjunctive direction of §1: `GREEN` →
upgrade `source` to `non_git_rung.source`; `RED` → withhold the upgrade (verdict stays
`shipped=True`, but the host may route a decision off the unchanged-but-flagged
state — Phase 2 decides whether RED demotes to a WARN-class `source`); `NO_SIGNAL` →
the git verdict unchanged. **No network, no subprocess, no `gh` inside `is_shipped`** —
the arbiter/`git_delta` rule the whole kernel lives by.

### 2c. The boundary gathers it by resolving the driver BY NAME (CLI, not kernel)

`cmd_verify` is the existing evidence-gather boundary — it builds the cfg and calls
`oracle.is_shipped(..., cfg=...)`. When the workspace declares a non-git oracle (a
`[verify] non_git_oracle = "ci_status"` table in `dos.toml`), the boundary resolves
that driver **by name** — `evidence.resolve_evidence_source(name)` already exists and
does exactly this — calls its `status_of(sha)` at the boundary (where the `gh api`
subprocess lives, inside the driver's `gather()`), maps the `CiVerdict` to a
`NonGitRung`, and passes it into `is_shipped`. The kernel verb stays provider-blind.

## 3. The config fold (the genuinely-new kernel-adjacent work)

`config.py` folds `[lanes]`/`[paths]`/`[stamp]`/`[reasons]` from `dos.toml` today; it
does **not** fold a `[verify]`/`[ci]` table. This plan adds:

```toml
[verify]
non_git_oracle = "ci_status"   # the dos.evidence_sources name to consult, or absent = git-only

[ci]                            # the driver's own policy knobs (read by ci_status, not the kernel)
provider = "github"
repo = "owner/name"
```

`[verify].non_git_oracle` is read into a new defaulted `SubstrateConfig` field
(keyword-only, defaulting to `""` = off — the back-compatible widening rule
`PathLayout` already documents). `[ci]` is **passed through to the driver**, never
interpreted by the kernel (the `_resolve_driver_config` posture). An unconfigured
workspace gets git-only `verify`, byte-identical.

## 4. Register the entry-point group (the one-line unblock)

`pyproject.toml` gains:

```toml
# The non-git evidence-source witnesses (docs/109/265). The kernel seam
# (`dos.evidence`) holds the EvidenceSource Protocol + believe_under_floor +
# resolver; every provider-specific witness (a CI poller is inherently
# GitHub/GitLab-specific) lives in a DRIVER and registers here — the same
# kernel/driver split as dos.judges / dos.notifiers.
[project.entry-points."dos.evidence_sources"]
ci_status = "dos.drivers.ci_status:CiStatusSource"     # the GREEN/RED/PENDING/NO_SIGNAL CI rung
os_acceptance = "dos.drivers.os_acceptance:OsAcceptanceSource"
paste_log = "dos.drivers.paste_log:PasteLogSource"
```

(Exact class names confirmed against each driver before landing — the entry-point
*target* must match the occupant.) This is the smallest possible change that turns
`active_evidence_sources()` from "built-ins only" into "discovers the three shipped
drivers," and it is independently shippable from the verify-plumbing.

## 5. Build order (each rung independently shippable + testable)

- **Phase 0 — register the group (1 line, zero behavior change).** Add the
  `dos.evidence_sources` entry-points to `pyproject.toml` so the resolver discovers
  the three drivers. Gate: `dos doctor` lists them; the full suite stays green; no
  verdict changes (nothing consults them yet). The "WAL before the writers" discipline.
- **Phase 1 — the seam + plumb `ci_status` into `verify`, byte-identical when
  unconfigured.** Add the `NonGitRung` dataclass + the optional conjunctive
  `non_git_rung` parameter on `is_shipped`/`batch_is_shipped` (default `None` = OFF).
  Add the `"ci-green"` source label. Fold `[verify].non_git_oracle` / `[ci]` into
  `SubstrateConfig`. Wire `cmd_verify` to resolve the named driver, call
  `status_of(sha)`, map GREEN→upgrade / RED→withhold / PENDING|NO_SIGNAL→passthrough.
  Gate: `test_verify_no_plan.py` byte-identical; new conjunctive-safety tests (§6).
- **Phase 2 — the proc-liveness rung (docs/95), demote-only, into `liveness` NOT
  `verify`.** The other half of "more proof than git", but it belongs to a different
  verdict — a `False` OS probe flips fresh-heartbeat SPINNING → STALLED. Sequenced
  here so the plan does not accidentally route process-liveness into `verify`.
- **Phase 3 — a second occupant (infra-log driver) proving the seam is generic.** A
  `drivers/<infra>_audit.py` over a cloud audit trail — field-for-field the
  `ci_status.py` template, minting its own `source` label through the unchanged
  Phase-1 seam. No kernel change.
- **Phase 4 — the approval-envelope driver** (the human-in-the-loop fossil:
  `APPROVED / NO-APPROVAL-FOUND` from a Slack/audit-API envelope — who/when, never the
  message content). Same seam, same conjunctive discipline.
- **Phase 5 — bench proof.** Inject commits whose git shape ships but whose build is
  RED into FleetHorizon; measure git-only `verify` false-clear vs git+CI. Falsify: the
  non-git rung strictly reduces false-SHIPPED on broken builds AND never false-clears
  a real ship when the oracle is silent.

## 6. Test obligations (the litmus this plan must keep green)

- **Unconfigured `verify` is byte-identical.** No `[verify]`/`[ci]` table → the new
  `is_shipped` parameter defaults `None` and `source`/bytes match today. Pinned
  against `test_verify_no_plan.py` + the existing `test_oracle`/`test_phase_shipped`.
- **Conjunctive, never disjunctive (the §1 safety pin).** git `shipped=False`
  (`source="none"`) + GREEN `NonGitRung` → STAYS `shipped=False` (CI green never
  manufactures a ship). git `shipped=True` + RED → not upgraded. git `shipped=True` +
  GREEN → upgraded to `source="ci-green"`. All on frozen data, no `gh`.
- **Degrade-to-git on silence.** NO_SIGNAL / PENDING / unreachable → the git verdict
  passes through unchanged (byte-identical `source`).
- **Kernel imports no driver — string-level.** `oracle.py` contains no `dos.drivers` /
  `ci_status` import (re-asserted by the existing
  `test_vendor_agnostic_kernel.py::test_no_kernel_module_imports_a_driver`). The
  `NonGitRung` datum is a kernel-local dataclass carrying a label + reason + state
  enum — no provider type.
- **The driver is resolved by name at the boundary.** A `cmd_verify` test with a
  `[verify] non_git_oracle` table monkeypatching the resolver proves the CLI reaches
  the driver by name, not by static import.

## 7. Boundary — what stays a driver, forever

A CI/infra/approval signal is tied to a provider (docs/93 move B), so it can **never**
become a `dos <verb>`. The only kernel surface is the *seam* that lets `verify` CARRY
the driver's verdict as a more-accountable rung. The one local OS signal that *is*
domain-free (process-liveness) lands as a *rung in `liveness`*, not a driver and not in
`verify` — Phase 2. The host WIRES which oracle `verify` consults via `dos.toml`; an
unwired host gets git-only `verify`, byte-identical to today.

## 8. See also

- docs/109 — the original spec this makes concrete (the rung ladder, the conjunctive
  asymmetry, the `[verify]`/`[ci]` fold, the bench).
- docs/93 / docs/95 — the accountability spectrum + the demote-only `proc_delta` rung
  Phase 2 reuses; the file-mtime trap this designs out.
- docs/196 — the KV-cache witness, the *other* unbuilt consumer of this exact
  `dos.evidence_sources` seam (registering the group in Phase 0 unblocks both).
- `src/dos/evidence.py` — the shipped resolver (`active_evidence_sources`,
  `EVIDENCE_SOURCE_ENTRY_POINT_GROUP`) this plan finally feeds from a config string.
- `src/dos/drivers/ci_status.py` — the first occupant: `gather`/`classify`/`status_of`,
  the GREEN/RED/PENDING/NO_SIGNAL ladder, the one-way import.

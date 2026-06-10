# DOS — next-stage direction

Status: **directional foundation + index of the committed plans it spawned.**
Captures where the `dos` package goes after the v0.1.0 kernel extraction, at the
small/modular level the operator asked for. Each item is shaped so it can ship as
its own small, separately-tested slice — never a big-bang. The directions below
that have hardened into committed, phase-sliced plans are linked under
**Committed plans (the genericization series)**; the rest stay directional until
demand pulls them forward.

## Committed plans (the genericization series)

The throughline is one question: *can a stranger point DOS at their own repo and
have the syscalls work without adopting any job-specific convention?* The first
four plans close the named *syscall* gaps; SKP extends the throughline up one
layer to the *workflow* itself; DOS-HOME gives the generic default its own
state-home so the answer holds *across many* repos. **As of 2026-06-01 the answer
is "yes" for everything but the arbiter safety hooks: five of the six plans have
shipped — only ADM (Axis 3) remains open.**

| # | Plan | What it makes generic | Status |
|---|---|---|---|
| SCV | [70_stamp-convention-plan](70_stamp-convention-plan.md) | `verify`'s git rung recognized only *job* commit subjects. Now the ship grammar is `dos.toml` data — **strict job grammar by default, `style="loose"` opt-in with a warning** (reconciles reach vs the false-positive guard). `phase_shipped.py` reads the active `StampConvention` through one `_subject_matchers(cfg)` helper on every entrypoint; `cli.py` reads back `[stamp]`; `dos doctor` names the grammar and `--check` flags a declared `[stamp]` that covers no real ship. **Shipped 2026-06-01** (`tests/test_stamp_convention.py` + `tests/test_stamp_doctor.py`, 17 tests; `test_verify_no_plan.py` green on the strict default). | **shipped** |
| WCR | [71_workspace-config-readback-plan](71_workspace-config-readback-plan.md) | `[lanes]`/`[paths]` in `dos.toml` — `_apply_workspace` now reads back all four data tables (`[reasons]`/`[stamp]`/`[lanes]`/`[paths]`), so a host stands up a real concurrent, correctly-pathed workspace with no driver. `--job` < TOML precedence pinned; `dos doctor --check` flags treeless lanes. **Shipped 2026-06-01** (`tests/test_workspace_config.py`, 15 tests). | **shipped** |
| RND | [72_renderer-seam-plan](72_renderer-seam-plan.md) | Output (Axis 4) — the `--output <name>` renderer seam the README already advertised but didn't ship. Now real: `dos.render` (`Renderer` protocol + `Text`/`Json` built-ins + `dos.renderers` entry-point discovery), `--output` on `verify`/`arbitrate`/`man`, `examples/dos_ext` installable (`pip install -e` registers `terse`). Built-ins can't be shadowed; unknown `--output` fails loud; default path byte-identical. **Shipped 2026-06-01** (`tests/test_render.py`, 26 tests; HACKING §4 → shipped). | **shipped** |
| ADM | [73_admission-predicate-plan](73_admission-predicate-plan.md) | Arbiter safety (Axis 3) — pluggable conjunctive-only admission predicates; ships the `SELF-MODIFY` guard as the first built-in. Highest leverage + risk; ships last. **The one open plan** — no `src/dos/admission.py` / `AdmissionVerdict` / `SELF-MODIFY` predicate exists yet. | **committed — not started** |
| SKP | [74_skill-pack-plan](74_skill-pack-plan.md) | Workflow (Axis 5) — the `next-up`/`dispatch`/`replan` *screenplay*, formerly only in `job/.claude/skills/`. Ships a **generic skill pack with DOS** in the wheel (`dos/skills/<name>/SKILL.md`, package-data), driven by `dos` verbs + `dos.toml` data; adds two thin verbs (`dos doctor --json`, `dos gate`). Five generic skills name no host path/lane/convention (pinned by `tests/test_skill_pack_*.py`); the seam ledger (`74-seam-ledger.md`) maps every POLICY line to its data/hook home and the friction log (`74-friction-log.md`) records the three open seams (packet template, evidence sources, heavy leasing tier). **Shipped 2026-06-01.** | **shipped** |
| DOS-HOME | [75_state-home-plan](75_state-home-plan.md) | The generic default's own *body*: a per-project `.dos/` (gitignored, auto-created on the first persisting syscall) collecting every DOS emission, plus a machine-local `~/.dos` *projection* (`projects/index.jsonl`, `decisions.jsonl`) that `dos reindex` rebuilds and never treats as source of truth. `job` does not move (`job_config` keeps `for_root`). Ships `src/dos/home.py` + the `dos reindex`/`projects`/`learn` home verbs. **Shipped v1+v2 2026-06-01** (`tests/test_{state_home,ensure_home,home_layering,central_index,reindex}.py`). | **shipped** |

Build order was dependency- and risk-ordered: SCV/WCR make the *truth* and
*admission-discovery* syscalls honest for a foreign repo; RND extends the output
surface HACKING.md sketched as 🔜 *design*; SKP sits on top, making the *workflow
that calls the syscalls* portable; DOS-HOME then gives the generic default a clean
state-home across many repos. **ADM (the arbiter safety hooks) is the last open
plan and deliberately ships last** — it touches the safety core. SCV led and
absorbed the shared phase-0 housekeeping (single-version, the one red
`test_decisions` case) so the rest of the series started green.

> **Companions (theory + instruments, not phased plans):**
> - [`76_flexible-goals-and-verification`](76_flexible-goals-and-verification.md) —
>   the *why* under HACKING.md: where a DOS-based system is allowed to flex when it
>   defines a goal and verifies it (the recognizer, as data; the goal, in the
>   driver) and where it must never (the verdict vocabulary + the evidence→verdict
>   rule).
> - [`79_primitives-not-features`](79_primitives-not-features.md) — why the four
>   syscalls are each deliberately small: a primitive makes a *space* buildable,
>   and the interesting things grow in the layer above without the syscall moving.
> - [`80_mcp-server-surface`](80_mcp-server-surface.md) — the **adoption surface**:
>   the syscalls exposed as MCP tools (`src/dos_mcp/`, `pip install dos-kernel[mcp]`) so any
>   MCP host (Claude Desktop/Code, Cursor, Cline) calls the referee with zero Python
>   coupling. Built agent-friendly (per-tool "use this when", actionable
>   `interpretation` fields, user-invokable prompts, browsable resources); a shipped
>   consumer of `dos`, fenced off from the kernel like the release tooling.
> - [`81_velocity-economics-and-the-fleet-benchmark`](81_velocity-economics-and-the-fleet-benchmark.md)
>   — the *second* axis of fleet effectiveness beside integrity: the collaboration
>   economics (coordination dividend, merge-conflict detonation cost, the review-queue
>   bottleneck, plan-then-adjudicate-completeness), the theory + prior-art behind each,
>   the **verified-velocity-per-$** metric family that extends `benchmark/fleet_horizon`,
>   and why this defines a benchmark *category* (a harness benchmark with a velocity
>   headline), not a new row.
>
> These are design notes — they carry no phases/litmus and are not in the table.

## North star

**A user can verify a claim, refuse with a reason, or arbitrate a lease without
adopting any of the host's workflow.** The kernel is mechanism; everything
workflow-shaped (phased plans, soft-claims) is a host concern layered *on top*,
never a prerequisite. See `CLAUDE.md` for the layer contract this direction must
preserve.

**Update (SKP, 2026-06-01): the dispatch/next-up skills are no longer purely
out-of-scope.** DOS now ships a *reference* workflow — the generic skill pack in
the wheel (`dos/skills/`) that drives the syscalls in order against any repo whose
layout lives in `dos.toml`. This does not contradict the North Star: the *shape*
of the workflow is domain-free mechanism (shipped), while *host-specific*
workflow (a host's plan grammar, its soft-claim tier, its evidence sources)
stays the host's. The skill pack is a baseline a stranger may use, fork, or
ignore — adopting it is not required to get value from the syscalls.

The litmus already holds for `verify`: `dos verify --workspace <repo> PLAN PHASE`
runs against a plain git repo with no phased plan (proven by
`tests/test_verify_no_plan.py`). The work below extends that "usable without the
workflow" property across the rest of the ABI, and hardens the kernel/driver
boundary.

## Direction (small, modular, test-each-step)

1. **Keep pulling kernel ⟂ driver apart.** v0.1.0 split the job lane taxonomy
   into `dos.drivers.job`. Continue: any remaining host-specific assumption that
   leaks into `src/dos/*` (a hardcoded path shape, a job-flavored default) moves
   to a driver or to `SubstrateConfig`. Acceptance per step: the kernel suite
   stays green AND a one-line litmus (kernel imports no host name) holds.

2. **Each syscall gets a no-workflow proof, like `verify` has.** Add the sibling
   of `test_verify_no_plan.py` for `refuse` and `arbitrate`: each must be callable
   (library + CLI) against a bare workspace with no plan/registry, returning a
   structured result, never crashing for lack of host workflow.

3. **A second driver, to prove the seam isn't job-shaped.** Add a minimal
   `dos.drivers.generic` (or a tiny example host) so there are two drivers, not
   one. Two consumers is what proves the policy boundary is real rather than a
   rename. Small: a taxonomy + a `*_config` factory + one test.

4. **The foreign-repo research surface is host-side, not kernel.** The "point
   the OS at a foreign repo, read via `--workspace`, write nothing into the
   target" research lives host-side (pure stdlib). Its productization path —
   point the OS at a foreign repo's issues and open verified PRs — is tracked as
   a **host-side phased plan** (the ISV series), not here. If/when it grows code,
   it graduates into either the kernel (if mechanism) or a driver (if policy) —
   decided per the layer contract.

5. **Versioning discipline.** `dos` is independently versioned (`__version__` in
   `src/dos/__init__.py` + `pyproject.toml`, kept in lockstep). Cut a tag when the
   kernel ABI changes; consumers pin the **`dos-kernel`** distribution
   (`dos-kernel>=X.Y` / `==X.Y.Z`) — the bare PyPI name `dos` is an unrelated
   package, never pin it. The kernel suite is the release gate — no tag on a red
   suite.

6. **Claim `dos-kernel` on PyPI (open follow-up).** The distribution was renamed
   from `dos` to `dos-kernel` because the bare `dos` name is squatted (an
   unrelated Flask/OpenAPI package); see `SECURITY.md` "Supply chain". The build
   is verified publish-ready (`python -m build` → `dos_kernel-X.Y.Z`, clean-venv
   wheel install works). **Next steps, both outside the kernel:**
   - **Run the first `twine upload`** (the `/release` skill now carries the step)
     to claim `dos-kernel` before anyone squats *that* name too. Until then,
     `pip install dos-kernel` will not resolve — local/dev use is `pip install -e .`.
   - **Update the reference userland app's pin** from `dos>=0.1.0` to
     `dos-kernel` (a host-repo edit, not a kernel change).

## Cross-references (host-side)

These are the reference userland app's phased plans that consume this kernel —
they belong in the host repo, not here, because they encode host workflow +
policy:

- **DSP** — port the hottest spine command to Go for cold-start latency;
  differential-tested against this Python kernel as the executable spec.
- **DOM** — a `man`-pages projection over the kernel's registries
  (`wedge_reason`, lanes, plan-meta, oracles).
- **ISV** — the foreign-repo issue→verified-PR demo (a host-side research
  surface that points the OS at a foreign repo's issues, reads via
  `--workspace`, and writes nothing into the target).

The boundary: **this doc is about the substrate's own modularity; those are about
what hosts build with it.**

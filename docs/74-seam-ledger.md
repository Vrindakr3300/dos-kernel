# SKP Phase 0 — the seam ledger (next-up dissection)

> **Status:** the committed Phase-0 litmus of [SKP](74_skill-pack-plan.md). For
> the heaviest `verify` consumer (`next-up`, the first vertical slice), this
> tables every shelled command / hardcoded path / convention name in the reference app's
> skill and classifies each as **MECHANISM** (liftable, identical across hosts)
> or **POLICY** (must become data/hook), naming the destination for each POLICY
> item — and, crucially, the ones with **no destination yet** (the genuine kernel
> gaps SKP surfaces, fed to the Phase-5 friction log).

The method is *dissection-by-observation*: pin exactly which lines are screenplay
shape vs host policy before porting prose. The source is the reference app's own
`next-up` skill (479 lines); the destinations are
the four `dos.toml` data tables (all read back after SCV+WCR), an optional
driver hook, or — where neither fits — a named open seam.

## The two cuts SKP makes

`CLAUDE.md` says the phased-plan *workflow* is host concern. SKP refines that:

- **Workflow MECHANISM** — the *shape* "snapshot the portfolio → audit each pick
  against `verify` → render a packet → gate the empty case → take a lease →
  archive." Domain-free, identical across hosts. This is what the generic
  `dos-next-up` screenplay ships.
- **Workflow POLICY** — which lanes, which plan grammar, the commit-subject
  template, the packet sections. Host's, declared in `dos.toml`/driver.

The ledger is the line-by-line application of that cut to `next-up`.

## next-up — shelled commands

| reference-app invocation | MECHANISM / POLICY | Generic destination |
|---|---|---|
| `python scripts/next_up_context.py` (bundle the portfolio context) | MECHANISM (bundle) wrapping POLICY (which evidence files) | The bundle *shape* is mechanism; the source paths are `[paths]` data. The generic skill bundles from `dos doctor --json` (paths) + the plans glob — no `next_up_context.py`. |
| `python scripts/next_up_render.py plan --scope <…> --focus <…>` (emit candidates JSON) | MECHANISM (walk plans, rank) + POLICY (scope/focus vocab, packet template) | The *walk + per-pick audit* is mechanism (the skill walks the `[paths] plans_glob` and calls `dos verify` per pick). The packet **template** is POLICY with **no kernel destination yet** — see the gap below. |
| `python scripts/next_up_render.py validate --tag <tag>` (validate the picks JSON) | MECHANISM | A schema check; the generic skill validates inline (the holes JSON is small, self-authored). |
| `python scripts/next_up_render.py render --tag <tag>` (render the packet) | MECHANISM (assemble) + POLICY (sections, subject) | The generic skill **assembles the packet itself** from the audited picks + `dos doctor --json`, writing to `[paths] next_packets`. The exact section grammar is the open `[render]` template gap. |
| `python scripts/check_phase_shipped.py --batch` (per-pick ship audit, called by the renderer) | MECHANISM | **`dos verify PLAN PHASE --json`** — the truth syscall, already generic (reads `[stamp]`, no plan needed). This is the single most important relocation: the skill audits each pick through the kernel verb. |
| `python scripts/fanout_state.py register --ttl-minutes 90` (soft-claim the picks) | POLICY (the heavy soft-claim lease core) | **Scoped OUT for v1** (`CLAUDE.md` heavy tier). The generic loop uses `dos arbitrate`/`dos lease` for lane coordination, not the soft-claim core. Named in the friction log. |
| `python scripts/dispatch_loop_status.py --leases --json` (scoped-run lease pre-check) | MECHANISM (read live leases) | Lease state the skill passes to **`dos arbitrate --leases`**; the live-lease list is what the arbiter consumes. |

## next-up — hardcoded paths

| reference-app literal | MECHANISM / POLICY | Generic destination |
|---|---|---|
| `output/next-up/` (packet output dir) | POLICY | `[paths] next_packets` (WCR) — `.dos/verdicts` under the generic default, `output/next-up` under the reference app's layout. The skill reads it from `dos doctor --json`. |
| `output/next-up/.ctx.json`, `.plan-out.json`, `.holes-<tag>.json`, `.verdict-<tag>.json`, `.candidates-<tag>.json` (scratch sidecars) | MECHANISM (per-run scratch) | The generic skill keeps its scratch under `[paths] next_packets` too; the *names* are the skill's own, not host policy. |
| `output/next-up/.dispositions-<tag>.json` (the OC3 gate sidecar) | MECHANISM (the gate contract) | The schema `oc3-dispositions-v1` is the kernel's; the skill writes it and gates via **`dos gate <packet>`** (SKP Phase 1). |
| `docs/_plans/execution-state.yaml` (the registry) | POLICY | `[paths] execution_state` (WCR). The skill never names it directly — `dos verify` reads it through the active config. |
| `docs/_plans/next-hits.md`, `replan-state.yaml`, `disjoint-clusters.md` (curated inputs/cooldown) | POLICY (host-specific evidence sources) | **No kernel destination** — these are the reference app's gardening surfaces. The generic skill works without them; an evidence-source hook is a named friction-log seam. |
| `docs/_plans/` (plans dir, implicit in the glob) | POLICY | `[paths] plans_glob` (WCR) — e.g. `planning/*.md`. The grep of a shipped generic skill for `docs/_plans` returns nothing. |

## next-up — convention / lane names

| reference-app literal | MECHANISM / POLICY | Generic destination |
|---|---|---|
| `apply` / `tailor` / `discovery` / `orchestration` (the `--scope` cluster names) | POLICY | `[lanes]` (WCR). The skill reads the active lane names from `dos doctor --json`; it never names a host lane. |
| `docs/<SERIES>:` (the direct-ship subject the audit greps) | POLICY | `[stamp]` grammar (SCV). The skill never greps subjects itself — `dos verify` applies the active `StampConvention`. |
| `--focus` aspects (`not-started` / `priority-first[:N]` / `nearly-done` / `stale-stamp`) | MECHANISM (state-of-plan axes) with POLICY tuning | The axes are generic ways to read a plan's state; the generic skill supports the domain-free ones (not-started / nearly-done / stale-stamp via `dos verify`) and leaves host-specific ranking to a driver. |

## The frontmatter

The reference app's `next-up` carries `name` / `description` / `output_root: runs/plans/` /
`retention: 30d`. MECHANISM (the skill envelope) with one POLICY field
(`output_root`). The generic `dos-next-up` keeps `name`/`description` and drops
the hardcoded `output_root` — its output goes to `[paths] next_packets`,
resolved at run time, not baked into frontmatter.

## The genuine kernel gaps (no destination yet → friction log)

These are the lines that could **not** be made generic by an existing
data table or hook — the seams SKP surfaces for a future plan (Phase 5c):

1. **The packet template.** `next_up_render.py render` carries the *exact* packet
   sections + the commit subject. RND's `--output` covers verdict/decision/
   timeline/man/decisions — **not** packet rendering (there is no `render_packet`
   on the `Renderer` protocol). So in v1 the generic `dos-next-up` skill
   **assembles the packet markdown itself** (from `dos verify --json` per pick +
   `dos doctor --json`), keeping the reference app's template out of the kernel. A `[render]`
   packet-template data seam (or a `render_packet` protocol method) is the named
   open axis.
2. **Evidence sources.** `next-hits.md` / `replan-state.yaml` / the postmortem
   stream are the reference app's gardening inputs with no generic analogue. An evidence-source
   driver hook is the seam; v1 works without them.
3. **The heavy soft-claim leasing tier.** `fanout_state.py register` (soft-claim
   core), `next_up_focus.py` (value-greedy scheduler), and the rate-limit resume
   machinery stay in the reference userland app (`CLAUDE.md` heavy tier). The generic loop uses
   `arbitrate`/`lease` for the lighter lane-coordination path and `log`s what it
   is NOT doing — no silent capability gap.

## What this ledger establishes

For `next-up`, **every POLICY line has a destination** — three of them already
shipped data tables (`[paths]`/`[lanes]`/`[stamp]` via WCR+SCV), the gate via the
new `dos gate` verb, the truth audit via the already-generic `dos verify` — and
the three that do **not** are named, bounded, and routed to the friction log
rather than forced into the kernel. That is the Phase-0 litmus: a generic
`dos-next-up` can be authored that names no `docs/_plans`, no `apply`/`tailor`,
no `docs/<SERIES>:`, and shells only to `dos` verbs.

# SKP — Skill-pack plan (Axis 5: the workflow screenplay, shipped as a baseline)

> **Status:** ✅ **SHIPPED** (2026-06-01). Fifth in the genericization series, and
> the first to address *workflow* rather than a syscall
> ([SCV](70_stamp-convention-plan.md) → [WCR](71_workspace-config-readback-plan.md)
> → [RND](72_renderer-seam-plan.md) → [ADM](73_admission-predicate-plan.md) → SKP
> → [DOS-HOME](75_state-home-plan.md)). Built on the now-landed WCR `[paths]`/`[lanes]`
> read-back. Five generic screenplays ship in the wheel under
> `src/dos/skills/{dos-next-up,dos-dispatch,dos-dispatch-loop,dos-replan,dos-replan-loop}/SKILL.md`,
> driven entirely by `dos` verbs (incl. the two new ones, `dos doctor --json` +
> `dos gate`) and `dos.toml` data; each names no host path/lane/convention. The
> seam ledger (`74-seam-ledger.md`) maps every POLICY line to its data/hook home;
> the friction log (`74-friction-log.md`) records the three open seams (packet
> template, evidence sources, the heavy leasing tier). Pinned by
> `tests/test_skill_pack_{generic,dispatch,replan,litmus}.py`. Method was
> *dissection-by-observation*: port one skill as a vertical slice, prove each
> kernel/host seam against a foreign repo, record what resisted genericization
> rather than forcing it.

## The gap this closes

DOS ships the *mechanism* the dispatch workflow leans on — `verify`, `refuse`,
`arbitrate`, the typed gate, the correlation spine — and `HACKING.md` makes four
**axes** of it hackable (reasons, gate concepts, admission predicates, renderers).
But the **workflow that sequences those syscalls** — the Claude Code skills
`next-up` / `dispatch` / `replan` / `dispatch-loop` / `replan-loop` — lives
**only in the host's own skills**, is 100% host-shaped, and is explicitly
framed everywhere as "host concern, not a prerequisite" (`next-stage-plan.md`
North Star; `CLAUDE.md` layer table).

The result: a stranger who `pip install dos-kernel` (the dist name — the bare
`dos` PyPI name is an unrelated package) gets honest syscalls and **no way to
drive them**. They must reverse-engineer five large screenplays (the reference app's
`dispatch/SKILL.md` is 88 KB, `dispatch-loop` 140 KB) and the fat host
orchestrators behind them (`next_up_render.py`, `replan_autoclose.py`,
`fanout_state.py`) before DOS does anything end-to-end. `examples/dos_ext/` shows
how to add a *reason* or a *renderer*; nothing shows how to **run a plan-and-ship
cycle**.

This plan ships a **generic skill pack with the package** — a baseline screenplay
that drives the kernel against any repo, with all host specifics in `dos.toml`
(WCR data) or an optional driver hook (code). Adopting it is not required to get
value from DOS; it is the reference workflow, the way `BASE_REASONS` is the
reference refusal vocabulary and `examples/dos_ext` is the reference plugin.

### Why this is a real axis, not a contradiction of the layer contract

`CLAUDE.md` says the phased-plan *workflow* is host concern. That stays true: the
**owner of a workspace's policy** is still the host. What SKP adds is a
distinction the layer table currently collapses —

- **Workflow policy** (which lanes, which plan grammar, the commit-subject
  template, the packet sections) — host's, declared in `dos.toml`/driver.
- **Workflow mechanism** (the *shape* of "snapshot the portfolio → audit each
  pick against `verify` → render a dispatch packet → gate the empty case → take a
  lane lease → archive") — domain-free, and identical across hosts.

The second is as liftable as the syscalls were. The reference app's skills prove the shape
works; SKP extracts the shape, leaves the policy as data, and ships the result so
a new host fills in a `dos.toml` instead of authoring 300 KB of prose. This is
**Axis 5 — workflow** in `HACKING.md`'s frame: not data (`dos.toml`), not behavior
(`entry_points`), but the *screenplay* that calls the syscalls in order. DOS ships
a reference one; a host may use it, fork it, or ignore it.

## Design laws this plan must honor

- **A generic skill names no host path, lane, or commit convention.** Every
  literal the reference app's skills hardcode — `docs/_plans/`, `output/next-up/`,
  `apply`/`tailor`/`discovery`, `docs/dispatch:` — comes from `dos doctor --json`
  (paths/lanes, via WCR) or `dos.toml [stamp]`/`[render]` (grammar/template). A
  grep of a shipped generic skill for `docs/_plans` or `apply` returns nothing.
  This is the skill analogue of "kernel imports no host."
- **The skill shells out to `dos`, never to a host's fat scripts.** Where a reference-app
  skill runs `python scripts/next_up_render.py`, the generic skill runs a `dos`
  subcommand. New kernel verbs (`dos doctor --json`, and a generic renderer entry)
  are the seam; the screenplay carries no Python of its own.
- **Battle-scarred correctness is preserved, not rewritten.** The reference app's skills
  encode hard-won fixes (FQ-77 bookkeeping exclusion, the empty-packet gate, the
  hard-locked pathspec discipline). Genericization *relocates* these into the
  kernel/config, it does not relax them. Each phase proves the relocated behavior
  matches the reference app's behavior before its prose is touched.
- **Minimal diff, prove-then-move.** Per the operator's method: change as little
  as possible per step, pull apart one seam, validate it against a throwaway
  foreign repo, and write any genericization insight that doesn't yet have a home
  into this plan's "Observed friction" log (Phase 5) rather than coding ahead of
  proof.

## North-star acceptance (the whole plan is done when)

```bash
pip install -e .                      # the skill pack ships under dos/skills/
dos init /tmp/svc && cd /tmp/svc      # scaffold dos.toml (lanes/paths/stamp)
# ... a repo with a couple of `planning/*.md` plans and real commits ...

# The generic next-up skill, driven entirely by dos verbs + dos.toml:
claude -p "/dos-next-up"              # writes a dispatch packet under the
                                      #   configured next_packets path, with
                                      #   each pick's status from `dos verify`,
                                      #   and NO reference to docs/_plans or
                                      #   host lanes anywhere in the run.
dos gate <that-packet>                # LIVE | DRAIN | STALE-STAMP, typed
```

…with the reference app's skills still working byte-for-byte (they keep their driver), the
existing kernel suite green, and a `tests/test_skill_pack_generic.py` proving the
generic `dos-next-up` produces a coherent packet against a foreign repo with **no
host-specific config**.

---

## Phase 0 — the gap audit + the seam ledger (no code)

Before porting prose, pin exactly which lines of each reference-app skill are *mechanism*
(liftable) vs *policy* (must become data/hook). This is the dissection map the
rest of the plan executes against.

- **0a.** For `next-up` (the heaviest `verify` consumer, the first slice), table
  every shelled command, every hardcoded path, every lane/convention name, and
  classify each as MECHANISM or POLICY, with the destination for each POLICY item
  (`[paths]` / `[lanes]` / `[stamp]` / `[render]` / driver hook). Repeat lighter
  passes for the other four.
- **0b.** Record the verified seam state this plan builds on (already established
  2026-05-31, see the throughline below): **SCV stamp readback is shipped and
  proven on a foreign repo; WCR `[lanes]`/`[paths]` readback is NOT yet wired
  (`dos doctor` ignores them).** SKP Phase 1 therefore cannot begin until WCR
  Phase 2 lands. State this dependency as a hard gate.
- **0c.** Decide the skill-pack home, distinguishing two audiences the repo now
  separates (`CLAUDE.md`'s "Release & dev tooling is OUTSIDE these four layers"):
  the `/release` + `/stable-release` skills in `.claude/skills/` are **dev tooling
  that maintains the package** (repo-local, not shipped to consumers). The SKP
  pack is the opposite — a **baseline workflow for *consumers* of the package**,
  so it ships *in the wheel* at `dos/skills/<name>/SKILL.md` (a
  `[tool.setuptools.package-data]` / `MANIFEST.in` entry), discoverable by a host
  that copies it into its own `.claude/skills/`. Both import `dos` / shell the CLI
  with the same one-way arrow (nothing under `src/dos/` imports them), so SKP
  honors the just-documented contract; it differs from the release skills only in
  audience and delivery (shipped vs repo-local). Confirm SKP is *native* owner
  code in this repository (like `70`–`73`), not a host-narrative stub.

**Litmus (Phase 0):** a committed `docs/74-seam-ledger.md` (or an appendix here)
that, for `next-up`, lists every POLICY line with its data/hook destination — and
names the ones with **no destination yet** (the genuine kernel gaps SKP surfaces,
e.g. a packet-template seam `[render]` that RND's `--output` does not cover).

---

## Phase 1 — `dos doctor --json` + `dos gate` (expose what the screenplay needs)

A generic skill discovers its layout and gates its empty case through the CLI.
Two thin verbs, both over machinery that already exists.

- **1a.** Add `--json` to `dos doctor`: emit `{workspace, paths:{…}, lanes:{…},
  stamp:{…}, git:bool}` — exactly the fields `doctor` already computes and prints
  (`cli.py:371-377`), as a machine-readable object a skill reads with one call.
  Text output stays byte-identical when `--json` is omitted.
- **1b.** Add `dos gate <packet>` (or `dos gate --picks N --…`): expose the typed
  empty-packet verdict (`gate_classify` / `tokens.GateVerdict` —
  `LIVE`/`DRAIN`/`STALE-STAMP`/`BLOCKED`/`RACE`) that the reference app's dispatch-loop
  computes inline today. The classifier exists in the kernel; this is a CLI
  surface over it, no new logic.
- **1c.** Verify both against the throwaway foreign repo (the SCV test rig:
  `PYTHONPATH=src python -m dos.cli`, BOM-free `dos.toml`): `doctor --json` on a
  repo with WCR-declared `[paths]` reports the *declared* glob, not the default.

**Litmus (Phase 1):**
- `test_doctor_json_reports_declared_paths` — with WCR landed, a workspace whose
  `dos.toml` sets `plans_glob="planning/*.md"` has `doctor --json` emit that glob.
- `test_gate_classifies_empty_packet` — a zero-pick packet returns `DRAIN`; a
  packet whose picks ship-but-aren't-stamped returns `STALE-STAMP`, through the
  CLI.
- Both default-text outputs unchanged (byte-identical litmus).

---

## Phase 2 — the generic `dos-next-up` skill (the throughline)

The first full vertical slice: one shipped, generic screenplay that drives a
plan-and-ship snapshot end-to-end with zero host specifics.

- **2a.** Author `dos/skills/dos-next-up/SKILL.md`: a screenplay that (1) calls
  `dos doctor --json` for paths/lanes, (2) walks the plans glob, (3) for each
  candidate pick calls `dos verify PLAN PHASE` for its true status, (4) renders a
  dispatch packet to the configured `next_packets` path, (5) reports a typed
  outcome via `dos gate`. No `docs/_plans`, no `apply`/`tailor`, no
  `next_up_render.py`.
- **2b.** Where `next_up_render.py` carries *generic* rendering (walk plans, audit
  via verify, emit a packet) vs the *host's* template (exact sections, commit subject),
  lift the generic half into a kernel entry the skill calls (a `dos next-up`
  emit, or — preferred, to reuse RND — a renderer the skill selects). Leave the
  template as a `[render]` data seam (Phase 0 flagged whether RND's `--output`
  covers this or a new `[render]` table is needed). **Do not port the host's
  template into the kernel.**
- **2c.** Prove it: run `/dos-next-up` against the foreign repo and assert the
  packet names the foreign repo's plans/phases with correct shipped/unshipped
  status, and that the run touched no host path.

**Litmus (Phase 2):**
- `test_skill_pack_generic.py::test_dos_next_up_foreign_repo` — drives the skill's
  scripted steps against a tmp foreign repo (no `--job`, generic `[stamp]`), and
  asserts a coherent packet with verify-backed statuses.
- A grep guard: the shipped `dos-next-up/SKILL.md` contains none of
  `{docs/_plans, output/next-up, apply, tailor, discovery, docs/dispatch:}`.

---

## Phase 3 — the lease-aware skills (`dos-dispatch`, the loop) over `arbitrate`/`lease`

`dispatch` and `dispatch-loop` add concurrency: a lane lease so parallel loops
don't collide, and the typed gate driving continue/stop. The admission kernel
(`dos arbitrate`) and the cross-process mutex (`dos lease`) already exist as CLI
verbs; the heavy `fanout_state.py` soft-claim core does not port in v1.

- **3a.** Author `dos/skills/dos-dispatch/SKILL.md`: the chained
  snapshot→ship cycle, taking a lane via `dos arbitrate --lane L --kind cluster
  --leases <live>` (trees from WCR `[lanes.trees]`) before launching, and
  archiving under a `dos.toml`-declared run dir. The "may I run on this lane"
  decision is the kernel's, not inline prose.
- **3b.** Author `dos/skills/dos-dispatch-loop/SKILL.md`: the dispatch⇄replan
  cadence, with the continue/stop decision from `dos` (the `loop_decide` surface,
  exposed as a verb if not already) and the typed gate from Phase 1. The
  drained-twice / dirty-zero breakers are kernel policy (`loop_decide.decide`),
  not re-implemented in the screenplay.
- **3c.** Explicitly scope OUT the soft-claim leasing, focus scheduler, and
  rate-limit resume machinery that `fanout_state.py` / `next_up_focus.py` own —
  these are the "heavy tier" `CLAUDE.md` already parks in the reference userland app. The generic loop
  uses `arbitrate`/`lease` for the lighter lane-coordination path and `log`s what
  it is NOT doing (no silent capability gap).

**Litmus (Phase 3):**
- `test_dos_dispatch_takes_lane` — two generic-skill dispatch runs on disjoint
  WCR-declared lanes both ADMIT; on overlapping trees the second gets a
  COLLISION, through `dos arbitrate`.
- `test_dos_loop_stops_on_drain_twice` — the loop's scripted decision calls
  `loop_decide` and halts after two consecutive `DRAIN`s.

---

## Phase 4 — the planning skills (`dos-replan`, `dos-replan-loop`)

`replan` gardens the portfolio from accumulated evidence. Its mechanism (read
findings, detect closures via `verify`, rerank a queue) is liftable; its evidence
*sources* and gardening *passes* are heavily host-specific.

- **4a.** Author `dos/skills/dos-replan/SKILL.md` covering the domain-free core:
  closure detection (a queue item whose phases now `verify` as shipped is closed),
  cooldown-state tracking, and the ruthless operator-summary (0–2 items). The
  host-specific gardening passes (anchor reconciliation, soak-state drift, the
  apply-postmortem stream) become driver hooks or are scoped OUT for v1.
- **4b.** Author `dos/skills/dos-replan-loop/SKILL.md`: the thin recurring wrapper
  (it is already mostly orchestration over `/replan` + a guarded release). The
  release guards (HEAD-on-trunk, docs-only) reference the workspace's trunk from
  config, not a hardcoded `main` (note: this repo's trunk is `master`).
- **4c.** Reconcile the `dos decisions` queue (already shipped) as the generic
  operator-inbox surface `replan` writes to — replacing the reference app's
  `decisions-pending.md` literal with the kernel's decisions projection where they
  overlap.

**Litmus (Phase 4):**
- `test_dos_replan_closes_shipped_item` — a queue item whose phases verify as
  shipped is moved to closed by the scripted replan steps.
- The release-guard reads trunk from config (a `master`-trunk repo is handled).

---

## Phase 5 — the workflow axis in the docs + the friction log

Make Axis 5 first-class in the hackability story, and capture what resisted
genericization so the next iteration has a target.

- **5a.** Add **Axis 5 — Workflow** to `HACKING.md`: the screenplay that sequences
  syscalls, shipped as `dos/skills/`, customizable via `dos.toml` (paths/lanes/
  stamp/render) + optional driver hooks; the two-attachment-model table grows a
  row. Flip the relevant sub-statuses to ✅ as phases land.
- **5b.** Add SKP to `next-stage-plan.md`'s committed-series table and update its
  North Star: skills are *no longer purely out-of-scope* — DOS ships a reference
  workflow, while host-specific workflow stays the host's.
- **5c.** **Observed-friction log** (the operator's "reflect and record" ask):
  a running list of every place a reference-app skill behavior could NOT be made generic
  in a phase — what it was, why (TOML can't express it / it's genuinely
  host-policy / it needs a kernel seam that doesn't exist) — feeding future plan
  items (a `[render]` template axis, an evidence-source hook, a focus-scheduler
  port). This is where insight that outran the build gets written down instead of
  coded ahead of proof.

**Litmus (Phase 5):** `HACKING.md` lists five axes with Axis 5 specified and its
example skill referenced; `next-stage-plan.md` indexes SKP; the friction log names
at least the known-open seams (packet template, evidence sources, the heavy
leasing tier).

---

## Out of scope (explicitly)

- **Porting the heavy tier.** `fanout_state.py`'s soft-claim lease core,
  `next_up_focus.py`'s value-greedy scheduler, and the rate-limit resume machinery
  stay in the reference userland app (`CLAUDE.md`'s "heavy tier"). The generic loop uses
  `arbitrate`/`lease` for lane coordination and is honest about the gap. A full
  lease-core port is a separate plan if demand pulls it.
- **Migrating the reference app off its skills.** The reference app keeps its five driver-backed skills;
  they have computed/reference policy and battle-scarred tuning. SKP adds the
  generic baseline for *new* hosts, it does not force the reference app onto it (mirrors WCR's
  "does not migrate the reference app off its driver").
- **A skill runtime.** SKP ships *screenplays* (SKILL.md) that drive the existing
  `dos` CLI under Claude Code. It does not build a new execution engine; the
  Claude Code skill mechanism is the host.
- **TOML-declared behavior.** Where a skill needs *code* (a computed commit
  subject, a bespoke evidence reader), that is a driver hook or an `entry_point`,
  never `dos.toml` — the HACKING.md data/behavior split holds.

## Why this is fifth (and depends on WCR)

SCV/WCR/RND/ADM make the *syscalls* honest and open for a stranger's repo. SKP is
the first plan to make the *workflow* portable — and it can only stand on a
workspace that already reads its lanes and paths from data, which is precisely
WCR. (SCV is already sufficient on the `verify` side: proven 2026-05-31 — a
foreign repo with `dos.toml [stamp] subject_dirs=["src"]` has `dos verify`
recognize `src/BAR: BAR2` as shipped.) Until WCR Phase 2 lands, a generic skill
would have to hardcode `docs/_plans/` — reintroducing the exact host-coupling this
series exists to remove. So SKP is gated on WCR, rides the `dos doctor`/`gate`
surfaces it adds in Phase 1, and reuses RND's renderer seam for packet output
where it fits. It is last because workflow is the top of the stack: it composes
every syscall the earlier plans made generic.

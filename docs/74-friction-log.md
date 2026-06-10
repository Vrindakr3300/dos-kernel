# SKP — observed-friction log

> **The "reflect and record" deliverable** ([SKP](74_skill-pack-plan.md) Phase
> 5c). A running list of every place a reference-app skill behavior could **not** be made
> generic in a phase — what it was, why it resisted (TOML can't express it / it's
> genuinely host policy / it needs a kernel seam that doesn't exist), and where it
> feeds. This is where insight that outran the build gets written down instead of
> coded ahead of proof. The companion [seam ledger](74-seam-ledger.md) is the
> *destinations* map; this is the *gaps* map.

Each entry: **what resisted · why · disposition** (the future plan item, or the
deliberate scope-out, it becomes).

## F1 — the packet template has no kernel home (open seam)

**What.** The reference userland app's `next_up_render.py render` carries the exact dispatch-packet
*template*: the section order, the per-pick prompt shape, the archive commit
subject. The generic `dos-next-up` needs to emit *a* packet, but must not bake
the reference app's template into the kernel.

**Why it resisted.** RND's `Renderer` protocol (`src/dos/render.py`) covers
`render_verdict` / `render_decision` / `render_timeline` / `render_man` /
`render_decisions` — the *syscall outputs*. There is **no `render_packet`**, and a
packet is not a syscall output — it is a composed artifact (walk + audit + lay
out). TOML can't express a template (that's behavior, not data), and a kernel
`render_packet` would have to encode *some* section grammar, which is host policy.

**Disposition.** v1 has the **skill assemble the packet itself** from
`dos verify --json` (per-pick status) + `dos doctor --json` (paths/lanes),
writing to `cfg.paths.next_packets`. The reference app's template stays out of the kernel.
The named future seam: a `[render]` **packet-template data table** (section
list + subject grammar as data) OR a `render_packet(picks, ctx) -> str` protocol
method on RND. Until demand pulls it, the skill's self-assembly is the contract.

## F2 — host evidence sources have no generic analogue (driver-hook seam)

**What.** The reference app's `next-up`/`replan` read curated evidence: a hand-ranked
next-hits file, a cooldown-state file, a postmortem stream, an INDEX of past
runs. These shape *which* picks surface and *what* the operator sees.

**Why it resisted.** These are host gardening *inputs* — there is no domain-free
"curated ranking" or "postmortem" a stranger's repo has. Forcing them into the
generic skill would re-couple it to the reference app's surfaces; making them TOML data
wouldn't help (the *content* is the host's, not just the path).

**Disposition.** The generic skills rank by a **domain-free signal** (plan-doc
order + `dos verify` status) and surface via the kernel's `dos decisions` queue.
The named future seam: an **evidence-source driver hook** (a host registers a
reader that contributes ranked candidates / findings). v1 works without it and
`log`s that it is not consulting host evidence — no silent gap.

## F3 — the heavy soft-claim leasing tier stays host-side (deliberate scope-out)

**What.** The reference app's `fanout_state.py` soft-claim core (per-pick claims with TTL),
`next_up_focus.py`'s value-greedy scheduler, and the rate-limit predictive
monitor + resume manifest. The reference app's dispatch loop leans on all three.

**Why it resisted.** This is the `CLAUDE.md` **heavy tier** — heavy I/O + host
workflow, explicitly parked in the reference userland app, not kernel mechanism. The generic loop
needs *lane* coordination, which the pure `dos arbitrate` already provides; it
does not need the per-pick soft-claim core to be useful.

**Disposition.** `dos-dispatch` / `dos-dispatch-loop` use `dos arbitrate` (lane
lease) + `dos lease` (cross-process mutex) for the lighter lane-coordination
path. They `log` what they are NOT doing (no per-pick soft-claim, no focus
scheduler, no rate-limit resume) so the capability gap is named. A full
soft-claim-core port is a **separate plan if demand pulls it** — not folded in.

## F4 — the release-guard trunk is a host fact, not in the doctor report (minor seam)

**What.** The reference app's `replan-loop` release guard hardcodes `main`. The generic loop
must gate on the *workspace's* trunk — and this very repo's trunk is `master`.

**Why it resisted.** `dos doctor --json` reports paths/lanes/stamp, but **not a
`trunk` field** — the default branch is a git fact, not a `dos.toml` policy axis,
so it isn't in the config-derived report.

**Disposition.** `dos-replan-loop` resolves the trunk **from git** generically
(`origin/HEAD` → current branch), never a literal — handled and tested for both
`master` and `main`. The named (low-priority) future seam: surface the resolved
trunk in `dos doctor --json` so the skill reads one report instead of shelling
`git symbolic-ref`. Small; deferred until a second consumer wants it.

## F6 — no generic verb writes a decision row (`dos decisions` is read-only)

**What.** `dos-replan` Step 5 surfaces the 0-2 items the operator must decide. The
natural home is the kernel's operator-decision queue (`dos decisions`) — but that
verb only **lists/drills-in**. There is no generic `dos` verb to *append* a
decision-needed row.

**Why it resisted.** The queue's write path (`home.append_decision`) is currently
reached only by `dos arbitrate --force`'s override-capture — an internal, attributed
write, not a general "raise a decision" surface. Adding a `dos decisions add`/`raise`
verb is a real kernel decision (what shape does an operator-raised row carry? how is
it resolved?) beyond SKP's scope.

**Disposition.** `dos-replan` is **honest about it**: it READs the queue (to avoid
duplicating a pending row) and surfaces the 0-2 items in its operator summary;
*emitting* a new decision row is named as a **host/driver capability** (an open
seam), not implied to be a `dos decisions` write. The named future seam: a generic
`dos decisions add` verb over `home.append_decision`. Until then the surface is the
summary, and the write stays host-side.

## F5 — the grep-clean litmus vs. teaching prose (method note, resolved)

**What.** The Phase-2 litmus is a literal grep: a shipped generic skill must
contain none of `{docs/_plans, output/next-up, apply, tailor, discovery,
docs/dispatch:}`. But a skill naturally wants to *say* "names no `docs/_plans`"
or "scoped OUT the apply-postmortem stream" — quoting the forbidden tokens to
teach the reader to avoid them.

**Why it resisted.** A dumb `grep` can't tell "this is the operative literal" from
"this is the don't-do-this example." And `apply` is a common English verb
("apply Step 2", "apply a ranking"), so a whole-word ban collides with prose.

**Disposition.** **Resolved in favor of the dumb grep.** The shipped skills were
reworded to never type the forbidden tokens at all (the strongest form of the
litmus: a naive `grep docs/_plans src/dos/skills/` returns nothing). Lesson
recorded: the generic-skill litmus is *full token absence*, so phrase hazards
descriptively ("a host's pending-decisions file", "the postmortem evidence
stream"), never by quoting the host literal. The tests pin this per skill.

---

# Foreign-repo adoption gaps (F7–F10)

> A second genre, from the foreign-repo readiness work:
> what breaks when you point the *installed* `dos` at a **random new repo** —
> here a foreign repository, a phased-plan host whose phase ids contain spaces
> (`hybrid-cache-type Phase 4`) and whose plan docs use prose status. F1–F6
> were "can a reference-app skill be made generic"; F7–F10 are "can a stranger's repo be
> verified at all." The first one a new adopter hits is the silent `via none`.

## F7 — the batch grep protocol truncates any multi-word phase (BUG, blocker)

**What.** `verify`'s git-log rung shells out to `python -m dos.phase_shipped
--batch`, one `<series> <phase> [<doc>]` line per pair on stdin, parsed
`line.split(None, 2)`. A phase containing a space is mis-split:
`"hybrid-cache-type Phase 4"` → series=`hybrid-cache-type`, phase=`Phase`,
doc=`4`. The child greps the wrong token (`Phase`, hitting `Phase 5`) and emits
a row keyed `("…","Phase")`; the parent looks up `("…","Phase 4")` → no match →
**`source="none"` for a phase that shipped.** The benchmark's dominant grammar
is `<slug> Phase <N>:`, so nearly every phase trips it.

**Why it resisted / why the green suite missed it.** `test_verify_no_plan.py`
only queries single-token phases (`"2"`, `"PH1"`, `"RS1"`). No test passes a
phase with a space, so the truncation is invisible. The rung itself is correct —
called directly with `cwd=repo` it returns `{shipped: True, via: direct}`; the
defect is purely in the oracle↔rung wire protocol.

**Disposition.** ✅ **FIXED 2026-06-01 (kernel-internal, no seam change).** The
batch protocol is now **tab-delimited** (`series \t phase [\t doc]`):
`oracle.default_grep_fallback_batch` tab-joins the fields and
`phase_shipped._parse_batch_line` splits on the tab, falling back to the legacy
whitespace split for manual CLI use. A multi-word phase (`Phase 4`) AND a
multi-word series (`blktrace auto-install`) survive the round-trip. Pinned by
`test_parse_batch_line_tab_preserves_spaces` / `_whitespace_legacy` (unit) +
`test_cli_verify_multiword_phase_out_of_the_box` (end-to-end through the real
subprocess).

## F8 — `doctor --check` gives a false "all clear" on a mismatched stamp (BUG)

**What.** The `--check` rail (`stamp.convention_coverage_finding`) should warn
"your `[stamp]` matches none of this repo's ship-shaped commits." Against the
benchmark it stays silent (exit 0) while concrete `verify` fails for every
phase. Cause: the rail uses the loose *heuristic* `recognizes_direct_ship`,
which matches 125/150 recent subjects — but matches the *wrong* ones (the
release anchor `v25.4: …` glues into a "ship-shaped" hit). One loose match →
`finding=None` → the operator's safety net is asleep.

**Why it resisted.** The heuristic is deliberately permissive (it doesn't know
the repo's real series ids), which is right for "is this even ship-shaped?" but
wrong for "would my grammar catch a *real* ship?" — the two predicates were
conflated in the rail.

**Disposition.** ✅ **FIXED 2026-06-01 (`stamp.recognizes_direct_ship`).** The
recognizer now (a) admits **multi-word/hyphenated** series slugs + the
`Phase N`/`P N` keyword phase form, so the rail SEES a repo's dominant
`<slug> Phase <N>:` ships; (b) **requires a digit** in the phase token, so an
ordinary `chore: refactor` is not mistaken for a ship; (c) **excludes
`vX.Y[.Z]:` release-cuts**, so a version bundle is never cited as the repo's
ship. (A grouping bug — a bare top-level `|` re-associating the alternation —
was fixed in the same change.) `doctor --check` now flags a genuinely-mismatched
declared `[stamp]` (exit 1, citing a real ship) and stays clean for a correct
one. Pinned by `test_ship_shaped_detector_multiword_and_release` +
`test_coverage_finding_fires_on_multiword_mismatch`.

## F9 — the generic config defaulted to the reference app's strict stamp (the out-of-box blocker)

**What.** The no-`dos.toml` path (`default_config`) inherited
`JOB_STAMP_CONVENTION` (`subject_dirs=(docs|go|agents|job_search|scripts)`),
which requires a dir prefix. So a brand-new repo — even one committing the
*canonical* North-Star shape `AUTH2: ship token refresh` from `stamp.py`'s own
docstring — resolved `verify AUTH AUTH2` → **`NOT_SHIPPED via none`** until the
operator discovered they must declare `subject_dirs = []`. `default_config`
already carried *generic lanes* but the *reference app's stamp* — an internal inconsistency.

**Why it resisted.** The strict default keeps the reference userland app + the existing suite
byte-identical (a real constraint), and SCV made an explicit "loosen knowingly"
call. But "what keeps the first userland app unchanged" and "what a stranger's
repo needs on day one" point opposite ways, and the default chose the former
silently — so every foreign repo hit `via none` first.

**Disposition.** ✅ **FIXED 2026-06-01 (`config.default_config`), user-approved.**
`default_config` now carries `GENERIC_STAMP_CONVENTION` — the lane/path
asymmetry applied to stamp (the generic config gets the generic grammar). So a
dir-less `<slug> Phase <N>:` / `AUTH2:` ship verifies with **zero config**.
`job_config` still carries `JOB_STAMP_CONVENTION` (the reference app + its bookkeeping guards
byte-unchanged), so the strict grammar is reachable via `--job` / a declared
`[stamp]`. This reverses SCV's strict-by-default call — a deliberate decision
the user signed off on, because strict-default made foreign-repo adoption fail
silently. Generic is not a free-for-all: it keeps the universal release/snapshot
guards, and a `docs/_plans: AUTH2 …` bookkeeping commit does NOT false-ship
(verified). Pinned by the rewritten `test_stamp_convention.py` /
`test_stamp_doctor.py` (generic-by-default, strict-by-opt-in).

## F10 — plan-doc ship markers have no grammar seam (open seam)

**What.** When the grep rung misses, `verify` consults the plan doc's own ship
stamps — but expects the reference app's heading grammar (`· SHIPPED <date> <sha>`). The
benchmark plans carry a **prose status line** (`**Status:** … 1b / 1c / 2b … all
landed`). The rung reads the file and finds no marker → `via: ''`. There is **no
`dos.toml` knob** for plan-body ship grammar — `[stamp]` covers commit *subjects*
only.

**Why it resisted.** SCV lifted the *commit-subject* grammar into data
(`StampConvention`), but the plan-body marker grammar stayed hardcoded in
`phase_shipped`. A repo whose ship truth lives in its plan docs (not its
commits) has no declarative path.

**Disposition.** **Open seam — or deliberate scope-out.** Option A: a
`[stamp] plan_body = {…}` grammar (the SHIPPED-marker regex as data, mirroring
the subject grammar). Option B: accept that foreign-repo ship truth comes from
*commits only* — workable for the benchmark once F7 lands, since it *does* stamp
phases in commit subjects. Decide per-demand; commit-only is the cheaper bet.

## Summary — what's open vs. closed

| # | Friction | State |
|---|---|---|
| F1 | packet template has no kernel home | **open seam** — `[render]` packet-template table or `render_packet` protocol method |
| F2 | host evidence sources | **open seam** — evidence-source driver hook |
| F3 | heavy soft-claim leasing tier | **deliberate scope-out** — separate plan on demand |
| F4 | release-guard trunk not in doctor report | **minor open seam** — surface trunk in `doctor --json` (deferred); the skill resolves it from git, **fail-closed** when `origin/HEAD` is unset |
| F5 | grep-clean litmus vs teaching prose | **resolved** — full token absence, reworded |
| F6 | no generic verb writes a decision row | **open seam** — a `dos decisions add` over `home.append_decision`; the skill READs the queue and surfaces in its summary, write stays host-side |
| F7 | batch grep protocol truncates a multi-word phase | ✅ **FIXED** — tab-delimited oracle↔rung protocol (`_parse_batch_line`); spaced phase + series round-trip; pinned end-to-end |
| F8 | `doctor --check` false "all clear" on stamp mismatch | ✅ **FIXED** — recognizer sees multi-word ships, requires a digit, excludes `vX.Y.Z:` release-cuts; `--check` now flags real mismatches |
| F9 | generic config defaulted to the reference app's strict stamp | ✅ **FIXED** (user-approved) — `default_config` now carries `GENERIC_STAMP_CONVENTION`; `verify` works out of the box; `job_config` stays strict |
| F10 | plan-doc ship markers have no grammar seam | **open seam / scope-out** — `[stamp] plan_body` grammar as data, OR accept commit-only ship truth (cheaper; covers the benchmark, since F7+F9 now read its commit-subject ships) |

The genuinely-open seams (F1, F2, F4, F6, F10) are the named targets the next
iteration inherits; F3 is parked by the layer contract; F5 is a method lesson
now baked into the tests. **F7–F9 were foreign-repo adoption defects** surfaced
by the foreign-repo readiness work and **fixed
2026-06-01** — `dos verify` now resolves a stranger's repo's `<slug> Phase <N>:`
ships with zero config (kernel suite 332 passed, was 311). F10 is the lone
remaining item and is non-blocking (the benchmark stamps phases in commit
subjects, which the commit path covers). Note `dos doctor --json` now also emits
`paths.runs` (the run dir a dispatch archives under), closing the "skill reads a
run path the verb doesn't expose" gap the final review surfaced.

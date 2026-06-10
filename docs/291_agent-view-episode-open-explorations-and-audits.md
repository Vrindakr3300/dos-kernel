# 291 — After the agent-view episode: the open explorations and audits

> **Status:** exploration agenda (no phase shipped). The residue of the
> 2026-06-10 agent-view A/B that `docs/290` (the durable harness plan) does
> *not* carry. Record: `docs/reports/2026-06-10_agent-view-ab.md`. The
> positioning telling of the same episode is `dos-private/291_*` — this doc is
> the engineering side: each item names why it matters, the first cheap step,
> and what "done" looks like.

Scope: `docs/290` owns making the *instrument* durable (litmus tests, the
grader as code, the replayable skill). This doc owns what the *episode itself*
exposed about the kernel's adoption seams and its own witnesses. Five threads.

## E1 — The unleased-session gap (the near-miss is the spec)

**What happened.** Two interactive sessions worked the identical goal. Neither
took a lease, so the WAL was empty and `dos arbitrate` had nothing to refuse
anyone with; the duplicate four-agent fleet was avoided by one session reading
clone mtimes and the process list *after* the other's clones happened to exist.
Probe five minutes earlier → both fleets launch. Check-then-use, by hand.

**Why it's a kernel-adoption seam, not a one-off.** The arbiter's region
algebra would have covered this case completely — the contested surface (the
report under `docs/`, the `.dosview` artifacts' fill) sits inside lane regions,
and a lane lease covers untracked paths too (the region is a glob over paths,
not over the index). The gap is purely that *interactive sessions and
experiment launchers don't ask*. The kernel is a PDP with a voluntary protocol;
this episode is the cleanest measurement yet of what "voluntary" costs.

**First cheap steps.**
- The `docs/290` Phase-3 skill's preflight takes a lane lease (`dos arbitrate`)
  before cloning anything, and releases on report-commit. An experiment IS a
  dispatch; treat it like one.
- A session-start convention for goal-working sessions (the `/goal` +
  `dos-goal-gate` family): arbitrate the lane the goal names, surface the
  refuse/redirect to the operator instead of silently proceeding.

**The audit.** Measure the base rate: join the lane journal (who held what,
when) against the trajectory archive (`scripts/trajectory_audit.py` already
parses the sessions) and count windows where ≥2 sessions edited one lane's
region with zero live lease. The episode says the rate is non-zero; the audit
says whether it's chronic. Done = a dated report with the unleased-concurrency
rate and the top colliding lanes.

## E2 — The narration gap Δ as a first-class metric

**What happened.** Graded on artifacts, the baseline arm scored 2/4; graded on
the agents' confident final messages it would have scored 4/4. The experiment's
entire signal lived in that gap — narration-graded, the A/B measures zero and
the defects are invisible.

**The proposal.** Define Δ = (narration-graded score) − (artifact-graded
score) per task and report it alongside every arm. Δ is the locally-measured
form of the over-claim rate the witness program keeps finding (docs/179's
rate-vs-payoff split; docs/228's over-claim slice; the RAG 98%-claimed /
6%-verified ladder in the strategy corpus). A surface improvement should move
the artifact score; **only an honesty improvement moves Δ** — the two axes
separate, which is exactly what a hand-wave "the agents did better" can't do.

**First cheap step.** The saved harness JSONs (`a1–a4`, `b1–b4` result fields)
permit a retroactive narration-only grade today, at zero spend. Record both
arms' Δ in an addendum. Then: the `docs/290` grader emits both scores per
journey so every future arm gets Δ for free.

**Done looks like.** Every agent-view report carries three numbers per arm:
artifact score, narration score, Δ — and a regression in Δ (agents over-claiming
more) is visible even when the artifact score holds.

## E3 — The commit-audit over-fire taxonomy (config-effect claims)

**What happened.** `dos commit-audit ca931a5` flagged CLAIM_UNWITNESSED: a
`fix(…)` subject whose diff touches no source file — only `.claude/settings.json`,
`.gitignore`, AGENTS.md, CLAUDE.md, README.md. The flag was useful (it forced a
real check) but wrong as a verdict: the commit *did* fix behavior — through
config. A machine without hooks behaves differently; that is an effect, and the
witnessing bytes are the config diff itself. The sibling over-fire (a ci-scoped
claim witnessed by its CI config) was fixed the same day in `be6d220` — this is
the same family, one member wider.

**The exploration.** A `config-effect` claim kind in the audit's grid: a
subject claiming a fix/behavior change is witnessed when the diff touches the
config surfaces that *carry* behavior (hook/settings files, ignore rules,
workflow YAML, `dos.toml`), graded by KIND as ever, never by correctness (the
Wall-3 line). The closed claim-kind set is data, so this is a vocabulary
extension, not a new rung.

**The audit.** `dos commit-audit --sweep` over the recent window; hand-classify
every UNWITNESSED hit into {true drift, fix-on-config over-fire, fix-on-docs
over-fire, other}. The taxonomy's relative sizes decide whether the new kind
pays for its complexity. Done = the sweep report + either the new kind shipped
with pins, or a recorded decision that the over-fire rate is too low to chase.

## E4 — Keeping the second witness honest once grading is code

**What happened.** The episode's strongest evidence was two sessions grading
the same artifacts *blind* and agreeing cell-for-cell. `docs/290` Phase 2 then
turns the grader into a script — which makes replication a deterministic re-run
of the same bytes: consistency, not grounding (the memory-store law, applied to
the grader). Determinism is good; it just stops being a *second witness*.

**The exploration.** Preserve what the blindness actually bought, on the
judges' discipline:
- The grader's read-backs are gathered **fresh per invocation** (its own clone,
  its own venv, its own suite run) — never folded from another run's cache, so
  two invocations remain two observations of the world, not one.
- Periodically seat a hand grader against the code grader on one arm (the JUDGE
  rung aimed at the instrument itself, advisory, fail-to-abstain): disagreement
  escalates to a human; agreement is recorded. The panel adjudicates the
  *grader*, which no amount of re-running the grader can do.

**Done looks like.** A short section in the 290 skill: "replication = fresh
read-backs; calibration = an occasional human seat," with the first
calibration row recorded.

## E5 — The static sweep for latent D8-class defects

**What happened.** D8 (the suite rewrites two tracked corpus files, CRLF on
Windows) was found *dynamically* — an agent ran the suite and the tree got
dirty. `docs/290` AV6 pins the invariant at runtime (the suite must add no
tracked modifications). What's missing is the **static** half: find the other
write-sites before they fire.

**The audit.** One pass over `tests/` (and `examples/` run by tests) for writes
that can land inside the tracked tree: `write_text(`/`open(..., "w")`/
`shutil.copy` whose target derives from the repo root rather than `tmp_path`,
plus any `write_text` on a tracked path missing `newline=` (the D8 shape
specifically — text-mode newline translation is invisible on POSIX, a tree-dirtier
on Windows). Grep gets the candidates; a hand pass classifies. Same move for
the metric-5 class, one level up: AV1 pins `.claude/settings.json`; the sweep
asks whether ANY committed vendor-config surface (`.claude/`, a future
`.gemini/`/`.cursor/`) executes code on a cold machine.

**Done looks like.** A dated audit note: candidates found, each either fixed
(`newline=`, `tmp_path`) or pinned as deliberate (the corpus regen is
deliberate — it is the *newline* that was the bug), plus AV-tier tests for any
new invariant the sweep justifies.

## Order and cost

E2's retro-grade and E5's grep sweep are an afternoon each, zero spend — do
them first. E3's sweep is one command plus classification. E1's audit rides
the existing trajectory tooling; its *fix* (lease-taking preflights) should
land with `docs/290` Phase 3 rather than separately. E4 is a paragraph of
discipline in the 290 skill plus one calibration row when the next arm runs.
None of these touch `src/dos/` except a possible E3 vocabulary extension —
this is tooling-and-audit work that operates ON the package, per the layering
contract.

# The cold-clone agent view, A/B-measured — 2026-06-10

**Question.** A stranger clones this repo and asks their AI agent the four things
people actually ask: *what is this? install it. wire it into my Claude Code. run
the tests.* How well does the repo's agent-facing surface serve that agent — and
do targeted fixes measurably improve it?

**Method (DOS style — verdicts from artifacts, never the agent's narration).**

- Each task ran as a **real cold headless agent**: `claude -p "<task>" --model
  claude-opus-4-8 --output-format json --dangerously-skip-permissions
  --max-turns 60`, cwd = its own fresh `git clone` of this repo. One clone per
  task, byte-identical prompts in both arms (kept in local `.dosview` run logs).
- **Arm A** = HEAD `f0cfc91` (before the fixes). **Arm B** = HEAD after the fixes.
- Grading is from **artifacts and independent read-backs**: the graded install is
  the one *my* re-run of `<their venv>\Scripts\dos doctor` answers; the suite
  verdict is *my own* pytest run on the same commit; a task with no artifact is a
  FAIL regardless of what the agent's final message claims.
- Known contamination, constant across both arms (so deltas survive it): this
  machine has a global editable `dos` install (a truly cold machine was simulated
  separately with a bare venv — see D1), the dos-kernel Claude plugin is installed
  user-globally, and other concurrent sessions loaded the box (wall-clock is
  therefore the weakest metric; turns and success are primary).

**Pre-registered metrics** (fixed before Arm B ran):

1. **Task success** (artifact-verified, per the rubrics below) — primary.
2. **Rubric points** per task (sub-criteria listed with each task) — primary.
3. **Cost to outcome**: `num_turns`, `total_cost_usd`, `duration_ms` from the
   harness JSON — secondary (turns > cost > seconds, in that order of trust).
4. **Cold-clone suite verdict** (my own `python -m pytest -q` from PowerShell on
   the arm's commit): red/green + failing count.
5. **Cold-machine hook noise**: does a python without `dos` installed error on the
   clone's committed hooks? (bare-venv probe of the `PostToolUse` command.)

## Arm A — baseline at `f0cfc91`

| Task | Verdict | Turns | Wall | Cost | Evidence |
|---|---|---|---|---|---|
| T1 orient ("what is this / ONE command / use on my repo") | **partial** (1/3) | 3 | 32s | $0.29 | What-is ✓. "One command" ✗ — gave `dos doctor`, never found `dos quickstart` (the purpose-built demo headlined by README *and* AGENTS.md). Own-repo path ✗ — recommended `pip install dos-kernel`, which fails today (not on PyPI; verified `pip index versions dos-kernel` → no distribution). |
| T2 install + prove | **success** (3/3) | 17 | 349s | $1.01 | PROOF.md real; my read-back of its venv's `dos doctor` answers. Note: the agent had to *self-correct the docs* — AGENTS.md/CLAUDE.md said `pip install -e .` then `pytest`, which fails cold (no pytest); it chose `.[dev]` on its own. Its self-check suite hit the then-live vendor-litmus red (D7). |
| T3 adopt into Claude Code | **success** (3/3) | 20 | 313s | $1.60 | ADOPT.md correct & verified (`dos init --hooks claude-code`, plugin, MCP handshake; PyPI trap dodged via docs/INSTALL.md). Cost is the finding: 20 turns of digging across README(691)/INSTALL/plugin docs — AGENTS.md, the agent front door, carried **zero** adoption content. |
| T4 run the test suite | **FAIL** (0/2) | 13 | 67s | $0.98 | No TESTS.md, no verdict. The agent backgrounded pytest and ended its one-shot session on a literal promise: *"Waiting for the suite to finish. The harness will re-invoke me…"* — nothing re-invokes a `-p` session. 67s wall vs the suite's real ~3.5 min proves the suite never finished under it. |

**Arm A totals: 2/4 success, 7/11 rubric points; mean 13.25 turns, $0.97/task.**

**Metric 4 (suite, my run, PowerShell):** RED — `2 failed, 3916 passed, 16 skipped (3:34)`.
**Metric 5 (cold-machine hooks):** FAIL — bare venv running the committed
`PostToolUse` command → `ModuleNotFoundError: No module named 'dos'`, exit 1, i.e.
a visible hook error on **every** Read/Bash/Grep/Glob of a cold user's session.

## The defects the baseline exposed (and the fix each got)

| # | Defect (evidence) | Fix |
|---|---|---|
| D1 | The committed `.claude/settings.json` ships the **maintainer's personal rig**: a `PostToolUse` hook that hard-fails on any machine without `dos` importable (metric 5), plus Stop hooks running the maintainer's trajectory audit (which reads the *user's own* `~/.claude` transcripts and writes report files into their clone) and a `$HOME` cleanup script that doesn't exist off this machine. | Committed `settings.json` → permissions only. The rig moved verbatim to `.claude/settings.local.json` (machine-local, now gitignored), so the maintainer's machine behavior is unchanged. |
| D2 | AGENTS.md + CLAUDE.md both documented `pip install -e .` → `python -m pytest -q`, which **fails cold** (`-e .` is deliberately PyYAML-only; pytest lives in `[dev]`). Ground-truthed in a fresh venv: `No module named pytest`. | Both files now say `pip install -e ".[dev,mcp]"` (exactly what CI installs) and name the trap explicitly. |
| D3 | AGENTS.md documented `ruff check .` — which reports **373 errors** on a clean clone, because CI's blocking lint is `ruff check src/dos src/dos_mcp`. A cold agent following the doc concludes the tree is dirty (or "fixes" it). | AGENTS.md now gives the CI-exact command and says the wider tree is not lint-clean by design. |
| D4 | The fresh-clone suite verdict was a **PATH lottery**: on Windows with WSL enabled, `bash` resolves to `System32\bash.exe`, which cannot address the `C:/…` sentinel — the hermes safety demo's naive arm fires 0 hazards and the suite is red from PowerShell (my run) while green from a Git-bash-PATH'd shell (the T2 agent's run). Same box, opposite verdicts. | `swarm_agent.run_tool_command` now resolves a Git-style bash explicitly (off `git`'s own install dir) and prepends it to the child's PATH; a host with no usable bash **skips** the test with a reason instead of failing on `naive = 0`. Verified red→green from PowerShell on this box, real execute path (not the skip). |
| D5 | The orient agent missed `dos quickstart` and recommended the unpublished `pip install dos-kernel` (T1). Root cause: a Claude Code agent's auto-loaded context is **CLAUDE.md, which carried zero consumer content** — no quickstart, no install matrix, no adoption pointers; and README's Try-it block led with the not-yet-real PyPI command. | AGENTS.md grew a **"When the user asks you ABOUT DOS"** table (orient → quickstart; install → from-clone, dated not-on-PyPI warning, squatter warning; Claude Code wiring → `dos init --hooks` / plugin / `dos-mcp`; use-on-my-repo; run-the-tests). CLAUDE.md got a 7-line pointer block routing consumer questions there. README's Try-it now leads with the clone path and dates the PyPI note. |
| D6 | The test-suite agent backgrounded pytest and stopped on a promise (T4) — the one-shot session died before the verdict existed. | Expectation-setting in AGENTS.md/CLAUDE.md: suite size (~3,900) and runtime (~3–4 min) stated, plus an explicit "run it in the foreground; in a one-shot session do NOT background it and stop" trap note. |
| D7 | (Found, already fixed by a concurrent session) `test_vendor_agnostic_kernel` red at `f0cfc91` — `hook_binary.py` compared against a `'claude-code'` literal. | Peer commit `f701a9f` references `DEFAULT_DIALECT` instead; Arm B inherits it. Not this change's work — recorded for the suite-verdict accounting. |

## Arm B — after the fixes

Same prompts (byte-identical `t*.txt` files), same flags, same grading. Arm B
HEAD = `ca931a5` — all four clones verified at that commit before launch. Honest
accounting: the arm delta is the full `f0cfc91..ca931a5` range (21 commits) —
the five-file agent-view commit (`ca931a5`) plus concurrent-session landings the
fix table already attributes (D4 = `a0784c7`, D7 = `f701a9f`, and `dad9fa2`'s
richer quickstart). The A/B measures the repo's *surface*, not one commit.

| Task | Verdict | Turns | Wall | Cost | Evidence |
|---|---|---|---|---|---|
| T1 orient | **success** (3/3) | 1 | 10s | $0.18 | All three rubric points from the auto-loaded context alone — zero digging. "One command" ✓ `dos quickstart` (the D5 pointer found). Own-repo path ✓ from-clone install with the not-on-PyPI date + squatter warning, then `dos doctor`/`dos verify`/`dos init --hooks claude-code`. Arm A's miss (recommending the unpublished `pip install dos-kernel`) is gone. |
| T2 install + prove | **success** (3/3) | 25 | 471s | $1.46 | PROOF.md real; my read-backs of *its* venv confirm: `dos doctor` exit 0, `dos verify` → `SHIPPED … (via grep-subject)`, `import dos` resolves into the clone, tracked tree clean. No doc self-correction needed this time — it followed the fixed `.[dev,mcp]` line verbatim and its in-venv suite ran GREEN (3968/12 sk). Bonus: it root-caused the corpus CRLF smudge (D8 below) to `test_go_hook_parity.py:112` and restored exact bytes unprompted. |
| T3 adopt into Claude Code | **success** (3/3) | 21 | 224s | $1.48 | ADOPT.md correct and *deeper* than Arm A's: dry-run-first wiring (`dos init --hooks claude-code --dry-run`), a merge-never-clobber proof, the native `dos-hook` binary probed, live MCP `dos_doctor`/`dos_arbitrate` verdicts captured. My re-runs of its evidence (hook verb, native exe, truth syscall) all reproduce. It cites the AGENTS.md consumer table as its source — the surface Arm A found empty. |
| T4 run the test suite | **success** (2/2) | 14 | 340s | $0.72 | The decisive flip. TESTS.md with the exact commands + last 30 lines of real output; suite run **in the foreground to completion** (5.7 min wall — long enough to be real; Arm A bailed at 67s on a promise). Verdict `3968 passed, 12 skipped` byte-matches my own independent run on the same commit. |

**Arm B totals: 4/4 success, 11/11 rubric points; mean 15.25 turns, $0.96/task
($3.84 total vs Arm A's $3.88).**

**Metric 4 (suite, my run):** GREEN — `3968 passed, 12 skipped (3:36)` on a fresh
clone of `ca931a5`. The two families red/lottery-prone in Arm A re-run from
**PowerShell** specifically: `test_vendor_agnostic_kernel.py` 8 passed,
hermes/safety/swarm family 15 passed — the verdict is shell-independent now (D4).
**Metric 5 (cold-machine hooks):** PASS — the committed `.claude/settings.json`
carries **no hooks key at all** (permissions only); there is nothing for a
`dos`-less machine to error on. Arm A erred on every Read/Bash/Grep/Glob.

## D8 — the defect Arm B itself surfaced (found, fixed, witnessed)

Running the suite on Windows **dirtied the cold clone's tracked tree**: `M
go/internal/hook/parity/corpus.jsonl` + `corpus_posttool.jsonl` after every
full-suite run (the T2 agent hit it; my metric-4 control clone reproduced it
identically, which is what attributes it to the suite, not the agent).
`test_go_decider_byte_parity` regenerates both corpora via `write_text(…,
encoding="utf-8")`, and Windows text-mode translation rewrites the committed LF
blobs as CRLF. Fix: `newline="\n"` on both writes (`05dc738`). Witness: corpora
restored, parity tests re-run from PowerShell (4 passed), worktree blob hash ==
index blob hash, zero CRLF bytes, `git status` clean.

## Verdict

Every pre-registered metric moved in the right direction; the two broken
journeys are gone:

| Metric | Arm A | Arm B |
|---|---|---|
| Task success (primary) | 2/4 | **4/4** |
| Rubric points (primary) | 7/11 | **11/11** |
| Cost for the 4 journeys | $3.88 | $3.84 |
| Cold-clone suite (my run) | RED (2 failed) + shell lottery | **GREEN, both shells** |
| Cold-machine hook noise | error on every tool call | **zero hook surface** |

Read by journey: the *most common* one (T1 orient — every "what did I just
clone?" question) went from a wrong answer that would strand a user on a
nonexistent PyPI package to a correct one, at 3× fewer turns (3→1), 3× faster
(32s→10s), and 0.6× the cost — the auto-loaded context now answers it outright.
The *most damaging* one (T4 — a user asking for a suite verdict and receiving a
dead promise) went 0/2 → 2/2. T2/T3 turns did **not** drop (17→25, 21→21): both
agents spent the constant budget on *more verification depth* (a green in-venv
suite run + the D8 diagnosis in T2; live MCP/native-binary probes in T3), which
is the direction the substrate wants — the waste eliminated was failed and
misleading work, not effort.

Method note, DOS-style: no cell above comes from an agent's narration. Success
is artifact-graded (PROOF/ADOPT/TESTS.md + my own re-runs of their venvs'
`dos doctor`/`dos verify`/hook verbs), the suite verdict is my independent run
on the same commit, and the one tie (T4's counts) was settled by byte-matching
two independently produced outputs. The A/B also paid for itself in the DOS
sense: the instrument *found a new defect* (D8) on the improved arm, and the fix
shipped with its own witness.

**Residuals.** (1) `dos doctor`'s `verifiability: none of your last 50 commits
name a unit of work` line on a fresh clone is accurate but reads as a scold —
the stamp-trailer work (docs/287) is the open fix. (2) The T2/T3 agents leaned
on this machine's global editable install for early probes (contamination noted
in Method; constant across arms). (3) Wall-clock remains the weakest metric on a
loaded box — turns and artifact success carried the verdict.

## Addendum — the same artifacts, graded twice (independent replication)

A second session, working the same goal concurrently and **blind to the fill
above** (it derived its grades from the `b1–b4` artifacts before `86654dc`
existed), reached the identical verdict on every cell it graded: T1 3/3 ·
T2 3/3 · T3 3/3 · T4 2/2 → 4/4 success, 11/11 rubric points; the same D8
root-cause (`test_go_hook_parity.py` corpus rewrite, CRLF over LF); the same
read-back results from the agents' venvs (`dos doctor` answers, tracked trees
clean modulo D8). Its own metric-4 control — a separate fresh clone of
`ca931a5`, separate venv, `python -m pytest -q` from PowerShell — returned
`3968 passed, 12 skipped in 204.33s (0:03:24)`, exit 0, matching the counts
above byte-for-byte. Two graders, two control clones, zero shared narration,
one verdict — the report's conclusion does not rest on any single session's
say-so. (The second session also confirms the coordination claim incidentally:
it found Arm B already in flight, declined to double-spend the four paid runs,
and took the verifier seat — the disjoint-role discipline this kernel exists
to referee, performed by hand.)

*Follow-ups:* the durable-harness successor (litmus tier + grader-as-code +
replayable skill) is `docs/290`; the open explorations and audits the episode
itself opened (the unleased-session gap, the narration-gap Δ metric, the
commit-audit over-fire taxonomy, grader calibration, the static D8-class sweep)
are `docs/291`; the positioning telling is `dos-strategy/291_*`.

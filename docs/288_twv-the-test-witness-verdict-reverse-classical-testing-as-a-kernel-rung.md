# 288 — TWV: the test-witness verdict (reverse-classical testing as a kernel rung)

> **Status:** P1 shipped (2026-06-10, `c966591` — module + verb + 18-test pin in
> one commit; this stamp commit makes the phase legible to the start-anchored
> grep rung, which cannot see a `feat(…):`-prefixed subject — the docs/287
> trailer-form lift, in flight on this tree, is the durable fix for that).
> The forcing prompt (operator `/goal`): *apply
> concepts from Cognition's FrontierCode post
> (<https://cognition.ai/blog/frontier-code>) to move DOS forward.* This doc records
> the concept-by-concept mapping (most of the post's QC machinery turns out to be
> something DOS already ships or already forbids itself), the ONE kernel-shaped gap
> the mapping exposed — nothing in the kernel adjudicates *"my new test actually
> witnesses my change"* — and the primitive built to fill it: `dos.testwitness`
> (module), `dos test-witness` (verb), `DISCRIMINATES 0 / VACUOUS 3 / UNSATISFIED 4
> / REGRESSIVE 5 / ABSTAIN 6` in the exit-code contract,
> `tests/test_testwitness.py` the pin.

---

## 1. Provenance — what FrontierCode is, in one paragraph

Cognition's FrontierCode is a coding benchmark that moves the bar from
*correctness* to **mergeability**: would a maintainer actually accept this PR?
It grades six dimensions (correctness, regression safety, mechanical
cleanliness, **test correctness**, **scope discipline**, code quality), and its
headline QC claim is a false-positive rate 81% under SWE-Bench Pro's. Three of
its named techniques matter here: **reverse-classical testing** (an
agent-written test must FAIL when run against the original, broken codebase —
"an automated, deterministic check that the agent understood the problem"),
**code scope evaluation** (a quality PR exhibits restraint: file allowlists,
line/file-count limits, locality), and a **blocker / non-blocker rubric**
(hard mergeability stops vs. advisory quality grades). The rest of its pipeline
— "mutagent" LLM-patched test environments, maintainer rubrics, adversarial
hack-reports — is evaluation operations, not mechanism.

## 2. The mapping — what DOS already has, claim by claim

The exercise that makes this doc worth writing: most of FrontierCode's QC
philosophy is the docs/138 invariant (*the byte-author of the evidence is never
the judged agent*) arriving at the same place from the benchmark side. Mapped
honestly:

| FrontierCode concept | DOS status | Where |
|---|---|---|
| Scope discipline (file containment, restraint) | **already shipped** — the footprint verdict + the binding pre-effect gate | `dos.scope.classify` (IN_SCOPE / SCOPE_CREEP / WRONG_TARGET), `dos.scope.gate` (docs/85 §4, docs/102 §5) |
| Blocker vs non-blocker rubric | **already law** — the conjunctive floor is non-negotiable, everything else is advisory | `improve()`'s suite-green ∧ truth-clean floor (docs/280); the OBSERVE‹WARN‹BLOCK ladder (docs/144) |
| False positives as the headline defect | **the founding thesis** — a self-judged accept is the FP machine | docs/138; `g3_forgeability` (floor FP 0.000 vs narration-judge 0.352) |
| Adversarial hack-report stage | **working ritual** — refute your own claims before believing them | the Phase-A self-refutation (6/7 of DOS's own claims killed); property-based pins (docs/273) |
| "Grades like a tech lead, not like CI" (LLM rubric, mutagent) | **placed, deliberately outside** — non-deterministic adjudication is the JUDGE rung, a driver, advisory, fail-to-abstain | `dos.judges` seam + `drivers/llm_judge` (docs/86) |
| Reverse-classical testing | **the gap** — nothing adjudicates the test-as-witness claim | → this plan |
| Numeric scope knobs (changed-line / net-growth / file-count caps) | **the second, smaller gap** — `ScopePolicy` is file-set-only today | noted §7, not built here |

The first five rows are the satisfying part: an eval shop optimizing for "would
a maintainer merge it" independently re-derived deterministic-first,
floor-then-advisory, adversarial-self-refutation — the architecture this repo
already enforces with tests. The two gaps are the actionable part, and the
first is kernel-shaped.

## 3. The gap — the vacuous test is an over-claim no existing verdict catches

"I added a test for this" is one of the highest-frequency work claims an agent
makes, and today every kernel consumer takes it at face value the moment the
suite is green:

- `verify()` witnesses that a *phase shipped* (git ancestry) — it never looks
  inside a test.
- `improve()` (docs/280) requires *suite green on the candidate tree* — a new
  test that **passes on both trees** keeps the suite green by construction. The
  keep-gate cannot distinguish a witnessing test from a decorative one.
- `reward()` (docs/230/234) admits a trajectory on a non-forgeable effect
  witness — but "the diff contains a test file" is presence, not discrimination
  (the Wall-3 shape, docs/204: the file-path rung witnesses W2 presence, never
  W3 goal).
- `commit-audit` checks a commit *subject* against its *diff* — "add test for
  X" with a test file in the diff is witnessed, even if that test would have
  passed before the fix existed.

So the canonical inflation: an agent fixes (or half-fixes, or doesn't fix) a
bug, writes a test that asserts something *already true on the baseline*, and
every downstream consumer — the keep-gate, the reward set, the reviewer reading
"tests added ✓" — banks a unit of assurance that does not exist. FrontierCode's
reverse-classical check is the deterministic kill for exactly this: **run the
new test against the tree WITHOUT the change; it must fail.** A test that
passes on both trees witnesses nothing.

That check is two env-authored bits joined — which is to say, it is a DOS
verdict that hadn't been written down yet.

## 4. The primitive — `testwitness.classify(TestRunEvidence) -> TestWitnessVerdict`

PURE, no I/O, no clock, no policy object (the rule is structural — there is no
threshold a host could legitimately tune). The evidence is the two runner
outcomes the caller gathered at the boundary:

```
TestRunEvidence(
    baseline  = the runner's outcome for THE TEST on the tree WITHOUT the change,
    candidate = the runner's outcome for THE TEST on the tree WITH the change,
    rung      = who authored those two outcome bits (Accountability;
                OS_RECORDED by default, AGENT_AUTHORED = narrated = forgeable),
)
```

Outcomes are a closed enum: `PASSED / FAILED / ERRORED / NOT_RUN` — `FAILED` is
an assert-level failure (the test ran and its assertion was false), `ERRORED`
is structural (the test could not run at all: a collection/import error). The
ladder, top to bottom:

1. **ABSTAIN** — the rung is forgeable (`AGENT_AUTHORED`: the agent *narrated*
   "it failed before and passes now"), or either run is `NOT_RUN`. Half a join
   is not a join; a narration is not a run. Never mint a witness off either.
2. **REGRESSIVE** — baseline `PASSED`, candidate not: the change *breaks* the
   test. For a pre-existing test this is a regression; for a test the change
   itself ships, an incoherent claim. (FrontierCode's "regression safety"
   dimension, reduced to its deterministic core.)
3. **UNSATISFIED** — candidate not `PASSED` (and baseline didn't pass either):
   the change does not satisfy its own test. Nothing is witnessed, and the fix
   claim itself is now in doubt — the red half of red→green without the green.
4. **VACUOUS** — `PASSED` on both trees. The test would have passed without the
   change; it witnesses nothing. **The FrontierCode false-positive shape, and
   the load-bearing verdict of this module** — the one a naive "tests added ✓"
   reviewer banks as assurance.
5. **DISCRIMINATES** — baseline `FAILED`/`ERRORED`, candidate `PASSED`:
   red→green across the change. The only verdict that licenses "this test
   witnesses this change," and the only one whose `witnesses` projection bit is
   True (the bit a keep-gate ANDs in).

The verdict carries one more typed bit, `assert_level`: True when the baseline
failure was assert-level (`FAILED`), False when it was structural (`ERRORED` —
e.g. the test imports a module the change introduces, so on the baseline it
cannot even load). Both are honestly DISCRIMINATES — the test provably cannot
pass without the change — but the assert-level form is the stronger witness
(the test *ran* against the old behavior and rejected it), and a consumer that
wants only the strong form filters on the bit rather than re-parsing prose.

Exit codes (the verdict-IS-the-exit-code idiom): `DISCRIMINATES 0 / VACUOUS 3 /
UNSATISFIED 4 / REGRESSIVE 5 / ABSTAIN 6`, contract error 2, unknown floor 7 —
published through `dos exit-codes` and `dos doctor --json` like every other
verdict verb.

## 5. Why it is byte-clean (docs/138), and the fold-mints-data check (docs/179)

The test's *content* is agent-authored — maximally forgeable; the kernel never
reads it. What the verdict joins is two bits the agent authors zero bytes of:
the runner's exit on the baseline tree and the runner's exit on the candidate
tree. Two independently-authored facts (two different trees, one
env-controlled runner), joined into a label neither fact carries alone — the
docs/179 fold-mints-data rule, satisfied the same way `liveness` joins
git-delta to journal-delta. An agent cannot write its way from VACUOUS to
DISCRIMINATES: the only path is a test that actually fails on the tree it
didn't get to touch. And the rung field makes the floor structural rather than
procedural: outcomes that exist only as the agent's own narration arrive on
`AGENT_AUTHORED` and the verdict ABSTAINS — `--witness confirm --forgeable`
cannot ACCEPT in `reward`, and `--baseline fail --candidate pass --forgeable`
cannot DISCRIMINATE here. Same floor, same shape, same $0 demo.

## 6. The honest residue — what DISCRIMINATES does NOT prove

Stated before anyone oversells it (the docs/204 discipline):

- **Tree-discrimination ≠ behavior-assertion.** An adversarial test can
  discriminate trivially — `assert os.path.exists("the_new_file.py")` is
  red→green across any change that adds a file. DISCRIMINATES is sound against
  the *lazy* inflation (the vacuous test, the overwhelmingly common case) and
  against pass/pass forgery; it is not sound against an adversarial test
  author. "Does this test assert the intended *behavior*?" is semantic — that
  residue goes UP the ladder to the JUDGE rung (`dos.judges`, advisory,
  fail-to-abstain), exactly where FrontierCode puts its own LLM rubric. The
  `assert_level` bit narrows the residue (structural discrimination is flagged
  typed, not buried in prose) but does not close it.
- **One test, one change — not a suite verdict.** TWV adjudicates a (test,
  change) pair. "The suite is green" stays `improve()`'s floor; TWV is the
  *per-new-test* rung a keep-gate may additionally AND in.
- **The gather is the caller's.** Running the same test on two trees (a
  worktree checkout without the candidate diff, then with it) is I/O — it lives
  at the boundary (a CI step, the `dos-self-improve` engine's worktree flow, a
  host driver), never inside `classify`. The kernel adjudicates outcomes; it
  does not run pytest. P1 ships the verdict + verb; a convenience gatherer is
  P2, below.

## 7. What was deliberately NOT built

- **The two-tree gather driver (P2, open).** A `drivers/`-side convenience that
  checks out `HEAD`/merge-base into a temp worktree, runs one named test on
  both trees, and feeds `classify` — the `dos-self-improve` engine already has
  the worktree mechanics this would reuse. Until then the CLI takes the two
  outcomes as flags, which is exactly how `reward` takes its witness.
- **Numeric scope knobs (the second §2 gap, open).** FrontierCode also caps
  changed lines / net growth / file count; `ScopePolicy` today is
  file-set-only (`allow_shared_infra`, `creep_tolerance`). Adding
  `max_files` / `max_net_lines` knobs would be a small, pure extension of
  `scope.classify` — left out of P1 because it is a different module and a
  different claim ("restraint", not "witnesses").
- **Anything resembling the rubric pipeline.** Calibration solutions, pod
  review, hack-reports are eval-ops. The repo's analogues (property pins,
  self-refutation audits) already exist as practice, not kernel surface.

## 8. Composition — who consumes the bit

- `improve()` (docs/280): a host policy may AND `witnesses` into the keep
  floor for any candidate that *claims* test coverage — "KEEP iff suite green
  AND truth clean AND metric gain **AND the claimed new test discriminates**."
  Kept out of `CandidateEvidence` for now (primitives-not-features, docs/79);
  the AND happens in the host's engine, not the kernel's dataclass.
- `reward()` (docs/230/234): a trajectory whose claim is "added a failing-test
  + fix" admits on DISCRIMINATES as the witness kind — the reward-set analogue
  of reverse-classical, purging the vacuous-test positive the same way the
  DB-hash witness purges the over-claimed write.
- `dos-witness-claim` (the SKP routing skill): "I added a test" is now a
  checkable effect claim with a named witness rung instead of a fold-through.

## 9. Phases

| Phase | What | Status |
|---|---|---|
| **P1** | `dos.testwitness` module (pure classify, closed vocab, rung floor) + `dos test-witness` verb + exit contract + `tests/test_testwitness.py` pin + this doc | **shipped** (this commit) |
| P2 | the two-tree gather driver (worktree checkout × one test × two runs → evidence), reusing the `self_improve` engine's isolation mechanics | open |
| P3 | numeric scope knobs on `ScopePolicy` (`max_files`, `max_net_lines`) — the other §2 gap | open |

*(Module file is `testwitness.py`, no underscore — a kernel leaf must never
match pytest's `test_*.py` discovery pattern.)*

# 226 — The hook-exit classifier: a shell script's exit code as a verdict

> **Status:** ✅ **Shipped** (2026-06-07). `src/dos/hook_exit.py` (the pure
> classifier), `dos hook-exit` (the CLI verb), `tests/test_hook_exit.py` (20 tests),
> the `dos doctor --json` exit-contract row. This is the build of idea **C3** from
> the Claude Code source audit (docs/189). It is the fourth concept generalized this
> session, after `productivity` (H1, docs/218), `breaker` (H2/H3, docs/223), and
> `exec_capability` (B1, docs/224).

## What this is, in one sentence

Take a plain shell script's exit code and map it onto the DOS intervention
vocabulary — so a script too simple to emit JSON still rides the intervention
ladder.

## The gap it closes

DOS has rich hook adapters — `pretool_sensor` and `posttool_sensor` read Claude
Code's JSON hook dialect, run kernel verdicts, and emit the exact CC envelope. But
that is the *sophisticated* integration: it assumes a hook that speaks structured
JSON. The vast majority of real hooks are not that. They are shell scripts — a
linter, a policy probe, a smoke test — and a shell script signals its result the
only way a plain process can: an **exit code**.

Claude Code already gives that exit code a meaning (`src/utils/hooks.ts`): a command
hook's `exit 0` is success (proceed), `exit 2` is a *blocking error* (stop the
action), and any other non-zero is a non-blocking error (a warning that still
proceeds). This is not a CC invention — it is the universal Unix hook convention
that `git` hooks and `pre-commit` and countless CI gates already use. It is the
zero-ceremony contract every shell author already knows.

DOS had no bridge from that convention to its own intervention vocabulary
(`intervention.Intervention`: OBSERVE‹WARN‹BLOCK‹DEFER). So the cheapest possible
integration — "I just have a script that exits 2, make that a DOS block" — was not
expressible. This module is that bridge.

## Why it belongs in the kernel — the mechanism/policy split

This is the smallest, purest example yet of the `malloc` property the user's framing
names. The mechanism is one line of intent: *look up the exit code in a map.* The
policy — *which code means which verb* — is data, defaulted to CC's convention
(`0 → pass`, `2 → BLOCK`, any-other-non-zero → WARN) and declarable per-workspace in
`dos.toml [hook_exit]`.

The classifier **never knows what the script did** — only the integer it returned. A
host that wants `exit 3 = DEFER`, or `exit 0 = OBSERVE` (record even on success),
changes one line of data; the kernel's lookup never changes. The script's entire
domain — what it checked, why it failed — is pushed out. That is exactly the
property that lets a small thing be a universal cog: it is the `malloc` of shell-hook
integration.

## Why a script's exit code is sound evidence

The exit code is authored by the *script process*, not by the judged agent — it is a
third party's verdict on the agent's action. That is the actor-witness split
(docs/117): the byte-author (the script) is not the judged party (the agent). So
`classify_exit` reads an agent-external signal, the same discipline `liveness`
(reads git), `exec_capability` (reads the command shape), and `tool_stream` (reads
env-authored result digests) all follow. The script is a **deterministic JUDGE** on
the trust ladder (ORACLE → JUDGE → HUMAN); this module routes its terse verdict —
one integer — into the kernel's richer vocabulary.

## The verdict and the fail-safe default

`classify_exit(code, policy) -> ExitVerdict` reads top to bottom:

1. **PASS** — `code == pass_code` (default 0): the script approved. Proceed, no
   intervention (`intervention=None`). This is distinct from OBSERVE: OBSERVE
   *records* a verdict and still dispatches; PASS records nothing — there is simply
   nothing to actuate.
2. **MAPPED** — the code is an explicit `mapping` entry: the declared verb (default
   `2 → BLOCK`, CC's blocking-error code).
3. **FALLBACK** — any other non-zero code: `fallback` (default WARN).

That fallback is the load-bearing safety decision, and it is the docs/143 lesson
encoded as a default. An *unanticipated* non-zero code — a script that failed in a
way the host did not foresee — degrades to **WARN**: it informs, it does not block.
Never a silent pass (which would hide a real failure), never a spurious BLOCK (which
is the expensive −9 pp disruption mistake). A wrong WARN is cheap; a wrong BLOCK is
not. So the default leans toward surfacing without disrupting.

## How it composes with the shipped infrastructure

The verdict carries an `intervention.Intervention` — the *same* type
`enforce.run_handler` already consumes. So the full pipeline for a plain shell hook
is:

```
script exits N  →  hook_exit.classify_exit(N)  →  Intervention  →  enforce.run_handler  →  EffectProposal
```

No JSON anywhere. A host captures `$?`, calls the classifier, and feeds the result
into the same enforcement seam `pretool_sensor` uses. The intervention ladder, the
enforcement handlers, the OP_ENFORCE journal record — all of it now reaches the
humblest integration: a one-line shell script.

## The CLI

The verdict IS the exit code, and here that idiom does double duty: the verb's *own*
exit code reflects the intervention rung, so a shell *wrapper* can branch without
parsing stdout:

```bash
dos hook-exit --code 2            #  BLOCK  exit 2 → BLOCK …        ; exit 3
dos hook-exit --code 0            #  PASS   exit 0 — script approved ; exit 0
dos hook-exit --code 42           #  WARN   exit 42 → WARN (fallback); exit 4
dos hook-exit --code 3 --map 3=DEFER   #  DEFER …                   ; exit 5
```

PASS 0, BLOCK 3, WARN 4, DEFER 5, OBSERVE 6, contract-error 2. So a wrapper like
`dos hook-exit --code $? || handle_intervention $?` works with no JSON parser.
No-plan rail: needs only the code — no git, no journal, no clock.

## What it makes buildable (the open right column)

Shipped as a classifier, not yet wired into a hook runner — the docs/79 restraint.
The space it opens:

1. **A `dos hook run -- <script>` wrapper.** The direct payoff: a verb that runs an
   arbitrary shell hook, captures its exit code, classifies it, and routes the
   intervention through `enforce.run_handler` — turning any script into a
   first-class DOS hook with zero code on the script's side.
2. **A `[hook_exit]` governance surface.** A fleet operator declares the org's
   exit-code convention once (e.g. "exit 3 always means DEFER across all our
   hooks"); every hook reads it.
3. **A `posttool`/`pretool` shell-hook bridge.** The existing sensors handle JSON;
   a sibling path could accept a plain script's exit code via this classifier, so a
   host mixes JSON-speaking and exit-code-only hooks freely.

## How it relates to the other audit lifts this session

This completes a small cluster around the **intervention ladder's inputs**:

- `exec_capability` (B1) is a *structural* input — it reads a proposed command's
  shape and produces a capability that a consumer can route to an intervention.
- `hook_exit` (C3) is an *external-judge* input — it reads a script's verdict (an
  exit code) and maps it directly to an intervention.

Both feed the same `intervention` → `enforce` pipeline; both are domain-free
classifiers whose policy is data. Together with `productivity` and `breaker` (the
loop-economics verdicts), they extend the kernel's vocabulary of *what can produce
an intervention* — from the kernel's own deterministic verdicts to a structural
command property to an arbitrary external script — without the kernel ever learning
a host's domain.

---

*Provenance: idea C3 from docs/189 (the Claude Code v2.1.88 source audit). Source
shape: `src/utils/hooks.ts` (the `result.code === 2` blocking-error convention).
Built 2026-06-07 as `src/dos/hook_exit.py` + `dos hook-exit` + 20 tests.*

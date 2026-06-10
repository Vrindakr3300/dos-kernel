# 224 — The exec-capability classifier: a SHAPE, not a word

> **Status:** ✅ **Shipped** (2026-06-07). `src/dos/exec_capability.py` (the pure
> classifier), `dos exec-capability` (the CLI verb), `tests/test_exec_capability.py`
> (39 tests), the `dos doctor --json` exit-contract row. This is the build of idea
> **B1** from the Claude Code source audit (docs/189).

## What this is, in one sentence

Given a command, answer "does the program it invokes grant *arbitrary* code
execution?" — by matching the invoked program's SHAPE, never a word in the command.

## The gap it closes, and where the shape comes from

The docs/189 audit found `dangerousPatterns.ts` in the Claude Code source. CC keeps
a list of program prefixes — `python`, `node`, `bash`, `ssh`, `npx`, `eval`, … —
that identify which *allow-rules* hand the model arbitrary code execution. The
insight is subtle and worth stating plainly: an allow-rule like `Bash(python:*)` is
**not** "permission to run python." It is permission to run *anything at all*,
because `python -c '<any code>'` will execute whatever you put in the string. The
interpreter is a universal escape from every narrower gate. So CC strips such rules
when it enters auto-mode — a rule that looks specific but grants everything is more
dangerous than an honest broad rule, because it hides its blast radius.

DOS had no equivalent. Its one capability-shaped guard, `self_modify`, asks a
*different* question ("does this lane's file-tree touch the kernel's own code?") over
a *different* input (a tree). There was no notion of "this command grants arbitrary
execution" — the `pretool_sensor` docstring even says so outright: *"there is no
'dangerous-exec' class."* This doc fills exactly that named gap.

## The law it applies: a capability is a SHAPE, not a word (docs/158)

The docs/158 detector-design law — born from the benchmark work — is that a sound
detector reads a **structural property**, never a keyword. A keyword detector is
forgeable (rename the thing and it slips through) and false-positive-prone (the word
appears in innocent places). The exec-capability classifier is the cleanest possible
application of that law to *command auditing*:

- It does **not** scan the command for the substring `python` or `eval`. A file
  named `python_notes.txt`, an argument `--eval-mode`, a comment mentioning bash —
  none of these are an arbitrary-exec capability, and a substring match would
  mis-fire on all of them.
- It **does** extract the *invoked program* — the first token of the command, after
  stripping a leading `env VAR=…` / `sudo` wrapper and any `VAR=value` assignments,
  reduced to its basename and lower-cased (`/usr/bin/python3` → `python3`,
  `PYTHON` → `python`) — and matches *that* against the capability set.

So `cat python_notes.txt` is **BOUNDED** (it invokes `cat`), `grep eval src/` is
**BOUNDED** (it invokes `grep`), and `python -c '...'` is **GRANTS_ARBITRARY_EXEC**
(it invokes `python`). Matching the program SHAPE, not a word in the string, is the
whole correctness story — and it is the single most-tested property in the suite,
because it is the one a naive implementation gets wrong.

The verdict has three states:

1. **GRANTS_ARBITRARY_EXEC** — the invoked program (or a capability wrapper like
   `sudo` in front of it) is in the set: an interpreter (`python`/`node`/`ruby`/…),
   a shell (`bash`/`sh`/`zsh`), a package-runner (`npx`/`npm`/`yarn`), an
   exec-builtin (`eval`/`exec`/`xargs`), or a remote/privilege wrapper
   (`ssh`/`sudo`). Each is a way to run any code.
2. **BOUNDED** — the invoked program is *not* a known arbitrary-exec entry point.
   This is **not a safety guarantee** — only "not a member of the declared set." A
   bounded command can still do damage (`rm -rf`); it just is not a *universal*
   execution escape. (The audit notes `git`/`gh`/`curl`/`kubectl` are flagged only
   in CC's ant-internal build — `git` can run hooks, `curl` can exfil — so a host
   that wants those caught adds them; they are bounded by default.)
3. **EMPTY** — no program token (a blank command). Nothing to classify.

## Why it is a classifier leaf, not an admission predicate

This was the load-bearing design call, and it follows the user's mechanism/policy
framing. B1 looks superficially like `self_modify` (both are "capability guards"),
but they belong in different layers:

- `self_modify` is an **admission predicate**: it answers "may this *lane* be
  leased?" over a file-tree, and it plugs into the arbiter's conjunction
  (`run_predicates`). It can *refuse* a lease.
- `exec_capability` answers "does this *command* grant arbitrary exec?" over a
  command string. **DOS has no permission-rule allow-list surface** — that is CC's
  home for this idea, and DOS's lane/claim model is a different shape. So forcing
  B1 into the arbiter would be welding a foreign concept into the admission kernel.

The honest placement is a **pure classifier** (the `terminal_error` / `arg_provenance`
detector shape) that the *consumer* consults. The natural consumer already exists:
`pretool_sensor` (the PRE-moment PEP, docs/191), whose own docstring named the gap.
A future wiring adds exec-capability as an advisory rung there — when a proposed
Bash call grants arbitrary exec, surface a WARN (riding the shipped `intervention`
ladder), not an auto-deny.

The advisory-by-default posture is deliberate, and it is the docs/143 lesson: an
auto-deny on "this command can run code" would fire on a huge fraction of legitimate
Bash calls (every `python`/`npm`/`bash` invocation) — spurious disruption, the −9 pp
mistake. A capability *observation* is cheap and honest; a capability *block* is a
host's explicit, `--force`-overridable choice, never the kernel's default. So the
verdict REPORTS; the host decides.

## Domain-free: the mechanism/policy split

The mechanism is "tokenize the command, strip wrappers, look up the program." The
**policy** — *which programs grant arbitrary exec* — is data: `CROSS_PLATFORM_CODE_EXEC`
(CC's list) by default, extended per-workspace via `dos.toml [exec_capability]` or
the `--extra` flag. A host that ships an internal interpreter (`fa run`, a cluster
launcher) adds one line of data; the kernel's matching logic never changes, and it
never branches on a host name. The classifier is unit-agnostic in the same spirit as
`productivity`'s `deltas` and `breaker`'s counts: the kernel knows the *shape* of the
question, the host supplies the *specifics*.

## The CLI

The verdict IS the exit code, the `liveness`/`breaker` idiom:

```bash
dos exec-capability --command "python -c 'import os'"
#   GRANTS_ARBITRARY_EXEC  the command invokes 'python', an arbitrary-code-execution
#                          entry point — it can run any code, escaping a narrower gate
#   exit 3

dos exec-capability --command "cat python_notes.txt"
#   BOUNDED  the command invokes 'cat', not a known arbitrary-exec entry point …
#   exit 0   ← the SHAPE-not-word proof: 'python' in the filename does not trip it

dos exec-capability --command "git push" --extra git
#   GRANTS_ARBITRARY_EXEC  …'git'…    ← a host opting into the ant-only set
#   exit 3
```

BOUNDED/EMPTY 0, GRANTS_ARBITRARY_EXEC 3, contract-error 2. No-plan rail: needs only
the command — no git, no journal, no clock.

## What it makes buildable (the open right column)

Shipped as a classifier, not yet wired into the PEP — the docs/79 restraint. The
space it opens:

1. **An advisory rung in `pretool_sensor`.** The direct payoff: when a proposed
   Bash call is GRANTS_ARBITRARY_EXEC, the PRE hook attaches a WARN
   (`additionalContext`) — "this command can run arbitrary code; scope it if you
   can." A host driver that wants enforcement can escalate it to a `deny`. This is
   a consumer change (the sensor + a host policy), not a kernel change.
2. **A lane/claim auditor.** Before granting a lane that includes a Bash capability,
   a host could flag claims that hand an agent an interpreter — the CC
   "strip the arbitrary-exec allow-rule" move, in DOS's vocabulary.
3. **A `dos.toml [exec_capability]` governance surface.** A fleet operator declares
   the org's arbitrary-exec set once; every consumer (sensor, auditor) reads it.

## How it relates to the other audit lifts this session

This is the third concept generalized from docs/189, after `productivity` (H1) and
`breaker` (H2/H3). All three are domain-free and pass the mechanism/policy test, but
they sit in different families:

- `productivity` / `breaker` are **loop-economics verdicts** (is the run fading? has
  a failure class tripped?) — temporal, about a run's trajectory.
- `exec_capability` is a **structural capability classifier** (does this command
  grant arbitrary exec?) — static, about one proposed action's shape.

Together they extend the kernel's reach from "what happened / is happening" toward
"what is *about to* happen" — the PRE moment the docs/191 division identified as the
one cell with both soundness and deny-power.

---

*Provenance: idea B1 from docs/189 (the Claude Code v2.1.88 source audit). Source
shape: `src/utils/permissions/dangerousPatterns.ts` (`CROSS_PLATFORM_CODE_EXEC`).
Applies the docs/158 "a SHAPE not a word" law. Built 2026-06-07 as
`src/dos/exec_capability.py` + `dos exec-capability` + 39 tests.*

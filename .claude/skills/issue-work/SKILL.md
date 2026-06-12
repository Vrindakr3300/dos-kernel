---
name: issue-work
description: Pick the next most important open GitHub issue this agent can actually complete, make its done-condition true, land it with witnesses (suite + parity + commit-audit), and priority-tag every issue touched along the way. Use when asked to "work the backlog", "complete the next most important issue", or to fix a specific issue number end-to-end.
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Grep, Glob, Edit, Write, Bash, PowerShell
argument-hint: "[issue-number] [--dry-run]"
output_root: none
---

# Issue-work — complete the next most important issue, witnessed

> **The pick is an admission decision; the completion is a claim; only a
> witness closes it.** Importance alone does not pick an issue — importance
> × *feasibility* does (an issue whose fix surface the SELF_MODIFY guard
> protects is not yours to take, however urgent). And "done" is never your
> narration: it is the issue's done-condition made TRUE, pinned by a test,
> landed in a commit whose subject `dos commit-audit` witnesses, with
> `Fixes #N` left for git ancestry — not you — to close. Worked example:
> [#12](https://github.com/anthony-chaudhary/dos-kernel/issues/12) →
> commit `8e7f2f5` (the reference run of every step below).

**Layering.** Dev tooling that operates ON the repo (the `/release` tier) —
it names a vendor (`gh`/GitHub), so it lives in `.claude/skills/`, never
`src/dos/skills/`. The closing half is [issue-verify](../issue-verify/SKILL.md);
this skill is the completing half.

**Public-repo note.** Issue comments and labels are public documents — no
dev-machine paths, hostnames, or private-process prose. Leak-scan every
drafted body (`python scripts/leak_scan.py --text-file <draft>`) before
posting; if the scanner is absent, the hand rule is the floor.

## Step 1: Sweep and pick (skip if given an issue number)

```bash
gh issue list --state open --limit 60
```

Triage by the label taxonomy, then by importance × feasibility:

- **Skip outright:** `human-only` (operator judgment), anything blocked on an
  external party or a not-yet-published contract, `design` issues with no
  `docs/NN` plan yet (they need a plan first, not code).
- **The T1 feasibility gate:** read the issue's fix surface against
  `_DISPATCH_RUNTIME_FILES` in `src/dos/self_modify.py`. If the fix requires
  editing a file in that set, the PreToolUse hook will deny you and there is
  no agent-side force — the issue is operator-gated (say so in your report;
  do not pick it). A NEW file under `src/dos/` is not in the set and is fine.
- **Prefer** `ready` (a checkable done-condition exists) and `priority:high`;
  among peers, prefer the issue that is *currently costing* the fleet or
  operator over the merely valuable.
- State the pick and the runner-up reasoning in one short paragraph — the
  operator reads this to audit the triage, not to re-do it.

## Step 2: Verify the issue's claims before building

An issue body is a CLAIM about current behavior — probe it, don't trust it.
Reproduce the defect and test the done-condition's examples against today's
code *first*; pin what is actually true (#12's done-condition asserted a
command "still DENIES today" that in fact never denied — the test that
shipped pins reality, not the issue text).

**Probe trap:** the live hook adjudicates YOUR tool calls with the OLD code.
A Bash command (or heredoc) that merely names a kernel runtime path may be
denied — write probes and drafts to a file OUTSIDE the repo and run them by
path, and keep kernel-path literals out of command strings until your fix is
live.

## Step 3: Implement inside the lane

- Stay in the issue's lane; out-of-scope findings become NEW issues
  (`gh issue create`, with a done-condition), never commit riders.
- **Find the twins before declaring done.** A change to hook/sensor logic has
  a Go fast-path twin (`go/internal/hook/`) plus a differential parity corpus:
  port the change, regenerate LF-safe
  (`python gen_corpus.py | tr -d '\r' > corpus.jsonl`), and run
  `go test ./...` from `go/`. Grep for the Python symbol name in `go/` — the
  ports cite their Python originals.
- Closed-set changes prefer *under-matching*: an entry you are unsure of
  stays OUT (the conservative direction must be preserved by construction,
  and the PR should be able to say so).

## Step 4: Test with the hot-tree discipline

Run the touched test file first, then the FULL suite foreground
(`python -m pytest -q`, ~4 min — wait for the verdict). On failures:

1. Re-run the failing files in isolation. The shared working tree carries
   sibling loops' in-flight edits; README/workspace-config failures that pass
   isolated are the documented false positives.
2. A failure that touches YOUR surface is yours — fix it. A failure that
   doesn't is reported as "pre-existing, not mine", with the isolation
   evidence.

## Step 5: Commit — scoped, atomic, pathspec'd

The index here is SHARED STATE and the sweep cuts both ways: a plain
`git commit` after a narrow `git add` absorbs whatever a sibling left staged.
One Bash call, pathspec on the commit itself:

```bash
git add <your files> && git commit -F - -- <your files> <<'EOF'
<type>(<scope>): <subject in the repo grammar>

<body: what was wrong, what the fix does, what is preserved>

Fixes #N
EOF
```

- `Fixes #N` in the BODY; the subject keeps its grammar. NO co-author trailer.
- Immediately verify: `git show --stat HEAD` contains exactly your files.
  Swept a sibling's staged work in anyway? `git reset --soft HEAD~1`, then
  re-commit with the pathspec form — their staged entries survive.
- Do not push, tag, or release — those are outward-facing and stay with the
  operator (the commit closes the issue when someone else's push lands it).

## Step 6: Witness, then leave the evidence trail

```bash
dos commit-audit --workspace . <SHA>   # by SHA — HEAD may have moved already
```

A `witnessed` row is the honesty floor; an `unwitnessed` row means your
subject claims what your diff doesn't show — fix the subject before anything
else. Then one comment on the issue (drafted OUTSIDE the repo, leak-scanned,
posted with `--body-file`): the fixing SHA, where the done-condition is
pinned, and any operational caveat (e.g. "pre-fix binaries keep the old
behavior until rebuilt"). **Never close the issue yourself** — closure is
`Fixes #N` reaching `master`, or the issue-verify skill's evidenced path.

## Step 7: Priority-tag every issue you touched

The tier (create once if absent): `priority:high` (blocking or actively
costing the fleet/operator) / `priority:medium` (real value, nothing
bleeding) / `priority:low` (safe to defer).

```bash
gh issue edit <N> --add-label "priority:<tier>"
```

"Touched" = the issue you completed AND every issue you read deeply enough
to rank during triage — the sweep's judgment is worth keeping, so write it
down as labels, not just prose in a session log.

## Step 8: Report

- The pick and why; the runner-ups and why not (one line each).
- What shipped: SHA, files, the done-condition's before/after.
- Witness results: suite verdict (with the isolated-rerun evidence for any
  pre-existing failures), parity/twin verdict, `commit-audit` row.
- Labels applied; any new issues filed for out-of-scope findings; any
  operator-gated work surfaced (T1 surfaces, pushes, external parties).

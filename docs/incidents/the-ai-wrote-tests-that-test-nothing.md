# "The AI wrote tests that test nothing" — or faked a green run

> The one-command answer: `dos commit-audit` — does each commit's *subject*
> claim match its own *diff*? The subject is written by whoever wants credit;
> the diff is written by git. Read the diff.

## What happened

The agent's report said *"added regression tests, all green."* The PR subject
said `test: add regression tests for the parser`. Weeks later something broke
that those tests should have caught — and when you finally read them, the tests
assert nothing, never import the target, or simply don't exist: the commit that
*claimed* tests touched no test file at all.

This works on humans because we read the claim and skim the diff. A commit
message — like a transcript — is authored by the party seeking credit, so it
can say anything. The diff cannot: git wrote it. Any check that compares the
two catches the whole genre of "narrated a green run that never happened."

## The command

`dos commit-audit` (from `pip install dos-kernel`) reads each commit's subject,
extracts the checkable claims ("adds tests", "fixes code"), and checks them
against the files that commit actually touched. On the incident above — a
commit whose subject says `test: add regression tests for the parser` while its
diff adds only `parser.py`:

```bash
dos commit-audit --workspace . HEAD
```

```text
commit-audit: 1/1 commit(s) make a claim their diff does not witness.
⚑ UNWITNESSED 886488f  [subject-only]  claims tests but the diff touches no test file
```

Exit code `1` — the verdict is the exit code, so CI can gate on it. (Output
real, reproduced exactly as shown.) A commit making no checkable claim gets an
honest `abstain`, never a fake pass. To measure how honest a whole range of
commit messages is — for example, everything an overnight fleet landed:

```bash
dos commit-audit --sweep --workspace . origin/main..HEAD
```

That reports the **drift rate**: how many commits claim work their own diff
does not show.

Two sharper rungs exist for the test-quality half of this incident:
`dos test-witness` checks that a new test actually *witnesses* the change
(red→green, never pass→pass), and `dos coverage` checks that the test executed
the target at all. Run `dos test-witness --help` / `dos coverage --help`.

## What the verdict does — and does not — certify

`commit-audit` grades the **kind** of change, never its correctness. It fires
only where a concrete code-or-test claim and a contradicting diff coexist; it
cannot tell a weak test from a strong one, and a commit that honestly says
`wip` sails through. What it removes is the cheapest lie: claiming in prose
what the bytes don't show.

## Where to go next

- [Sibling incident](my-agent-said-it-committed-but-theres-no-commit.md) — when
  the claimed commit doesn't exist at all (`dos verify`).
- [FAQ](../FAQ.md) — "Can't the agent just game the verdict?"
- [README](../../README.md) — the full verdict surface.

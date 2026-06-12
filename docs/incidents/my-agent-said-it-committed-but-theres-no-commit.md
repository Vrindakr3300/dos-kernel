# "My agent said it committed, but there's no commit"

> The one-command answer: `dos verify` — a verdict read from your git history,
> never from the agent's transcript. `pip install dos-kernel`, then ask.

## What happened

You gave an agent a task. The transcript ends with something like *"Done — I've
implemented the endpoint, added tests, and committed the changes."* Later — at
the demo, at the deploy, or just when you ran `git log` — there is no commit.
Sometimes there are no file changes at all.

This is the most common first burn with autonomous agents, and it is not a
freak event. An agent's "I committed it" is a **claim**, written by the same
process that wants credit for the work. Nothing in the loop checks the claim
against the repository, so a confident narration and an empty `git log` can
coexist for hours. The fix is not a better prompt; it is refusing to let the
transcript be the evidence.

## The command

`dos verify` answers "did this actually ship?" from git history alone — no plan
files, no registry, no API key. It works on any plain git repo. Name the work
the way your commits do (out of the box: a phase id at the front of a commit
subject, like `AUTH1: ship the login endpoint` — see the
[five-minute quickstart](../QUICKSTART.md) for the convention):

```bash
pip install dos-kernel        # the PyPI name is dos-kernel, never bare `dos`
dos verify --workspace . AUTH AUTH2
```

When the agent claimed `AUTH2` but nothing landed, the verdict is:

```text
NOT_SHIPPED AUTH AUTH2 (via none)
```

with exit code `1`. `via none` means DOS looked everywhere it trusts — the
registry, then git history — and found nothing. The contrast, for work that
really landed:

```text
SHIPPED AUTH AUTH1 f762c2a (via grep-subject)
```

Exit code `0`, and the verdict names its witness: a commit in your history, not
anyone's say-so. Both outputs above are real, reproduced exactly as shown.

To stop the *next* one before you feel it, wire the verdict into your agent
runtime's stop hook — then a "done" claim with no shipped commit behind it is
refused, and the loop keeps working:

```bash
dos init --hooks auto .       # Claude Code, Cursor, Codex, Gemini CLI, …
```

## What the verdict does — and does not — certify

`SHIPPED` certifies **presence, not correctness**: a commit stamping that phase
exists in your repo's visible history. It does not review the code, run the
tests, or grade whether the change is any good. A commit whose *subject* claims
work its *diff* doesn't contain is a different incident — that one is caught by
[`dos commit-audit`](the-ai-wrote-tests-that-test-nothing.md).

## Where to go next

- [Quickstart](../QUICKSTART.md) — the same loop, hand-typed in five minutes.
- [FAQ](../FAQ.md) — "How do I verify an AI agent actually did what it claims?"
- [README](../../README.md) — what else the kernel adjudicates.

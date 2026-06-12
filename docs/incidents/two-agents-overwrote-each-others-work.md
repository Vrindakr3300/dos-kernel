# "Two agents overwrote each other's work"

> The one-command answer: `dos arbitrate` — may this agent start *here* without
> colliding with work already in flight? A collision is refused at admission
> time, before the edit exists, instead of discovered at merge time.

## What happened

You ran two agents at once — two terminals, two tabs, a small fleet. Both were
"helping". Both edited the same file. The second save silently flattened the
first, or the two diverged and the merge ate an afternoon — and nobody noticed
until review, because each agent's own transcript looked perfectly clean.

Agents don't check who else is editing; nothing in the loop makes them. Git
worktrees don't fix this either — they isolate the copies but defer the
collision to the merge, where recovery is most expensive (the
[FAQ entry on worktrees](../FAQ.md#dont-git-worktrees-already-solve-this--one-isolated-checkout-per-agent)
has the measured evidence). What's missing is an *admission* check: a referee
that says no to the overlapping start.

## The command

Declare lanes once — `dos init .` seeds one lane per top-level source
directory — then have each agent take a lease before it starts. Agent 1 takes
the `api` lane, journaled so every other process sees the hold:

```bash
dos init .
dos lease-lane acquire --lane api --owner agent-1
```

```json
{"outcome": "acquire", "journaled": true, "lane": "api", "owner": "agent-1",
 "reason": "cluster lane 'api' free — admitted.", "tree": ["api/**"], ...}
```

Agent 2 asks for the same lane and is refused — with a structured reason and a
way forward, not a silent overwrite:

```json
{"outcome": "refuse", "lane": "",
 "reason": "lane 'api' is already held by a live loop — pick a different --lane or wait.",
 "free_clusters": ["web"], ...}
```

Exit code `1`. The same ask against the disjoint `web` lane is admitted
(exit `0`) — disjoint lanes run concurrently; that is the point of declaring
them. (Both decisions above are real arbiter output, abridged to the
load-bearing fields; `dos arbitrate --lane api` asks the same question as a
pure decision, without taking the hold.) When the work lands, release the
lane:

```bash
dos lease-lane release --lane api --owner agent-1
```

The lease lives in a write-ahead journal, so a crashed agent can't leave a
phantom lock — and an agent runtime wired with `dos init --hooks auto .` can
have the refusal *enforced* (the colliding tool call is denied before it runs).

## What the verdict does — and does not — certify

`arbitrate` is admission control over the **file tree**: it refuses two live
leases whose declared trees overlap. It does not merge, does not lock files at
the operating-system level, and cannot stop an agent that never asks — the
discipline (or the hook wiring) is what routes agents through it. A granted
lease certifies "no live overlap at admission", not that the work done inside
the lane is correct.

## Where to go next

- [FAQ](../FAQ.md) — "How do I stop two AI agents from editing the same files
  at the same time?"
- [Quickstart §5–6](../QUICKSTART.md) — `arbitrate` vs `lease-lane`, hand-typed.
- [README](../../README.md) — the lane taxonomy and the refusal vocabulary.

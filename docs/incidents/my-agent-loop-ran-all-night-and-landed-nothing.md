# "My agent loop ran all night, said 'making progress', and landed nothing"

> The one-command answer: `dos liveness` — is the run *moving*, or just
> narrating? The verdict reads commits and heartbeats, never the agent's
> "still making progress" line. Its siblings price the damage: `dos
> productivity` (is the work rate collapsing?) and `dos efficiency` (did the
> tokens buy anything?).

## What happened

You started a loop at 11pm — *"keep working until the feature is done"* — and
went to bed. In the morning the transcript is enormous and optimistic: plans,
re-plans, "good progress on the refactor". The token bill is real. The repo is
untouched: zero commits, or a handful of trivial ones, since you left.

The loop wasn't lying on purpose; it was *grading itself*, and a loop that
grades itself by re-reading its own narration always passes. The only honest
referee is the state the loop cannot author by talking: the git history it did
(or didn't) move, and the clock.

## The commands

Mint a run id when the loop starts, note the starting commit, and at any point
ask whether the run is actually moving:

```bash
RID=$(dos run-id mint overnight-refactor | python -c "import json,sys; print(json.load(sys.stdin)['run_id'])")
SHA=$(git rev-parse HEAD)
# ...hours later:
dos liveness --run-id "$RID" --start-sha "$SHA"
```

A run whose heartbeat went silent with nothing landed:

```text
STALLED  no heartbeat and 0 commits since start — run is dead or hung (never beat)
```

Exit code `4`. The overnight case — still alive, still talking, landing
nothing — is `SPINNING` (exit `3`). Reproduced here deterministically by
injecting the clock (`--now-ms` simulates "8 hours in"; a live run omits it):

```text
SPINNING  alive (heartbeat 5000 ms old ≤ spin window 900000 ms) and 28836358 ms
into the run (≥ grace 1800000 ms) but 0 commits and 0 lane events since start — spinning
```

Two siblings sharpen the autopsy. `dos productivity` reads the *trend* of work
per step — the unit (commits, changed bytes, tests passed) is yours:

```bash
dos productivity --deltas 800,600,300,40,12 --floor 100
```

```text
DIMINISHING  the last two of 5 steps landed 40 then 12 work units, both under
the 100-unit floor — a sustained fading rate (diminishing returns)
```

And `dos efficiency` relates the work to its price in tokens:

```bash
dos efficiency --work 0 --tokens 80000
```

```text
WASTEFUL  80000 tokens spent and 0 work units landed — the spend bought nothing (pure overhead)
```

All three verdicts are exit codes (`0` healthy; `3`/`4` degraded), so a
supervisor loop, a cron job, or a CI step can gate on them mechanically —
catch the burn at 1am instead of reading about it at 9.

## What the verdicts do — and do not — certify

All three are **advisory**: they report, they never kill a process. `ADVANCING`
means repository state moved — it does not grade whether the commits are any
good (a loop committing junk reads as moving; pair with
[`dos commit-audit`](the-ai-wrote-tests-that-test-nothing.md)). `productivity`
and `efficiency` only compare the magnitudes you feed them — honest inputs in,
honest verdicts out; both counts come from the environment (git, the test
runner, the provider's bill), not from the agent.

## Where to go next

- [FAQ](../FAQ.md) — "How do I detect that an agent loop is spinning?"
- [Debug-a-stuck-fleet playbook](../../examples/playbooks/06_debug-a-stuck-fleet.md)
  — the operating guide for a fleet that is stuck right now.
- [README](../../README.md) — wiring the verdicts into hooks and supervisors.

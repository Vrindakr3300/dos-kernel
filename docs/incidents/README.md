# Incident pages — start from what just happened

One short page per real-world failure mode, titled in the words you'd actually
search right after it happened. Each page tells the story in plain language,
gives the one command that catches that failure (with its real output), states
honestly what the verdict does *not* certify, and points onward.

If you're not arriving from an incident, start at the
[README](../../README.md) or the [five-minute quickstart](../QUICKSTART.md)
instead.

| It just happened | The command that catches it |
|---|---|
| ["My agent said it committed, but there's no commit"](my-agent-said-it-committed-but-theres-no-commit.md) | `dos verify` |
| ["The AI wrote tests that test nothing" / faked a green run](the-ai-wrote-tests-that-test-nothing.md) | `dos commit-audit` |
| ["My agent loop ran all night, said 'making progress', and landed nothing"](my-agent-loop-ran-all-night-and-landed-nothing.md) | `dos liveness` / `dos productivity` / `dos efficiency` |
| ["Two agents overwrote each other's work"](two-agents-overwrote-each-others-work.md) | `dos arbitrate` |

# Braintrust × DOS — the witness-gated scorer

Braintrust's scorer shelf grades **text**: an LLM judge or a string metric
reads the agent's output and mints the score — bytes the agent authored, so a
confidently-narrated failure scores like a success. This recipe adds the rung
none of them cover ([issue #48](https://github.com/anthony-chaudhary/dos-kernel/issues/48)):
`dos reward`'s admission verdict, computed from a read-back the agent did not
author, in Braintrust's handler shape.

```bash
pip install dos-kernel
python examples/braintrust_scorer/dos_braintrust_scorer.py   # offline, no account
python -m pytest tests/test_braintrust_scorer_example.py     # the pinned rows
```

| verdict | score | meaning |
|---|---|---|
| `ACCEPT` | `1.0` | a non-forgeable witness confirmed the claimed effect |
| `REJECT_POISON` | `0.0` | the witness REFUTED it — the row a text grader scores high |
| `ABSTAIN` / `NO_CLAIM` | `None` | no accountable witness / nothing claimed — unscored, never a silent 0 or a free 1 |

The verdict + reason ride the score's `metadata`. Non-distillability holds
through the adapter: the same forged read-back scores 0.0 under any narration,
and an `AGENT_AUTHORED` "receipt" the agent pastes into metadata is
structurally ignored (`believe_under_floor`).

## Wiring into online scoring

A Braintrust **custom code scorer** (online scoring config or `Eval(scores=…)`)
is a plain handler — build it once at module load:

```python
from dos_braintrust_scorer import make_braintrust_scorer

def my_claim_extractor(output: str) -> bool:
    return "cancelled" in output.lower()      # your confident-write detector

handler = make_braintrust_scorer(my_claim_extractor)

def dos_reward(input, output, expected=None, metadata=None, **kwargs):
    return handler(input=input, output=output, metadata=metadata)
```

The default witness replays the **recorded read-back** your runtime logged
into the span's metadata at run time (`metadata["readback"]` — see
[`fixtures/recorded_runs.json`](fixtures/recorded_runs.json) for the shape);
that is what makes offline scoring deterministic. A scorer with egress (or an
HTTP-endpoint scorer on your own infrastructure) swaps in a **live** witness —
re-GET the API, read the ledger — through the same parameter:

```python
def live_witness(task, metadata):
    state = my_provider.get_subscription(task).status   # the world, not the text
    return (EvidenceFacts.attest("provider_api", Accountability.THIRD_PARTY, task)
            if state == "cancelled"
            else EvidenceFacts.refute("provider_api", Accountability.THIRD_PARTY, task),)

handler = make_braintrust_scorer(my_claim_extractor, witness=live_witness)
```

Record the accountability honestly: a runtime that logs the agent's own paste
as the read-back must mark it `AGENT_AUTHORED` — the floor then ignores it,
which is the point.

The sibling recipe for W&B Serverless-RL / Weave is
[`../serverless_rl/`](../serverless_rl/) — same kernel verdict, that
platform's two shapes.

# NeMo Guardrails × DOS — the effect-check action

The custom-action shelf in [NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails)
holds actions that adjudicate **text** — toxicity, hallucination-likelihood,
prompt-injection. This recipe adds the rung none of them cover: **did the
claimed effect actually happen?** The `dos_effect_check` action
(`dos.drivers.nemo_action`, issue
[#51](https://github.com/anthony-chaudhary/dos-kernel/issues/51)) re-reads
git / the filesystem / the ship oracle — surfaces the agent did not author —
and returns the typed verdict for the flow to act on.

```bash
pip install dos-kernel          # the action needs nothing else
python examples/nemo_guardrails/demo.py   # offline: forged claim refused, landed claim accepted
```

## Registration — two ways

**Auto-discovered** ([`config/actions.py`](config/actions.py)): a rails
config folder's `actions.py` exposing the action at module level. The factory
runs at app load, so a `CommitClaim()` baseline pins to HEAD at start:

```python
from dos.drivers._effect_gate import CommitClaim
from dos.drivers.nemo_action import make_dos_effect_check

dos_effect_check = make_dos_effect_check(".", expect=[CommitClaim()])
```

**Programmatic**:

```python
rails = LLMRails(config)
rails.register_action(make_dos_effect_check("."), name="dos_effect_check")
```

## The flow ([`config/rails/output.co`](config/rails/output.co))

```colang
define flow check effect claims
  $verdict = execute dos_effect_check(claim_text=$bot_message)
  if $verdict["tripped"]
    bot refuse unverified claim
    stop
```

The verdict dict carries `outcome` (`TRIPPED` / `CLEAR` / `ABSTAINED` /
`NO_CLAIM`), `tripped`, the one-line `reason`, and per-claim `rows`. The
action is **advisory**: it only returns the verdict — your flow decides what
a refuted claim does (refuse, rephrase, escalate). Fail-to-abstain holds: a
crash or unreachable witness returns `ABSTAINED` with `tripped=False`, never
a fabricated refusal — only an accountable read-back that says the claimed
effect is ABSENT trips.

Claim kinds (`dos.drivers._effect_gate`): `CommitClaim` (new commits beyond a
baseline), `FileClaim(path)` (the file exists), `ShippedClaim(plan, phase)`
(the ship oracle finds the phase in git ancestry — no plan registry needed).
Declared at construction, never parsed from prose; inject `extract=` to mine
claims your way.

Pinned by `tests/test_nemo_action.py` (offline; a lockstep slice runs against
the real `nemoguardrails` decorator when installed).

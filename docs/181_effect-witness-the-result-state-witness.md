# 181 — effect_witness: the result-state witness (building DOS's key unbuilt member)

> **One-line claim.** docs/176/177 named the **out-of-trajectory result-state
> witness** as DOS's most valuable UNBUILT member — the one tool-verification check
> whose value *grows* with model strength, because it reads the world instead of the
> trajectory. docs/180 found three groups shipped it externally in early 2026
> (Agent-Diff, VAGEN, Tool Receipts). This doc builds DOS's domain-free,
> floor-disciplined version: `effect_witness.witness_effect` (pure kernel verdict) +
> `drivers/state_diff` (the Agent-Diff state-diff read-back). It catches the exact
> docs/177 silent frontier-fail — a confidently-narrated success the world does not
> corroborate — that the three in-trajectory detectors fire **zero** on.

## 0. What was unbuilt, precisely

DOS already had **most** of the scaffolding, which is why this was a build and not a
research project:

- `evidence.py` — the witness seam: the `EvidenceSource` protocol, the
  `AGENT_AUTHORED < OS_RECORDED < THIRD_PARTY` accountability spectrum, and the
  security-load-bearing `believe_under_floor` (believe ⟺ a non-forgeable source
  attests) + `derived_witness` (mint by joining two independently-authored facts).
- `drivers/os_acceptance.py` — one witness: run a command, read the OS exit code.
- `claim_extract.py` — pull an agent's asserted `(plan, phase)` from a transcript.

What was **missing** was the *join* the three SOTA groups built: a verdict that takes
an agent's **claimed effect** and a **read-back of world state from a different
surface**, and asks *is the claimed change actually present?* The `os_acceptance`
witness answers "did an acceptance command pass?" — it does not compare a *specific
claimed effect* against a *state delta*. That join is `effect_witness`.

## 1. The three concepts taken from the SOTA (docs/180)

| Concept | Source | What we took |
|---|---|---|
| **Canonical state-diff** | Agent-Diff (2602.11224) | Success = the expected STATE delta occurred; diff = inserted/deleted/updated entities; presence (claim ⊆ delta), not fuzzy trace match. → `drivers/state_diff.diff_state` + the `StateDiffEvidenceSource`. |
| **Independent active prober** | VAGEN (2602.00575) | The witness must read the world from a surface the AGENT did not author. → the `accountability` rung is the structural encoding of "different surface": a snapshot the kernel read is `OS_RECORDED`; an agent-pasted one is rejected at construction. |
| **Unforgeable receipt** | Tool Receipts (2603.10060) | An HMAC the LLM cannot forge closes the actor==witness hole. → NOT built here (it's the next rung); noted as the follow-on in §5. The floor discipline already refuses to believe a forgeable read-back, so the system is sound without it — HMAC would *extend* the set of cases where a same-process witness can still be trusted. |

## 2. The design — a verdict is a JOIN of two independently-authored facts

`effect_witness.witness_effect(claim, readbacks)` is the pure keystone. It never
re-reads the agent's claim against itself (the mirror-verifier trap,
`[[consistency-is-not-grounding]]`). It mints a verdict only by joining:

1. **the claim** (`EffectClaim`) — what the agent ASSERTED it did to the world, an
   opaque effect-key. The agent authored this — the forgeable floor.
2. **the read-back** (`evidence.EvidenceFacts`) — a witness re-read of world state,
   authored by the witness, carrying its `accountability` rung.

The verdict is four-valued (the typed-verdict family):

- **CONFIRMED** — a non-forgeable witness re-read the world and the effect is PRESENT.
  The only value granting belief; gated by the floor.
- **REFUTED** — a non-forgeable witness re-read the world and the effect is ABSENT.
  **The load-bearing value: docs/177's silent frontier-fail made VISIBLE** — a
  narrated success the world denies.
- **UNWITNESSED** — no accountable witness reached a presence answer (only
  forgeable-floor reads, or only NO_SIGNAL). The honest abstain.
- **NO_CLAIM** — the agent asserted no checkable effect (the `claim_extract`
  abstain-never-invent law, restated for effects). NOT a pass.

The floor is enforced by **delegating the belief decision to
`believe_under_floor`** — so the dual-of-`overlap_policy` guarantee lives in ONE
place. The structural consequence (pinned by `test_effect_witness.py`):

> A read-back on the forgeable floor (`AGENT_AUTHORED` — the agent re-reading its OWN
> surface) is recorded but **structurally incapable of CONFIRMED or REFUTED on its
> own**. The worst a lying same-surface witness can do is be IGNORED (a safe-direction
> no-op), never manufacture a CONFIRMED for an effect that did not happen, nor a
> REFUTED for one that did.

## 3. Why presence, not correctness

We verify **claim ⊆ witnessed-delta** (was the change the agent took credit for
actually made?), not global end-state correctness. Global correctness needs a gold
state — a benchmark oracle has one (Agent-Diff diffs against a golden delta); a live
deployment does not. Presence needs only the agent's claim + a read-back, both of
which a live runtime HAS. This is the honest, domain-free slice — and it is exactly
the silent-fail class: gemini-3-pro narrates *"I successfully created the quiz"*, the
fresh read-back shows no such quiz → REFUTED. (Proven live in §4.)

## 4. Proof it works (live, $0)

```
$ python -m dos.drivers.state_diff "quiz:Classic-Art-History" \
    --before before.json --after after.json \
    --narrated "I have successfully created the quiz 'Classic Art History Questions'."
VERDICT   REFUTED   (believe=False refuted=True)
WITNESS   state_diff (OS_RECORDED)
WHY       REFUTED — non-forgeable witness re-read the world and effect
          'quiz:Classic-Art-History' is ABSENT (a narrated success the world does
          not corroborate)
```

When the effect really happened (the quiz IS in the delta) → `CONFIRMED`. This is the
docs/177 frontier-silent class — the one the three trajectory detectors fire **zero**
on — caught by a read-back the agent did not author.

## 5. The honest boundaries + what's next

- **DETECT, not FIX, and ADVISORY.** The verdict reports; it does not refuse a lease
  or roll back. A consumer (`dos verify`, the decisions queue, a PostToolUse hook)
  routes a REFUTED to a WARN/human — the docs/99 actuation-boundary discipline.
- **Soundness rests on the read-back's rung.** A state-diff over agent-pasted
  snapshots is `AGENT_AUTHORED` and is **rejected at construction** — the kernel must
  read the snapshot for the witness to be sound. A host with a SaaS store writes a
  `THIRD_PARTY`-tagged sibling reader.
- **Not yet wired into the umbrella `dos` CLI.** Reachable today via `python -m
  dos.drivers.state_diff` and the pure `witness_effect` API. Wiring a `dos witness`
  verb + folding a CONFIRMED/REFUTED into `dos verify`'s belief output is the next
  lift (it touches `cli.py`, currently a concurrent lane).
- **The HMAC receipt rung (Tool Receipts) is the next member.** It closes the
  actor==witness hole for a same-process tool stream — a `tool_receipt` evidence
  source on a crypto-unforgeable rung. The floor discipline already makes the system
  sound without it; HMAC widens the set of trustable witnesses.
- **A live read-back PROBER (VAGEN-style).** `state_diff` needs two snapshots; a
  fuller witness takes its OWN read action against the live store at check time (an
  HTTP re-GET, a fresh query). `os_acceptance` already does the command form; a
  `drivers/http_readback` that re-GETs an idempotent effect URL is the natural sibling.

## 6. Layering & litmus

- `effect_witness.py` is **kernel** (pure, no I/O, no host names, no driver import —
  pinned by `test_state_diff.test_kernel_effect_witness_does_not_import_driver`). It
  imports only `dos.evidence`.
- `drivers/state_diff.py` is a **driver** (it reads a state store; imports the kernel,
  never the reverse). Advisory.
- This does not couple the kernel to the phased-plan layer or any host — an
  `EffectClaim.key` is an opaque string the host's extractor chooses.

This is docs/170's governing finding honored: defensive in-trajectory lift decays on
strong models, but the **result-state witness is the one detector-family member whose
value GROWS with model strength** (docs/176) — because a more competent agent fails
more silently, and silence is exactly what an out-of-trajectory read-back is for.

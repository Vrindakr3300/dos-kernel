# Raising detector recall on the silent / frontier failure — and the one byte-clean way to do it

> **The docs/157 replay left a sharp question: the detectors fire with high precision but ~2–3%
> recall, and purchase VANISHES on the strongest models. To make DOS a net-lift / SOTA story rather
> than an honest-negative one, the detectors must *speak more often* — catch more of the 95% of
> failures they currently miss, ESPECIALLY on the frontier models where they fire ~0. This doc asks
> how to do that WITHOUT leaving the byte-clean invariant (the only thing that makes a DOS verdict
> worth acting on), designs the candidate space, adversarially filters it, and SHIPS the one
> in-trace detector that survives: `terminal_error`. Result: union recall 4.74% → 6.18% at 92.6%
> precision, with 75 net-new catches — and it ADDS catches on the frontier (the strongest models):
> +7/+9/+12 net-new at the top-4/≥0.30/top-10 capability cuts (§4 table). It is NOT the first detector
> to reach the frontier — `tool_stream` already catches some there — but it is additive there, and is
> the first whose catches CONCENTRATE on the reasoning frontier (o3, claude-4.5-sonnet).**

**Status:** SHIPPED in the benchmark harness — `benchmark/toolathlon/trajectory.py`
(`terminal_error_fired` + `is_struct_error` + `TerminalErrorEvidence`), wired into the replay grid +
durable rows, **31 tests green**. The design survey + adversarial filter (15-agent workflow) is in
§3; the shipped detector is §4; the rejected (forgeable) ideas are §5; the remaining frontier gap
and its $ tier are §6.

**Lineage.** Companion to `docs/157` (the replay that surfaced the recall ceiling). Inherits the
byte-clean doctrine from `docs/141` (byte-inequality), `docs/143 §5a` (the mirror-verifier trap),
`docs/145` (`tool_stream`, the env-authored-repeat detector this is a sibling of), `docs/150/152`
(`dangling_intent`), and the `claim_extract` / `derived_witness` / `believe_under_floor` evidence
seam. **`docs/159` stress-tests this detector against naive baselines** (loose grammar,
any-error-anywhere, no-recovery-check) and extracts the reusable detector-design defaults — the
answer to "is this real, and would a naive version do as well?" **`docs/160` positions it against the
SOTA** — a runnable head-to-head vs the trained-classifier baseline (arXiv 2511.04032), which on this
corpus does NOT beat the zero-training detector at a deployable false-alarm rate, plus why the
arbiter neighbors (Limen/CodeCRDT) are a different axis and not runnable on frozen traces.

**Terms.** Every term this doc leans on — `byte-clean` / `byte-author` / `forgeable`, the three
detectors, `net-new` / `additive` / `union recall`, the `frontier` cut + `SSOT`, `mirror-verifier`,
`structured error envelope` — is defined in `benchmark/toolathlon/GLOSSARY.md` (grounded in the
detector source). Read it first if any of those are unfamiliar.

---

## 1. The problem, measured (from the durable rows)

From `benchmark/toolathlon/_results/replay_all_rows.csv` (7,116 records, 22 models, third-party
labeled):

- **76% of runs fail** (hard benchmark). The two shipped detectors catch **4.74% of failures**
  (union recall) — so **95% of failures are SILENT** to them.
- The silent failures are **NOT premature quits**: median 19 tool steps, 50% ran ≥20 steps, only 6%
  stopped short. They are **long runs that did a lot and still failed the final-state check.**
- `tool_stream` **near-misses are ~zero** (only 40 silent failures had run-length 2, just under the
  fire threshold of 3). **Lowering `repeat_n` will not help** — there is no cliff of almost-loops to
  recover.
- **92% of silent failures have a substantial final narration** (median 1,004 chars) — the agent
  *wrote a lot* at the end.
- The **top-capability four** (claude-4.5-opus, deepseek-3.2, claude-4.5-sonnet, gemini-3-pro — the
  highest Toolathlon pass-rate) are where the pair goes nearly silent: across their ~750 failures the
  pair catches just **2** (`terminal_error` adds **7** net-new). Of those failures: **59% confidently
  CLAIM completion** ("All customers have now received their surveys!"), 21% admit partial, 19% hedge.
  **They fail WHILE asserting success.** (NB — "frontier" is a capability THRESHOLD, and the net-new
  count moves with it; §4 reports all three honest cuts. fig6 draws the ≥0.30 cut.)

So the recall ceiling is not "no evidence exists" — it is "**we read a narrow slice of the evidence
that exists.**" The frontier failure specifically is **confidently-wrong completion**: a polished,
false "done."

## 2. The hard constraint: byte-clean, or it dies on deployment

A DOS verdict is worth acting on ONLY if it reads bytes the **judged agent did not author** (the
§5a line, `src/dos/tool_stream.py`). The tempting frontier detectors all violate this:

- A **hedge / confidence detector** ("flag runs where the agent hedges") would fire on 19% of
  frontier failures here — but it reads **agent-authored narration**. A model trained against it just
  stops hedging. It shows fake recall on this frozen dataset and **degrades to zero when deployed**
  (the mirror-verifier trap, `docs/143 §5a`).
- An **overconfidence detector** ("flag runs that claim success too strongly") — same flaw, inverted.

**The only honest way to catch "agent claims X but X is false" is to check the claim against an
effect the agent did not author.** That single principle organizes the whole candidate space.

## 3. The design survey (a 15-agent adversarial workflow)

Three generator lenses (effect-grounding, expand-existing-byte-clean-signals, frontier-specific)
proposed 12 candidates; two skeptics per candidate ruled on each (`byte_clean` ∈
clean/borderline/forgeable, `survives_frontier`, `recall_tier`, `verdict`). The filter's job: reject
anything that reduces to reading agent narration. Outcome:

| Candidate | byte-clean | frontier? | recall | verdict |
|---|---|---|---|---|
| **`terminal_error`** — stopped on an unresolved structured env error | **clean** | **yes** | **medium** | **BUILT (§4)** |
| live post-hoc effect re-read (re-query the app for each claim) | clean | yes | **high** | prototype — but **$ tier** (§6) |
| error_streak — N consecutive env errors the agent walked past | clean | yes | low | future (subsumed by `terminal_error`) |
| terminal_error_override — last result an error yet stopped | clean | yes | low | = `terminal_error` (merged) |
| intra-trace final-state re-read (agent re-read its own write) | borderline | yes | low | prototype — read-your-own-write hazard |
| cross-tool set reconciliation (claimed-N vs env-enumerated-N) | borderline | no | low | prototype — narrow subclass |
| required-precursor-read missing before a write | clean | no | low | future |
| **hedge / over-confidence language scoring** | **forgeable** | no | negligible | **REJECTED** |
| **completion-without-verification (claim-vs-last-narration)** | **forgeable** | no | negligible | **REJECTED** |
| absence_of_acked_effect, unconsumed_error_value, set-coverage shortfall | mixed | no | low/neg | rejected |

The two **forgeable** rejections are the load-bearing negative result: both reduce to reading the
agent's own words about itself. The workflow caught that even the "completion-without-verification"
idea (tempting — "the agent claimed done but its last narration doesn't match the last result") is
forgeable, because the *claim* it extracts is agent-authored. Only a check against **env-authored**
or **third-party** bytes survives.

## 4. SHIPPED: `terminal_error` — the agent stopped on an env failure it never fixed

**The mechanism.** Read the ENV-authored `content` of the last K=3 tool results (the MCP gateway's
bytes). A result is an error iff it matches a **structured error envelope** — an `MCP error -3xxxx`
code, an `"isError": true` flag, a leading `Error:` text node, a `Traceback`, a non-zero `exited
with code N`, or a `permission denied`. Fire iff such an error sits in the closing window **AND no
later result from the SAME tool recovered to a success** — i.e. the agent walked away from an
unresolved environment failure.

**Why it is byte-clean (the §5a line held).** The error envelope is in a `tool` message the **MCP
gateway authored**, not the judged agent — identical provenance to `tool_stream.result_digest`, the
canonical byte-clean field. A model **cannot forge an env failure-envelope into a success**, and
"stop emitting the cue" is *not available to it* — the **environment** emits the cue. It never reads
the agent's narration, so it does not reduce to a forgeable satisfaction-predicate. A pinned test
proves the point: even a confident final "Email sent successfully to all recipients!" does **not**
suppress the fire when the env's `tool` result was `{"isError": true, "SMTP 550 rejected"}`.

**Why the grammar is TIGHT (where the precision risk lives).** The provenance is clean; the only
precision risk is the error-classification grammar. A **loose** match on `error` / `failed` / `not
found` would match env-authored PAYLOAD that legitimately contains those words (an arXiv abstract
about "error rates", a "404" in fetched HTML, "task failed successfully"). So the grammar is anchored
to **structured envelope shapes only** — the same tight-anchor discipline as the `result_digest`
normalizer (docs/157 §4). Loose substrings (`not found`, bare HTTP 4xx/5xx — 3.4% / 1.6% of results)
are **deliberately excluded**: they appear in legitimate content, and trading precision for a few
points of recall is the wrong trade for an advisory detector.

**The tight-grammar choice, measured (not asserted).** Swapping the structured grammar for a LOOSE
one (any `error`/`failed`/`not found`/`4xx`/`5xx`/`denied` substring) was tried and rejected with
numbers: it fires on **65% of all runs at 69.4% false-alarm** — a completely unusable detector that
flags the majority of *passed* runs. The tight structured-envelope grammar fires on 1.2% at **0.2%
false-alarm**. That ~350× false-alarm gap is the entire reason the grammar is anchored, not loose —
the same lesson as the `result_digest` normalizer's tight token shapes (docs/157 §4).

**The measured result (full corpus, third-party scored):**

```
terminal_error  fire=1.2%  prec=95.0%  (base=76.2%)  lift=+18.8pp  recall=1.5%  falarm=0.2%  [fired=80 fail/pass=76/4]
```

**The headline — it is ADDITIVE, and it adds catches on the frontier (not the first to reach it):**

- **75 of its 76 catches are NET NEW** — missed by both shipped detectors. It is not re-catching the
  same failures; it is a distinct slice (the agent that hit a wall the environment reported and
  stopped, vs. the agent that narrated open work or looped).
- **It adds net-new catches on the frontier — but the count is THRESHOLD-SENSITIVE, so we report all
  three honest cuts** (capability = the in-data Toolathlon pass-rate; numbers straight from the
  `benchmark/toolathlon/additivity.py` single-source-of-truth, `--check`-enforced):

  | "frontier" cut | models | pair already caught | terminal_error net-new |
  |---|---|---|---|
  | top-4 (pass-rate ≥ 0.37) | 4 | 2 | **7** |
  | **≥ 0.30 (the SSOT default, fig6)** | **8** | **6** | **9** |
  | top-10 (pass-rate ≥ 0.26) | 10 | 43 | **12** |

  Two honesty points the table makes that a single number hides: (1) **the pair is NOT blind on the
  frontier** (it already catches 2 / 6 / 43 as the cut widens) — so `terminal_error` is **additive
  there, NOT the first DOS signal to reach the frontier** (the over-claim a stale draft made; an
  earlier hand-picked 10-model set inflated this to "22 net-new / pair 35", which no principled cut
  reproduces). (2) The *additive* count rises with the cut only because more models are admitted;
  the strict top-4 (+7) is the cleanest "where the pair is nearly silent" statement. `dangling_intent`
  is the detector that is genuinely near-blind on the frontier (≈1 catch across the strongest models).
- **Union recall rises 4.74% → 6.18%** (the pair → the trio), a **+30% relative gain**, and the
  **union of all three fires at 92.6% precision**.

See `benchmark/toolathlon/_results/fig6_trio_additivity.png` (drawn from the ≥0.30 SSOT cut).

## 5. The rejected ideas (the negative result, recorded)

Two candidates were rejected as **forgeable** — they would inflate recall on this frozen dataset and
collapse on deployment:

1. **Hedge / over-confidence language scoring** — reads agent-authored narration tone. The model
   learns to stop hedging.
2. **Completion-without-verification (claim-vs-last-narration)** — the "claim" it extracts is
   agent-authored; comparing two agent-authored things is consistency, not grounding
   (`[[project-dos-byte-inequality-and-derivatives]]`). Even though it *sounds* like effect-checking,
   without an env-authored operand it is a mirror verifier.

Recording these is the point: the space of "speak more often" ideas is dominated by forgeable
narration-readers, and naming them keeps the next agent from re-proposing one.

## 6. The remaining frontier gap — and why it needs $ (the honest boundary)

`terminal_error` catches the frontier failure where **the environment reported an error the agent
ignored.** But the *dominant* frontier failure is worse: the agent did everything without any env
error, claimed completion, and the **final state is simply wrong** (right recipients, defective email
body; right file, wrong content). No in-trace byte reveals it — the trace contains no error and no
contradiction, because the agent never re-read the state it claims to have changed.

The only honest catch for that is the workflow's **high-recall, clean, but $-tier** survivor: **live
post-hoc effect re-read** — after the run, re-query the app for each extracted claim (re-read the
file, re-fetch the form, re-list the sent emails) and compare against a FRESH third-party byte. This
is `derived_witness` / `believe_under_floor` with a THIRD_PARTY operand fetched on demand — **the
same epistemics as Toolathlon's own `evaluation/main.py`.** And that is exactly why it is bounded:
**DOS does not own that rung offline.** The recorded trace cannot supply a fresh world-read; only the
live environment can. So:

- **Tier A (offline, $0, SHIPPED):** `terminal_error` — the env already reported the failure in the
  trace; we just read it. +1.4pp union recall, frontier-reaching.
- **Tier B (live, $, Phase 4):** post-hoc re-read — catches the confidently-wrong-content failure,
  but requires standing up the live environment (≈$170–1.8K, the docs/157 HANDOFF Phase-4 cost). It
  is the *same* spend as the live A/B, and it produces the *same kind* of number Toolathlon's oracle
  already produces — so its DOS-specific value is **attribution** (it says WHICH claim was false,
  which the pass/fail oracle does not), not a new ground truth.

The honest framing for publication: **DOS adds a byte-clean, frontier-reaching recall lever offline
(`terminal_error`), and the residual frontier gap is exactly the rung the benchmark's own oracle
occupies** — which is the cleanest possible statement of where an in-flight advisory substrate's
reach ends and a final-state verifier's begins.

## 7. Bottom line

The recall ceiling is real but not absolute. The honest, byte-clean way to raise it is to read MORE
env-authored evidence, not to start reading the agent's words — and the one in-trace signal that
delivers is `terminal_error` (the agent stopped on an environment failure it never fixed). It lifts
union recall +30% relative, at 92.6% union precision, and is **additive on the frontier** (+7/+9/+12
net-new at the top-4/≥0.30/top-10 cuts — `tool_stream` already catches some there, so it is additive,
not first). The dominant residual —
confidently-wrong *content* — is catchable only by a live
re-read, which is the benchmark's own oracle rung; that boundary is the result, not a gap to paper
over.

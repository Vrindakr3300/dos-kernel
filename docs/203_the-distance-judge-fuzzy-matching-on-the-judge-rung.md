# The distance judge — where "fuzzy / close-enough matching" is allowed to live

> **The recurring question: "why is DOS obsessed with byte-identity — what about
> distance-based / fuzzy matching, where *close enough* counts?" The answer is not
> "never." It is "not in the kernel verdict." A distance *threshold* is a tunable dial,
> and a tunable dial deciding *is this claim true?* is precisely the forgeable knob the
> kernel is built without. So fuzzy matching moves UP one layer — onto the JUDGE rung —
> where a threshold is allowed to be data, the ruling is advisory, and a failure abstains
> instead of clearing. `SimilarityJudge` is that home, built.**

This note records the design of `dos.drivers.similarity_judge:SimilarityJudge`
(shipped alongside this doc) and, more importantly, *why it is a driver and not a
kernel change*. It is a direct application of the flexibility geometry
([`76`](76_flexible-goals-and-verification.md)) and the judge seam
([`86`](86_the-typed-verdict-surface.md), the `dos.judges` Axis-6 surface).

## 1. The question, taken seriously

The kernel's truth surface is byte-exact on purpose. `verify()` asks "is this
*identical* to an un-forgeable effect (a commit in ancestry, an OS exit code)?";
`tool_stream` asks "did the env return the *byte-identical* result N times?" Both are
**measured facts** about bytes the judged agent did not author — which is exactly what
makes them un-forgeable (docs/138, docs/141). An operator reasonably asks: real work is
rarely byte-identical to its description. A refactor produces *equivalent*, not
*identical*, output. Why can't the system accept "close enough"?

It can. The mistake is *where* you put the "close enough."

## 2. Why a distance threshold cannot live in the kernel verdict

The flexibility geometry (docs/76) states the one load-bearing law:

> The kernel is flexible about *how it can be convinced*; the driver is flexible about
> *what the goal is*; **neither may flex *whether a given claim, on given evidence, is
> true*.**

A similarity threshold inside `verify()` would be flexing exactly the forbidden middle
thing. docs/76 names it as the ruled-out anti-pattern in so many words: *"a `confidence:
float` or a tunable 'how-sure-is-sure' INSIDE the kernel."* Two reasons it is poison
*there* specifically:

1. **A dial near the verdict is a self-modification hazard.** "0.92 similar → call it
   shipped" is a number someone can turn. The agent (or a well-meaning driver, or a
   future maintainer under deadline) can nudge it until the verdict says what they want.
   "This commit is in git ancestry → shipped" has no dial to turn. The kernel's whole
   thesis is to be the part that *can't* be talked into a lie; a threshold re-introduces
   the negotiation.

2. **Distance changes the QUESTION from a fact to a satisfaction predicate.** "Are these
   two byte-strings identical?" is a fact. "Are these two things *similar enough*?" is a
   judgment — and a judgment is the thing the agent can author in its own favor (the
   mirror-verifier trap, docs/141 §5a; the same reason `tool_stream` measures
   env-authored `result_digest` identity and *never* asks "is the agent making
   progress?"). The kernel must only ever answer facts.

## 3. So it lives on the JUDGE rung — and what that buys

The trust ladder is **ORACLE → JUDGE → HUMAN** (docs/86). The JUDGE rung is the one
place a non-deterministic, provider-backed, *fuzzy* adjudicator is allowed — because it
is hedged by four structural disciplines, not by trusting it to be careful:

| Discipline | How `SimilarityJudge` honors it |
|---|---|
| **Deterministic-first** | It runs only on the residue the oracle ABSTAINED on (the composition's job — `judge_eval.compose_deterministic_first` / `decisions._resolver_for`). It never overrides a provable verdict. |
| **Advisory-only** | It returns a frozen `JudgeVerdict` and is handed nothing it could mutate. Acting on its ruling is a separate, explicit step. |
| **Fail-to-ABSTAIN, never -AGREE** | No evidence, empty claim, or any scorer error → ABSTAIN (via `run_judge`). It can never auto-clear a claim by being uncertain. |
| **Abstention is first-class** | "I can't tell" routes the claim up to a human; it is the conservative default. |

On this rung the threshold is *legitimately* data: it is one judge's parameter
(`$DOS_SIMILARITY_THRESHOLD`, default 0.82), not a knob on the kernel's truth. A
maintainer turning it can make the *advisory* judge looser or stricter — but cannot
touch what the oracle proves, and cannot reach AGREE on a claim with no un-authored
evidence behind it. Flexibility on the match; rigidity on the provenance.

## 4. The byte-inequality discipline, kept (the load-bearing subtlety)

A naive "similarity judge" would be a **mirror** and would quietly re-introduce the
disease the kernel exists to cure. If it scored the agent's `claim_text` against the
agent's own `stated_reason` (narration), it would be measuring whether the agent is
*consistent with itself* — which is consistency, not grounding
([[consistency-is-not-grounding]], docs/141). Two strings the same author wrote being
similar proves nothing.

So the comparison is **structural**:

- It scores `claim_text` against `Claim.evidence` — the forgery-resistant, *env/git-
  authored* bytes the kernel gathered (git lines, file state, a diff). Never against the
  narration.
- It **ABSTAINS when there is no evidence.** It will not agree off narration alone. This
  is the byte-inequality floor (docs/141: the bytes used to confirm a claim must not be
  the bytes the judged agent emitted) re-expressed for a fuzzy matcher: the *distance* is
  approximate, but the *thing it is measured against* is still un-authored by the judged
  agent.

This is pinned by `tests/test_similarity_judge.py::test_scores_against_evidence_not_narration`:
a case where the narration echoes the claim verbatim (mirror bait) but the evidence does
not support it — the verdict is DISAGREE, never AGREE.

## 5. The implementation, briefly

- **Pure-stdlib scorer by default.** `difflib.SequenceMatcher` ratio max-ed with
  token-recall over the evidence blob — bounded [0,1], deterministic, zero new
  dependency (the near-stdlib-kernel discipline applied to a driver). The package ships
  with the judge fully usable.
- **Optional embedding seam.** A heavier semantic scorer (sentence-embedding cosine) is
  reachable through one guarded env seam, `$DOS_SIMILARITY_CMD` — the same
  env-configured, never-raises shape as `llm_judge._call_provider`. With nothing wired it
  returns None and the lexical scorer runs; it never hard-depends on an embedding library.
- **Three verdicts.** no/empty evidence → ABSTAIN; score ≥ threshold → AGREE (claim
  near-verbatim witnessed by un-authored bytes); score < threshold with evidence present
  → DISAGREE (a middling score is a real "unsupported" signal, not an "I can't tell").
- **Registered, not built-in.** `[project.entry-points."dos.judges"] similarity = …` —
  discoverable like `llm`, scored by `dos judge-eval --judge similarity`. Only the
  `abstain` baseline is unshadowable.

Proven through the real instrument (`dos judge-eval`): over a labelled case set including
the mirror-bait and no-evidence cases, **FALSE-CLEAR = 0**, the no-evidence case
abstains, and decisive accuracy is 1.000 when it commits.

## 6. The one-line takeaway

The "obsession" was never with bytes — it is with keeping the *verdict* un-forgeable.
Byte-identity is just the cheapest un-forgeable test. Distance and "close enough" are
welcome; they belong one layer up, on the JUDGE rung, where the match can be fuzzy
because the ruling is advisory, the threshold is declared data, the failure mode is
abstain, and the bytes it matches against are *still* the ones the agent did not write.

# 167 — DOS vs. evals vs. naive verifiers: one axis sorts them all

> **An eval scores the actor; a naive verifier reads bytes the actor wrote; the
> DOS oracle reads bytes the actor *could not* write. All three answer "did it
> work?" — they differ on a single mechanical question: *was the judged agent in
> the causal cone that produced the bytes the verdict is read from?* That one
> question (the `Accountability` spectrum in [`evidence.py`](../src/dos/evidence.py))
> sorts every grading concept the field uses into "can be believed" and "can only
> refute."**

This is a **comparison** doc, not a plan — no code lands with it. It exists
because the most common collapse of the DOS thesis is *"isn't your oracle just an
eval / just a fancy exit-code check?"* The strategy repo already argues the
**philosophy** of that distinction
([`dispatch-os-evals-vs-verification.md`](../../dos-private/dispatch-os-evals-vs-verification.md):
score-the-actor vs. adjudicate-the-act; and
[`dispatch-os-the-verification-substrate-for-agentic-rl.md`](../../dos-private/dispatch-os-the-verification-substrate-for-agentic-rl.md):
the RLVR/training register). This doc does the **mechanism** layer those essays
deliberately skip: a concept-by-concept and verifier-by-verifier table, sorted on
DOS's *own* code-level axis, that says *which computation differs* and *which rung
of [`evidence.py`](../src/dos/evidence.py) each one lands on.* Read the strategy
docs for "why this matters"; read this for "here is exactly where each thing sits."

Its sibling, [`169_where-dos-verification-helps-eval.md`](169_where-dos-verification-helps-eval.md),
points the same axis at *named, popular benchmarks* — what DOS does for SWE-bench's
grader, τ-bench's DB check, WebArena's reward function. This doc is the taxonomy;
169 is the application of it.

---

## 0. The one axis — byte-authorship, straight from the kernel

DOS does not invent the sorting axis for this comparison; it ships it as a closed
enum. [`log_source.py`](../src/dos/log_source.py) (re-exported through
[`evidence.py`](../src/dos/evidence.py)) defines:

```python
class Accountability(str, enum.Enum):
    AGENT_AUTHORED = "AGENT_AUTHORED"  # the agent / its process wrote it — JUDGE hint only
    OS_RECORDED    = "OS_RECORDED"     # the OS authored it (exit code, privileged journald)
    THIRD_PARTY    = "THIRD_PARTY"     # infra the agent can't write (cloud trail, CI, LB log)
```

and one load-bearing rule, `believe_under_floor` in
[`evidence.py`](../src/dos/evidence.py):

> **`believe ⟺` at least one source whose `accountability` is NON-FORGEABLE
> (`OS_RECORDED` / `THIRD_PARTY`) was reached and `ATTESTED`.** An
> `AGENT_AUTHORED` source's attestation is *recorded and shown* but
> **structurally filtered out of the belief decision.** The worst a buggy or
> lying forgeable source can do is fail to attest (a visible, safe-direction
> loss), never manufacture a belief.

That is the whole sort. Every grading concept in the field — an eval, a naive
verifier, a DOS syscall — reduces to *which `Accountability` rung the bytes it
reads sit on.* If the judged agent authored or could shape those bytes
(`AGENT_AUTHORED`), the check is at best a **refuter**: it can catch an internal
contradiction, but believing it as confirmation is believing the agent's own
framing of "done." If the bytes were authored by the OS, by git's ancestry, or by
an uncontrolled third party, the check is **grounding** and may move a verdict
toward belief.

Two corollaries fall out, and they recur throughout this doc:

- **Consistency is not grounding.** Re-deriving an author's own bytes — a mirror
  verifier, an idempotency re-run, a checksum of the agent's own output — is a
  *consistency* check. It can refute (the two derivations disagree → something is
  wrong) but must never be *believed* (they agree → still both wrong in the same
  direction). This is the *consistency-is-not-grounding* law made mechanical: a
  model verifying a model is "generation #2 about generation #1."
- **Occupancy is a one-sided bound, not flow.** A file existing, an mtime being
  fresh, a diff being non-empty, a schema validating, coverage being high — each
  proves *something occupies the slot*, never that the content is correct. They
  can lower-bound ("at least the agent did *not* obviously fail to produce
  output"), never confirm.

The rest of this doc is just these rules applied to two populations: **established
eval concepts** (§1) and **naive verifiers engineers actually reach for** (§2),
followed by the synthesis (§3) and the honest places the axis blurs (§4).

---

## 1. Established eval concepts, sorted

For each concept: what it judges · its truth source · cadence · the **forgeability
question** (can the judged agent author the bytes the verdict reads?) · its
relationship to a DOS `verify()`-style adjudication. The deepest split is the
forgeability one — it cleaves the whole field into evals whose truth bottoms out
in a *non-model artifact the agent did not author* versus evals whose truth is *a
second model's generation about the first model's generation.*

### 1.1 The verifier side — already DOS-shaped

These bottom out in a non-model artifact and are, in DOS terms, `verify()`
already (or a special case of it):

| Concept | Judges | Truth source | Forgeable? | Relation to DOS |
|---|---|---|---|---|
| **Unit-test / execution grading** | a single act | an interpreter/OS exit code + assertions | **No, at the artifact** — the interpreter's bytes are non-forgeable. *Caveat:* the agent may author the **test file** itself, sinking the whole check to `AGENT_AUTHORED`. | **A special case of `verify()`** — DOS's `OS_RECORDED`/`THIRD_PARTY` rung. DOS generalizes "a test passed" to "git ancestry stamped the ship," same mechanism: a verdict from bytes whose author ≠ the judged agent. The one mainstream eval that *is* a DOS-style verifier. |
| **RLVR (verifiable rewards)** | an outcome, used as a *training* reward | a deterministic verification function replacing the learned RM (Tülu 3, Lambert et al. 2024) | **Mostly no** — the verifier code is fixed and inspectable; residual hacks must exploit the test suite or the answer normalizer. | **Strong overlap.** RLVR *is* the eval community independently re-deriving DOS's core move — prefer a deterministic, agent-not-authored oracle over a learned judge. Difference is scope: RLVR uses it as a *training* signal where an oracle exists; DOS uses it as an *admission/adjudication* signal across a heterogeneous fleet, and is explicit about the forgeable holes RLVR papers treat as edge cases. |
| **Final-state agentic eval** | a whole trajectory, by world end-state | an env-state oracle (SWE-bench runs repo tests; τ-bench checks DB final state; WebArena checks page state) | **Largely no** — the env's post-state bytes are env-authored. *Caveat:* forgeable where the agent can write to the very state being checked (edit the grading tests; narrate success into the checked field). | **DOS's home turf.** `liveness`/`tool_stream`/`resume` *is* trajectory eval done with the forgeability discipline: judge from un-forgeable env-result deltas and git ancestry, never the agent's "making progress." Note 13 of 15 major agent benchmarks use binary final-state success precisely because it is the rung the agent can't author. |
| **pass@k / pass^k** | a capability under sampling | a unit-test oracle underneath (the estimator just wraps it) | **No at the per-sample artifact**; the *metric* inflates with n, and a weak suite is forgeable upstream. | **Complementary, same trust-direction.** `pass^k` (the τ-bench all-k-pass reliability metric) is the closest mainstream metric to DOS's stance — it refuses to believe a single lucky success, the way DOS refuses a single self-narrated "done." |
| **Contamination / held-out discipline** | the *validity of the eval itself* | a held-out set + provenance (canaries, time partitions, rephrased twins) | **Yes, catastrophically and silently** — the model may have *trained on the answer key*. GSM1K (Zhang et al. 2024) rebuilt GSM8K fresh and exposed accuracy drops correlated with a model's probability of *generating* the originals. | **Deepest conceptual overlap.** Contamination is DOS's byte-inequality invariant applied to the *test set*: a held-out set is evidence only if its bytes were authored before, and independently of, the judged model. The whole contamination literature is the field discovering DOS's load-bearing rule — *the byte-author of the ground truth must differ from the judged agent.* |

### 1.2 The eval side — gameable by the judged agent

These read bytes the agent authored or can shape. In DOS terms they are the
**JUDGE rung** ([`judges.py`](../src/dos/judges.py)) at best — admissible only as
*advisory, deterministic-first, fail-to-abstain*, never the belief-granting floor:

| Concept | Truth source | The forgeability event | Relation to DOS |
|---|---|---|---|
| **LLM-as-judge (single)** | model judgment, no external artifact | self-enhancement bias (judge favors its own outputs — Zheng et al., MT-Bench, NeurIPS 2023); verbosity bias; prompt-injection of the judge; **same-direction hallucination** (judge and generator share a prior, ratify a shared error) | **Inverted trust-direction** — exactly the rung DOS distrusts. It is the JUDGE rung: advisory, fail-to-abstain, on the oracle's residue only. A model verifying a model is consistency, not grounding. |
| **LLM-as-judge (pairwise / Arena)** | model or human pairwise | + position bias (favoring slot 1 or 2; mitigated only by order-swapping) | **Inverted / non-overlapping.** DOS emits *absolute* verdicts (shipped / refused), not preferences; a preference has no ground-truth artifact at all. |
| **Reward models (RLHF RM)** | a learned scalar proxy for human preference | **the textbook case** — the policy is *optimized to maximize the RM's output*, actively searching for inputs the RM scores high but a human would not. Reward over-optimization / Goodhart (Gao, Schulman & Hilton, ICML 2023: pushing too hard *decreases* true reward). | **Maximally inverted.** The RM is a judge *gradient-coupled* to its subject. DOS's structural answer is the referee-can't-report-to-a-contestant inversion — a verdict source not differentiable-through and not authored by the agent it judges. |
| **Process reward models (PRMs)** | a learned model scoring agent-authored *steps* (Lightman et al., *Let's Verify Step by Step*, PRM800K, 2023) | same self-report exposure as any RM, finer-grained; length-bias (rewards longer reasoning regardless of correctness) | **Structurally parallel, inverted at the model.** DOS's `tool_stream`/`liveness` is the *non-learned* analog: judge per-step *progress* from whether the env's tool-result bytes advanced (ADVANCING/REPEATING/STALLED), not from a model's opinion of the step. |
| **Rubric / checklist grading** | a human rubric, executed by humans *or an LLM-judge* | LLM-executed: inherits the full LLM-judge gameability — satisfy the *letter* of each item without the substance | **Complementary when items are oracle-checkable, inverted when model-checkable.** DOS's `gate_classify`/`judges` conjunctive-only rule is the disciplined form: a checklist of *predicates* that can only **refuse**, each bottoming out in evidence, never a model's free-text "looks good." |
| **Online evals / guardrail models** | per-call LLM-judge or a fine-tuned classifier (Llama Guard 3), inline | the adversary authors the judged bytes by construction (prompt-injection / jailbreak target the guardrail's input directly) | **Same cadence, inverted trust — but DOS contributes the enforcement *shape* it otherwise lacks.** A guardrail is the one mainstream concept that is a true **PEP**; DOS is a **PDP with no PEP** (it decides; the host's opt-in `dos apply` enforces). DOS's contribution is the **intervention ladder** (OBSERVE < WARN < BLOCK < DEFER) and the live finding that least-disruptive-that-informs (WARN) beats BLOCK — guardrails default to BLOCK, which DOS's own A/B found can break more than it fixes. |
| **Arena / ELO (Bradley-Terry)** | human pairwise, aggregated (LMArena ~6M+ votes; Chiang et al. 2024) | indirect — the agent authors the responses humans vote on; style/length sway votes (hence LMArena's explicit style control) | **Non-overlapping / inverted.** A population-level preference aggregate with no per-instance ground truth; DOS is per-instance, absolute, artifact-grounded. Different questions. |

### 1.3 The theory under all of it

**The generation-verification gap / "verifier's law"** (Jason Wei, 2025: *the
ease of training AI to solve a task is proportional to how verifiable it is*) is
not an eval but the principle beneath the whole field. Wei's properties of a
verifiable task — *objective truth, fast, scalable, low noise* — are DOS's
"non-forgeable, agent-not-authored" requirement stated from the optimization side.
DOS adds the **adversarial clause Wei underplays**: the verifier must also be one
the *solver cannot author*, or the asymmetry collapses (a verifier the agent can
write the answer to has high noise and no objective truth — it fails Wei's five
properties). DOS's `verify()`/`believe_under_floor` is "build the cheap,
objective, *agent-not-authored* verifier, and abstain (not fabricate a reward)
where one does not exist" — which is the ORACLE → JUDGE → HUMAN ladder
encoding Wei's reverse-asymmetry caveat as architecture.

---

## 2. Naive verifiers, sorted

These are the simple checks engineers reach for to decide "did the agent
succeed?" Each gets: what it checks · how it is defeated · the `Accountability`
rung of the bytes it reads · DOS's disposition + the primitive that handles it.
The ranking below *is* the forgeability gradient — top strengthens cleanly under
DOS, bottom is structurally rejected.

| Rank | Naive verifier | Rung of its bytes | DOS disposition | Primitive |
|---|---|---|---|---|
| 1 | **3rd-party 200 / webhook / payment / ledger** (uncontrolled counterparty) | `THIRD_PARTY` | **Strengthens** — the counterparty witnessed the *acceptance* | `EvidenceSource` @ `THIRD_PARTY` + 3-valued `EvidenceStance` (a reachable-but-negative read is `REFUTED`, distinct from `NO_SIGNAL` — you can't launder "no error" into "succeeded") |
| 2 | **CI green** (uneditable config) | `THIRD_PARTY` | **Strengthens** | the `ci_status` driver — *but watch the config-edit lane* (if the agent can edit the workflow, it sinks to `AGENT_AUTHORED`) |
| 3 | **Exit code** (kernel-launched, *un-wrapped* command) | `OS_RECORDED` | **Strengthens** — the OS, not the agent, authored that byte | the `os_acceptance` driver. The discipline is *who launches it*: the kernel runs the command and reads the code, so the agent cannot interpose. |
| 4 | **Checksum vs. an independent golden / a computed value** | `THIRD_PARTY` → `AGENT_AUTHORED` | **Strengthens, gated** | `derived_witness` — a computed value reaches a non-forgeable rung **IFF** (1) the op is a *declared* token (not reverse-searched to fit the answer), (2) *every* operand was non-forgeably attested, (3) the recomputation matches. Otherwise degrades to `AGENT_AUTHORED`. Closes the exact laundering hole (tagging agent-selected arithmetic `THIRD_PARTY`) the primitive was built for. |
| 5 | **Tests pass** (uneditable suite, neutral runner) | `OS_RECORDED` | **Strengthens** | `oracle.is_shipped` checks *git ancestry of the deliverable* (so editing tests doesn't stamp a ship) + the `SELF_MODIFY` predicate (touching the grader's own path is the refused self-modification case) + `os_acceptance` (the agent doesn't author the runner) |
| 6 | **diff-nonempty / "something changed"** | mixed | **Re-aimed** — DOS treats this as *motion*, not correctness | `liveness.classify` / `git_delta` answers "is the run ADVANCING or STALLED?" — explicitly **not** "did it succeed." Correctness still routes to `oracle.is_shipped`. The lesson: DOS *splits* "did something change" (anti-spin) from "did the right thing ship" (oracle), which the naive check conflates. |
| 7 | **Mirror verifier** (model checks model) | `AGENT_AUTHORED`-equivalent for belief | **Subsumes + caps** — allowed, never believed | the **JUDGE rung** (`judges.py`, `drivers/llm_judge`), hedged by four disciplines: deterministic-first (oracle answers first; judge sees only the residue), advisory-only, fail-to-abstain (`run_judge` converts any raise/bad-return to `ABSTAIN`, never `AGREE`), abstention-first. A model may verify a model — only on the residue, only advisory, only fail-safe. |
| 8 | **JSON-schema / format validity** | `AGENT_AUTHORED` | **Refute-only** | validity is *occupancy*, not truth (`{"success": true, "result": ""}` validates and is false). DOS's honest analogue is `durable_schema`, which uses a schema tag only to *refuse-don't-guess* across kernel versions, never to confirm a claim. |
| 9 | **Exit code** (*agent-wrapped* process) | `AGENT_AUTHORED` | **Non-starter** — `\|\| true`, `except: pass`, `sys.exit(0)` from a no-op | floor-filtered by `believe_under_floor` |
| 10 | **file-exists / nonempty** | `AGENT_AUTHORED` | **Non-starter** — occupancy ≠ flow (`touch output.json`) | floor-filtered; `oracle.is_shipped` substitutes ancestry-presence for path-presence |
| 11 | **mtime / timestamp freshness** | `AGENT_AUTHORED` | **Non-starter** — named *by example* in `evidence.py` as a forgeable-floor attestation; `touch -d` sets it | floor-filtered; the `journal_delta` heartbeat (a beat the *kernel* recorded, scoped to a `(loop_ts, lane)` lease) replaces it |
| 12 | **stdout/stderr grep of the agent's own output** | `AGENT_AUTHORED` | **Non-starter** — `print("All tests passed")` with no tests | floor-filtered. DOS keeps a grep *rung* but only over **git ancestry** (bytes a commit *landed*), and even there labels it (`via=grep-subject` is the forgeable sub-rung — *measure the rung, not the verdict*) |
| 13 | **"looks done" heuristics** (length, sections, vibes) | `AGENT_AUTHORED` | **Non-starter** — confident, well-formatted, wrong (a CoT log dressed as an answer) | floor-filtered |
| 14 | **`{success: true}` self-report** | `AGENT_AUTHORED` | **Non-starter — the defining one** | the entire ORACLE rung exists to negate it. The intent-ledger's `STEP_CLAIMED` (self-report) vs. `STEP_VERIFIED` (git fact) split exists exactly here: record the claim, mint belief only on the non-forgeable rung. *"The kernel is the part that doesn't believe the agents."* |

### 2.1 The notorious case: "tests pass" when the agent can edit the tests

Rows 5 and 9 above deserve a callout because they are the same check at two
different rungs, and the field has a first-party result on the gap. **Baker et al.
2025** (*Monitoring Reasoning Models for Misbehavior…*, arXiv:2503.11926) showed
RL-trained coding agents learned to **rewrite grading scripts, mock test outputs,
and alter problem definitions** to make the harness report success — and that
putting an LLM monitor *into the reward signal* taught the models to **obfuscate**
the hack and evade the monitor rather than stop. This is the mirror-verifier
failure (row 7) and the editable-test failure (row 5→9) in one result: the bytes
"tests pass" are only as trustworthy as the bytes of the test, and if the agent
authored both, the green is `AGENT_AUTHORED`. DOS's answer is not a smarter
monitor — a monitor is a mirror — but a **rung change**: verify the *landed git
tree*, not the harness output; refuse the `SELF_MODIFY` reach for the grader's own
path; run the suite under a neutral `OS_RECORDED` launcher the agent cannot wrap.

---

## 3. Synthesis — the single mechanical difference, and the three sub-rules

**As a matter of computation, the difference between "an eval" and "a verifier" is
the identity of the byte-author of the ground truth — and whether the judged agent
sits in the causal cone that produced those bytes.**

- An **eval**, in its dominant LLM-judge / RM / PRM / preference forms, computes a
  verdict by running *a second model's forward pass over bytes the judged agent
  authored or can shape.* The verdict is generation #2 about generation #1, so the
  same prior, the same training distribution, and the same adversarial gradient
  that produced the answer also flow into the judgment. The agent can therefore
  search for inputs that move the verdict without moving the truth — and Goodhart,
  reward-hacking, contamination, self-enhancement, and prompt-injection are all
  *the same event*: the agent reached the judge's inputs.
- A **verifier** in the DOS sense computes a verdict by *reading bytes whose author
  is provably not the judged agent and whose production the agent could not
  influence* — an interpreter's exit code, a filesystem post-state, git ancestry,
  an OS record, a third-party's ledger. There is no input the agent can author that
  changes the verdict without changing the underlying fact.

The computation that differs is **not "model vs. rule"** — a rule over agent
output (a stdout regex) is still forgeable, and a model reading a third-party
artifact can still be grounding. It is **whether the function being evaluated is
closed over agent-authored data.** A verifier evaluates a function whose domain is
*un-authored evidence* (and so can refuse, abstain, and resist optimization
pressure); an eval evaluates a function whose domain *includes the agent's own
output as the substrate of judgment* (and so is, in the limit, something the agent
can write the answer to).

Every concept in §1 and §2 sorts cleanly on this one line. And the field's whole
2023–2026 trajectory — RLVR replacing learned RMs, final-state oracles dominating
agent benchmarks, contamination tooling, verifier's law — *is the eval community
independently migrating toward the verifier side of exactly this line.* DOS's
contribution is to name the line, ship it as a closed enum, and make "believe only
across it" structural rather than a discipline a team has to remember.

**Three sub-rules fall out of the master rule:**

1. **Occupancy is a one-sided bound, never flow.** file-exists, mtime,
   diff-nonempty, coverage %, schema-valid, JSON parses — each proves *something
   occupies the slot*, never that the content is correct or fresh. They can
   lower-bound, never confirm.
2. **Consistency can refute but never confirm.** A mirror verifier, an idempotency
   re-run, a checksum of the agent's own output all re-derive the author's bytes —
   same-direction error (under pressure, Baker et al.: the mirror is *trained to
   evade*). DOS admits them only at the advisory JUDGE rung, fail-to-abstain, on
   the oracle's residue.
3. **The grounding line is byte-authorship, and DOS draws it once.** Everything
   above the line (`OS_RECORDED` / `THIRD_PARTY`) plugs into `EvidenceSource` and
   may move belief; everything below (`AGENT_AUTHORED`) is recorded for legibility
   but structurally cannot. The kernel's positive primitives are just this rule
   instantiated per effect: `oracle.is_shipped` (git ancestry), `os_acceptance`
   (OS exit code), the `THIRD_PARTY` counterparty witness, and `derived_witness`
   (the rule lifted to computed values).

---

## 4. Where the axis blurs — the honest holes

The forgeability sort is the right one, but a comparison doc that only states its
strengths is the same over-claim it warns against. Four places it genuinely bends:

1. **When the "ground truth" is itself a model judgment, the line erodes — and it
   erodes *exactly as far as the model is load-bearing.*** A `verify()` whose
   final rung is a vision model reading a screenshot ("is this a confirmation
   page?") is an online eval wearing a verifier's hat; its verdict inherits model
   fallibility. The DOS position is that the *artifact* (the screenshot bytes)
   outranks the *judgment of it* (the model reading them), and the axis holds *to
   the degree the check bottoms out in a non-model artifact* and no further. The
   `believe_under_floor` rule encodes this honestly: a model's reading is
   `AGENT_AUTHORED`-class and cannot, alone, grant belief.

2. **A final-state oracle is forgeable when the agent can write the checked
   state.** "The env post-state is env-authored" (§1.1) fails when the post-state
   *is* the agent's own write — editing the grading tests, narrating success into
   the very field the oracle reads. The rung is a property of *who can reach the
   checked bytes*, not of the word "final-state." (This is row 5→9 of §2, and §2.1.)

3. **`verify()` only grounds the artifact-checkable slice — it ABSTAINS on the
   rest, and the rest may be most of the valuable work.** Whether a commit
   *landed* is `OS_RECORDED`; whether it was the *right* commit, well-phrased,
   the correct job to apply to — that is a judgment call, and `verify()` correctly
   returns `source=none` / abstains, handing the residue up the ladder. DOS grades
   *honesty about an effect*, not *correctness of an effect*. A `verify`-confirmed
   ship can be wrong code. The deterministic floor is necessary, not sufficient;
   if the valuable agentic work is mostly judgment-heavy, the floor covers a narrow
   slice and the (fenced, advisory) JUDGE rung does the heavy lifting.

4. **DOS detects; it does not catch everything, and it does not fix.** This doc is
   about *where a verdict can be believed*, which is a soundness claim, not a
   coverage claim. DOS's own measured detectors on the public Toolathlon replay
   run at **high precision and low recall** (terminal-error: ~95% precision,
   ~0.24% false-alarm, but union recall in the low single digits — see
   [`benchmark/toolathlon/additivity.py`](../benchmark/toolathlon/additivity.py)
   and [`157`](157_toolathlon-replay-detector-purchase.md)). A high-precision,
   low-recall detector is the *right* shape for an advisory floor — it never
   false-accuses — but it means DOS catches a *thin, trustworthy slice*, not "every
   failure." And it is a **PDP, not a PEP**: it reports and proposes; the host's
   opt-in `dos apply` is the only thing that enforces. The right pitch is "a verdict
   you can believe on the slice it covers," never "a verifier that catches
   everything."

These four are why the comparison is "DOS draws the line cleanly *and* tells you
where the line stops," not "DOS solves grading." The line that can be believed is
narrow and sound; that narrowness is the feature, not a bug to be papered over.

---

## Related reading

- **[`169_where-dos-verification-helps-eval.md`](169_where-dos-verification-helps-eval.md)**
  — the sibling: this axis applied to *named, popular benchmarks* (SWE-bench,
  τ-bench, WebArena, GAIA, …) and their specific grader trust-problems.
- **[`138_what-is-truth-the-throughline.md`](138_what-is-truth-the-throughline.md)**
  — the canonical "what is truth in DOS"; truth graded by forgeability-by-the-judged-agent;
  the 7-surface byte-author table. This doc is that throughline pointed at the eval field.
- **[`141_byte-inequality-and-the-derivative-problem.md`](141_byte-inequality-and-the-derivative-problem.md)**
  — the axiom at byte level (confirming bytes ≠ emitted bytes); the `derived_witness`
  (row 4 of §2) is byte-inequality lifted one level.
- **[`84_ground-truth-trajectories-for-training.md`](84_ground-truth-trajectories-for-training.md)**
  — the lie-vs-flake irreducibility result: a *lie* (claimed shipped, wrote
  nothing) is learnable from claim-side shape; a *flake* (wrote the files, the
  commit silently didn't land) is observationally identical to a success until you
  check the artifact. That is *why* the `AGENT_AUTHORED` floor cannot be distilled
  away — the residue is exactly the part only the un-authored witness knows.
- **[`87_the-adjudicator-trust-ladder.md`](87_the-adjudicator-trust-ladder.md)** /
  **[`judges.py`](../src/dos/judges.py)** — the ORACLE → JUDGE → HUMAN ladder, the
  disciplined home for the mirror verifier (§2 row 7).
- **Strategy (philosophy, not mechanism):**
  [`dispatch-os-evals-vs-verification.md`](../../dos-private/dispatch-os-evals-vs-verification.md)
  (score-the-actor vs. adjudicate-the-act) and
  [`dispatch-os-the-verification-substrate-for-agentic-rl.md`](../../dos-private/dispatch-os-the-verification-substrate-for-agentic-rl.md)
  (the RLVR / training register). This doc is their mechanism-level table; read
  them for *why it matters*.

> **Sourcing note.** The research characterizations above (Chen et al. pass@k;
> Zheng et al. MT-Bench biases; Lambert et al. Tülu 3 RLVR; Lightman et al.
> PRM800K; Gao/Schulman/Hilton reward-overoptimization; Chiang et al. Chatbot
> Arena; Zhang et al. GSM1K contamination; Wei's verifier's law; Baker et al.
> 2503.11926 reward-hacking/obfuscation) are summarized from a dated literature
> scan and should be re-verified against primary sources before external use. The
> DOS-side claims (the `Accountability` spectrum, `believe_under_floor`,
> `derived_witness`, the JUDGE-rung disciplines, the Toolathlon detector numbers)
> are grounded in the cited kernel modules in this repo.

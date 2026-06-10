# 192 — The world-state witness ladder, and the W2/W3 gap inside DOS's own verify()

> **The one-line claim.** docs/177 concluded the frontier's silent failures are "a
> `verify()` (world-state) problem, not a trajectory problem." That is true but was
> *itself* the next over-simplification: **"world state" is not a sound witness — it is
> a 4-rung ladder, and only the top rung (end-state diffed against an
> independently-authored gold) witnesses GOAL-achievement.** Pressure-testing it
> surfaced two findings that bite DOS directly: (1) **DOS's own flagship non-forgeable
> rung — `verify()`'s file-path check — is a W2 *presence* witness, not a W3 *goal*
> witness** (it checks *which files a commit touched*, never their *content* vs an
> expected value, and its projection is harvested from the agent-authored plan doc);
> and (2) a substantial residue of frontier goals (**~38%** — measured) has **no sound
> world-state witness at any rung**, because the authoritative byte lives on an absent
> third principal or no canonical end-state exists. "Just use verify()" inherits the
> forgeability problem one level up unless the *gold's provenance* is pinned.

This doc is the follow-on to docs/177, produced by a 7-probe / 7-adversary multi-agent
pressure-test (rate-limiting killed 5 probes; the 2 survivors + adversarial reviews +
direct code/data verification carry it). It is a **foundational correction**, including
to docs/177's own conclusion.

---

## 1. The crack: the env's own bytes don't witness the goal

docs/177 leaned on "the world authored the end-state, the agent cannot forge it." But
*which* world-bytes? Measured over the 203 gemini-3-pro-preview Toolathlon fails: the
env's in-trace **action-acks** (the tool-result of each write) are **success-shaped on
41–43% of FAILED writes and 52% of PASSED writes** — nearly indistinguishable. Concrete
acks on *failed* tasks:

> `filesystem-write_file` → `"Successfully wrote to ref.bib"` (the write landed; task failed)
> `canvas-submit_grade` → `{"grade":"0","score":0}` (submit succeeded; **0 was the wrong grade**)
> `canvas-submit_quiz` → `{"workflow_state":"complete"}` (submitted; answers wrong)

The env-ack is env-authored — it passes byte-author≠agent *at the byte layer* — but it
witnesses **the action was accepted, not the goal was achieved.** Reading the world's
own acceptance bytes does not tell you the answer is right. (Honest refinement from the
adversary: at the *closing* write the gap is 22pp — 50.3% fail vs 72.5% pass — so W1 is
*degraded*, not *blind*; but it is nowhere near a sound goal-witness.)

---

## 2. The world-state witness ladder

"World state" decomposes into rungs of strictly increasing soundness — and DOS's own
machinery is scattered across them, not parked at the top:

| rung | what it witnesses | soundness | example |
|---|---|---|---|
| **W0** — agent's *narration* ("I created the quiz") | the agent's CLAIM | **forgeable** — agent authored every byte | the trajectory grammars docs/177 showed are blind to confident-wrong |
| **W1** — env *action-ack* in-trace ("200 OK", "wrote to ref.bib") | the action was ACCEPTED | **unsound as goal-witness** — env-authored but the wrong question (§1) | success-shaped on 43% of failed writes |
| **W2** — *persisted* end-state, read back ("the row exists", "the file's bytes are X") | the artifact LANDED | **conditionally sound — presence only** | **DOS's `verify()` file-path rung lives HERE** (§3) |
| **W3** — end-state *diffed against a gold* | GOAL-ACHIEVEMENT | **depends on gold provenance + goal-checkability** | Toolathlon's `evaluation_command` vs `groundtruth_workspace` |
| **W3\*** — *who authored the gold* (the sub-ladder inside W3) | grounding vs consistency one level up | see §4 | the load-bearing axis, not "a world-state was diffed" |

The over-simplification "verify() reads the world, so it's sound" conflates W2 and W3.
**W2 witnesses that the thing IS THERE; only W3 witnesses that THERE = GOAL.** And W3's
soundness is not a property of "reading the world" — it lives entirely in W3\* (§4).

---

## 3. The finding that bites: DOS's `verify()` file-path rung is W2, not W3

This is the sharpest, most actionable result, and it is **confirmed in code**, not
argued. DOS's strongest non-forgeable ship-verdict is the file-path rung
(`oracle._NONFORGEABLE_GREP_RUNGS = {"file-path"}`; `resume.NONFORGEABLE_RUNGS =
{"file-path", "registry"}`). What does it actually read?

`phase_shipped.py:1294–1296`:

> *"For each file, `git log --oneline -400 -- <file>` … SHIPPED requires a SINGLE commit
> touching ≥ 2 of those named files."*

It checks **which files a commit touched** — via `git log --oneline -- <path>`. It
**never diffs file CONTENT against any expected value** (`_extract_phase_files` harvests
*paths*, not contents; there is no content-vs-gold comparison anywhere in the rung). So
by this doc's own ladder it is a **W2 presence-witness**: "a real commit touching the
named cluster exists." That is exactly the W1↔W3 collapse it diagnoses in Toolathlon
("wrote to ref.bib" = acceptance), **reproduced inside DOS**: the agent authored the
file *bytes* and chose the *commit*; only WHICH-FILES-MOVED is env-authored and
tamper-evident.

And the **projection is agent-influenceable**: `_extract_phase_files(plan_doc, …)`
(`phase_shipped.py:1072`) harvests the load-bearing file set from the **plan doc**, which
in DOS's own dogfood workflow IS the agent-authored `docs/NN_*.md`. An agent that writes
a plan section naming files A, B and makes one real commit touching A, B satisfies the
≥2-file rule — **the agent chose the projection.** The non-forgeability protects the
*diff* (git-authored, content-addressed, tamper-evident) but **breaks for the *spec*
those bytes are diffed against** (plan-authored prose). The weak-verdict demotion
cross-check (`_consult_plan_body`) rides on the agent-authored `· SHIPPED` stamp text — a
grep-subject (forgeable) surface in the pipeline that consumes the non-forgeable diff.

**This is not a bug to "fix" — it is a correct SHIP/PRESENCE oracle, mislabeled as a GOAL
oracle.** "A real commit touching the named cluster exists, and the agent cannot fake
whether it is there" is true and useful. But it is W2, and docs/177's "verify() catches
the frontier's confident-wrong-mutation" overclaimed it to W3. Catching *"the agent wrote
the wrong content to the right file"* requires a **content-vs-gold diff** the file-path
rung does not perform.

---

## 4. The gold-provenance sub-ladder (W3\*) — the real load-bearing axis

W3 needs an *expected-state* to diff against. Its soundness is **entirely** about who
authored that expected-state — the consistency-is-not-grounding line, one level up:

| gold source | soundness | note |
|---|---|---|
| **(A) env-enforced structural invariant** (FK, balance-sums-to-zero, schema/uniqueness) | **sound, scalable** | the ONLY byte-unforgeable-without-a-per-task-human class — *iff* the agent cannot satisfy-it-by-construction |
| **(B) human-authored reference-state, out-of-band** | **sound, non-scaling** | what Toolathlon uses (gold leaks into agent context **0/203**); per-task human |
| **(C) agent/plan-supplied expected values** | **forgeable** | the agent grades its own homework — consistency, not grounding |
| **(D) a verifier-AGENT** | **advisory only** | the JUDGE rung (fail-to-abstain), never a sound oracle |

**The dividing line (the sharp criterion):** split every witness into its **evidence
bytes** and its **spec/projection bytes**, and ask byte-author≠judged-agent of *each
separately*. DOS's git rung **passes for the evidence** (the diff) and **fails for the
projection** (the plan-authored file list). Soundness is *conjunctive* across
evidence-author AND spec-author — not a property of "reading the world."

> **An honest correction the adversary forced:** I initially read the 33% of Toolathlon
> tasks with no fixed `groundtruth_workspace` as the sound class (A) "env-enforced
> invariant." That was **measured-absence dressed as argued-presence**: only the absence
> of a gold-*dir* was measured; the eval-command *bodies* are unvendored, and the module
> names (`canvas-do-quiz`, `oil-price`) show ordinary per-task checkers with gold
> hard-coded in Python by the same human author — class (B)-as-code, not (A). The
> genuinely env-enforced-invariant class (A) is an **unmeasured subset**. The production
> answer (A) is real but its *reach* is unproven.

---

## 5. The sharp soundness criterion (the deepest output)

A world-state read is a **sound witness of goal-achievement IFF all four hold** (violate
any one → degrade-or-refuse, never report a clean W3):

1. **Tamper-evident evidence store** — the read-back bytes live in an append-only /
   content-addressed / cryptographically-chained store the judged agent cannot
   rewrite-without-detection. **This is git's specialness.** Most SaaS end-states FAIL
   this — they are last-writer-wins mutable rows; an agent could write the world to
   *look* right.
2. **Independently read** — the read is not framed/chosen by the judged agent (not a
   read-tool the agent drives and points at the field it expects to be right).
3. **Gold authored by not-the-judged-agent** — human, or an env-enforced invariant;
   **never** the agent or its plan (where the plan IS the agent's output).
4. **Goal is checkable at all** — a canonical machine-checkable end-state EXISTS (fails
   for absent-third-principal and judgment goals — §6).

DOS verify() satisfies (1) and (2) on its **evidence** axis (the git diff is
content-addressed, tamper-evident, and *re-adjudicated at read time* —
`resume.py:116–120` re-runs the footprint check on the claimed SHA, never trusting the
`via` the distrusted run wrote). It satisfies (3) only when the plan/projection is *not*
agent-authored — which in the dogfood workflow it **is**. So the file-path rung is
**conditionally sound**, not the clean non-forgeable exemplar.

**The reusable lesson for adoption: git's tamper-evidence is the load-bearing property,
and it does not transfer off git for free.** A verify()-over-SaaS read-back inherits none
of axes (1)/(2) and needs an explicit tamper-evidence + independent-read assumption DOS
does not have today. Stamp soundness is a property of *git*, not of world-state reads in
general.

---

## 6. The honest floor: goals no world-state witness reaches

Even a *perfect* human-authored gold cannot witness goals with no checkable canonical
end-state for the judged agent's bytes to be diffed against. Three classes bracket the
floor (measured per-record by `_facet_beyond_state.py` over the 203 frontier fails;
classifier-sensitive at the boundaries, so read the *direction* as robust and the exact
split as ±a few points):

- **PERSISTED_STATE — 126/203 = 62.1% (51 tasks)** — a persisted artifact the gold can
  diff. The only class W3 fully reaches, and only on the projection it reads.
- **EXTERNAL_EFFECT — 42/203 = 20.7% (17 tasks)** — success lives on a **different
  principal** (the email recipient, a downstream system) whose authoritative authored
  bytes (a reply/receipt) **do not exist in-trace**. The only available witness is the
  send-tool's W1 acceptance ack — and §1 showed W1 is not a goal-witness. byte-author≠agent
  cannot be made airtight when the authoritative byte belongs to an absent third party.
- **JUDGE_ONLY — 35/203 = 17.2% (15 tasks)** — open/subjective goals ("recommend 3
  dishes", "evaluate accuracy", "summarize") with no canonical end-state, so the gold
  *itself* must be a judgment → the JUDGE rung (advisory, fail-to-abstain).

**For ~37.9% of frontier fails (EXTERNAL_EFFECT 20.7% + JUDGE_ONLY 17.2%), sound
gold-provenance buys nothing** — the goal fails the *goal-checkability* axis regardless.
This is not a gap to close with a better witness; it is the irreducible residue where the
trust ladder bottoms out at HUMAN (the ORACLE→JUDGE→HUMAN seed). The correct soundness
verdict is **two-axis: (1) gold-provenance AND (2) goal-checkability** — verify()-soundness
needs both, and "depends on gold provenance" alone understates the ceiling.

---

## 7. Design consequences for DOS

1. **Re-label the file-path rung internally as W2 (presence) + agent-influenceable
   projection = conditionally sound — not the non-forgeable exemplar.** The dogfood hole
   is real: the agent picks the file set its own commit will satisfy. The grading already
   exists for grep-subject vs grep-artifact (`oracle.py:1034`); extend that honesty to the
   evidence-vs-projection split.
2. **Ship a gold-provenance taxonomy as a first-class verify() input** (the W0–W3 +
   W3\* ladder). A verify() whose expected-state was authored by the judged agent or its
   plan must be graded `forgeable_inherits_agent`, the same way grep-subject is downgraded.
3. **Add an explicit `invariant_witness` rung** for env-enforced structural invariants
   (FK / balance / schema) — the only scalable production gold — distinct from
   `derived_witness` and from a per-task human reference. Do **not** claim it covers the
   33% "program-only" Toolathlon class until you measure how many are genuinely
   env-enforced vs human-coded checkers.
4. **A content-diff rung above the file-path rung.** Catching "wrong content in the right
   file" (the confident-wrong-mutation class, 95/203 in docs/177) needs a
   content-vs-expected diff the presence rung cannot do — and that immediately raises the
   gold-provenance question (§4), so it must ship *with* a provenance grade.
5. **Surface projection-WIDTH and projection-AUTHORSHIP as verdict fields.** A narrow
   projection false-PASSes (the failure hides in a secondary surface — 58% of fails are
   multi-surface AND carry preserve/branch language); a wide projection false-FAILs (a
   volatile timestamp swept in — the `trajectory.py` `_VOLATILE_PATTERNS` confound one
   rung down).
6. **A temporal-stability gate.** A world-state read at time T cannot distinguish "not
   written yet" (async/eventual-consistency) from "never written" — the tool_stream
   eventual-consistency confound one level up. verify() over an async SaaS surface needs a
   settle/quiescence condition before the read counts.
7. **Any new SaaS read-back driver pays the git tax explicitly:** prove the store is
   tamper-evident at field granularity AND the read is out-of-band/agent-uninfluenceable
   *before* the verdict is trusted.

---

## 8. The takeaway in one paragraph

docs/177 said the frontier's silent failures are a `verify()` problem — true, but
"verify() against world-state" is the next cartoon. **World-state is a 4-rung ladder, and
only the top rung — end-state diffed against an independently-authored gold over a
tamper-evident, independently-read store — witnesses goal-achievement.** DOS's own
flagship non-forgeable rung is a W2 presence-witness with an agent-authored projection,
not a W3 goal-witness; it proves *a commit touched the named files*, never *the content
is right*. The soundness criterion is conjunctive and sharp: split every witness into
evidence-bytes and spec-bytes and demand byte-author≠judged-agent of *each* — git passes
for the diff and fails for the plan-authored projection. And beneath all of it sits an
irreducible floor (~38% of frontier fails, measured) where the authoritative byte belongs
to an absent third party or no canonical gold exists, so *no* world-state witness — however
sound its provenance — reaches the goal, and the ladder bottoms out at HUMAN. The
model-agnostic consequence: **"world state" buys soundness only to the exact degree it is
tamper-evident, independently-read, and diffed against a not-the-agent gold — and DOS
should grade all three explicitly rather than presenting verify() as monolithic truth.**

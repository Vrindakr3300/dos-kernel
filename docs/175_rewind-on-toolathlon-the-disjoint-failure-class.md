# 175 — Rewind on Toolathlon: the failure class WARN cannot touch

> *Dated finding — written 2026-06-05. Every number is a dated observation on the
> frozen Toolathlon-Trajectories corpus (6,862 labeled runs, 22 models) as it stood
> that day, not an eternal truth. Companion to docs/172 (the rewindable FIX loop on
> EnterpriseOps-Gym) and docs/164 F1.5 (the rewind/backjump kernel verdict). The
> rewind mechanism was built + measured on EnterpriseOps' **injected-mint** regime;
> this doc applies the same idea to Toolathlon's **naturally-occurring** failures on
> a third-party-scored benchmark — independent corroboration on a different corpus.*

## 0. The question, and why Toolathlon is the right second corpus

docs/172 measured the rewind FIX loop on EnterpriseOps-Gym, where failures are
*injected* (the harness mints invented foreign-key IDs at a set rate) and the model
is held weak (gemini-2.5-flash) so it thrashes. That is a clean controlled
experiment, but a fair objection is: *the thrash was manufactured.* Toolathlon is
the answer to that objection. It is a **third-party benchmark we do not score** (an
independent HKUST oracle labels pass/fail), with **66 frozen real trajectories
across 22 models** spanning weak to frontier — and its failures are *natural*. If
the rewind-relevant failure class shows up here too, the mechanism is not an
artifact of the mint injection.

The specific question this doc answers offline, at $0:

> **Is there a failure class on a real third-party benchmark that the WARN
> re-surface (docs/144, the shipped winner) structurally cannot fix, but a
> REWIND/backjump (docs/164 F1.5) could — and is it a *distinct* population, not
> WARN relabeled?**

## 1. The two mechanisms are not the same shape

`conversion_ceiling.py` (docs/158) sizes the WARN ceiling: of failed runs, how many
fire a detector AND are *recoverable* because the value the agent needed was already
in its trajectory and re-presenting it could unblock. **A WARN appends a message; it
authors no step** (the docs/143 −9pp lesson, made structural). Its precondition is a
**usable** looped value — something worth re-surfacing.

REWIND is the *subtract* sibling. It rolls the transcript back to a kernel-minted
checkpoint **before** a dead-end branch, **excises** the dead-end turns, and
re-enters with a byte-clean no-good note (the kernel's typed verdict + the env's own
error excerpt, never a generated critique — `rewind.py`, `rewind_tokens.py`). Its
precondition is the **opposite**: a branch the env kept **rejecting**, where there is
no usable value to re-surface — re-presenting "you got a 404" is useless; the agent
has to *un-commit the path*.

That opposition is the whole point: **WARN needs a usable looped value, rewind needs
an error-dominated looped value.** They cannot both be true of the same loop. The
disjointness is structural, not coincidental.

## 2. The rewind-fixable predicate (byte-clean, an upper bound)

`benchmark/toolathlon/rewind_ceiling.py`. A FAILED run is **REWIND-FIXABLE** iff it
exhibits a **dead-end mutation branch**:

1. **MUTATION TOOL.** The looping tool is a state-mutating write (a fixed name-stem
   grammar: patch/post/write/update/create/upload/put/edit/scale/delete/append/
   insert/send/add, matched per name-segment). A read/list/query loop is *not* a
   dead-end branch — re-reading is the docs/145 WARN/tool_stream class.

2. **THRASH (≥ 5 calls) WITH ENV-AUTHORED BRANCH EVIDENCE.** The tool is issued `>= 5`
   times AND the **environment** returned `>= 2` *distinct* result-digests across those
   calls. **This discriminator is env-authored, not agent-authored** — an adversarial
   pass (§4) caught that keying "branch vs re-issue" on distinct *args* is forgeable
   (`_normalize_args` collapses only key-order, so cosmetic perturbation mints a
   distinct args-digest while the env returns identical bytes — an agent could promote
   itself WARN→rewind with zero new env evidence). A genuine dead-end branch draws `>=
   2` *distinct env responses* (the agent explored a region and the env answered
   variously); a WARN-shaped wall draws one identical byte hammered N times. The agent
   cannot forge a second distinct env result it did not receive.

3. **THE ENV REJECTED IT (≥ 60% errors), and the rejection is a real dead end.** `>=
   60%` of the mutation tool's env results are errors/unusable — the wall. Five honesty
   guards (all from the adversarial pass, §4) keep this an upper bound on *the named
   mechanism*, not a larger phenomenon. Each removes a class where a backjump buys
   nothing; together they take the count from a naive 64 down to **20**:
   - **(a) Success-dominated loops** — a varied *successful* multi-write (50 cells to a
     sheet) is not a dead end — the env did not reject it.
   - **(b) Eventual-consistency retry walls** — a `409 conflict`/"please try again"/
     `429`/`503`/"converting" is the env asking the agent to *retry the same action*;
     re-issuing is correct, there is no branch to subtract. (−5)
   - **(c) Early-success runs** — if the *first* loop-tool call returned a usable result,
     a real write landed; rewinding would *delete* progress. (−13)
   - **(d) Permission/access walls** — `object_not_found`/"shared with your
     integration"/`403`: the resource is unreachable regardless of how the write is
     phrased, so a backjump re-hits the same wall. (−2)
   - **(e) Never-solved tasks** — a task that *no model anywhere in the corpus* ever
     solved is plausibly impossible/mis-specified (the wrong commit is the *envelope*,
     not the branch); crediting it would not bound the named mechanism. (−11)

**Byte-cleanliness (the §5a line).** The load-bearing gates (2)+(3) read env-authored
result bytes only — the gym MCP server produced them; the judged agent did not author
the *identity* of its repeated results. The tool name in (1) is agent-authored but
classifying it only *excludes* (the safe-direction rule). **The agent cannot forge its
way into rewind-fixable: it cannot make the env return distinct errors it did not
return.** The verdict is provenance-of-an-env-rejection, never a forgeable "I'm stuck."

**Ceiling discipline.** This is an UPPER BOUND, never a prediction. The safe error is
to under-count (over-reject), which only lowers the ceiling — hence the five guards.

## 3. The result (frozen corpus, 2026-06-05)

`python -m benchmark.toolathlon.rewind_ceiling`:

| | runs | ceiling |
|---|---|---|
| WARN-fixable (conversion_ceiling) | 165 | +2.40pp |
| **REWIND-fixable (sound gates — the PRIMARY)** | **20** | **+0.29pp** |
| most-conservative fire-gated variant (§4) | 8 | +0.12pp |
| args-variety upper variant (incl. forgeable promotions) | 41 | +0.60pp |
| **BOTH (rewind ∩ warn)** | **0** | — |
| **ONLY-rewind (WARN cannot touch)** | **20** | **+0.29pp** |
| dead-end turns a backjump would excise | 880 | — |

**The journey is the story: 64 → 50 → 33 → 20.** Each adversarial round tightened the
ceiling toward the named mechanism:
- 64: first cut, branch keyed on agent-authored arg-variety.
- 50: env-authored result-diversity discriminator (−14 forgeable promotions).
- 33: EC-retry + early-success guards (−17 runs the mechanism doesn't apply to).
- **20: permission-wall (−2) + never-solved-task (−11) gates** — the sound-gates primary.

**And the disjointness survived every single cut: BOTH = 0 throughout, measured not
asserted.** The 20 are genuine dead-end branches WARN structurally cannot touch — as
the mechanism opposition in §1 predicts. The +0.29pp ceiling is *small*; the value is
not the magnitude but **the existence of a disjoint, capability-orthogonal class**.

**The scissors-inversion (the part that matters for frontier models), and it survives
all five hardening rounds.** WARN's headroom collapses to **0 on strong models** (gpt-5,
gpt-5.1, gemini-3-pro, claude-4.5-sonnet, deepseek-3.2 all warn-fixable = 0 — the
docs/170 scissors). But sound-gates rewind **still fires on them**: gpt-5 = 2,
gemini-3-pro = 1. **Where WARN has no headroom at all, rewind is the only mechanism with
any.** The reason is mechanistic: a strong model rarely re-issues the *identical* failed
call (so WARN/tool_stream rarely fires), but it *does* still commit to a wrong approach
and thrash *variations* of it — a dead-end branch capability-independent in a way the
identical-repeat loop is not. Best reachable A/B target among models we have keys for:
gemini-2.5-pro; grok-4 leads (4) but is xAI/unreachable.

## 4. The load-bearing design choice: branch, not loop

The natural temptation — and where an early multi-agent design pass landed — is to
gate rewind-fixable on **`tool_stream` firing** (a consecutive run of identical
`(tool, args, result)` triples). That is *wrong* for the rewind mechanism, and the
data shows why:

> Of the 20 sound-gates rewind-fixable runs, only **8 actually `tool_stream`-fire**
> (the agent re-issued the *exact same* rejected mutation). The other **12 do NOT
> fire** — they are **varying-branch thrash**: the agent tried *different* approaches
> (and the env answered with *different* rejections), so no consecutive identical run
> ever forms.

A `tool_stream`-gated predicate would discard **12 of the 20** — and those 12 are
precisely the dead-end *branches* the rewind mechanism uniquely exists for. The
estimator therefore gates on a **mutation issued ≥ 5 times that drew ≥ 2 distinct ENV
responses**, independent of consecutive-repeat firing. The adversarial synthesis
argued for *restoring* a `tool_stream`-fire precondition (which would cut the headline
to **8**); this doc **diverges from that one fix on the merits and reports it as a
variant rather than hiding the choice** — a fire-gate conflates "no consecutive repeat"
with "no branch," and the 12 varying branches draw genuinely *distinct env rejections*
(parent A → 404, parent B → 404, …), which is exactly an explored dead-end region. The
estimator prints both the sound-gates primary (20) and the fire-gated variant (8) so
the 12-run sensitivity to that contested choice is visible, not buried. Every *other*
adversarial fix — env-authored discriminator, EC-retry, early-success, permission-wall,
never-solved — is adopted. This is also *why* the disjointness from WARN is perfect:
WARN-recoverable requires a fire over a *usable* value; the non-firing branches are
invisible to it, and the firing ones are error-dominated (so WARN's usable-value gate
rejects them).

The honest reading: **"loop" (identical repeat) is the WARN class; "branch" (varied
thrash drawing varied env rejections) is the rewind class.** Keeping them apart is the
whole contribution.

## 5. What is proven, and what is not

**Proven, at $0, on a third-party-scored corpus, after FIVE adversarial gate rounds:**
- A real, byte-clean failure class exists (**20 runs**, the sound-gates primary;
  hardened down from 64→50→33→20, with a most-conservative fire-gated variant of 8)
  that the shipped WARN winner cannot touch (disjoint, **BOTH = 0 measured at every
  cut**), with a concrete subtraction magnitude (880 dead-end turns).
- It is *not* a weak-model artifact: it persists on frontier models where WARN's
  headroom is zero (the scissors-inversion survives all five hardening rounds).
- The varying branch — not the identical-repeat loop — is its core (12/20 invisible
  to `tool_stream`).

**The honest verdict on the null hypothesis** (H0 = "rewind adds nothing a WARN cannot
reach"): **qualified-refuted.** Refuted *in kind* — the 20 runs are genuinely disjoint
from WARN (BOTH = 0 measured), a committed-wrong-write class no append-only intervention
reaches. But the magnitude is *marginal* — +0.29pp, single digits, and the realized
lift is a fraction of even that. The value is **substantial qualitatively** (a new
failure-shape covered, on frontier models) but **marginal quantitatively**.

**NOT proven (the honest wall, same as docs/172 Tier (a)):**
- **Whether the agent then succeeds.** Offline replay proves *where* the backjump
  lands and *how much* it subtracts. It cannot replay the counterfactual *future* —
  a truncated transcript re-fed to the model produces new tokens we do not have on
  disk. Conversion is a live question (being measured live on EnterpriseOps in
  parallel — docs/172).
- **The ceiling is +0.29pp, small.** Like WARN's +2.40pp, this is a modest corpus
  ceiling and the *real* lift is a fraction of it. The value is not the magnitude;
  it is **the existence of a disjoint, capability-orthogonal class** — the same
  durable-infra claim docs/172 §4 makes, corroborated on a second, natural corpus.
  A paid Toolathlon rewind A/B is **not justified by magnitude** on this corpus; if
  run at all, target grok-4 on `notion-API-patch-page` (the densest cell).

## 6. The frontier-lab framing (carried from docs/170 / docs/172, not re-argued)

This is the **durable-infra** claim, not the decaying-lift claim. The lift ceiling is
small and a fraction is realized — docs/170's scissors stands. But the durable point
is sharper here than on EnterpriseOps because it shows up **on frontier models**:
when you run thousands of agents for hours (horizon × fanout), a non-trivial fraction
commit to a wrong approach and thrash variations of it — and *that* failure does not
go away when you upgrade the model. WARN cannot back them out (nothing usable to
re-surface); the naive append (BLOCK) was net-negative (docs/144); the sound move is
to **subtract the dead-end branch and re-enter with the env's own rejection bytes**.
That a real third-party benchmark contains this class on its strongest models, and
that it is provably disjoint from everything WARN reaches, is the lab-legible reason
the rewind primitive is worth having independent of which model ships.

## 7. Provenance of the numbers

- sound-gates rewind-fixable = **20** / +0.29pp (PRIMARY), fire-gated variant = 8,
  args-variety upper = 41, BOTH = 0, only-rewind = 20, 880 turns subtracted, per-model
  scissors: `python -m benchmark.toolathlon.rewind_ceiling`, run 2026-06-05 over
  `_data/*.jsonl` (7,116 records / 6,862 labeled / 22 models). Committed
  `benchmark/toolathlon/rewind_ceiling.py` + 14 tests
  (`tests/test_toolathlon_rewind_ceiling.py`).
- the 64 → 50 → 33 → 20 hardening, each a measured `compute_rewind_ceiling` fold:
  64 = args-keyed first cut; 50 = env-authored result-diversity discriminator (−14
  forgeable arg-promotions); 33 = EC-retry guard (−5) + early-success guard (−13);
  **20 = permission-wall gate (−2) + never-solved-task gate (−11)**. The journey is
  reproduced in the git history of the estimator file.
- 8 fire / 12 non-fire split of the 20: a `run_row.tool_stream_fired` fold over the
  sound-gates rewind-fixable set (the fire-gated variant the CLI prints).
- WARN ceiling = 165 / +2.40pp, the strong-model scissors:
  `python -m benchmark.toolathlon.conversion_ceiling` (docs/158).
- the five adopted adversarial fixes (env-authored discriminator, EC-retry,
  early-success, permission-wall, never-solved) + the one diverged-from
  (`tool_stream`-fire gate, reported as a variant, §4) came from a 3-characterize /
  3-adversary / synthesis design workflow (7 agents, 936K tokens).
- The rewind kernel surface (the verdict, the no-good note, the 31 tests):
  `src/dos/rewind.py`, `src/dos/rewind_tokens.py`, `tests/test_rewind.py`.
- The EnterpriseOps live rewind experiment (the conversion half this corroborates):
  docs/172, `benchmark/enterpriseops/{rewind_counterfactual,live_ab}.py`.

> **The live conversion number** is the half no offline estimator can produce — and §8
> reports it: the powered EnterpriseOps live A/B **REFUTES** the conversion thesis (the
> cheap subtract-the-branch fix does not convert when the cause is upstream). A paid
> Toolathlon A/B is **not justified by magnitude** (+0.29pp). So the honest split: this
> doc settles, at $0 on Toolathlon, that the failure class *exists and is disjoint from
> WARN* (solid, across 22 models); §8 shows the obvious live *fix* for it is *not enough*
> — pointing at F3 (supply the missing fact at the write, gated) rather than subtract.

## 8. The live conversion — TWO runs disagreed; the powered one REFUTES

The offline result above settles *existence + disjointness*. The live conversion
question — *does subtracting the branch actually convert fail→pass?* — was run on
EnterpriseOps-Gym (docs/172) **twice on 2026-06-05, and the two runs disagreed in
sign.** That disagreement is itself the verdict: the effect is small relative to noise,
so **the more-powered run governs, and it refutes.** Both are reported; neither is hidden.

| run | tasks | domains | mint | rewind−block (verifier) | fired-run flip net | verdict |
|---|---|---|---|---|---|---|
| **A — POWERED** | **48** | **4 (itsm/csm/hr/email)** | 0.40 | **−3.4pp** | **−3 (4 help / 7 hurt)** | **REFUTES** |
| B — small | 20 | 1 (itsm) | 0.30 | +6.2pp | +3 (3 help / 0 hurt) | favorable but underpowered |

**Run A is the governing result (docs/172 §3.5): the conversion thesis is DISPROVED on
this regime.** Run A trips two pre-registered kill conditions — rewind (44.9% verifier)
landed *below* block (48.3%), and the fired-run flip net went *negative* (−3, worse than
block's +2). The mechanism (the valuable part): a **rewind livelock** — when the dead
end's cause is an *upstream omission* (the agent never looked up the id, and that missing
read lives *before* the rewind anchor), backjumping to a clean prefix hands back the same
prefix that caused the invention, so the agent **re-emits the same invented id and
re-thrashes**. Subtraction removed a *symptom*, not the *cause*. (Plus a no-op spin: the
trigger re-fired per-block, so 27% of rewinds dropped nothing — a livelock in the rewind
mechanism itself.)

**Run B (my ITSM-only n=20) landed favorably — rewind 38.3% vs block 32.1% (+6.2pp),
fired-run flip 3/0 — but it is NOT a confirmation.** It is exactly the small,
single-domain, lower-mint sample the runner's ±~5pp band and docs/172 §6 warn against.
**Two opposite-sign results on a sub-5pp effect is the textbook signature of a
noise-dominated measurement; the larger sample (A) wins.** Reporting B as a "confirmation"
would be motivated reading of the favorable draw — so it is recorded here as one small
*contradicting* data point, governed by A.

**What this does and does NOT touch:**
- The **offline Toolathlon result (§3) is unaffected** by either live run. That the
  rewind-relevant failure class *exists* and is *disjoint from WARN* across 22 models is
  a property of the frozen corpus, not a conversion claim. The disjointness stands.
- What is **refuted** is the live *conversion* thesis — that subtracting the branch
  reliably converts fail→pass on this weak-model + injected-mint regime. It does not;
  subtraction of a *symptom* cannot supply a missing *cause*.
- What still **held** (docs/172 §3.5.2): the byte-clean note (18/18 live rewinds emitted
  only kernel tokens + env bytes, zero generated prose — the §6 contract survived a real
  model) and the anchor *placement* (the $0 replay's 6/6). The failure was conversion,
  not the byte contract.

**The honest synthesis across both corpora.** Toolathlon (offline) shows a *real,
disjoint, capability-orthogonal failure class* WARN cannot touch — that finding is solid.
EnterpriseOps (live, powered) shows that *the obvious fix for it — subtract the branch —
does not convert* when the root cause is upstream, and points instead at F3 (supply the
verified missing fact at the write, gated — docs/126 PEP) as the only rung that addresses
an *omission* cause. **The class is real; the cheap content-free fix for it is not enough.**
That is a more useful result than a clean win would have been: it says where the value
is (detect + attribute the disjoint class) and where it is not yet (a sound *supply*, not
just a *subtract*).

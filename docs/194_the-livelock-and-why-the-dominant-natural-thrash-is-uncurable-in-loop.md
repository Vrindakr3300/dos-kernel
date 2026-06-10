# docs/194 — The livelock, and why the dominant natural thrash is uncurable in-loop

> **The same-deadend loop is not one problem. The mint-injection livelock (rewind
> re-invents the omitted id) and the *natural* livelock (the agent re-issues a wrong
> arg it already saw the env reject) have different causes — and the dominant natural
> one is structurally uncurable by any advisory, byte-clean cure. The value DOS can
> still bank is not in-loop conversion; it is early-halt cost-aversion for the cheap-
> model fleet tier, plus a new byte-clean key-mismatch DETECTOR. Detection is solved;
> for this class, conversion is *refuted*, not merely unmeasured.**

> ## §0.0 — CORRECTION (2026-06-06, after "this still seems off"): a CATEGORY ERROR
>
> **The body below scored every cure — including this doc's own abandon refutation —
> against a contaminated denominator, and reached a conclusion that is partly wrong.**
> The dominant "thrash" tool `create_filter` is not a *curable* loop the agent fails to
> escape; it is an **INFEASIBLE TASK**. Measured: `create_filter` succeeds **0/579 calls
> across all 7 arms** (none 0/262, rewind_natural 0/134, …) and **0/278 in the natural
> A/B specifically** — never once, by any model or intervention. The tool's schema
> demands all ~9 `criteria` fields be present and non-empty; the user task ("filter on
> sender only") cannot be expressed under it. The agents even *diagnose the fix*
> (`"from should be 'from' not 'from1', and size expects an integer"`) and still fail,
> then conclude the task is infeasible. **You cannot cure an infeasible task — measuring
> "did the agent succeed" was a category error.**
>
> **The consequence corrects §3.1's abandon refutation.** That refutation killed early-
> halt cost-aversion because 33–42% of fired runs "self-recovered." But it counted a
> *non-error tool result later* as recovery — and on this corpus **0 of those 10
> "recoveries" actually succeeded at the TASK** (the run still failed). Re-scored on the
> honest **task-success denominator**, abandon's false-abandon rate is **0.000 at every
> K** (it never halts a run that wins; there are none to win) and it saves **33k / 22k /
> 21k tokens** at K=2/3/4 — it **PASSES** its own pre-registered kill (FA<0.10 AND net>0).
> *Early-halt cost-aversion is the SURVIVOR, not the refuted candidate.*
>
> **The feasibility witness** (the missing distinction): a thrashing tool is WALLED iff
> it has **0 successes anywhere**, CURABLE iff the same tool succeeds on other runs.
> Measured across the natural A/B: WALLED = `create_filter` (0/278). CURABLE = everything
> else that thrashes (`update_vacation_settings` 20✓/84✗, `update_hr_case` 35/17,
> `create_label` 88/6, …). **Conversion must be A/B'd on the CURABLE tools — testing it
> on WALLED `create_filter` was the testbed error that produced every "refuted" verdict.**
>
> **So the corrected headline is NOT "conversion is refuted."** It is: the dominant
> natural failure is two disjoint populations — (a) WALLED tasks, where the value is
> **give-up-correctly** (early-halt, byte-clean, measured-positive on the success
> denominator), and (b) CURABLE tasks, where conversion is genuinely **untested** (every
> prior A/B mixed them, drowning any signal). Read the body below THROUGH this correction;
> the new direction is in [[docs/198]] (give-up-correctly + the feasibility witness).

Status: **DESIGN + MEASURED REFUTATION.** This doc records the result of a multi-agent
design+adversarial-verify pass (2 workflows, 30 agents, ~2.1M tokens) over five
candidate cures, every claim grounded in the REAL EnterpriseOps corpus
(`benchmark/enterpriseops/live_results_natural_ab/none`, n≈47–98 runs,
gemini-2.5-flash). All five candidates were **killed**, each for a sound, specific,
data-verified reason. The negative result is the contribution: it tells the operator
to stop building in-loop conversion rungs for this class.

Parent: [[docs/172]] (rewindable FIX loop, the mint regime), [[docs/175]] (rewind
disjoint class), [[docs/144]] (intervention ladder), [[docs/164]] (FIX/rewind verdict),
the conversion-gap reframe. Siblings: `tool_stream` / `natural_thrash_gate` /
`precursor_gate` / `arg_provenance` (the byte-clean detector family); [[docs/191]]
(the proactive "bank the verdict before the failure on a non-agent denominator" lens —
this doc is its negative case: even the non-agent denominator (cost-averted) is refuted
on the schema-blindness class, §3.1); [[docs/177]] (frontier silent-failure → verify()
rung, where the durable value actually lives).

---

## §0 — The measured premise correction (this overrides the mint-injection framing)

Every prior rewind doc (172/175) rested on the framing **"the dominant failure is an
UPSTREAM OMISSION — the agent invents `contract_id` because it never looked it up."**
That framing is a **mint-INJECTION artifact**. Probing the *natural* thrash population
(no injection) refutes it:

- **The dominant natural thrashers are `create_filter` (8 runs) and
  `update_vacation_settings` (7 runs)** — both Gmail tools. Everything else ≤1 run.
- **They are not missing-lookup (omission) failures and not minting failures.** They
  are **malformed-argument** failures the env error under-specifies:
  - `create_filter`: the agent sends `criteria.from1` (a phantom key); the env says
    `criteria.from: is required`. The correct key is *in the error every turn*; the
    agent re-issues `from1` / `from1_` anyway. **A wrong-KEY-name confusion.**
  - `update_vacation_settings`: `start_time must be a valid epoch millisecond
    timestamp` / `HTML content must contain at least one HTML tag`. **A wrong-VALUE-
    type encoding.**

So there is a **third failure class** beyond the two the prior work named:

| Class | Cause location | Prior verdict |
|---|---|---|
| (a) downstream-accretion | junk pasted INTO recent turns | rewind/SUBTRACT cures it |
| (b) upstream-omission | a missing read BEFORE the anchor | rewind LIVELOCKS (mint regime) |
| **(c) schema-blindness** *(NEW, dominant naturally)* | the **model's prior**, not the transcript | **this doc: uncurable in-loop** |

The precursor-gate cure is a **false premise** for the natural population: the grammar
(`precursor_grammar.toml`) covers only ITSM tools (`update_case`/`link_new_case_sla`),
while the dominant thrash is email-domain — so `precursor.REFUTED` fires ~never on the
class it was meant to cure. Measured: `arg_provenance.UNSUPPORTED` fires 15× (only on
`create_label`'s hex `color` field — a false positive, not an FK mint);
`precursor.REFUTED` fires 10× (only on ITSM `update_case`). The two conjuncts live on
**disjoint tool sets and never co-occur on the same call** → a `minted AND skipped`
write-gate fires **exactly 0 times** naturally.

---

## §1 — The five candidates and why each was killed

All grounded in the corpus. (Full kill-shots: the workflow record; preserved digest in
`_livelock_killshots.txt`.)

1. **SCHEMA-RESURFACE** (on a thrash, re-surface the failing tool's JSON schema) —
   **KILLED (fatal, redundancy).** The gym's own validation error **already enumerates
   the required-field set verbatim**; the schema re-states the identical field names one
   ToolMessage later. The agent already ignored those bytes in the error → re-printing
   them at the same recency adds no lever. Wrong-type class isn't even in the schema (the
   "must be epoch-ms" constraint lives in the gym's *validator logic*, not the declared
   JSON Schema). Plus: the gym does **not** persist `inputSchema` in result files, so the
   "$0 replay settles it" claim is false — it needs a live `tools/list` dump.

2. **REFUSE-WITH-NAMED-PRECURSOR** (compose `arg_provenance` MINTED + `precursor_gate`
   → refuse + name the lookup) — **KILLED (fatal, zero footprint).** The conjunctive AND
   fires **0×** naturally (§0). On `create_filter` the bug is a wrong key passed as an
   *empty string* — nothing minted (`arg_provenance` ABSTAINs), no grammar precursor
   (`precursor_gate` NO_SIGNAL). Byte-cleanliness/no-deadlock/conjunctive all HOLD (the
   substrate is clean) — it just helps nobody on the dominant class. Honest residual: the
   ITSM upstream-omission slice (4/84 runs), a mint-injection artifact that decays on
   strong models.

3. **ABANDON-AND-ESCALATE** (halt the doomed loop, value = cost-averted) — **KILLED
   (serious ×2, survivable but re-scoped).** The byte-clean lens **could not break it**
   (clean signal, no smuggled predicate). But: (i) **conversion lens** — its $0 kill-gate
   uses the *full-stream* gate (0/13 false-abandon) while the *live incremental* gate
   fires early and **42% of fired runs SELF-RECOVER later** (the tool succeeds at call
   5–6 after failing at 1–2). The "tokens-averted" ledger is a **work-DESTROYED** ledger
   on that slice. (ii) **durability lens** — its differentiating claim "value INCREASES
   with model strength" is **false by docs/177**: the gate keys on the structured-error
   channel that drains to **0/321 on gemini-3-pro** (83% of frontier fails are *silent*).
   So it **decays** on the frontier, like every other trajectory-grammar rung.

4. **CAUSE-GATED RESTART / KEY-STEER** (route schema-blind thrashes to restart; name the
   env-canonical key) — **KILLED (fatal ×2).** The conversion premise — "the agent is one
   rename from success" — is **empirically false**: 3/13 runs self-discover `from` with
   zero help and **still fail**; one run self-discovers it **10 times and reverts every
   time** (a generation-stability livelock, not an information deficit). And when the key
   IS correct, the binding constraint is **value-encoding** (`size: integer got number`,
   empty-string-required) the steer is byte-clean-FORBIDDEN to supply. Blocker
   composition (n=144 calls): MISNAME is the *sole* blocker in ≈0 cases; it co-occurs
   with unfixable EMPTY/TYPE residue in 131/144. Named-key precision is **67.5% < the
   80% pre-registered bar** (54 fires name never-tried fields, not misspellings).

5. **SCHEMA-VALIDATION WRITE-GATE** (pre-dispatch refuse a malformed write) — **KILLED
   (fatal).** Same value-encoding wall as #4, plus it **re-implements the gym's own
   validator** (the env already returns the missing-required set in full). The genuinely-
   novel bit (the phantom-key diff) is **not on the success critical path**.

**The convergent kill across #1/#4/#5:** `create_filter` succeeds **0/144 calls across
13 runs**. It is **unwinnable by any byte-clean advisory cure**, because (1) the wrong
key is a self-resolving symptom the model reverts off, and (2) the real wall is a
value-encoding constraint a PDP may not author. This is a model-prior / generation-
stability failure, and an advisory re-surface (PDP) cannot move a prior-driven loop —
the same structural reason rewind scored −3 and BLOCK scored −6.

---

## §2 — The one genuinely-new byte-clean artifact: the key-mismatch DETECTOR

Killed *as a cure*, but sound *as a detector* (every adversary agreed): a
**phantom-key / key-mismatch verdict** — the schema-blindness sibling of
`arg_provenance`'s value-mint detector, one grain over:

```
arg_provenance : "is this VALUE minted (never in env bytes)?"   [provenance of a value]
key_mismatch   : "is this KEY a phantom (not in the env-declared field set)?" [structural diff]
```

Both are pure byte questions over **agent-authored** (the key/value the agent chose) vs
**env-authored** (the env error's named fields / the tool's declared schema) bytes — no
satisfaction predicate. It NAMES the agent's specific mistake (`from1` ∉ declared set;
closest declared field `from`, edit-distance 1), the bit the raw error withholds.

**Why it does not graduate to a cure:** the named key is already in the error the agent
ignores; the suggestion is redundant with bytes the model declined to act on; and the
edit-distance "you meant `from`" pairing sits close to the SUPPLY line (kernel inferring
agent INTENT). Keep it as a **detector / cost-averted instrument / label**, not an
agent-side fix. Honest measured precision on env-error-derived field sets: only **14% of
"phantom" instances are typo-resolvable within edit-distance 2** (the rest are noise from
deriving the field set from error text) — a sound version needs the tool's *real* schema.

---

## §3 — The honest answer: where value remains

Detection is solved; **for the schema-blindness class, in-loop conversion is refuted.**
The value DOS can still bank, ranked:

1. **EARLY-HALT COST-AVERSION for the cheap-model fleet tier — MEASURED + REFUTED on
   this corpus (the §5 replay ran).** The hypothesis: on a *confirmed* livelock (≥K
   consecutive same-tool errors), HALT and reap, banking tokens-averted + lane-throughput.
   The corrected recovery-aware $0 replay (`abandon_counterfactual.py`, 104 none-runs)
   **fails its own pre-registered kill at every K**:

   | K | fired runs | false-abandon | FA-rate | net tokens averted |
   |---|---|---|---|---|
   | 2 | 19 | 8 | **0.42** | +14 734 |
   | 3 | 14 | 5 | **0.36** | +13 522 |
   | 4 | 12 | 4 | **0.33** | +12 668 |

   The kill criterion (∃K: FA-rate < 0.10 AND net-averted > 0) **does not clear**: net
   tokens-averted is positive at every K, but the false-abandon rate never falls below
   **0.33** — i.e. a third-plus of fired runs **self-recover** (the same tool succeeds
   later), so early-halt destroys productive work too often. The adversary's predicted
   42% at K=2 reproduced **exactly**. Raising K shrinks the fired set but **not** the
   recovery rate — the natural recovery window is wide and persistent. So even the
   consolation-prize cost-aversion does not bank net value through the agent-action path
   on this class. **Verdict: this class is DETECTION-ONLY — no actuation clears the bar.**
   (Cost-aversion may still pay on a *different* failure population — e.g. a confirmed
   never-recovers signature like the 88-call `criteria.from` wall — but that is a narrower
   gate to be re-derived, not the K-on-same-tool-error gate, which is refuted.)

2. **The key-mismatch DETECTOR as a label/instrument (§2).** Feeds the docs/179
   firing-label / `fleet_roll` machinery: a confirmed key-mismatch livelock is a clean
   training datum ("this trajectory needed key X, sent phantom Y, never recovered").

3. **The negative result itself, as a research redirect.** "The dominant natural thrash
   is value-encoding + retry-instability, NOT wrong-key, and is uncurable by advisory
   byte-clean means" redirects the next bet away from schema-key naming entirely — and
   toward the verify()-rung (result-state witness) for the frontier, where the failures
   actually live (docs/177).

---

## §4 — The honest ceiling

- **Frontier:** ~0 in-loop value on this class. Frontier failures leave the structured-
  error channel every trajectory-grammar detector keys on (docs/177: 0/321 fires,
  83% silent). The frontier value is a **verify()-not-tool_stream** problem.
- **Cheap-model fleet:** real, measured, but **cost-averted, not pass-rate** — and only
  under a recovery-aware gate. The mistake the prior work kept making is scoring on the
  agent's pass-rate (the refuted denominator); the only surviving denominator is
  cost/throughput, monotone in fanout, 0 at N=1.
- **The discipline that held throughout:** detection-soundness ≠ value-conversion. Four
  byte-clean detectors are sound; for class (c), no advisory rung converts, because the
  cause is in the model's prior, not the transcript, and the binding wall is a value
  the kernel may not author.

---

## §5 — The buildable next step (cheapest decision-relevant datum)

**Do NOT build an in-loop conversion arm.** The single cheapest experiment that banks a
result is the **corrected cost-aversion $0 replay** — **BUILT + RUN this session**
(`abandon_counterfactual.py`); result above (§3.1): **refuted at every K**, the class is
detection-only. The replay spec, for the record / re-running on a new corpus:

- **File:** a new `benchmark/enterpriseops/abandon_counterfactual.py` (the
  `natural_thrash_counterfactual.py` pattern), reading `live_results_natural_ab/none`.
- **Gate:** fire the abandon trigger **incrementally** (over growing prefixes, at the
  first Kth same-tool structured error), NOT on the full stream. Sweep K ∈ {2,3,4}.
- **Metric:** for each K, (a) fire-rate, (b) **false-abandon = fraction of fired runs
  where the SAME tool succeeds anywhere AFTER the fire point** (the within-tool-recovery
  look-ahead — the 42% the original gate hid), (c) net tokens-averted = averted-tail
  tokens MINUS successful-tail-call tokens destroyed.
- **Pre-registered kill criterion:** ship the abandon arm only if ∃K with false-abandon
  < 10% AND net-averted > 0. The corpus already hints K=2 fails (42% recovery); K≥3 is
  the candidate. If no K clears it, **cost-aversion is also refuted** and the honest
  output is "detection-only, no actuation" for this class.
- **Layer:** BENCHMARK arm (disjoint lane), zero kernel edit. If cost-aversion clears,
  the kernel primitive is already shipped (`liveness` self-stop / `dos halt` /
  `supervise` reap) — only the *gate K + recovery look-ahead* is new, and it is policy.

The `key_mismatch` detector (§2) may be built as a pure benchmark instrument in parallel
(`key_mismatch_counterfactual.py`) to quantify named-key precision on the real schema —
but as a LABEL/cost-averted input, never wired to an agent-side rung.

---

## §6 — Litmus (what would overturn this)

- If a K exists with false-abandon < 10% and net-averted > 0 → cost-aversion ships
  (cheap-model tier). If not → the class is detection-only.
- If a future model's `create_filter` thrash shows the wrong key IS the sole blocker
  (no value-encoding wall, no revert) → re-open the key-steer cure. The corpus says it
  is not, on gemini-2.5-flash; re-measure on any new model before re-opening.
- If the gym is cloned and exposes real `inputSchema` → the key-mismatch detector's
  precision can be measured properly (today's 14% is an error-text-derived floor).

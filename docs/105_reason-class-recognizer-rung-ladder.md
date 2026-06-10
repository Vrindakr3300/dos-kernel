# 105 — The reason-class recognizer is a rung ladder, not an exact-match table

> Found by running Arm A of the supervision-ratio proof
> (`dos-private/dispatch-os-proving-the-supervision-ratio.md` §3.1) against
> `job`'s real dispatch corpus, 2026-06-02. The plumbing half of the oracle's
> blind spot is fixed (commit `5de7e28`); **this is the design for the deeper
> half** — and the reason not to fix it the obvious two ways.

## 1. The defect, stated precisely

`picker_oracle.resolve_cause(reason_class)` maps an emitted token onto a closed
`NoPickCause` so the oracle can grade a NO-PICK. Today it is a **two-tier
exact-match lookup**:

1. the frozen `REASON_CLASS_MAP` (derived from the closed `wedge_reason` enum +
   legacy aliases), then
2. the active workspace's `ReasonRegistry.category_for` (the `dos.toml [reasons]`
   hackability seam),
3. else `UNCLASSIFIED`.

Both tiers are **string equality**. Measured on `job`'s corpus: the kernel knows
**17** tokens; the producer emits **24 distinct**; the gap is **16 unknown tokens
(32 occurrences)** that fall to `UNCLASSIFIED`. That is *why* the proof's recall
is "less vacuous but not yet biting" — and the unknown tokens are not noise, they
are the **most diagnostic** ones:

```
PLAN_ID_COLLISION_FALSE_SHIPPED   REGISTRY_FALSE_SHIPPED   VALIDATOR_STAMP_FALSE_SHIP
STALE_STAMP_LANE_DRAINED          OPERATOR_DECISION_PENDING …
```

These are *false-shipped / stamp-drift* signals — exactly the picker-bug shapes
`oracle_disagrees` exists to surface. The oracle is blind to the decisions it most
needs to see.

## 2. Why the two obvious fixes are both wrong

This problem sits squarely under **docs/76 (flexible-goals-and-verification)**,
the design law for *where flexibility is allowed to live*. Read against it, both
reflexive fixes fail:

- **Widen the kernel `wedge_reason` enum to include job's tokens.** Violates
  docs/76 §3's line (*"a driver tunes the recognizer's vocabulary; the kernel owns
  the judgment"*). `APPLY_LANE_BLOCKED_MESH` / `TAILOR_LANE_FOCUS_BLOCKED_SOAK_GATE_CLOSED`
  are a *host's* dialect; baking them into the kernel makes it accrete every
  host's vocabulary forever. The kernel would stop being domain-free.
- **Declare all 16 in `job/dos.toml [reasons]`.** Respects the §3 line — but
  ignores docs/76 §2 (*the kernel flexes as a graceful **rung ladder**, not by
  demanding more scaffolding*). Reason-class tokens are **LLM-authored compounds**
  and therefore an **open, effectively-infinite set** — e.g.
  `DL_LANE_STALE_STAMP_BODY_VS_META_DRIFT_PLUS_SHIP_ORACLE_SERIES_COLLISION`. An
  exact-match registry over an infinite generator is the *same brittleness* the
  hardcoded grep grammar had before `StampConvention` (docs/76 §3's origin bug) —
  worse, because ship-dirs were finite and these are not. You cannot enumerate
  your way out.

The tell that both are wrong: each NO-PICK token's **category is legible in its
morphology**. `*FALSE_SHIP*` is a stale-claim shape; `*OPERATOR*` is an
operator-gate; `*INFLIGHT*` / `*DRAIN*` is a true-drain; `*SOAK*`/`*GATE*` is a
gate. Exact equality throws this signal away.

## 3. The design: a rung ladder over a host-declared recognizer

The clean generic fix is the **synthesis docs/76 §2 + §3 already imply** but the
code doesn't have yet: make `resolve_cause` a **rung ladder** (§2) over a
**recognizer the host declares as data** (§3), and have it **report which rung
answered** (§2's "name the weakest authority"). Three rungs:

| Rung | Recognizer | Authority |
|---|---|---|
| **1. exact** | frozen `REASON_CLASS_MAP` + workspace `ReasonRegistry` (today) | strongest — an exact, declared token |
| **2. morphological** | ordered `(substring → NoPickCause)` rules, declared as DATA (kernel ships a GENERIC default; host extends via `dos.toml`) | weaker — category inferred from token shape |
| **3. none** | — | `UNCLASSIFIED`, the honest floor |

Crucially this is the **same shape as `oracle.is_shipped`** (registry → grep →
none) and as the `StampConvention` lift: the kernel's **judgment stays closed and
identical across hosts** (the `NoPickCause` set, the cross-checks downstream of
it), while the **recognizer's vocabulary becomes data**. A driver gets to declare
*what a stale-claim token looks like in its dialect*; it never gets to change
*whether* a recognized stale-claim, once classified, is cross-checked — that is
still the kernel's `_check_stale_claim_real`, the same everywhere.

### 3.1 The morphological rung must report itself

The `PickerVerdict` gains a `cause_source: "exact" | "morphological" | "none"`
(mirroring `verify`'s `source`). This is non-negotiable under docs/76 §2: a fuzzy
classification **must not masquerade as an exact one**. A cross-check that fired
on a morphologically-guessed `STALE_CLAIM` is weaker evidence than one on a
declared token, and the operator-decisions queue / `oracle_disagrees` routing must
be able to see the difference. The rung is the honesty knob, exactly as
`source="grep"` is for `verify`.

### 3.2 Rule order encodes a precedence judgment — so it is auditable data

Validated against the 16 real unknown tokens, the morphological rung classifies
**25 of 32 occurrences (78%)**, leaving 7 honestly `UNCLASSIFIED`
(`APPLY_LANE_BLOCKED_MESH`, `LANE_DECISION_STALLED`,
`APPLY_LANE_POST_UNSTICK_STOP_RESPAWN` — genuinely ambiguous shapes where
abstention is *correct*). But one token, `LANE_ALL_SHIPPED_INFLIGHT_OR_SOAK_GATED`,
matches **two** rules (`INFLIGHT`→TRUE_DRAIN and `GATE`→OPERATOR_GATE). First-match
-wins means **rule order is a precedence decision**, and because the rung reports
itself (§3.1) *which rule fired is recoverable*. This is why the rules are ordered
DATA, not a hardcoded `if/elif`: the precedence is a host-tunable, auditable
policy, not a buried constant.

### 3.3 What stays rigid (the docs/76 line, restated for this seam)

> A driver tunes the *reason-class recognizer's vocabulary and morphology*; the
> kernel owns the *category set and every cross-check downstream of it*. Declaring
> a new dialect (exact token or substring rule) widens what the oracle can
> **recognize**; it never changes what the oracle **concludes** once it has
> recognized, nor whether `oracle_disagrees` fires.

The anti-pattern this rules out, same spirit as docs/76 §2's `confidence: float`:
a similarity score on the token (`0.8 stale-claim-ish`). The morphological rung is
still a **closed, ordered, deterministic** set of substring rules returning a
**closed** `NoPickCause` — it is a *recognizer dialect*, not a fuzzy classifier.
The kernel remains the part that doesn't believe the agents; it has merely learned
to read more dialects of "no."

## 4. Implementation sketch (kernel-clean, no host names)

- `dos/reason_morphology.py` (new pure leaf, sibling of `stamp.py`): a
  `MorphologyRule(substring, cause)` + an ordered `MorphologyRuleset` +
  `GENERIC_REASON_MORPHOLOGY` (the domain-free default rules: `FALSE_SHIP`,
  `STALE_STAMP`, `OPERATOR`, `SOAK`/`GATE`, `INFLIGHT`/`IN_FLIGHT`, `DRAIN`,
  `MISROUTE` → their categories). **No job lanes** — only domain-free shapes ship
  in the kernel default. `APPLY_LANE_*`/`TAILOR_LANE_*` are a host's, declared
  host-side.
- `SubstrateConfig.reason_morphology` — the seam field (default
  `GENERIC_REASON_MORPHOLOGY`), readback in `dos.toml [reasons.morphology]` as an
  ordered list of `{substring, cause}` (the same closed-enum→declared-data pattern
  as `[stamp]`/`[reasons]`; `docs/HACKING.md`).
- `resolve_cause` gains the rung 2 fallback between the registry check and
  `UNCLASSIFIED`, and returns `(cause, cause_source)`.
- `PickerVerdict.cause_source` + serialization + report column.
- Tests: pin the three rungs, the self-reporting, rule-order precedence, and the
  litmus that `GENERIC_REASON_MORPHOLOGY` names no host lane (the
  reason-class analogue of "kernel imports no host", grep-checkable like the
  shipped-skill test).

## 5. Why this is the right *next* step, not gold-plating

The proof (`dispatch-os-proving-the-supervision-ratio.md` §8 action 3) names
vocabulary reconciliation as the gate between *less-vacuous* recall (today, 37%
verifiable) and *biting* recall. This design is that gate done **generically**: it
closes ~78% of the residual drift for `job` **and** for any future host **with one
kernel default + a data seam**, instead of N hosts each hand-enumerating an
infinite token set. It is the smallest change that respects docs/76 and actually
makes recall load-bearing — after which a *second* Arm A run yields the first
honest before/after supervision ratio the contractibility claim lives or dies on.

The 7 tokens the rung still can't place are a feature: they are where the oracle
**should** abstain, and where the `cause_source="none"` floor correctly routes a
human. The design removes the *mechanical* blindness and concentrates the residue
on the genuinely ambiguous — the same shape as the whole proof's thesis (§7.2:
remove the mechanical tax, concentrate the human on the irreducible).

## 6. Built and measured (2026-06-02)

Shipped: `dos/reason_morphology.py` (the pure leaf — `MorphologyRule` /
`MorphologyRuleset` / `GENERIC_REASON_MORPHOLOGY` / `NO_REASON_MORPHOLOGY` /
`load_from_toml`), the `resolve_cause_with_source` three-rung resolver +
`cause_source` on `PickerVerdict`, the `SubstrateConfig.reason_morphology` seam
with `[[reasons.morphology]]` readback, and 18 tests (leaf, ladder, seam,
no-host litmus). Full suite **989 green**.

Re-running Arm A with the full recognizer active completes the progression the
two fixes produced on `job`'s corpus:

| Stage | Verifiable NO-PICKs | UNCLASSIFIED | New rung |
|---|---|---|---|
| Raw (exact only) | 25% | 75% | — |
| + prose-fallback (`5de7e28`) | 37% | 63% | recovers the dropped field |
| **+ morphological rung** | **63%** | **36%** | classifies the legible tail |

The `cause_source` split on the final run: **exact 33 · morphological 17 · none 29**
— the rung-2 recognizer classified 17 NO-PICKs the exact rungs missed, and the 29
`none` are the genuinely-ambiguous tail where abstention is correct (the honest
floor, working). The blind spot fell from **75% → 36%**: the oracle now grades
nearly two-thirds of stop-decisions, and the newly-visible causes are the
diagnostic ones (`STALE_CLAIM` 25, `OPERATOR_GATE` 19).

**What this does and does not settle.** It makes recall *far less vacuous* (graded
over 63% of NO-PICKs, not 25%) — but recall is still `1.0` on this corpus because
`oracle_disagrees` is still 0: even seeing two-thirds of the decisions, no
fake-DRAIN surfaced. So the recognizer work is **done**; whether the supervision
ratio *bites* now depends on whether the picker actually errs on this workload —
which is the honest, falsifiable state, and exactly what the cross-checks (now
reaching 64% more decisions) are positioned to detect when it does. The remaining
36% `UNCLASSIFIED` is a mix of truly-token-absent rows and genuinely-ambiguous
shapes; a host can shrink its own slice further by declaring
`[[reasons.morphology]]` for its dialect (`APPLY_LANE_BLOCKED_MESH` →
`OPERATOR_GATE`, etc.) — the seam doing its job, no kernel change.

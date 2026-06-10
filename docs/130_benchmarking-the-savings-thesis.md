# 130 — Benchmarking the savings thesis

> **[docs/128](https://github.com/anthony-chaudhary/dos-private/blob/master/128_the-ultracode-economics-and-how-the-kernel-saves-spend.md) claims the kernel lets a host *not spend*. This doc designs how to
> measure that — honestly.** _(docs/128 relocated to the `dos-private` repo; the
> `docs/128 §N` shorthand throughout this doc refers to it there.)_ The hard part is not building a simulator; the repo
> already has one (FleetHorizon) and a real token oracle (`trajectory_audit`).
> The hard part is that FleetHorizon's cost model is *deliberately abstract*
> (`COST_PER_ACTION = 1.0`, "read as cents, tokens, or seconds", uniform across
> arms) — so it cannot, today, price the *token* thesis at all. The benchmark is
> therefore two-pronged: **(A)** give the existing simulator a model-aware cost
> vector so its honest 0.81×→2.89× edge can be denominated in Opus dollars, and
> **(B)** wire the *real* trajectory-token telemetry into a with-DOS-vs-without
> A/B so the headline number is *billed tokens*, not action-units. Prong B is the
> only one that answers docs/128 non-synthetically, and it is the DOS-shaped move:
> measure the effect, don't trust the model of it.

Design-only. No code lands with this doc. Cross-refs: docs/81 (velocity
economics — the cost-model lineage), docs/98 (the orchestrator-is-a-driver A/B),
docs/128 (the savings thesis being measured), and the existing
`benchmark/fleet_horizon/` + `scripts/trajectory_audit.py`.

---

## 1. What already exists (the factual inventory)

Don't design in a vacuum — two assets already exist, and the design is mostly
*wiring them together*, not greenfield.

### 1.1 FleetHorizon — a synthetic believe-vs-adjudicate A/B

`benchmark/fleet_horizon/` runs two arms (`open_loop` = believe, `closed_loop` =
adjudicate) over the **same seeded workload + same `FailureModel`**, and scores
both with **one pure function** (`metrics.score`, so no per-arm scoring tilts the
A/B). It is a **synthetic simulation**, not a real-agent run: a "tick" is a costed
worker *action* (`Event(kind="action")`), and the failure model injects lies /
overwrites at a seeded rate (`lie_rate=0.12`, `shared_ratio=0.25-0.3`). Entry:

```
PYTHONPATH=src python -m benchmark.fleet_horizon.harness --efforts 6 --phases 20
PYTHONPATH=src python -m benchmark.fleet_horizon.harness --sweep      # gap vs horizon×fleet
```

Its metrics are genuinely good for **three axes** — integrity (`lie_rate`,
`defect_adjusted_verified_per_dollar`), velocity (`human_review_fraction`,
`verified_velocity_per_dollar`), and orchestrator (`prevention_rate`) — and it
ships its own falsifier (the gap → 0 as fleet/horizon → 1, where DOS is pure
overhead). The believe-vs-adjudicate edge it reports (0.81×→2.89× over horizon;
review fraction 100%→~22%) is real *for those axes*.

### 1.2 The cost model is model-blind (the gap docs/128 §9 named)

`metrics.py:20` — `COST_PER_ACTION = 1.0`, uniform across arms by design (§6.2
steelman: don't give the closed loop free verification). Every action costs the
same **whether it is a Haiku grep or a cold-context Opus fan-out**. The model
knows nothing about:

- the **Opus rate** ($5 in / $25 out per MTok),
- the **parent-context re-payment** (each child re-pays ~120K input tokens),
- the **5-minute cache TTL** (a pause >5 min reprocesses the prefix at 12.5× the
  read rate),
- the **model ladder** (Sonnet ~1.67× cheaper, Haiku 5× cheaper than Opus).

So FleetHorizon's "verified-per-$" is verified-per-*action-unit*. It cannot speak
to docs/128's token thesis. This is not a bug — it is the boundary of what a
flat-cost simulation can claim, and exactly what limits #5 and #11 of docs/128 §9
were honest about.

### 1.3 There is already a REAL token oracle in the repo

`scripts/trajectory_audit.py` parses **actual Claude Code session `.jsonl`** and
sums ground-truth usage per session: `input_tokens`, `cache_creation_input_tokens`,
`cache_read_input_tokens`, `output_tokens` (`trajectory_audit.py:244-247`), and
already derives `billed_input`, `cache_read`, and a cache **`miss_ratio`**
(`trajectory_audit.py:290-292`). `loop_decide.py:839` even cites a measured
"~26M cache-read tokens / ~$7.80 in one run." **The repo can already see real
dollars** — it just never multiplies the token vector by a price, and never
diffs two task-matched runs. That is the wire Prong B adds.

---

## 2. The measurement problem, stated precisely

docs/128's levers are **advisory and host-realized**: DOS emits a verdict; a host
*choosing to honor it* is what saves money. So the unit of comparison is never
"DOS vs no-DOS" in the abstract — it is **{a host that honors the verdict} vs {the
same host that ignores it}**, on the **same task, same seed, same model tier**.
Every prong below holds that invariant. Three consequences:

1. **The arms must differ only in compliance.** Same workload, same failure
   injection, same model assignment. The saving is "what the verdict let the
   compliant arm skip," nothing else. (FleetHorizon already enforces this for the
   synthetic case; Prong B must enforce it for the real case.)
2. **Each lever needs its own falsifier.** docs/128 §9 says the magnitude is
   bounded and often ~0 (healthy runs, single loops, named lanes). A benchmark
   that can't report "≈0 saving here" is rigged. Every cell ships its null case.
3. **Synthetic dollars are an illustration; billed dollars are the claim.** Prong
   A produces a *defensible illustration* (Opus-denominated, but over simulated
   actions). Prong B produces *the claim* (real billed tokens). The doc must never
   let A's number masquerade as B's — the docs/128 §9 #11 discipline.

---

## 3. Prong A — give FleetHorizon a model-aware cost vector

**Goal:** turn the abstract action-unit into Opus-denominated tokens, so the
existing 0.81×→2.89× edge can be *illustrated* in dollars, and so two new
docs/128 levers (smaller-model routing, resume-the-residual) become measurable.

**Minimal change, maximal reuse.** Do NOT rewrite the simulator. Replace the
scalar `COST_PER_ACTION` with a **cost function over the event**, defaulting to
1.0 so every existing test stays green:

```
# illustrative shape, not final code
@dataclass(frozen=True)
class CostVector:
    in_tok: int          # input tokens this action paid
    out_tok: int         # output tokens emitted
    cached_in_tok: int   # of in_tok, how many hit cache (0.1×)
    tier: str            # "opus" | "sonnet" | "haiku"

PRICE = {  # $/MTok, docs/128 §1, source: platform.claude.com/.../pricing
    "opus":   (5.0, 25.0),
    "sonnet": (3.0, 15.0),
    "haiku":  (1.0, 5.0),
}
def dollars(cv: CostVector) -> float: ...   # applies tier rate + 0.1× cache mult
```

Then attach a `CostVector` to each `Event` (a flat default for legacy kinds keeps
`score` byte-compatible). This lets the simulator express the docs/128 cost
*structure*, not just count actions:

| docs/128 lever | New event kind / cost shape | What the cell shows |
|---|---|---|
| **§4 smaller-model** (ORACLE→JUDGE) | a verification action priced at `tier="haiku"` or `$0` (deterministic oracle) vs `tier="opus"` | $ saved per adjudication by routing the residue, not the full set |
| **§3 resume-residual** | a "restart" event re-pays the whole effort's token sum; "resume" re-pays only the residual tail (`declared − verified`) | $ saved on an interrupted long-horizon run (the biggest single lever) |
| **§1 context re-payment** | per-spawn `in_tok += PARENT_CTX` (≈120K) unless a fork/cache flag is set | how the per-child re-payment scales the believe arm's loaded cost |
| **§2 stop-on-SPINNING** | the spinning arm emits N extra `action`s before the iteration cap; the compliant arm stops at the SPINNING verdict | $ saved = (capped − spun) × per-iteration cost, **0 on healthy runs** |

**Headline:** re-run the existing `--sweep` but report `loaded_cost` and
`verified_velocity_per_dollar` in **dollars** (tier-weighted), with the
smaller-model and resume levers toggled on/off. The number to publish is the
*ratio* (compliant/non-compliant), because the absolute dollars are
parameter-driven and the ratio is what survives a skeptic swapping the constants.

**Falsifiers Prong A must ship (or it's rigged):**
- horizon=1, fleet=1 → ratio → 1.0 (DOS is pure overhead; already FleetHorizon's
  built-in falsifier — keep it).
- resume lever with the run *completing* normally → 0 saving (nothing to resume).
- smaller-model lever when the oracle ABSTAINS on everything → 0 saving (the
  JUDGE pays full Opus anyway).
- The cache-TTL re-payment with a fork/cache flag set → saving collapses (the
  documented `CLAUDE_CODE_FORK_SUBAGENT` mitigation; docs/128 §1).

**What Prong A still CANNOT claim:** that real ultracode runs spend these tokens.
The token counts are still *modeled* (a `PARENT_CTX` constant, a `lie_rate`). It
is a defensible illustration of the cost *structure*, denominated honestly — not a
measurement. Label every Prong-A figure "simulated, Opus-denominated."

---

## 4. Prong B — the real-token A/B (the actual claim)

**Goal:** the headline docs/128 number must be **billed tokens from real runs**,
not action-units. The repo already has the oracle (`trajectory_audit`); the
design is a task-matched A/B that feeds it.

### 4.1 The shape

Pick a small fixed battery of **real tasks** (e.g. 5–10 self-contained changes in
a throwaway fixture repo, each with a knowable "done" the deterministic oracle can
confirm). For each task, run it **twice under a real ultracode host**:

- **Arm IGNORE** — the host runs the fan-out with DOS verdicts *not* wired in
  (today's default: no `dos verify` short-circuit, no SPINNING stop, no resume,
  every adjudication goes to the model).
- **Arm HONOR** — the *same* host, same task, same seed/model, with the DOS levers
  wired: `dos verify` answers "did it ship?" before the model re-reasons it;
  `loop_decide`'s SPINNING/DRAINED_TWICE stop the loop; `dos resume` re-dispatches
  only the residual after an injected mid-run kill; the JUDGE is consulted only on
  the oracle's abstained residue.

Then **diff the trajectories** with `trajectory_audit`: the metric is
`Δ billed_input + Δ output + Δ cache_creation`, converted to dollars by the §3
`PRICE` table. That Δ **is** the docs/128 saving — measured, per lever, on real
billed tokens.

### 4.2 Why this is the DOS-shaped move

docs/128's whole thesis is *measure the effect, don't trust the self-report*.
Prong B applies that to the benchmark itself: it does not trust a *model* of token
spend (Prong A); it reads the **un-authored fossil** — the session `.jsonl` the
host wrote as a byproduct, exactly the "byte-author ≠ judged agent" evidence rung
from docs/117. The benchmark's own ground truth is gathered the way the kernel
gathers ground truth.

### 4.3 The per-lever attribution problem (and the honest answer)

If you wire all levers at once, you measure their *sum*, not each. To attribute
per-lever (docs/128 §9 #11: "no benchmark attributes a saving to the SPINNING
lever specifically"), run HONOR as an **ablation ladder** — IGNORE, then +verify,
then +SPINNING-stop, then +resume, then +smaller-model — and diff *adjacent* rungs.
Each rung's Δ is that lever's marginal saving. This is more runs (k+1 per task) but
it is the only way the headline can say "resume saved X, stop-on-spin saved Y"
instead of an unattributable lump.

### 4.4 The falsifiers Prong B must ship

- **The healthy-run null.** A task that ships cleanly first try: HONOR ≈ IGNORE
  (verify short-circuits nothing it wouldn't, nothing spins, nothing resumes). If
  HONOR isn't ~equal here, the wiring is *adding* cost — report it.
- **The single-loop null.** No fan-out → arbitrate/collision levers save nothing
  (docs/128 §9 #8).
- **The named-lane null.** Class budgets + auto-pick bypassed by `--force`/named
  lane → 0 (docs/128 §9 #7).
- **The honor-cost line.** HONOR pays for the verdicts (every `dos verify` is a
  subprocess; every HEARTBEAT is a write). The benchmark must *charge* HONOR for
  this (it is tokens/wall-clock the host spent), or it gives DOS free verification
  — the §6.2 discipline FleetHorizon already respects. The expectation is this
  cost is milliseconds/zero-model-tokens (docs/128 §5), but **prove it, don't
  assume it.**

### 4.5 The cost and the honest caveat

Prong B is **expensive** — it runs real Opus fan-outs, k+1 times per task, twice
(both arms). That is the irony worth stating in the doc: *measuring the
cost-savings thesis costs real Opus dollars.* Budget it as a small battery (5–10
tasks), run under the Batch API (−50%) where possible, and treat it as a
*periodic* measurement (a release-gate artifact), not a per-commit CI run. The
sample is small, so report it as **point estimates with the task battery named**,
never as a population claim — the docs/128 §9 #11 discipline made structural.

---

## 5. The third prong, free: harvest the trajectories you already have

Prong B's fixture battery is the *controlled* experiment. But there is an
*observational* dataset sitting on disk already: every Claude Code session that
has ever run in this repo, with full token telemetry, joinable to the **lane
journal + run-id spine** (the `/trajectory-audit` skill already does this join).

So a **zero-new-cost** measurement: over the existing session corpus, the
trajectory-audit already flags `cache_miss`, `read_loop`, `shell_poll`,
`keepalive_poll` (the waste classes). Cross-reference those flagged sessions
against the kernel artifacts — *was the kernel emitting a SPINNING/refuse verdict
during the window the session was burning tokens?* If yes, that is an
**observed** instance of "the verdict that would have saved this spend, had the
host honored it" — the narration-vs-ground-truth divergence the trajectory-audit
skill is built to surface, now priced in dollars via the §3 table.

This prong cannot prove causation (no control arm), but it **sizes the
opportunity** on real historical spend at zero marginal API cost, and it is the
cheapest thing to build first — it is mostly "multiply the existing
`trajectory_audit` token rollup by `PRICE`, and join to the journal." It also
dogfoods the thesis: the audit of *our own* token waste becomes the first
estimate of what the levers are worth.

---

## 6. Build order (cheapest-first, each independently shippable)

1. **Prong C (observational, ~hours). — PARTLY BUILT (2026-06-03).** Add a `PRICE`
   table + a `--dollars` rollup to `trajectory_audit`, and a join that flags
   "kernel emitted a savings-verdict during a high-waste session window." Zero API
   cost; sizes the opportunity from history. Ships as a dev-tooling change (outside
   the kernel — it operates *on* the package, like the release scripts).
   **Shipped:** `scripts/trajectory_audit.py` now carries a pure
   `price_tokens(tokens, price)` (default = Opus 4.8 list, overridable via
   `--price-in/--price-out/--price-cache-read`), the `rollup` emits a `spend` block
   (per-category $ + **`cache_miss_premium`** = the avoidable cold-reprocess
   overpay, the docs/128 §1 5-min-TTL lever priced on the window's own spend), and
   the report renders a "Token spend (priced)" section + a heaviest-by-spend table
   (5 new tests in `tests/test_trajectory_audit.py`). First live run over 40 of this
   repo's own sessions: **~$270 priced spend, ~$70 (26%) of it the cache-miss
   premium.** **Still TODO:** the kernel-verdict join is the *opportunity-sizing*
   half — the existing `contention_vs_waste` join surfaces refusal-during-waste, but
   "a SPINNING/refuse verdict was live during a high-$ waste window" needs the
   dispatch path to emit HEARTBEAT/SCAVENGE journal ops (the report already says so),
   so the priced-waste×verdict cross-signal is not yet wired.
2. **Prong A (synthetic, ~day).** Replace `COST_PER_ACTION` scalar with a
   `CostVector`/`dollars()` function (default 1.0 → all tests green), add the four
   lever event-shapes from §3, re-run `--sweep` in dollars with per-lever toggles +
   the §3 falsifiers. Lives in `benchmark/fleet_horizon/` (already outside the
   kernel boundary).
3. **Prong B (real, ~periodic, $$).** Build the fixture battery + the
   ablation-ladder runner + the trajectory-diff. This is the claim; gate it as a
   release artifact, run it under Batch, report point estimates with the battery
   named. Its honest limits (small sample, list-price conversion, honor-cost
   charged) are carried inline.

None of the three touches a `src/dos/` kernel module — the cost model and the
benchmark are *consumers* of the kernel (the docs/98 "orchestrator is a driver"
and the release-tooling "operates on the package" boundary). The kernel emits the
verdicts; the benchmark prices what honoring them saved.

---

## 7. The one-paragraph synthesis

The savings thesis is measurable in three escalating tiers of confidence, each
shipping its own null case. **Observe** (Prong C): price the token telemetry we
already have and join it to the kernel's verdicts — zero cost, sizes the prize,
proves nothing causal. **Illustrate** (Prong A): give the existing honest
simulator an Opus-denominated cost vector so its 0.81×→2.89× edge speaks in
dollars and the smaller-model/resume levers become visible — defensible, but
modeled. **Measure** (Prong B): run the same real tasks with vs without the
verdicts wired, as an ablation ladder, and diff the *billed* tokens — the actual
claim, expensive, small-sample, honest about it. The discipline throughout is the
kernel's own: the arms differ only in *compliance with the verdict*, the headline
is the *ratio*, every lever ships a falsifier, and the ground truth is the
un-authored fossil (the session `.jsonl`), never the host's self-report about what
it saved. Measuring DOS the way DOS measures everything else is the point — and
the fact that the highest-confidence tier costs real Opus dollars is the thesis,
restated: the cheapest token is the one a verdict told you not to spend, and to
*prove* that you have to spend a few.

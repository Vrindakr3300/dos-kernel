# Out-of-loop live-payoff experiment registry

> Companion to `docs/209`. The modular, independently-runnable spec for every
> out-of-loop value experiment designed + adversarially verified this session
> (`wf_5c5629f4`, 2026-06-07). Each entry is a "found item" you can pick up and run.
> **Read `docs/209` for the framing** (the re-projection trap, the triple constraint,
> the gap numbers). This file is the operational index.

> **✅ ITEM 1 (E-TAU2-WRITEADMIT) WAS BUILT + RAN LIVE — see [docs/228](../../docs/228_running-tau2-writeadmit-live-the-out-of-loop-payoff-measured.md)
> (2026-06-08).** Outcome: the gate caught + blocked **J = 5** real over-claims off the
> tau2 env DB-hash on a fresh **natural** sample (the projected `J ≈ 8–20` row below was a
> per-100-task guess; the realized rate is **11.6%** over 43 clean tasks). Two corrections
> the run forced on the spec: (1) the tau2 entry is **`run_single_task`**, not `run_task`
> (this registry + docs/216 had it backwards); (2) re-running the *frozen over-claim slice*
> live gives **J = 0** — over-claims evaporate under a capable policy, so the natural draw
> (Item rationale below) is the right harness, not the frozen indices. Cost was **$0.89**,
> not the ~$80–200 estimate (Gemini-2.5-flash + a 50-task sample is cheap).
>
> **✅ ITEM 2 (E2L-1, the RLVR/lab twin) — Payoff 1 now BUILT + MEASURED on those rows; see
> [docs/230](../../docs/230_the-lab-facing-twin-rlvr-admit-the-non-distillable-reward-label.md).**
> Re-folding the docs/228 live rows through a reward-set admission filter (the last function
> only — `writeadmit/rlvr_admit.py`) turns the J=5 over-claims into **5 poison reward-labels**
> a naive self-judged RLVR loop banks as positives, purged by a non-distillable env-grounded
> label: acceptance precision **60%→100%**, ΔP **+40 pp**, $0. Item-2 **Payoff 2** (the
> trained-behavior delta J₂, needs a GPU) remains unbuilt.
>
> **✅ ITEM 4 (the multi-agent coordination A/B) — BUILT + RAN LIVE; see
> [docs/233](../../docs/233_the-coordination-payoff-measured-live-arbiter-prevents-clobbers.md)
> (2026-06-08).** The OTHER value half-plane (referee-BETWEEN-AGENTS, the sibling of Item 1's
> referee-over-claims). Two live Gemini agents conflict on a shared tau2 reservation (A1
> cancels R; A2 adds a bag), A2 re-run against A1's committed state (the causal serialized
> outcome). The naive blind compose corrupts the DB; the arbiter, refusing the 2nd concurrent
> lease on `reservations/<id>`, prevents it → **J = 6** clobbers over 8 pairs (+ 2 honest
> non-clobbers: a falsifier where the agent declined, a variance case the directional-J fix
> excludes). Witness = the gold DB-hash; the "key→region mapper" the spec called hard is one
> line. `writeadmit/coord_loop.py`, ~$1.5. Pair with docs/190's measured RATE.
>
> **▶ FLEET-SCALE PROGRAM (docs/245) — the next frontier beyond the per-event payoffs.** The
> two results above are per-EVENT (J=15, J=6); docs/245 takes them to fleet scale, where the
> number is COMPOUNDING corruption averted, not events. **F1 RAN
> ([docs/251](../../docs/251_f1-the-cascade-runs-corruption-compounds-the-gate-stops-it.md),
> `writeadmit/cascade_loop.py`):** a poison handed down a chain of live agents stays corrupt at
> every node under believe (D−1; the agents do NOT self-heal a corrupt *state*) and 0 under
> adjudicate — compounding CONFIRMED live, payoff grows with depth. **F1-super-linear ALSO RAN
> ([docs/253](../../docs/253_f1-super-linear-the-fanout-tree-payoff-grows-f-to-the-d.md)):** the
> fan-out tree — every leaf corrupt under believe (**F^D**: payoff 4 at depth 2, 8 at depth 3),
> 0 under adjudicate — the payoff is SUPER-LINEAR live (F^D vs D−1; honest scope = breadth
> fanout, agents blocked by the shared poison, not value-amplification). **CURRENT NEXT STEP =
> F2** (a NATURAL collision stream — K=4..16 live agents on a shared DB, collisions falling out
> of the task distribution, no pinning — kills the constructed-conflict objection O2). Still
> unbuilt elsewhere: Item-2 Payoff 2 (the GPU-trained behavior delta).
>
> **▶ ITEM 1's *commons-causal* fork — see [docs/229](../../docs/229_the-peer-b-handoff-making-J-causal-plan.md)
> (plan; the $0 constructor shipped).** docs/228's J=5 is a *counted* inheritance — the gate
> blocked 5 phantom writes, but no second agent ran on what it published. docs/229 wires a real
> downstream **peer B** that inherits the gate's output and turns J into a measured
> **ΔB = success(B|adjudicate) − success(B|believe)** on the over-claim slice (control: ΔB≈0 on
> the 9 honest rows, by construction). Where docs/230 takes Item 1's verdict to the *lab*
> (reward set), docs/229 takes it to the *commons* (peer handoff) — same witness, two consumers.
> **Shipped:** `writeadmit/peer_b.py` (the Design-A handoff/arm constructor + control invariant,
> 9 tests, $0). **Pending:** the paid live B run (~$0.40) + the ΔB fold. This is the *causal*
> deepening of Item 1 the registry previously folded loosely under Item 4's coordination A/B.

## Legend

- **verdict** — `live-payoff-real` (survives both traps), `live-but-weak-witness`
  (live but the witness adds ~0 over the benchmark's own construction),
  `secretly-static-reprojection` (claims live, actually re-projects a frozen field
  → 0 new labels, docs/179), `unbuildable-now` (needs external compute/keys),
  `refuted`.
- The **triple constraint**: (a) consumer ≠ producer, (b) independent byte-author
  witness, (c) live via API. See `docs/209` Module 2.

## The whole set (15), ranked by payoff-shown-per-dollar

| rank | id | family | benchmark | verdict | cost | conf |
|---|---|---|---|---|---|---|
| **1** | **E-TAU2-WRITEADMIT** ✅RAN | commons write-admission | tau2 | **live-payoff-real → J=5 (docs/228)** | **$0.89** actual | 1.0 |
| **2** | **E2L-1** ✅P1-RAN | training-label (Family C) | tau2 | **live-payoff-real → J=5 poison purged, ΔP+40pp (docs/230)** | **$0** (P1) | 0.85 |
| 3 | E2 ✅RAN | coordination | tau2 | **live-payoff-real → J=6 (docs/233)** | **$1.5** actual | 1.0 |
| 4 | E-TAU2-WRITE-ADMISSION | commons + coordination | tau2 | live-but-weak-witness | medium | 0.74 |
| 5 | E1 | commons write-admission | tau2 | live-but-weak-witness (reproj-caught) | medium | 0.78 |
| 6 | E2L-2 | reward-hack refusal | ImpossibleBench | live-payoff-real* | ~$100–300 | 0.70 |
| 7 | E-IB-LIVE | reward-hack refusal | ImpossibleBench | live-but-weak-witness | ~$30–120 | 0.72 |
| 8 | E3 / E-IMPOSSIBLE-REFEREE / IB1 / IB2 / IB3 | reward-hack tail | ImpossibleBench | live-but-weak / reproj | varies | 0.7–0.8 |
| — | E-SWE-MERGEGATE | downstream-gate | SWE-bench Verified | **secretly-static-reprojection** | expensive | 0.78 |
| — | E2L-3 | training-label | built-on-oracle | **unbuildable-now** (needs GPU/SFT) | external | 0.55 |
| — | E-PRECHECK-OVERCLAIMGAP | the $0 build-gate | published logs | (out of competition) | $0 | 0.9 |

\* `E2L-2` is `live-payoff-real` on its own JSON but **degenerate as a DOS proof**:
the one live-measured quantity (LLM-judge false-accept ~0.35–0.55) is real, but the
deterministic "0" half is the *benchmark's* scorer, not DOS's `verify()`, and it
duplicates G3. Treat as a slide, not a DOS payoff. See `docs/209` §3.2–3.3.

---

## ITEM 1 — `E-TAU2-WRITEADMIT`  🏆 BUILD THIS

- **family:** commons write-admission · **benchmark:** tau2-bench
- **consumer (≠ producer):** the state-commit / peer that inherits the "resolved" ticket
- **witness (independent):** the gold **DB-hash** gold-replay — least-gameable available
  anywhere; the agent authors zero bytes of a hash
- **triple constraint:** (a) PASS (b) PASS (c) PASS
- **live design:** two arms over identical runs, Gemini drives policy + user-simulator.
  `believe` commits the write whenever the agent claims resolved; `adjudicate` commits
  iff `db_hash == gold`, else holds / routes-to-human. The consumer acts differently per
  arm → a real flipped outcome.
- **pre-registered PAYOFF (a measured integer, no κ/μ):**
  `J = count( agent_declared_resolved AND db_hash ≠ gold )` blocked before a peer
  inherits the write. Honest expected magnitude: raw mismatch ~25–40/100; confident
  over-claim slice **J ≈ 8–20**.
- **$0 pre-check that gates the build:** join "agent declared resolved" vs "DB-hash ≠
  gold" over the in-repo frozen tau2 corpus (`benchmark/agentprocessbench/dataset.py`,
  ~250 trajectories). **KILL if the confident-over-claim slice < ~5%.**
- **build:** `git clone sierra-research/tau2-bench` (⚠ **NOT** `pip install tau2` — that
  is an unrelated magnetic-relaxation squatter). Run the **deterministic config only**
  (DB-hash + substring COMMUNICATE; exclude the LLM-judged NL-assertions). Wrap Gemini
  with the `live_ab.py` `langchain_google_genai` glue. Admission shim = copy
  `dos.effect_witness` / `witness_effect` (the CONFIRMED/REFUTED claim-vs-readback join).
  **No kernel change.**
- **cost:** ~$80–200 (Gemini, dual-role ~2× tokens). Wall-clock 2–4 days incl. standup.
- **kill criterion:** $0 pre-check slice < ~5%, OR a 10-task dual-Gemini smoke run shows
  `J = 0`.
- **honest ceiling:** a **buyer/commons-integrity** result (a measured count of caught
  over-claimed commits), not a frontier-lab science result. The dollar figure still
  half-imports a per-false-resolution cost — keep it out of the headline.

## ITEM 2 — `E2L-1`  ✅ PAYOFF-1 BUILT + MEASURED LIVE (docs/230); lead with this for a LAB audience

> **✅ The $0 acceptance-precision arm RAN on the docs/228 live rows — see
> [docs/230](../../docs/230_the-lab-facing-twin-rlvr-admit-the-non-distillable-reward-label.md)
> (2026-06-08).** The Item-1 adapter (docs/228) is the shared build; this fork is
> `writeadmit/rlvr_admit.py` (the last function only). Result on 49 clean live rows: of 15
> confident "resolved" write-bids a naive self-judged sampler banks as positives, **5 are
> poison** (the env DB-hash refutes), purged by the witness-gated filter — **acceptance
> precision 60%→100%, J=5 poison purged, ΔP=+40 pp**, all off a label the policy cannot
> distill (the believe_under_floor floor, pinned by `test_rlvr_admit.py`). The "soft spot"
> below (the adjudicate arm drifts toward a self-report rate) is **resolved**: the headline
> is now *acceptance-precision lift on a non-distillable label*, not a raw over-claim rate.
> **Payoff 2 — HARNESS BUILT + $0 SIGNAL MEASURED, weight-update BLOCKED (docs/250):** the
> focused claim-head SFT pipeline (`rlvr_train`/`rlvr_vertex`/`rlvr_eval`/`rlvr_run`, +tests)
> is built and the trained-behavior signal is shown to SEPARATE strongly at $0 — the
> in-context proxy (poison 100% vs clean 40% = **+60 pp**) and the base control (un-tuned
> gemini-2.5-flash over-claims **0/4** given honest facts, so any over-claim is *learned*). The
> real Vertex `gemini-2.5-flash` tune itself **wedged at ingestion twice** (`tuningDataStats`
> never populated; a backend/new-project issue, NOT a format/auth defect — a `role`-on-
> systemInstruction bug was found+fixed but did not change it), so the **weight-update** J₂
> stays open and the arm is left one command from running (a dedicated GCP project,
> datasets staged in GCS). Not "needs a GPU" — managed Vertex tuning was the path; it's a
> backend wedge to retry on a warmed project.

- **family:** training-label (docs/206 Family C) · **benchmark:** tau2
- **consumer:** a rejection-sampling admission filter (RL/SFT stand-in)
- **witness:** same gold DB-hash (the NARROW write-correctness bit, not the composite reward
  — keyed on `db_match`, the least-gameable sub-witness; docs/230 §4a)
- **payoff:** acceptance precision of the *admitted corpus* — believe-select vs
  adjudicate-select, adjudicated by the independent witness. **Payoff 1 (label quality) =
  done live (docs/230); Payoff 2 (trained behavior) = harness built + $0 proxy/base signal
  measured (+60pp / 0-4, docs/250), the weight-update tune wedged on Vertex (open, retryable).**
- **why it hedges:** same tau2 adapter as Item 1 (shared build), but the consumer is the
  frontier-lab half-plane (the non-distillable RLVR label, docs/206 E1/E2).
- **soft spot (RESOLVED in docs/230):** the adjudicate arm is ~0-poison by construction, so
  a raw "over-claim rate" headline would drift toward self-report — re-aimed at the
  **acceptance-precision LIFT (ΔP) + poison-purged count (J)**, which is a flipped label-set
  composition, not a re-projected rate.
- **cost:** Payoff-1 was **$0** (re-folds the docs/228 rows); Payoff-2 ~$150. **needs:** the
  Item-1 adapter (done).

## ITEM 3 — `live_orchestrator_demo`  ⭐ RUN FIRST ($0, already in repo)

- **not a candidate — a pre-existing asset the completeness critic surfaced.** All file
  claims verified 2026-06-07.
- **what it is:** a real cross-process believe-vs-adjudicate concurrent-write A/B — real
  `dos lease-lane` across real OS processes, ground truth off git, reports
  clobbers-prevented, **zero model tokens**.
- **run:**
  `DOS_LIVE_DEMO=1 PYTHONPATH=src python -m benchmark.fleet_horizon.live_orchestrator_demo --issues 3 --overlap 2`
- **why first:** de-risks the expensive tau2 shared-DB coordination build (Items E2 /
  E-TAU2-WRITE-ADMISSION). If the naive arm doesn't lose a line, the coordination lift is
  moot; if it does, you have hand-checkable live evidence the corruption gap exists.
- **file:** `benchmark/fleet_horizon/live_orchestrator_demo.py`

## ITEM 4 — `E2` (coordination; the one that exercises DOS's *distinctive* mechanism)

> **✅ BUILT + RAN LIVE 2026-06-08 — J=6, see [docs/233](../../docs/233_the-coordination-payoff-measured-live-arbiter-prevents-clobbers.md)** (`writeadmit/coord_loop.py`). The spec below stands; the realization used the
> tau2 airline DB with a `reservations/<id>` region and a re-run-A2-after-A1 causal serial arm.

- **family:** coordination · **benchmark:** tau2 (or SWE-bench repo)
- **consumer:** the shared DB + every peer whose write would be clobbered
- **witness:** `dos.arbiter` disjointness (pure) **+** gold DB-hash as the outcome
- **payoff:** corruptions structurally prevented by the arbiter on N concurrent live
  agents (both-applied hash vs serialized hash — a fresh execution, NOT a multiply of
  the frozen "26").
- **build (the hard lift):** N agents on the SAME DB fights every harness; needs a
  key→region mapper. **De-risk with Item 3 first.**
- **caveats:** collision rate risks 0 on a natively single-agent benchmark (fleet=1 wall,
  docs/204 §1) — report the live overlap rate as a first-class measured number. Pair the
  PAYOFF with the already-measured RATE from docs/190 (labeled separately).

## ITEMS 5–8 — the DEMOTED set (do not build as value experiments)

- **`E-SWE-MERGEGATE` (secretly-static-reprojection):** its "downstream P2P regressions"
  re-project the gold P2P field already on disk (SWE-bench runs F2P+P2P in one eval, no
  sequential dependent). The *sound* version is the docs/206 §5c verify-gated best-of-N
  (delivered-rate-per-spend) — but it needs a frontier coder key the repo lacks.
- **ImpossibleBench family (`E-IMPOSSIBLE-REFEREE`, `IB1/2/3`, `E3`, `E-IB-LIVE`,
  `E2L-2`):** the impossibility *construction* (benchmark-authored, not DOS) supplies the
  whole refusal → payoff = cheat-count × 1, a re-projected detection rate that ALSO
  duplicates the already-run **G3** (`g3_forgeability.py`: deterministic 0.000 vs
  LLM-judge 0.352, live). Good slide, not a DOS payoff.
- **`E1` (reproj-caught):** single-agent tau2 headline = `1 − pass@1` (tau2 already
  adjudicates every episode by DB-hash). Only the hand-built downstream-dependent half
  is new, and tau2 ships no DB-carryover.
- **`E2L-3` (unbuildable-now):** the trained-model over-claim delta — the one experiment
  that fully escapes re-projection, but chains two unbuilt harnesses + a GPU/SFT pipeline
  that does not exist here.

## ITEM — `E-PRECHECK-OVERCLAIMGAP` (the $0 build-gate, not a payoff)

- A static re-projection **used correctly**: a GO/NO-GO gate that protects live $ by
  killing a dead experiment before standup. Mints zero value labels by design (docs/179).
  Build the live experiment only for the (benchmark, model-tier) where the published
  over-claim gap is non-trivial (> ~5pp). Partly redundant for ImpossibleBench (cheating
  rate already published > 0). Its in-repo instance is Item 1's $0 pre-check.

---

## The gap numbers (the "45% thing") — quick reference; full treatment in docs/209 §3

| number | what it measures | source |
|---|---|---|
| **0.000** | deterministic floor false-accept (reads the world, asks the model nothing) | `g3_forgeability.py:239` |
| **0.352** | LLM-judge false-accept, **live on Gemini**, gym silent-failure rows | `g3_forgeability.py:241` |
| **~35–55%** | LLM-judge false-accept on fresh ImpossibleBench cheats (judge detection 42–50%) | arXiv 2510.20270 |
| **54% / 93%** | GPT-5 cheat rate, conflicting Impossible-SWEbench / Impossible-LiveCodeBench | arXiv 2510.20270 |
| **~24pp** | METR grader over-optimism (~half of test-passing SWE-bench-V PRs unmergeable) | METR; UTBoost; SWE-ABS |
| **~38%** | frontier goals reaching NO sound witness (the Wall-3 ceiling) | docs/204 §3; docs/192 |
| **AUC 0.909** | ablated non-distillability of the verdict on REAL transcripts (lift +0.172) | docs/206; `verifier.py` |
| **71/71 · 6/13** | pure lies caught vs FLAKES caught (the irreducible residue) | docs/206 §E1 |
| **J = 5 (ran)** | over-claimed writes E-TAU2-WRITEADMIT blocked LIVE off the env DB-hash; 11.6% of 43 clean natural tasks (projected was 8–20/100) | docs/228, 2026-06-08 |

# docs/190 — Coordination, measured; and the F3 gateability split

> (Renumbered 189→190: a concurrent session independently took docs/189 — the
> live cross-session collision this very doc measures, happening to the doc that
> measures it. Yielded the number to keep the namespace unique.)

Companion to docs/188 (which killed the rank-1 agent-side bet on the frontier).
This resolves the two remaining value-capture bets from the conversion-gap
synthesis (`wf_6647ad3c-913`):
- **Bet #2 (coordination):** is the collision footprint real, or only simulated?
- **Bet #3 (F3/PEP):** does a gated write deadlock on the dominant failure?

## Bet #2 — coordination is REAL and MEASURED (not simulated)

**The weakness it answers:** FleetHorizon's coordination numbers (1.32× velocity/$,
human-review 100%→17.1%, collisions 0@N=1→104@N=8) are a proven *mechanism* but
every magnitude rides a **simulated** workload — `workload.generate` plants
collisions via a `shared_pool` + `shared_ratio`, and `agent.py:59` hardcodes
`lie_rate=0.12`. The synthesis verdict: measure the rate, don't claim payoff.

**Method (`benchmark/fleet_horizon/measure_real_collisions.py`, $0, real kernel
logic):** parse every Write/Edit across the operator's real Claude Code fleet
(`~/.claude/projects/<ws>/**/*.jsonl`) into `(session_id, abs_path, timestamp)`.
Two writes COLLIDE when they are from **different sessions**, to a **colliding
path** (the real `_tree.prefixes_collide` — byte-identical to the arbiter's
disjointness test), within a **concurrency window**. This is the empirical N>1
footprint the simulated `shared_ratio` was a proxy for.

**Result (real Opus-4.x fleet, 2,684 transcripts / 4,118 write events / 174
writing sessions):**

| Concurrency window | Concurrent cross-session collisions |
|---|---|
| 10 s | **5** |
| 30 s | 7 |
| 60 s | 9 |
| 120 s | 14 |
| 300 s | 21 |

- **5 unambiguous live races even at a 10-second window**, rising monotonically to
  21 at 300 s. Rate ≈ **5.1 collisions / 1,000 writes**.
- The tightest is **3.3 s apart** on `benchmark/toolathlon/viz.py`. Verified real
  concurrency — two distinct sessions **interleaving** writes:
  ```
  22:22:37.6  session 1bf4017a  → viz.py
  22:22:40.9  session 5a60b6d7  → viz.py   (3.3s later)
  22:22:46.5  session 1bf4017a  → viz.py
  22:23:02.7  session 5a60b6d7  → viz.py
  ```
  A writes, B writes 3.3 s later, A writes again, B again — the lost-update race
  the arbiter's lane lease exists to serialize. Neither agent could see the other.
- The contention surface matches what the simulation hand-planted: `MEMORY.md`
  written by **138** sessions, `cli.py` by **49** — the "shared registry / common
  util" collision area, observed not assumed.
- Kernel sanity: `prefixes_collide` agrees on every collision (the offline measure
  uses the same rule the live arbiter would).

**What this settles:** the coordination axis is no longer simulated — a real
frontier fleet on *this* repo produced ≥5 genuine concurrent same-file collisions.
Critically, this is **frontier-model data**, and unlike defensive lift (0.00pp,
docs/188) the collision rate does **not** decay with capability: a faster model
makes the window *tighter* (3.3 s), the Kingman/Faros amplification the synthesis
predicted. **Detection-on-the-frontier is dead; coordination-on-the-frontier is
real and measured.** This is the RATE half — the honest predecessor to a payoff
claim (which still needs the believed-vs-adjudicated A/B; the one real arc was a
net loss, so payoff stays unproven). Bet #2 survives; its denominator is real.

## Bet #3 — the F3 deadlock fear is PARTIALLY refuted: a gateability split

**The fear (synthesis):** the F3 write-gate (model authors a fix, kernel admits it
vs ground truth) risks **deadlock** on the dominant *upstream-omission* loop — the
agent never looked up an id, so it authors no fix to admit, and the gate refuses
forever (re-becoming the refuted BLOCK author-and-believe trap if it injects the
read itself).

**What the data shows (the dominant NATURAL thrash, `create_filter` ×3 of 5):**
the env's own error bytes are:
```
Invalid Tool Arguments: ['criteria.from: is required', 'criteria.to: is required',
                         'criteria.subject: is required', ...]
```
This is **required-argument-underfill**, NOT invented-FK-omission. The split:

- **Underfill (gateable, the natural-dominant case):** the env's error bytes
  *already name exactly what is missing* (`criteria.from is required`). The model
  CAN author a fix (supply the fields — it has the data), and the gate CAN verify
  it against the *known schema*. No oracle, no held-out state, no deadlock. This is
  the **F2 constrain-and-reissue** rung with the **env supplying the constraint** —
  byte-clean (the agent did not author the "what's required" bytes) and convergent.
- **True omission (deadlock-prone, the MINTED case):** the agent invents a value
  because a *needed read* never happened; the env error (`blocked_unresolved_id`)
  does NOT name the missing read. Here the gate genuinely risks refuse-forever —
  this is the F3 hazard, and it is **specific to the minted regime** (docs/172),
  which fires ~0 naturally on a capable model.

**The reframe:** the F3 deadlock fear conflated two failure shapes. On the
SOTA-relevant natural regime, the dominant failure is **underfill, which is
gateable by the env's own schema-error bytes** — a convergent constrain-and-reissue
loop, not a deadlock. The deadlock hazard is real but lives in the artificial
minting regime the rewind experiment already refuted. So the buildable next step is
narrower and safer than the synthesis feared: **gate the underfill class on the
env's required-field error bytes** (F2, byte-clean, no kernel-authored content),
and route true omission to HUMAN (the irreducible seed), never to a self-injecting
gate. Bet #3 is not a monolithic step-function — it splits into a cheap convergent
sub-case (build) and a deadlock-prone sub-case (defer to human).

## The combined verdict across all three bets

| Bet | Frontier status | Evidence |
|---|---|---|
| #1 agent-side WARN re-surface | **DEAD** (harmless, not lift) | docs/188: 0.2% fire, 0 substantive |
| #2 coordination | **REAL + MEASURED** | ≥5 concurrent collisions @10s, 3.3s tightest |
| #3 F3 gated write | **SPLIT**: underfill gateable, omission → human | env names the gap on the natural-dominant class |

Detection is solved; the agent-action denominator is empirically dead on the
frontier; **value-capture lives off that denominator** — in coordination (now
measured) and in gating the env-named-constraint slice of the fix problem.

## Reproduce

```bash
python benchmark/fleet_horizon/measure_real_collisions.py                 # 300s window
python benchmark/fleet_horizon/measure_real_collisions.py --window-sec 10 # tight: live races
python benchmark/enterpriseops/natural_thrash_counterfactual.py \
    --dir benchmark/enterpriseops/live_results_natural/none                # the failure-kind split
```

Related: docs/188 (rank-1 killed), docs/170 (frontier-lift axis), docs/172
(rewind/livelock), docs/164 (F0–F3 ladder), docs/98 (orchestrator axis /
generate_disjoint). Memory: `project-dos-conversion-gap-value-capture`.

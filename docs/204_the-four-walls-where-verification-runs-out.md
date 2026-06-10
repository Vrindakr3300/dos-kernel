# The four walls — where DOS works, up to a point, then the witness runs out

> **DOS catches everything it can mechanically witness. Every bottleneck is the same
> bottleneck wearing different clothes: the moment "did this happen?" turns into "is
> this *right*?" — because the second question can only be answered by bytes the agent
> itself authored, which the kernel refuses to believe. The benchmarks do not show DOS
> failing; they show exactly where the witness runs out.**

This note is the modular companion to the benchmark runs (`benchmark/BENCHMARKS.md`).
It does not introduce a mechanism — it *names the boundaries* of the ones we have, one
self-contained section per wall, each grounded in a benchmark number AND the mechanism
doc that explains why the wall is there. Each §N is independently citable; the
through-line in §0 is the single root cause they all reduce to. Every load-bearing
figure below was re-grounded against live code/data (adversarial verify, `wf_d1c7fd98`,
2026-06-06) — citations are file:line or verbatim run output, not memory.

The walls are ordered from *scaling cliff* (cheapest to reason about) to *fundamental
limit* (the design deliberately punts to JUDGE/HUMAN rather than fake a verdict).

---

## §0. The through-line — the witness runs out

The kernel's one invariant is **evidence counts only when its byte-author ≠ the judged
agent** ([`138`](138_what-is-truth-the-throughline.md), [`141`](141_byte-inequality-and-the-derivative-problem.md)).
That is what makes a verdict unforgeable — and it bounds the verdict precisely. Each wall
is one face of it:

| Wall | DOS needs… | …and hits the wall when |
|---|---|---|
| §1 Fleet-of-one | **plurality** | there is only one agent (no concurrent effect to witness) |
| §2 Frontier silence | the failure **visible in env-authored bytes** | a strong model hides it in world-state, not the trajectory |
| §3 Presence-not-goal | a witness of **correctness** | git witnesses that a file *changed*, not that it is *right* |
| §4 Detect-not-fix | something **curable** to act on | the failure is infeasible/upstream, so there is nothing to convert |

Read top to bottom this is a single sentence: *the referee is only as strong as the
un-authored evidence available to it, and that evidence thins out as you move from
"concurrent fleet" → "frontier model" → "goal correctness" → "in-loop repair."*

---

## §1. The fleet-of-one wall — value → 0 at fleet=1 (the benchmark's own falsifier)

**Works:** DOS's coordination value rises *monotonically* with horizon × fanout —
verified-$/edge climbs 2.48× → 1.89× → 3.07× as the fleet/horizon grows, and the closed
loop prevents **104/104** silent overwrites in the headline cell.

**Wall:** at **fleet = 1, overwrites-prevented = 0.** This is not an empirical dip — it
is *structural*. `refused_writes` is emitted only when `arbitrate()` refuses a footprint
collision against *another effort's* in-flight lease (`closed_loop.py:286-294`); with a
single effort there is never a concurrent other-effort lease, so the count is
structurally 0 (`closed_loop.py:263-269,303`). The benchmark names this its **own
falsifier** and pins it as a test (`test_fleet_horizon.py:121-128`,
`test_collision_value_is_zero_at_fleet_of_one`).

> `RESULTS.txt:45-49`: *"At fleet=1 there is no one to collide with — overwrites-prevented
> is 0 and DOS's collision value is nil (its own falsifier). It climbs with the fleet —
> collision-prevention is strictly a fleet phenomenon."*

**So:** DOS is a *fleet* technology. A single serial agent on a short horizon does not
need a non-believing kernel arbitrating its lane — that is pure overhead. The value is a
*plurality* phenomenon, which is why the protected seam is the cross-vendor conductor of
many agents, not single-agent supervision (the two-product split, `dos-strategy`).
**Citations:** `benchmark/fleet_horizon/{RESULTS.txt,harness.py,closed_loop.py,test_fleet_horizon.py}`.

---

## §2. The frontier-silence wall — detectors hit a sweet spot, then go silent

**Works:** the three byte-clean in-trace detectors show real lift on cached
trajectories — toolathlon replay: `dangling_intent` **+21.9pp**, `terminal_error`
**+18.8pp**, `tool_stream` **+12.0pp**, false-alarm 0.1–1.2%.

**The sweet spot, then the cliff** (the Gemini capability ladder, [`177`](177_the-frontier-silent-failure-and-why-detection-is-not-solved.md)):

| model | base-fail | in-trace detectors |
|---|---|---|
| gemini-2.5-flash | 96.2% | slightly **net-harmful** (base swamps signal) |
| gemini-2.5-pro | 87.9% | **sweet spot** — 100% precision, +12.1pp, 0 false alarms |
| gemini-3-pro (strongest) | 63.2% | `dangling_intent` + `tool_stream` fire **0 / 321** |

**Wall:** a stronger model does not make fewer mistakes the in-trace detectors can see —
it makes the same mistakes *somewhere the detectors cannot look*. The `0/321` zeros are
**not a normalizer artifact** (re-run live: `--raw-digest` floor is byte-identical,
both detectors still `fired=0 ... n=321`). Failure mass drains out of the legible
trajectory cells into world-state: of the n=203 confirmed fails, **CLAIM_SUCCESS×WROTE =
95** (confident wrong mutation) and **ABANDONED×WROTE = 52** (ran out without narrating,
having already written) — loud in world-state, *silent in trajectory*
(`_frontier_contingency.txt`, docs/177 §3.3).

**So:** the in-trace detector line is a **weak/mid-tier-model + fleet** instrument. On
the frontier it reports a null — and that is *correct*. Reading the trajectory harder
would mean believing the agent's own self-consistent narration, the satisfaction-predicate
trap the kernel exists to avoid (the "consistency is not grounding" rule,
[`141`](141_byte-inequality-and-the-derivative-problem.md) §5a). This
wall is the detector-side view of §3.
**Citations:** `docs/177`, `benchmark/toolathlon/_frontier_contingency.txt`, live `run_replay --by-model`.

---

## §3. The presence-not-goal wall — verify() is W2, not W3

This is the deepest wall, and it bites DOS itself.

**Works:** `verify()`'s file-path rung is an unforgeable **ship/presence** oracle —
tamper-evident, content-addressed, byte-clean. "A single commit in git ancestry touched
≥2 of the plan-named files."

**Wall:** it is a **W2 presence-witness, not a W3 goal-witness**
([`192`](192_the-world-state-witness-ladder-and-the-w2-w3-gap.md)). Confirmed in code: the rung
(`_check_phase_by_filepath`, `phase_shipped.py:1279`) runs `git log --oneline -{800} --
<path>` per named file (`:1329`) and records only *which sha touched the path*
(`touched.setdefault(sha, set()).add(path)`, `:1350`). There is **no `git show` / `git
diff` / blob read anywhere in the rung** (`_git_log`, `:154-171`) — it never compares file
*content* against an expected value. And the projection of *which files count* comes from
`_extract_phase_files`, which harvests path-shaped tokens out of the **agent-authored
plan doc** (`:1072,1320`).

The world-state ladder (W0 narration → W1 env-ack → W2 presence → W3 gold-diff): only W3
witnesses GOAL. The toolathlon data shows why it bites — an env ack like
`submit_grade → {"grade":"0"}` is "200 OK" (W1 acceptance) while the grade *0 was wrong*
(W3 failure); action-acks look success-shaped on **41–43% of failed writes**. The honest
floor (`_facet_beyond_state.py`): **62%** of frontier goals reach a persisted-state
witness, **21%** are external effects (success on a *different* principal, no authoritative
in-trace byte), **17%** are judge-only — **~38% reach no sound witness at all**, regardless
of gold.

**So:** DOS can prove a thing *shipped*; it largely cannot prove it shipped *correctly*.
That residue bottoms out at JUDGE (advisory, forgeable) or HUMAN — the trust ladder
working as designed, and the ceiling on autonomous adjudication. The fix is not to make
the oracle guess: it is to (a) re-label the file-path rung W2/conditionally-sound, (b) add
a content-diff rung + an `invariant_witness` rung where a tamper-evident gold exists, and
(c) downgrade agent/plan-authored gold the way grep-subject is downgraded (docs/192 §design).
**Citations:** `src/dos/phase_shipped.py:{154,1072,1279,1320,1329,1350}`, `docs/192`.

> **Where the wall is partly climbable — measured live ([docs/228](228_running-tau2-writeadmit-live-the-out-of-loop-payoff-measured.md), 2026-06-08).**
> Point (b) above is not hypothetical for **Tier-1 write tasks** (docs/212): the tau2 env's
> own **DB-state hash** *is* a tamper-evident W3 correctness witness — a reservation booked
> *successfully but wrong* fails it, and the agent authors none of its bytes. Running an
> out-of-loop write-admission gate on it live, the gate caught + blocked **5 real
> over-claims** (the agent said "successfully …", the hash said no). So Wall 3 is not a flat
> ceiling — it **lowers exactly to the slice that has a state invariant** (money/inventory/
> reservations), and stays at JUDGE/HUMAN for the goals that don't (the ~38% residue). The
> wall is real; its height is the *fraction of goals with a checkable invariant*, not 100%.

---

## §4. The detect-not-fix wall — stopping a bad loop is robust; steering it is not

**Works:** the intervention ladder *detects* and is well-ordered — sim_ab: **BLOCK beats
DEFER by +0.4005** (turn-preserving beats turn-spending, the s13.4 gate PASSES); WARN is
the least-disruptive arm.

**Wall — four fresh numbers that all say the same thing** (re-run live at HEAD, $0):

- **The +6.2pp WARN lift is injected-mint-only.** On the natural failure stream it is
  **+0.20pp — flat** ([`202`](202_intervention-ladder-refresh-natural-regime.md)). The
  lift was a property of the *injection*, not of WARN.
- **0% of natural thrash is rewind-addressable** (`cause_locality`:
  `A_recoverable_from_prefix = 0`, `rewind_addressable_pct = 0.0`, `B+C = 100.0`). 100% is
  upstream-omission livelock (B) or a capability gap *outside any transcript move* (C). You
  cannot rewind out of a problem the transcript never contained.
- **The dominant natural thrash is infeasible, not curable** (`feasibility_split`:
  `create_filter  0 ok / 278 err  WALLED` — the schema demands ~9 fields the agent never
  supplies; [`198`](198_the-feasibility-witness-and-give-up-correctly.md)). There is
  nothing to convert.
- **The one experiment that could settle curable conversion is underpowered** — curable
  slice **n=6, discordant pairs d=0**, powered threshold 30 → "GENUINELY UNTESTED."

**So:** DOS's *fix* story is much weaker than its *detect* story. The one fix that
survives every regime is the *negative* one — **give-up-correctly** (witness-gated
early-halt: PASSES at K=2/3/4, **0% false-alarm**, ~22.8k tokens saved). Telling a doomed
loop to stop is robust *because halting needs no curable residue*; steering it to success
is not, because the cure usually has nothing curable to act on. This is the same wall as
§3 from the actuation side: you cannot author the fix without authoring the bytes the
kernel won't believe.
**Citations:** live `cause_locality` + `feasibility_split` stdout (`run_e8083f3_*`), `docs/{198,202}`.

---

## The honest read

The benchmarks are healthy and the deterministic numbers reproduce their baselines.
**DOS is a strong, unforgeable referee for concurrent mid-capability fleets, with a
detect-and-halt value that is real and measured — and a known frontier (correctness-
witnessing and in-loop repair) where the design deliberately punts to JUDGE/HUMAN rather
than fake a verdict it cannot ground.** Naming the four walls is not an admission of
weakness; it is the same discipline as the kernel itself — *report the rung that
answered, and abstain where no sound rung exists.*

# 140 — The reference userland app adjudicates *dispatch*, not *truth*: the missing half of DOS adoption

> **The job-search fleet (the reference userland app DOS was lifted out of)
> consumes the kernel in exactly one half of its surface — the *dispatch* half
> (`scripts/*`, 48 files importing `dos.*`: the lease arbiter, the lane journal,
> the loop-decide spine, the scout) — and in *none* of the truth half. The entire
> apply path (`agents/*`, `job_search/*`, ~31k lines) imports zero DOS. So the
> kernel today adjudicates *which agent is allowed to run* and never *whether what
> the agent did was real*. The irony is sharp: the job repo independently built a
> high-quality evidence ladder for "was this application actually submitted?"
> (`agents/apply_verifier.py`, `agents/ev/*`, `job_search/track_mutations.py`) —
> the very machinery DOS abstracted into the `EvidenceSource` seam (docs/121) and
> wrote up, using *this exact pipeline*, as the empirical proof of that seam
> (docs/129). The kernel learned the witness law from the userland app and shipped
> it as a syscall; the userland app never adopted it back, and as a result still
> carries the one self-report hole the seam exists to close. This note maps the
> asymmetry, names the three conceptual fault-lines it produces, and lays out what
> "more usage of DOS / DOS doing more integrity + drift control" concretely means
> for the host.**

Status: analysis note (host-consumption gap), companion to docs/121 (the
`EvidenceSource` seam), docs/129 (the apply-confirmation as that seam's proving
ground), and docs/117 (completion as a verdict). No kernel code is proposed here
that doesn't already exist — the seams are all shipped (`dos.evidence`,
`dos.os_acceptance`, `dos.completion`, `dos.oracle`, `dos.arbiter`). The lift is
*adoption*, host-side, plus three small kernel affordances called out in §6. The
job-search fleet lives in its own repo (`job/`); this note references its
code as a downstream consumer, never as a dependency — the one-way arrow
(CLAUDE.md).

---

## 1. The measured asymmetry: DOS owns dispatch, not truth

A grep across the job repo for `from dos` / `import dos`, bucketed by layer:

| Layer | Files importing `dos.*` | What DOS adjudicates there |
|---|---|---|
| `scripts/` (dispatch + orchestration) | **48** | which lane is free (`dos.arbiter`), the lease WAL (`dos.lane_journal`), should-the-loop-continue (`dos.loop_decide`), what-to-start (`dos.scout`), ship-stamp truth (`dos.oracle`/`ship_oracle.py` shim), liveness, timeline |
| `agents/` (the apply / discovery / scoring path) | **0** | — |
| `job_search/` (models, tracking, the state machine) | **0** | — |

The kernel sits *around* the work — gating entry to a lane, deciding whether the
loop spins again — and is absent from the *inside* of the work, where the actual
question "did this application get submitted?" is answered. That inside question is
the one DOS was built for ("the kernel is the part that doesn't believe the
agents"). It is answered today by host-local code that does not call the referee.

This is not a criticism of the dispatch integration — that half is mature and
correct (`fanout_state.py`'s arbiter, the lane journal, the scout composition are
all real). It is an observation that **adoption stopped at the orchestration
boundary** and never crossed into the effect-verification boundary, which is the
higher-value half.

## 2. The host already re-implemented the seam DOS ships

The job repo's apply-truth surface is, structurally, a hand-rolled `EvidenceSource`
ladder — built before the kernel seam existed, and never migrated onto it:

- **`agents/apply_verifier.py`** — an explicit evidence hierarchy: weak (agent
  narration contains a `_SUCCESS_PHRASES` string) → medium (a `06-confirmation.png`
  exists) → strong (artifact + a corroborating sidecar OR a post-submit host
  change). It even documents removing `phase4-submit.txt` from the corroboration
  set because it "trivially self-matches" — i.e. it *discovered the forgeable-floor
  problem by hand* and patched one instance of it.
- **`agents/ev/*`** — `joiner.py`, `confirmation_rules.py`, `verdict_judge.py`,
  `audit_reconcile.py`, `sweep.py`: the email-confirmation pipeline. A closed
  verdict vocabulary graded by accountability (A deterministic ATS auto-ack · B
  LLM-classified company mail · C this ATS never emails → submit-side fallback · D
  unconfirmed), an observation-derived rule registry, a check-the-checker audit.
  This is **field-for-field** the `dos.evidence` seam: a witness whose byte-author
  is not the judged agent, an `accountability` tag that ceilings trust, a fail-safe
  judge, an independent audit. docs/129 reads this exact pipeline as the empirical
  proof that the seam is right.
- **`job_search/track_mutations.py`** — `_derive_final_status(outcome,
  verifier_verdict, artifact_verdict)`: the function that writes `applied` to the
  ledger. This is the host's private `believe_under_floor`.

So the host did the hard conceptual work — *and DOS already generalized it into a
kernel module with a structural safety floor*. The two have simply never been
joined. `agents/ev/__init__.py` imports no `dos`.

## 3. The fault-lines this asymmetry produces

### 3.1 The self-report hole survives in the fallback path (the load-bearing one)

`track_mutations.py:_derive_final_status` (the canonical PSV2 rule) is correct on
its strong paths — verifier-verified → `applied`, verifier-unverified → `failed`,
artifact-confirmed → `applied`. But its **fallback**, reached whenever the verifier
was skipped *and* there is no artifact verdict (the documented "99% case for legacy
rows + any non-SUCCESS dispatch", and any cost-gated skip):

```python
# track_mutations.py:358-360
return _OUTCOME_TO_FINAL_STATUS.get((outcome or "").upper().strip(), "failed")
#   _OUTCOME_TO_FINAL_STATUS["SUCCESS"] == "applied"     (line 304)
```

maps the **raw outcome string** `"SUCCESS"` — which originates in the agent's own
response text (`parse_apply_outcome` over `detect_submission_success`, which accepts
a `_SUCCESS_PHRASES` substring in agent narration, `apply_contracts.py:212-221`) —
straight to `applied`. No artifact required. This is precisely the move DOS's
`believe_under_floor` makes *structurally impossible*: an `AGENT_AUTHORED` source
(the agent's stdout) can be recorded and shown but can **never by itself** move a
verdict from abstain to believe. The host's own load-bearing axiom
("evidence-over-narrative", CLAUDE.md §92) is violated on its most-travelled code
path — not by oversight, but because the floor is a *convention* here, not a
*structure*. The PSV verifier and the `ev/` join are both **cost-gated and
advisory**, so when budget is exhausted the system silently falls back to the
narration tier for the rest of the batch — a two-tier truth model where the tier is
chosen by budget, not by evidence.

The kernel's framing of why this matters: `believe ⟺ a non-forgeable source
attests`. The worst a buggy/hostile/lying source may do is *withhold* an
attestation (a visible, safe-direction loss), never *manufacture* a belief the
agent could forge. The host fallback manufactures the belief.

### 3.2 Many truth surfaces, no adjudicated join (drift is reported, never refused)

The portfolio's "where do we stand" answer is spread across surfaces that
`scripts/plan_audit.py` itself enumerates as "routinely disagree":
`docs/_plans/plans.yaml`, `docs/_plans/execution-state.yaml`,
the `docs/*-plan.md` SHIPPED-marker scan, and git ship-rate — plus, on the apply
side, `data/applications.jsonl` vs. the Go-owned `data/pipeline.duckdb` mirror vs.
the Go UI. The audit **reports** drift; the operator resolves it by hand-editing
`plans.yaml`. There is no surface that, given a `run_id`, *refuses* a claim because
two of its sources contradict each other. DOS already has the shape for this —
`dos.trace` walks spine + ledger + WAL + git joined by `run_id` (docs/137), and
docs/116/120 specced a fail-closed `dos status <run_id>` digest whose headline cell
is the over-claim (one surface says done, another says not). The host has the raw
material (it emits `pipeline_events.jsonl`, it has a run history) but no adjudicated
cross-surface verdict — so a divergence is a thing a human notices, not a thing the
substrate catches.

### 3.3 The lease floor is wall-clock, not liveness (a duplicate of a kernel verdict)

`fanout_state.py` (7,526 lines) still owns the host's three-tier claim model
(soft-claim TTL → hard-register → agent-in-session). Its abandonment signal is a
wall-clock TTL (`expected_wallclock_minutes` × a factor): a slow ATS form that
outruns its TTL is declared `abandoned` while still in flight, and a concurrent
`/next-up` can re-claim and launch a **duplicate** dispatch. DOS shipped exactly the
verdict that fixes this — `dos.liveness.classify` answers ADVANCING / SPINNING /
STALLED from the git/journal delta and a real `HEARTBEAT` rung, *not* from a clock
(docs/82). The host's `dispatch_liveness.py` already shims `dos.liveness`, but the
*claim-expiry decision* in `fanout_state.py` does not consult it — so the kernel's
liveness verdict and the host's abandonment timer are two different answers to the
same question, and the host trusts the weaker (time-only) one for the load-bearing
"is this claim still live?" call.

## 4. The throughline: same disease, named three places, fixed in one kernel

These three fault-lines are one fault-line — **a belief asserted without a
non-forgeable witness** — appearing at three radii:

| Radius | Host artifact | The claim taken on faith | The kernel verdict that refuses it |
|---|---|---|---|
| The effect | `track_mutations.py:358` | "agent said SUCCESS ⇒ applied" | `evidence.believe_under_floor` (AGENT_AUTHORED can't attest) |
| The portfolio | `plan_audit.py` (report-only) | "this surface says done" | `trace` join + fail-closed `status <run_id>` over-claim cell |
| The dispatch | `fanout_state.py` TTL | "clock expired ⇒ claim dead" | `liveness.classify` (ADVANCING vs SPINNING from real beats) |

DOS already ships the right answer in all three rows. The work is not *building* a
referee — it is *calling the one that exists* from inside the work, instead of
re-deriving a weaker one beside it.

## 5. What "more usage of DOS / more integrity + drift control" concretely means

Ordered by value-per-unit-effort (highest first), each a host-side adoption move,
none touching the kernel except where §6 notes:

1. **Route the apply-success verdict through `dos.evidence`.** Make
   `track_mutations._derive_final_status` (and `apply_verifier`) construct
   `EvidenceSource` attestations — the `06-confirmation.png` and `ev/` email join as
   non-forgeable witnesses (`OS_RECORDED`/`THIRD_PARTY`), the agent narration as the
   `AGENT_AUTHORED` floor — and decide `applied` via `believe_under_floor`. Effect:
   the §3.1 hole closes *structurally*; "SUCCESS in agent text, no artifact" can no
   longer write `applied`. This is the single highest-integrity change in the repo
   and it is a ~one-function rewrite plus a driver that wraps the existing
   `06-confirmation.png` reader.
2. **Adopt `dos.completion` for the apply-batch + dispatch-loop stop condition.**
   The loops stop on budget (`ITERATION_CAP`), not on done — the exact gap
   `dos.completion.classify` closes (residual = declared − verified, asked forward).
   Effect: a batch reports COMPLETE only when the residual of *verified* applies is
   empty, not when the turn ran out. Ties the §3.1 evidence verdict to loop
   termination.
3. **Stand up a fail-closed `dos status <run_id>` over the host's surfaces.** Feed
   `applications.jsonl` + `pipeline_events.jsonl` + the plan surfaces into the
   docs/116/120 digest so a cross-surface over-claim is *refused*, not reported.
   Effect: §3.2 drift becomes an adjudicated verdict an operator (or a gate) reads,
   the headline being the contradiction.
4. **Make `fanout_state.py` claim-expiry consult `dos.liveness`.** Replace (or
   gate) the wall-clock abandonment with the liveness verdict the host already
   shims. Effect: §3.3 duplicate-dispatch hazard closes; a slow-but-advancing form
   is not declared abandoned.
5. **Put the apply ledger behind `dos.oracle` semantics, not string maps.** The
   ship-stamp/ancestry discipline (`oracle.is_shipped`) is the same shape as "is
   this application *verifiably* in a terminal applied state" — the host's
   `_OUTCOME_TO_FINAL_STATUS` string table is the anti-pattern the oracle replaced
   for phases.

The ordering is deliberate: (1) is the keystone — it converts the host's best
hand-rolled work into a structurally-safe kernel call and closes the load-bearing
hole. (2)–(4) compose off it.

## 6. The three small kernel affordances this surfaces

Adoption is *mostly* host-side, but it exercises three kernel edges worth a small
lift (each its own follow-up plan, not built here):

- **An `EvidenceSource` driver for "a confirmation artifact on disk exists + a
  sidecar corroborates."** `drivers/os_acceptance.py` already does the OS-exit-code
  witness; the apply pipeline needs the artifact-on-disk witness as a sibling
  driver so the host can wrap `06-confirmation.png` + `06-confirmation.summary.txt`
  without re-implementing the seam. Small, mechanical, lives in `drivers/`.
- **`dos status <run_id>` as a shipped fail-closed digest** (specced in
  docs/116/120, liked by the operator, not built). The host is the obvious first
  consumer; building it against the host's surfaces is the forcing function.
- **A `liveness`-backed claim-expiry helper** the host can call from
  `fanout_state.py` without folding the whole host claim model into the kernel —
  i.e. expose "given this lease's last beat + git delta, is it ADVANCING?" as a
  one-call boundary the host substitutes for its TTL check.

## 7. The meta-point (why this is the conceptual issue, not a feature gap)

DOS's thesis is that the referee must be *structurally separated* from the
contestants — "the referee can't report to a player" (the 100x framing,
[[project-dos-security-10x-100x]]). Inside the job repo today, the apply agent is
both the contestant (it fills the form) **and**, on the fallback path, the source of
the verdict that it succeeded (its narration sets `applied`). That is the referee
reporting to the player, in the one fleet DOS was lifted out of, on the highest-
stakes write it makes (a mildly-irreversible outward effect — a submitted
application). The fix is not more host code; the host already wrote excellent
witness code. The fix is to **let the kernel be the referee from inside the work**,
not just at the lane door — to cross the adoption boundary from dispatch into truth.
That single move is what "more usage of DOS, DOS doing more integrity and drift
control" means, made concrete.

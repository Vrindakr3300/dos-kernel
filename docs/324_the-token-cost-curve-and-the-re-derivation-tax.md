# 324 — CURVE: the re-derivation tax and the 14-day campaign to bend it

> **Status:** DESIGN / campaign spine (2026-06-12). The forcing question
> (operator `/goal`): *from a token-maxxing view, we have 14 days to bend the
> curve with DOS — take the best actions so that, as tokens become "more
> expensive," nobody wants to start from scratch.* This doc is the **spine**:
> it names the macro thesis, the one number that makes it a procurement line
> and not a philosophy, the cold-start artifact that makes DOS sticky, and the
> phased 14-day plan. It writes **no kernel code** — it sequences work that
> already has a home (docs/197, docs/219, docs/263, docs/300, docs/191) and
> files the gaps the per-issue backlog does not capture (§6).

---

## 0. The thesis in one line

> **As tokens get more expensive, the dominant cost stops being the work and
> becomes *re-establishing trust in work already done.* DOS is the part of the
> stack that turns a re-derivation into a read.**

Everything below is an unpacking of that sentence. It is not a new claim — it
is the *macro* form of three claims the repo already proves in pieces:

- the fold-site referee saves spend by not re-running a verifier agent
  (docs/197, private docs/128);
- model-agnostic verdicts make the *cheap-model bet* safe to take, which is the
  whole point when the expensive model is the thing you are trying to stop
  paying for (docs/219);
- the kernel can already *price* a run and bank the verdict before the failure
  lands (docs/263, docs/300, docs/191).

The 14-day job is to **assemble these into one legible wedge with one number on
the front of it**, and to make the durable artifacts portable enough that a
fresh, expensive-token session inherits ground truth instead of re-deriving it.

---

## 1. Why the curve bends the way it does — the re-derivation tax

Hold the *work* an agent does constant. As the per-token price rises, the spend
splits into two piles that scale very differently:

| pile | what it is | how it scales with token price |
|---|---|---|
| **first-derivation** | the tokens that did the work the first time | linear — unavoidable, everyone pays it |
| **re-derivation** | tokens spent re-establishing facts a prior session already established: re-reading the tree to learn "is this actually done?", re-running a suite to re-confirm green, re-grounding a fresh context that inherited a summary it cannot trust, a verifier-agent re-grading a worker's "✅ done" | **super-linear** — paid again every session, every context reset, every fold site, every fleet member |

The second pile is the **re-derivation tax**. It is small when tokens are cheap
(re-checking is "free, just do it again") and it is the line item that hurts
when they are not. Three structural amplifiers make it super-linear:

1. **Context resets multiply it.** Every compaction or fresh window drops the
   prefix; the next session re-derives "where are we" from a summary it has no
   reason to trust (docs/193's restart arm; issue #122). Longer horizons → more
   resets → the tax is paid more times.
2. **Fold sites multiply it.** Every `parallel()`/`pipeline()` barrier where one
   agent's self-authored return becomes another's input is a place where the
   *honest* move is to re-verify with another agent — model-grading-model, more
   tokens, and still self-report at the bottom (docs/197 §1).
3. **Fan-out multiplies it.** N fleet members each re-derive the same shared
   facts; the tax is monotone in horizon × fan-out and 0 at N=1 (docs/191's
   non-agent fleet denominator).

DOS attacks all three with the **same move**: replace a re-derivation with a
read of a small, durable, *non-self-authored* verdict. A `dos verify` reads git
ancestry; a banked efficiency fossil reads the price the work already cost; a
status digest folds four adjudicated facts with **no `claimed` field** by
construction (docs/120). The verdict is cheap to carry forward because it is
*evidence already paid for once*, not a re-run.

> **The shape of the win:** first-derivation stays linear; DOS bends the
> re-derivation pile from "paid again every time" toward "paid once, then read."
> When tokens are cheap the two curves are close. When tokens are expensive the
> gap *is* the value of the substrate.

---

## 2. The one number that makes this a procurement line

A philosophy does not survive a budget meeting; a number does. The campaign's
single headline:

> **On a realistic multi-session / multi-agent task, what fraction of total
> tokens is re-derivation — and how much of it does carrying a DOS verdict
> forward remove?**

This is measurable with machinery that already exists. The five-way spend split
and the efficiency verdict are shipped (docs/263, docs/300); the journal banks
fossils; the trend folds them. The missing piece is a **paired A/B harness**:

- **arm A (cold):** each session/fold re-derives trust — re-reads the tree, re-runs
  the suite, re-grades the worker. Count the tokens.
- **arm B (carried):** the same task, but a banked verdict answers "is this
  shipped / green / clean" with a read. Count the tokens.
- **the headline:** `(A − B) / A` = the re-derivation tax DOS removes, reported
  with the cache-hit and output-share breakdown so it is honest about *which*
  tokens were saved (cache reads are ~0.1× input; output is ~4–5× — the mix
  matters, docs/300 §1).

**Honest-limits floor (kept from docs/197 §6, docs/219):** the verdict is
advisory and host-realized; the number is a *measured* delta on a *named*
workload, never an extrapolated "DOS saves X%." If the measured delta is small
on a given workload, we report it small — the value of a trust substrate is not
a marketing multiplier, it is the removal of a failure mode (a confident wrong
"done" you cannot see) that otherwise forces the expensive model everywhere.

This A/B harness is the **rank-1 deliverable** of the 14 days. It is filed as an
issue in §6 and sequenced in §5.

---

## 3. Cold-start stickiness — the artifact nobody wants to re-derive

"Nobody wants to start from scratch" is a statement about a **portable artifact**.
Today DOS produces the right *facts* (verdict journal, intent ledger, decision
fossils, the status digest) but they are workspace-local and re-loaded ad hoc.
The stickiness play is to make them a **portable trust bundle**: a small,
signed-or-checksummed, re-loadable object that a fresh session ingests to
inherit ground truth at a read's cost instead of a re-derivation's.

The bundle is not new mechanism — it is a *projection* of fossils that already
exist:

- the **shipped-phase set** (what `dos verify` would answer SHIPPED, precomputed);
- the **last clean-truth snapshot** (commit-audit clean as of SHA X);
- the **efficiency fossils** for the run (what the work already cost — so the
  next session does not re-price it);
- the **decision fossils** (the human rulings and the evidence they were made
  against — docs/120, issue #120), so a reset does not re-litigate a settled call.

The adjacent design issues (#120 decision fossil, #121 baton admission, #122
session-start re-grounding) are the *primitives*; the bundle is their **consumer**
— the thing that makes "inherit, don't re-derive" a single ingest. Re-grounding
(#122) is the read side; the bundle is the portable write side. This is the
**rank-2 deliverable**, filed in §6.

> Why this is the moat and not a feature: a competitor can copy a verdict verb in
> an afternoon. They cannot retroactively make a user's *existing, already-paid-for
> trust history* portable into their tool. The bundle makes DOS the format the
> trust history lives in — and the format is what nobody wants to abandon when
> starting fresh gets expensive.

---

## 4. Distribution against the clock — be already-installed before the squeeze

When tokens spike, adoption friction kills new tools: nobody onboards a
trust-substrate mid-crisis. The play is to be **already present** in the host
and registry surfaces *before* the moment, so adoption is a config flip, not a
project. This is pure sequencing of work that already has issues — the campaign's
contribution is to **order it against the 14-day clock** by audience size and
ship-readiness, not to invent it:

- **ready-now, large-audience listings** — gemini-extension manifest (#101),
  artifact-gated marketplace listings (#102), conda-forge feedstock (#54),
  GitLab CI template (#73). These reach populations the PyPI/GitHub-Action path
  never touches.
- **the pre-cost page** (#68, "running parallel AI agents safely") — the page a
  team reads *at the scale-up moment*, which is exactly the cost-spike moment.
  This is distribution *and* the value pitch in one artifact; it ships early.
- **host adapters, sequenced by audience** — Copilot (#86, largest audience),
  then the guardrail seats already built (#77, gated on release), then the
  long tail (#87 Cline, #88 Qwen, #89/#90/#91 SDK seats).

Sequencing rule for the 14 days: **ship the largest-audience, lowest-friction
surface that is already buildable first.** Do not start a new host adapter when
a ready listing reaches more people for less work.

---

## 5. The 14-day plan (phased)

Each phase is a few days; each names its witness (the thing that closes it is an
oracle or a landed artifact, never a status sentence — DOGFOOD discipline).

| phase | days | deliverable | witness |
|---|---|---|---|
| **P1 — the spine + the gaps** | 1–2 | this doc; the strategic issues filed (§6); the OTel-named spend egress (#39) landed as the first concrete ship | `dos verify CURVE P1`; the §6 issues exist; #39 commit-audits clean |
| **P2 — the headline harness** | 3–6 | the paired A/B re-derivation-tax harness on a named multi-session workload; the measured `(A−B)/A` with the cache/output breakdown | a reproducible benchmark dir with a RESULTS.md carrying the measured delta, not an asserted one |
| **P3 — the portable trust bundle** | 6–10 | the bundle projection (§3) + a fresh-session ingest that inherits the shipped-phase set, clean-truth snapshot, and efficiency fossils at read cost | a test that a cold session answers "is X shipped/green" from the bundle without re-running verify/suite |
| **P4 — distribution against the clock** | 8–13 | the §4 listings/pages shipped in audience order, starting with the pre-cost page (#68) and the largest ready listing | each listing live / each page indexed; commit-audit clean |
| **P5 — the legible headline** | 13–14 | the one-number pitch assembled over P2's measured delta + P3's bundle + P4's reach: "here is the re-derivation tax, here is what carrying a DOS verdict removes, here is how you inherit it" | a single receipt-linked page (issue #71's quotable headline surface is the vehicle) |

P1 is started in this session (this doc + §6 issues + the first ship). The rest
are filed as issues so the fleet can pick them against `scripts/backlog_triage.py`.

---

## 6. The gaps to file (what the per-issue backlog does not capture)

The backlog triage oracle prioritizes *per-issue*; it has no view of the
campaign. Three campaign-level issues were missing and are filed alongside this
doc (#130, #131, #132):

1. **The re-derivation-tax A/B harness** (§2, P2 — **#130**) — the rank-1 number.
   Paired cold/carried arms on a named multi-session workload; reports the
   measured `(A−B)/A` with the five-way breakdown. Done-condition: a benchmark
   dir whose RESULTS.md carries a *measured* delta on a reproducible workload.
2. **The portable trust bundle** (§3, P3 — **#131**) — the rank-2 stickiness
   artifact. A projection of existing fossils (shipped-phase set + clean-truth
   snapshot + efficiency fossils + decision fossils) into a re-loadable object,
   plus the cold-session ingest. Consumer of #120/#121/#122. Done-condition: a
   cold session answers shipped/green from the bundle without re-deriving.
3. **The campaign headline surface** (§5 P5 — **#132**) — the one-number pitch
   assembled over the harness delta. Vehicle is issue #71's receipt-linked
   headline log; this issue is the *content* aimed at the cost-spike audience.
   Done-condition: a single page stating the measured tax, the carried-forward
   removal, and the inherit path, each line receipt-linked.

Already-filed work this campaign *sequences* rather than re-files: #39 (OTel
spend egress, P1), #68 (pre-cost page, P4), #101/#102/#54/#73 (listings, P4),
#86/#77 (hosts, P4), #120/#121/#122 (bundle primitives, P3), #71 (headline
surface, P5).

---

## 7. What this doc deliberately does not do

- **No kernel code.** The thesis is that the machinery is largely built; the work
  is assembly, measurement, and reach. A kernel edit here would be a smell.
- **No asserted multiplier.** Every number the campaign produces is a measured
  delta on a named workload (§2 floor). "DOS saves X%" with no workload attached
  is exactly the over-claim the kernel exists to refuse.
- **No new trust surface.** The bundle (§3) is a projection of fossils that
  already adjudicate clean; it adds a *consumer*, not a new authority. The
  claimant still authors no byte that reaches the admit bit (issue #116).

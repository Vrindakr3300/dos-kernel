# DOS value-add — Phase A (free, no paid API calls)

> Run 2026-06-08 · workflow `wf_375152a2-c06` · 15 agents · ~50 min · $0 API.
> Method: dogfood the kernel live on this repo → replay the banked live Gemini
> A/B → send independent skeptics to **refute** each value-add claim → critic
> scopes the paid Phase B. The headline is the refutation rate, and that is the
> point.

## TL;DR

**6 of 7 value-add claims were REFUTED by DOS's own adversarial pass.** That is
not DOS failing — it is DOS doing the one thing it exists to do: **refuse to
believe a self-narrated win, even when the narrator is the operator.** The two
results that survive scrutiny are exactly the two that ride a witness the
adjudicated agent cannot author. Everything that got refuted, got refuted on the
*same* axis: a forgeable witness, or an underpowered slice — the two failure
modes my own method laws predict.

The real value-add is therefore demonstrated at the meta level: **the verifier is
sound enough to catch its own operator over-claiming.**

## What ran live on THIS repo ($0)

| syscall | verdict (verbatim) | witness forgeable? | survived refute? |
|---|---|---|---|
| `verify` (shipped) | `SHIPPED docs/82… liveness 80d4f30 (via grep-subject)` | **yes** — commit subject | ❌ refuted |
| `verify` (in-flight) | `NOT_SHIPPED docs/99… halt (via none)` | no — absence of git stamp | ✅ **SOUND** |
| `arbitrate --lane src` | `acquire` on lane `benchmark`, "src was busy" | claimed no | ❌ refuted |
| `commit-audit --sweep HEAD~12..HEAD` | `DRIFT 0.0%` (7/7 checkable witnessed) | claimed no | ❌ refuted |
| `lint --json` | `{}` clean, exit 0 | yes — own `dos.toml` | ❌ refuted |

## The banked live Gemini A/B (replayed, docs/237)

| model | over-claim rate | gate blocks all? | ΔB (behavioral) | survived refute? |
|---|---|---|---|---|
| gemini-2.5-flash | 23/35 = **66%** | ✅ yes | **+4** | ❌ underpowered |
| gemini-2.5-pro | 25/31 = **81%** | ✅ yes | **0** | ❌ underpowered |

**Detection is the robust, model-independent win** (the gate blocks 100% of
over-claims in both models, off a state-diff witness the agent authors 0 bytes
of). The **behavioral ΔB does not generalize and is underpowered** — +4 on flash
is 4 discordant pairs out of 23 (McNemar p≈0.125); 0 on pro is 2-vs-2 cancelling
(p=1.0). Blocking a bad write changes the outcome only when the agent would not
have self-recovered — and that recovery rate is unmeasured here.

## Why each refutation is correct (the load-bearing detail)

1. **`verify` via grep-subject is self-certifiable.** The skeptic reproduced a
   decisive control: `git commit --allow-empty -m "fakephase42: implement the
   thing (touches NOTHING)"` then `dos verify … fakephase42 fakephase42` →
   `SHIPPED (via grep-subject)`. A SHIPPED verdict for a phase that built nothing.
   The codebase agrees (`oracle.py:1034` grades this rung "forgeable"). The
   *honest* rungs (`registry` mark-done, `grep-artifact` file-path,
   `commit-audit`'s diff) exist — this just wasn't one.

2. **`arbitrate`'s "src was busy" was FALSE on this run.** With a provably empty
   lease WAL (`--leases '[]'`) it still redirected off `src` — because the
   **SELF_MODIFY predicate** fired (src/ is the kernel's own running code), not
   because anything was contended. The "was busy" string is a generic redirect
   template, not a diagnosis. The pure `arbitrate(request, live_leases, config)`
   is real and 54-test-pinned, but the `--leases` input is agent-authorable and
   the default WAL has no actor-binding — so *this output* is not a non-forgeable
   witness of contention. (Worth a real fix: the redirect reason should name
   SELF_MODIFY, not "busy.")

3. **`commit-audit` 0.0% drift rides a forgeable class.** 6 of 8 "witnessed"
   commits are DOC-kind, graded OK merely because "the commit touches files" —
   and for 5 of them the only file is the author's own markdown. The skeptic fed
   `classify()` three fabricated triumphant subjects (e.g. *"docs/999: PROVEN live
   coordination payoff J=99/100"*) touching one self-authored `.md` each; all
   three returned OK/diff-witnessed. Only 2/8 are source-corroborated, and even
   those witness *kind*, never correctness. (Also: the printed `HEAD~12..HEAD`
   range is a sliding window — the count already drifted as HEAD advanced.)

4. **`lint` audits self-authored config.** Its only inputs are the `[lanes]` /
   `[reasons]` tables of `dos.toml` — tracked, writable, the same bytes the agent
   edits. Subject and witness are identical; no second independently-authored
   fact is joined. A real static analyzer (JSON-schema-on-your-own-JSON), not a
   non-forgeable witness of self-narrated work.

5. **The two survivors** both join a fact the claimant did not author:
   `NOT_SHIPPED via none` reads the *absence* of a git stamp (you cannot narrate
   an ancestor into being), and its conservative degrade is fail-safe.
   `arbitrate`'s underlying pure function never double-books a *trusted* lease set.

## What Phase A proves vs. what it structurally cannot

**Proven free:** the syscall ABI executes live on a real workspace; non-forgeability
is *demonstrated and checkable*, not asserted (the survivors are exactly the
non-forgeable ones); detection is robust across both models; `verify` degrades
honestly; and the recovery-confound + model-split are surfaced, not hidden.

**Structurally NOT provable for free** (DOS method law: payoff is live-loop-only):
fresh ΔB on any new run; whether ΔB generalizes beyond flash; disentangling the
recovery-confound on pro (needs the believe arm run *fresh* to measure self-
recovery `r`); the compounding/fleet-scale (F^D) claim; and anything quoted as
text rather than re-executed (a reader who didn't re-run the syscall is in the
peer-B-handoff position).

## Phase B (paid, gated on operator go-ahead)

Re-smoke the expiring `AQ.` Gemini access-token first (200 via `?key=`/
`x-goog-api-key`, 401 via Bearer). Then, in priority order:

| run | runner | model | ~tasks | closes |
|---|---|---|---|---|
| **MUST** | `writeadmit/peer_b_run.py` | flash | ~22×2 | re-mints +4 *live*; reads `believe_self_recovery` |
| **MUST** | `writeadmit/peer_b_run.py` | pro (fix `reasoning_effort`) | ~27×2 | generalization + recovery-confound on pro |
| next | `agentdiff/delta_b.py` | flash | ~18×2 | 2nd independent witness (state-diff, needs :8000) |
| anchor | `writeadmit/coord_loop.py` | flash | ~9 | the known-positive coordination half-plane (J≈6/8) |

**Est. ~250–400 paid Gemini calls** for minimal-but-decisive; the two MUST-runs
alone (~240–290 calls) reproduce +4, test generalization, and settle the
recovery-confound. `coord_loop` is the high-confidence anchor (referee-between-
agents, does not depend on self-recovery) if the single-agent ΔB stays model-
dependent.

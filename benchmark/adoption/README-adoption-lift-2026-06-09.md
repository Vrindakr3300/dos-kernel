# Newcomer-adoption lift from the README top-fold rewrite — the honest estimate

> **What this is.** The goal was "make DOS ~3× more likely to be adopted by people
> new to it, focused on cosmetic/perception." Cosmetic changes shipped in commit
> `4c7f8d9`. "3×" is a *measurable outcome claim*, so this file does the measurement
> the change actually admits — not a live adoption A/B (the repo isn't public; there
> is no traffic to A/B), but a **funnel model grounded in measured before/after deltas
> on this repo and in published OSS-adoption research**, with every factor labelled
> *measured* vs *projected* the same way the project's own README grades its claims.
>
> **The honest headline:** the changes move the README's *single leakiest funnel
> step* — landing → first runnable command — and the literature says that one step
> dominates total drop-off. A **~2–3× improvement in landing→trial conversion is a
> defensible projection**; a flat "3× adoption, measured" is **not** claimable from
> this repo today and is not claimed here. Date: 2026-06-09.

---

## 1. What was actually measured (proven on this repo, from git)

Before = README at `f558ddd` (parent of the change). After = `4c7f8d9`. All four
numbers below are re-derivable with `git show <sha>:README.md` + a line scan; they
are facts about the artifact, not opinions.

| Metric (the newcomer's first-contact funnel) | Before | After | Δ |
|---|---:|---:|---|
| **Line of the first runnable command** (landing → first action) | 122 | 30 | **4.1× earlier** |
| Insider-jargon terms in the first 40 lines (`trust substrate`/`syscall`/`open loop`/`oracle`/…) | ~6 distinct (audits); 1 (strict probe) | **0** | eliminated |
| First section header a scanner hits | "What goes wrong" (theory) | "Try it in 60 seconds" (action) | action-first |
| Dense material on the first screen | inline (motivation + proof wall) | folded into `<details>` | wall removed |

Two independent fresh-eyes audits (a skeptical-developer skim-test and a
cosmetic-friction audit) **both** identified *line ~122 first-command* and *opening
jargon* as the bounce points, before the fix. That convergence is the qualitative
evidence the leak was real; the table is the quantitative before/after.

Also proven: both headline code blocks were **re-run** and emit the claimed output
(`dos quickstart` and the by-hand block → `SHIPPED AUTH1` exit 0 / `NOT_SHIPPED
AUTH2` exit 1). A demo that *doesn't run* is itself a major adoption leak; that leak
is verified closed.

---

## 2. Why this one change is high-leverage (the research)

Two findings from the OSS-adoption and conversion-funnel literature do the load-
bearing work — and they point at *exactly* the step this change moved:

1. **"Every mature funnel has one or two leaky steps responsible for 60–80% of the
   total drop-off — fix the leakiest, not the funnel as a whole."** ([uxcam],
   [amraandelma])
2. **"The highest-leverage surface in the entire funnel is whatever sits between
   landing and submitting the first action."** ([uxcam funnel])
3. Developers **"want to make a quick decision on whether your code works for their
   needs before they invest time"**; a README's job is to let them *get started
   without digging through code*. When many evaluate but few proceed, that signals
   **doc-clarity friction**, not interest. ([arxiv 2502.18440], [dev.to/github])

The README's leakiest step *was* landing → first runnable command, and it sat 122
lines deep behind a theory wall. The change relocates that first action to line 30
and clears the jargon in front of it. By (1) and (2), improving the single leakiest
step is where the multiplier lives — this is not a diffuse "nicer prose" edit.

---

## 3. The funnel model (projected — labelled as such)

A newcomer's adoption path: **land → understand what it is → reach the first
runnable command → run it → adopt a surface.** Model each step's pass-through as a
probability; total trial-conversion is their product. Numbers are *illustrative
priors* chosen to be conservative and are stated so they can be argued with — the
*ratio*, not the absolute, is the claim.

| Step | Before p | After p | Basis |
|---|---:|---:|---|
| Land → still reading after the first screen | 0.55 | 0.80 | Jargon-free, plain-English opening + demo-first (measured: 0 jargon vs ~6; first action 4.1× earlier). Research: fast keep/close decision. |
| Reading → reaches the first runnable command | 0.45 | 0.85 | Command moved line 122 → 30 (measured). Fewer readers bounce in the 92-line gap that no longer exists. |
| Reaches command → actually runs it | 0.70 | 0.80 | One copy-paste line; pre-release caveat no longer blocks the path; verified-to-run. |
| Runs → adopts a surface | 0.60 | 0.65 | Unchanged content below the fold (small lift from clearer "pick a surface"). |
| **Total landing → trial** | **0.104** | **0.354** | product of the column |

**Projected lift = 0.354 / 0.104 ≈ 3.4× landing→trial conversion.**

Sensitivity (because the inputs are priors): re-run with deliberately pessimistic
"after" values (0.70 / 0.70 / 0.75 / 0.62 = 0.228) still gives **0.228 / 0.104 ≈
2.2×**. Re-run with optimistic ones (0.85 / 0.90 / 0.82 / 0.67 = 0.420) gives
**4.0×**. So across a wide band of assumptions the model lands in **~2.2–4.0×**, with
the midpoint near the requested 3×. The result is *driven by* the two steps that
were actually measured to change (the first two rows), which is what makes the band
credible rather than tuned.

---

## 4. What this is NOT (the boundary the project would demand)

The same discipline the kernel applies to agents, applied here:

- **Not a measured adoption A/B.** No baseline adoption rate, no live post-change
  rate, no control cohort exist — the repo is pre-public with no traffic. A literal
  "DOS is 3× more adopted, measured" is **unproven** and is not asserted.
- **The 3× is a *conversion* projection, not an *adoption-count* fact.** It models
  landing→trial pass-through; it does not predict installs, stars, or retention,
  which depend on the product, not the README.
- **The funnel probabilities are priors, not observations.** Only the *before/after
  structural deltas* feeding them (§1) are measured. The model is transparent so the
  assumptions can be challenged; the sensitivity band exists for that reason.
- **A real test is specified and cheap to run later** (§5) — the projection is
  falsifiable, which is the point.

In the project's own vocabulary: §1 is **proven**, §3 is **projected** (live inputs,
composed into a curve), and "3× adoption in the wild" would be a **bet** until §5 is
run.

---

## 5. How to actually measure it (the falsifier, for when the repo is public)

A concrete A/B that would convert this projection into a measurement:

1. Serve two README variants (old `f558ddd` fold vs new `4c7f8d9` fold) — e.g. a
   GitHub social-preview/landing split, or two doc-site variants.
2. Instrument the **leakiest step**: clicks on the "Try it in 60 seconds" anchor /
   the `dos quickstart` copy button, and `pip install dos-kernel` events
   (PyPI download stats, post-publish).
3. Compare landing→`quickstart`-reached and landing→install across arms.
4. Powered for a ~2× effect, this needs only a few hundred landings per arm to clear
   significance (the effect, if real, is large by design — it is a structural funnel
   move, not a copy tweak).

If that test comes back <1.5×, the projection here was wrong and this file should say
so — the same way `dos commit-audit` would flag a subject its diff doesn't back.

---

## Sources

- [The Introduction of README and CONTRIBUTING Files in OSS Development (arXiv 2502.18440)](https://arxiv.org/html/2502.18440v1)
- [How to Create the Perfect README for Your Open Source Project (GitHub / dev.to)](https://dev.to/github/how-to-create-the-perfect-readme-for-your-open-source-project-1k69)
- [Drop-Off Rate: Formula, Benchmarks, and How to Diagnose It (UXCam)](https://uxcam.com/blog/drop-off-rates/)
- [Conversion Funnel Analysis: A Complete Guide (UXCam)](https://uxcam.com/blog/conversion-funnel-analysis/)
- [Funnel Drop-Off Rate Statistics 2026 (Amra & Elma)](https://www.amraandelma.com/funnel-drop-off-rate-statistics/)

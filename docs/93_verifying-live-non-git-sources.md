# Verifying live, non-git sources — the accountability spectrum, and a CI oracle we run on ourselves

> **Extending `verify()` to a "live" source — CI, logs, a chat thread, a screen
> recording — is never a machinery question. The machinery already generalizes:
> `classify(Evidence, Policy) -> Verdict`. It is an *evidence-sourcing* question,
> and it has one test — can the party being judged author this byte? Git is
> load-bearing not because it is git, but because a self-narrating agent cannot
> retroactively forge a reachable commit object. Any source with that property can
> ground a verdict; any source the agent authors can only ground a *judge*.**

This note answers the natural follow-on to [`84`](183_how-much-does-this-lean-on-git.md)
(git is necessary and not sufficient) and [`85`](85_extending-the-verifiable-surface.md)
(extend deeper before broader; one four-gate test sorts every candidate): **how do
you point the distrust machinery at sources that are not git** — logs, CI runs,
Slack, a Linux screenshare — and which of them are worth anything? It is a theory +
spec note in the family of [`79`](79_primitives-not-features.md),
[`82`](182_the-kernel-is-a-taxonomy-of-refusal.md), [`84`](183_how-much-does-this-lean-on-git.md),
[`85`](85_extending-the-verifiable-surface.md). Unlike most of them it ships code:
[`src/dos/drivers/ci_status.py`](../src/dos/drivers/ci_status.py) is the worked
example, the move-B reference driver, and `tests/test_ci_status.py` pins it.

---

## 1. The thing that generalizes is not git — it is the verdict ABI

All three shipped/specced epistemic verdicts read git today:

| Verb | Distrusts | Reads |
|---|---|---|
| `verify()` | "I shipped P" (finished) | commit existence + ancestry + subject grammar |
| `liveness()` | "I'm making progress" (in-flight) | commits-since-start delta |
| `scope()` | "I only touched my lane" (footprint) | the diff's touched-file set |

But git is **incidental**. [`liveness.py`](../src/dos/liveness.py) and
[`scope.py`](../src/dos/scope.py) say the same thing in their docstrings: *all I/O
happens in the caller; `classify()` receives already-gathered, frozen evidence.*
Git is just "the one tamper-evident fossil a code fleet happens to leave lying
around for free" ([`84`](183_how-much-does-this-lean-on-git.md)). The actual contract
([`verdict.py`](../src/dos/verdict.py)) is source-agnostic:

```
classify(Evidence, Policy) -> Verdict[V]
```

where `Evidence` is a frozen dataclass of facts **gathered at the boundary** and —
the load-bearing clause — **unforgeable by the party being judged.** So "verify a
live source" is not a new subsystem. The verdict shape, the boundary-reader split,
the typed enum, the `to_dict` seam — all already exist. The only question a new
source raises is: *what fills the `Evidence` dataclass, and can the agent forge it?*

---

## 2. The one test: who can author this byte? (gate 2, restated)

[`85 §2`](85_extending-the-verifiable-surface.md)'s four-gate test sorts every
candidate. Three gates decide *where the thing lives*; **gate 2 is the kill switch**:

| Gate | Pass | Fail |
|---|---|---|
| 1. A claim about **ground-truth state**? | maybe a verdict | taste/correctness → a **JUDGE** (advisory) |
| 2. Evidence **unforgeable by the agent**? | maybe a verdict | **belief, not verification — drop it** |
| 3. **Domain-free**? | a kernel **verb** | a specific system → a **driver oracle** |
| 4. Verdict **mechanical / typed**? | a kernel verb | redesign or make it advisory |

Gate 2 is not binary — [`85 §1`](85_extending-the-verifiable-surface.md) makes it a
**spectrum of accountability**:

```
strongest  immutable third-party record     git content-hash; a registry image digest; a signed CI attestation
     │     mutable third-party state        a CI run conclusion; a DB migration catalog; a cloud control-plane status
     │     a probe the agent doesn't own     an external health endpoint on infra the agent can't redeploy
weakest    a self-report dressed as evidence a probe of the agent's OWN service; a commit subject it typed; its own logs/screen
```

A new oracle does not *remove* trust — it **relocates the axiom** to a party you'd
rather trust than the self-narrating agent. "What can we verify next" is therefore
"where does the most accountable referent for this claim-type live," risk-weighted
by `value(rung) ≈ P(claim false) × detonation-cost-if-believed − cost(rung)`.

---

## 3. The live sources, placed on the spectrum

The placement *is* the answer. The same word ("logs") lands at opposite ends
depending on the author.

### CI / Checks — **mid-spectrum, high value → a driver oracle (built, §5)**

A CI conclusion is **mutable third-party state on infrastructure the agent does not
control**: GitHub ran the workflow and recorded `conclusion == "success"`, and the
agent under adjudication cannot retroactively forge that on a public commit without
compromising the CI system itself. Strictly more accountable than the commit subject
the same agent typed — and it answers the single thing git *cannot*: not "a commit
exists" but "**the build is green at that commit**" ([`84 §3.3`](183_how-much-does-this-lean-on-git.md),
the *complete → correct* jump). It is **not** the top of the spectrum: an agent that
*administers* its CI can edit the workflow, disable a required check, or re-run with a
patched config — so the signal is only as honest as the branch protection around it.
That residual is exactly why it stays a **driver the host wires**, not a kernel
guarantee. Worth building first; built in §5.

### Logs — **the split runs through the middle of the word**

- *Application logs the agent's own process emits* — bottom of the spectrum. "INFO
  deployed successfully" in a logger is `git commit --allow-empty -m "deployed"` in a
  new font. **Drop it** (gate 2), or feed it to a judge as a hint.
- *Infrastructure logs the agent cannot write* — a cloud provider's audit trail, a
  load-balancer access log, a database migration/WAL catalog, a CI build record — are
  mutable-to-immutable third-party records, mid-to-high spectrum. **A driver oracle**,
  the same shape as §5's CI reader: a boundary reader that pulls the record, a pure
  classifier that renders a typed verdict. This is the highest-value extension after
  CI because so much fleet "done" leaves exactly this fossil
  ([`84 §3.4`](183_how-much-does-this-lean-on-git.md): deploys, migrations).

### Slack / chat — **only the envelope, never the content → a narrow driver oracle**

"Agent posts 'deployed to prod'" is a self-report with a webhook — drop it. But the
**Slack audit log** — *a message was posted by user U at time T in a channel the agent
cannot impersonate*, attested by Slack's API, not the agent — is mutable third-party
state. The content is never trustworthy; the *envelope* (who/when) sometimes is. So a
Slack-derived verdict can adjudicate exactly one claim git can never leave: **"an
accountable human approved this"** (`APPROVED / NO-APPROVAL-FOUND`) — never "the thing
the message describes is true." Narrow, but it is the natural fossil for the human-in-
the-loop approval gate.

### Linux screenshare / terminal recording — **a JUDGE input, almost never a verdict**

A recording of an agent's own terminal is **the agent narrating with pixels**. A frame
showing `tests passed ✓` is the forgeable floor ([`84 §3.1`](183_how-much-does-this-lean-on-git.md))
rendered as an image — it fails gate 2 whenever the agent (or a harness it controls)
produces the frames. It climbs the spectrum only if the *capture* is on infrastructure
the agent cannot author (a separate session-recording service it cannot write to). And
reading a screen for meaning requires *interpretation* — a vision model — which leaves
gate 1's "ground-truth state" and enters taste/correctness. So a screenshare is a
**JUDGE** signal (advisory, fail-to-abstain — [`drivers/llm_judge`](../src/dos/drivers/llm_judge.py),
the ORACLE → JUDGE → HUMAN ladder of [`87`](87_the-adjudicator-trust-ladder.md)), never
a deterministic verdict. The highest risk on the list: it is the most natural way to
build belief wearing evidence's clothes.

### The ranking

1. **CI / Checks** — mid-spectrum, answers the *complete → correct* gap, domain-shaped
   → driver oracle. **Built (§5).**
2. **Infrastructure logs** (cloud audit, migration catalog) — same shape, same value
   tier; the next driver to write.
3. **Slack approval envelope** — narrow but the only fossil for "a human approved";
   driver oracle over the audit API, content ignored.
4. **Screenshare** — JUDGE input only; advisory, never trusted alone.

---

## 4. Three homes, one arrow (where each lands in the layering)

[`85 §2`](85_extending-the-verifiable-surface.md): "extend" is three moves, only one
touches the kernel. Mapped onto the live sources:

- **(A) A JUDGE, not a verdict** — the screenshare, the chat-sentiment read. Anything
  needing interpretation. Lives in a driver, advisory, fail-to-abstain. Never a verb.
- **(B) A driver oracle on the seam** — CI, infra logs, the Slack approval envelope.
  Each speaks a *specific system*, so each fails gate 3 (domain-free) and is a driver,
  exactly as [`llm_judge`](../src/dos/drivers/llm_judge.py) is. A repo with it wired
  gets a stronger verdict; one without **degrades honestly** to "no signal." **This is
  where almost every live source belongs**, and it is *possible today* — a host wiring
  job, not a missing kernel feature.
- **(C) A new kernel verb** — none of the live sources qualify, because all are tied to
  a provider (fail gate 3) or agent-authorable (fail gate 2). The verbs that *do*
  qualify read the git fossil or the run-id spine: scope-fidelity (shipped),
  acceptance, identity, journal-integrity.

All three obey the one-way arrow: **they import the kernel; the kernel never imports
them** (`tests/test_ci_status.py::test_kernel_does_not_import_this_driver` pins it for
the CI oracle, the same way the kernel's own litmus tests pin "kernel imports no host").

---

## 5. Worked example — the CI oracle, and running it on ourselves

[`drivers/ci_status.py`](../src/dos/drivers/ci_status.py) is the move-B reference,
built field-for-field in the kernel's own family so a host writing the next driver
(infra logs, Slack approvals) has a template, not a blank page.

**The two halves the kernel always splits:**

- **Boundary reader** `gather(sha, repo)` — mirrors [`git_delta`](../src/dos/git_delta.py):
  the subprocess (`gh api repos/<repo>/commits/<sha>/check-runs`) happens HERE, and
  **every** failure mode (no `gh`, unauthenticated, network/timeout, unknown SHA,
  malformed JSON) degrades to an honest `CiEvidence(reachable=False, detail=<why>)` —
  never a raise, never a propagated exception. The one guarded provider seam, the
  [`llm_judge._call_provider`](../src/dos/drivers/llm_judge.py) discipline.
- **Pure classifier** `classify(CiEvidence, CiPolicy) -> CiVerdict` — the
  [`verdict.py`](../src/dos/verdict.py) ABI: a closed enum, frozen caller-gathered
  evidence, a frozen `dos.toml [ci]`-shaped policy, an operator-facing `reason` naming
  the driving checks, a `to_dict()`. No I/O inside, so the whole verdict is
  replay-testable on frozen fixtures.

**The verdict ladder — four states, and the fourth is the honest part:**

```
GREEN      every gating check completed and none failed
RED        ≥1 gating check failed/errored/cancelled — a failure DOMINATES
PENDING    no failure, but ≥1 gating check is still running — not green YET, not red
NO_SIGNAL  no checks found, OR the provider was unreachable/unwired — ask a human
```

A binary green/red would have to *lie* about the two cases with no answer yet
(in-flight, unwired). Both are kept distinct so the verdict never claims more than the
evidence supports — typed-verdict-over-binary-gate applied to a source that is
legitimately sometimes silent. The ordering is conservative by construction: **RED
dominates** (one red required check reddens the commit regardless of how many passed),
**PENDING beats GREEN** (an unfinished check is never a pass), and an unreachable
provider is **always NO_SIGNAL, never a fabricated GREEN** — fail-safe, never fail-open,
the deterministic cousin of the judge's fail-to-abstain.

It sits *above* every git rung on the [`84 §4`](183_how-much-does-this-lean-on-git.md)
ladder, because its referent is more accountable than a subject the agent typed:

```
non-git oracle (CI green)            ← ci_status.CiVerdict — strongest "complete ≈ correct"
  registry stamp ⋈ git ancestry      ← oracle.ShipVerdict source="registry"
    distinctive file-path overlap     ← oracle grep rung, file backstop
      direct-ship subject match       ← oracle grep rung, subject
        source="none" / via=""        ← git history alone / could not confirm
```

### Using this pipeline on ourselves (the dog-food)

The substrate should consult the same green-build fossil it asks its users to trust.
`gather()` defaults `repo` to this project's own remote, so:

```bash
python -m dos.drivers.ci_status <sha>          # adjudicate DOS's own CI for a commit
python -m dos.drivers.ci_status <sha> --json   # the verdict + the checks behind it
```

Run live against a local-only commit it correctly reports `NO_SIGNAL` ("commit has no
CI, or none has reported yet") with exit code 3 — the honest floor, not a fabricated
pass. Against a pushed `master` commit it reports `GREEN`/`RED`/`PENDING` from the real
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) run. The exit-code map mirrors
`dos verify` so a gate can chain on it: `GREEN=0, RED=1, PENDING=2, NO_SIGNAL=3`.

The payoff is in the release tooling. The [`/release`](../.claude/skills/release/) and
[`/stable-release`](../.claude/skills/stable-release/) gates today shell `pytest -q`
**locally** — a self-report from the same machine cutting the release. Consulting
`ci_status.status_of(sha)` instead turns "the suite is green" into a **verified claim
against the third-party CI record**: the substrate stops believing its own local test
run for the one decision (promotion) where a silent local-vs-CI drift detonates as a
broken published wheel. That is move B pointed at DOS itself — the kernel eating the
exact distrust it sells.

---

## 6. What this note claims, and what it does not

- **Does claim:** the verdict machinery is source-agnostic (`classify(Evidence,
  Policy)`), so extending to a live source is an evidence-sourcing question settled by
  one test — *can the judged party author this byte?* (§1–2); the live sources land at
  very different points on the accountability spectrum, and that placement dictates
  driver-vs-judge-vs-nothing (§3–4); and the CI oracle is a built, tested, dog-fooded
  instance of the move-B pattern hosts copy (§5).
- **Does not claim:** that CI/logs/Slack belong *in* the kernel (they are drivers — they
  speak specific systems), that a screenshare can ground a deterministic verdict (it is
  a judge input), or that any of these reach total coverage (the flake floor of
  [`84 §2`](183_how-much-does-this-lean-on-git.md) still caps the payoff). A CI oracle on
  a CI system the agent administers is only as honest as the branch protection around it
  — the spectrum has no un-trusted bottom, only more-accountable referents.
- **The one-liner:** verifying a live source is choosing *whose word you relocate the
  trust to*. Pick a source the judged agent cannot author, render a typed verdict that
  degrades honestly when the source is silent, wire it as a driver — and point the first
  one at your own pipeline.

---

## References

*The machinery this reuses (§1, §5):*
- [`src/dos/verdict.py`](../src/dos/verdict.py) — the `classify(Evidence, Policy) ->
  Verdict` ABI the CI oracle conforms to (`TypedVerdict`).
- [`src/dos/liveness.py`](../src/dos/liveness.py), [`src/dos/scope.py`](../src/dos/scope.py)
  — the two prior pure-verdict instances the CI oracle is field-for-field analogous to.
- [`src/dos/git_delta.py`](../src/dos/git_delta.py) — the boundary-reader fail-safe
  pattern `gather()` follows.
- [`src/dos/drivers/llm_judge.py`](../src/dos/drivers/llm_judge.py) — the guarded
  provider-seam + advisory + one-way-import driver template; the CI oracle is its
  deterministic cousin.
- [`src/dos/drivers/ci_status.py`](../src/dos/drivers/ci_status.py) + `tests/test_ci_status.py`
  — the worked example this note specs.

*The frame (§2–§4):*
- [`183_how-much-does-this-lean-on-git.md`](183_how-much-does-this-lean-on-git.md) — git
  necessary-not-sufficient; the rung-ladder the CI oracle tops; the forgeable floor a
  screenshare re-creates as pixels.
- [`85_extending-the-verifiable-surface.md`](85_extending-the-verifiable-surface.md) —
  the accountability spectrum, the four-gate test, and the three homes this note applies
  to live sources.
- [`87_the-adjudicator-trust-ladder.md`](87_the-adjudicator-trust-ladder.md) — ORACLE →
  JUDGE → HUMAN; why a screenshare is a judge, not a verb.
- [`76_flexible-goals-and-verification.md`](76_flexible-goals-and-verification.md) — the
  give lives in provenance + which-signals, never the adjudication: new evidence enters
  as a rung/driver, the verdict stays mechanical.

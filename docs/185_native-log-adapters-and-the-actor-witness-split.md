# Native log adapters — and why a log is only evidence when the actor isn't the witness

> **An LLM already runs a program and reads its log. That loop is real, it is
> useful, and it produces *belief*, not verification — because the party that ran
> the program, chose what to surface, and summarized the output is the same party
> being judged. A log becomes *evidence* only at the moment the author of the bytes
> stops being the agent under adjudication: the kernel (not the agent) launched the
> process and read the OS exit code; or the bytes are an infrastructure fossil the
> agent cannot author (a cloud audit trail, a load-balancer log, a CI record). This
> note adds the log axis the way the kernel adds every axis — a tiny pure seam, many
> driver backends, the verdict mechanical — and it sorts every log source by the one
> test that matters: *who authored this byte?* The seductive, trivially-ingestible
> sources (a pasted terminal, the agent's own `screen` log, a screenshot) sit at the
> bottom of that order, not the top. Ease of ingestion is inversely correlated with
> trust, and a log-adapter feature that organizes itself by ease ships belief in
> evidence's clothes.**

This is the log-specific sequel to [`93`](93_verifying-live-non-git-sources.md) (the
accountability spectrum for non-git sources) and [`95`](95_os-level-evidence-and-the-proc-liveness-rung.md)
(local OS signals; file mtimes rejected, process-liveness accepted). Those notes
*placed* logs on the spectrum and ranked "infrastructure logs" as the highest-value
unbuilt driver — but they never went deep on the **adapter design itself**: the
ladder from a copy-pasted terminal to CloudWatch, what shape a `LogSource` takes,
and the trap a naive "add native log adapters" feature falls into. This note does
that, motivated by the one objection that decides whether the whole axis is worth
anything (§1), informed by what a legacy log-inspection system (netra-apex) actually
did (§3), and it ships the smallest honest slice: a pure `LogSource` seam +
`LogEvidence` value + one deliberately-floored driver (§6–7).

It is a theory + spec + skeleton note in the family of
[`82`](182_the-kernel-is-a-taxonomy-of-refusal.md),
[`85`](85_extending-the-verifiable-surface.md),
[`93`](93_verifying-live-non-git-sources.md),
[`95`](95_os-level-evidence-and-the-proc-liveness-rung.md). Unlike the pure-theory
ones it ships code: `src/dos/log_source.py` (the pure seam) and
`src/dos/drivers/paste_log.py` (the worked move-B/floor example).

---

## 1. The objection that motivates the whole note: "an LLM already reads logs"

The first reaction to "native log adapters for a *verification* substrate" is
correct and fatal if unanswered:

> An agent already runs the build and reads the output. It already tails the server
> log and sees the stack trace. Reading logs is table stakes — what does routing
> them through DOS add?

The answer is the entire thesis of the kernel, restated for one input. When an
**agent** runs a program and reads its log, the agent is simultaneously **the actor
and the witness**. It chose the command, it decided which lines to surface, it wrote
the summary ("tests passed, shipping"). The log it shows you is downstream of every
one of those choices. `INFO: deployed successfully` in a logger the agent's own
process emitted is `git commit --allow-empty -m "deployed"` rendered in a different
font ([`93 §3`](93_verifying-live-non-git-sources.md)). It is the **forgeable floor**
([`84 §3.1`](183_how-much-does-this-lean-on-git.md)) — not because the agent is
lying, but because nothing structurally *prevents* the log from diverging from
ground truth, and the kernel's whole stance is to distrust exactly the reports that
nothing prevents from diverging ([`103`](103_memory-is-an-unverified-agent.md), the
distrust-the-self-report law).

So "an LLM reads the log" produces **belief**. DOS's contribution is not to read the
log *better* — a frontier model already reads it better than any regex. DOS's
contribution is to change *who authored the bytes the verdict rests on*. There are
exactly three ways a log stops being a self-report, and they are the spine of this
note:

1. **The kernel runs the program, not the agent.** When a *DOS-supervised* process
   is launched by the kernel and the kernel reads the **OS-recorded exit code** and
   captures the stream, the agent did not author the "the tests ran and exited 0"
   fact — the OS did. That is the **acceptance** verb the distrust-map and
   [`95 §6`](95_os-level-evidence-and-the-proc-liveness-rung.md) flag as unbuilt, and
   it is the single highest-value target on this whole axis (§5). The difference
   from "the agent ran the tests and says they passed" is not subtle: it is the
   difference between `subprocess` output the referee captured and a sentence the
   subject typed.
2. **The bytes are an infrastructure fossil the agent cannot author.** A cloud
   provider's audit trail, a load-balancer access log, a database migration catalog,
   a CI build record — written by infrastructure the agent under adjudication does
   not control. Mid-to-high on the [`93 §2`](93_verifying-live-non-git-sources.md)
   spectrum, a **driver oracle** (§4). The agent can no more forge a CloudWatch
   entry on an account it can't write than it can forge a reachable commit object.
3. **Everything else is a JUDGE input, never a verdict.** The agent's own stdout, a
   pasted terminal buffer, a `screen`/`tmux` scrollback, a screenshot of a passing
   test run — these *are* the loop the objection describes. They are not worthless:
   handed to a model as a *hint*, they can rule on the residue the deterministic
   oracle abstained on. But that is the **JUDGE rung** ([`87`](87_the-adjudicator-trust-ladder.md),
   [`judges.py`](../src/dos/judges.py)) — advisory, fail-to-abstain, hedged by four
   disciplines and scored by [`judge_eval`](../src/dos/judge_eval.py) — and naming it
   as such is the contribution. The slop move is to let the log-reading loop
   masquerade as ground truth; the kernel move is to *give it the correct, lower
   rung* and a verdict that degrades honestly when it can't tell.

> **The one-liner.** "An LLM reads a log" is the JUDGE rung with no fence around it.
> This note keeps that rung (it is genuinely useful) but fences it, and adds the two
> rungs above it where the *author of the byte is not the agent* — the kernel that
> launched the process, and the infrastructure that wrote the fossil. The value is
> not better reading; it is **separating the actor from the witness**.

---

## 2. The inversion law: ease of ingestion is anti-correlated with trust

The natural way to build "native log adapters" is to sort by *how easy the source is
to get*: start with copy-paste (zero integration), then `screen` logs (a file on
disk), then journald (a CLI), then cloud logs (an API + auth). That ordering is a
trap, because it is **almost exactly the reverse of the trust ordering**.

| Source | Ingestion effort | Who authored the bytes | Trust rung |
|---|---|---|---|
| Copy-paste a terminal buffer into the prompt | ~0 | the agent (it chose what to paste) | **floor** — JUDGE hint only |
| The agent's own `screen`/`tmux` scrollback | trivial (read a file) | the agent (its own process wrote it) | **floor** — JUDGE hint only |
| A screenshot of "tests passed ✓" | trivial | the agent (it rendered the frame) | **floor** — JUDGE hint only |
| A local app log file the agent's process writes | easy (tail a file) | the agent's process | **floor** — JUDGE hint only |
| Kernel-launched process: OS exit code + captured stream | moderate (the kernel runs it) | **the OS / the kernel** | **mid-high** — an oracle (acceptance) |
| `systemd-journald` / Windows Event Log for a tree the agent can't write | moderate (a CLI + privilege) | **the OS**, root-gated | **high** — a driver oracle |
| Cloud audit log / LB access log / CI record | hard (API + auth + parsing) | **third-party infra** | **mid-high → high** — a driver oracle |

Read top to bottom: effort rises, and trust rises *with* it, because the thing that
makes a source hard to ingest — it lives on infrastructure you don't control, behind
an API, written by a party that isn't you — is the *same* thing that makes its bytes
unforgeable by the agent. The easy sources are easy precisely because the agent
already has them in hand, which is exactly why they are worthless as ground truth.

> **The law:** *a log's ingestion-ease is inversely proportional to its evidentiary
> value, because both are governed by the same variable — proximity to the agent.*
> A log adapter framework must therefore be organized by the
> [`93 §2`](93_verifying-live-non-git-sources.md) accountability spectrum (who
> authored the byte), **never** by ingestion convenience. The convenient sources
> still get adapters — but they are wired to the JUDGE rung with the fence on, and
> the framework's *shape* makes that routing the path of least resistance, so a host
> cannot accidentally promote a pasted log into a verdict.

This is the [`95`](95_os-level-evidence-and-the-proc-liveness-rung.md) file-mtime
result generalized: an mtime *feels* like the OS vouching for the file, but the agent
caused every write, so it is `heartbeat_at`, not `ts`. A pasted log feels like
evidence because it is real text from a real run — but the agent chose every byte
that reached the prompt, so it is the same forgeable floor.

---

## 3. What netra-apex did, and the one move worth lifting

A legacy log-inspection system in this lineage (netra-apex) did what every log
analytics engine does: **tail many heterogeneous sources, run a rule/regex/pattern
set over the stream, classify lines, and emit alerts/rollups.** The valuable
engineering there was the *adapter layer* — a uniform way to pull lines from a dozen
shapes of source (files, sockets, journald, cloud APIs) and normalize them into a
common record — plus the *rule engine* that matched patterns and raised typed
findings.

Run that whole design through the kernel's one test and it splits cleanly:

- **The pattern/rule/classify engine is a JUDGE.** "This line matches `ERROR.*OOM`
  → raise a memory-pressure finding" is *interpretation of forgeable text*. In a
  monitoring product that is the entire value. In a *verification substrate* it is a
  JUDGE input ([`93 §3`](93_verifying-live-non-git-sources.md), screenshare row): it
  leaves gate 1's "ground-truth state" and enters taste/heuristic, so it is advisory,
  fail-to-abstain, never a deterministic verdict. apex's rules become a
  [`drivers/llm_judge`](../src/dos/drivers/llm_judge.py)-style adjudicator (or a
  cheaper deterministic-pattern judge) that *rules on residue*, scored by
  [`judge_eval`](../src/dos/judge_eval.py) for false-clear rate like any judge.
- **The "watch the infra audit log" path is a driver oracle.** Where apex tailed a
  *third-party, agent-unwriteable* log (a cloud trail, a privileged journald tree),
  the same reader is a [`93 §4`](93_verifying-live-non-git-sources.md) move-B driver
  oracle — boundary reader pulls the record, a pure classifier renders a typed
  verdict that degrades to `NO_SIGNAL`.
- **The adapter abstraction is the lift.** The one piece worth taking wholesale is
  apex's *uniform source adapter* — the "many backends, one record shape" layer. DOS
  needs exactly that, but as a **pure seam** ([`judges.py`](../src/dos/judges.py) /
  [`overlap_policy.py`](../src/dos/overlap_policy.py) shape): a `LogSource` Protocol +
  a frozen `LogEvidence` record + a by-name resolver over an entry-point group, with
  every backend a driver. We lift the *abstraction*, not the *trust posture*: apex
  treated every source as equally actionable; DOS tags each source with where it sits
  on the spectrum, and the tag decides JUDGE-input vs oracle.

So the apex lesson is: **build the adapter layer; do not inherit the assumption that
a matched log line is an actionable fact.** A matched line is a *judge's hint* unless
the bytes are infra-authored, in which case it is an *oracle's evidence*. The adapter
is domain-free plumbing; the trust rung is a property of the *source*, carried as
data.

---

## 4. The shape — a pure `LogSource` seam, many driver backends

The kernel already proved this exact shape three times: `judges` (a `Judge` Protocol
+ resolver, ruling judges in drivers), `overlap_policy` (an `OverlapPolicy` Protocol
+ floor, model scorers in drivers), `render`/`admission` (pure protocol + resolver,
implementations outside). The log axis is the fourth instance.

```python
# log_source.py — the pure seam (sketch; §6 is the shipped version)

class Accountability(str, enum.Enum):
    """Where a source sits on the docs/93 spectrum — carried as DATA, not inferred.
    This tag is what makes the inversion law (§2) structural: a consumer routes by
    the tag, so an AGENT_AUTHORED source can never reach the oracle path."""
    AGENT_AUTHORED = "AGENT_AUTHORED"  # the floor — JUDGE hint only (paste, own stdout)
    OS_RECORDED    = "OS_RECORDED"     # the OS authored it (exit code, privileged journald)
    THIRD_PARTY    = "THIRD_PARTY"     # infra the agent can't write (cloud trail, CI, LB log)

@dataclass(frozen=True)
class LogEvidence:
    """Frozen, caller-gathered log facts — the verdict ABI's Evidence, for logs.
    `lines` is the pulled text; `accountability` is the source's spectrum tag;
    `reachable` is False for every degrade (no source, auth fail, timeout) so an
    absent log reads as NO_SIGNAL, never a fabricated pass."""
    source_name: str
    accountability: Accountability
    lines: tuple[str, ...] = ()
    reachable: bool = False
    detail: str = ""

@runtime_checkable
class LogSource(Protocol):
    """The contract a backend implements: pull recent lines for a subject.
    MAY do I/O inside `gather` (read a file, call an API) — that is why every real
    backend is a DRIVER, outside the kernel boundary, exactly like a ruling Judge."""
    name: str
    accountability: Accountability
    def gather(self, subject: str, config: object) -> LogEvidence: ...
```

The disciplines, lifted verbatim from `judges`:

- **The seam is pure; every backend is a driver.** `log_source.py` holds the
  Protocol, the `LogEvidence`/`Accountability` value types, an unshadowable built-in
  `NullLogSource` (the honest zero — always `reachable=False`, the `text`-renderer /
  `AbstainJudge` analogue), a by-name resolver over the `dos.log_sources` entry-point
  group, and a **fail-safe runner** `gather_log` that converts any raise / wrong
  return type into an unreachable `NO_SIGNAL` `LogEvidence`. It names no host, has no
  provider surface, does no I/O inside a verdict. Backends — file-tail, paste,
  journald, CloudWatch — live in `drivers/*`, import the kernel, and the kernel never
  imports them (the `drivers/__init__` litmus, pinned by a test).
- **`accountability` is carried as data, never inferred.** A source *declares* its
  rung. This is the [`76`](76_flexible-goals-and-verification.md) line held exactly:
  the flexibility lives in the provenance tag (a which-signal), the *adjudication*
  (JUDGE-vs-oracle routing) is a fixed function of the tag. A consumer does
  `if ev.accountability is AGENT_AUTHORED: feed_a_judge(ev) else: classify_as_oracle(ev)`
  — so the inversion law is structural, not a convention a host must remember.
- **Fail-safe, never fail-open.** No source reachable → `LogEvidence(reachable=False)`
  → the consuming verdict is `NO_SIGNAL`/abstain, never a fabricated GREEN/AGREE. The
  `ci_status` / `run_judge` discipline, restated for logs.

This is the [`93 §4`](93_verifying-live-non-git-sources.md) "three homes, one arrow"
applied: the *abstraction* is a tiny kernel seam (it is domain-free), every *backend*
is a driver (each speaks a specific source), and the agent-authored ones route to a
judge (interpretation).

---

## 5. The prize: kernel-launched acceptance (the rung that escapes the loop)

§1 said the highest-value target is the one log source whose bytes the agent did not
author: a **kernel-launched** process's OS-recorded exit code and captured stream.
This is the **acceptance** verb ([`93 §4`](93_verifying-live-non-git-sources.md) move
C / [`95 §6`](95_os-level-evidence-and-the-proc-liveness-rung.md)) — "done means
done," answered by structured, unforgeable evidence instead of the summary line
`verify` currently believes.

The design, kept honest by the disciplines from the distrust-map:

- **The kernel runs the command; the agent does not.** A host declares an acceptance
  command (`pytest -q`, `make check`) in `dos.toml`; DOS launches it via `subprocess`,
  captures stdout/stderr and the **exit code the OS set**, and stamps a
  `LogEvidence(accountability=OS_RECORDED, …)`. The agent cannot author the exit
  status — that is the whole point, and the precise difference from "the agent ran the
  tests and pasted the output."
- **Never re-do the work as a side effect.** The distrust-map's load-bearing
  discipline: acceptance *captures* a kernel-run, it does not silently re-run an
  agent's build to "check." The command is the host's declared gate, run once, its
  result recorded — not a second opinion the kernel manufactures.
- **A typed verdict that degrades honestly.** `ACCEPTED` (exit 0, gate ran),
  `REJECTED` (non-zero), `NO_SIGNAL` (no command declared / the launch itself failed
  — distinct from a test failure, the `ci_status` four-state honesty). It sits *above*
  the git rungs and *beside* the CI oracle on the [`84 §4`](183_how-much-does-this-lean-on-git.md)
  ladder: CI is "green on third-party infra," acceptance is "green under the kernel's
  own launch," both more accountable than a subject the agent typed.
- **Advisory, like every non-arbiter verdict.** It reports `REJECTED`; it does not
  revert a commit. A host MAY gate on it (an `AcceptancePredicate` over the arbiter's
  conjunctive seam, or a `REJECTED` row in `dos decisions`) — but the acceptance
  verdict and the admission decision stay different syscalls, the
  `liveness`/SPINNING line.

Acceptance is specced here, not built in this pass (it is a verb with real blast
radius and deserves its own focused session). It is named now because it is *the*
answer to §1: it is the log source that is genuinely not a self-report, and the seam
in §4 is the abstraction it will plug into (`accountability=OS_RECORDED`).

---

## 6. The adapter ladder — every source, placed and routed

Concrete backends, easiest-to-hardest (the §2 ingestion axis), each tagged with its
rung (the trust axis) and its home. The point of listing them on the *ease* axis is
to show how consistently it runs *against* the trust axis.

| # | Backend (driver) | Ingestion | `accountability` | Home / routing |
|---|---|---|---|---|
| 1 | **`paste_log`** — text the operator pastes / passes via `--paste` / stdin | ~0 | `AGENT_AUTHORED` | JUDGE input only. The §7 worked example, **deliberately the floor** — it exists to demonstrate the fence, not to be trusted. |
| 2 | **`screen_log`** — read a `screen -L` / `tmux capture-pane` scrollback file | trivial | `AGENT_AUTHORED` | JUDGE input only. The agent's own session output — convenient, forgeable. |
| 3 | **`file_tail`** — tail an arbitrary local log file | easy | `AGENT_AUTHORED` by default (the agent's process likely wrote it); a host may re-tag a file it *knows* is written by an unprivileged-to-the-agent daemon | JUDGE input by default; oracle only on an explicit host re-tag (with the burden on the host to justify the rung). |
| 4 | **`journald` / `eventlog`** — `journalctl -u <unit>` / Windows Event Log for a unit the agent can't write | moderate (CLI + privilege) | `OS_RECORDED` | Driver oracle. The OS authored it, root-gated; the [`95 §6`](95_os-level-evidence-and-the-proc-liveness-rung.md) heavy-tier source. |
| 5 | **`acceptance`** — kernel-launched command, OS exit code + stream | moderate (kernel runs it) | `OS_RECORDED` | The §5 prize — an oracle/verb. The one that escapes the §1 loop. |
| 6 | **`cloudwatch` / `gcp_logging` / `datadog`** — pull a log group/stream via the provider API | hard (API + auth + paging + parse) | `THIRD_PARTY` | Driver oracle. Infra the agent can't author; the [`93`](93_verifying-live-non-git-sources.md) #2-ranked highest-value oracle. |
| 7 | **`lb_access` / `audit_trail`** — a load-balancer access log / cloud audit trail proving a request was served / an action occurred | hard | `THIRD_PARTY` | Driver oracle. The fossil for "the deploy actually served traffic," which git can never leave. |

Two things this table makes unmissable:

1. **Rows 1–3 (the easy ones) are all `AGENT_AUTHORED` → all JUDGE-only.** The entire
   bottom of the ingestion ladder is the forgeable floor. A framework that led with
   "we support copy-paste and screen logs!" would be advertising its least
   trustworthy rung as a headline feature — the §2 trap, made concrete.
2. **Rows 4–7 (the hard ones) are where verdicts come from.** And the hardest of all
   (cloud) is the single highest-value oracle, because deploys/migrations/served-traffic
   leave *only* this fossil. The work is front-loaded onto exactly the sources the
   easy-first instinct defers.

The build order therefore *inverts* the ease ladder: ship the seam + the floor
example first (to nail the fence and the shape), then climb to the OS_RECORDED and
THIRD_PARTY oracles where the value is.

---

## 7. What ships in this pass (the skeleton)

The smallest slice that proves the shape and the fence, no more:

1. **`src/dos/log_source.py`** — the pure seam (§4): `Accountability` enum,
   `LogEvidence` frozen value, `LogSource` Protocol, the unshadowable `NullLogSource`
   built-in, the `dos.log_sources` entry-point resolver, and the `gather_log`
   fail-safe runner (any raise / wrong type → unreachable `NO_SIGNAL`). Pure stdlib,
   no host, no provider surface, no I/O inside a verdict.
2. **`src/dos/drivers/paste_log.py`** — the worked move-B example and the
   *deliberate floor* (row 1): a `LogSource` that wraps operator-supplied text, hard-
   tagged `AGENT_AUTHORED`, with a docstring that says in plain words *this is not a
   verdict source — it is a judge hint, and here is why.* It imports the kernel; the
   kernel never imports it.
3. **`tests/test_log_source.py`** — pins: the Protocol round-trips; `gather_log`
   converts a raising source and a wrong-return-type source to unreachable
   `NO_SIGNAL` (fail-safe); the resolver finds built-ins first and an unknown name
   fails loud; the `paste_log` driver is `AGENT_AUTHORED`; and the litmus that **the
   kernel imports no log driver** (`import dos.drivers` absent under `src/dos/` except
   `drivers/`), the log analogue of "kernel imports no host."

What does **not** ship this pass, and why: the `journald`/`cloudwatch` oracles and
the `acceptance` verb (§5) are real I/O against real systems / a verb with admission
blast radius — each is its own session, and shipping a stub would violate the
honesty the note argues for. The seam is the contract they will plug into; the floor
example proves the fence holds.

---

## 8. The litmus tests (each enforced by a test or trivially checkable)

- **The actor is not the witness.** The seam carries an `accountability` tag and the
  routing is a fixed function of it; a test asserts an `AGENT_AUTHORED` source's
  evidence is never consumed by an oracle-classifier path in the shipped wiring (the
  §1 separation, made structural).
- **Ease never promotes trust.** `paste_log` (zero-effort ingestion) is hard-tagged
  `AGENT_AUTHORED` and cannot be constructed at a higher rung — the §2 inversion law,
  pinned by a test that the driver's `accountability` is fixed.
- **Fail-safe, never fail-open.** `gather_log` converts every failure (raise, wrong
  return type, unreachable source) to `LogEvidence(reachable=False)` → `NO_SIGNAL`,
  never a fabricated reachable log — the `ci_status`/`run_judge` discipline.
- **The seam is pure; backends are drivers.** No `subprocess`/network/`open()` inside
  `log_source.py`; every backend lives under `drivers/`. Grep-checkable.
- **The kernel imports no log driver.** No module under `src/dos/` (except
  `drivers/`) imports `dos.drivers.paste_log` or any log backend — the log analogue of
  the kernel-imports-no-host litmus, pinned by `tests/test_log_source.py`.
- **Degrades with no source at all** (the [`test_verify_no_plan`](../tests/test_verify_no_plan.py)
  sibling): `gather_log` with no source wired returns a `NullLogSource`-shaped
  unreachable evidence, so a consumer always gets a verdict, never a crash.

---

## 9. What this note claims, and what it does not

- **Does claim:** the value of routing logs through DOS is not better reading (a
  model already reads better than a regex) but **separating the actor from the
  witness** (§1) — the kernel running the program, or an infra-authored fossil, in
  place of the agent's self-report; that ingestion-ease is *anti-correlated* with
  trust, so a log-adapter framework must be organized by the accountability spectrum,
  not convenience (§2); that the apex pattern-engine is a JUDGE and only its
  infra-log path is an oracle, with the adapter abstraction the one piece worth
  lifting (§3); and that the shape is the proven pure-seam-many-drivers one (§4),
  with kernel-launched acceptance the prize (§5).
- **Does not claim:** that the easy sources are useless (they are real JUDGE hints —
  fenced, not discarded); that logs belong *in* the kernel (the abstraction is a tiny
  seam, every backend is a driver); that a pasted/own-stdout log can ever ground a
  deterministic verdict (it is the forgeable floor by construction); or that this
  pass ships the oracles (it ships the seam + the fence + the floor example, and
  specs the rest). The flake floor of [`84 §2`](183_how-much-does-this-lean-on-git.md)
  still caps the payoff; an oracle on a system the agent administers is only as honest
  as the access control around it — the spectrum has no un-trusted bottom, only
  more-accountable referents.
- **The one-liner:** an LLM reading a log is the JUDGE rung with the fence off;
  native log adapters, done right, keep that rung but fence it, and add the rungs
  above it where *the agent did not author the byte* — and the sources easiest to
  ingest are the ones that fence buys you the least from, so build by accountability,
  not by ease.

---

## References

*The machinery this reuses (§4):*
- [`src/dos/judges.py`](../src/dos/judges.py) — the pure-seam template: a Protocol +
  frozen value types + unshadowable built-in + entry-point resolver + fail-safe
  runner; `log_source` is field-for-field analogous, with `gather_log` the `run_judge`
  fail-safe analogue.
- [`src/dos/overlap_policy.py`](../src/dos/overlap_policy.py) — the other recent
  instance of "pure seam in the kernel, ruling implementations in drivers, a
  deterministic floor under any plugin."
- [`src/dos/drivers/ci_status.py`](../src/dos/drivers/ci_status.py) — the move-B
  boundary-reader + pure-classifier + four-state honest verdict the oracle backends
  (journald/cloud/acceptance) will copy.
- [`src/dos/verdict.py`](../src/dos/verdict.py) — the `classify(Evidence, Policy) ->
  Verdict` ABI; `LogEvidence` is the Evidence half for logs.

*The frame (§1–§3, §5):*
- [`93_verifying-live-non-git-sources.md`](93_verifying-live-non-git-sources.md) — the
  accountability spectrum + the "who authored this byte?" gate-2 test this note
  applies to logs specifically; the logs-split-down-the-middle placement (§3) and the
  infra-logs #2 ranking this note's ladder (§6) makes concrete.
- [`95_os-level-evidence-and-the-proc-liveness-rung.md`](95_os-level-evidence-and-the-proc-liveness-rung.md)
  — the file-mtime rejection (the inversion law's ancestor: OS-flavored ≠ unforgeable)
  and the heavy-tier OS-audit-log / acceptance sources this note routes.
- [`183_how-much-does-this-lean-on-git.md`](183_how-much-does-this-lean-on-git.md) — git
  necessary-not-sufficient; the forgeable floor a pasted log re-creates; the rung
  ladder acceptance/CI sit atop.
- [`87_the-adjudicator-trust-ladder.md`](87_the-adjudicator-trust-ladder.md) — ORACLE
  → JUDGE → HUMAN; why a pattern-matched log line is a judge, not a verb.
- [`76_flexible-goals-and-verification.md`](76_flexible-goals-and-verification.md) —
  the give lives in provenance + which-signals, never the adjudication: the
  `accountability` tag is a which-signal; the JUDGE-vs-oracle routing is fixed.
- [`103_memory-is-an-unverified-agent.md`](103_memory-is-an-unverified-agent.md) — the
  distrust-the-self-report law a pasted log violates and the kernel-run capture
  restores.
